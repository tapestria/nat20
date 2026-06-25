"""Named result envelopes for state-mutating library entry points.

Per the dnd5e-engine extraction spec — start_combat and end_combat
return envelopes rather than tuples so fields are named, IDE
introspection works, and adding new return data later is non-breaking.

CombatHandle is defined in dnd5e_engine.orchestrator (moved in Task 13);
this module imports it via TYPE_CHECKING + model_rebuild() to avoid a
hard import cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from dnd5e_engine.events import CombatEvent
from dnd5e_engine.outcome import CombatOutcome
from dnd5e_engine.types.effects import ActiveEffect

if TYPE_CHECKING:
    from dnd5e_engine.orchestrator import CombatHandle


class StartCombatResult(BaseModel):
    """Returned by dnd5e_engine.start_combat."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    handle: CombatHandle
    events: list[CombatEvent]


class EndCombatResult(BaseModel):
    """Returned by dnd5e_engine.end_combat.

    ``final_active_effects`` is the engine's authoritative snapshot of
    effects still live at end_combat — excludes effects whose source
    died, durations ticked to zero, or concentration broken. Log-only
    in Phase 6; persisted in [effects-cross-combat].
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    outcome: CombatOutcome
    events: list[CombatEvent]
    final_active_effects: tuple[ActiveEffect, ...] = Field(default_factory=tuple)


__all__ = [
    "EndCombatResult",
    "StartCombatResult",
]
