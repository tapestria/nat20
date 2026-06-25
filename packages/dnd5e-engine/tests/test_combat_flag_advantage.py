"""Regression — combat resolvers honor flag-based advantage / disadvantage.

Codex Phase 6 review iter-12 P2: combat.py's saving_throw and
resolve_player_attack didn't read flag-based advantage / disadvantage
from active_effects, so Restrained / Guidance-style / Faerie Fire /
Invisible effects didn't shift the d20 mechanic in combat. Now both
mirror the iter-10/11 resolve_check fix.
"""

from __future__ import annotations

import dnd5e_engine.rules.dice as dice_mod
from dnd5e_engine.rules.combat import resolve_player_attack, saving_throw
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
)


def _flag_effect(key: str, target_id: str = "char:hero") -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:test_{key}",
        name=f"test_{key}",
        origin=f"cast:test:{key}",
        target_id=target_id,
        changes=[ActiveEffectChange(key=key, mode="override", value=True)],
    )


def test_saving_throw_inherits_advantage_from_active_effect_flag(monkeypatch):
    """flags.advantage.save (broad) on a target's active_effects forces
    advantage on a combat save."""
    rolls = iter([5, 18])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = _flag_effect("flags.advantage.save")
    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="wisdom",
        active_effects=[eff],
    )
    # Advantage takes higher of (5, 18) = 18 + 0 = 18.
    assert result.roll.total == 18


def test_saving_throw_inherits_disadvantage_from_per_ability_flag(monkeypatch):
    """flags.disadvantage.save.dexterity affects a Dex save only."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = _flag_effect("flags.disadvantage.save.dexterity")
    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="dexterity",
        active_effects=[eff],
    )
    assert result.roll.total == 5


def test_saving_throw_per_ability_flag_doesnt_leak(monkeypatch):
    """flags.disadvantage.save.dexterity must NOT affect a Wisdom save."""
    rolls = iter([18, 5])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = _flag_effect("flags.disadvantage.save.dexterity")
    result = saving_throw(
        ability_score=10,
        is_proficient=False,
        proficiency_bonus=0,
        dc=15,
        ability="wisdom",
        active_effects=[eff],
    )
    assert result.roll.total == 18


def test_resolve_player_attack_inherits_attacker_advantage(monkeypatch):
    """flags.advantage.attack on the attacker's active_effects (e.g.
    Invisible) grants attack roll advantage."""
    rolls = iter([5, 18, 6, 6, 6, 6])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = _flag_effect("flags.advantage.attack")
    result = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=15,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[eff],
        target_active_effects=[],
    )
    # Advantage takes higher → 18 + 3 = 21 vs AC 15 → hit.
    assert result.attack_roll == 21
    assert result.hit is True


def test_resolve_player_attack_inherits_target_attack_advantage(monkeypatch):
    """flags.advantage.attack on the TARGET's active_effects (e.g.
    Faerie Fire) grants attack roll advantage to the attacker."""
    rolls = iter([5, 18, 6, 6, 6, 6])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    faerie_fire = _flag_effect("flags.advantage.attack", target_id="mon:foe")
    result = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=15,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[],
        target_active_effects=[faerie_fire],
    )
    assert result.attack_roll == 21
    assert result.hit is True


def test_resolve_player_attack_inherits_attacker_disadvantage(monkeypatch):
    """flags.disadvantage.attack (e.g. blinded translator output)
    applies disadvantage to the attack roll."""
    rolls = iter([18, 5, 6, 6, 6, 6])
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: next(rolls))

    eff = _flag_effect("flags.disadvantage.attack")
    result = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=15,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[eff],
        target_active_effects=[],
    )
    # Disadvantage takes lower → 5 + 3 = 8 vs AC 15 → miss.
    assert result.attack_roll == 8
    assert result.hit is False
