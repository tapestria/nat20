"""dnd5e-engine type surface — host-agnostic Pydantic + Literal types."""

from dnd5e_engine.types.combat import Combatant, CombatNPC
from dnd5e_engine.types.conditions import ActiveCondition, ConditionScope
from dnd5e_engine.types.dice import DiceOutcome
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)
from dnd5e_engine.types.intent import ActionType, CombatOutcome

__all__ = [
    "ActionType",
    "ActiveCondition",
    "ActiveEffect",
    "ActiveEffectChange",
    "ActiveEffectDuration",
    "CombatNPC",
    "CombatOutcome",
    "Combatant",
    "ConditionScope",
    "DiceOutcome",
]
