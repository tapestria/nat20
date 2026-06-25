"""Dice rolling — pure functions, no side effects."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RollResult:
    dice: list[int]
    modifier: int
    total: int

    @property
    def raw(self) -> int:
        return sum(self.dice)


def roll(sides: int, count: int = 1, modifier: int = 0) -> RollResult:
    """Roll `count` d`sides` dice plus a modifier."""
    if sides < 1:
        raise ValueError(f"Dice must have at least 1 side, got {sides}")
    if count < 1:
        raise ValueError(f"Must roll at least 1 die, got {count}")
    dice = [random.randint(1, sides) for _ in range(count)]
    return RollResult(dice=dice, modifier=modifier, total=sum(dice) + modifier)


def roll_d4(count: int = 1, modifier: int = 0) -> RollResult:
    return roll(4, count, modifier)


def roll_d6(count: int = 1, modifier: int = 0) -> RollResult:
    return roll(6, count, modifier)


def roll_d8(count: int = 1, modifier: int = 0) -> RollResult:
    return roll(8, count, modifier)


def roll_d10(count: int = 1, modifier: int = 0) -> RollResult:
    return roll(10, count, modifier)


def roll_d12(count: int = 1, modifier: int = 0) -> RollResult:
    return roll(12, count, modifier)


def roll_d20(modifier: int = 0) -> RollResult:
    return roll(20, 1, modifier)


def roll_d100() -> RollResult:
    return roll(100, 1, 0)


def roll_with_advantage(modifier: int = 0) -> RollResult:
    """Roll 2d20, take the highest."""
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    best = max(a, b)
    return RollResult(dice=[a, b], modifier=modifier, total=best + modifier)


def roll_with_disadvantage(modifier: int = 0) -> RollResult:
    """Roll 2d20, take the lowest."""
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    worst = min(a, b)
    return RollResult(dice=[a, b], modifier=modifier, total=worst + modifier)


def parse_dice_expression(expr: str) -> RollResult:
    """
    Parse and roll a dice expression like "2d6+3", "1d8-1", "d20", "4d6".
    """
    expr = expr.strip().lower().replace(" ", "")
    modifier = 0

    # Extract modifier
    if "+" in expr:
        parts = expr.split("+", 1)
        expr = parts[0]
        modifier = int(parts[1])
    elif "-" in expr[1:]:  # avoid negative first char
        idx = expr.rindex("-")
        modifier = -int(expr[idx + 1 :])
        expr = expr[:idx]

    if "d" not in expr:
        raise ValueError(f"Invalid dice expression: {expr!r}")

    count_str, sides_str = expr.split("d", 1)
    count = int(count_str) if count_str else 1
    sides = int(sides_str)
    return roll(sides, count, modifier)


def ability_modifier(score: int) -> int:
    """D&D 5e ability score modifier: (score - 10) // 2."""
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    """D&D 5e character proficiency bonus by level: +2 at 1-4, +3 at 5-8, etc."""
    return 2 + (level - 1) // 4


def drop_lowest(rolls: list[int], drop: int = 1) -> list[int]:
    """Return rolls with the lowest `drop` values removed (for 4d6 drop lowest)."""
    return sorted(rolls, reverse=True)[: len(rolls) - drop]


def roll_4d6_drop_lowest() -> int:
    """Standard D&D stat generation: roll 4d6, drop the lowest."""
    rolls = [random.randint(1, 6) for _ in range(4)]
    return sum(drop_lowest(rolls, 1))


def generate_ability_scores_4d6() -> dict[str, int]:
    """Generate a full set of ability scores using 4d6 drop lowest."""
    stats = [roll_4d6_drop_lowest() for _ in range(6)]
    keys = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    return dict(zip(keys, stats, strict=True))


STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]

POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_TOTAL = 27


def validate_point_buy(scores: dict[str, int]) -> tuple[bool, str]:
    """Validate that a point-buy array is legal. Returns (valid, message)."""
    for stat, val in scores.items():
        if val not in POINT_BUY_COSTS:
            return False, f"{stat}={val} is not a valid point-buy value (8-15)"
    total = sum(POINT_BUY_COSTS[v] for v in scores.values())
    if total > POINT_BUY_TOTAL:
        return False, f"Total cost {total} exceeds {POINT_BUY_TOTAL}"
    return True, "OK"


__all__ = [
    "POINT_BUY_COSTS",
    "POINT_BUY_TOTAL",
    "STANDARD_ARRAY",
    "RollResult",
    "ability_modifier",
    "drop_lowest",
    "generate_ability_scores_4d6",
    "parse_dice_expression",
    "proficiency_bonus",
    "roll",
    "roll_4d6_drop_lowest",
    "roll_d4",
    "roll_d6",
    "roll_d8",
    "roll_d10",
    "roll_d12",
    "roll_d20",
    "roll_d100",
    "roll_with_advantage",
    "roll_with_disadvantage",
    "validate_point_buy",
]
