"""Regression — resolve_check folds specific bucket keys alongside the generic.

Codex Phase 6 review iter-4 P2: `apply_changes_to_check` is exact-match
on bucket key. The previous resolve_check only queried the generic
`check.bonus` / `save.bonus`, silently dropping any
ActiveEffectChange targeted at a more specific bucket like
`check.skill_check.bonus` or `save.wisdom.bonus`. This test locks the
fix that resolve_check now folds both the generic and the kind-specific
(and for saves, the per-ability) bucket keys.
"""

from __future__ import annotations

from dnd5e_engine.check import CheckSpec, resolve_check
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _effect(key: str, value=1) -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:test_{key}",
        name=f"test_{key}",
        origin=f"cast:test:{key}",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=10),
        changes=[ActiveEffectChange(key=key, mode="add", value=value)],
    )


def test_resolve_check_skill_picks_up_specific_bucket(monkeypatch):
    """A check.skill_check.bonus change lands on a skill check resolution."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("check.skill_check.bonus", value=5)

    spec = CheckSpec(
        kind="skill",
        ability_scores={"wisdom": 10},
        skill="perception",
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # 10 (roll) + 0 (modifier) + 0 (proficiency) + 5 (specific bucket) = 15
    assert result.roll_total == 15


def test_resolve_check_ability_picks_up_ability_specific_bucket(monkeypatch):
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("check.ability_check.bonus", value=3)
    spec = CheckSpec(
        kind="ability",
        ability="strength",
        ability_scores={"strength": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    assert result.roll_total == 13


def test_resolve_check_save_picks_up_per_ability_bucket(monkeypatch):
    """save.wisdom.bonus lands on a Wisdom save (Cloak of Mind Shielding style)."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("save.wisdom.bonus", value=2)
    spec = CheckSpec(
        kind="saving_throw",
        ability="wisdom",
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    assert result.roll_total == 12


def test_resolve_check_save_per_ability_bucket_does_not_leak_to_other_ability(
    monkeypatch,
):
    """A save.wisdom.bonus must NOT influence a Dex save."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("save.wisdom.bonus", value=2)
    spec = CheckSpec(
        kind="saving_throw",
        ability="dexterity",
        ability_scores={"dexterity": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # 10 + 0, no bonus — wisdom-specific change doesn't apply.
    assert result.roll_total == 10


def test_resolve_check_save_generic_bucket_applies_to_any_save(monkeypatch):
    """A save.bonus change still applies regardless of ability."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("save.bonus", value=1)
    spec = CheckSpec(
        kind="saving_throw",
        ability="charisma",
        ability_scores={"charisma": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    assert result.roll_total == 11


def test_resolve_check_generic_and_specific_buckets_stack(monkeypatch):
    """Both buckets apply if both are present on the same effect."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = ActiveEffect(
        id="effect:test_stack",
        name="Stacking Buff",
        origin="cast:test_stack:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=1),
            ActiveEffectChange(key="check.skill_check.bonus", mode="add", value=2),
        ],
    )
    spec = CheckSpec(
        kind="skill",
        ability_scores={"wisdom": 10},
        skill="perception",
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # 10 + 0 + 1 (generic) + 2 (specific) = 13
    assert result.roll_total == 13


def test_resolve_check_no_per_ability_when_kind_is_skill(monkeypatch):
    """save.wisdom.bonus must NOT influence a skill check resolution."""
    import dnd5e_engine.rules.dice as dice_mod

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    eff = _effect("save.wisdom.bonus", value=2)
    spec = CheckSpec(
        kind="skill",
        ability_scores={"wisdom": 10},
        skill="perception",
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    assert result.roll_total == 10
