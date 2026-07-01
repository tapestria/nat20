"""Translator fidelity gate — assert canonical preserves Foundry's
structured mechanical fields.

Complementary to the 5e-bits oracle test (which validates against
authoritative SRD facts). This test validates against the upstream
the translator actually consumes, catching the class of "translator
silently dropped a field" bugs codex has surfaced iteratively
(magicalBonus on weapons/armor, reach weapon range values, top-level
effects[] arrays).

Predicate-based: each FidelityCheck applies ONLY when the foundry
predicate matches (the source has a non-default value). So adding
new checks doesn't false-fail on entries that legitimately don't
ship the field.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FOUNDRY_PACKS = ROOT / "raw_sources" / "foundry" / "packs" / "_source"
CANONICAL = ROOT / "src" / "dnd5e_srd_data" / "canonical"

# Loaded from JSON sidecar — slugs the translator legitimately can't
# preserve a field for, with rationale. Same pattern as the 5e-bits
# known_oracle_divergence.json.
KNOWN_FIDELITY_EXCEPTIONS: dict[str, list[str]] = json.loads(
    (ROOT / "tests" / "oracle" / "known_fidelity_exceptions.json").read_text()
)


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class FidelityCheck:
    name: str
    foundry_predicate: Callable[[dict[str, Any]], bool]
    canonical_assertion: Callable[[dict[str, Any], dict[str, Any]], bool]
    diagnostic: Callable[[dict[str, Any], dict[str, Any]], str]


# ---------------------------------------------------------------------------
# Field-extraction helpers (re-readable from both predicate and diagnostic)
# ---------------------------------------------------------------------------


def _weapon_magical_bonus(doc: dict[str, Any]) -> int:
    try:
        return int(doc.get("system", {}).get("magicalBonus") or 0)
    except (TypeError, ValueError):
        return 0


def _armor_magical_bonus(doc: dict[str, Any]) -> int:
    try:
        return int((doc.get("system", {}).get("armor") or {}).get("magicalBonus") or 0)
    except (TypeError, ValueError):
        return 0


def _system_range_value(doc: dict[str, Any]) -> int | None:
    r = doc.get("system", {}).get("range") or {}
    v = r.get("value")
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _activity_range_value(doc: dict[str, Any]) -> int | None:
    """Foundry hides reach-weapon range on the activity, not at
    ``system.range``. Mirror tools.translators.foundry._activity_range_value
    so the predicate sees what the translator sees."""
    activities = (doc.get("system") or {}).get("activities")
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


def _weapon_effective_range_value(doc: dict[str, Any]) -> int | None:
    """Range value Foundry actually ships for the weapon — system.range first,
    fallback to the first activity. Reach weapons (glaive/whip/lance/etc.) put
    their 10ft on the activity; the system-level range is null."""
    sys_val = _system_range_value(doc)
    if sys_val is not None:
        return sys_val
    return _activity_range_value(doc)


def _foundry_top_effects(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("effects")
    return raw if isinstance(raw, list) else []


def _item_daily_uses_max(item: dict[str, Any]) -> int | None:
    """Mirror tools.translators.foundry._daily_uses_max. An embedded item is
    day-limited when ``system.uses.recovery`` contains ``period: 'day'`` and
    ``system.uses.max`` parses to a positive int."""
    uses = (item.get("system") or {}).get("uses") or {}
    recovery = uses.get("recovery")
    if not isinstance(recovery, list):
        return None
    if not any(isinstance(e, dict) and e.get("period") == "day" for e in recovery):
        return None
    raw = uses.get("max")
    if raw in (None, ""):
        return None
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _monster_daily_use_items(doc: dict[str, Any]) -> list[tuple[str, int]]:
    """Return (name, max) pairs for every embedded weapon/feat item that ships
    a day-limited usage cap. Equipment / spells / consumables are excluded —
    those aren't surfaced as MonsterActions (see ``_monster_actions``)."""
    out: list[tuple[str, int]] = []
    items = doc.get("items")
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("type") not in {"weapon", "feat"}:
            continue
        cap = _item_daily_uses_max(it)
        if cap is None:
            continue
        out.append((str(it.get("name") or ""), cap))
    return out


def _all_canonical_actions(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *(canonical.get("actions") or []),
        *(canonical.get("legendary_actions") or []),
        *(canonical.get("lair_actions") or []),
        *(canonical.get("special_abilities") or []),
    ]


def _any_embedded_item_has_daily_uses(doc: dict[str, Any]) -> bool:
    return bool(_monster_daily_use_items(doc))


def _all_daily_uses_reflected(doc: dict[str, Any], canonical: dict[str, Any]) -> bool:
    actions = _all_canonical_actions(canonical)
    by_name = {a.get("name"): a for a in actions}
    for name, cap in _monster_daily_use_items(doc):
        action = by_name.get(name)
        if action is None:
            # Action didn't survive bucketing (e.g. spell/equipment filter) —
            # nothing to assert.
            continue
        if action.get("uses_per_day") != cap:
            return False
    return True


def _daily_uses_diagnostic(doc: dict[str, Any], canonical: dict[str, Any]) -> str:
    actions = _all_canonical_actions(canonical)
    by_name = {a.get("name"): a.get("uses_per_day") for a in actions}
    pairs = _monster_daily_use_items(doc)
    return (
        "foundry day-limited items: "
        + ", ".join(f"{n}={c}" for n, c in pairs)
        + "; canonical uses_per_day: "
        + ", ".join(f"{n}={by_name.get(n)!r}" for n, _ in pairs)
    )


# ---------------------------------------------------------------------------
# Fidelity checks
# ---------------------------------------------------------------------------


FIDELITY_CHECKS: dict[str, list[FidelityCheck]] = {
    "weapon": [
        FidelityCheck(
            name="magicalBonus preserved",
            foundry_predicate=lambda d: _weapon_magical_bonus(d) > 0,
            canonical_assertion=lambda y, c: (
                int(c.get("magical_bonus", 0)) == _weapon_magical_bonus(y)
            ),
            diagnostic=lambda y, c: (
                f"foundry magicalBonus={_weapon_magical_bonus(y)}; canonical magical_bonus={c.get('magical_bonus')}"
            ),
        ),
        FidelityCheck(
            name="range.value preserved (reach / thrown / ranged)",
            foundry_predicate=lambda d: (
                _weapon_effective_range_value(d) is not None
                and _weapon_effective_range_value(d) > 5  # type: ignore[operator]
            ),
            canonical_assertion=lambda y, c: (
                (c.get("range") or {}).get("value") == _weapon_effective_range_value(y)
            ),
            diagnostic=lambda y, c: (
                f"foundry effective range.value={_weapon_effective_range_value(y)} (system={_system_range_value(y)}, activity={_activity_range_value(y)}); canonical range={c.get('range')}"
            ),
        ),
        FidelityCheck(
            name="top-level effects[] preserved",
            foundry_predicate=lambda d: bool(_foundry_top_effects(d)),
            canonical_assertion=lambda y, c: bool(c.get("passive_effects")),
            diagnostic=lambda y, c: (
                f"foundry has {len(_foundry_top_effects(y))} effects[]; canonical passive_effects={len(c.get('passive_effects') or [])}"
            ),
        ),
    ],
    "armor": [
        FidelityCheck(
            name="armor.magicalBonus preserved",
            foundry_predicate=lambda d: _armor_magical_bonus(d) > 0,
            canonical_assertion=lambda y, c: (
                int(c.get("magical_bonus", 0)) == _armor_magical_bonus(y)
            ),
            diagnostic=lambda y, c: (
                f"foundry armor.magicalBonus={_armor_magical_bonus(y)}; canonical magical_bonus={c.get('magical_bonus')}, base_ac={c.get('base_ac')}"
            ),
        ),
        FidelityCheck(
            name="top-level effects[] preserved",
            foundry_predicate=lambda d: bool(_foundry_top_effects(d)),
            canonical_assertion=lambda y, c: bool(c.get("passive_effects")),
            diagnostic=lambda y, c: (
                f"foundry has {len(_foundry_top_effects(y))} effects[]; canonical passive_effects={len(c.get('passive_effects') or [])}"
            ),
        ),
    ],
    "magic_item_or_equipment": [
        FidelityCheck(
            name="top-level effects[] preserved",
            foundry_predicate=lambda d: bool(_foundry_top_effects(d)),
            canonical_assertion=lambda y, c: (
                bool(c.get("passive_effects")) or bool(c.get("activities"))
            ),
            diagnostic=lambda y, c: (
                f"foundry has {len(_foundry_top_effects(y))} effects[]; canonical passive_effects={len(c.get('passive_effects') or [])} activities={len(c.get('activities') or [])}"
            ),
        ),
    ],
    "monster": [
        FidelityCheck(
            name="monster action uses_per_day populated",
            foundry_predicate=_any_embedded_item_has_daily_uses,
            canonical_assertion=_all_daily_uses_reflected,
            diagnostic=_daily_uses_diagnostic,
        ),
    ],
    "spell": [
        FidelityCheck(
            name="spell level preserved",
            foundry_predicate=lambda d: ((d.get("system") or {}).get("level")) is not None,
            canonical_assertion=lambda y, c: c.get("level") == (y.get("system") or {}).get("level"),
            diagnostic=lambda y, c: (
                f"foundry level={(y.get('system') or {}).get('level')}; canonical level={c.get('level')}"
            ),
        ),
        FidelityCheck(
            name="spell school preserved",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("school")),
            canonical_assertion=lambda y, c: (
                c.get("school") == (y.get("system") or {}).get("school")
            ),
            diagnostic=lambda y, c: (
                f"foundry school={(y.get('system') or {}).get('school')!r}; canonical school={c.get('school')!r}"
            ),
        ),
        FidelityCheck(
            name="spell components V/S/M preserved",
            foundry_predicate=lambda d: any(
                p in {"vocal", "somatic", "material"}
                for p in ((d.get("system") or {}).get("properties") or [])
            ),
            canonical_assertion=lambda y, c: (
                {"V", "S", "M"} & set(c.get("components") or [])
                == {
                    {"vocal": "V", "somatic": "S", "material": "M"}[p]
                    for p in ((y.get("system") or {}).get("properties") or [])
                    if p in {"vocal", "somatic", "material"}
                }
            ),
            diagnostic=lambda y, c: (
                f"foundry properties V/S/M={[p for p in ((y.get('system') or {}).get('properties') or []) if p in {'vocal', 'somatic', 'material'}]}; "
                f"canonical components={c.get('components')}"
            ),
        ),
        FidelityCheck(
            name="spell ritual flag preserved",
            foundry_predicate=lambda d: (
                "ritual" in ((d.get("system") or {}).get("properties") or [])
            ),
            canonical_assertion=lambda y, c: c.get("ritual") is True,
            diagnostic=lambda y, c: (
                f"foundry has ritual property; canonical ritual={c.get('ritual')}"
            ),
        ),
        FidelityCheck(
            name="spell concentration flag preserved",
            foundry_predicate=lambda d: (
                "concentration" in ((d.get("system") or {}).get("properties") or [])
            ),
            canonical_assertion=lambda y, c: c.get("concentration") is True,
            diagnostic=lambda y, c: (
                f"foundry has concentration property; canonical concentration={c.get('concentration')}"
            ),
        ),
        FidelityCheck(
            name="spell material cost preserved when non-zero",
            foundry_predicate=lambda d: (
                int(((d.get("system") or {}).get("materials") or {}).get("cost") or 0) > 0
            ),
            canonical_assertion=lambda y, c: (
                int((c.get("materials") or {}).get("cost") or 0)
                == int(((y.get("system") or {}).get("materials") or {}).get("cost") or 0)
            ),
            diagnostic=lambda y, c: (
                f"foundry materials.cost={((y.get('system') or {}).get('materials') or {}).get('cost')}; "
                f"canonical materials.cost={(c.get('materials') or {}).get('cost')}"
            ),
        ),
        FidelityCheck(
            name="spell material value (prose) preserved when non-empty",
            foundry_predicate=lambda d: bool(
                str(((d.get("system") or {}).get("materials") or {}).get("value") or "").strip()
            ),
            canonical_assertion=lambda y, c: (
                (c.get("materials") or {}).get("value")
                == ((y.get("system") or {}).get("materials") or {}).get("value")
            ),
            diagnostic=lambda y, c: (
                f"foundry materials.value={((y.get('system') or {}).get('materials') or {}).get('value')!r}; "
                f"canonical materials.value={(c.get('materials') or {}).get('value')!r}"
            ),
        ),
        FidelityCheck(
            name="spell material consumed flag preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("materials") or {}).get("consumed")
            ),
            canonical_assertion=lambda y, c: bool((c.get("materials") or {}).get("consumed")),
            diagnostic=lambda y, c: (
                f"foundry materials.consumed={((y.get('system') or {}).get('materials') or {}).get('consumed')!r}; "
                f"canonical materials.consumed={(c.get('materials') or {}).get('consumed')!r}"
            ),
        ),
        FidelityCheck(
            name="spell casting_time (activation type+value) preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("activation") or {}).get("type")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("casting_time") or {}).get("unit")
                == ((y.get("system") or {}).get("activation") or {}).get("type")
            ),
            diagnostic=lambda y, c: (
                f"foundry activation.type={((y.get('system') or {}).get('activation') or {}).get('type')!r}; "
                f"canonical casting_time.unit={(c.get('casting_time') or {}).get('unit')!r}"
            ),
        ),
        FidelityCheck(
            name="spell range.value preserved when set",
            foundry_predicate=lambda d: (
                ((d.get("system") or {}).get("range") or {}).get("value") not in (None, "")
            ),
            canonical_assertion=lambda y, c: (
                str((c.get("range") or {}).get("value") or "")
                == str(((y.get("system") or {}).get("range") or {}).get("value") or "")
            ),
            diagnostic=lambda y, c: (
                f"foundry range.value={((y.get('system') or {}).get('range') or {}).get('value')!r}; "
                f"canonical range.value={(c.get('range') or {}).get('value')!r}"
            ),
        ),
        FidelityCheck(
            name="spell range.units preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("range") or {}).get("units")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("range") or {}).get("units")
                == ((y.get("system") or {}).get("range") or {}).get("units")
            ),
            diagnostic=lambda y, c: (
                f"foundry range.units={((y.get('system') or {}).get('range') or {}).get('units')!r}; "
                f"canonical range.units={(c.get('range') or {}).get('units')!r}"
            ),
        ),
        FidelityCheck(
            name="spell duration.units preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("duration") or {}).get("units")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("duration") or {}).get("units")
                == ((y.get("system") or {}).get("duration") or {}).get("units")
            ),
            diagnostic=lambda y, c: (
                f"foundry duration.units={((y.get('system') or {}).get('duration') or {}).get('units')!r}; "
                f"canonical duration.units={(c.get('duration') or {}).get('units')!r}"
            ),
        ),
        FidelityCheck(
            name="spell duration.value preserved when numeric",
            # Formula-shaped duration values (e.g. magic-circle's
            # ``@item.level - 2``) can't round-trip into the NonNegativeInt
            # schema field. The predicate fires only for integer-parseable
            # values — 317 of 319 SRD spells qualify.
            foundry_predicate=lambda d: (
                str(((d.get("system") or {}).get("duration") or {}).get("value") or "")
                .strip()
                .isdigit()
            ),
            canonical_assertion=lambda y, c: (
                int((c.get("duration") or {}).get("value") or 0)
                == int(((y.get("system") or {}).get("duration") or {}).get("value"))
            ),
            diagnostic=lambda y, c: (
                f"foundry duration.value={((y.get('system') or {}).get('duration') or {}).get('value')!r}; "
                f"canonical duration.value={(c.get('duration') or {}).get('value')!r}"
            ),
        ),
        FidelityCheck(
            name="spell top-level effects[] preserved",
            foundry_predicate=lambda d: bool(_foundry_top_effects(d)),
            canonical_assertion=lambda y, c: bool(c.get("passive_effects")),
            diagnostic=lambda y, c: (
                f"foundry has {len(_foundry_top_effects(y))} effects[]; canonical passive_effects={len(c.get('passive_effects') or [])}"
            ),
        ),
    ],
    "species": [
        FidelityCheck(
            name="species walk speed preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("movement") or {}).get("walk")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("movement") or {}).get("walk")
                == ((y.get("system") or {}).get("movement") or {}).get("walk")
            ),
            diagnostic=lambda y, c: (
                f"foundry movement.walk={((y.get('system') or {}).get('movement') or {}).get('walk')}; "
                f"canonical movement.walk={(c.get('movement') or {}).get('walk')}"
            ),
        ),
        FidelityCheck(
            name="species darkvision preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("senses") or {}).get("darkvision")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("senses") or {}).get("darkvision")
                == ((y.get("system") or {}).get("senses") or {}).get("darkvision")
            ),
            diagnostic=lambda y, c: (
                f"foundry senses.darkvision={((y.get('system') or {}).get('senses') or {}).get('darkvision')}; "
                f"canonical senses.darkvision={(c.get('senses') or {}).get('darkvision')}"
            ),
        ),
        FidelityCheck(
            name="species advancement entries preserved",
            foundry_predicate=lambda d: bool(((d.get("system") or {}).get("advancement")) or []),
            canonical_assertion=lambda y, c: (
                len(c.get("advancement") or [])
                # canonical may drop entries with unknown advancement type;
                # require canonical preserves *most* of them (>=80%).
                >= int(len(((y.get("system") or {}).get("advancement")) or []) * 0.8)
            ),
            diagnostic=lambda y, c: (
                f"foundry advancement[]={len(((y.get('system') or {}).get('advancement')) or [])}; "
                f"canonical advancement={len(c.get('advancement') or [])}"
            ),
        ),
        FidelityCheck(
            name="species creature_type.value preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("type") or {}).get("value")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("creature_type") or {}).get("value")
                == ((y.get("system") or {}).get("type") or {}).get("value")
            ),
            diagnostic=lambda y, c: (
                f"foundry type.value={((y.get('system') or {}).get('type') or {}).get('value')!r}; "
                f"canonical creature_type.value={(c.get('creature_type') or {}).get('value')!r}"
            ),
        ),
        FidelityCheck(
            name="species creature_type.subtype preserved when set",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("type") or {}).get("subtype")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("creature_type") or {}).get("subtype")
                == ((y.get("system") or {}).get("type") or {}).get("subtype")
            ),
            diagnostic=lambda y, c: (
                f"foundry type.subtype={((y.get('system') or {}).get('type') or {}).get('subtype')!r}; "
                f"canonical creature_type.subtype={(c.get('creature_type') or {}).get('subtype')!r}"
            ),
        ),
        *(
            FidelityCheck(
                name=f"species movement.{mode} preserved when set",
                foundry_predicate=(
                    lambda d, m=mode: bool(((d.get("system") or {}).get("movement") or {}).get(m))
                ),
                canonical_assertion=(
                    lambda y, c, m=mode: (
                        (c.get("movement") or {}).get(m)
                        == ((y.get("system") or {}).get("movement") or {}).get(m)
                    )
                ),
                diagnostic=(
                    lambda y, c, m=mode: (
                        f"foundry movement.{m}={((y.get('system') or {}).get('movement') or {}).get(m)}; "
                        f"canonical movement.{m}={(c.get('movement') or {}).get(m)}"
                    )
                ),
            )
            for mode in ("fly", "swim", "burrow", "climb")
        ),
        *(
            FidelityCheck(
                name=f"species senses.{sense} preserved when set",
                foundry_predicate=(
                    lambda d, s=sense: bool(((d.get("system") or {}).get("senses") or {}).get(s))
                ),
                canonical_assertion=(
                    lambda y, c, s=sense: (
                        (c.get("senses") or {}).get(s)
                        == ((y.get("system") or {}).get("senses") or {}).get(s)
                    )
                ),
                diagnostic=(
                    lambda y, c, s=sense: (
                        f"foundry senses.{s}={((y.get('system') or {}).get('senses') or {}).get(s)}; "
                        f"canonical senses.{s}={(c.get('senses') or {}).get(s)}"
                    )
                ),
            )
            for sense in ("blindsight", "tremorsense", "truesight")
        ),
        # The 2024 SRD species carry no ability-score bonuses and no language
        # grants (both moved to the character's background), so the old
        # ability_bonuses / languages fidelity checks were dropped here.
    ],
    "class": [
        FidelityCheck(
            name="class hit die preserved",
            # 2024 classes24/ store the hit die at ``system.hd.denomination``;
            # legacy 2014 packs used the flat ``system.hitDice``. Mirror the
            # translator: prefer the 2024 shape, fall back to the legacy field.
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("hd") or {}).get("denomination")
                or (d.get("system") or {}).get("hitDice")
            ),
            canonical_assertion=lambda y, c: (
                c.get("hit_die")
                == (
                    ((y.get("system") or {}).get("hd") or {}).get("denomination")
                    or (y.get("system") or {}).get("hitDice")
                )
            ),
            diagnostic=lambda y, c: (
                "foundry hit die="
                f"{(((y.get('system') or {}).get('hd') or {}).get('denomination') or (y.get('system') or {}).get('hitDice'))!r}; "
                f"canonical hit_die={c.get('hit_die')!r}"
            ),
        ),
        FidelityCheck(
            name="class spellcasting progression preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("spellcasting") or {}).get("progression")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("spellcasting") or {}).get("progression")
                == ((y.get("system") or {}).get("spellcasting") or {}).get("progression")
            ),
            diagnostic=lambda y, c: (
                f"foundry spellcasting.progression={((y.get('system') or {}).get('spellcasting') or {}).get('progression')!r}; "
                f"canonical spellcasting.progression={(c.get('spellcasting') or {}).get('progression')!r}"
            ),
        ),
        FidelityCheck(
            name="class advancement entries preserved",
            foundry_predicate=lambda d: bool(((d.get("system") or {}).get("advancement")) or []),
            canonical_assertion=lambda y, c: (
                len(c.get("advancement") or [])
                >= int(len(((y.get("system") or {}).get("advancement")) or []) * 0.8)
            ),
            diagnostic=lambda y, c: (
                f"foundry advancement[]={len(((y.get('system') or {}).get('advancement')) or [])}; "
                f"canonical advancement={len(c.get('advancement') or [])}"
            ),
        ),
        FidelityCheck(
            name="class spellcasting ability preserved",
            foundry_predicate=lambda d: bool(
                ((d.get("system") or {}).get("spellcasting") or {}).get("ability")
            ),
            canonical_assertion=lambda y, c: (
                (c.get("spellcasting") or {}).get("ability")
                == ((y.get("system") or {}).get("spellcasting") or {}).get("ability")
            ),
            diagnostic=lambda y, c: (
                f"foundry spellcasting.ability={((y.get('system') or {}).get('spellcasting') or {}).get('ability')!r}; "
                f"canonical spellcasting.ability={(c.get('spellcasting') or {}).get('ability')!r}"
            ),
        ),
        FidelityCheck(
            name="class identifier preserved",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("identifier")),
            canonical_assertion=lambda y, c: (
                c.get("identifier") == (y.get("system") or {}).get("identifier")
            ),
            diagnostic=lambda y, c: (
                f"foundry identifier={(y.get('system') or {}).get('identifier')!r}; canonical identifier={c.get('identifier')!r}"
            ),
        ),
        FidelityCheck(
            name="class saving_throws derived from saves: grant tokens",
            foundry_predicate=lambda d: any(
                str(g).startswith("saves:")
                for a in ((d.get("system") or {}).get("advancement") or [])
                if isinstance(a, dict) and a.get("type") == "Trait"
                for g in ((a.get("configuration") or {}).get("grants") or [])
            ),
            canonical_assertion=lambda y, c: bool(c.get("saving_throws")),
            diagnostic=lambda y, c: (
                f"foundry has saves: grants; canonical saving_throws={c.get('saving_throws')}"
            ),
        ),
        FidelityCheck(
            name="class wealth preserved when set",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("wealth")),
            canonical_assertion=lambda y, c: (
                c.get("wealth") == (y.get("system") or {}).get("wealth")
            ),
            diagnostic=lambda y, c: (
                f"foundry wealth={(y.get('system') or {}).get('wealth')!r}; canonical wealth={c.get('wealth')!r}"
            ),
        ),
    ],
    "background": [
        FidelityCheck(
            name="background identifier → slug preserved",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("identifier")),
            canonical_assertion=lambda y, c: (
                c.get("slug") == (y.get("system") or {}).get("identifier")
            ),
            diagnostic=lambda y, c: (
                f"foundry identifier={(y.get('system') or {}).get('identifier')!r}; canonical slug={c.get('slug')!r}"
            ),
        ),
        FidelityCheck(
            name="background wealth preserved when set",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("wealth")),
            canonical_assertion=lambda y, c: (
                c.get("wealth") == (y.get("system") or {}).get("wealth")
            ),
            diagnostic=lambda y, c: (
                f"foundry wealth={(y.get('system') or {}).get('wealth')!r}; canonical wealth={c.get('wealth')!r}"
            ),
        ),
        FidelityCheck(
            name="background startingEquipment preserved",
            foundry_predicate=lambda d: bool(
                (d.get("system") or {}).get("startingEquipment") or []
            ),
            canonical_assertion=lambda y, c: (
                len(c.get("starting_equipment") or [])
                == len((y.get("system") or {}).get("startingEquipment") or [])
            ),
            diagnostic=lambda y, c: (
                f"foundry startingEquipment[]={len((y.get('system') or {}).get('startingEquipment') or [])}; "
                f"canonical starting_equipment={len(c.get('starting_equipment') or [])}"
            ),
        ),
        FidelityCheck(
            name="background ability options invert locked set",
            foundry_predicate=lambda d: any(
                isinstance(a, dict) and a.get("type") == "AbilityScoreImprovement"
                for a in ((d.get("system") or {}).get("advancement") or [])
            ),
            canonical_assertion=lambda y, c: (
                set((c.get("ability_options") or {}).get("options") or [])
                == {"str", "dex", "con", "int", "wis", "cha"}
                - {
                    str(ab).lower()
                    for a in ((y.get("system") or {}).get("advancement") or [])
                    if isinstance(a, dict) and a.get("type") == "AbilityScoreImprovement"
                    for ab in ((a.get("configuration") or {}).get("locked") or [])
                }
            ),
            diagnostic=lambda y, c: (
                f"canonical ability_options.options={(c.get('ability_options') or {}).get('options')!r}; "
                f"foundry locked sets must be inverted"
            ),
        ),
    ],
    "subclass": [
        FidelityCheck(
            name="subclass classIdentifier preserved",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("classIdentifier")),
            canonical_assertion=lambda y, c: (
                c.get("class_identifier") == (y.get("system") or {}).get("classIdentifier")
            ),
            diagnostic=lambda y, c: (
                f"foundry classIdentifier={(y.get('system') or {}).get('classIdentifier')!r}; "
                f"canonical class_identifier={c.get('class_identifier')!r}"
            ),
        ),
        FidelityCheck(
            name="subclass identifier preserved",
            foundry_predicate=lambda d: bool((d.get("system") or {}).get("identifier")),
            canonical_assertion=lambda y, c: (
                c.get("identifier") == (y.get("system") or {}).get("identifier")
            ),
            diagnostic=lambda y, c: (
                f"foundry identifier={(y.get('system') or {}).get('identifier')!r}; canonical identifier={c.get('identifier')!r}"
            ),
        ),
        FidelityCheck(
            name="subclass advancement entries preserved",
            foundry_predicate=lambda d: bool(((d.get("system") or {}).get("advancement")) or []),
            canonical_assertion=lambda y, c: (
                len(c.get("advancement") or [])
                >= int(len(((y.get("system") or {}).get("advancement")) or []) * 0.8)
            ),
            diagnostic=lambda y, c: (
                f"foundry advancement[]={len(((y.get('system') or {}).get('advancement')) or [])}; "
                f"canonical advancement={len(c.get('advancement') or [])}"
            ),
        ),
    ],
}


# ---------------------------------------------------------------------------
# YAML / canonical lookup
# ---------------------------------------------------------------------------


def _load_foundry_yaml(yaml_path: Path) -> dict[str, Any] | None:
    try:
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_canonical(category: str, slug: str) -> dict[str, Any] | None:
    path = CANONICAL / category / f"{slug}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _is_foundry_random_id(value: str) -> bool:
    return len(value) == 16 and value.isalnum()


def _foundry_slug(doc: dict[str, Any], yaml_path: Path) -> str:
    """Mirror tools.translators.foundry._slug exactly so the right canonical
    entry is looked up. Keeping this re-implemented (instead of importing the
    private helper) prevents the fidelity oracle and the translator from
    quietly drifting if either is refactored."""
    system = doc.get("system") or {}
    identifier = system.get("identifier")
    if identifier:
        raw = str(identifier)
    else:
        _id = doc.get("_id")
        if _id and _is_foundry_random_id(str(_id)):
            raw = yaml_path.stem
        else:
            raw = str(_id) if _id else yaml_path.stem
    kebab = _CAMEL_BOUNDARY.sub("-", raw)
    return kebab.lower().replace("_", "-").replace(" ", "-")


def _doc_category(doc: dict[str, Any]) -> str:
    """Return the FidelityCheck category for this Foundry doc."""
    doc_type = doc.get("type")
    if doc_type == "npc":
        return "monster"
    if doc_type == "weapon":
        return "weapon"
    if doc_type == "spell":
        return "spell"
    if doc_type == "race":
        # The 2024 Foundry species docs still carry the legacy ``type: race``
        # discriminator; canonical treats them as species.
        return "species"
    if doc_type == "class":
        return "class"
    if doc_type == "subclass":
        return "subclass"
    if doc_type == "background":
        return "background"
    if doc_type == "equipment":
        # Foundry's 'equipment' covers armor + non-weapon items.
        system = doc.get("system", {}) or {}
        armor = system.get("armor") or {}
        if armor.get("value"):
            return "armor"
    return "magic_item_or_equipment"


# ---------------------------------------------------------------------------
# Test entry point
# ---------------------------------------------------------------------------


def test_translator_preserves_foundry_mechanical_fields() -> None:
    """Walk every real Foundry YAML; for each, run applicable
    FidelityChecks. Aggregate failures into one report."""
    failures: list[str] = []
    # Map Foundry pack-source dir → canonical category dir. Most align 1:1;
    # the doc-type filter inside the loop guarantees we only fidelity-check
    # docs that landed in the matching canonical category.
    category_dirs: tuple[tuple[str, str], ...] = (
        ("equipment24", "items"),
        ("actors24", "monsters"),
        ("spells24", "spells"),
        ("origins24/species", "species"),
        ("origins24/backgrounds", "backgrounds"),
        ("classes24", "classes"),
        ("classes24", "subclasses"),
    )
    # Doc-type → canonical category. Docs in origins24/species or classes/ that
    # are 'feat' type (class features, species features) are filtered out via
    # this mapping. The 2024 Foundry species docs use the legacy ``type: race``
    # discriminator, which maps to the ``species`` canonical category.
    _DOC_TYPE_TO_CANONICAL = {
        "npc": "monsters",
        "weapon": "items",
        "equipment": "items",
        "consumable": "items",
        "tool": "items",
        "loot": "items",
        "container": "items",
        "Item": "items",
        "spell": "spells",
        "race": "species",
        "class": "classes",
        "subclass": "subclasses",
        "background": "backgrounds",
    }
    for foundry_dir, _expected_canonical in category_dirs:
        category_root = FOUNDRY_PACKS / foundry_dir
        if not category_root.is_dir():
            continue
        for yaml_path in category_root.rglob("*.yml"):
            if yaml_path.name == "_folder.yml":
                continue
            doc = _load_foundry_yaml(yaml_path)
            if not isinstance(doc, dict):
                continue
            canonical_category = _DOC_TYPE_TO_CANONICAL.get(doc.get("type") or "")
            if canonical_category is None:
                continue
            slug = _foundry_slug(doc, yaml_path)
            canonical = _load_canonical(canonical_category, slug)
            if canonical is None:
                continue  # quarantined / not in canonical
            doc_cat = _doc_category(doc)
            exceptions_for_slug = set(KNOWN_FIDELITY_EXCEPTIONS.get(slug, []))
            for check in FIDELITY_CHECKS.get(doc_cat, []):
                if check.name in exceptions_for_slug:
                    continue
                try:
                    if not check.foundry_predicate(doc):
                        continue
                except Exception as exc:
                    failures.append(f"{slug} ({doc_cat}): {check.name} — predicate error: {exc!r}")
                    continue
                try:
                    ok = check.canonical_assertion(doc, canonical)
                except Exception as exc:
                    failures.append(f"{slug} ({doc_cat}): {check.name} — assertion error: {exc!r}")
                    continue
                if not ok:
                    failures.append(
                        f"{slug} ({doc_cat}): {check.name} — " + check.diagnostic(doc, canonical)
                    )
    if failures:
        msg = f"{len(failures)} fidelity failures:\n" + "\n".join(failures[:200])
        if len(failures) > 200:
            msg += f"\n... ({len(failures) - 200} more truncated)"
        pytest.fail(msg)


def test_doc_type_weapon_classified_as_weapon() -> None:
    """Foundry doc.type=='weapon' must produce a canonical Weapon regardless
    of pack subdir. Guards the iter-9 regression where spellcasting-focus/
    staff.yml (type: weapon) went through the generic translator and lost
    its damage parts."""
    failures: list[str] = []
    for yaml_path in (FOUNDRY_PACKS / "equipment24").rglob("*.yml"):
        if yaml_path.name == "_folder.yml":
            continue
        doc = _load_foundry_yaml(yaml_path)
        if not isinstance(doc, dict):
            continue
        if doc.get("type") != "weapon":
            continue
        slug = _foundry_slug(doc, yaml_path)
        canonical = _load_canonical("items", slug)
        if canonical is None:
            continue  # quarantined / not in canonical
        if canonical.get("item_kind") != "weapon":
            failures.append(
                f"{slug} ({yaml_path.relative_to(ROOT)}): "
                f"foundry type='weapon' but canonical item_kind={canonical.get('item_kind')!r}"
            )
    if failures:
        pytest.fail("\n".join(failures))
