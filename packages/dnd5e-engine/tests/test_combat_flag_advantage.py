"""Regression — combat resolvers honor flag-based advantage / disadvantage.

Codex Phase 6 review iter-12 P2: combat.py's saving_throw and
resolve_player_attack didn't read flag-based advantage / disadvantage
from active_effects, so Restrained / Guidance-style / Faerie Fire /
Invisible effects didn't shift the d20 mechanic in combat. Now both
mirror the iter-10/11 resolve_check fix.
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
