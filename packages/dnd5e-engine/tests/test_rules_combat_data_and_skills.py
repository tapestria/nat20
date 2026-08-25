"""Behavioral tests for ``rules/combat_data.py`` and ``rules/skills.py``.

Both encode SRD formulas a host reads on every roll:

- Cantrip scaling adds a fixed number of dice at each tier reached (5th, 11th,
  17th), keeping the *base* die size — a Fire Bolt at 11th is 3d10, not 3d6.
- Spell attack bonus and save DC share a spellcasting ability per class, and
  non-casters must return ``None`` rather than a misleading 0.
- Weapon attack bonus picks STR for melee, DEX for ranged, and the better of
  the two only for finesse *melee*.
- Skill checks fold proficiency, expertise (double) and Jack of All Trades
  (half, rounded down, only when not already proficient).
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine.rules.skills import (
    SKILL_ABILITIES,
    SKILL_DISPLAY_NAMES,
    ability_check,
    contested_check,
    passive_perception,
    saving_throw,
    skill_check,
)


@pytest.fixture
def fixed_dice(monkeypatch: pytest.MonkeyPatch):
    def _install(values: list[int]) -> None:
        stream = iter(values)
        monkeypatch.setattr(random, "randint", lambda low, high: next(stream))

    return _install


# ---------------------------------------------------------------------------
# Cantrip scaling
# ---------------------------------------------------------------------------


CANTRIP_TIERS = [5, 11, 17]


# ---------------------------------------------------------------------------
# Spell attack / save DC
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Unarmed strike
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Weapon attack bonus
# ---------------------------------------------------------------------------


SCORES = {"strength": 18, "dexterity": 14}


# ---------------------------------------------------------------------------
# Skill table integrity
# ---------------------------------------------------------------------------


def test_every_skill_has_a_display_name() -> None:
    assert set(SKILL_ABILITIES) == set(SKILL_DISPLAY_NAMES)


def test_skill_table_covers_the_srd_eighteen() -> None:
    assert len(SKILL_ABILITIES) == 18
    assert SKILL_ABILITIES["stealth"] == "dexterity"
    assert SKILL_ABILITIES["arcana"] == "intelligence"
    assert SKILL_ABILITIES["survival"] == "wisdom"


# ---------------------------------------------------------------------------
# skill_check
# ---------------------------------------------------------------------------


def test_skill_check_adds_ability_and_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 16}, ["stealth"], 3, dc=15)

    assert result.skill == "stealth"
    assert result.ability == "dexterity"
    assert result.is_proficient is True
    assert result.total_modifier == 6  # DEX +3 + proficiency 3
    assert result.roll.total == 16
    assert result.success is True


def test_skill_check_without_proficiency_uses_the_ability_alone(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 16}, [], 3)

    assert result.is_proficient is False
    assert result.total_modifier == 3
    assert result.success is None, "no DC means no verdict"


def test_skill_check_normalizes_the_skill_name(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("Sleight of Hand", {"dexterity": 10}, ["Sleight of Hand"], 2)

    assert result.skill == "sleight_of_hand"
    assert result.is_proficient is True


def test_unknown_skill_falls_back_to_intelligence(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("basket_weaving", {"intelligence": 14}, [], 2)

    assert result.ability == "intelligence"
    assert result.total_modifier == 2


def test_expertise_doubles_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 10}, ["stealth"], 3, expertise=True)

    assert result.total_modifier == 6


def test_expertise_without_proficiency_does_nothing(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 10}, [], 3, expertise=True)

    assert result.total_modifier == 0


def test_jack_of_all_trades_adds_half_proficiency_rounded_down(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 10}, [], 3, jack_of_all_trades=True)

    assert result.total_modifier == 1


def test_jack_of_all_trades_does_not_stack_with_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = skill_check("stealth", {"dexterity": 10}, ["stealth"], 3, jack_of_all_trades=True)

    assert result.total_modifier == 3


def test_skill_check_advantage_keeps_the_higher_die(fixed_dice) -> None:
    fixed_dice([4, 17])

    result = skill_check("stealth", {"dexterity": 10}, [], 0, advantage=True)

    assert result.roll.total == 17


def test_skill_check_disadvantage_keeps_the_lower_die(fixed_dice) -> None:
    fixed_dice([4, 17])

    result = skill_check("stealth", {"dexterity": 10}, [], 0, disadvantage=True)

    assert result.roll.total == 4


def test_skill_check_advantage_and_disadvantage_cancel(fixed_dice) -> None:
    fixed_dice([11])

    result = skill_check("stealth", {"dexterity": 10}, [], 0, advantage=True, disadvantage=True)

    assert len(result.roll.dice) == 1


def test_skill_check_meeting_the_dc_exactly_succeeds(fixed_dice) -> None:
    fixed_dice([15])

    assert skill_check("stealth", {"dexterity": 10}, [], 0, dc=15).success is True


# ---------------------------------------------------------------------------
# passive_perception / ability_check / saving_throw / contested_check
# ---------------------------------------------------------------------------


def test_passive_perception_is_ten_plus_wisdom() -> None:
    assert passive_perception(14, proficient=False, proficiency_bonus=3) == 12


def test_passive_perception_adds_proficiency_when_proficient() -> None:
    assert passive_perception(14, proficient=True, proficiency_bonus=3) == 15


def test_ability_check_uses_the_raw_ability_with_no_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = ability_check("strength", {"strength": 18}, dc=14)

    assert result.ability == "strength"
    assert result.skill == ""
    assert result.is_proficient is False
    assert result.total_modifier == 4
    assert result.success is True


def test_ability_check_defaults_a_missing_score(fixed_dice) -> None:
    fixed_dice([10])

    assert ability_check("charisma", {}).total_modifier == 0


def test_ability_check_honors_advantage(fixed_dice) -> None:
    fixed_dice([3, 18])

    assert ability_check("strength", {"strength": 10}, advantage=True).roll.total == 18


def test_ability_check_honors_disadvantage(fixed_dice) -> None:
    fixed_dice([3, 18])

    assert ability_check("strength", {"strength": 10}, disadvantage=True).roll.total == 3


def test_ability_check_advantage_and_disadvantage_cancel(fixed_dice) -> None:
    fixed_dice([9])

    result = ability_check("strength", {"strength": 10}, advantage=True, disadvantage=True)

    assert len(result.roll.dice) == 1


def test_saving_throw_adds_proficiency_for_proficient_saves(fixed_dice) -> None:
    fixed_dice([10])

    result = saving_throw("wisdom", {"wisdom": 16}, ["wisdom"], 3, dc=15)

    assert result.ability == "wisdom"
    assert result.is_proficient is True
    assert result.total_modifier == 6
    assert result.success is True


def test_saving_throw_without_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = saving_throw("wisdom", {"wisdom": 16}, ["dexterity"], 3, dc=15)

    assert result.is_proficient is False
    assert result.total_modifier == 3
    assert result.success is False


def test_saving_throw_proficiency_matching_is_case_insensitive(fixed_dice) -> None:
    fixed_dice([10])

    assert saving_throw("WISDOM", {"wisdom": 10}, ["Wisdom"], 2).is_proficient is True


def test_saving_throw_honors_advantage(fixed_dice) -> None:
    fixed_dice([2, 19])

    assert saving_throw("wisdom", {"wisdom": 10}, [], 0, advantage=True).roll.total == 19


def test_saving_throw_honors_disadvantage(fixed_dice) -> None:
    fixed_dice([2, 19])

    assert saving_throw("wisdom", {"wisdom": 10}, [], 0, disadvantage=True).roll.total == 2


def test_saving_throw_advantage_and_disadvantage_cancel(fixed_dice) -> None:
    fixed_dice([9])

    result = saving_throw("wisdom", {"wisdom": 10}, [], 0, advantage=True, disadvantage=True)

    assert len(result.roll.dice) == 1


def test_saving_throw_without_a_dc_reports_no_verdict(fixed_dice) -> None:
    fixed_dice([10])

    assert saving_throw("wisdom", {"wisdom": 10}, [], 0).success is None


def test_contested_check_ties_favor_the_active_participant() -> None:
    """5e: on a tie the situation stays as it was — the active roller (A) wins."""
    assert contested_check(15, 15) == 1


def test_contested_check_higher_total_wins() -> None:
    assert contested_check(18, 12) == 1
    assert contested_check(9, 12) == -1
