"""ConditionScope + ActiveCondition — structured condition records for combatants."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ConditionScope = Literal["combat", "session"]


class ActiveCondition(BaseModel):
    """A condition currently affecting a combatant.

    Phase 1 v3.1: replaces list[str] conditions with structured model.
    """

    condition: str  # Condition.value (e.g. "poisoned")
    source_entity_id: Annotated[
        str,
        Field(pattern=r"^[a-z]+:[a-f0-9]{12}$|^implied:[a-z]+$"),
    ]
    scope: ConditionScope
    duration_rounds: int | None = None
    save_dc: int | None = None
    applied_round: int = 0
    exhaustion_level: int = 1  # Only meaningful when condition=="exhaustion"
    # Effect node ID when condition is bridged from an effect; None for non-bridged conditions
    source_effect_id: str | None = None


__all__ = [
    "ActiveCondition",
    "ConditionScope",
]
