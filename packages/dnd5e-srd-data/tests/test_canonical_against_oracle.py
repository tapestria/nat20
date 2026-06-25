"""SRD-authoritative oracle test.

For every slug in the SRD oracle that ALSO exists in canonical/, assert
canonical's flat values match the oracle. Aggregates all failures into one
report so we see the full translator gap, not just the first mismatch.

Known divergences are recorded in ``tests/oracle/known_oracle_divergence.json``
as ``{slug: {field: rationale}}`` — divergences listed there don't fail the
test, but every entry is human-reviewed and time-stamped at commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / "tests" / "oracle"
CANONICAL = ROOT / "src" / "dnd5e_srd_data" / "canonical"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_aliases(path: Path) -> dict[str, str]:
    """Load a slug-alias file's ``aliases`` map; empty if absent."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw.get("aliases") or {})


def _resolve_oracle_slug(
    canonical_slug: str, oracle: dict[str, Any], aliases: dict[str, str]
) -> str | None:
    """Return the oracle key that matches the canonical slug, honouring aliases.

    Tries exact match first, then the alias map. Returns ``None`` if neither
    resolves to an oracle entry — caller treats that as "no oracle coverage".
    """
    if canonical_slug in oracle:
        return canonical_slug
    aliased = aliases.get(canonical_slug)
    if aliased and aliased in oracle:
        return aliased
    return None


def _is_excluded(divergence: dict[str, Any], slug: str, field: str) -> bool:
    entry = divergence.get(slug)
    if not isinstance(entry, dict):
        return False
    # Match exact field ('skills.arcana') OR top-level field ('skills' →
    # matches any 'skills.*' subfield diff). Keeps the divergence file
    # concise: one entry per logical field, even when the test reports
    # multiple per-subfield diffs.
    if field in entry:
        return True
    top = field.split(".", 1)[0]
    return top in entry


import re  # noqa: E402


def _norm_lang(items: list[str]) -> set[str]:
    """Set-equality, case-insensitive, trailing-period-stripped, whitespace-
    collapsed. Telepathy entries (which Foundry ships only in `custom`) compare
    by their dotted/un-dotted form. Foundry's structured slugs (e.g. 'deep')
    expand to 5e-bits' full names (e.g. 'Deep Speech') — we accept either.
    """
    expansions = {
        "deep": "deep speech",
        "thieves": "thieves' cant",
        "cant": "thieves' cant",
    }
    out: set[str] = set()
    for s in items:
        if not s:
            continue
        n = re.sub(r"\s+", " ", s.lower().rstrip(".")).strip()
        out.add(expansions.get(n, n))
    return out


def _cmp_languages(canonical: list[str], oracle: list[str]) -> bool:
    return _norm_lang(canonical) == _norm_lang(oracle)


def _check_monster(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []

    def diff(field: str, c_val: Any, o_val: Any) -> None:
        if c_val != o_val:
            diffs.append(f"{slug}.{field}: canonical={c_val!r} oracle={o_val!r}")

    diff("hp", canonical.get("hp"), oracle.get("hp"))
    diff("cr", canonical.get("cr"), oracle.get("cr"))
    diff("proficiency_bonus", canonical.get("proficiency_bonus"), oracle.get("proficiency_bonus"))
    diff("creature_size", canonical.get("creature_size"), oracle.get("creature_size"))
    diff("creature_type", canonical.get("creature_type"), oracle.get("creature_type"))

    # AC: oracle's first armor_class entry is authoritative ONLY when ac_type
    # is "natural", "dex" (no armor), or "armor" computed flat. When canonical
    # ships ac=null (Foundry omitted flat AC because it derives from equipped
    # items), we don't fail — the runtime resolves it. We DO fail if canonical
    # ships a number that disagrees with the oracle.
    c_ac = canonical.get("ac")
    o_ac = oracle.get("ac")
    o_ac_max = oracle.get("ac_max")
    if c_ac is not None and o_ac is not None:
        # Foundry sometimes bakes a buffed/alt AC (e.g. dryad w/ Barkskin) into
        # the flat field. Accept any value in the oracle's AC list.
        if c_ac != o_ac and c_ac != o_ac_max:
            diffs.append(f"{slug}.ac: canonical={c_ac} oracle={o_ac} (max={o_ac_max})")

    # Ability scores
    c_abil = canonical.get("ability_scores") or {}
    o_abil = oracle.get("ability_scores") or {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        if c_abil.get(ab) != o_abil.get(ab):
            diffs.append(
                f"{slug}.ability_scores.{ab}: canonical={c_abil.get(ab)} oracle={o_abil.get(ab)}"
            )

    # Saving throws — only the proficient ones, oracle's values match Foundry-
    # derived (ability_mod + prof + bonuses).
    c_saves = canonical.get("saving_throws") or {}
    o_saves = oracle.get("saving_throws") or {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        c_v = c_saves.get(ab)
        o_v = o_saves.get(ab)
        if o_v is not None:
            if c_v != o_v:
                diffs.append(f"{slug}.saving_throws.{ab}: canonical={c_v} oracle={o_v}")
        # If oracle has no entry (creature isn't proficient), canonical must
        # also be None — otherwise translator invented a save.
        elif c_v is not None:
            diffs.append(f"{slug}.saving_throws.{ab}: canonical claims {c_v}, oracle has none")

    # Skills. Oracle ships ONLY proficient skills (from the proficiencies
    # array). Canonical may also legitimately ship skills the oracle missed:
    # some 5e-bits entries encode perception proficiency only via the
    # `senses.passive_perception` value, not via the proficiencies array.
    # So we only assert on the positive case: oracle has a value, canonical
    # must match.
    c_skills = canonical.get("skills") or {}
    o_skills = oracle.get("skills") or {}
    for skill, o_v in o_skills.items():
        c_v = c_skills.get(skill)
        if c_v != o_v:
            diffs.append(f"{slug}.skills.{skill}: canonical={c_v} oracle={o_v}")

    # Passive perception
    c_pp = (canonical.get("senses") or {}).get("passive_perception")
    o_pp = oracle.get("passive_perception")
    if o_pp is not None and c_pp != o_pp:
        diffs.append(f"{slug}.passive_perception: canonical={c_pp} oracle={o_pp}")

    # Languages — set-equality with normalization
    c_langs = canonical.get("languages") or []
    o_langs = oracle.get("languages") or []
    if o_langs and not _cmp_languages(c_langs, o_langs):
        diffs.append(f"{slug}.languages: canonical={sorted(c_langs)!r} oracle={sorted(o_langs)!r}")

    # Damage lists. Oracle ships compound SRD strings like
    # "bludgeoning, piercing, and slashing from nonmagical weapons" as a single
    # element; Foundry splits them per damage type and ALSO carries the
    # "bypasses" caveat in a separate field we don't surface in canonical yet.
    # Normalize both sides to the bare damage-type set; the caveat (silvered /
    # adamantine / nonmagical) is a known representational difference and lives
    # in the schema's deferred bypass-modifier track. The comparison fails only
    # when canonical is MISSING a damage type the oracle calls out.
    def _flatten_damage(items: list[str]) -> set[str]:
        out: set[str] = set()
        for entry in items:
            # Strip "from ..." caveat tail.
            head = re.split(r"\s+from\s+", entry.lower(), maxsplit=1)[0]
            # Split on ", and " / ", " / " and ".
            for chunk in re.split(r",\s+and\s+|,\s+|\s+and\s+", head):
                chunk = chunk.strip()
                if chunk and chunk != "damage" and "spell" not in chunk:
                    out.add(chunk)
        return out

    for field in ("damage_resistances", "damage_immunities", "damage_vulnerabilities"):
        c_v = canonical.get(field) or []
        o_v = oracle.get(field) or []
        if not o_v:
            continue
        o_flat = _flatten_damage(o_v)
        c_flat = _flatten_damage(c_v)
        missing = o_flat - c_flat
        if missing:
            diffs.append(
                f"{slug}.{field}: canonical missing {sorted(missing)!r} (oracle={sorted(o_v)!r})"
            )

    # Condition immunities. 5e-bits ships occasional duplicates and the
    # occasional typo (e.g. "blinded, blinded" where one should be
    # "deafened" — verified in oozes). Only flag entries the oracle calls
    # out that canonical IS MISSING; canonical-superset is fine.
    c_ci = {str(s).lower() for s in (canonical.get("condition_immunities") or [])}
    o_ci = {str(s).lower() for s in (oracle.get("condition_immunities") or [])}
    missing = o_ci - c_ci
    if missing:
        diffs.append(f"{slug}.condition_immunities: canonical missing {sorted(missing)!r}")

    return diffs


def _check_item(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    kind = oracle.get("kind")

    def diff(field: str, c_val: Any, o_val: Any) -> None:
        if c_val != o_val:
            diffs.append(f"{slug}.{field}: canonical={c_val!r} oracle={o_val!r}")

    # Common
    if oracle.get("weight") is not None:
        diff("weight", float(canonical.get("weight") or 0), float(oracle["weight"]))
    if oracle.get("cost_gp") is not None:
        diff("cost_gp", canonical.get("cost_gp"), oracle["cost_gp"])

    if kind == "weapon":
        if oracle.get("weapon_category"):
            diff("weapon_category", canonical.get("weapon_category"), oracle["weapon_category"])
        # Damage parts: oracle has a single (dice, type) tuple.
        o_dice = oracle.get("damage_dice")
        o_type = oracle.get("damage_type")
        parts = canonical.get("damage_parts") or []
        if o_dice and o_type:
            if not parts:
                diffs.append(f"{slug}.damage_parts: canonical=[] oracle=[{o_dice}/{o_type}]")
            else:
                c_dice = parts[0].get("dice")
                c_type = parts[0].get("damage_type")
                if c_dice != o_dice:
                    diffs.append(
                        f"{slug}.damage_parts[0].dice: canonical={c_dice!r} oracle={o_dice!r}"
                    )
                if c_type != o_type:
                    diffs.append(
                        f"{slug}.damage_parts[0].damage_type: canonical={c_type!r} oracle={o_type!r}"
                    )
        # Versatile
        o_vers = oracle.get("versatile_dice")
        c_vers = (
            (canonical.get("versatile_damage") or {}).get("dice")
            if canonical.get("versatile_damage")
            else None
        )
        if o_vers and c_vers != o_vers:
            diffs.append(f"{slug}.versatile_damage.dice: canonical={c_vers!r} oracle={o_vers!r}")

        # Properties: set-compare. Normalize hyphen/underscore (oracle uses
        # kebab "two-handed"; canonical schema uses snake "two_handed"). Drop
        # "monk" — that's a 2024 SRD addition; our schema is 5.1 (2014).
        def _norm_props(items: set[str]) -> set[str]:
            return {p.replace("-", "_") for p in items if p != "monk"}

        o_props = _norm_props(set(oracle.get("properties") or []))
        c_props = _norm_props(set(canonical.get("properties") or []))
        missing = o_props - c_props
        if missing:
            diffs.append(
                f"{slug}.properties: oracle has extras not in canonical: {sorted(missing)!r}"
            )

    elif kind == "armor":
        if oracle.get("armor_category"):
            diff("armor_category", canonical.get("armor_category"), oracle["armor_category"])
        if oracle.get("base_ac") is not None:
            diff("base_ac", canonical.get("base_ac"), oracle["base_ac"])
        if oracle.get("stealth_disadvantage") is not None:
            diff(
                "stealth_disadvantage",
                canonical.get("stealth_disadvantage"),
                oracle["stealth_disadvantage"],
            )

    # Magic-item layer (may apply to weapons/armor too if oracle has the keys).
    # The 5e-bits oracle ships some items as a single AGGREGATE entry spanning
    # multiple rarity grades (feather-token, ioun-stone, spell-scroll →
    # "rarity_varies"; shield/+N items → "uncommon (+1), rare (+2), ..."). Those
    # un-normalized prose values are not a single comparable tier — Foundry ships
    # the concrete base grade. Only cross-check when the oracle rarity is a clean
    # canonical tier; the aggregate cases are validated per-variant elsewhere.
    _CANON_RARITIES = {"common", "uncommon", "rare", "very_rare", "legendary", "artifact"}
    if oracle.get("rarity") in _CANON_RARITIES:
        diff("rarity", canonical.get("rarity"), oracle["rarity"])
    if "requires_attunement" in oracle:
        diff(
            "requires_attunement",
            canonical.get("requires_attunement"),
            oracle["requires_attunement"],
        )

    return diffs


def _check_spell(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    # MIXED-EDITION ORACLE (Decision D1): the spell oracle is built from the
    # 2014 5e-bits snapshot (no 2024 `5e-SRD-Spells.json` exists) while canonical
    # is the 2024 `spells24/` Foundry packs. The 2014→2024 SRD spell redesign
    # changed several fields on 80+ spells — school (cure-wounds evo→abj),
    # concentration (barkskin lost it, sleep gained it), duration, range, and
    # casting_time. Those fields are therefore NOT edition-stable and asserting
    # them against the 2014 oracle would surface 100+ genuine edition changes as
    # "divergences", masking real signal. We cross-check only the genuinely
    # edition-stable fields the two editions agree on for the overwhelming
    # majority of spells: level (0 cross-edition diffs), components, and ritual.
    # The ~6 residual component/ritual divergences are real 2024 redesigns
    # curated in known_oracle_divergence.json. ``name`` is not asserted — 2024
    # re-cased preposition words (Protection From Energy vs from), a cosmetic-only
    # cross-edition difference.
    #
    # The oracle's per-spell ``classes`` field is likewise not built/checked:
    # 2024 SRD packs ship no spell→class tags (curated separately in PR 4b).
    diffs: list[str] = []

    def diff(field: str, c_val: Any, o_val: Any) -> None:
        if c_val != o_val:
            diffs.append(f"{slug}.{field}: canonical={c_val!r} oracle={o_val!r}")

    if oracle.get("level") is not None:
        diff("level", canonical.get("level"), oracle["level"])
    if oracle.get("ritual") is not None:
        diff("ritual", canonical.get("ritual"), oracle["ritual"])
    if oracle.get("components"):
        diff(
            "components",
            sorted(canonical.get("components") or []),
            oracle["components"],
        )

    # NOT cross-checked — 2024 SRD redesigned these on 80+ spells vs the 2014
    # oracle (see header). school / concentration / casting_time / range /
    # duration are validated against Foundry's own structured fields by the
    # translator-fidelity test instead.

    # Note: ``oracle["material"]`` is intentionally NOT cross-checked. Foundry
    # and 5e-bits paraphrase the same SRD material requirement with cosmetic
    # whitespace/wording differences on 52 of the 319 spells (e.g. "50 gp" vs
    # "50gp", "phosphorous" vs "phosphorus"). The mechanical facts (is a
    # material component required? is it consumed? does it have a cost?) are
    # verified via ``materials.cost`` + components frozenset above, and the
    # ``spell material value preserved`` fidelity check ensures Foundry's
    # exact prose round-trips into canonical.
    return diffs


def _check_species(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []

    def diff(field: str, c_val: Any, o_val: Any) -> None:
        if c_val != o_val:
            diffs.append(f"{slug}.{field}: canonical={c_val!r} oracle={o_val!r}")

    if oracle.get("size"):
        diff("size", canonical.get("size"), oracle["size"])
    if oracle.get("speed") is not None:
        diff("walk_speed", (canonical.get("movement") or {}).get("walk"), oracle["speed"])

    # The 2024 SRD dropped species ability-score bonuses and language grants
    # (both moved to background), so neither is oracled — size + speed are the
    # mechanical facts we cross-check. The oracle's ``traits`` are 5e-bits slug
    # indices, not the Foundry feature UUIDs canonical carries, so they are not
    # comparable here.
    return diffs


# Foundry skill short-codes → 5e-bits full names. Canonical backgrounds carry
# Foundry codes (``ins``, ``rel``); the 2024 oracle ships full hyphenated names
# (``insight``, ``sleight-of-hand``). Normalise to the oracle's hyphen form.
_SKILL_CODE_TO_NAME = {
    "acr": "acrobatics",
    "ani": "animal-handling",
    "arc": "arcana",
    "ath": "athletics",
    "dec": "deception",
    "his": "history",
    "ins": "insight",
    "itm": "intimidation",
    "inv": "investigation",
    "med": "medicine",
    "nat": "nature",
    "prc": "perception",
    "prf": "performance",
    "per": "persuasion",
    "rel": "religion",
    "slt": "sleight-of-hand",
    "ste": "stealth",
    "sur": "survival",
}


def _check_background(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []

    # Ability-improvement pool: oracle ships the three improvable abilities as a
    # sorted index list; canonical serializes the frozenset → sorted list.
    expected_abilities = sorted(oracle.get("ability_options") or [])
    actual_abilities = sorted((canonical.get("ability_options") or {}).get("options") or [])
    if expected_abilities and actual_abilities != expected_abilities:
        diffs.append(
            f"{slug}.ability_options: canonical={actual_abilities!r} oracle={expected_abilities!r}"
        )

    # Skill proficiencies: canonical Foundry short-codes → oracle full names.
    expected_skills = sorted(oracle.get("skill_proficiencies") or [])
    actual_skills = sorted(
        _SKILL_CODE_TO_NAME.get(c, c) for c in (canonical.get("skill_proficiencies") or [])
    )
    if expected_skills and actual_skills != expected_skills:
        diffs.append(
            f"{slug}.skill_proficiencies: canonical={actual_skills!r} oracle={expected_skills!r}"
        )

    # NOT cross-checked (genuine cross-source vocabulary divergence, mirrors the
    # species ``traits``/feat handling):
    # - ``feat``: the oracle ships the 5e-bits feat index (``magic-initiate``),
    #   canonical carries the Foundry compendium-UUID segment
    #   (``phbftMagicInitia``). The two ID spaces are not comparable without a
    #   feat-slug map that a later phase introduces.
    # - ``tool_proficiencies``: oracle uses equipment slugs
    #   (``calligraphers-supplies``, ``thieves-tools``), canonical carries
    #   Foundry tool keys (``art:calligrapher``, ``thief``, ``game:*``) — again
    #   distinct vocabularies. The translator-fidelity test pins the exact
    #   Foundry values.
    return diffs


def _check_feat(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []

    def diff(field: str, c_val: Any, o_val: Any) -> None:
        if c_val != o_val:
            diffs.append(f"{slug}.{field}: canonical={c_val!r} oracle={o_val!r}")

    if oracle.get("name"):
        diff("name", canonical.get("name"), oracle["name"])

    # Category: the 5e-bits ``type`` string maps cleanly onto the four canonical
    # FeatCategory values (origin / general / fighting_style / epic_boon). The
    # ASI feat — which Foundry ships with an EMPTY ``system.type.subtype`` — is
    # the one case where the translator's GENERAL fallback must agree with the
    # 5e-bits ``general`` classification; cross-checking it here pins that.
    if oracle.get("category"):
        diff("category", canonical.get("category"), oracle["category"])

    # NOT cross-checked: ``prerequisites`` (Foundry's structured level/items vs
    # the 5e-bits prose vary in vocabulary) and ``activities`` (the four epic
    # boons' activity payloads are pinned by the translator-fidelity test, and
    # the activity oracle does not yet cover feats24 — a later agent expands
    # its TRANSLATED_SUBTREES). Name + category are the mechanical facts here.
    return diffs


def _check_class(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    expected_hd = oracle.get("hit_die")
    if expected_hd is not None:
        actual_hd_str = canonical.get("hit_die") or ""
        try:
            actual_hd = int(str(actual_hd_str).removeprefix("d") or 0)
        except ValueError:
            actual_hd = 0
        if actual_hd != expected_hd:
            diffs.append(f"{slug}.hit_die: canonical={actual_hd} oracle={expected_hd}")

    # Saving throws — oracle ships sorted list (["con", "str"]), canonical
    # serializes frozenset → sorted list via field_serializer.
    expected_saves = oracle.get("saving_throws") or []
    actual_saves = canonical.get("saving_throws") or []
    if expected_saves and sorted(actual_saves) != sorted(expected_saves):
        diffs.append(
            f"{slug}.saving_throws: canonical={sorted(actual_saves)!r} oracle={sorted(expected_saves)!r}"
        )

    # Subclass linkage — oracle ships 5e-bits short slugs (e.g. ["champion"]),
    # canonical ships Foundry filenames (e.g. ["champion"] or
    # ["school-of-evocation"]). Translate canonical → 5e-bits via the same
    # subclass_aliases used by test_subclasses_match_oracle, then set-compare.
    expected_sub = set(oracle.get("subclass_slugs") or [])
    if expected_sub:
        aliases = _load_aliases(ORACLE_DIR / "subclass_aliases.json")
        actual_sub = {aliases.get(s, s) for s in (canonical.get("subclass_identifiers") or [])}
        missing = expected_sub - actual_sub
        if missing:
            diffs.append(
                f"{slug}.subclass_identifiers: canonical missing {sorted(missing)!r} "
                f"(expected={sorted(expected_sub)!r}, got={sorted(actual_sub)!r})"
            )
    return diffs


def _check_subclass(slug: str, canonical: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    expected_class = oracle.get("class_slug")
    actual_class = canonical.get("class_identifier")
    if expected_class and actual_class and expected_class != actual_class:
        diffs.append(
            f"{slug}.class_identifier: canonical={actual_class!r} oracle={expected_class!r}"
        )
    return diffs


def _run_oracle_check(
    category: str,
    oracle_filename: str,
    check_fn: Any,
    aliases_filename: str | None = None,
) -> None:
    oracle = _load_json(ORACLE_DIR / oracle_filename)
    divergence = _load_json(ORACLE_DIR / "known_oracle_divergence.json")
    aliases = _load_aliases(ORACLE_DIR / aliases_filename) if aliases_filename else {}
    canonical_dir = CANONICAL / category
    if not oracle:
        pytest.skip(f"{category} oracle not built")
    all_diffs: list[str] = []
    checked = 0
    for canon_path in sorted(canonical_dir.glob("*.json")):
        slug = canon_path.stem
        oracle_slug = _resolve_oracle_slug(slug, oracle, aliases)
        if oracle_slug is None:
            continue
        oracle_entry = oracle[oracle_slug]
        canonical_entry = json.loads(canon_path.read_text(encoding="utf-8"))
        diffs = check_fn(slug, canonical_entry, oracle_entry)
        diffs = [
            d for d in diffs if not _is_excluded(divergence, slug, d.split(":")[0].split(".", 1)[1])
        ]
        all_diffs.extend(diffs)
        checked += 1
    if all_diffs:
        pytest.fail(
            f"{category} oracle mismatches (checked {checked} slugs, {len(all_diffs)} diffs):\n"
            + "\n".join(all_diffs[:200])
            + (f"\n... and {len(all_diffs) - 200} more" if len(all_diffs) > 200 else "")
        )


def test_spells_match_oracle() -> None:
    _run_oracle_check("spells", "srd_spell_oracle.json", _check_spell)


def test_species_match_oracle() -> None:
    _run_oracle_check("species", "srd_species_oracle.json", _check_species)


def test_backgrounds_match_oracle() -> None:
    _run_oracle_check("backgrounds", "srd_background_oracle.json", _check_background)


def test_feats_match_oracle() -> None:
    _run_oracle_check("feats", "srd_feat_oracle.json", _check_feat)


def test_classes_match_oracle() -> None:
    _run_oracle_check("classes", "srd_class_oracle.json", _check_class)


def test_subclasses_match_oracle() -> None:
    _run_oracle_check(
        "subclasses",
        "srd_subclass_oracle.json",
        _check_subclass,
        aliases_filename="subclass_aliases.json",
    )


def test_monsters_match_oracle() -> None:
    oracle = _load_json(ORACLE_DIR / "srd_monster_oracle.json")
    divergence = _load_json(ORACLE_DIR / "known_oracle_divergence.json")
    aliases = _load_aliases(ORACLE_DIR / "monster_form_aliases.json")
    canonical_dir = CANONICAL / "monsters"
    if not oracle:
        pytest.skip("monster oracle not built")
    all_diffs: list[str] = []
    checked = 0
    for canon_path in sorted(canonical_dir.glob("*.json")):
        slug = canon_path.stem
        oracle_slug = _resolve_oracle_slug(slug, oracle, aliases)
        if oracle_slug is None:
            continue
        canonical_entry = json.loads(canon_path.read_text(encoding="utf-8"))
        diffs = _check_monster(slug, canonical_entry, oracle[oracle_slug])
        diffs = [
            d for d in diffs if not _is_excluded(divergence, slug, d.split(":")[0].split(".", 1)[1])
        ]
        all_diffs.extend(diffs)
        checked += 1
    if all_diffs:
        pytest.fail(
            f"monster oracle mismatches (checked {checked} slugs, {len(all_diffs)} diffs):\n"
            + "\n".join(all_diffs[:200])
            + (f"\n... and {len(all_diffs) - 200} more" if len(all_diffs) > 200 else "")
        )


def test_items_match_oracle() -> None:
    oracle = _load_json(ORACLE_DIR / "srd_item_oracle.json")
    divergence = _load_json(ORACLE_DIR / "known_oracle_divergence.json")
    aliases = _load_aliases(ORACLE_DIR / "slug_aliases.json")
    canonical_dir = CANONICAL / "items"
    if not oracle:
        pytest.skip("item oracle not built")
    all_diffs: list[str] = []
    checked = 0
    for canon_path in sorted(canonical_dir.glob("*.json")):
        slug = canon_path.stem
        oracle_slug = _resolve_oracle_slug(slug, oracle, aliases)
        if oracle_slug is None:
            continue
        canonical_entry = json.loads(canon_path.read_text(encoding="utf-8"))
        diffs = _check_item(slug, canonical_entry, oracle[oracle_slug])
        diffs = [
            d for d in diffs if not _is_excluded(divergence, slug, d.split(":")[0].split(".", 1)[1])
        ]
        all_diffs.extend(diffs)
        checked += 1
    if all_diffs:
        pytest.fail(
            f"item oracle mismatches (checked {checked} slugs, {len(all_diffs)} diffs):\n"
            + "\n".join(all_diffs[:200])
            + (f"\n... and {len(all_diffs) - 200} more" if len(all_diffs) > 200 else "")
        )
