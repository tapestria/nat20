"""Behavioral tests for ``dnd5e_engine.rules.combat``.

This is the module every swing goes through, so the tests pin the SRD rules
themselves:

- Critical hits and fumbles key off the *die that is actually used*. Under
  disadvantage that is the lower die — a 20 on the discarded die must not
  crit, and a 1 on the discarded die must not fumble.
- Advantage and disadvantage cancel to a flat roll rather than stacking.
- Paralyzed/Stunned auto-fail STR and DEX saves outright; other saves are
  merely at disadvantage.
- Resistance halves, immunity zeroes, and damage never drops HP below 0 or
  heals above max.
- ``resolve_player_attack`` routes through three distinct paths (auto-hit,
  save-based, attack roll) and applies each effect bucket at exactly one
  site: attacker effects move the attack roll and damage, target effects
  move AC and the target's save.

Dice come from the module-global RNG, so tests that need a specific die
patch ``random.randint`` directly; the rest force the outcome with extreme
bonuses and assert the invariant.
"""

from __future__ import annotations

import random
from collections.abc import Iterator

import pytest

from dnd5e_engine.rules.combat import (
    AttackResult,
    HitType,
    apply_damage,
    apply_healing,
    attack_roll,
    damage_roll,
    death_saving_throw,
    initiative_roll,
    opportunity_attack_eligible,
    resolve_player_attack,
    saving_throw,
)
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange


def _effect(*changes: ActiveEffectChange, effect_id: str = "effect:test") -> ActiveEffect:
    return ActiveEffect(
        id=effect_id,
        name=effect_id,
        origin=f"cast:{effect_id}:1",
        target_id="char:abc123def456",
        changes=list(changes),
    )


def _flag(key: str) -> ActiveEffectChange:
    return ActiveEffectChange(key=key, mode="override", value=True)


def _bonus(key: str, value: object, priority: int = 20) -> ActiveEffectChange:
    return ActiveEffectChange(key=key, mode="add", value=value, priority=priority)


@pytest.fixture
def fixed_dice(monkeypatch: pytest.MonkeyPatch):
    """Feed a scripted sequence of die results to ``random.randint``."""

    def _install(values: list[int]) -> None:
        stream: Iterator[int] = iter(values)

        def _fake_randint(low: int, high: int) -> int:
            return next(stream)

        monkeypatch.setattr(random, "randint", _fake_randint)

    return _install


# ---------------------------------------------------------------------------
# attack_roll — hit classification
# ---------------------------------------------------------------------------


def test_attack_roll_reports_the_inputs_it_resolved_against() -> None:
    random.seed(31)
    result = attack_roll(5, 15)

    assert isinstance(result, AttackResult)
    assert result.target_ac == 15
    assert result.attacker_bonus == 5
    assert result.roll.total == result.roll.dice[0] + 5


def test_natural_twenty_always_crits_even_against_impossible_ac(fixed_dice) -> None:
    fixed_dice([20])

    assert attack_roll(0, 99).hit_type is HitType.CRITICAL_HIT


def test_natural_one_always_misses_even_with_a_huge_bonus(fixed_dice) -> None:
    fixed_dice([1])

    assert attack_roll(50, 5).hit_type is HitType.MISS


def test_meeting_the_ac_exactly_is_a_hit(fixed_dice) -> None:
    fixed_dice([10])

    assert attack_roll(5, 15).hit_type is HitType.HIT


def test_falling_one_short_of_the_ac_is_a_miss(fixed_dice) -> None:
    fixed_dice([10])

    assert attack_roll(5, 16).hit_type is HitType.MISS


# ---------------------------------------------------------------------------
# attack_roll — advantage / disadvantage
# ---------------------------------------------------------------------------


def test_advantage_rolls_two_dice_and_keeps_the_higher(fixed_dice) -> None:
    fixed_dice([7, 18])

    result = attack_roll(2, 15, advantage=True)

    assert len(result.roll.dice) == 2
    assert result.roll.total == 20  # 18 + 2
    assert result.hit_type is HitType.HIT


def test_disadvantage_rolls_two_dice_and_keeps_the_lower(fixed_dice) -> None:
    fixed_dice([7, 18])

    result = attack_roll(2, 15, disadvantage=True)

    assert result.roll.total == 9  # 7 + 2
    assert result.hit_type is HitType.MISS


def test_disadvantage_does_not_crit_on_the_discarded_die(fixed_dice) -> None:
    """SRD: with disadvantage you use the lower roll. A 20 on the die you
    discard is not a critical hit."""
    fixed_dice([3, 20])

    result = attack_roll(2, 10, disadvantage=True)

    assert result.roll.total == 5  # the 3 is the die in play
    assert result.hit_type is HitType.MISS


def test_advantage_does_not_fumble_on_the_discarded_die(fixed_dice) -> None:
    """The mirror case: a 1 on the discarded die must not force a miss."""
    fixed_dice([1, 19])

    result = attack_roll(2, 10, advantage=True)

    assert result.roll.total == 21
    assert result.hit_type is HitType.HIT


def test_advantage_and_disadvantage_cancel_to_a_flat_roll(fixed_dice) -> None:
    fixed_dice([11])

    result = attack_roll(0, 10, advantage=True, disadvantage=True)

    assert len(result.roll.dice) == 1
    assert result.hit_type is HitType.HIT


# ---------------------------------------------------------------------------
# attack_roll — condition-derived advantage
# ---------------------------------------------------------------------------


def test_invisible_attacker_gains_advantage(fixed_dice) -> None:
    fixed_dice([2, 19])

    result = attack_roll(0, 15, attacker_conditions=["invisible"])

    assert len(result.roll.dice) == 2
    assert result.hit_type is HitType.HIT


@pytest.mark.parametrize("condition", ["blinded", "restrained", "poisoned"])
def test_attacker_conditions_impose_disadvantage(condition: str, fixed_dice) -> None:
    fixed_dice([2, 19])

    result = attack_roll(0, 15, attacker_conditions=[condition])

    assert len(result.roll.dice) == 2
    assert result.roll.total == 2  # the low die is kept
    assert result.hit_type is HitType.MISS


def test_paralyzed_target_grants_the_attacker_advantage(fixed_dice) -> None:
    fixed_dice([2, 19])

    result = attack_roll(0, 15, target_conditions=["paralyzed"])

    assert result.hit_type is HitType.HIT


def test_condition_advantage_and_disadvantage_cancel(fixed_dice) -> None:
    """An invisible but poisoned attacker rolls flat."""
    fixed_dice([12])

    result = attack_roll(0, 10, attacker_conditions=["invisible", "poisoned"])

    assert len(result.roll.dice) == 1


def test_prone_target_alone_does_not_change_the_roll(fixed_dice) -> None:
    """Melee gets advantage and ranged disadvantage against a prone target;
    the module leaves that distinction to the caller's explicit flags."""
    fixed_dice([12])

    result = attack_roll(0, 10, target_conditions=["prone"])

    assert len(result.roll.dice) == 1


# ---------------------------------------------------------------------------
# damage_roll
# ---------------------------------------------------------------------------


def test_damage_roll_sums_dice_plus_modifier(fixed_dice) -> None:
    fixed_dice([3, 4])

    result = damage_roll(2, 6, 3, "slashing")

    assert result.dice_rolls == [3, 4]
    assert result.modifier == 3
    assert result.total == 10
    assert result.damage_type == "slashing"
    assert result.is_critical is False


def test_critical_hit_doubles_the_dice_but_not_the_modifier(fixed_dice) -> None:
    """SRD: roll the damage dice twice; the flat modifier is added once."""
    fixed_dice([3, 4, 5, 6])

    result = damage_roll(2, 6, 3, "slashing", is_critical=True)

    assert len(result.dice_rolls) == 4
    assert result.total == 3 + 4 + 5 + 6 + 3
    assert result.is_critical is True


def test_damage_is_never_negative(fixed_dice) -> None:
    """A large penalty must clamp to 0 rather than healing the target."""
    fixed_dice([1])

    result = damage_roll(1, 4, -10, "necrotic")

    assert result.total == 0


# ---------------------------------------------------------------------------
# saving_throw
# ---------------------------------------------------------------------------


def test_saving_throw_adds_ability_modifier_and_proficiency(fixed_dice) -> None:
    fixed_dice([10])

    result = saving_throw(
        ability_score=16, is_proficient=True, proficiency_bonus=3, dc=15, active_effects=[]
    )

    assert result.roll.total == 16  # 10 + 3 (STR mod) + 3 (proficiency)
    assert result.success is True
    assert result.dc == 15


def test_saving_throw_omits_proficiency_when_not_proficient(fixed_dice) -> None:
    fixed_dice([10])

    result = saving_throw(
        ability_score=16, is_proficient=False, proficiency_bonus=3, dc=15, active_effects=[]
    )

    assert result.roll.total == 13
    assert result.success is False


@pytest.mark.parametrize("condition", ["paralyzed", "stunned"])
@pytest.mark.parametrize("ability", ["strength", "dexterity"])
def test_paralyzed_or_stunned_auto_fails_str_and_dex_saves(
    condition: str, ability: str, fixed_dice
) -> None:
    """SRD: the save fails automatically — even a natural 20 does not save."""
    fixed_dice([20])

    result = saving_throw(
        ability_score=20,
        is_proficient=True,
        proficiency_bonus=6,
        dc=5,
        conditions=[condition],
        ability=ability,
        active_effects=[],
    )

    assert result.success is False
    assert result.ability == ability


@pytest.mark.parametrize("condition", ["paralyzed", "stunned"])
def test_paralyzed_or_stunned_only_imposes_disadvantage_on_other_saves(
    condition: str, fixed_dice
) -> None:
    fixed_dice([18, 3])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=10,
        conditions=[condition],
        ability="wisdom",
        active_effects=[],
    )

    assert len(result.roll.dice) == 2
    assert result.roll.total == 3  # lower die kept
    assert result.success is False


def test_unconscious_implies_incapacitated_but_not_an_auto_failed_save(fixed_dice) -> None:
    """Only Paralyzed/Stunned are wired to auto-fail here; an unconscious
    creature still rolls (its auto-fail is projected via the sidecar)."""
    fixed_dice([15])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=10,
        conditions=["unconscious"],
        ability="dexterity",
        active_effects=[],
    )

    assert result.success is True


def test_effect_flag_grants_advantage_on_every_save(fixed_dice) -> None:
    fixed_dice([4, 17])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="wisdom",
        active_effects=[_effect(_flag("flags.advantage.save"))],
    )

    assert result.roll.total == 17
    assert result.success is True


def test_effect_flag_grants_disadvantage_on_every_save(fixed_dice) -> None:
    fixed_dice([4, 17])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=10,
        ability="wisdom",
        active_effects=[_effect(_flag("flags.disadvantage.save"))],
    )

    assert result.roll.total == 4
    assert result.success is False


def test_per_ability_save_flag_only_applies_to_that_ability(fixed_dice) -> None:
    fixed_dice([4, 17])

    matching = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="wisdom",
        active_effects=[_effect(_flag("flags.advantage.save.wisdom"))],
    )

    assert matching.roll.total == 17

    fixed_dice([4])
    non_matching = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="charisma",
        active_effects=[_effect(_flag("flags.advantage.save.wisdom"))],
    )

    assert len(non_matching.roll.dice) == 1


def test_generic_save_bonus_bucket_is_folded_in(fixed_dice) -> None:
    """A Cloak of Protection (+1 to all saves) lifts the total past the DC."""
    fixed_dice([9])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=10,
        ability="wisdom",
        active_effects=[_effect(_bonus("save.bonus", 1))],
    )

    assert result.success is True


def test_per_ability_save_bonus_bucket_is_folded_in(fixed_dice) -> None:
    fixed_dice([9])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=12,
        ability="wisdom",
        active_effects=[_effect(_bonus("save.wisdom.bonus", 3))],
    )

    assert result.success is True


def test_save_bonus_for_another_ability_is_not_applied(fixed_dice) -> None:
    fixed_dice([9])

    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=12,
        ability="charisma",
        active_effects=[_effect(_bonus("save.wisdom.bonus", 3))],
    )

    assert result.success is False


# ---------------------------------------------------------------------------
# apply_damage / apply_healing
# ---------------------------------------------------------------------------


def test_apply_damage_subtracts_and_reports_survival() -> None:
    assert apply_damage(20, 20, 5) == (15, False)


def test_apply_damage_floors_at_zero_and_reports_death() -> None:
    """Overkill does not produce negative HP."""
    assert apply_damage(5, 20, 500) == (0, True)


def test_exact_lethal_damage_reports_death() -> None:
    assert apply_damage(5, 20, 5) == (0, True)


def test_resistance_halves_damage_rounding_down() -> None:
    assert apply_damage(20, 20, 7, resistances=["fire"], damage_type="fire") == (17, False)


def test_immunity_zeroes_damage() -> None:
    assert apply_damage(20, 20, 50, immunities=["poison"], damage_type="poison") == (20, False)


def test_immunity_takes_priority_over_resistance() -> None:
    new_hp, _ = apply_damage(
        20, 20, 50, resistances=["fire"], immunities=["fire"], damage_type="fire"
    )

    assert new_hp == 20


def test_resistance_to_another_damage_type_does_not_apply() -> None:
    assert apply_damage(20, 20, 8, resistances=["cold"], damage_type="fire") == (12, False)


def test_apply_healing_caps_at_max_hp() -> None:
    assert apply_healing(18, 20, 10) == 20


def test_apply_healing_adds_below_the_cap() -> None:
    assert apply_healing(5, 20, 7) == 12


# ---------------------------------------------------------------------------
# death_saving_throw
# ---------------------------------------------------------------------------


def test_death_save_natural_twenty_is_a_critical_success(fixed_dice) -> None:
    fixed_dice([20])

    assert death_saving_throw() == (True, True)


def test_death_save_natural_one_is_a_critical_failure(fixed_dice) -> None:
    fixed_dice([1])

    assert death_saving_throw() == (False, True)


def test_death_save_ten_succeeds(fixed_dice) -> None:
    """SRD: 10 or higher succeeds."""
    fixed_dice([10])

    assert death_saving_throw() == (True, False)


def test_death_save_nine_fails(fixed_dice) -> None:
    fixed_dice([9])

    assert death_saving_throw() == (False, False)


# ---------------------------------------------------------------------------
# initiative / opportunity attacks
# ---------------------------------------------------------------------------


def test_initiative_adds_the_dex_modifier(fixed_dice) -> None:
    fixed_dice([11])

    assert initiative_roll(18).total == 15  # 11 + 4


@pytest.mark.parametrize(
    "movement,left_zone,can_see,expected",
    [
        (True, True, True, True),
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
    ],
)
def test_opportunity_attack_requires_all_three_conditions(
    movement: bool, left_zone: bool, can_see: bool, expected: bool
) -> None:
    assert opportunity_attack_eligible(movement, left_zone, can_see) is expected


# ---------------------------------------------------------------------------
# resolve_player_attack — path 1: auto-hit
# ---------------------------------------------------------------------------


def _attack(**kwargs):
    defaults = dict(
        action_type="attack",
        attack_bonus=5,
        target_ac=15,
        damage_dice="2d6+0",
        damage_type="slashing",
        damage_modifier=3,
        target_name="Goblin",
        target_hp_current=20,
        target_hp_max=20,
        active_effects=[],
        target_active_effects=[],
    )
    defaults.update(kwargs)
    return resolve_player_attack(**defaults)


def test_auto_hit_spell_skips_the_attack_roll(fixed_dice) -> None:
    """Magic Missile always hits: no d20 is consumed and no AC is compared."""
    fixed_dice([3, 4])

    outcome = _attack(is_auto_hit=True)

    assert outcome.hit is True
    assert outcome.attack_roll == 0
    assert outcome.is_critical is False
    assert outcome.damage_dealt == 10  # 3 + 4 + 3
    assert outcome.target_hp_remaining == 10
    assert outcome.raw_damage_dice == [3, 4]


def test_auto_hit_damage_is_reduced_by_target_resistance(fixed_dice) -> None:
    fixed_dice([3, 4])

    outcome = _attack(is_auto_hit=True, damage_type="fire", target_resistances=["fire"])

    assert outcome.damage_dealt == 5  # 10 halved


def test_auto_hit_reports_a_kill(fixed_dice) -> None:
    fixed_dice([6, 6])

    outcome = _attack(is_auto_hit=True, target_hp_current=5)

    assert outcome.target_died is True
    assert outcome.target_hp_remaining == 0
    assert outcome.damage_dealt == 5, "damage_dealt is capped at the HP actually removed"


def test_attacker_damage_bonus_applies_on_the_auto_hit_path(fixed_dice) -> None:
    fixed_dice([3, 4])

    outcome = _attack(is_auto_hit=True, active_effects=[_effect(_bonus("damage.bonus", 5))])

    assert outcome.damage_dealt == 15


def test_damage_penalty_cannot_heal_the_target(fixed_dice) -> None:
    fixed_dice([1, 1])

    outcome = _attack(
        is_auto_hit=True,
        damage_modifier=0,
        active_effects=[_effect(_bonus("damage.bonus", -50))],
    )

    assert outcome.damage_dealt == 0
    assert outcome.target_hp_remaining == 20


# ---------------------------------------------------------------------------
# resolve_player_attack — path 2: save-based
# ---------------------------------------------------------------------------


def test_failed_save_takes_full_damage(fixed_dice) -> None:
    # save d20 = 1, then 2d6 damage
    fixed_dice([1, 5, 5])

    outcome = _attack(save_type="dexterity", save_dc=15, target_save_score=10, damage_modifier=0)

    assert outcome.hit is True
    assert outcome.raw_save_success is False
    assert outcome.raw_save_dc == 15
    assert outcome.damage_dealt == 10


def test_successful_save_negates_damage_without_half_on_save(fixed_dice) -> None:
    fixed_dice([20, 5, 5])

    outcome = _attack(save_type="dexterity", save_dc=15, target_save_score=10, damage_modifier=0)

    assert outcome.raw_save_success is True
    assert outcome.damage_dealt == 0
    assert outcome.target_hp_remaining == 20


def test_successful_save_halves_damage_when_half_on_save(fixed_dice) -> None:
    """Fireball: a successful DEX save still takes half damage."""
    fixed_dice([20, 5, 6])

    outcome = _attack(
        save_type="dexterity",
        save_dc=15,
        target_save_score=10,
        half_on_save=True,
        damage_modifier=0,
    )

    assert outcome.raw_save_success is True
    assert outcome.damage_dealt == 5  # 11 // 2


def test_save_path_never_crits_and_reports_no_attack_roll(fixed_dice) -> None:
    fixed_dice([20, 5, 5])

    outcome = _attack(save_type="dexterity", save_dc=15, damage_modifier=0)

    assert outcome.attack_roll == 0
    assert outcome.is_critical is False


def test_target_effects_boost_the_targets_save_not_the_attackers(fixed_dice) -> None:
    """Bless on the defender adds to their save; the same effect passed as an
    attacker effect must not."""
    fixed_dice([12, 5, 5])
    with_defence = _attack(
        save_type="dexterity",
        save_dc=15,
        target_save_score=10,
        damage_modifier=0,
        target_active_effects=[_effect(_bonus("save.bonus", 3))],
    )

    assert with_defence.raw_save_success is True

    fixed_dice([12, 5, 5])
    attacker_side = _attack(
        save_type="dexterity",
        save_dc=15,
        target_save_score=10,
        damage_modifier=0,
        active_effects=[_effect(_bonus("save.bonus", 3))],
    )

    assert attacker_side.raw_save_success is False


# ---------------------------------------------------------------------------
# resolve_player_attack — path 3: attack roll
# ---------------------------------------------------------------------------


def test_attack_path_hits_and_deals_damage(fixed_dice) -> None:
    fixed_dice([15, 3, 4])

    outcome = _attack(target_ac=15)

    assert outcome.hit is True
    assert outcome.is_critical is False
    assert outcome.attack_roll == 20  # 15 + 5
    assert outcome.damage_dealt == 10  # 3 + 4 + 3
    assert outcome.target_name == "Goblin"


def test_attack_path_miss_deals_no_damage(fixed_dice) -> None:
    fixed_dice([2])

    outcome = _attack(target_ac=25)

    assert outcome.hit is False
    assert outcome.damage_dealt == 0
    assert outcome.target_hp_remaining == 20


def test_attack_path_natural_twenty_crits_and_doubles_dice(fixed_dice) -> None:
    fixed_dice([20, 3, 4, 5, 6])

    outcome = _attack(target_ac=15, target_hp_current=50, target_hp_max=50)

    assert outcome.is_critical is True
    assert outcome.raw_damage_dice == [3, 4, 5, 6]
    assert outcome.damage_dealt == 3 + 4 + 5 + 6 + 3


def test_attacker_attack_bonus_effect_can_turn_a_miss_into_a_hit(fixed_dice) -> None:
    fixed_dice([9, 3, 4])

    outcome = _attack(target_ac=17, active_effects=[_effect(_bonus("attack.roll.bonus", 3))])

    # 9 + 5 = 14 vs AC 17 misses; +3 from the effect reaches 17.
    assert outcome.hit is True


def test_target_ac_effect_can_turn_a_hit_into_a_miss(fixed_dice) -> None:
    """Shield of Faith on the defender raises AC before the comparison."""
    fixed_dice([11])

    outcome = _attack(target_ac=15, target_active_effects=[_effect(_bonus("ac.bonus", 3))])

    # 11 + 5 = 16 clears AC 15 but not the effective AC 18.
    assert outcome.hit is False


def test_attacker_flag_grants_advantage_on_the_attack_roll(fixed_dice) -> None:
    fixed_dice([2, 19, 3, 4])

    outcome = _attack(target_ac=20, active_effects=[_effect(_flag("flags.advantage.attack"))])

    assert outcome.hit is True


def test_attacker_flag_imposes_disadvantage_on_the_attack_roll(fixed_dice) -> None:
    fixed_dice([2, 19])

    outcome = _attack(target_ac=15, active_effects=[_effect(_flag("flags.disadvantage.attack"))])

    assert outcome.hit is False


def test_faerie_fire_on_the_target_grants_the_attacker_advantage(fixed_dice) -> None:
    """The target-side advantage flag is lifted to attacker-side advantage."""
    fixed_dice([2, 19, 3, 4])

    outcome = _attack(
        target_ac=20, target_active_effects=[_effect(_flag("flags.advantage.attack"))]
    )

    assert outcome.hit is True


def test_attack_path_reports_the_kill_and_clamps_damage_to_remaining_hp(fixed_dice) -> None:
    fixed_dice([18, 6, 6])

    outcome = _attack(target_ac=10, target_hp_current=4)

    assert outcome.target_died is True
    assert outcome.target_hp_remaining == 0
    assert outcome.damage_dealt == 4
