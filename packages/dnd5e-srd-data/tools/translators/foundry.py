"""Foundry pack YAML → canonical Pydantic. Deterministic per pack-pin."""

from __future__ import annotations

import functools
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel

from dnd5e_srd_data import (
    AbilityScores,
    Activity,
    AdvancementEntry,
    AdvancementType,
    Armor,
    ArmorCategory,
    AttackActivity,
    Background,
    BackgroundAbilityChoice,
    CastActivity,
    CastingTime,
    CastingTimeUnit,
    CheckActivity,
    Class,
    CreatureKind,
    CreatureSize,
    CreatureType,
    CreatureTypeRef,
    DamageActivity,
    DamagePart,
    DamagePartBlock,
    EnchantActivity,
    Feat,
    FeatCategory,
    FeatPrerequisite,
    Feature,
    GrantRef,
    HealActivity,
    HitDie,
    Item,
    ItemRarity,
    MagicItem,
    Monster,
    MonsterAction,
    MonsterActionKind,
    Movement,
    PassiveEffect,
    PassiveEffectChange,
    PrimaryAbility,
    Provenance,
    Range,
    RangeUnits,
    ReviewState,
    SaveActivity,
    SavingThrowProficiencies,
    Senses,
    SkillProficiencies,
    Spell,
    SpellComponent,
    SpellDuration,
    SpellDurationUnits,
    SpellMaterials,
    SpellPreparation,
    SpellRange,
    SpellRangeUnits,
    SpellSchool,
    Species,
    Spellcasting,
    SpellcastingProgression,
    Subclass,
    SummonActivity,
    TransformActivity,
    UtilityActivity,
    Weapon,
    WeaponProperty,
)

from tools.translators.prose_cleanup import cleanup_prose

ROOT = Path(__file__).resolve().parent.parent.parent


_WEAPON_TYPE_MAP = {
    "simpleM": "simple_melee",
    "simpleR": "simple_ranged",
    "martialM": "martial_melee",
    "martialR": "martial_ranged",
    # Full forms occasionally appear in newer pack revisions.
    "simpleMelee": "simple_melee",
    "simpleRanged": "simple_ranged",
    "martialMelee": "martial_melee",
    "martialRanged": "martial_ranged",
}

_WEAPON_PROPERTY_MAP = {
    "amm": WeaponProperty.AMMUNITION,
    "fin": WeaponProperty.FINESSE,
    "hvy": WeaponProperty.HEAVY,
    "lgt": WeaponProperty.LIGHT,
    "lod": WeaponProperty.LOADING,
    "rch": WeaponProperty.REACH,
    "spc": WeaponProperty.SPECIAL,
    "thr": WeaponProperty.THROWN,
    "two": WeaponProperty.TWO_HANDED,
    "ver": WeaponProperty.VERSATILE,
}

_ARMOR_TYPE_MAP = {
    "light": ArmorCategory.LIGHT,
    "medium": ArmorCategory.MEDIUM,
    "heavy": ArmorCategory.HEAVY,
    "shield": ArmorCategory.SHIELD,
}

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


# SRD versatile dice — Foundry doesn't structurally encode the upgraded die
# (it relies on user choice at roll time). The mapping below is sourced from
# 5e-bits' `5e-SRD-Equipment.json` two_handed_damage.damage_dice for every
# SRD weapon with the `versatile` property. Lookup by Foundry baseItem slug.
_SRD_VERSATILE_DICE: dict[str, str] = {
    "battleaxe": "1d10",
    "longsword": "1d10",
    "warhammer": "1d10",
    "trident": "1d8",
    "quarterstaff": "1d8",
    "spear": "1d8",
}


# ---------------------------------------------------------------------------
# Activity translator (Phase 7b PR A — task A4).
#
# Foundry stores ``system.activities`` as ``{activity_id: activity_dict}``.
# Each activity_dict's ``type`` discriminator selects the per-kind Pydantic
# model (AttackActivity / SaveActivity / …); ``_translate_activities`` returns
# a deterministic list[Activity] in Foundry's source order (Python 3.7+ dict
# iteration preserves insertion order, which matches the YAML write order).
#
# The translator is a near-pass-through: Foundry's nested field structure
# survives unchanged; only camelCase identifiers map to the schema's
# snake_case names. The mapping is closed (see ``_ACTIVITY_CAMEL_TO_SNAKE``);
# any future Foundry-side new camelCase field must be added here AND surface
# in the activity oracle so the fidelity test catches the drift.
#
# A small set of Foundry-side legacy fields are not (yet) representable in
# the A3 schema and are deliberately dropped at translation time:
# - ``appliedEffects``: a legacy flat list[str] of effect ids that duplicates
#   the structured ``effects[]._id`` slice. Empty in most YAML; non-empty in
#   four entries (hunters-mark, ring-of-invisibility, shillelagh,
#   wand-of-paralysis) where it still mostly aliases ``effects[]._id``.
#   Tracked as an A3 follow-up; see ``known_activity_fidelity_exceptions``
#   in ``tests/test_activity_translator_fidelity.py``.
# ---------------------------------------------------------------------------


_ACTIVITY_CAMEL_TO_SNAKE: dict[str, str] = {
    "spellSlot": "spell_slot",
    "chatFlavor": "chat_flavor",
    "includeBase": "include_base",
    "onSave": "on_save",
    "requireAttunement": "require_attunement",
    "requireIdentification": "require_identification",
    "requireMagic": "require_magic",
    "creatureSizes": "creature_sizes",
    "creatureTypes": "creature_types",
    "tempHP": "temp_hp",
    "attackDamage": "attack_damage",
    "saveDamage": "save_damage",
    "allowMagical": "allow_magical",
}

# Foundry-side fields we deliberately drop because the A3 schema cannot
# represent them losslessly. See module docstring above. Recorded here so
# `_normalize_activity_dict` can drop them with intent (vs accidentally).
_ACTIVITY_DROP_KEYS: frozenset[str] = frozenset({"appliedEffects"})


_ACTIVITY_KIND_TO_CLASS: dict[str, type[BaseModel]] = {
    "attack": AttackActivity,
    "cast": CastActivity,
    "check": CheckActivity,
    "damage": DamageActivity,
    "enchant": EnchantActivity,
    "heal": HealActivity,
    "save": SaveActivity,
    "summon": SummonActivity,
    "transform": TransformActivity,
    "utility": UtilityActivity,
}


# Foundry serializes "no die" damage/healing fields as ``""`` rather than null
# (e.g. mass-heal's flat 700-HP heal: ``denomination: ''``). The schema types
# these as ``NonNegativeInt | None``, so the empty string must become None.
_NULLABLE_INT_KEYS: frozenset[str] = frozenset({"number", "denomination"})


def _normalize_activity_dict(obj: Any, *, drop_keys: frozenset[str] = _ACTIVITY_DROP_KEYS) -> Any:
    """Recursively rename Foundry's camelCase activity keys to the schema's
    snake_case names. List elements are walked; primitives pass through.

    ``drop_keys`` defaults to the legacy keys not representable in A3 (see
    ``_ACTIVITY_DROP_KEYS``). Tests that want the pure camelCase rewrite
    without the schema-driven drop can pass ``drop_keys=frozenset()``."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in drop_keys:
                continue
            mapped = _ACTIVITY_CAMEL_TO_SNAKE.get(k, k)
            if mapped in _NULLABLE_INT_KEYS and v == "":
                out[mapped] = None
                continue
            out[mapped] = _normalize_activity_dict(v, drop_keys=drop_keys)
        return out
    if isinstance(obj, list):
        return [_normalize_activity_dict(x, drop_keys=drop_keys) for x in obj]
    return obj


def _coerce_save_ability(save: Any) -> Any:
    """Foundry's ``save.ability`` is a ``SetField(StringField)``; the YAML pack
    serializes it as either a scalar string (~90% of entries) or a list. The
    A3 schema types it as ``list[str]``. Promote scalar → single-element list
    so both shapes validate."""
    if not isinstance(save, dict):
        return save
    ability = save.get("ability")
    if isinstance(ability, str):
        save = dict(save)
        save["ability"] = [ability] if ability else []
    return save


def _coerce_check_associated(check: Any) -> Any:
    """Foundry's ``check.associated`` is a ``SetField(StringField)``; the YAML
    pack serializes it as a scalar string (e.g. maze's ``associated: 'inv'``)
    or a list. The A3 schema types it as ``list[str]``. Promote scalar →
    single-element list (empty string → empty list) so both shapes validate."""
    if not isinstance(check, dict):
        return check
    associated = check.get("associated")
    if isinstance(associated, str):
        check = dict(check)
        check["associated"] = [associated] if associated else []
    return check


def _coerce_enchant_effect_riders(effects: Any) -> Any:
    """Foundry's ``enchant.effects[*].riders`` is a ``SchemaField`` (dict). The
    YAML pack occasionally ships ``riders: []`` (the empty-list placeholder
    for an unset schema), which fails A3's ``EnchantEffectRiders`` validator.
    Coerce ONLY the empty-list placeholder → default empty dict; any
    non-empty list shape (a future Foundry revision or homebrew enchant) is
    left intact so EnchantEffectRiders' validator raises loud rather than
    the translator silently dropping rider IDs."""
    if not isinstance(effects, list):
        return effects
    out = []
    for e in effects:
        if isinstance(e, dict) and e.get("riders") == []:
            e = dict(e)
            e["riders"] = {}
        out.append(e)
    return out


def _inherit_item_target(raw: dict[str, Any], item_target: dict[str, Any]) -> dict[str, Any]:
    """Foundry's ``ActivityData#target`` getter resolves the effective target
    by *inheriting* the owning item's ``system.target`` whenever the activity's
    own ``target.override`` is false (the common case). Only an activity that
    sets ``override: true`` carries its own template/affects. The YAML pack
    serializes the un-overridden activity ``target`` as a near-empty stub
    (``{template: {…units}, affects: {choice}, override: false}``) and leaves
    the real measured-template / affects data at the item level.

    Surface that inheritance here so the typed activity carries the AoE shape
    (e.g. fireball's ``sphere/20``) instead of an empty template. When
    ``override`` is true (e.g. detect-thoughts' save activity narrowing to a
    single creature), the activity's own target wins untouched."""
    target = raw.get("target")
    if not isinstance(target, dict) or target.get("override"):
        return raw
    if not isinstance(item_target, dict):
        return raw
    merged_target = dict(target)
    for block in ("template", "affects"):
        item_block = item_target.get(block)
        if isinstance(item_block, dict):
            merged_target[block] = item_block
    raw = dict(raw)
    raw["target"] = merged_target
    return raw


def _build_activity(
    activity_id: str,
    raw: dict[str, Any],
    *,
    item_target: dict[str, Any] | None = None,
) -> Activity | None:
    """Build one per-kind Activity Pydantic model from a Foundry activity
    dict. Returns ``None`` if the discriminator is missing or maps to a kind
    not in the schema (Foundry's ``order`` / ``forward`` kinds aren't yet
    modeled). The activity fidelity oracle captures EVERY kind (no filter),
    so an unhandled kind that appears in SRD content will fail
    test_every_oracle_activity_builds — making the silent drop CI-visible.
    A warning here gives a louder signal during regen itself.

    ``item_target`` is the owning item's ``system.target`` block, inherited
    into the activity's target when the activity does not override it (see
    :func:`_inherit_item_target`)."""
    if item_target is not None:
        raw = _inherit_item_target(raw, item_target)
    raw_kind = str(raw.get("type") or "").strip()
    cls = _ACTIVITY_KIND_TO_CLASS.get(raw_kind)
    if cls is None:
        print(
            f"[foundry-translator] WARN: dropping activity {activity_id!r} "
            f"with unmodeled kind {raw_kind!r}",
            file=sys.stderr,
        )
        return None
    normalized = _normalize_activity_dict(raw)
    # Foundry's YAML occasionally serializes the optional top-level string
    # fields ``img`` / ``name`` as ``null`` (vs the schema-default empty
    # string). Coerce to empty string so validation passes without losing the
    # upstream "field was present but empty" signal.
    for str_field in ("img", "name"):
        if normalized.get(str_field) is None and str_field in normalized:
            normalized[str_field] = ""
    # Per-kind shape coercions for Foundry → Pydantic-schema mismatches that
    # are too narrow to bake into A3 but too common to defer.
    if raw_kind == "save" and "save" in normalized:
        normalized["save"] = _coerce_save_ability(normalized["save"])
    if raw_kind == "check" and "check" in normalized:
        normalized["check"] = _coerce_check_associated(normalized["check"])
    if raw_kind == "enchant" and "effects" in normalized:
        normalized["effects"] = _coerce_enchant_effect_riders(normalized["effects"])
    # ``_id`` is the canonical Foundry identifier (Pydantic field name ``id``
    # with alias ``_id``; populate_by_name=True). _normalize_activity_dict
    # never renames ``_id`` and never produces ``id``, so a single setdefault
    # on the alias suffices when Foundry omits the inline ``_id`` field
    # (rare; the outer dict key carries the same value).
    normalized.setdefault("_id", activity_id)
    return cls.model_validate(normalized)  # type: ignore[return-value]


def _translate_activities(system: dict[str, Any]) -> list[Activity]:
    """Translate ``system.activities`` (Foundry's id-keyed dict) into a
    deterministic ``list[Activity]`` preserving Foundry's source order.

    Foundry's source YAML uses ordered mappings; PyYAML's ``safe_load``
    preserves insertion order, so iterating ``activities.items()`` is the
    canonical order. No sorting — see PR A spec §C (determinism: preserve
    Foundry order; do not introduce alphabetical reordering)."""
    activities_raw = system.get("activities") if isinstance(system, dict) else None
    if not isinstance(activities_raw, dict):
        return []
    item_target = system.get("target") if isinstance(system, dict) else None
    out: list[Activity] = []
    for activity_id, raw in activities_raw.items():
        if not isinstance(raw, dict):
            continue
        built = _build_activity(
            str(activity_id),
            raw,
            item_target=item_target if isinstance(item_target, dict) else None,
        )
        if built is None:
            continue
        out.append(built)
    return out


def _load_yaml(yaml_path: Path) -> dict[str, Any]:
    return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))


_INDEX_PACK_REF_TYPE: dict[str, str] = {
    "classes24": "feature",
    "origins24": "feature",
    "feats24": "feat",
    "spells24": "spell",
    "equipment24": "equipment",
}

# Feature-bearing packs hold non-feature docs (class/subclass/weapon under
# classes24; species/background under origins24) alongside the ``type:feat``
# docs that are the only ones emitted to ``canonical/features``. Restrict their
# index to ``type:feat`` so a packed UUID in the index ⟺ an emitted SRD feature;
# the other ref-type packs (feats24/spells24/equipment24) index all SRD docs.
_FEATURE_PACKS: frozenset[str] = frozenset({"classes24", "origins24"})


def _is_srd_doc(doc: dict[str, Any]) -> bool:
    if doc.get("flags", {}).get("srd"):
        return True
    source = (doc.get("system") or {}).get("source") or {}
    return (source.get("license") or "") == "CC-BY-4.0" and (source.get("rules") or "") in (
        "2014",
        "2024",
    )


def build_feature_index(packs_root: Path) -> dict[str, GrantRef]:
    index: dict[str, GrantRef] = {}
    for pack, ref_type in _INDEX_PACK_REF_TYPE.items():
        src = packs_root / pack
        if not src.is_dir():
            continue
        for yaml_path in sorted(src.rglob("*.yml")):
            if yaml_path.name.startswith("_"):
                continue
            doc = _load_yaml(yaml_path)
            if not isinstance(doc, dict) or not _is_srd_doc(doc):
                continue
            if pack in _FEATURE_PACKS and doc.get("type") != "feat":
                continue
            doc_id = str(doc.get("_id") or "")
            if not doc_id:
                continue
            uuid = f"Compendium.dnd5e.{pack}.Item.{doc_id}"
            index[uuid] = GrantRef(ref_type=ref_type, slug=_slug(doc, yaml_path))
    return index


@functools.cache
def _foundry_pinned_sha() -> str:
    """Foundry pack pinned SHA from PINS.json. Embedded in provenance URLs so
    ``source_url`` stays stable as upstream evolves."""
    pins_path = ROOT / "raw_sources" / "PINS.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    return str(pins["foundry"]["commit"])


def _provenance(yaml_path: Path, ingest_date: date, ingest_version: str) -> Provenance:
    # Preserve the full path layout under `_source/` so nested pack dirs
    # (items/weapon/, monsters/aberration/, …) appear in the provenance URL
    # exactly as they do upstream.
    parts = yaml_path.parts
    try:
        idx = parts.index("_source")
        relative = "/".join(parts[idx + 1 :])
    except ValueError:
        relative = f"{yaml_path.parent.name}/{yaml_path.name}"
    sha = _foundry_pinned_sha()
    return Provenance(
        source="foundry",
        source_url=f"https://github.com/foundryvtt/dnd5e/blob/{sha}/packs/_source/{relative}",
        ingest_date=ingest_date,
        ingest_version=ingest_version,
        srd_version=frozenset({"5.2"}),
    )


def _slug(doc: dict[str, Any], fallback: Path) -> str:
    # Prefer system.identifier (a clean kebab slug in real Foundry items, e.g.
    # "longsword"). Monsters lack a top-level identifier and their _id is a
    # random 16-char mixed-case alphanumeric blob (e.g. "shhHtE7b92PefCWB") —
    # in that case the clean SRD slug lives in the filename. Legacy fixture
    # docs may use _id as a clean slug (e.g. "longsword", "chainShirt").
    system = doc.get("system") or {}
    identifier = system.get("identifier")
    if identifier:
        raw: str = str(identifier)
    else:
        _id = doc.get("_id")
        if _id and _is_foundry_random_id(str(_id)):
            raw = fallback.stem
        else:
            raw = str(_id) if _id else fallback.stem
    # Split on camelCase boundaries before normalizing separators so legacy
    # camelCase _ids (chainShirt → chain-shirt) kebab cleanly. Real
    # identifiers are already kebab and pass through unchanged.
    kebab = _CAMEL_BOUNDARY.sub("-", raw)
    return kebab.lower().replace("_", "-").replace(" ", "-")


def _is_foundry_random_id(value: str) -> bool:
    # Foundry random IDs are exactly 16 alphanumeric characters with no
    # separators (e.g. "shhHtE7b92PefCWB", "6oc29m5uzzzb0pk3"). Real SRD slugs
    # at that length always contain a separator (e.g. "chain-shirt-of-thorns").
    # Legacy fixture _ids like "longsword" (9) or "chainShirt" (10) are
    # shorter than 16 and pass through.
    return len(value) == 16 and value.isalnum()


def _description(doc: dict[str, Any]) -> str:
    raw = doc.get("system", {}).get("description", {}).get("value", "") or ""
    return cleanup_prose(raw)


def _weight(system: dict[str, Any]) -> float:
    """Foundry weight is either a scalar (legacy/fixture) or
    ``{value, units}`` dict (real pack). Units are always lb in SRD content."""
    w = system.get("weight")
    if isinstance(w, dict):
        return float(w.get("value") or 0)
    return float(w or 0)


_DENOM_TO_GP = {"cp": 0.01, "sp": 0.1, "ep": 0.5, "gp": 1.0, "pp": 10.0}


def _price_gp(system: dict[str, Any]) -> float | None:
    """Convert Foundry price to gp, honoring denomination. Returns ``None`` when
    no usable price ships (e.g. magic items without a listed cost)."""
    price = system.get("price")
    if price is None:
        return None
    if isinstance(price, dict):
        value = price.get("value")
        if value is None:
            return None
        denom = (price.get("denomination") or "gp").lower()
        rate = _DENOM_TO_GP.get(denom, 1.0)
        return float(value) * rate
    # Legacy scalar fallback (fixture compatibility) — assumed gp.
    return float(price)


def _weapon_type_code(system: dict[str, Any]) -> str:
    """Weapon category code lives at either ``system.weaponType`` (legacy/
    fixture) or ``system.type.value`` (real pack)."""
    if "weaponType" in system and system["weaponType"]:
        return str(system["weaponType"])
    t = system.get("type")
    if isinstance(t, dict) and t.get("value"):
        return str(t["value"])
    return "simpleM"


def _armor_category_code(system: dict[str, Any]) -> str:
    """Armor category code lives at either ``system.armor.type`` (legacy/
    fixture) or ``system.type.value`` (real pack)."""
    armor = system.get("armor") or {}
    if armor.get("type"):
        return str(armor["type"])
    t = system.get("type")
    if isinstance(t, dict) and t.get("value"):
        return str(t["value"])
    return "light"


def _damage_parts(damage: dict[str, Any]) -> list[DamagePart]:
    """Damage parts. Foundry ships three observed shapes (per shape catalog):

    1. Legacy/fixture: ``parts: [[dice, type], ...]``.
    2. Real pack standard die: ``base: {number, denomination, types: [...], bonus}``.
    3. Real pack bonus-only (e.g. blowgun): ``base: {number: null,
       denomination: 0, bonus: "1", types: [...]}`` — flat damage, no roll.

    Magic weapons with empty ``types`` (e.g. vicious-mace) defer their damage
    type to the base weapon (looked up via ``system.type.baseItem``). The
    caller's overall pipeline doesn't have cross-item resolution yet, so we
    fall back to bludgeoning/slashing/piercing only when the slug is one of
    the few SRD magic weapons we care about; otherwise the damage_parts list
    stays empty and validation_report flags the gap.
    """
    raw_parts = damage.get("parts")
    if raw_parts:
        return [DamagePart(dice=dice, damage_type=dtype) for dice, dtype in raw_parts]
    base = damage.get("base") or {}
    number = base.get("number")
    denom = base.get("denomination")
    bonus_raw = base.get("bonus")
    types = base.get("types") or []
    if not types:
        return []
    dtype = str(types[0])
    if number and denom:
        dice = f"{number}d{denom}"
        if bonus_raw not in (None, "", 0, "0"):
            try:
                bonus = int(bonus_raw)
                if bonus:
                    dice = f"{dice}{'+' if bonus > 0 else ''}{bonus}"
            except (TypeError, ValueError):
                pass
        return [DamagePart(dice=dice, damage_type=dtype)]
    # Bonus-only (blowgun): number/denom absent, bonus carries the flat damage.
    if bonus_raw not in (None, "", 0, "0"):
        try:
            bonus = int(bonus_raw)
            if bonus > 0:
                return [DamagePart(dice=str(bonus), damage_type=dtype)]
        except (TypeError, ValueError):
            pass
    return []


def _versatile_damage_srd(slug: str, parts: list[DamagePart]) -> DamagePart | None:
    """SRD fallback: when Foundry's ``versatile`` block is empty but the
    weapon has the ``versatile`` property, look up the upgraded die from the
    SRD table by base-weapon slug."""
    dice = _SRD_VERSATILE_DICE.get(slug)
    if dice is None:
        return None
    damage_type = parts[0].damage_type if parts else "slashing"
    return DamagePart(dice=dice, damage_type=damage_type)


def _versatile_damage(damage: dict[str, Any], parts: list[DamagePart]) -> DamagePart | None:
    versatile = damage.get("versatile")
    if isinstance(versatile, str) and versatile:
        return DamagePart(
            dice=versatile,
            damage_type=parts[0].damage_type if parts else "slashing",
        )
    if isinstance(versatile, dict):
        number = versatile.get("number")
        denom = versatile.get("denomination")
        if number and denom:
            types = versatile.get("types") or []
            damage_type = (
                str(types[0]) if types else (parts[0].damage_type if parts else "slashing")
            )
            return DamagePart(dice=f"{number}d{denom}", damage_type=damage_type)
    return None


_ATTUNEMENT_DESC_RE = re.compile(
    r"requires attunement\s*(by [^).]*)?",
    re.IGNORECASE,
)


def _attunement(system: dict[str, Any]) -> tuple[bool, str | None]:
    """Foundry's ``system.attunement`` is a BOOL-shaped flag ('required',
    'optional', '') — it says whether attunement is needed, not by whom.

    Some Foundry magic items leave ``attunement`` blank even when the SRD
    description states "requires attunement" (e.g. arrow-catching-shield).
    Fall back to parsing the description prose: if it contains the phrase
    "requires attunement", flip the bool true and capture the optional
    "by ..." constraint for ``attunement_constraint``.
    """
    raw = system.get("attunement")
    raw_str = str(raw or "").strip().lower()
    flag_required = raw_str not in {"", "none", "false"}

    # Always probe the description — it's authoritative when Foundry's flag is
    # blank, and it carries the "by ..." constraint phrase the flag never has.
    desc_raw = (system.get("description") or {}).get("value") or ""
    # Strip HTML before matching so tags don't split the phrase.
    desc_plain = re.sub(r"<[^>]+>", " ", desc_raw)
    match = _ATTUNEMENT_DESC_RE.search(desc_plain)
    constraint: str | None = None
    if match:
        flag_required = True
        captured = match.group(1)
        if captured:
            constraint = re.sub(r"\s+", " ", captured).strip().rstrip(".")
    return flag_required, constraint


def _passive_effects(doc: dict[str, Any]) -> list[PassiveEffect]:
    """Translate Foundry's top-level ``effects[]`` into ``PassiveEffect``
    entries. Foundry-side ActiveEffect docs carry passive modifiers (e.g.
    Cloak of Protection's AC+1 / save+1, Gauntlets of Ogre Power's
    Strength=19) as a ``changes[]`` array of key/mode/value triples.

    Per-entry ``origin``, ``tint``, ``flags``, ``_stats``, ``img``,
    ``sort``, ``type``, ``system`` etc. are Foundry bookkeeping that don't
    carry SRD semantics — we drop them. ``_id`` and ``statuses`` are
    preserved: the resolver keys condition application off the Foundry
    status slug and needs a stable per-effect id. The surviving fields are
    the ones a resolver needs to apply the effect.
    """
    raw_effects = doc.get("effects")
    if not isinstance(raw_effects, list):
        return []
    out: list[PassiveEffect] = []
    for entry in raw_effects:
        if not isinstance(entry, dict):
            continue
        raw_changes = entry.get("changes") or []
        changes: list[PassiveEffectChange] = []
        if isinstance(raw_changes, list):
            for ch in raw_changes:
                if not isinstance(ch, dict):
                    continue
                key = ch.get("key")
                if not key:
                    continue
                try:
                    mode = int(ch.get("mode") or 0)
                except (TypeError, ValueError):
                    mode = 0
                value = ch.get("value")
                priority_raw = ch.get("priority")
                try:
                    priority = int(priority_raw) if priority_raw is not None else None
                except (TypeError, ValueError):
                    priority = None
                changes.append(
                    PassiveEffectChange(
                        key=str(key),
                        mode=mode,
                        value="" if value is None else str(value),
                        priority=priority,
                    )
                )
        duration_raw = entry.get("duration")
        duration: dict[str, Any] | None = None
        if isinstance(duration_raw, dict):
            # Drop nulls/empty strings so byte-stable JSON stays compact.
            duration = {k: v for k, v in duration_raw.items() if v not in (None, "")}
            if not duration:
                duration = None
        raw_statuses = entry.get("statuses")
        statuses = [str(s) for s in raw_statuses] if isinstance(raw_statuses, list) else []
        out.append(
            PassiveEffect(
                id=str(entry.get("_id") or ""),
                name=str(entry.get("name") or ""),
                description=str(entry.get("description") or ""),
                changes=changes,
                statuses=statuses,
                duration=duration,
                disabled=bool(entry.get("disabled") or False),
                transfer=bool(entry.get("transfer") if "transfer" in entry else True),
            )
        )
    return out


def _activity_range_value(system: dict[str, Any]) -> int | None:
    """Foundry hides reach-weapon range (10 ft for glaive/halberd/whip) in
    the *activity's* range block, not at ``system.range``. Probe the first
    weapon-attack activity's range and return ``value`` as int when present.
    Returns None when the activity tree has no usable range value."""
    activities = system.get("activities")
    if not isinstance(activities, dict):
        return None
    for entry in activities.values():
        if not isinstance(entry, dict):
            continue
        rng = entry.get("range")
        if not isinstance(rng, dict):
            continue
        val = rng.get("value")
        if val in (None, ""):
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _rarity(doc: dict[str, Any]) -> ItemRarity:
    raw = doc.get("system", {}).get("rarity") or "common"
    # Foundry uses camelCase ("veryRare"); enum is snake_case ("very_rare").
    normalised = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", raw).lower()
    try:
        return ItemRarity(normalised)
    except ValueError:
        return ItemRarity.COMMON


def translate_weapon_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Weapon:
    doc = _load_yaml(yaml_path)
    system = doc["system"]
    damage = system.get("damage", {}) or {}
    parts = _damage_parts(damage)
    versatile_damage = _versatile_damage(damage, parts)
    slug_str = _slug(doc, yaml_path)
    weapon_type = _WEAPON_TYPE_MAP.get(_weapon_type_code(system), "simple_melee")
    raw_props = system.get("properties") or []
    if isinstance(raw_props, dict):
        # Newer Foundry sometimes uses {"ver": true, "fin": true, ...}
        raw_props = [k for k, v in raw_props.items() if v]
    props = frozenset(_WEAPON_PROPERTY_MAP[p] for p in raw_props if p in _WEAPON_PROPERTY_MAP)
    if versatile_damage is None and WeaponProperty.VERSATILE in props:
        # Foundry didn't structurally encode the upgraded die — fall back to
        # the SRD table.
        base_item = (
            ((system.get("type") or {}).get("baseItem"))
            if isinstance(system.get("type"), dict)
            else None
        )
        lookup_key = str(base_item or slug_str).lower()
        versatile_damage = _versatile_damage_srd(lookup_key, parts)
    range_doc = system.get("range") or {}
    range_val = range_doc.get("value")
    range_long = range_doc.get("long")
    has_thrown = WeaponProperty.THROWN in props
    # Foundry stashes non-default weapon range on the *activity's* range block
    # rather than at ``system.range``. This covers two cases:
    #   * Reach weapons (glaive, halberd, pike, lance, whip) — range.value=10
    #   * Magic weapons that attack at extended range (dancing-rapier 30 ft,
    #     longsword-of-sharpness 10 ft, hammer-of-thunderbolts 20 ft)
    # Pull the activity range forward when system.range is missing so canonical
    # preserves the structural value, regardless of which property triggered it.
    if range_val is None or range_val == 0:
        activity_val = _activity_range_value(system)
        if activity_val is not None and activity_val > 5:
            range_val = activity_val
    if weapon_type.endswith("ranged") or (has_thrown and range_val is not None):
        # Thrown melee weapons keep kind="melee" — semantically still melee
        # weapons that *can* be thrown — but preserve their range value/long.
        rng_kind = "ranged" if weapon_type.endswith("ranged") else "melee"
        rng = Range(
            kind=rng_kind,
            value=range_val,
            units=RangeUnits.FEET if range_val is not None else None,
            long=range_long,
        )
    elif range_val is not None and range_val > 5:
        # Melee reach weapon (no THROWN prop) — preserve range.value at melee kind.
        rng = Range(
            kind="melee",
            value=range_val,
            units=RangeUnits.FEET,
            long=range_long,
        )
    else:
        rng = Range(kind="melee")
    requires_attunement, attunement_constraint = _attunement(system)
    magical_bonus_raw = system.get("magicalBonus")
    try:
        magical_bonus = int(magical_bonus_raw or 0)
    except (TypeError, ValueError):
        magical_bonus = 0
    # 2024 SRD weapon mastery — flat slug at ``system.mastery`` ("sap", "graze",
    # "nick", …). Empty string (unarmed-strike, magic weapons) and absence both
    # mean "no mastery" → None.
    mastery_raw = system.get("mastery")
    mastery = mastery_raw.strip() or None if isinstance(mastery_raw, str) else None
    return Weapon(
        slug=slug_str,
        name=doc["name"],
        description=_description(doc),
        weight=_weight(system),
        cost_gp=_price_gp(system),
        rarity=_rarity(doc),
        requires_attunement=requires_attunement,
        attunement_constraint=attunement_constraint,
        weapon_category=weapon_type,
        damage_parts=parts,
        versatile_damage=versatile_damage,
        properties=props,
        range=rng,
        magical_bonus=max(0, magical_bonus),
        mastery=mastery,
        activities=_translate_activities(system),
        passive_effects=_passive_effects(doc),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


def translate_armor_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Armor:
    doc = _load_yaml(yaml_path)
    system = doc["system"]
    armor = system.get("armor", {}) or {}
    requires_attunement, attunement_constraint = _attunement(system)
    armor_magical_bonus_raw = armor.get("magicalBonus")
    try:
        armor_magical_bonus = int(armor_magical_bonus_raw or 0)
    except (TypeError, ValueError):
        armor_magical_bonus = 0
    return Armor(
        slug=_slug(doc, yaml_path),
        name=doc["name"],
        description=_description(doc),
        weight=_weight(system),
        cost_gp=_price_gp(system),
        rarity=_rarity(doc),
        requires_attunement=requires_attunement,
        attunement_constraint=attunement_constraint,
        armor_category=_ARMOR_TYPE_MAP.get(_armor_category_code(system), ArmorCategory.LIGHT),
        base_ac=int(armor.get("value") or 10),
        dex_bonus_max=armor.get("dex"),
        # Foundry ships stealth disadvantage as a tagged entry in
        # ``system.properties`` (e.g. ``properties: [stealthDisadvantage]``)
        # for the 2014 SRD pack. Legacy fixtures use the boolean
        # ``system.stealth``. Accept either signal.
        stealth_disadvantage=(
            "stealthDisadvantage" in (system.get("properties") or []) or bool(system.get("stealth"))
        ),
        strength_min=system.get("strength"),
        magical_bonus=max(0, armor_magical_bonus),
        activities=_translate_activities(system),
        passive_effects=_passive_effects(doc),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


_SIZE_MAP = {
    "tiny": CreatureSize.TINY,
    "sm": CreatureSize.SMALL,
    "med": CreatureSize.MEDIUM,
    "lg": CreatureSize.LARGE,
    "huge": CreatureSize.HUGE,
    "grg": CreatureSize.GARGANTUAN,
}

_SKILL_KEY_MAP = {
    "acr": "acrobatics",
    "ani": "animal_handling",
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
    "slt": "sleight_of_hand",
    "ste": "stealth",
    "sur": "survival",
}

# Each skill's governing ability (5e SRD). Used to compute the bonus from
# Foundry's rank (0/1/2) since Foundry doesn't ship the final modifier.
_SKILL_ABILITY = {
    "acr": "dex",
    "ani": "wis",
    "arc": "int",
    "ath": "str",
    "dec": "cha",
    "his": "int",
    "ins": "wis",
    "itm": "cha",
    "inv": "int",
    "med": "wis",
    "nat": "int",
    "prc": "wis",
    "prf": "cha",
    "per": "cha",
    "rel": "int",
    "slt": "dex",
    "ste": "dex",
    "sur": "wis",
}


def _ability_mod(score: int) -> int:
    return (score - 10) // 2


def _sense_value(raw: Any) -> int | None:
    """Foundry ships 0 for senses the creature lacks. Schema uses None as
    'unavailable'; 0 would falsely say 'has the sense with range 0 ft'."""
    if raw is None:
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


_LANGUAGE_SLUG_EXPAND = {
    "deep": "Deep Speech",
    "cant": "Thieves' Cant",
    "druidic": "Druidic",
    "undercommon": "Undercommon",
    "abyssal": "Abyssal",
    "celestial": "Celestial",
    "common": "Common",
    "draconic": "Draconic",
    "dwarvish": "Dwarvish",
    "elvish": "Elvish",
    "giant": "Giant",
    "gnomish": "Gnomish",
    "goblin": "Goblin",
    "halfling": "Halfling",
    "infernal": "Infernal",
    "orc": "Orc",
    "primordial": "Primordial",
    "sylvan": "Sylvan",
    "auran": "Auran",
    "aquan": "Aquan",
    "ignan": "Ignan",
    "terran": "Terran",
}


def _languages(traits: dict[str, Any]) -> list[str]:
    """Foundry languages ship as a nested dict::

        languages:
          value: ["abyssal"]            # structured slug list
          custom: ""                     # free text overrides / extras
          communication:
            telepathy: {value: 120, units: ft}

    All three sources flow into canonical ``languages: list[str]``. Short
    slugs in ``value`` expand to full SRD names (``deep`` → ``Deep Speech``).
    Telepathy renders as ``"telepathy 120 ft."`` (matches the SRD wording
    5e-bits ships). The literal ``"custom"`` sentinel that some packs leak
    into ``value`` is filtered.
    """
    raw = traits.get("languages")
    if raw is None:
        return []
    if isinstance(raw, dict):
        out: list[str] = []
        value = raw.get("value")
        if isinstance(value, list):
            for v in value:
                s = str(v).strip()
                if not s or s == "custom":
                    continue
                out.append(_LANGUAGE_SLUG_EXPAND.get(s.lower(), s))
        custom = raw.get("custom")
        if custom and isinstance(custom, str) and custom.strip():
            # Split on common separators so combined ``"Giant Eagle; Common..."``
            # custom blobs surface as discrete language entries (matches the
            # 5e-bits per-language list shape).
            for chunk in re.split(r"[;,]\s*", custom.strip()):
                chunk = chunk.strip()
                if chunk:
                    out.append(chunk)
        communication = raw.get("communication") or {}
        telepathy = communication.get("telepathy") or {}
        if isinstance(telepathy, dict):
            tval = telepathy.get("value")
            units = telepathy.get("units") or "ft"
            if tval:
                out.append(f"telepathy {tval} {units}.")
        return out
    if isinstance(raw, list):
        return [str(v) for v in raw if v and str(v) != "custom"]
    return []


def _trait_list(traits: dict[str, Any], key: str) -> list[str]:
    """Foundry traits ship as either bare lists (legacy fixture) or
    ``{value: [...], bypasses: [...], custom: ...}`` dicts (real pack). The
    canonical layer wants the actual type strings — read ``.value`` when the
    shape is a dict, never the dict keys."""
    raw = traits.get(key)
    if raw is None:
        return []
    if isinstance(raw, dict):
        value = raw.get("value") or []
        return [str(v) for v in value]
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return []


def _monster_ac(ac_doc: dict[str, Any]) -> int | None:
    """Pick the first authoritative AC value Foundry provides. Returns ``None``
    when Foundry omits a usable flat value — silently defaulting to 10 ships
    wrong data for armored monsters (deferred: derive AC from equipped armor
    + dex at runtime; see commit + backlog)."""
    flat = ac_doc.get("flat")
    if isinstance(flat, int) and flat > 0:
        return flat
    formula = ac_doc.get("formula")
    if isinstance(formula, str) and formula.strip():
        try:
            parsed = int(formula.strip())
        except ValueError:
            return None
        if parsed > 0:
            return parsed
    return None


def _proficiency_bonus(attrs: dict[str, Any], cr: float) -> int:
    """SRD proficiency bonus scales with CR: +2 (CR 0-4), +3 (5-8), +4 (9-12),
    +5 (13-16), +6 (17-20), +7 (21-24), +8 (25-28), +9 (29-30)."""
    prof = attrs.get("prof")
    if isinstance(prof, int) and prof > 0:
        return prof
    cr_ceil = math.ceil(max(cr, 0))
    return 2 + max(0, (cr_ceil - 1) // 4)


_ACTIVATION_TYPE_TO_KIND: dict[str, MonsterActionKind] = {
    "action": MonsterActionKind.ACTION,
    "bonus": MonsterActionKind.BONUS_ACTION,
    "reaction": MonsterActionKind.REACTION,
    "legendary": MonsterActionKind.LEGENDARY,
    "lair": MonsterActionKind.LAIR,
    "regional": MonsterActionKind.REGIONAL,
    "special": MonsterActionKind.SPECIAL,
    # Crew, mythic, and other niche signals fall through to SPECIAL via the
    # heuristic on the caller side.
}


def _slug_from_name(name: str) -> str:
    kebab = _CAMEL_BOUNDARY.sub("-", name)
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", kebab).strip("-")
    return cleaned.lower()


def _first_activation(activities: Any) -> dict[str, Any] | None:
    """Foundry stores activities as a dict keyed by activity id. The activation
    signal (action/bonus/reaction/legendary/lair) lives on the first entry's
    ``activation`` block. Returns the activation dict or ``None`` for passive
    traits whose ``activities`` is an empty dict."""
    if not isinstance(activities, dict) or not activities:
        return None
    for entry in activities.values():
        if isinstance(entry, dict):
            activation = entry.get("activation")
            if isinstance(activation, dict):
                return activation
    return None


def _recharge_formula(uses: dict[str, Any]) -> str | None:
    """Foundry encodes recharge as a recovery entry with ``period == 'recharge'``
    and ``formula`` carrying the threshold (e.g. ``'5'`` → recharge on 5-6).
    Surface the formula as ``"5-6"`` / ``"6"`` so consumers don't reinvent the
    SRD shorthand."""
    recovery = uses.get("recovery")
    if not isinstance(recovery, list):
        return None
    for entry in recovery:
        if not isinstance(entry, dict):
            continue
        if entry.get("period") != "recharge":
            continue
        formula = str(entry.get("formula") or "").strip()
        if not formula:
            continue
        try:
            low = int(formula)
        except ValueError:
            return formula
        return f"{low}-6" if low < 6 else "6"
    return None


def _daily_uses_max(uses: dict[str, Any]) -> int | None:
    """Foundry encodes per-day usage caps as ``system.uses.max`` (string int,
    e.g. ``"3"``) with a recovery entry ``{period: "day", type: "recoverAll"}``.
    Surface the cap as an int so downstream consumers can rate-limit. Returns
    None when the item isn't day-limited."""
    recovery = uses.get("recovery")
    if not isinstance(recovery, list):
        return None
    if not any(isinstance(e, dict) and e.get("period") == "day" for e in recovery):
        return None
    raw_max = uses.get("max")
    if raw_max in (None, ""):
        return None
    try:
        value = int(str(raw_max).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _resolve_monster_activities(system: dict[str, Any]) -> list[Activity]:
    """Translate an embedded monster item's ``system.activities`` and resolve
    weapon base damage inline.

    2024 ``actors24`` weapon items keep their attack damage at
    ``system.damage.base`` and the attack activity defers to it via
    ``damage.includeBase: true``. The 2014 UUID-reference deferral no longer
    applies — the base damage is local — so we fold the resolved
    ``system.damage.base`` into the attack activity's ``parts`` to produce a
    self-contained canonical activity.

    An attack may carry BOTH base weapon damage and rider parts (e.g. Wight's
    Necrotic Sword: slashing base + necrotic rider). ``includeBase`` is the
    sole trigger for base injection — it is not gated on ``parts`` being empty —
    so the base part is preserved alongside any riders. Ordering is
    deterministic: base first, then the activity's existing rider parts."""
    activities = _translate_activities(system)
    base = (system.get("damage") or {}).get("base")
    if not isinstance(base, dict):
        return activities
    resolved_part = DamagePartBlock(
        number=base.get("number"),
        denomination=base.get("denomination"),
        bonus=str(base.get("bonus") or ""),
        types=list(base.get("types") or []),
    )
    out: list[Activity] = []
    for activity in activities:
        if isinstance(activity, AttackActivity) and activity.damage.include_base:
            merged_parts = [resolved_part, *activity.damage.parts]
            new_damage = activity.damage.model_copy(update={"parts": merged_parts})
            activity = activity.model_copy(update={"damage": new_damage})
        out.append(activity)
    return out


def _build_monster_action(item: dict[str, Any]) -> tuple[MonsterAction, MonsterActionKind]:
    """Translate one embedded item document into a ``MonsterAction``. Returns
    the action plus its resolved kind so the caller can bucket it."""
    name = str(item.get("name") or "Unnamed")
    system = item.get("system") or {}
    activation = _first_activation(system.get("activities")) or {}
    raw_type = str(activation.get("type") or "").strip().lower()
    kind = _ACTIVATION_TYPE_TO_KIND.get(raw_type, MonsterActionKind.SPECIAL)
    description = cleanup_prose(((system.get("description") or {}).get("value")) or "")
    identifier = system.get("identifier") or _slug_from_name(name)
    uses = system.get("uses") or {}
    recharge = _recharge_formula(uses)
    uses_per_day = _daily_uses_max(uses)
    legendary_cost: int | None = None
    if kind is MonsterActionKind.LEGENDARY:
        cost_raw = activation.get("value")
        try:
            cost_int = int(cost_raw) if cost_raw not in (None, "") else 1
        except (TypeError, ValueError):
            cost_int = 1
        legendary_cost = max(1, cost_int)
    action = MonsterAction(
        slug=str(identifier),
        name=name,
        kind=kind,
        description=description,
        activities=_resolve_monster_activities(system),
        recharge=recharge,
        uses_per_day=uses_per_day,
        legendary_cost=legendary_cost,
    )
    return action, kind


def _monster_actions(
    doc: dict[str, Any],
) -> tuple[list[MonsterAction], list[MonsterAction], list[MonsterAction], list[MonsterAction]]:
    """Partition a monster's embedded ``items[]`` into the four canonical
    action buckets. Foundry NPC packs store actions/traits/legendary actions
    as sub-documents in a top-level ``items`` array; each carries a
    ``system.activities.<key>.activation.type`` signal that maps to the SRD
    action category. Equipment items (``type: equipment``) are excluded — they
    represent worn gear, not actions."""
    actions: list[MonsterAction] = []
    legendary_actions: list[MonsterAction] = []
    lair_actions: list[MonsterAction] = []
    special_abilities: list[MonsterAction] = []
    raw_items = doc.get("items")
    if not isinstance(raw_items, list):
        return actions, legendary_actions, lair_actions, special_abilities
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        # Equipment is gear the monster wears (armor, shields), not an action.
        # Spells are deferred — spellcasting integration is engine-side work.
        if item_type in {"equipment", "spell", "container", "consumable"}:
            continue
        if item_type not in {"weapon", "feat"}:
            continue
        action, kind = _build_monster_action(item)
        if kind is MonsterActionKind.LEGENDARY:
            legendary_actions.append(action)
        elif kind is MonsterActionKind.LAIR or kind is MonsterActionKind.REGIONAL:
            lair_actions.append(action)
        elif kind is MonsterActionKind.SPECIAL:
            special_abilities.append(action)
        else:
            actions.append(action)
    return actions, legendary_actions, lair_actions, special_abilities


def translate_monster_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Monster:
    doc = _load_yaml(yaml_path)
    system = doc["system"]
    details = system.get("details", {})
    attrs = system.get("attributes", {})
    traits = system.get("traits", {})
    abilities = system.get("abilities", {})

    creature_type_raw = (details.get("type", {}).get("value") or "humanoid").lower()
    creature_type = CreatureType(creature_type_raw)
    creature_size = _SIZE_MAP.get(traits.get("size") or "med", CreatureSize.MEDIUM)

    ability_scores = AbilityScores(
        str=abilities.get("str", {}).get("value", 10),
        dex=abilities.get("dex", {}).get("value", 10),
        con=abilities.get("con", {}).get("value", 10),
        int=abilities.get("int", {}).get("value", 10),
        wis=abilities.get("wis", {}).get("value", 10),
        cha=abilities.get("cha", {}).get("value", 10),
    )

    cr_value = float(details.get("cr") or 0)
    prof_bonus = _proficiency_bonus(attrs, cr_value)

    # Foundry saves: abilities.<ab>.proficient is 0/1; the actual save bonus
    # is NOT pre-computed at abilities.<ab>.save (which stays null). Derive
    # it: ability_mod + prof when proficient, else None ("not proficient").
    save_kwargs: dict[str, int] = {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        entry = abilities.get(ab) or {}
        if int(entry.get("proficient") or 0) >= 1:
            score = int(entry.get("value") or 10)
            bonus_extra = int(((entry.get("bonuses") or {}).get("save") or 0) or 0)
            save_kwargs[ab] = _ability_mod(score) + prof_bonus + bonus_extra
    saving_throws = SavingThrowProficiencies(**save_kwargs)

    # Foundry skills: system.skills.<short>.value is a rank (0=not proficient,
    # 1=proficient, 2=expertise), NOT the SRD bonus. Compute the bonus and
    # OMIT skills the creature isn't proficient in (rank == 0).
    skill_kwargs: dict[str, int] = {}
    for short, entry in (system.get("skills") or {}).items():
        canonical = _SKILL_KEY_MAP.get(short)
        if canonical is None:
            continue
        rank = int(entry.get("value") or 0)
        if rank <= 0:
            continue
        ability = _SKILL_ABILITY.get(short)
        if ability is None:
            continue
        ability_score = int((abilities.get(ability) or {}).get("value") or 10)
        skill_bonus_extra = int(entry.get("bonus") or 0)
        skill_kwargs[canonical] = (
            _ability_mod(ability_score) + rank * prof_bonus + skill_bonus_extra
        )
    skills = SkillProficiencies(**skill_kwargs)

    movement_doc = attrs.get("movement", {}) or {}
    movement = Movement(
        walk=movement_doc.get("walk"),
        fly=movement_doc.get("fly"),
        swim=movement_doc.get("swim"),
        burrow=movement_doc.get("burrow"),
        climb=movement_doc.get("climb"),
        hover=bool(movement_doc.get("hover")),
    )

    senses_doc = attrs.get("senses", {}) or {}
    # 2024 actors24 nest the per-sense ranges under ``senses.ranges`` while the
    # legacy 2014 packs put them flat on ``senses``. Prefer the nested 2024
    # shape, then fall back so both editions resolve.
    sense_ranges = senses_doc.get("ranges") or senses_doc
    # Foundry doesn't ship passive_perception; derive from 10 + perception
    # bonus (if proficient) or 10 + wis_mod (if not).
    wis_score = int((abilities.get("wis") or {}).get("value") or 10)
    perception_bonus = skill_kwargs.get("perception")
    if perception_bonus is not None:
        passive_perception = 10 + perception_bonus
    else:
        passive_perception = 10 + _ability_mod(wis_score)
    senses = Senses(
        darkvision=_sense_value(sense_ranges.get("darkvision")),
        blindsight=_sense_value(sense_ranges.get("blindsight")),
        tremorsense=_sense_value(sense_ranges.get("tremorsense")),
        truesight=_sense_value(sense_ranges.get("truesight")),
        passive_perception=passive_perception,
    )

    ac_doc = attrs.get("ac", {}) or {}
    hp_doc = attrs.get("hp", {}) or {}

    actions, legendary_actions, lair_actions, special_abilities = _monster_actions(doc)

    return Monster(
        slug=_slug(doc, yaml_path),
        name=doc["name"],
        description=_description(doc),
        creature_type=creature_type,
        creature_size=creature_size,
        alignment=details.get("alignment"),
        ac=_monster_ac(ac_doc),
        hp=int(hp_doc.get("value") or hp_doc.get("max") or 1),
        hp_dice=hp_doc.get("formula") or "",
        ability_scores=ability_scores,
        movement=movement,
        senses=senses,
        cr=cr_value,
        proficiency_bonus=prof_bonus,
        saving_throws=saving_throws,
        skills=skills,
        damage_resistances=_trait_list(traits, "dr"),
        damage_immunities=_trait_list(traits, "di"),
        damage_vulnerabilities=_trait_list(traits, "dv"),
        condition_immunities=_trait_list(traits, "ci"),
        languages=_languages(traits),
        actions=actions,
        legendary_actions=legendary_actions,
        lair_actions=lair_actions,
        special_abilities=special_abilities,
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


# Pack-subdir → item kind. The Foundry pack layout puts magic-item categories
# (potion, scroll, wand, ring, rod) in their own subdirs; mundane gear lives in
# equipment/tool/loot/ammunition/food/poison/spellcasting-focus. Trinket is
# heterogeneous (mixes magic figurines with mundane curios) so it falls back to
# the rarity+attunement heuristic. ``None`` signals "decide per-entry".
_ITEM_KIND_BY_PACK_SUBDIR: dict[str, str | None] = {
    "potion": "magic_item",
    "scroll": "magic_item",
    "wand": "magic_item",
    "ring": "magic_item",
    "rod": "magic_item",
    "equipment": "item",
    "tool": "item",
    "loot": "item",
    "ammunition": "item",
    "food": "item",
    "poison": "item",
    "spellcasting-focus": "item",
    # Container pack mixes mundane sacks/quivers (Item) with attuned magic
    # bags (Bag of Holding, Handy Haversack) — fall back to the heuristic per
    # entry so attunement/rarity promotes the right ones.
    "container": None,
    "trinket": None,  # rarity+attunement heuristic
}


def _pack_subdir(yaml_path: Path) -> str | None:
    """Pack subdir under ``packs/_source/items/`` (e.g. ``potion``, ``trinket``).

    Real Foundry layout: ``.../packs/_source/items/<subdir>/<slug>.yml``.
    Test fixtures may flatten or vary; return None when we can't identify."""
    parts = yaml_path.parts
    if "items" in parts:
        idx = parts.index("items")
        if idx + 1 < len(parts) - 1:  # there's at least one dir between items/ and the file
            return parts[idx + 1]
    return None


def translate_generic_item_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Item | MagicItem:
    """Translator for non-weapon, non-armor item categories (trinket, equipment,
    loot, potion, tool, ring, ammunition, wand, spellcasting-focus, scroll, rod,
    poison, food).

    Classification is by pack-subdir taxonomy (``_ITEM_KIND_BY_PACK_SUBDIR``):
    known magic-item categories (potion/scroll/wand/ring/rod) emit ``MagicItem``
    regardless of rarity (a common Potion of Healing is still a magic item per
    the SRD). Known mundane categories emit ``Item``. ``trinket`` is mixed and
    falls back to the rarity+attunement heuristic.

    The explicit ``item_kind`` discriminator field round-trips through JSON so
    the loader recovers the correct Python type without structural sniffing.
    """
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    requires_attunement, attunement_constraint = _attunement(system)
    rarity = _rarity(doc)

    base_kwargs: dict[str, Any] = dict(
        slug=_slug(doc, yaml_path),
        name=doc.get("name", ""),
        description=_description(doc),
        weight=_weight(system),
        cost_gp=_price_gp(system),
        rarity=rarity,
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
        activities=_translate_activities(system),
        passive_effects=_passive_effects(doc),
        requires_attunement=requires_attunement,
        attunement_constraint=attunement_constraint,
    )

    subdir = _pack_subdir(yaml_path)
    mapped_kind = _ITEM_KIND_BY_PACK_SUBDIR.get(subdir) if subdir is not None else None
    # Magic-item subdirs (potion/scroll/wand/ring/rod) — always magic_item.
    if mapped_kind == "magic_item":
        return MagicItem(**base_kwargs)
    # Mundane-baseline subdirs (equipment/tool/loot/ammunition/food/poison/
    # spellcasting-focus) + unknown/trinket: rarity/attunement promotes to
    # magic_item. Catches Foundry-mixed packs where magic items sit alongside
    # mundane gear — amulet-of-health (uncommon) and ioun-stone-of-absorption
    # (rare) live in equipment/ but are clearly magic items by SRD.
    if requires_attunement or rarity != ItemRarity.COMMON:
        return MagicItem(**base_kwargs)
    return Item(**base_kwargs)


# ---------------------------------------------------------------------------
# Spells / classes / subclasses / species (Phase 7a PR 2)
# ---------------------------------------------------------------------------


def _name(doc: dict[str, Any]) -> str:
    return str(doc.get("name") or "")


_SPELL_COMPONENT_PROPS = {
    "vocal": SpellComponent.VOCAL,
    "somatic": SpellComponent.SOMATIC,
    "material": SpellComponent.MATERIAL,
}


def _spell_components(props: list[Any]) -> tuple[frozenset[SpellComponent], bool, bool]:
    """Parse Foundry's ``system.properties`` list into the V/S/M frozenset plus
    ``ritual`` and ``concentration`` flags. Unknown property tokens are silently
    dropped — they're either future-pack metadata or already-handled
    activity-level signals (e.g. ``mgc`` for "is magical")."""
    components: set[SpellComponent] = set()
    ritual = False
    concentration = False
    for prop in props or []:
        p = str(prop).lower()
        if p in _SPELL_COMPONENT_PROPS:
            components.add(_SPELL_COMPONENT_PROPS[p])
        elif p == "ritual":
            ritual = True
        elif p == "concentration":
            concentration = True
    return frozenset(components), ritual, concentration


def _casting_time(activation: dict[str, Any]) -> CastingTime:
    raw_type = str(activation.get("type") or "action").lower()
    try:
        unit = CastingTimeUnit(raw_type)
    except ValueError:
        unit = CastingTimeUnit.SPECIAL
    value_raw = activation.get("value")
    try:
        value = int(value_raw) if value_raw not in (None, "") else 1
    except (TypeError, ValueError):
        value = 1
    condition = str(activation.get("condition") or "")
    return CastingTime(unit=unit, value=max(0, value), condition=condition)


_SPELL_RANGE_UNITS_MAP = {
    "self": SpellRangeUnits.SELF,
    "touch": SpellRangeUnits.TOUCH,
    "ft": SpellRangeUnits.FEET,
    "mi": SpellRangeUnits.MILES,
    "any": SpellRangeUnits.ANY,
    "spec": SpellRangeUnits.SPECIAL,
    # Foundry sometimes emits an empty string for self/touch spells where
    # `special` carries the human label. Treat empty as SPECIAL so we still
    # round-trip without a schema error.
    "": SpellRangeUnits.SPECIAL,
}


def _spell_range(range_doc: dict[str, Any]) -> SpellRange:
    units_raw = str(range_doc.get("units") or "").lower()
    units = _SPELL_RANGE_UNITS_MAP.get(units_raw, SpellRangeUnits.SPECIAL)
    value_raw = range_doc.get("value")
    value: int | None = None
    if value_raw not in (None, ""):
        try:
            value = int(value_raw)
        except (TypeError, ValueError):
            value = None
    special = range_doc.get("special")
    special_str = str(special).strip() if special not in (None, "") else None
    return SpellRange(units=units, value=value, special=special_str)


_SPELL_DURATION_UNITS_MAP = {
    "inst": SpellDurationUnits.INSTANT,
    "round": SpellDurationUnits.ROUND,
    "minute": SpellDurationUnits.MINUTE,
    "hour": SpellDurationUnits.HOUR,
    "day": SpellDurationUnits.DAY,
    "disp": SpellDurationUnits.UNTIL_DISPELLED,
    "dstr": SpellDurationUnits.UNTIL_DESTROYED,
    "perm": SpellDurationUnits.PERMANENT,
    "spec": SpellDurationUnits.SPECIAL,
    "": SpellDurationUnits.SPECIAL,
}


def _spell_duration(duration_doc: dict[str, Any]) -> SpellDuration:
    units_raw = str(duration_doc.get("units") or "").lower()
    units = _SPELL_DURATION_UNITS_MAP.get(units_raw, SpellDurationUnits.SPECIAL)
    value_raw = duration_doc.get("value")
    value: int | None = None
    if value_raw not in (None, ""):
        try:
            value = int(value_raw)
        except (TypeError, ValueError):
            value = None
    return SpellDuration(units=units, value=value)


def _spell_materials(materials_doc: dict[str, Any]) -> SpellMaterials:
    cost_raw = materials_doc.get("cost")
    try:
        cost = int(cost_raw) if cost_raw not in (None, "") else 0
    except (TypeError, ValueError):
        cost = 0
    supply_raw = materials_doc.get("supply")
    try:
        supply = int(supply_raw) if supply_raw not in (None, "") else 0
    except (TypeError, ValueError):
        supply = 0
    return SpellMaterials(
        value=str(materials_doc.get("value") or ""),
        consumed=bool(materials_doc.get("consumed") or False),
        cost=max(0, cost),
        supply=max(0, supply),
    )


def _spell_preparation(preparation_doc: dict[str, Any]) -> SpellPreparation:
    return SpellPreparation(
        mode=str(preparation_doc.get("mode") or ""),
        prepared=bool(preparation_doc.get("prepared") or False),
    )


def translate_spell_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Spell:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    components, ritual, concentration = _spell_components(system.get("properties") or [])
    school_raw = str(system.get("school") or "").lower()
    try:
        school = SpellSchool(school_raw)
    except ValueError:
        # Unknown school code: default to evocation to keep regen moving;
        # validation_report flags the gap.
        school = SpellSchool.EVOCATION
    level_raw = system.get("level")
    try:
        level = int(level_raw) if level_raw is not None else 0
    except (TypeError, ValueError):
        level = 0
    return Spell(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        level=max(0, level),
        school=school,
        components=components,
        ritual=ritual,
        concentration=concentration,
        casting_time=_casting_time(system.get("activation") or {}),
        range=_spell_range(system.get("range") or {}),
        duration=_spell_duration(system.get("duration") or {}),
        materials=_spell_materials(system.get("materials") or {}),
        preparation=_spell_preparation(system.get("preparation") or {}),
        activities=_translate_activities(system),
        passive_effects=_passive_effects(doc),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


# --- advancement (shared by class/subclass/race) ---

_ADVANCEMENT_TYPE_VALUES = {a.value for a in AdvancementType}


def _advancement(system: dict[str, Any]) -> list[AdvancementEntry]:
    """Parse Foundry's ``system.advancement[]`` array into typed entries.

    Unknown ``type`` values are skipped rather than crashing the whole entity —
    a Foundry-side schema bump that introduces a new advancement variant
    shouldn't break canonical regen for every class/subclass/species.
    """
    raw = system.get("advancement")
    # Most class/subclass docs serialize advancement as a list; the 2024 ranger
    # ships it as an ``_id``-keyed mapping. PyYAML preserves insertion order, so
    # taking the dict's values keeps Foundry's source order (deterministic).
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []
    out: list[AdvancementEntry] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        adv_type = str(entry.get("type") or "")
        if adv_type not in _ADVANCEMENT_TYPE_VALUES:
            continue
        level_raw = entry.get("level")
        try:
            level = int(level_raw) if level_raw is not None else 0
        except (TypeError, ValueError):
            level = 0
        out.append(
            AdvancementEntry(
                _id=str(entry.get("_id") or ""),
                type=AdvancementType(adv_type),
                level=max(0, level),
                title=str(entry.get("title") or ""),
                hint=str(entry.get("hint") or ""),
                class_restriction=str(entry.get("classRestriction") or ""),
                configuration=entry.get("configuration") or {},
                value=entry.get("value") or {},
            )
        )
    return out


# --- Species / Class derived fields from advancement ---


def _species_languages(advancement: list[AdvancementEntry]) -> list[str]:
    """Read languages from ``Trait`` advancement entries. Foundry encodes them
    as grants like ``languages:standard:common`` / ``languages:exotic:draconic``.
    The third segment is the SRD language slug."""
    out: list[str] = []
    seen: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.TRAIT:
            continue
        grants = entry.configuration.get("grants") or []
        if not isinstance(grants, list):
            continue
        for g in grants:
            parts = str(g).split(":")
            if len(parts) >= 3 and parts[0] == "languages":
                lang = parts[2]
                if lang not in seen:
                    out.append(lang)
                    seen.add(lang)
    return out


def _species_trait_grants(advancement: list[AdvancementEntry]) -> list[str]:
    """Collect Trait-advancement configuration.grants (dr/di/dv/ci/etc.), source order, deduped.
    Skips choice-based traits (grants empty) — those are char-creation selection state."""
    grants: list[str] = []
    seen: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.TRAIT:
            continue
        for g in entry.configuration.get("grants") or []:
            s = str(g)
            if s not in seen:
                seen.add(s)
                grants.append(s)
    return grants


def _class_saving_throws(
    advancement: list[AdvancementEntry],
) -> frozenset[Literal["str", "dex", "con", "int", "wis", "cha"]]:
    """Read saving-throw proficiencies from ``Trait`` advancement entries
    with ``classRestriction == "primary"``. Foundry uses that flag to mark
    the foundational class proficiency grants (every SRD class has exactly
    two); later class-feature grants like Rogue's Slippery Mind (level-15
    wis save) carry no restriction and are intentionally excluded."""
    out: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.TRAIT:
            continue
        if entry.class_restriction != "primary":
            continue
        grants = entry.configuration.get("grants") or []
        if not isinstance(grants, list):
            continue
        for g in grants:
            parts = str(g).split(":")
            if (
                len(parts) == 2
                and parts[0] == "saves"
                and parts[1] in {"str", "dex", "con", "int", "wis", "cha"}
            ):
                out.add(parts[1])
    return frozenset(out)  # type: ignore[arg-type]


def _class_subclass_identifiers(advancement: list[AdvancementEntry]) -> list[str]:
    """Extract subclass identifiers from ``Subclass``-type advancement entries.
    Foundry encodes them via ``configuration.identifier`` (preferred) or via
    nested ``configuration.items[].uuid`` references."""
    out: list[str] = []
    seen: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.SUBCLASS:
            continue
        identifier = entry.configuration.get("identifier")
        if identifier and str(identifier) not in seen:
            out.append(str(identifier))
            seen.add(str(identifier))
            continue
        items = entry.configuration.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            uuid = item.get("uuid")
            if uuid and str(uuid) not in seen:
                out.append(str(uuid))
                seen.add(str(uuid))
    return out


# --- Species ---


_FOUNDRY_SIZE_TO_CANONICAL = {
    "tiny": CreatureSize.TINY,
    "sm": CreatureSize.SMALL,
    "small": CreatureSize.SMALL,
    "med": CreatureSize.MEDIUM,
    "medium": CreatureSize.MEDIUM,
    "lg": CreatureSize.LARGE,
    "large": CreatureSize.LARGE,
    "huge": CreatureSize.HUGE,
    "grg": CreatureSize.GARGANTUAN,
    "gargantuan": CreatureSize.GARGANTUAN,
}


def _species_size(advancement: list[AdvancementEntry]) -> CreatureSize:
    """Pull species size from the first ``Size`` advancement entry's
    ``configuration.sizes``. Foundry species consistently ship at least one Size
    entry; if missing (non-SRD content), default to MEDIUM.

    A species may offer a player choice of sizes (e.g. 2024 Human ships
    ``['sm', 'med']`` — Small or Medium, chosen at creation). When the choice
    includes Medium, prefer Medium: it is the standard playable default and
    matches the 5e-bits oracle. Single-size species resolve to their only size.
    """
    for entry in advancement:
        if entry.type is not AdvancementType.SIZE:
            continue
        sizes = entry.configuration.get("sizes")
        if not (isinstance(sizes, list) and sizes):
            continue
        mapped_sizes = [
            mapped
            for raw in sizes
            if (mapped := _FOUNDRY_SIZE_TO_CANONICAL.get(str(raw).lower())) is not None
        ]
        if not mapped_sizes:
            continue
        if CreatureSize.MEDIUM in mapped_sizes:
            return CreatureSize.MEDIUM
        return mapped_sizes[0]
    return CreatureSize.MEDIUM


def _species_creature_type(system: dict[str, Any]) -> CreatureTypeRef:
    type_doc = system.get("type") or {}
    raw_value = str(type_doc.get("value") or "humanoid").lower()
    try:
        kind = CreatureKind(raw_value)
    except ValueError:
        kind = CreatureKind.HUMANOID
    return CreatureTypeRef(
        value=kind,
        subtype=str(type_doc.get("subtype") or ""),
        custom=str(type_doc.get("custom") or ""),
    )


def _movement(system: dict[str, Any]) -> Movement:
    m = system.get("movement") or {}
    return Movement(
        walk=m.get("walk") or None,
        fly=m.get("fly") or None,
        swim=m.get("swim") or None,
        burrow=m.get("burrow") or None,
        climb=m.get("climb") or None,
        hover=bool(m.get("hover") or False),
    )


def _species_senses(system: dict[str, Any]) -> Senses:
    s = system.get("senses") or {}
    return Senses(
        darkvision=_sense_value(s.get("darkvision")),
        blindsight=_sense_value(s.get("blindsight")),
        tremorsense=_sense_value(s.get("tremorsense")),
        truesight=_sense_value(s.get("truesight")),
        passive_perception=None,  # Species don't ship a passive perception value.
    )


def translate_species_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Species:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    advancement = _advancement(system)
    return Species(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        creature_type=_species_creature_type(system),
        size=_species_size(advancement),
        movement=_movement(system),
        senses=_species_senses(system),
        languages=_species_languages(advancement),
        trait_grants=_species_trait_grants(advancement),
        advancement=advancement,
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


# --- Class / Subclass ---


_HIT_DIE_MAP = {
    "d6": HitDie.D6,
    "d8": HitDie.D8,
    "d10": HitDie.D10,
    "d12": HitDie.D12,
}


def _hit_die(system: dict[str, Any]) -> HitDie:
    # 2024 packs (classes24/) store the hit die at ``system.hd.denomination``;
    # the legacy 2014 packs used the flat ``system.hitDice``. Prefer the 2024
    # shape, then fall back so both editions resolve correctly.
    hd = system.get("hd") or {}
    raw = str(hd.get("denomination") or system.get("hitDice") or "d8").lower()
    return _HIT_DIE_MAP.get(raw, HitDie.D8)


def _primary_ability(system: dict[str, Any]) -> PrimaryAbility:
    doc = system.get("primaryAbility") or {}
    raw_value = doc.get("value") or []
    abilities: set[str] = set()
    if isinstance(raw_value, list):
        for ab in raw_value:
            s = str(ab).lower()
            if s in {"str", "dex", "con", "int", "wis", "cha"}:
                abilities.add(s)
    return PrimaryAbility(
        value=frozenset(abilities),  # type: ignore[arg-type]
        all=bool(doc.get("all") or False),
    )


def _spellcasting(system: dict[str, Any]) -> Spellcasting:
    doc = system.get("spellcasting") or {}
    ability_raw = str(doc.get("ability") or "").lower()
    ability: str = ability_raw if ability_raw in {"str", "dex", "con", "int", "wis", "cha"} else ""
    progression_raw = str(doc.get("progression") or "none").lower()
    try:
        progression = SpellcastingProgression(progression_raw)
    except ValueError:
        progression = SpellcastingProgression.NONE
    return Spellcasting(
        ability=ability,  # type: ignore[arg-type]
        progression=progression,
    )


def translate_class_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Class:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    advancement = _advancement(system)
    return Class(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        identifier=str(system.get("identifier") or ""),
        hit_die=_hit_die(system),
        primary_ability=_primary_ability(system),
        spellcasting=_spellcasting(system),
        wealth=str(system.get("wealth") or ""),
        saving_throws=_class_saving_throws(advancement),
        subclass_identifiers=_class_subclass_identifiers(advancement),
        advancement=advancement,
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


def translate_subclass_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Subclass:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    return Subclass(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        identifier=str(system.get("identifier") or ""),
        class_identifier=str(system.get("classIdentifier") or ""),
        spellcasting=_spellcasting(system),
        advancement=_advancement(system),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


# --- Background ---


_ALL_ABILITIES: tuple[str, ...] = ("str", "dex", "con", "int", "wis", "cha")


def _background_ability_options(advancement: list[AdvancementEntry]) -> BackgroundAbilityChoice:
    """Build the +2/+1 choice from the ``AbilityScoreImprovement`` advancement.

    Foundry stores the three abilities the background does NOT improve in
    ``configuration.locked``; the eligible (improvable) abilities are the
    complement. ``cap``/``points`` come straight from the configuration
    (2/3 across the 2024 SRD backgrounds)."""
    for entry in advancement:
        if entry.type is not AdvancementType.ABILITY_SCORE_IMPROVEMENT:
            continue
        cfg = entry.configuration
        locked_raw = cfg.get("locked") or []
        locked = {str(a).lower() for a in locked_raw if isinstance(locked_raw, list)}
        options = frozenset(a for a in _ALL_ABILITIES if a not in locked)
        cap_raw = cfg.get("cap")
        points_raw = cfg.get("points")
        return BackgroundAbilityChoice(
            options=options,  # type: ignore[arg-type]
            cap=int(cap_raw) if cap_raw is not None else 2,
            points=int(points_raw) if points_raw is not None else 3,
        )
    # No ASI advancement (non-SRD content) → all six eligible, SRD defaults.
    return BackgroundAbilityChoice(options=frozenset(_ALL_ABILITIES))  # type: ignore[arg-type]


def _trait_grant_strings(entry: AdvancementEntry) -> list[str]:
    grants = entry.configuration.get("grants") or []
    return [str(g) for g in grants] if isinstance(grants, list) else []


def _trait_choice_pool_strings(entry: AdvancementEntry) -> list[str]:
    """Flatten a ``Trait`` advancement's ``configuration.choices[].pool`` into
    the grant-string vocabulary (``tool:game:*``, ``languages:standard:*`` …)."""
    out: list[str] = []
    choices = entry.configuration.get("choices") or []
    if not isinstance(choices, list):
        return out
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        pool = choice.get("pool") or []
        if isinstance(pool, list):
            out.extend(str(p) for p in pool)
    return out


def _background_proficiencies(advancement: list[AdvancementEntry]) -> tuple[list[str], list[str]]:
    """Split the proficiency ``Trait`` advancement's grants (and tool/skill
    choice pools) into ``(skill_short_codes, tool_keys)``, preserving source
    order. The proficiency Trait is identified by carrying ``skills:`` or
    ``tool:`` grants/choices; the separate language Trait (``languages:`` only)
    is ignored here. Order within a single grant list is byte-stable from
    Foundry; we de-dup while preserving first-seen order."""
    skills: list[str] = []
    tools: list[str] = []
    skills_seen: set[str] = set()
    tools_seen: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.TRAIT:
            continue
        strings = _trait_grant_strings(entry) + _trait_choice_pool_strings(entry)
        if not any(s.startswith(("skills:", "tool:")) for s in strings):
            continue
        for s in strings:
            if s.startswith("skills:"):
                code = s.removeprefix("skills:")
                if code and code not in skills_seen:
                    skills.append(code)
                    skills_seen.add(code)
            elif s.startswith("tool:"):
                code = s.removeprefix("tool:")
                if code and code not in tools_seen:
                    tools.append(code)
                    tools_seen.add(code)
    return skills, tools


def _background_languages(advancement: list[AdvancementEntry]) -> list[str]:
    """Granted language slugs from the language ``Trait`` advancement's
    ``languages:<group>:<slug>`` grants. Only fixed grants — the free choice
    pool (``languages:standard:*``) is a player decision, not a grant."""
    out: list[str] = []
    seen: set[str] = set()
    for entry in advancement:
        if entry.type is not AdvancementType.TRAIT:
            continue
        for g in _trait_grant_strings(entry):
            parts = g.split(":")
            if len(parts) >= 3 and parts[0] == "languages":
                lang = parts[2]
                if lang and lang not in seen:
                    out.append(lang)
                    seen.add(lang)
    return out


def _background_starting_feat_slug(advancement: list[AdvancementEntry]) -> str:
    """Final slug segment of the "Background Feat" ItemGrant's compendium UUID.

    The feat ItemGrant is identified by title; its
    ``configuration.items[0].uuid`` is a Foundry compendium ref like
    ``Compendium.dnd5e.feats24.Item.phbftMagicInitia`` — we surface the trailing
    ``phbftMagicInitia`` segment as the feat slug."""
    for entry in advancement:
        if entry.type is not AdvancementType.ITEM_GRANT:
            continue
        if entry.title.strip().lower() != "background feat":
            continue
        items = entry.configuration.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            uuid = item.get("uuid")
            if uuid:
                return str(uuid).rsplit(".", 1)[-1]
    return ""


def translate_background_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Background:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    advancement = _advancement(system)
    skills, tools = _background_proficiencies(advancement)
    starting_equipment_raw = system.get("startingEquipment") or []
    starting_equipment = (
        [e for e in starting_equipment_raw if isinstance(e, dict)]
        if isinstance(starting_equipment_raw, list)
        else []
    )
    return Background(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        ability_options=_background_ability_options(advancement),
        skill_proficiencies=skills,
        tool_proficiencies=tools,
        languages=_background_languages(advancement),
        starting_feat_slug=_background_starting_feat_slug(advancement),
        starting_equipment=starting_equipment,
        wealth=str(system.get("wealth") or ""),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


# --- Feat ---


_FEAT_SUBTYPE_TO_CATEGORY = {
    "origin": FeatCategory.ORIGIN,
    "general": FeatCategory.GENERAL,
    "fightingStyle": FeatCategory.FIGHTING_STYLE,
    "epicBoon": FeatCategory.EPIC_BOON,
}


def _feat_category(system: dict[str, Any]) -> FeatCategory:
    """Map Foundry ``system.type.subtype`` onto a :class:`FeatCategory`.

    The 2024 ``ability-score-improvement`` feat ships with an EMPTY ``subtype``
    (and empty ``type.value``) in the Foundry pack, while the 5e-bits SRD
    classifies it as a general feat — so an empty subtype falls back to
    ``GENERAL`` rather than failing translation."""
    subtype = str((system.get("type") or {}).get("subtype") or "")
    if not subtype:
        return FeatCategory.GENERAL
    return _FEAT_SUBTYPE_TO_CATEGORY[subtype]


def _feat_prerequisites(system: dict[str, Any]) -> list[FeatPrerequisite]:
    """Collapse Foundry's ``system.prerequisites`` block plus the free-text
    ``system.requirements`` into a single :class:`FeatPrerequisite`. Returns an
    empty list when the feat has no level gate, no prerequisite features, and no
    requirement prose."""
    prereq = system.get("prerequisites") or {}
    level = prereq.get("level")
    feats = [str(i) for i in (prereq.get("items") or [])]
    requirement = str(system.get("requirements") or "")
    if level is None and not feats and not requirement:
        return []
    return [
        FeatPrerequisite(
            level=int(level) if level is not None else None,
            feats=feats,
            requirement=requirement,
        )
    ]


def translate_feat_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Feat:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    return Feat(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        category=_feat_category(system),
        prerequisites=_feat_prerequisites(system),
        activities=_translate_activities(system),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


def _feature_type_and_source(yaml_path: Path) -> tuple[str, str]:
    parts = yaml_path.parts
    if "subclass-features" in parts:
        return "subclass_feature", parts[parts.index("subclass-features") + 1]
    if "traits" in parts:  # origins24/species/traits/<species>/...
        return "species_trait", parts[parts.index("traits") + 1]
    if "classes24" in parts:  # any class-feature dir: class-features/,
        return "class_feature", parts[
            parts.index("classes24") + 1
        ]  # metamagic-options/, eldritch-invocation-options/, ...
    raise ValueError(f"cannot classify feature doc path: {yaml_path}")


def translate_feature_yaml(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
) -> Feature:
    doc = _load_yaml(yaml_path)
    system = doc.get("system") or {}
    feature_type, source_slug = _feature_type_and_source(yaml_path)
    return Feature(
        slug=_slug(doc, yaml_path),
        name=_name(doc),
        description=_description(doc),
        feature_type=feature_type,
        foundry_id=str(doc.get("_id") or ""),
        source_slug=source_slug,
        activities=_translate_activities(system),
        passive_effects=_passive_effects(doc),
        provenance=_provenance(yaml_path, ingest_date, ingest_version),
        review=ReviewState(),
    )


T = TypeVar("T", bound=BaseModel)


def write_canonical_with_overrides(entity: T, canonical_dir: Path) -> None:
    """Write canonical JSON, preserving reviewer overrides from any existing file.

    If a file already exists with ``review.known_divergence != null``, the
    existing entry's field values WIN over the freshly-translated entity.
    Provenance + ingest fields always update to the fresh translator output.
    """
    target = canonical_dir / f"{entity.slug}.json"  # type: ignore[attr-defined]
    # frozenset-typed fields define their own deterministic serializers
    # (see schema field_serializer hooks) so model_dump is byte-stable.
    fresh_dict = entity.model_dump(mode="json")

    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("review", {}).get("known_divergence") is not None:
            # Reviewer-controlled fields stay; refresh only provenance.
            existing["provenance"] = fresh_dict["provenance"]
            target.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
            return

    target.write_text(json.dumps(fresh_dict, indent=2, sort_keys=True), encoding="utf-8")
