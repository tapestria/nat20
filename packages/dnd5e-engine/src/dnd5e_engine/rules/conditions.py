"""D&D 5e conditions — effects and application logic."""

from __future__ import annotations

from collections.abc import Iterable
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

#: Conditions that make their bearer immune to another condition. SRD 5.2
#: Petrified: "Poison Immunity. You have Immunity to the Poisoned condition."
#: Immunity means the condition "doesn't affect you in any way": it never
#: attaches (``activities/effects.py::is_condition_immune``), and one the
#: creature already had stops imposing anything while the grant lasts.
CONDITION_GRANTED_IMMUNITIES: dict[Condition, frozenset[str]] = {
    Condition.PETRIFIED: frozenset({Condition.POISONED.value}),
}

# Human-readable effects per condition, phrased against SRD 5.2 (2024).
#
# These strings are DESCRIPTIVE ONLY — they are surfaced by
# ``get_condition_effects`` for hosts to display, and are not what the engine
# enforces. A condition's actual mechanical effect reaches a roll through the
# projection helpers below (``project_passive_*``) and the active-effect fold in
# the orchestrator. Where the two differ, the projections are authoritative and
# the gap is tracked in BACKLOG.md; do not read this table as a statement of
# what is implemented.
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
    # SRD 5.2 replaced the 2014 six-tier ladder with two scaling penalties.
    # NOT ENFORCED by the engine today: the level is tracked but applies no
    # penalty (see BACKLOG.md).
    Condition.EXHAUSTION: [
        "D20 Tests are reduced by 2 times the creature's Exhaustion level",
        "Speed is reduced by 5 feet times the creature's Exhaustion level",
        "Exhaustion level 6 is death",
        "Finishing a Long Rest removes one level",
    ],
    Condition.FRIGHTENED: [
        "Disadvantage on ability checks and attack rolls while source of fear is in line of sight",
        "Cannot willingly move closer to source of fear",
    ],
    Condition.GRAPPLED: [
        "Speed is 0 and can't increase",
        "Disadvantage on attack rolls against any target other than the grappler",
        "The grappler can drag or carry this creature when it moves",
    ],
    Condition.INCAPACITATED: [
        "Cannot take any action, Bonus Action, or Reaction",
        "Concentration is broken",
        "Cannot speak",
        "Disadvantage on Initiative if Incapacitated when rolling it",
    ],
    Condition.INVISIBLE: [
        "Concealed: unaffected by effects that require the target to be seen",
        "Attacks by this creature have advantage",
        "Attacks against this creature have disadvantage",
    ],
    Condition.PARALYZED: [
        "Incapacitated; Speed is 0 and can't increase",
        "Automatically fails STR and DEX saving throws",
        "Attack rolls against this creature have advantage",
        "Any attack that hits is a critical hit if within 5 feet",
    ],
    Condition.PETRIFIED: [
        "Transformed into stone; incapacitated, can't move or speak",
        "Attacks against this creature have advantage",
        "Automatically fails STR and DEX saving throws",
        "Resistance to all damage",
        "Immune to the Poisoned condition",
    ],
    Condition.POISONED: [
        "Disadvantage on attack rolls and ability checks",
    ],
    Condition.PRONE: [
        "Only movement option is to crawl, unless the creature stands up",
        "Disadvantage on attack rolls",
        "An attack roll against this creature has advantage if the attacker is "
        "within 5 feet, and disadvantage otherwise",
    ],
    Condition.RESTRAINED: [
        "Speed becomes 0",
        "Attack rolls against this creature have advantage",
        "This creature's attack rolls have disadvantage",
        "Disadvantage on DEX saving throws",
    ],
    Condition.STUNNED: [
        "Incapacitated",
        "Automatically fails STR and DEX saving throws",
        "Attack rolls against this creature have advantage",
    ],
    Condition.UNCONSCIOUS: [
        "Incapacitated and Prone; remains Prone when the condition ends",
        "Speed is 0 and can't increase; drops whatever it is holding",
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


def granted_condition_immunities(conditions: Iterable[str]) -> frozenset[str]:
    """The condition slugs ``conditions`` make their bearer immune to
    (``CONDITION_GRANTED_IMMUNITIES``): ``{"poisoned"}`` while Petrified."""
    active = {c.lower() for c in conditions}
    granted: set[str] = set()
    for condition, immune_to in CONDITION_GRANTED_IMMUNITIES.items():
        if condition.value in active:
            granted |= immune_to
    return frozenset(granted)


def check_immunity(condition_name: str, immunities: list[str]) -> bool:
    """Static immunities only; ``granted_condition_immunities`` adds the
    immunity a held condition grants (Petrified → Poisoned)."""
    return condition_name in immunities


def conditions_grant_disadvantage_on_ability_checks(
    conditions: list[str], *, fear_source_in_sight: bool = True
) -> bool:
    """Return True if conditions impose disadvantage on ability checks.

    SRD 5.2 glossary: Poisoned — "You have Disadvantage on attack rolls and
    ability checks."; Frightened — "You have Disadvantage on ability checks and
    attack rolls while the source of fear is within line of sight."

    ``fear_source_in_sight`` is the attack-roll helper's flag
    (``conditions_grant_advantage_on_attack``): True, the SRD-conservative
    default, unless the caller knows the Frightened creature can't see its
    fear source. A condition the creature is immune to imposes nothing
    (``granted_condition_immunities``: a Petrified creature's Poisoned).

    Exhaustion is deliberately NOT here: SRD 5.2 replaced the 2014 ladder with a
    numeric ``-2 x level`` penalty on every D20 Test — see ``d20_test_penalty``.
    (Behavioural change in 0.6.0; see docs/migration/v0.5-to-v0.6.md.)
    """
    active = {c.lower() for c in conditions}
    active -= granted_condition_immunities(active)
    if Condition.POISONED.value in active:
        return True
    return Condition.FRIGHTENED.value in active and fear_source_in_sight


def conditions_grant_advantage_on_attack(
    attacker_conditions: list[str],
    target_conditions: list[str],
    *,
    distance_ft: int | None = None,
    grappler_id: str | None = None,
    target_id: str | None = None,
    attacker_invisibility_pierced: bool = False,
    target_invisibility_pierced: bool = False,
    fear_source_in_sight: bool = True,
) -> tuple[bool, bool]:
    """
    Returns (attacker_has_advantage, attacker_has_disadvantage) based on conditions.
    Does NOT account for ranged vs melee distinction (caller's responsibility).

    Keyword inputs (all optional — absent means "unknown" and the row that
    needs it stays inert, so pre-0.6 callers are unaffected):

    * ``distance_ft`` — attacker→target distance for the Prone target row
      (SRD 5.2 Prone: advantage within 5 ft, disadvantage otherwise).
    * ``grappler_id`` / ``target_id`` — identity of the creature grappling the
      ATTACKER and of the target, for the Grappled attacker row (SRD 5.2
      Grappled: disadvantage against any target other than the grappler).
    * ``attacker_invisibility_pierced`` — True iff the TARGET can somehow see
      the Invisible ATTACKER (a special sense — Blindsight/Truesight — reaches
      AND line of sight holds). SRD 5.2 Invisible: "If a creature can somehow
      see you, you don't gain this benefit against that creature." Default
      ``False`` preserves pre-C16b behaviour (no vision model wired).
    * ``target_invisibility_pierced`` — the same, but for the ATTACKER seeing
      the Invisible TARGET.
    * ``fear_source_in_sight`` — SRD 5.2 Frightened: "Disadvantage on ...
      attack rolls while the source of fear is within line of sight." True
      (the SRD-conservative default) means either the attacker isn't
      Frightened, or the gate doesn't apply / can't be evaluated (unknown
      source), or the source is actually visible — so the disadvantage row
      below still fires. Only an explicit ``False`` — a known, tracked
      source the Frightened attacker cannot currently see — drops it.
    """
    advantage = False
    disadvantage = False

    if (
        is_condition_active(Condition.INVISIBLE, attacker_conditions)
        and not attacker_invisibility_pierced
    ):
        advantage = True
    if is_condition_active(Condition.BLINDED, attacker_conditions):
        disadvantage = True
    if is_condition_active(Condition.POISONED, attacker_conditions):
        disadvantage = True
    # SRD 5.2 glossary, Frightened: "Disadvantage on ... attack rolls while
    # the source of fear is within line of sight." (C16b: ``fear_source_in_sight``
    # defaults True — SRD-conservative — so pre-C16b callers are unaffected.)
    if is_condition_active(Condition.FRIGHTENED, attacker_conditions) and fear_source_in_sight:
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
    # SRD 5.2 glossary, Restrained: "Attack rolls against you have Advantage,
    # and your attack rolls have Disadvantage."
    if is_condition_active(Condition.RESTRAINED, target_conditions):
        advantage = True
    # SRD 5.2 glossary, Petrified: "Attacks Affected. Attack rolls against you
    # have Advantage."
    if is_condition_active(Condition.PETRIFIED, target_conditions):
        advantage = True
    # SRD 5.2 glossary, Invisible: "Attack rolls against you have Disadvantage,
    # and your attack rolls have Advantage. If a creature can somehow see you,
    # you don't gain this benefit against that creature." (C16b: the "can
    # somehow see you" exception is ``target_invisibility_pierced`` — the
    # ATTACKER's Blindsight/Truesight reaching the Invisible target plus line
    # of sight.)
    if (
        is_condition_active(Condition.INVISIBLE, target_conditions)
        and not target_invisibility_pierced
    ):
        disadvantage = True

    # SRD 5.2 glossary, Prone: "You have Disadvantage on attack rolls."
    if is_condition_active(Condition.PRONE, attacker_conditions):
        disadvantage = True
    # SRD 5.2 glossary, Prone: "An attack roll against you has Advantage if the
    # attacker is within 5 feet of you. Otherwise, that attack roll has
    # Disadvantage." Needs a distance; unknown distance → inert.
    if is_condition_active(Condition.PRONE, target_conditions) and distance_ft is not None:
        if distance_ft <= 5:
            advantage = True
        else:
            disadvantage = True
    # SRD 5.2 glossary, Grappled: "You have Disadvantage on attack rolls against
    # any target other than the grappler." Unknown grappler → inert (never
    # penalise a swing that might be at the grappler).
    if (
        is_condition_active(Condition.GRAPPLED, attacker_conditions)
        and grappler_id is not None
        and target_id != grappler_id
    ):
        disadvantage = True

    return advantage, disadvantage


# ── SRD 5.2 condition predicates and numeric projections (C12) ──────────────

#: SRD 5.2 glossary, "Speed 0. Your Speed is 0 and can't increase." — Grappled,
#: Restrained, Paralyzed, Petrified, Unconscious. Stunned carries no Speed
#: clause in SRD 5.2 (the 2014 "can't move" text was dropped), Prone restricts
#: the movement MODE (crawl / stand up) rather than the Speed.
SPEED_ZERO_CONDITIONS: frozenset[str] = frozenset(
    {"grappled", "restrained", "paralyzed", "petrified", "unconscious"}
)

#: SRD 5.2 glossary, Paralyzed / Unconscious: "Any attack roll that hits you is
#: a Critical Hit if the attacker is within 5 feet of you."
AUTO_CRIT_WITHIN_5FT_CONDITIONS: frozenset[str] = frozenset({"paralyzed", "unconscious"})

#: SRD 5.2 Exhaustion: "When you make a D20 Test, the roll is reduced by 2
#: times your Exhaustion level." / "Your Speed is reduced by a number of feet
#: equal to 5 times your Exhaustion level." (Foundry ``config.mjs``
#: ``conditionTypes.exhaustion.reduction = {rolls: 2, speed: 5}``.)
EXHAUSTION_D20_PENALTY_PER_LEVEL = 2
EXHAUSTION_SPEED_PENALTY_PER_LEVEL = 5


def exhaustion_level_of(conditions: list[ActiveCondition]) -> int:
    """The creature's Exhaustion level: the highest ``exhaustion_level`` carried
    by any ``exhaustion`` entry (0 when the condition is absent)."""
    return max(
        (ac.exhaustion_level for ac in conditions if ac.condition.lower() == "exhaustion"),
        default=0,
    )


def d20_test_penalty(conditions: list[ActiveCondition]) -> int:
    """The signed flat modifier SRD 5.2 Exhaustion applies to EVERY D20 Test
    (attack rolls, saving throws — death saves included — and ability checks):
    ``-2 x level``; ``0`` when not exhausted."""
    return -EXHAUSTION_D20_PENALTY_PER_LEVEL * exhaustion_level_of(conditions)


def project_speed(base_speed: int, condition_names: list[str], exhaustion_level: int = 0) -> int:
    """The creature's effective walking Speed under its conditions.

    A ``SPEED_ZERO_CONDITIONS`` member forces 0 ("and can't increase" — the
    orchestrator's Dash adds THIS projection, not ``base_speed``); otherwise
    Exhaustion subtracts ``5 x level``, floored at 0.
    """
    active = {c.lower() for c in condition_names}
    if active & SPEED_ZERO_CONDITIONS:
        return 0
    return max(0, base_speed - EXHAUSTION_SPEED_PENALTY_PER_LEVEL * exhaustion_level)


def conditions_block_actions(condition_names: list[str]) -> bool:
    """SRD 5.2 Incapacitated: "You can't take any action, Bonus Action, or
    Reaction." True when Incapacitated is active directly or via
    ``CONDITION_IMPLIES`` (Paralyzed, Petrified, Stunned, Unconscious)."""
    return is_condition_active(Condition.INCAPACITATED, condition_names)


def conditions_auto_crit_within_5ft(target_condition_names: list[str]) -> bool:
    """True when a hit on this target from within 5 ft is automatically a
    Critical Hit (SRD 5.2 Paralyzed / Unconscious)."""
    active = {c.lower() for c in target_condition_names}
    return bool(active & AUTO_CRIT_WITHIN_5FT_CONDITIONS)


# ── Per-effect sidecar projection (combat orchestrator hydration) ────────────
#
# The combat orchestrator hydrates the active-effect projection sidecars from the live
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

    Only Petrified contributes: SRD 5.2 "Resist Damage. You have Resistance to
    all damage." Poison damage is halved like any other — its "Poison
    Immunity" is to the Poisoned condition (``CONDITION_GRANTED_IMMUNITIES``),
    not to the damage type.
    """
    out: dict[str, list[str]] = {"resistances": [], "vulnerabilities": [], "immunities": []}
    if "petrified" in {c.lower() for c in conditions}:
        out["resistances"].append("all")
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


def project_passive_check_modifiers(
    conditions: list[str], *, fear_source_in_sight: bool = True
) -> dict[str, list[str]]:
    """Return ``passive_check_adv`` / ``passive_check_dis`` lists.

    Conditions that impose disadvantage on *every* ability check use the
    ``"all"`` catch-all marker the ``check.py`` handler already recognizes
    (see ``_reconcile_adv_dis``): Poisoned, and Frightened while its source is
    in sight — ``conditions_grant_disadvantage_on_ability_checks`` decides,
    with the same ``fear_source_in_sight`` flag. Exhaustion is NOT projected
    here (SRD 5.2: numeric ``-2 x level`` penalty on every D20 Test, see
    ``d20_test_penalty``).
    """
    out: dict[str, list[str]] = {"passive_check_adv": [], "passive_check_dis": []}
    if conditions_grant_disadvantage_on_ability_checks(
        conditions, fear_source_in_sight=fear_source_in_sight
    ):
        out["passive_check_dis"].append("all")
    return out


__all__ = [
    "AUTO_CRIT_WITHIN_5FT_CONDITIONS",
    "CONDITION_EFFECTS",
    "CONDITION_GRANTED_IMMUNITIES",
    "CONDITION_IMPLIES",
    "EXHAUSTION_D20_PENALTY_PER_LEVEL",
    "EXHAUSTION_SPEED_PENALTY_PER_LEVEL",
    "SPEED_ZERO_CONDITIONS",
    "Condition",
    "active_condition_names",
    "apply_condition",
    "apply_condition_with_implies",
    "check_immunity",
    "conditions_auto_crit_within_5ft",
    "conditions_block_actions",
    "conditions_grant_advantage_on_attack",
    "conditions_grant_disadvantage_on_ability_checks",
    "d20_test_penalty",
    "exhaustion_level_of",
    "get_condition_effects",
    "granted_condition_immunities",
    "is_condition_active",
    "project_passive_check_modifiers",
    "project_passive_damage_modifiers",
    "project_passive_save_modifiers",
    "project_speed",
    "remove_condition",
    "remove_condition_with_implies",
]
