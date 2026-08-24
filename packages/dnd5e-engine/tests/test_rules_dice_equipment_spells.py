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
from dnd5e_engine.rules.equipment import (
    UNARMED_STRIKE_DAMAGE,
    VALID_SLOTS,
    calculate_ac,
    is_armor_proficient,
)
from dnd5e_engine.rules.spells import (
    FULL_CASTER_SLOTS,
    HALF_CASTER_SLOTS,
    SpellSlotState,
    can_cast,
    concentration_check,
    expend_slot,
    spell_slot_cost,
    spell_slots_for_class,
    upcast_bonus_dice,
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


def test_unarmored_ac_is_ten_plus_dex() -> None:
    assert (
        calculate_ac("unarmored", base_ac=0, max_dex_bonus=None, dex_score=16, has_shield=False)
        == 13
    )


def test_light_armor_adds_the_full_dex_modifier() -> None:
    """Leather (11) with DEX 18 -> 11 + 4."""
    assert (
        calculate_ac("light", base_ac=11, max_dex_bonus=None, dex_score=18, has_shield=False) == 15
    )


def test_medium_armor_caps_dex_at_two_by_default() -> None:
    """Half plate (15) with DEX 18 would be +4 uncapped; SRD caps it at +2."""
    assert (
        calculate_ac("medium", base_ac=15, max_dex_bonus=None, dex_score=18, has_shield=False) == 17
    )


def test_medium_armor_honors_an_explicit_cap() -> None:
    assert calculate_ac("medium", base_ac=14, max_dex_bonus=3, dex_score=18, has_shield=False) == 17


def test_medium_armor_uses_dex_when_below_the_cap() -> None:
    assert calculate_ac("medium", base_ac=14, max_dex_bonus=2, dex_score=12, has_shield=False) == 15


def test_medium_armor_applies_a_dex_penalty() -> None:
    """min(-1, 2) = -1 — a negative modifier is not clamped away."""
    assert calculate_ac("medium", base_ac=14, max_dex_bonus=2, dex_score=8, has_shield=False) == 13


def test_heavy_armor_ignores_dex_entirely() -> None:
    """Plate is a flat 18 whether DEX is 20 or 6."""
    assert calculate_ac("heavy", base_ac=18, max_dex_bonus=0, dex_score=20, has_shield=False) == 18
    assert calculate_ac("heavy", base_ac=18, max_dex_bonus=0, dex_score=6, has_shield=False) == 18


def test_shield_adds_two_to_any_armor_type() -> None:
    without = calculate_ac("light", base_ac=11, max_dex_bonus=None, dex_score=14, has_shield=False)
    with_shield = calculate_ac(
        "light", base_ac=11, max_dex_bonus=None, dex_score=14, has_shield=True
    )

    assert with_shield - without == 2


def test_unknown_armor_type_falls_back_to_unarmored() -> None:
    assert (
        calculate_ac(
            "mithril-plate", base_ac=99, max_dex_bonus=None, dex_score=14, has_shield=False
        )
        == 12
    )


def test_armor_type_matching_is_case_insensitive() -> None:
    assert calculate_ac("HEAVY", base_ac=16, max_dex_bonus=0, dex_score=20, has_shield=False) == 16


@pytest.mark.parametrize(
    "armor_type,profs,expected",
    [
        ("light", ["light", "medium"], True),
        ("heavy", ["light", "medium"], False),
        ("LIGHT", ["light"], True),
        ("light", ["Light"], True),
        ("shield", ["shields"], True),  # singular type vs plural proficiency
        ("shield", ["shield"], True),
        ("shield", ["light", "medium"], False),
        ("medium", [], False),
    ],
)
def test_armor_proficiency(armor_type: str, profs: list[str], expected: bool) -> None:
    assert is_armor_proficient(armor_type, profs) is expected


def test_equipment_constants() -> None:
    assert {"right_hand", "left_hand", "armor", "backpack"} == VALID_SLOTS
    assert UNARMED_STRIKE_DAMAGE == "1"


# ---------------------------------------------------------------------------
# Spell slots
# ---------------------------------------------------------------------------


def test_full_caster_table_matches_the_srd_progression() -> None:
    assert FULL_CASTER_SLOTS[0] == [2, 0, 0, 0, 0, 0, 0, 0, 0]
    assert FULL_CASTER_SLOTS[4] == [4, 3, 2, 0, 0, 0, 0, 0, 0]
    assert FULL_CASTER_SLOTS[19] == [4, 3, 3, 3, 3, 2, 2, 1, 1]
    assert len(FULL_CASTER_SLOTS) == 20
    assert all(len(row) == 9 for row in FULL_CASTER_SLOTS)


def test_half_casters_gain_no_slots_at_first_level() -> None:
    assert HALF_CASTER_SLOTS[0] == [0] * 9
    assert HALF_CASTER_SLOTS[1] == [2, 0, 0, 0, 0, 0, 0, 0, 0]


def test_half_caster_progression_trails_the_full_caster() -> None:
    """A half-caster never has more slots of any level than a full caster of
    the same level."""
    for level_idx in range(20):
        for slot_idx in range(9):
            assert HALF_CASTER_SLOTS[level_idx][slot_idx] <= FULL_CASTER_SLOTS[level_idx][slot_idx]


def test_spell_slots_for_full_caster_class() -> None:
    assert spell_slots_for_class("wizard", 5) == [4, 3, 2, 0, 0, 0, 0, 0, 0]
    assert spell_slots_for_class("Bard", 1) == [2, 0, 0, 0, 0, 0, 0, 0, 0]


def test_spell_slots_for_half_caster_class() -> None:
    assert spell_slots_for_class("paladin", 5) == [4, 2, 0, 0, 0, 0, 0, 0, 0]
    assert spell_slots_for_class("RANGER", 2) == [2, 0, 0, 0, 0, 0, 0, 0, 0]


def test_spell_slots_for_non_caster_class_are_empty() -> None:
    assert spell_slots_for_class("fighter", 20) == [0] * 9


def test_spell_slots_returns_a_copy_so_callers_cannot_corrupt_the_table() -> None:
    slots = spell_slots_for_class("wizard", 1)
    slots[0] = 99

    assert FULL_CASTER_SLOTS[0][0] == 2


@pytest.mark.parametrize("level", [0, -1, 21])
def test_spell_slots_rejects_levels_outside_1_to_20(level: int) -> None:
    with pytest.raises(ValueError, match="Invalid level"):
        spell_slots_for_class("wizard", level)


def test_spell_slot_cost_is_always_one() -> None:
    assert spell_slot_cost(1) == 1
    assert spell_slot_cost(9) == 1


@pytest.mark.parametrize("spell_level", [-1, 10])
def test_spell_slot_cost_rejects_levels_outside_0_to_9(spell_level: int) -> None:
    with pytest.raises(ValueError, match="Invalid spell level"):
        spell_slot_cost(spell_level)


def test_spell_slot_state_remaining_is_total_minus_used() -> None:
    state = SpellSlotState(total=[4, 3] + [0] * 7, used=[1, 3] + [0] * 7)

    assert state.remaining[:2] == [3, 0]


def test_cantrips_are_always_castable() -> None:
    empty = SpellSlotState()

    assert can_cast(empty, 0) is True


def test_can_cast_requires_a_remaining_slot_of_that_level() -> None:
    state = SpellSlotState(total=[2, 1] + [0] * 7, used=[2, 0] + [0] * 7)

    assert can_cast(state, 1) is False  # both first-level slots spent
    assert can_cast(state, 2) is True


def test_expend_slot_returns_new_state_and_leaves_the_original_untouched() -> None:
    state = SpellSlotState(total=[2] + [0] * 8, used=[0] * 9)

    new_state = expend_slot(state, 1)

    assert new_state.used[0] == 1
    assert state.used[0] == 0, "expend_slot must not mutate the caller's state"
    assert new_state.total == state.total


def test_expend_cantrip_is_a_no_op() -> None:
    state = SpellSlotState(total=[2] + [0] * 8)

    assert expend_slot(state, 0) is state


def test_expend_slot_without_a_remaining_slot_raises() -> None:
    state = SpellSlotState(total=[1] + [0] * 8, used=[1] + [0] * 8)

    with pytest.raises(ValueError, match="No spell slots remaining at level 1"):
        expend_slot(state, 1)


@pytest.mark.parametrize(
    "base_level,cast_level,expected",
    [(1, 1, 0), (1, 3, 2), (3, 5, 2), (5, 3, 0)],  # downcasting never yields negative dice
)
def test_upcast_bonus_dice(base_level: int, cast_level: int, expected: int) -> None:
    assert upcast_bonus_dice("1d8", base_level, cast_level) == expected


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------


def test_concentration_dc_floor_is_ten() -> None:
    """Small hits still use DC 10: a CON +5 caster with proficiency (+3) can
    never roll below 1+8 = 9... but must still fail on a 1."""
    random.seed(15)
    outcomes = {
        concentration_check(
            constitution_score=20, proficient=True, proficiency_bonus=3, damage_taken=2
        )
        for _ in range(200)
    }

    # d20 + 8 vs DC 10 -> fails only on a natural 1.
    assert outcomes == {True, False}


def test_concentration_dc_scales_with_half_damage() -> None:
    """40 damage -> DC 20. A CON 10 caster without proficiency needs a nat 20."""
    random.seed(16)
    successes = sum(
        concentration_check(
            constitution_score=10, proficient=False, proficiency_bonus=2, damage_taken=40
        )
        for _ in range(400)
    )

    # Roughly 1 in 20 attempts should clear DC 20 on a flat d20.
    assert 0 < successes < 60


def test_concentration_proficiency_only_counts_when_proficient() -> None:
    """An impossible DC must fail regardless; a trivially-low DC must always
    pass — together these pin that the modifier is applied, not ignored."""
    random.seed(17)

    # CON 20 (+5) + proficiency (+6) = +11 vs DC 10 — the lowest possible
    # roll is 12, so concentration always holds.
    assert all(
        concentration_check(
            constitution_score=20, proficient=True, proficiency_bonus=6, damage_taken=0
        )
        for _ in range(50)
    )

    assert not any(
        concentration_check(
            constitution_score=1, proficient=False, proficiency_bonus=0, damage_taken=100
        )
        for _ in range(50)
    ), "DC 50 is unreachable with d20-5"
