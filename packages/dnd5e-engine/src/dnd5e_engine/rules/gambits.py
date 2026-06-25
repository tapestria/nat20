"""Deterministic monster AI gambit system.

Selects actions for monsters based on behavior profile and current game state.
Zero DB imports. Uses only dnd5e_engine.rules.* imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from dnd5e_engine.rules.combat import HitType, attack_roll, damage_roll

# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------


class BehaviorProfile(StrEnum):
    AGGRESSIVE = "AGGRESSIVE"
    RANGED = "RANGED"
    DEFENSIVE = "DEFENSIVE"


@dataclass(frozen=True)
class GambitAction:
    """An action selected by the gambit system for a monster."""

    action_type: str  # melee_attack | ranged_attack | flee | pass
    target_priority: str  # lowest_hp | random
    description: str


@dataclass
class MonsterActionResult:
    """Result of resolving a monster's gambit action."""

    hit: bool
    damage: int
    damage_type: str
    is_critical: bool
    description: str
    target_id: str
    death_save_failures: int  # 0 normally; 2 for melee auto-crit on unconscious target


# ---------------------------------------------------------------------------
# Damage dice parser
# ---------------------------------------------------------------------------


def parse_damage_dice(expr: str) -> tuple[int, int, int]:
    """Parse a damage dice expression like "2d6+3" into (count, sides, modifier).

    Supports:
    - "2d6+3"  -> (2, 6, 3)
    - "1d8-1"  -> (1, 8, -1)
    - "3d4"    -> (3, 4, 0)
    - "1d6+0"  -> (1, 6, 0)
    """
    expr = expr.strip().lower().replace(" ", "")

    # Match pattern: <count>d<sides>[+/-<modifier>]
    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", expr)
    if not match:
        raise ValueError(f"Invalid damage dice expression: {expr!r}")

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    return count, sides, modifier


# ---------------------------------------------------------------------------
# Action selection
# ---------------------------------------------------------------------------

_PASS_ACTION = GambitAction(
    action_type="pass",
    target_priority="random",
    description="No valid targets.",
)


def _get_alive_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in targets if t.get("is_alive", False) or t.get("hp_current", 0) > 0]


def select_action(
    profile: BehaviorProfile,
    monster_hp_current: int,
    monster_hp_max: int,
    targets: list[dict[str, Any]],
) -> GambitAction:
    """Select the next action for a monster given its profile and situation.

    Returns a GambitAction. If no alive targets remain, returns pass.

    Priority lists:
    - AGGRESSIVE: [hp < 10% -> flee], [else -> melee_attack(lowest_hp)]
    - RANGED:     [hp < 25% -> flee], [else -> ranged_attack(lowest_hp)]
    - DEFENSIVE:  [else -> melee_attack(lowest_hp)]  (no heal in v1)
    """
    alive = _get_alive_targets(targets)
    if not alive:
        return _PASS_ACTION

    hp_ratio = monster_hp_current / monster_hp_max if monster_hp_max > 0 else 0.0

    if profile == BehaviorProfile.AGGRESSIVE:
        if hp_ratio < 0.10:
            return GambitAction(
                action_type="flee",
                target_priority="random",
                description="Flees in panic!",
            )
        return GambitAction(
            action_type="melee_attack",
            target_priority="lowest_hp",
            description="Attacks the weakest foe.",
        )

    if profile == BehaviorProfile.RANGED:
        if hp_ratio < 0.25:
            return GambitAction(
                action_type="flee",
                target_priority="random",
                description="Retreats to a safe distance!",
            )
        return GambitAction(
            action_type="ranged_attack",
            target_priority="lowest_hp",
            description="Fires at the weakest foe.",
        )

    # DEFENSIVE (v1: no heal ability, always melee attack)
    return GambitAction(
        action_type="melee_attack",
        target_priority="lowest_hp",
        description="Defends and strikes.",
    )


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


def resolve_monster_action(
    action: GambitAction,
    attack_bonus: int,
    damage_dice: str,
    damage_type: str,
    target: dict[str, Any],
    monster_name: str,
) -> MonsterActionResult:
    """Resolve a monster action against a target.

    For flee/pass: returns a no-damage result.
    For melee/ranged attacks:
    - If target hp_current <= 0: auto-hit + auto-crit (D&D RAW — melee within 5ft) + 2 death saves.
    - Otherwise: standard attack_roll + damage_roll from rules/combat.

    damage_dice: "XdY+Z" string (e.g. "2d6+3")
    """
    target_id = str(target.get("entity_id", ""))
    target_name = str(target.get("name", "target"))

    # Non-attack actions
    if action.action_type in ("flee", "pass"):
        return MonsterActionResult(
            hit=False,
            damage=0,
            damage_type=damage_type,
            is_critical=False,
            description=f"{monster_name} {action.description}",
            target_id=target_id,
            death_save_failures=0,
        )

    dice_count, dice_sides, dice_modifier = parse_damage_dice(damage_dice)
    target_ac = int(target.get("armor_class", 10))
    is_unconscious = target.get("hp_current", 1) <= 0

    if is_unconscious:
        # Auto-hit + auto-crit when target is at 0 HP (melee within 5ft per RAW)
        dmg = damage_roll(dice_count, dice_sides, dice_modifier, damage_type, is_critical=True)
        return MonsterActionResult(
            hit=True,
            damage=dmg.total,
            damage_type=damage_type,
            is_critical=True,
            description=(
                f"{monster_name} strikes the unconscious {target_name} with a devastating blow!"
            ),
            target_id=target_id,
            death_save_failures=2,
        )

    # Normal attack
    atk = attack_roll(attack_bonus, target_ac)
    is_hit = atk.hit_type in (HitType.HIT, HitType.CRITICAL_HIT)
    is_crit = atk.hit_type == HitType.CRITICAL_HIT

    if is_hit:
        dmg = damage_roll(dice_count, dice_sides, dice_modifier, damage_type, is_critical=is_crit)
        dmg_total = dmg.total
        hit_word = "critically hits" if is_crit else "hits"
        desc = f"{monster_name} {hit_word} {target_name} for {dmg_total} {damage_type} damage!"
    else:
        dmg_total = 0
        desc = f"{monster_name} misses {target_name}."

    return MonsterActionResult(
        hit=is_hit,
        damage=dmg_total,
        damage_type=damage_type,
        is_critical=is_crit,
        description=desc,
        target_id=target_id,
        death_save_failures=0,
    )


# ---------------------------------------------------------------------------
# Behavior profile assignment
# ---------------------------------------------------------------------------


def assign_behavior_profile(monster_stats: dict[str, Any]) -> BehaviorProfile:
    """Assign a behavior profile to a monster based on its stats.

    Heuristic:
    - has_ranged_attack=True -> RANGED
    - Otherwise             -> AGGRESSIVE (DEFENSIVE reserved for future healers)
    """
    has_ranged = bool(monster_stats.get("has_ranged_attack", False))
    if has_ranged:
        return BehaviorProfile.RANGED
    return BehaviorProfile.AGGRESSIVE


__all__ = [
    "BehaviorProfile",
    "GambitAction",
    "MonsterActionResult",
    "assign_behavior_profile",
    "parse_damage_dice",
    "resolve_monster_action",
    "select_action",
]
