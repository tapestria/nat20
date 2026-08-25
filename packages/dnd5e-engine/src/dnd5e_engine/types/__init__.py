"""dnd5e-engine type surface — host-agnostic Pydantic + Literal types."""

from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition, ConditionScope
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)

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

_GEN1_LAZY = {
    "ActionType": ("dnd5e_engine.types.intent", "ActionType"),
    "CombatOutcome": ("dnd5e_engine.types.intent", "CombatOutcome"),
    "DiceOutcome": ("dnd5e_engine.types.dice", "DiceOutcome"),
    "CombatNPC": ("dnd5e_engine.types.combat", "CombatNPC"),
}


def __getattr__(name: str) -> object:
    # PEP 562 — keep the 0.3.x names resolvable without importing the
    # deprecated modules eagerly (which would warn on every ``import dnd5e_engine.types``).
    if name in _GEN1_LAZY:
        import importlib
        import warnings

        module, attr = _GEN1_LAZY[name]
        warnings.warn(
            f"dnd5e_engine.types.{name} belongs to the legacy (Gen 1) surface — a host-side "
            f"shape, not an engine type — and will be removed in dnd5e-engine 0.5.0. "
            f"Import it from {module} (also deprecated) or copy it into your host; "
            f"see docs/migration/v0.3-to-v0.4.md.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(f"module 'dnd5e_engine.types' has no attribute {name!r}")
