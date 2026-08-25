"""Regression — combat resolvers use Foundry-shaped bucket keys (Phase 6).

Codex review of Phase 6 caught that ``rules/combat.py`` was passing legacy
bucket strings (``"saving_throw"``, ``"damage"``, ``"attack_roll"``, ``"ac"``)
into ``apply_changes_to_check``. The seed templates emit Foundry-shaped keys
(``save.bonus``, ``damage.bonus``, ``attack.roll.bonus``, ``ac.bonus``); the
helper does exact key matching, so the resolvers were silently no-op-ing
every effect. These tests lock the alignment.
"""

from __future__ import annotations

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
