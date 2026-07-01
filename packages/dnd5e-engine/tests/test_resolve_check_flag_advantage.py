"""Regression — resolve_check honors flag-based advantage/disadvantage changes.

Codex Phase 6 review iter-10 P2: ieffect2._translate_passive_to_changes
emits effects like frightened/blinded as ``flags.disadvantage.check.*``
changes, but resolve_check only iterated ``check.*.bonus`` / ``save.*.bonus``
buckets. Frightened actors could still roll SKILL_CHECK / FLEE normally.

The fix derives advantage / disadvantage from override-mode flag changes
on the active_effects and ORs them with the spec's own advantage /
disadvantage before invoking the base roll helper.
"""

from __future__ import annotations

import dnd5e_engine.rules.dice as dice_mod
from dnd5e_engine.check import CheckSpec, resolve_check
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
)


def _disadvantage_check_effect() -> ActiveEffect:
    """Frightened-style: flags.disadvantage.check (broad, no ability)."""
    return ActiveEffect(
        id="effect:frightened",
        name="Frightened",
        origin="cast:frightening_presence:1",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="flags.disadvantage.check", mode="override", value=True)],
    )


def _advantage_save_effect() -> ActiveEffect:
    return ActiveEffect(
        id="effect:resistance",
        name="Resistance",
        origin="cast:resistance:1",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="flags.advantage.save", mode="override", value=True)],
    )


def test_skill_check_inherits_disadvantage_from_frightened_effect(monkeypatch):
    """Frightened actor → skill check rolled at disadvantage."""
    # First call: d20 = 18, second call (disadvantage takes lower): d20 = 5.
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    spec = CheckSpec(
        kind="skill",
        skill="perception",
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(_disadvantage_check_effect(),),
    )
    result = resolve_check(spec)
    # Disadvantage took the lower of (18, 5) = 5; modifier = 0 → total = 5.
    assert result.roll_total == 5


def test_skill_check_without_effect_is_normal(monkeypatch):
    """Without a flag-tagged effect, the roll uses the first d20."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    spec = CheckSpec(
        kind="skill",
        skill="perception",
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(),
    )
    result = resolve_check(spec)
    # Normal roll → first d20 only = 18.
    assert result.roll_total == 18


def test_saving_throw_inherits_advantage_from_resistance_effect(monkeypatch):
    """flags.advantage.save (broad) lifts a saving throw to advantage."""
    rolls = iter([5, 18])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    spec = CheckSpec(
        kind="saving_throw",
        ability="wisdom",
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(_advantage_save_effect(),),
    )
    result = resolve_check(spec)
    # Advantage takes the higher of (5, 18) = 18.
    assert result.roll_total == 18


def test_per_ability_save_flag_applies_only_to_matching_ability(monkeypatch):
    """flags.disadvantage.save.dexterity must not affect a Wisdom save."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:test",
        name="Test",
        origin="cast:test:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.disadvantage.save.dexterity",
                mode="override",
                value=True,
            )
        ],
    )
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
    # Dex-specific disadvantage must NOT apply to a Wis save → normal roll = 18.
    assert result.roll_total == 18


def test_per_ability_save_flag_applies_to_matching_ability(monkeypatch):
    """flags.disadvantage.save.wisdom DOES affect a Wisdom save."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:test",
        name="Test",
        origin="cast:test:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.disadvantage.save.wisdom",
                mode="override",
                value=True,
            )
        ],
    )
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
    # Wis-targeted disadvantage applies → roll = 5.
    assert result.roll_total == 5


def test_spec_advantage_or_flag_advantage_either_triggers(monkeypatch):
    """A spec.advantage=True OR a flags.advantage effect both produce advantage.
    Either path independently triggers the higher-roll selection."""
    rolls = iter([5, 18])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:bardic_inspiration",
        name="Bardic Inspiration",
        origin="cast:bardic_inspiration:1",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="flags.advantage.check", mode="override", value=True)],
    )
    spec = CheckSpec(
        kind="skill",
        skill="performance",
        ability_scores={"charisma": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        advantage=False,  # spec says no, but flag says yes
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    assert result.roll_total == 18
