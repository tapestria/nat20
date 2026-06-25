"""D&D 5e conditions — effects and application logic."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_engine.types.conditions import ActiveCondition, ConditionScope


class Condition(StrEnum):
    BLINDED = "blinded"
    CHARMED = "charmed"
    DEAFENED = "deafened"
    EXHAUSTION = "exhaustion"
    FRIGHTENED = "frightened"
    GRAPPLED = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE = "invisible"
    PARALYZED = "paralyzed"
    PETRIFIED = "petrified"
    POISONED = "poisoned"
    PRONE = "prone"
    RESTRAINED = "restrained"
    STUNNED = "stunned"
    UNCONSCIOUS = "unconscious"


# Conditions that automatically include other conditions
CONDITION_IMPLIES: dict[Condition, list[Condition]] = {
    Condition.PARALYZED: [Condition.INCAPACITATED],
    Condition.PETRIFIED: [Condition.INCAPACITATED],
    Condition.STUNNED: [Condition.INCAPACITATED],
    Condition.UNCONSCIOUS: [Condition.INCAPACITATED, Condition.PRONE],
}

# Human-readable effects per condition
CONDITION_EFFECTS: dict[Condition, list[str]] = {
    Condition.BLINDED: [
        "Automatically fails any ability check requiring sight",
        "Attack rolls against this creature have advantage",
        "This creature's attack rolls have disadvantage",
    ],
    Condition.CHARMED: [
        "Cannot attack the charmer or target them with spells",
        "Charmer has advantage on social checks against this creature",
    ],
    Condition.DEAFENED: [
        "Cannot hear",
        "Automatically fails ability checks requiring hearing",
    ],
    Condition.EXHAUSTION: [
        "Level 1: Disadvantage on ability checks",
        "Level 2: Speed halved",
        "Level 3: Disadvantage on attack rolls and saving throws",
        "Level 4: HP maximum halved",
        "Level 5: Speed reduced to 0",
        "Level 6: Death",
    ],
    Condition.FRIGHTENED: [
        "Disadvantage on ability checks and attack rolls while source of fear is in line of sight",
        "Cannot willingly move closer to source of fear",
    ],
    Condition.GRAPPLED: [
        "Speed becomes 0",
        "Ends if grappler becomes incapacitated",
        "Ends if creature is moved out of reach of grappler",
    ],
    Condition.INCAPACITATED: [
        "Cannot take actions or reactions",
    ],
    Condition.INVISIBLE: [
        "Impossible to see without special sense",
        "Attacks by this creature have advantage",
        "Attacks against this creature have disadvantage",
    ],
    Condition.PARALYZED: [
        "Incapacitated and cannot move or speak",
        "Automatically fails STR and DEX saving throws",
        "Attack rolls against this creature have advantage",
        "Any attack that hits is a critical hit if within 5 feet",
    ],
    Condition.PETRIFIED: [
        "Transformed into stone; incapacitated, can't move or speak",
        "Attacks against this creature have advantage",
        "Automatically fails STR and DEX saving throws",
        "Resistance to all damage",
        "Immune to poison and disease",
    ],
    Condition.POISONED: [
        "Disadvantage on attack rolls and ability checks",
    ],
    Condition.PRONE: [
        "Only movement option is to crawl (costs double movement)",
        "Disadvantage on attack rolls",
        "Attack rolls within 5 feet have advantage against this creature",
        "Ranged attack rolls against this creature have disadvantage",
    ],
    Condition.RESTRAINED: [
        "Speed becomes 0",
        "Attack rolls against this creature have advantage",
        "This creature's attack rolls have disadvantage",
        "Disadvantage on DEX saving throws",
    ],
    Condition.STUNNED: [
        "Incapacitated, cannot move, can only speak falteringly",
        "Automatically fails STR and DEX saving throws",
        "Attack rolls against this creature have advantage",
    ],
    Condition.UNCONSCIOUS: [
        "Incapacitated, cannot move or speak, unaware of surroundings",
        "Drops whatever it's holding and falls prone",
        "Automatically fails STR and DEX saving throws",
        "Attacks against this creature have advantage",
        "Any attack that hits from within 5 feet is a critical hit",
    ],
}


def is_condition_active(condition: Condition, active_conditions: list[str]) -> bool:
    """Check if a condition (or one that implies it) is active."""
    active_set = {c.lower() for c in active_conditions}

    if condition.value in active_set:
        return True

    # Check implied conditions
    for cond, implied in CONDITION_IMPLIES.items():
        if cond.value in active_set and condition in implied:
            return True

    return False


def apply_condition(
    condition: Condition,
    current_conditions: list[str],
) -> list[str]:
    """Add a condition (idempotent)."""
    if condition.value not in current_conditions:
        return [*current_conditions, condition.value]
    return current_conditions


def remove_condition(
    condition: Condition,
    current_conditions: list[str],
) -> list[str]:
    """Remove a condition."""
    return [c for c in current_conditions if c.lower() != condition.value]


def get_condition_effects(condition: Condition) -> list[str]:
    """Return human-readable effects of a condition."""
    return CONDITION_EFFECTS.get(condition, [])


def active_condition_names(conditions: list[ActiveCondition]) -> list[str]:
    """Extract string condition names from list[ActiveCondition] for legacy helper compatibility."""
    from dnd5e_engine.types.conditions import (
        ActiveCondition as _ActiveCondition,  # noqa: F401 (runtime import)
    )

    return [c.condition for c in conditions]


def apply_condition_with_implies(
    condition: Condition,
    source_entity_id: str,
    scope: ConditionScope,
    current_conditions: list[ActiveCondition],
    duration_rounds: int | None = None,
    save_dc: int | None = None,
    applied_round: int = 0,
    exhaustion_level: int = 1,
    source_effect_id: str | None = None,
) -> list[ActiveCondition]:
    """Apply a condition plus all implied conditions per D-04.

    Idempotent per condition name. Implied conditions get
    source_entity_id=f"implied:{condition.value}".

    source_effect_id: Effect node ID when this condition is bridged from an
    effect (FX-05). Set on the root condition only; implied conditions inherit
    source_entity_id="implied:{condition}" with no effect link.
    """
    from dnd5e_engine.types.conditions import ActiveCondition

    existing_names = {c.condition for c in current_conditions}
    result = list(current_conditions)

    # Apply the root condition if not already present
    if condition.value not in existing_names:
        result.append(
            ActiveCondition(
                condition=condition.value,
                source_entity_id=source_entity_id,
                scope=scope,
                duration_rounds=duration_rounds,
                save_dc=save_dc,
                applied_round=applied_round,
                exhaustion_level=exhaustion_level,
                source_effect_id=source_effect_id,
            )
        )
        existing_names.add(condition.value)

    # Apply all implied conditions
    for implied_cond in CONDITION_IMPLIES.get(condition, []):
        if implied_cond.value not in existing_names:
            result.append(
                ActiveCondition(
                    condition=implied_cond.value,
                    source_entity_id=f"implied:{condition.value}",
                    scope=scope,
                    applied_round=applied_round,
                )
            )
            existing_names.add(implied_cond.value)

    return result


def remove_condition_with_implies(
    condition: Condition,
    current_conditions: list[ActiveCondition],
) -> list[ActiveCondition]:
    """Remove root condition AND all entries implied by it.

    Removes:
    - entries with condition == condition.value
    - entries where source_entity_id == f"implied:{condition.value}"
    """
    implied_source = f"implied:{condition.value}"
    implied_names = {c.value for c in CONDITION_IMPLIES.get(condition, [])}

    result = []
    for c in current_conditions:
        # Remove the root condition itself
        if c.condition == condition.value:
            continue
        # Remove entries that were implied by this condition (by source tag)
        if c.source_entity_id == implied_source and c.condition in implied_names:
            continue
        result.append(c)
    return result


def check_immunity(condition_name: str, immunities: list[str]) -> bool:
    """Check if condition_name is in the immunities list."""
    return condition_name in immunities


def conditions_grant_disadvantage_on_ability_checks(conditions: list[str]) -> bool:
    """Return True if conditions impose disadvantage on ability checks.

    Level 1 exhaustion and poisoned both impose disadvantage on ability checks per SRD.
    """
    return "exhaustion" in conditions or "poisoned" in conditions


def conditions_grant_advantage_on_attack(
    attacker_conditions: list[str],
    target_conditions: list[str],
) -> tuple[bool, bool]:
    """
    Returns (attacker_has_advantage, attacker_has_disadvantage) based on conditions.
    Does NOT account for ranged vs melee distinction (caller's responsibility).
    """
    advantage = False
    disadvantage = False

    if is_condition_active(Condition.INVISIBLE, attacker_conditions):
        advantage = True
    if is_condition_active(Condition.BLINDED, attacker_conditions):
        disadvantage = True
    if is_condition_active(Condition.POISONED, attacker_conditions):
        disadvantage = True
    if is_condition_active(Condition.FRIGHTENED, attacker_conditions):
        disadvantage = True
    if is_condition_active(Condition.RESTRAINED, attacker_conditions):
        disadvantage = True

    if is_condition_active(Condition.PARALYZED, target_conditions):
        advantage = True
    if is_condition_active(Condition.STUNNED, target_conditions):
        advantage = True
    if is_condition_active(Condition.UNCONSCIOUS, target_conditions):
        advantage = True
    if is_condition_active(Condition.BLINDED, target_conditions):
        advantage = True

    return advantage, disadvantage


# ── Per-effect sidecar projection (combat orchestrator hydration) ────────────
#
# The combat orchestrator hydrates ``EffectStore`` sidecars from the live
# combatant's conditions immediately before invoking the per-effect
# evaluator. The handlers under ``app/combat/effects/*.py`` read three
# tables off the store:
#
#   * ``_passive_damage_modifiers[target_id]`` →
#       ``{"resistances": [...], "vulnerabilities": [...], "immunities": [...]}``
#     (consumed by ``damage.py``; ``"all"`` is the catch-all damage-type
#     marker used by Petrified's "resistance to all damage")
#   * ``_save_modifiers[target_id]`` →
#       ``{"passive_save_adv": [ability_code, ...],
#         "passive_save_dis": [ability_code, ...]}``
#     (consumed by ``save.py``; ability codes are upper-case STR/DEX/CON/
#     INT/WIS/CHA)
#   * ``_check_modifiers[actor_id]`` →
#       ``{"passive_check_adv": [...], "passive_check_dis": [...]}``
#     (consumed by ``check.py``; ``"all"`` is the catch-all for conditions
#     that impose dis/adv on *every* ability check — Frightened, Poisoned,
#     Exhaustion ≥ 1)
#
# This projection is the SRD-condition portion of the sidecar payload —
# active-effect modifier projection (Bless, Bane, etc.) layers on top in
# the orchestrator. Keeping the table here in ``rules/`` keeps the SRD
# semantics in the pure rules engine; the orchestrator owns the
# transport-level merge.


def project_passive_damage_modifiers(conditions: list[str]) -> dict[str, list[str]]:
    """Return the resistance / vulnerability / immunity projection for ``conditions``.

    Only Petrified contributes here per SRD 5.1 §Conditions — "resistance
    to all damage" + immune to poison + can't be poisoned (we surface the
    poison damage immunity, not the condition-immunity which lives on
    ``Combatant`` separately).
    """
    out: dict[str, list[str]] = {"resistances": [], "vulnerabilities": [], "immunities": []}
    if "petrified" in {c.lower() for c in conditions}:
        out["resistances"].append("all")
        out["immunities"].append("poison")
    return out


def project_passive_save_modifiers(conditions: list[str]) -> dict[str, list[str]]:
    """Return passive save adv / dis / auto-fail ability-code lists.

    Per SRD 5.1 §Conditions:

    * Restrained → disadvantage on DEX saves.
    * Paralyzed / Stunned / Petrified / Unconscious → auto-fail STR + DEX
      saves. Surfaced as ``passive_save_auto_fail`` so the save handler
      short-circuits the d20 roll entirely (no rng consumption, no
      modifier math). ``passive_save_dis`` is also populated as a
      belt-and-suspenders fallback so a save handler that doesn't yet
      honor auto-fail still resolves in the correct direction.
    """
    out: dict[str, list[str]] = {
        "passive_save_adv": [],
        "passive_save_dis": [],
        "passive_save_auto_fail": [],
    }
    active = {c.lower() for c in conditions}
    if "restrained" in active:
        out["passive_save_dis"].append("DEX")
    auto_fail_str_dex = {"paralyzed", "stunned", "petrified", "unconscious"}
    if active & auto_fail_str_dex:
        out["passive_save_auto_fail"].extend(("STR", "DEX"))
        # Defensive: keep the disadvantage entries so a save handler
        # without the auto-fail short-circuit still resolves the save
        # in the correct direction.
        if "STR" not in out["passive_save_dis"]:
            out["passive_save_dis"].append("STR")
        if "DEX" not in out["passive_save_dis"]:
            out["passive_save_dis"].append("DEX")
    return out


def project_passive_check_modifiers(conditions: list[str]) -> dict[str, list[str]]:
    """Return ``passive_check_adv`` / ``passive_check_dis`` lists.

    Per SRD 5.1 §Conditions, conditions that impose disadvantage on
    *every* ability check use the ``"all"`` catch-all marker the
    ``check.py`` handler already recognizes (see ``_reconcile_adv_dis``):

    * Frightened — "disadvantage on ability checks ... while source of fear
      is in line of sight" (we project as ``all`` — the line-of-sight gate
      isn't carried on the live state today)
    * Poisoned — "disadvantage on attack rolls and ability checks"
    * Exhaustion ≥ 1 — "disadvantage on ability checks" (Level 1 effect;
      exhaustion stacks but the disadvantage doesn't compound, so any
      exhaustion entry surfaces the marker)
    """
    out: dict[str, list[str]] = {"passive_check_adv": [], "passive_check_dis": []}
    active = {c.lower() for c in conditions}
    if active & {"frightened", "poisoned", "exhaustion"}:
        out["passive_check_dis"].append("all")
    return out


__all__ = [
    "CONDITION_EFFECTS",
    "CONDITION_IMPLIES",
    "Condition",
    "active_condition_names",
    "apply_condition",
    "apply_condition_with_implies",
    "check_immunity",
    "conditions_grant_advantage_on_attack",
    "conditions_grant_disadvantage_on_ability_checks",
    "get_condition_effects",
    "is_condition_active",
    "project_passive_check_modifiers",
    "project_passive_damage_modifiers",
    "project_passive_save_modifiers",
    "remove_condition",
    "remove_condition_with_implies",
]
