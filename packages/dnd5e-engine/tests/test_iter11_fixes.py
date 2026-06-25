"""Regression — Codex Phase 6 review iter-11 fixes.

P1: flat integer strings ("1", "-1") are valid mode=add values per
SRD asset shape (Haste / Warding Bond / Resurrection). They must
parse via int() rather than crashing the dice parser.

P2: skill check flag-based advantage / disadvantage derives the
relevant ability from the skill via SKILL_ABILITIES; an ability-tagged
flag (e.g. flags.disadvantage.check.strength from Weakening Breath)
applies only to skills whose underlying ability matches.
"""

from __future__ import annotations

import dnd5e_engine.rules.dice as dice_mod
from dnd5e_engine.check import CheckSpec, resolve_check
from dnd5e_engine.rules.effects import apply_changes_to_check
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _eff_changes(*changes: ActiveEffectChange) -> ActiveEffect:
    return ActiveEffect(
        id="effect:test",
        name="Test",
        origin="cast:test:1",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=10),
        changes=list(changes),
    )


def test_apply_changes_to_check_flat_string_value_parses_as_int():
    """Haste-style save_bonus="1" must not crash; the int folds into total."""
    eff = _eff_changes(ActiveEffectChange(key="save.bonus", mode="add", value="1"))
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="save.bonus", effects=[eff]
    )
    assert total == 11
    assert any("+1" in b for b in breakdown)


def test_apply_changes_to_check_negative_string_value_parses():
    """Resurrection-style check_bonus="-1" parses as a flat int."""
    eff = _eff_changes(
        ActiveEffectChange(key="check.bonus", mode="add", value="-1")
    )
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="check.bonus", effects=[eff]
    )
    assert total == 9
    assert any("-1" in b for b in breakdown)


def test_apply_changes_to_check_dice_formula_still_works(monkeypatch):
    """The dice-formula path is untouched: "1d4" still rolls via the parser."""
    monkeypatch.setattr(
        "dnd5e_engine.rules.effects._roll_dice_str", lambda s: 3
    )
    eff = _eff_changes(
        ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4")
    )
    total, _ = apply_changes_to_check(
        base_total=10, bucket="attack.roll.bonus", effects=[eff]
    )
    assert total == 13


def test_apply_changes_to_check_unparseable_string_skips_safely():
    """An unparseable string ("foo") doesn't crash; the breakdown notes it."""
    eff = _eff_changes(
        ActiveEffectChange(key="save.bonus", mode="add", value="foo")
    )
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="save.bonus", effects=[eff]
    )
    assert total == 10
    assert any("unparsed" in b for b in breakdown)


def test_strength_only_check_dis_doesnt_leak_to_perception(monkeypatch):
    """flags.disadvantage.check.strength (Weakening Breath) must NOT
    disadvantage a Perception (Wisdom) check."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:weakening",
        name="Weakening Breath",
        origin="cast:weakening:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.disadvantage.check.strength",
                mode="override",
                value=True,
            )
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="perception",  # Perception → Wisdom
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # Strength-only flag doesn't apply to Perception → normal roll = 18.
    assert result.roll_total == 18


def test_strength_only_check_dis_applies_to_athletics(monkeypatch):
    """flags.disadvantage.check.strength DOES apply to Athletics (Strength)."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:weakening",
        name="Weakening Breath",
        origin="cast:weakening:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.disadvantage.check.strength",
                mode="override",
                value=True,
            )
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="athletics",  # Athletics → Strength
        ability_scores={"strength": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # Strength-tagged → disadvantage → take lower of (18, 5) = 5.
    assert result.roll_total == 5


def test_broad_check_dis_still_applies_to_any_skill(monkeypatch):
    """A broad flags.disadvantage.check (no ability suffix) applies to any skill."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = ActiveEffect(
        id="effect:frightened",
        name="Frightened",
        origin="cast:frightful:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.disadvantage.check", mode="override", value=True
            )
        ],
    )
    spec = CheckSpec(
        kind="skill",
        skill="perception",
        ability_scores={"wisdom": 10},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=0,
        active_effects=(eff,),
    )
    result = resolve_check(spec)
    # Broad disadvantage applies → take lower = 5.
    assert result.roll_total == 5
