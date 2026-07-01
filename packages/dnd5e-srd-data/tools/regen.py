"""Top-level translator + audit runner.

Run: `make regen` after `make refresh-upstream` populates raw_sources/.

Emits to:
- src/dnd5e_srd_data/canonical/<category>/<slug>.json
- audit/{validation_report,requires_review,non_srd_excluded}.json
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from tools.audit.cross_check import (
    diff_class_flat_fields,
    diff_item_flat_fields,
    diff_monster_flat_fields,
    diff_species_flat_fields,
    diff_spell_flat_fields,
    diff_subclass_flat_fields,
)
from tools.translators.foundry import (
    translate_armor_yaml,
    translate_background_yaml,
    translate_class_yaml,
    translate_feat_yaml,
    translate_feature_yaml,
    translate_generic_item_yaml,
    translate_monster_yaml,
    translate_species_yaml,
    translate_spell_yaml,
    translate_subclass_yaml,
    translate_weapon_yaml,
    write_canonical_with_overrides,
)
from tools.translators.srd_gate import (
    GateDecision,
    SrdSourceVerdict,
    gate_decision,
)

ROOT = Path(__file__).resolve().parent.parent
FOUNDRY_PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
CANONICAL = ROOT / "src" / "dnd5e_srd_data" / "canonical"
AUDIT = ROOT / "audit"
INGEST_VERSION = "foundry-translator-v1"

# Grant targets that legitimately have no canonical entry (audited 2026-06-04).
# Each entry MUST have a reason. A grant UUID absent from the index AND from this
# allowlist is a hard regen failure (catches real omissions; no silent drops).
#
# These are referenced by class/subclass advancement in Foundry's data but have
# no SRD-eligible type:feat source doc to grant. The six phbfst* fighting styles
# (Blind Fighting, Dueling, Interception, Protection, Thrown Weapon Fighting,
# Unarmed Fighting) ship no source YAML in the CC-BY SRD packs at all — only the
# four SRD styles (Archery, Defense, Great Weapon Fighting, Two-Weapon Fighting)
# are present, and those resolve normally. The two unarmed-strike targets are
# type:weapon (not features); phbmnkUnarmedStr additionally carries no license.
_KNOWN_UNRESOLVABLE_GRANTS: dict[str, str] = {
    "Compendium.dnd5e.classes24.Item.phbmnkSelfrestor": (
        "Monk Self-Restoration: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.classes24.Item.phbmnkUnarmedStr": (
        "Monk Unarmed Strike: type:weapon (non-feature) and no CC-BY license"
    ),
    "Compendium.dnd5e.equipment24.Item.phbUnarmedStrike": (
        "Unarmed Strike: type:weapon (non-feature) and no CC-BY license"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstBlindFight": (
        "Blind Fighting style: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstDueling000": (
        "Dueling style: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstIntercepti": (
        "Interception style: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstProtection": (
        "Protection style: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstThrownWeap": (
        "Thrown Weapon Fighting style: no source doc in SRD packs (non-SRD)"
    ),
    "Compendium.dnd5e.feats24.Item.phbfstUnarmedFig": (
        "Unarmed Fighting style: no source doc in SRD packs (non-SRD)"
    ),
}


def _gate_for_yaml(yaml_path: Path) -> GateDecision:
    """Three-source SRD agreement. In Phase 7a PR 1 we approximate this as
    Foundry-only: the real Foundry pack tags SRD content via
    ``system.source.license == 'CC-BY-4.0'`` AND
    ``system.source.rules in ('2014', '2024')`` (CC-BY-4.0 covers both the 5.1
    and the active 5.2 / 2024 SRD releases). 2024 is the active edition; 2014 is
    still admitted for back-compat. The minimal fixture uses the legacy
    ``flags.srd: true`` marker, so we accept either signal.

    open5e + five_e_bits cross-checks layer in PR 2 or as a follow-up.
    """
    import yaml

    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    flags_srd = bool(doc.get("flags", {}).get("srd"))
    source = (doc.get("system") or {}).get("source") or {}
    license_srd = (source.get("license") or "") == "CC-BY-4.0" and (source.get("rules") or "") in (
        "2014",
        "2024",
    )
    foundry_srd = flags_srd or license_srd
    return gate_decision(
        SrdSourceVerdict(
            foundry_srd=foundry_srd,
            open5e_srd=foundry_srd,  # PR 1 approximation
            five_e_bits_srd=foundry_srd,
        )
    )


def _run_category(
    pack_subdir: str,
    canonical_subdir: str,
    translator,
    ingest_date: date,
    expected_doc_type: str | tuple[str, ...],
) -> tuple[int, int, list[dict]]:
    src = FOUNDRY_PACKS / pack_subdir
    dst = CANONICAL / canonical_subdir
    dst.mkdir(parents=True, exist_ok=True)
    excluded: list[dict] = []
    accepted = 0
    quarantined = 0
    # Real packs nest by subtype (items/weapon/longsword.yml AND
    # items/weapon/martial-melee/... in 2024 layout). Walk recursively.
    yaml_paths = sorted(src.rglob("*.yml")) if src.is_dir() else []
    for yaml_path in yaml_paths:
        # Only the directory-metadata document is excluded. Real SRD docs in
        # items/container/<slug>/_container.yml carry leading underscores and
        # must be translated.
        if yaml_path.name == "_folder.yml":
            continue
        import yaml as _yaml

        try:
            doc = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001  # malformed YAML → quarantine
            quarantined += 1
            excluded.append(
                {
                    "slug": yaml_path.stem,
                    "path": str(yaml_path.relative_to(ROOT)),
                    "reason": f"yaml_parse_error:{exc.__class__.__name__}",
                }
            )
            continue
        expected_types = (
            (expected_doc_type,) if isinstance(expected_doc_type, str) else expected_doc_type
        )
        if not isinstance(doc, dict) or doc.get("type") not in expected_types:
            quarantined += 1
            found_type = doc.get("type") if isinstance(doc, dict) else "not_a_dict"
            excluded.append(
                {
                    "slug": yaml_path.stem,
                    "path": str(yaml_path.relative_to(ROOT)),
                    "reason": f"wrong_doc_type:{found_type}",
                }
            )
            continue
        decision = _gate_for_yaml(yaml_path)
        if not decision.is_srd:
            quarantined += 1
            excluded.append(
                {
                    "slug": yaml_path.stem,
                    "path": str(yaml_path.relative_to(ROOT)),
                    "reason": decision.quarantine_reason,
                }
            )
            continue
        # Dispatch by doc["type"] when the per-subdir bucket can mis-classify.
        # Foundry stores e.g. spellcasting-focus/staff.yml as type: weapon — it
        # belongs to the weapon translator regardless of pack subdir. Same for
        # equipment with armor data → armor translator. Without this override,
        # such entries lose all mechanical fields (damage parts, AC).
        doc_type = doc.get("type")
        effective_translator = translator
        if translator is translate_generic_item_yaml:
            if doc_type == "weapon":
                effective_translator = translate_weapon_yaml
            elif doc_type == "equipment" and (
                ((doc.get("system") or {}).get("armor") or {}).get("value")
            ):
                effective_translator = translate_armor_yaml
        try:
            entity = effective_translator(
                yaml_path=yaml_path,
                ingest_date=ingest_date,
                ingest_version=INGEST_VERSION,
            )
        except Exception as exc:  # noqa: BLE001  # translator crash → quarantine
            quarantined += 1
            excluded.append(
                {
                    "slug": yaml_path.stem,
                    "path": str(yaml_path.relative_to(ROOT)),
                    "reason": f"translator_error:{exc.__class__.__name__}:{exc}",
                }
            )
            continue
        write_canonical_with_overrides(entity, dst)
        accepted += 1
    return accepted, quarantined, excluded


def _pinned_ingest_date() -> date:
    """Read the Foundry pinned date from PINS.json. Foundry is the canonical
    source in PR 1, so its ``pinned_date`` is the authoritative ingest
    timestamp. Sourcing from PINS makes regen deterministic — same pins
    produce the same canonical bytes regardless of calendar day."""
    pins_path = ROOT / "raw_sources" / "PINS.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    return date.fromisoformat(pins["foundry"]["pinned_date"])


def _prune_stale_canonical() -> None:
    """Remove stale ``canonical/<subdir>/*.json`` entries before regen so
    slugs that dropped from upstream or started being quarantined don't
    linger. Reviewer-override entries (``review.known_divergence != null``)
    survive the prune — ``write_canonical_with_overrides`` preserves them
    on rewrite. Pruning is done ONCE per canonical subdir at the top of
    ``main()`` because both weapons and armor write into ``canonical/items/``
    and prune-per-category would delete the prior category's output."""
    for canonical_subdir in (
        "items",
        "monsters",
        "spells",
        "species",
        "classes",
        "subclasses",
        "backgrounds",
        "feats",
        "features",
    ):
        dst = CANONICAL / canonical_subdir
        if not dst.is_dir():
            continue
        for stale in dst.glob("*.json"):
            try:
                blob = json.loads(stale.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                blob = {}
            if (blob.get("review") or {}).get("known_divergence"):
                continue
            stale.unlink()


def main() -> int:
    ingest_date = _pinned_ingest_date()
    AUDIT.mkdir(exist_ok=True)
    _prune_stale_canonical()
    non_srd_excluded: list[dict] = []

    # 2024 ``equipment24`` nests weapons/ (by category) and armor/ at the top,
    # plus generic item subdirs (adventuring-gear, consumables, containers,
    # equipment, supplemental, tools, traps). _run_category's rglob recurses
    # each subtree.
    print("[regen] weapons …")
    a, q, e = _run_category(
        "equipment24/weapons", "items", translate_weapon_yaml, ingest_date, "weapon"
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] armor …")
    a, q, e = _run_category(
        "equipment24/armor", "items", translate_armor_yaml, ingest_date, "equipment"
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    # Non-weapon, non-armor item packs. The generic translator re-routes
    # type:weapon → weapon translator and type:equipment-with-armor → armor
    # translator (see _run_category dispatch), so weapons/armor embedded in
    # these subdirs still get full mechanical fields.
    generic_item_subdirs = (
        "adventuring-gear",
        "consumables",
        "containers",
        "equipment",
        "supplemental",
        "tools",
        "traps",
    )
    # Real Foundry ships heterogeneous ``type:`` values across these packs
    # (consumable, equipment, loot, tool, Item, weapon). Accept the full set
    # so the generic translator sees every SRD-marked entry.
    generic_doc_types = (
        "Item",
        "consumable",
        "container",
        "equipment",
        "loot",
        "tool",
        "weapon",
    )
    for subdir in generic_item_subdirs:
        src_dir = FOUNDRY_PACKS / "equipment24" / subdir
        if not src_dir.is_dir():
            continue
        print(f"[regen] equipment24/{subdir} …")
        a, q, e = _run_category(
            f"equipment24/{subdir}",
            "items",
            translate_generic_item_yaml,
            ingest_date,
            generic_doc_types,
        )
        non_srd_excluded.extend(e)
        print(f"  accepted={a}, quarantined={q}")

    print("[regen] monsters …")
    a, q, e = _run_category("actors24", "monsters", translate_monster_yaml, ingest_date, "npc")
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] spells …")
    a, q, e = _run_category("spells24", "spells", translate_spell_yaml, ingest_date, "spell")
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] species …")
    a, q, e = _run_category(
        "origins24/species", "species", translate_species_yaml, ingest_date, "race"
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] backgrounds …")
    a, q, e = _run_category(
        "origins24/backgrounds",
        "backgrounds",
        translate_background_yaml,
        ingest_date,
        "background",
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] feats …")
    # feats24 nests four category subdirs; _run_category's rglob recurses them.
    a, q, e = _run_category("feats24", "feats", translate_feat_yaml, ingest_date, "feat")
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] classes …")
    a, q, e = _run_category("classes24", "classes", translate_class_yaml, ingest_date, "class")
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] subclasses …")
    # classes24 nests class docs, subclass docs, and class/subclass features in
    # the same tree; _run_category's rglob walks it and the doc-type quarantine
    # separates type:subclass from type:class and the type:feat features.
    a, q, e = _run_category(
        "classes24", "subclasses", translate_subclass_yaml, ingest_date, "subclass"
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] class features …")
    a, q, e = _run_category("classes24", "features", translate_feature_yaml, ingest_date, "feat")
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    print("[regen] species traits …")
    a, q, e = _run_category(
        "origins24/species/traits", "features", translate_feature_yaml, ingest_date, "feat"
    )
    non_srd_excluded.extend(e)
    print(f"  accepted={a}, quarantined={q}")

    # Post-process: populate Class.subclass_identifiers from the subclass
    # forward references. Foundry's Subclass-type advancement entries on the
    # class document are empty (configuration: {}); the parent→child link
    # lives on the subclass via ``system.classIdentifier``. We walk the
    # subclass canonical and inject the reverse index into each class JSON.
    subclass_index: dict[str, list[str]] = {}
    for sub_path in sorted((CANONICAL / "subclasses").glob("*.json")):
        sub_blob = json.loads(sub_path.read_text(encoding="utf-8"))
        parent = sub_blob.get("class_identifier")
        if not parent:
            continue
        subclass_index.setdefault(parent, []).append(sub_blob["slug"])
    for class_path in sorted((CANONICAL / "classes").glob("*.json")):
        class_blob = json.loads(class_path.read_text(encoding="utf-8"))
        # Reviewer-override classes are preserved; skip them.
        if (class_blob.get("review") or {}).get("known_divergence"):
            continue
        identifier = class_blob.get("identifier") or class_blob.get("slug")
        class_blob["subclass_identifiers"] = sorted(subclass_index.get(identifier, []))
        class_path.write_text(json.dumps(class_blob, indent=2, sort_keys=True), encoding="utf-8")

    # Post-process: resolve Foundry advancement UUID refs (ItemGrant/ItemChoice)
    # on class/subclass/species docs into typed GrantRef/FeatureChoice records.
    # The feature index maps Foundry UUIDs → the canonical feature slugs emitted
    # by the two feature passes above. A UUID present in the index is an emitted
    # SRD feature/feat/spell/item; a UUID absent from BOTH the index AND the
    # audited ``_KNOWN_UNRESOLVABLE_GRANTS`` allowlist is a hard failure — that
    # catches a real omission (an SRD feature that should have been emitted but
    # wasn't) instead of silently dropping the grant. The ``_assert_emitted``
    # guard still verifies every RESOLVED ref exists on disk, catching any
    # index/emit drift.
    from dnd5e_srd_data.schema.refs import ChoiceLevel, FeatureChoice, GrantRef
    from tools.translators.foundry import build_feature_index

    index = build_feature_index(FOUNDRY_PACKS)
    _REF_CANONICAL_DIR = {
        "feature": "features",
        "feat": "feats",
        "spell": "spells",
        "equipment": "items",
    }

    def _assert_emitted(refs: list[GrantRef]) -> None:
        for r in refs:
            target = CANONICAL / _REF_CANONICAL_DIR[r.ref_type] / f"{r.slug}.json"
            if not target.is_file():
                raise RuntimeError(
                    f"grant resolves to {r.ref_type}:{r.slug} but {target} not emitted"
                )

    def _resolve_tolerant(uuids: list[str], level: int) -> list[GrantRef]:
        out: list[GrantRef] = []
        for uuid in uuids:
            ref = index.get(uuid)
            if ref is None:
                reason = _KNOWN_UNRESOLVABLE_GRANTS.get(uuid)
                if reason is None:
                    raise RuntimeError(
                        f"unresolved grant target (not in index or allowlist): {uuid}"
                    )
                print(
                    f"[regen] skipping allowlisted grant target ({reason}): {uuid}",
                    file=sys.stderr,
                )
                continue
            out.append(GrantRef(ref_type=ref.ref_type, slug=ref.slug, level=level))
        return out

    def _inject_grants(canonical_subdir: str) -> None:
        d = CANONICAL / canonical_subdir
        if not d.is_dir():
            return
        for path in sorted(d.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            granted: list[GrantRef] = []
            choices: list[FeatureChoice] = []
            for entry in data.get("advancement", []):
                cfg = entry.get("configuration") or {}
                level = int(entry.get("level") or 0)
                if entry.get("type") == "ItemGrant":
                    uuids = [str(it.get("uuid")) for it in cfg.get("items", []) if it.get("uuid")]
                    granted += _resolve_tolerant(uuids, level)
                elif entry.get("type") == "ItemChoice":
                    pool_uuids = [
                        str(it.get("uuid")) for it in cfg.get("pool", []) if it.get("uuid")
                    ]
                    # Pool refs are options, not granted-at-a-level entries; their
                    # levels live in the schedule, so resolve them with level=0.
                    pool = _resolve_tolerant(pool_uuids, 0)
                    restriction = (cfg.get("restriction") or {}).get("subtype") or ""
                    # configuration.choices: {"<level>": {count, replacement}}.
                    # Foundry uses count:null for replace-only levels → count=0.
                    schedule = tuple(
                        sorted(
                            (
                                ChoiceLevel(
                                    level=int(lvl_key),
                                    count=int(spec.get("count") or 0),
                                    replacement=bool(spec.get("replacement")),
                                )
                                for lvl_key, spec in (cfg.get("choices") or {}).items()
                            ),
                            key=lambda cl: cl.level,
                        )
                    )
                    choices.append(
                        FeatureChoice(
                            restriction_subtype=restriction,
                            pool=tuple(pool),
                            schedule=schedule,
                        )
                    )
            _assert_emitted(granted)
            for ch in choices:
                _assert_emitted(list(ch.pool))
            data["granted_features"] = [r.model_dump() for r in granted]
            data["feature_choices"] = [c.model_dump() for c in choices]
            path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    for sub in ("classes", "subclasses", "species"):
        _inject_grants(sub)

    (AUDIT / "non_srd_excluded.json").write_text(
        json.dumps(non_srd_excluded, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Cross-check: load the SRD oracle (see tools/audit/build_srd_oracle.py)
    # and compare each freshly-written canonical entry against it. Findings
    # surface real Foundry-vs-open5e disagreements; oracle-clean translator
    # output produces an empty report.
    monster_oracle_path = ROOT / "tests" / "oracle" / "srd_monster_oracle.json"
    item_oracle_path = ROOT / "tests" / "oracle" / "srd_item_oracle.json"
    findings: list[dict] = []
    if monster_oracle_path.is_file():
        monster_oracle = json.loads(monster_oracle_path.read_text(encoding="utf-8"))
        for canonical_file in sorted((CANONICAL / "monsters").glob("*.json")):
            slug = canonical_file.stem
            oracle_entry = monster_oracle.get(slug)
            if not oracle_entry:
                continue
            canonical_entry = json.loads(canonical_file.read_text(encoding="utf-8"))
            for f in diff_monster_flat_fields(slug, canonical_entry, oracle_entry):
                findings.append(
                    {
                        "slug": f.slug,
                        "kind": f.kind,
                        "field": f.field,
                        "canonical_value": f.canonical_value,
                        "oracle_value": f.oracle_value,
                    }
                )
    if item_oracle_path.is_file():
        item_oracle = json.loads(item_oracle_path.read_text(encoding="utf-8"))
        for canonical_file in sorted((CANONICAL / "items").glob("*.json")):
            slug = canonical_file.stem
            oracle_entry = item_oracle.get(slug)
            if not oracle_entry:
                continue
            canonical_entry = json.loads(canonical_file.read_text(encoding="utf-8"))
            for f in diff_item_flat_fields(slug, canonical_entry, oracle_entry):
                findings.append(
                    {
                        "slug": f.slug,
                        "kind": f.kind,
                        "field": f.field,
                        "canonical_value": f.canonical_value,
                        "oracle_value": f.oracle_value,
                    }
                )

    # Spell / race / class / subclass cross-checks (Phase 7a PR 2).
    for category, diff_fn, oracle_filename in (
        ("spells", diff_spell_flat_fields, "srd_spell_oracle.json"),
        ("species", diff_species_flat_fields, "srd_species_oracle.json"),
        ("classes", diff_class_flat_fields, "srd_class_oracle.json"),
        ("subclasses", diff_subclass_flat_fields, "srd_subclass_oracle.json"),
    ):
        oracle_path = ROOT / "tests" / "oracle" / oracle_filename
        if not oracle_path.is_file():
            continue
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        for canonical_file in sorted((CANONICAL / category).glob("*.json")):
            slug = canonical_file.stem
            oracle_entry = oracle.get(slug)
            if not oracle_entry:
                continue
            canonical_entry = json.loads(canonical_file.read_text(encoding="utf-8"))
            for f in diff_fn(slug, canonical_entry, oracle_entry):
                findings.append(
                    {
                        "slug": f.slug,
                        "kind": f.kind,
                        "field": f.field,
                        "canonical_value": f.canonical_value,
                        "oracle_value": f.oracle_value,
                    }
                )

    (AUDIT / "validation_report.json").write_text(
        json.dumps(findings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (AUDIT / "requires_review.json").write_text("[]\n", encoding="utf-8")
    print(f"[regen] validation_report: {len(findings)} cross-check findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
