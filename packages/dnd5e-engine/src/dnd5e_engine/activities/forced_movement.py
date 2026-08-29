"""Typed forced-movement riders (SRD 5.2 "pushed … away from you").

The canonical dataset carries these pushes only as prose (Foundry's activity
model has no push field — ``canonical/spells/thunderwave.json`` is a plain
``save`` activity with ``effects: []``), so the engine keeps a typed registry
keyed by spell slug, exactly as conditions/traits started as a Python registry
before becoming dataset categories (spec §6 D3). Moving this to a dataset
field is the recorded C22 seam. Pure data: no orchestrator import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ForcedMovementTrigger = Literal["failed_save", "hit"]
ForcedMovementDirection = Literal["away_from_caster"]


@dataclass(frozen=True)
class ForcedMovementRider:
    distance_ft: int
    trigger: ForcedMovementTrigger
    direction: ForcedMovementDirection


# SRD 5.2 Thunderwave: "On a failed save, a creature takes 2d8 Thunder damage
# and is pushed 10 feet away from you."
FORCED_MOVEMENT_RIDERS: dict[str, ForcedMovementRider] = {
    "thunderwave": ForcedMovementRider(
        distance_ft=10, trigger="failed_save", direction="away_from_caster"
    ),
}

__all__ = [
    "FORCED_MOVEMENT_RIDERS",
    "ForcedMovementDirection",
    "ForcedMovementRider",
    "ForcedMovementTrigger",
]
