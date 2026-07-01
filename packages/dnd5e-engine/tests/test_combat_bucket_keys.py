"""Regression — combat resolvers use Foundry-shaped bucket keys (Phase 6).

Codex review of Phase 6 caught that ``rules/combat.py`` was passing legacy
bucket strings (``"saving_throw"``, ``"damage"``, ``"attack_roll"``, ``"ac"``)
into ``apply_changes_to_check``. The seed templates emit Foundry-shaped keys
(``save.bonus``, ``damage.bonus``, ``attack.roll.bonus``, ``ac.bonus``); the
helper does exact key matching, so the resolvers were silently no-op-ing
every effect. These tests lock the alignment.
"""

from __future__ import annotations

import dnd5e_engine.rules.dice as dice_mod
import dnd5e_engine.rules.effects as eff_mod
from dnd5e_engine.rules.combat import resolve_player_attack, saving_throw
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _bless(target_id: str = "char:hero") -> ActiveEffect:
    """Seed-shaped Bless: +1d4 on attack rolls and saves (Foundry keys)."""
    return ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id=target_id,
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="save.bonus", mode="add", value="1d4"),
        ],
        flags={"concentration": True},
    )


def _cloak(target_id: str = "char:hero") -> ActiveEffect:
    """Seed-shaped Cloak of Protection: +1 AC and +1 saves (Foundry keys)."""
    return ActiveEffect(
        id="effect:cloak_of_protection",
        name="Cloak of Protection",
        origin="item:cloak_of_protection:1",
        target_id=target_id,
        changes=[
            ActiveEffectChange(key="ac.bonus", mode="add", value=1),
            ActiveEffectChange(key="save.bonus", mode="add", value=1),
        ],
    )


def _plus_one_sword(target_id: str = "char:hero") -> ActiveEffect:
    """Seed-shaped +1 Weapon: +1 attack and +1 damage (Foundry keys)."""
    return ActiveEffect(
        id="effect:weapon_plus_1",
        name="+1 Weapon",
        origin="item:weapon_plus_1:1",
        target_id=target_id,
        changes=[
            ActiveEffectChange(key="attack.roll.bonus", mode="add", value=1),
            ActiveEffectChange(key="damage.bonus", mode="add", value=1),
        ],
    )


def test_saving_throw_consumes_save_bonus_changes(monkeypatch):
    """Bless / Cloak / Bane changes keyed `save.bonus` land on a saving throw."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    monkeypatch.setattr(eff_mod, "roll_dice_str", lambda s: 3)

    result_without = saving_throw(
        ability_score=14,
        is_proficient=False,
        proficiency_bonus=2,
        dc=15,
        ability="wisdom",
        active_effects=[],
    )
    result_with_bless = saving_throw(
        ability_score=14,
        is_proficient=False,
        proficiency_bonus=2,
        dc=15,
        ability="wisdom",
        active_effects=[_bless()],
    )
    # Bless adds +1d4 (pinned to 3) on save → succeed where the bare save
    # would not (10 + WIS +2 = 12 vs DC 15, then +3 from Bless = 15 ≥ 15).
    assert result_without.success is False
    assert result_with_bless.success is True, (
        "Bless save.bonus change must fold into the saving throw total via the `save.bonus` bucket"
    )


def test_resolve_player_attack_consumes_attack_roll_bonus_changes(monkeypatch):
    """+1 weapon / Bless attack-side changes land on the attack roll."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)

    base = resolve_player_attack(
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
        target_active_effects=[],
    )
    with_sword = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=15,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[_plus_one_sword()],
        target_active_effects=[],
    )
    # +1 weapon → +1 attack roll AND +1 damage dealt.
    assert with_sword.attack_roll == base.attack_roll + 1, (
        "+1 weapon attack.roll.bonus must fold into the attack total via the "
        "`attack.roll.bonus` bucket"
    )
    if base.hit and with_sword.hit:
        assert with_sword.damage_dealt == base.damage_dealt + 1, (
            "+1 weapon damage.bonus must fold via the `damage.bonus` bucket"
        )


def test_resolve_player_attack_consumes_target_ac_bonus_changes(monkeypatch):
    """Target-side `ac.bonus` (Cloak of Protection) raises effective AC."""
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 14)

    # With +14 d20 and +3 attack vs AC 16, base attack hits (17 ≥ 16).
    base = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=16,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[],
        target_active_effects=[],
    )
    # With Cloak of Protection on the TARGET, AC is effectively 17, attack misses.
    with_cloak = resolve_player_attack(
        action_type="attack",
        attack_bonus=3,
        target_ac=16,
        damage_dice="1d8",
        damage_type="slashing",
        damage_modifier=2,
        target_name="goblin",
        target_hp_current=10,
        target_hp_max=10,
        active_effects=[],
        target_active_effects=[_cloak(target_id="goblin")],
    )
    # Load-bearing: ac.bonus must propagate into the reported target_ac. If
    # the bucket name mismatches, ac.bonus silently no-ops and the
    # CombatOutcome carries the raw input AC unchanged.
    assert base.target_ac == 16
    assert with_cloak.target_ac == 17, (
        "Cloak of Protection ac.bonus on the target must raise effective AC "
        "via the `ac.bonus` bucket — otherwise CombatOutcome.target_ac stays "
        "at the raw input value"
    )
