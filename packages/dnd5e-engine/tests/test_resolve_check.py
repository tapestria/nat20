"""Phase 5 — resolve_check workstream tests.

Phase 6 migration: ``EffectModifier`` → ``ActiveEffectChange`` with
``key``/``mode``/``value``/``priority``; ``ActiveEffect`` is Foundry-aligned
(``id``/``name``/``origin``/``target_id`` + ``changes`` + ``duration``).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import dnd5e_engine.rules.dice as dice_mod
from dnd5e_engine.check import CheckKind, CheckSpec


def test_check_spec_is_frozen():
    spec = CheckSpec(
        kind="skill",
        skill="perception",
        ability_scores={"wisdom": 14},
        proficient_skills=("perception",),
        proficient_saves=(),
        proficiency_bonus=2,
        dc=15,
    )
    with pytest.raises(FrozenInstanceError):
        spec.dc = 10  # type: ignore[misc]


def test_check_spec_defaults():
    spec = CheckSpec(
        kind="ability",
        ability="strength",
        ability_scores={"strength": 16},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=2,
    )
    assert spec.skill is None
    assert spec.dc is None
    assert spec.active_effects == ()


def test_check_kind_literal_values():
    # Ensure CheckKind covers exactly the three supported kinds.
    valid: list[CheckKind] = ["skill", "ability", "saving_throw"]
    for k in valid:
        # Round-trips through the spec constructor without error
        CheckSpec(
            kind=k,
            skill="perception" if k == "skill" else None,
            ability="wisdom",
            ability_scores={"wisdom": 12},
            proficient_skills=(),
            proficient_saves=(),
            proficiency_bonus=2,
        )


def test_resolve_check_skill_no_effects(monkeypatch):
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 12)

    from dnd5e_engine.check import resolve_check

    spec = CheckSpec(
        kind="skill",
        skill="perception",
        ability_scores={"wisdom": 14},
        proficient_skills=("perception",),
        proficient_saves=(),
        proficiency_bonus=3,
        dc=15,
    )
    result = resolve_check(spec)
    assert result.kind == "skill"
    assert result.skill == "perception"
    assert result.ability == "wisdom"
    # roll 12 + wis mod +2 + prof +3 = 17
    assert result.roll_total == 17
    assert result.success is True
    assert result.is_proficient is True
    assert result.effect_breakdown == ()


def test_resolve_check_ability_no_effects(monkeypatch):
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 8)

    from dnd5e_engine.check import resolve_check

    spec = CheckSpec(
        kind="ability",
        ability="strength",
        ability_scores={"strength": 18},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=2,
        dc=10,
    )
    result = resolve_check(spec)
    assert result.kind == "ability"
    assert result.skill == ""
    assert result.ability == "strength"
    # 8 + str mod +4 = 12
    assert result.roll_total == 12
    assert result.success is True


def test_resolve_check_saving_throw_no_effects(monkeypatch):
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 6)

    from dnd5e_engine.check import resolve_check

    spec = CheckSpec(
        kind="saving_throw",
        ability="constitution",
        ability_scores={"constitution": 14},
        proficient_skills=(),
        proficient_saves=("constitution",),
        proficiency_bonus=2,
        dc=12,
    )
    result = resolve_check(spec)
    assert result.kind == "saving_throw"
    assert result.ability == "constitution"
    # 6 + con +2 + prof +2 = 10
    assert result.roll_total == 10
    assert result.success is False
    assert result.is_proficient is True


def test_resolve_check_skill_with_bless(monkeypatch):
    """Bless: +1d4 on check bucket → folded into roll_total."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    import dnd5e_engine.rules.effects as eff_mod

    monkeypatch.setattr(eff_mod, "_roll_dice_str", lambda s: 3)

    from dnd5e_engine.check import resolve_check
    from dnd5e_engine.types.effects import (
        ActiveEffect,
        ActiveEffectChange,
        ActiveEffectDuration,
    )

    bless = ActiveEffect(
        id="fx:bless00000001",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(
                key="check.bonus", mode="add", value="1d4", priority=20
            ),
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="persuasion",
        ability_scores={"charisma": 16},
        proficient_skills=("persuasion",),
        proficient_saves=(),
        proficiency_bonus=3,
        dc=18,
        active_effects=(bless,),
    )
    result = resolve_check(spec)
    # base: 10 + cha +3 + prof +3 = 16; + bless +3 = 19
    assert result.roll_total == 19
    assert result.success is True
    assert any("1d4:3" in b for b in result.effect_breakdown)


def test_resolve_check_saving_throw_with_cloak_of_protection(monkeypatch):
    """Cloak of Protection: +1 flat on saving_throw bucket."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 8)

    from dnd5e_engine.check import resolve_check
    from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange

    cloak = ActiveEffect(
        id="fx:cloak0000001",
        name="Cloak of Protection",
        origin="item:cloak_of_protection:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="save.bonus", mode="add", value=1, priority=20
            ),
        ],
    )
    spec = CheckSpec(
        kind="saving_throw",
        ability="wisdom",
        ability_scores={"wisdom": 14},
        proficient_skills=(),
        proficient_saves=("wisdom",),
        proficiency_bonus=2,
        dc=12,
        active_effects=(cloak,),
    )
    result = resolve_check(spec)
    # 8 + wis +2 + prof +2 = 12; + cloak +1 = 13
    assert result.roll_total == 13
    assert result.success is True


def test_resolve_check_ignores_non_matching_change_key(monkeypatch):
    """A change on a non-matching key (attack.roll.bonus) is ignored on a skill check."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 12)

    from dnd5e_engine.check import resolve_check
    from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange

    sword_buff = ActiveEffect(
        id="fx:weaponplus001",
        name="+1 Weapon",
        origin="item:weapon_plus_one:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="attack.roll.bonus", mode="add", value=1, priority=20
            ),
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="athletics",
        ability_scores={"strength": 14},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=2,
        active_effects=(sword_buff,),
    )
    result = resolve_check(spec)
    # 12 + str +2 = 14, attack_roll change ignored (bucket mismatch)
    assert result.roll_total == 14
    assert result.effect_breakdown == ()


def test_resolve_check_skill_with_explicit_advantage(monkeypatch):
    """Caller-supplied advantage (e.g. hidden attacker) raises the d20."""
    # roll_with_advantage takes the higher of two d20s
    rolls = iter([4, 17])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    from dnd5e_engine.check import resolve_check

    spec = CheckSpec(
        kind="skill",
        skill="stealth",
        ability_scores={"dexterity": 14},
        proficient_skills=("stealth",),
        proficient_saves=(),
        proficiency_bonus=2,
        advantage=True,
    )
    result = resolve_check(spec)
    # 17 + dex +2 + prof +2 = 21
    assert result.roll_total == 21


def test_resolve_check_invariant_roll_total_equals_natural_plus_modifier(monkeypatch):
    """DiceOutcome contract: roll_total = natural_roll + modifier, with or without effects."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    import dnd5e_engine.rules.effects as eff_mod

    monkeypatch.setattr(eff_mod, "_roll_dice_str", lambda s: 3)

    from dnd5e_engine.check import resolve_check
    from dnd5e_engine.types.effects import (
        ActiveEffect,
        ActiveEffectChange,
        ActiveEffectDuration,
    )

    bless = ActiveEffect(
        id="fx:bless00000002",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(
                key="check.bonus", mode="add", value="1d4", priority=20
            ),
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="persuasion",
        ability_scores={"charisma": 16},
        proficient_skills=("persuasion",),
        proficient_saves=(),
        proficiency_bonus=3,
        active_effects=(bless,),
    )
    result = resolve_check(spec)
    assert result.roll_total == result.natural_roll + result.modifier, (
        f"invariant violated: roll_total={result.roll_total}, "
        f"natural_roll={result.natural_roll}, modifier={result.modifier}"
    )
