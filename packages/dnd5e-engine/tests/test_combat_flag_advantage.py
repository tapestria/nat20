"""Regression — combat resolvers honor flag-based advantage / disadvantage.

combat.py's saving_throw and resolve_player_attack read flag-based
advantage / disadvantage from active_effects, so Restrained /
Guidance-style / Faerie Fire / Invisible effects shift the d20 mechanic
in combat, as resolve_check does.
"""

from __future__ import annotations

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
