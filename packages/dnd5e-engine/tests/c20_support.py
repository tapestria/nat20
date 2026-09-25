"""Seeded single-foe grid combats shared by the C20 class-feature tests."""

from __future__ import annotations

import asyncio
from typing import Any

from dnd5e_engine import CombatHandle, PlayerIntent
from dnd5e_engine.orchestrator import (
    _get_live,
    _LiveCombat,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant


def pc(entity_id: str = "char:hero", **fields: Any) -> PartyMemberSpec:
    """A PC at cell 0,0 that acts first (initiative 20) with 30/30 HP."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("char:").title(),
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def foe(**fields: Any) -> EncounterMemberSpec:
    """A template-less 500-HP, AC 1 foe at cell 1,0 (5 ft away) that acts last."""
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 1,
        "hp_current": 500,
        "hp_max": 500,
        "ac": 1,
        "zone_id": cell_id(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def start(
    party: list[PartyMemberSpec],
    *,
    seed: int,
    encounter: list[EncounterMemberSpec] | None = None,
    **kwargs: Any,
) -> tuple[CombatHandle, _LiveCombat]:
    """Start a combat on a 10x10 grid; ``kwargs`` pass through (``active_effects=``)."""
    result = asyncio.run(
        start_combat(
            session_id=f"c20-{seed}",
            party=party,
            encounter=encounter or [foe()],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=seed,
            **kwargs,
        )
    )
    return result.handle, _get_live(result.handle)


def act(handle: CombatHandle, actor_id: str, **intent: Any) -> None:
    """Submit one ``PlayerIntent`` for ``actor_id``."""
    asyncio.run(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def monster_turn(handle: CombatHandle) -> None:
    asyncio.run(advance_monster_turn(handle))


def combatant(live: _LiveCombat, entity_id: str = "char:hero") -> Combatant:
    return next(c for c in live.initiative if c.entity_id == entity_id)


def events[T](live: _LiveCombat, kind: type[T]) -> list[T]:
    return [e for e in live.event_log if isinstance(e, kind)]
