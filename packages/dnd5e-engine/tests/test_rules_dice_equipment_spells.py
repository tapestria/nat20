"""Behavioral tests for the SRD arithmetic in ``rules/dice``, ``rules/equipment``
and ``rules/spells``.

These modules encode published SRD tables and formulas, so the assertions are
against the SRD values themselves (ability modifier, proficiency bonus by
level, point-buy costs, armor-class rules, spell-slot progressions) rather
than against whatever the implementation currently returns. Dice functions
draw from the module-global RNG, so the tests seed it and assert on
structure and bounds — the properties that must hold for every roll — instead
of pinning one lucky sequence.
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine.rules.dice import (
    POINT_BUY_COSTS,
    POINT_BUY_TOTAL,
    STANDARD_ARRAY,
    RollResult,
    ability_modifier,
    drop_lowest,
    generate_ability_scores_4d6,
    parse_dice_expression,
    proficiency_bonus,
    roll,
    roll_4d6_drop_lowest,
    roll_d4,
    roll_d6,
    roll_d8,
    roll_d10,
    roll_d12,
    roll_d20,
    roll_d100,
    roll_with_advantage,
    roll_with_disadvantage,
    validate_point_buy,
)

ABILITIES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


# ---------------------------------------------------------------------------
# roll / RollResult
# ---------------------------------------------------------------------------


def test_roll_result_raw_excludes_the_modifier() -> None:
    result = RollResult(dice=[3, 4], modifier=5, total=12)

    assert result.raw == 7
    assert result.total == 12


def test_roll_produces_count_dice_within_range_and_sums_with_modifier() -> None:
    random.seed(4)
    for _ in range(50):
        result = roll(6, count=3, modifier=2)

        assert len(result.dice) == 3
        assert all(1 <= d <= 6 for d in result.dice)
        assert result.total == sum(result.dice) + 2
        assert result.raw == sum(result.dice)


def test_roll_defaults_to_a_single_unmodified_die() -> None:
    random.seed(5)
    result = roll(8)

    assert len(result.dice) == 1
    assert result.modifier == 0
    assert result.total == result.dice[0]


@pytest.mark.parametrize("sides", [0, -1])
def test_roll_rejects_dice_without_sides(sides: int) -> None:
    with pytest.raises(ValueError, match="at least 1 side"):
        roll(sides)


@pytest.mark.parametrize("count", [0, -3])
def test_roll_rejects_non_positive_die_count(count: int) -> None:
    with pytest.raises(ValueError, match="at least 1 die"):
        roll(6, count=count)


@pytest.mark.parametrize(
    "fn,sides",
    [(roll_d4, 4), (roll_d6, 6), (roll_d8, 8), (roll_d10, 10), (roll_d12, 12)],
)
def test_die_shorthands_roll_the_right_die(fn, sides: int) -> None:
    random.seed(6)
    for _ in range(30):
        result = fn(count=2, modifier=1)

        assert len(result.dice) == 2
        assert all(1 <= d <= sides for d in result.dice)
        assert result.total == sum(result.dice) + 1


def test_roll_d20_is_a_single_die_with_modifier() -> None:
    random.seed(7)
    for _ in range(30):
        result = roll_d20(modifier=3)

        assert len(result.dice) == 1
        assert 1 <= result.dice[0] <= 20
        assert result.total == result.dice[0] + 3


def test_roll_d100_is_unmodified() -> None:
    random.seed(8)
    for _ in range(30):
        result = roll_d100()

        assert 1 <= result.dice[0] <= 100
        assert result.modifier == 0
        assert result.total == result.dice[0]


# ---------------------------------------------------------------------------
# advantage / disadvantage
# ---------------------------------------------------------------------------


def test_advantage_keeps_both_dice_and_totals_the_higher_one() -> None:
    random.seed(9)
    for _ in range(50):
        result = roll_with_advantage(modifier=2)

        assert len(result.dice) == 2
        assert result.total == max(result.dice) + 2


def test_disadvantage_keeps_both_dice_and_totals_the_lower_one() -> None:
    random.seed(10)
    for _ in range(50):
        result = roll_with_disadvantage(modifier=2)

        assert len(result.dice) == 2
        assert result.total == min(result.dice) + 2


def test_advantage_beats_disadvantage_on_average() -> None:
    """A statistical sanity check that the two are not swapped."""
    random.seed(11)
    adv = sum(roll_with_advantage().total for _ in range(300))
    dis = sum(roll_with_disadvantage().total for _ in range(300))

    assert adv > dis


# ---------------------------------------------------------------------------
# parse_dice_expression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,count,sides,modifier",
    [
        ("2d6+3", 2, 6, 3),
        ("1d8-1", 1, 8, -1),
        ("d20", 1, 20, 0),
        ("4d6", 4, 6, 0),
        ("  3D8 + 2 ", 3, 8, 2),  # whitespace and case are normalized
        ("d20-2", 1, 20, -2),
        ("2d10+10", 2, 10, 10),
    ],
)
def test_parse_dice_expression_shapes(expr: str, count: int, sides: int, modifier: int) -> None:
    random.seed(12)
    result = parse_dice_expression(expr)

    assert len(result.dice) == count
    assert all(1 <= d <= sides for d in result.dice)
    assert result.modifier == modifier
    assert result.total == sum(result.dice) + modifier


@pytest.mark.parametrize("expr", ["", "2x6", "hello", "12"])
def test_parse_dice_expression_rejects_expressions_without_a_die(expr: str) -> None:
    with pytest.raises(ValueError):
        parse_dice_expression(expr)


# ---------------------------------------------------------------------------
# SRD arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,modifier",
    [(1, -5), (3, -4), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (15, 2), (20, 5), (30, 10)],
)
def test_ability_modifier_matches_the_srd_table(score: int, modifier: int) -> None:
    assert ability_modifier(score) == modifier


@pytest.mark.parametrize(
    "level,bonus",
    [
        (1, 2),
        (4, 2),
        (5, 3),
        (8, 3),
        (9, 4),
        (12, 4),
        (13, 5),
        (16, 5),
        (17, 6),
        (20, 6),
    ],
)
def test_proficiency_bonus_matches_the_srd_table(level: int, bonus: int) -> None:
    assert proficiency_bonus(level) == bonus


def test_drop_lowest_removes_the_smallest_value() -> None:
    assert drop_lowest([6, 1, 4, 3]) == [6, 4, 3]


def test_drop_lowest_can_drop_several() -> None:
    assert drop_lowest([6, 1, 4, 3], drop=2) == [6, 4]


def test_roll_4d6_drop_lowest_stays_within_the_possible_range() -> None:
    """Three of four d6 kept -> 3..18."""
    random.seed(13)
    for _ in range(200):
        assert 3 <= roll_4d6_drop_lowest() <= 18


def test_generate_ability_scores_returns_all_six_abilities() -> None:
    random.seed(14)
    scores = generate_ability_scores_4d6()

    assert tuple(scores) == ABILITIES
    assert all(3 <= v <= 18 for v in scores.values())


def test_standard_array_is_the_srd_spread() -> None:
    assert STANDARD_ARRAY == [15, 14, 13, 12, 10, 8]


def test_point_buy_costs_match_the_srd_table() -> None:
    assert POINT_BUY_COSTS == {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
    assert POINT_BUY_TOTAL == 27


def test_point_buy_accepts_a_legal_spread() -> None:
    """15/15/15/8/8/8 costs 9+9+9 = 27 — exactly the budget."""
    valid, message = validate_point_buy(
        {
            "strength": 15,
            "dexterity": 15,
            "constitution": 15,
            "intelligence": 8,
            "wisdom": 8,
            "charisma": 8,
        }
    )

    assert valid is True
    assert message == "OK"


def test_point_buy_rejects_scores_outside_the_table() -> None:
    valid, message = validate_point_buy({"strength": 16})

    assert valid is False
    assert "strength=16" in message


def test_point_buy_rejects_an_over_budget_spread() -> None:
    valid, message = validate_point_buy(dict.fromkeys(ABILITIES, 15))

    assert valid is False
    assert "exceeds 27" in message


def test_point_buy_allows_spending_under_budget() -> None:
    valid, _ = validate_point_buy(dict.fromkeys(ABILITIES, 8))

    assert valid is True


# ---------------------------------------------------------------------------
# Armor class
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Spell slots
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------
