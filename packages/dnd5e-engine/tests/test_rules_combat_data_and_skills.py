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

from dnd5e_engine.rules.combat_data import (
    CLASS_SPELLCASTING_ABILITY,
    UNARMED_STRIKE_DAMAGE_TYPE,
    calculate_cantrip_dice,
    is_weapon_proficient,
    spell_attack_bonus,
    spell_save_dc,
    unarmed_strike_damage,
    weapon_attack_bonus,
)
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


@pytest.mark.parametrize(
    "level,expected",
    [(1, "1d10"), (4, "1d10"), (5, "2d10"), (10, "2d10"), (11, "3d10"), (17, "4d10"), (20, "4d10")],
)
def test_cantrip_scales_at_each_tier(level: int, expected: str) -> None:
    """Fire Bolt: 1d10, +1d10 at 5th, 11th and 17th."""
    assert calculate_cantrip_dice("1d10", "1d10", CANTRIP_TIERS, level) == expected


def test_cantrip_scaling_keeps_the_base_die_size() -> None:
    """The scaling expression contributes a die *count*; the size comes from
    the base expression."""
    assert calculate_cantrip_dice("1d8", "1d6", CANTRIP_TIERS, 11) == "3d8"


def test_cantrip_scaling_can_add_more_than_one_die_per_tier() -> None:
    assert calculate_cantrip_dice("2d6", "2d6", CANTRIP_TIERS, 5) == "4d6"


def test_cantrip_without_scaling_dice_is_unchanged() -> None:
    assert calculate_cantrip_dice("1d10", None, CANTRIP_TIERS, 20) == "1d10"


def test_cantrip_without_scaling_levels_is_unchanged() -> None:
    assert calculate_cantrip_dice("1d10", "1d10", None, 20) == "1d10"


def test_cantrip_with_empty_scaling_levels_never_scales() -> None:
    assert calculate_cantrip_dice("1d10", "1d10", [], 20) == "1d10"


def test_cantrip_drops_the_base_flat_modifier() -> None:
    """The returned expression is pure dice; a flat modifier on the base is
    the caller's to re-apply."""
    assert calculate_cantrip_dice("1d10+3", "1d10", CANTRIP_TIERS, 5) == "2d10"


# ---------------------------------------------------------------------------
# Spell attack / save DC
# ---------------------------------------------------------------------------


def test_every_caster_class_has_a_spellcasting_ability() -> None:
    assert CLASS_SPELLCASTING_ABILITY["wizard"] == "intelligence"
    assert CLASS_SPELLCASTING_ABILITY["cleric"] == "wisdom"
    assert CLASS_SPELLCASTING_ABILITY["sorcerer"] == "charisma"


def test_spell_attack_bonus_uses_the_class_spellcasting_ability() -> None:
    scores = {"intelligence": 18, "charisma": 8}

    assert spell_attack_bonus("wizard", scores, 3) == 7  # INT +4 + prof 3
    assert spell_attack_bonus("sorcerer", scores, 3) == 2  # CHA -1 + prof 3


def test_spell_attack_bonus_is_case_insensitive() -> None:
    assert spell_attack_bonus("WIZARD", {"intelligence": 16}, 2) == 5


def test_spell_attack_bonus_is_none_for_non_casters() -> None:
    """None (not 0) so callers can tell 'cannot cast' from 'a +0 bonus'."""
    assert spell_attack_bonus("fighter", {"intelligence": 20}, 6) is None


def test_spell_attack_bonus_defaults_a_missing_ability_score() -> None:
    assert spell_attack_bonus("wizard", {}, 2) == 2


def test_spell_save_dc_is_eight_plus_proficiency_plus_ability() -> None:
    assert spell_save_dc("wizard", {"intelligence": 18}, 3) == 15


def test_spell_save_dc_is_none_for_non_casters() -> None:
    assert spell_save_dc("barbarian", {"strength": 20}, 6) is None


def test_spell_save_dc_and_attack_bonus_stay_in_lockstep() -> None:
    """DC is always the attack bonus + 8 for the same caster."""
    scores = {"wisdom": 17}

    assert spell_save_dc("cleric", scores, 4) == spell_attack_bonus("cleric", scores, 4) + 8


# ---------------------------------------------------------------------------
# Unarmed strike
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strength,expected",
    [(20, 6), (14, 3), (10, 1), (8, 1), (1, 1)],  # never below 1
)
def test_unarmed_strike_damage(strength: int, expected: int) -> None:
    assert unarmed_strike_damage(strength) == expected


def test_unarmed_strike_damage_type() -> None:
    assert UNARMED_STRIKE_DAMAGE_TYPE == "bludgeoning"


# ---------------------------------------------------------------------------
# Weapon attack bonus
# ---------------------------------------------------------------------------


SCORES = {"strength": 18, "dexterity": 14}


def test_melee_weapon_uses_strength() -> None:
    assert weapon_attack_bonus(SCORES, 3, True, "Melee", False) == 7


def test_ranged_weapon_uses_dexterity() -> None:
    assert weapon_attack_bonus(SCORES, 3, True, "Ranged", False) == 5


def test_finesse_melee_takes_the_better_ability() -> None:
    dex_heavy = {"strength": 8, "dexterity": 18}

    assert weapon_attack_bonus(dex_heavy, 2, True, "Melee", True) == 6  # DEX +4 wins
    assert weapon_attack_bonus(SCORES, 2, True, "Melee", True) == 6  # STR +4 wins


def test_finesse_does_not_apply_to_ranged_weapons() -> None:
    """A finesse flag on a ranged weapon must not resurrect a higher STR."""
    str_heavy = {"strength": 20, "dexterity": 10}

    assert weapon_attack_bonus(str_heavy, 2, True, "Ranged", True) == 2  # DEX +0 + prof


def test_non_proficient_weapon_omits_the_proficiency_bonus() -> None:
    assert weapon_attack_bonus(SCORES, 3, False, "Melee", False) == 4


def test_weapon_range_matching_is_case_insensitive() -> None:
    assert weapon_attack_bonus(SCORES, 0, False, "RANGED", False) == 2


def test_weapon_attack_bonus_defaults_missing_scores() -> None:
    assert weapon_attack_bonus({}, 2, True, "Melee", False) == 2


@pytest.mark.parametrize(
    "category,profs,expected",
    [
        ("Simple Melee", ["simple"], True),
        ("Martial Ranged", ["martial"], True),
        ("Martial Melee", ["simple"], False),
        ("simple melee", ["Simple"], True),
        ("Simple Melee", [], False),
        ("Simple Melee", ["martial", "simple"], True),
    ],
)
def test_is_weapon_proficient(category: str, profs: list[str], expected: bool) -> None:
    assert is_weapon_proficient(category, profs) is expected


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
