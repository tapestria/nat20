"""Seeded grid combats shared by the C21a tests: the concentration anchor,
Magic Weapon, Spiritual Weapon, Wild Shape and Polymorph."""

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
    """A PC at cell 0,0 that acts first (initiative 20) with 40/40 HP."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("char:").title(),
        "initiative": 20,
        "hp_current": 40,
        "hp_max": 40,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def cleric(entity_id: str = "char:cleric", **fields: Any) -> PartyMemberSpec:
    """A Cleric 5 with WIS 16: spell attack +6 (PB 3 + WIS 3), spellcasting
    modifier +3. Knows Spiritual Weapon and Bless; two level-1 and two level-2
    slots."""
    base: dict[str, Any] = {
        "class_slug": "cleric",
        "character_level": 5,
        "wisdom": 16,
        "spells_known": ["spiritual-weapon", "bless"],
        "spell_slots": {1: 2, 2: 2},
    }
    return pc(entity_id, **(base | fields))


def druid(entity_id: str = "char:druid", **fields: Any) -> PartyMemberSpec:
    """A Druid 6: Wild Shape into a Beast of CR 1/2 or lower without a Fly
    Speed, gaining 6 Temporary Hit Points."""
    base: dict[str, Any] = {"class_slug": "druid", "character_level": 6}
    return pc(entity_id, **(base | fields))


def wizard(entity_id: str = "char:wiz", **fields: Any) -> PartyMemberSpec:
    """A Wizard 9 with INT 18 (spell save DC 16) who knows Polymorph and Hold
    Person; two level-2 slots and one level-4 slot."""
    base: dict[str, Any] = {
        "class_slug": "wizard",
        "character_level": 9,
        "intelligence": 18,
        "spells_known": ["polymorph", "hold-person"],
        "spell_slots": {2: 2, 4: 1},
    }
    return pc(entity_id, **(base | fields))


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
            session_id=f"c21a-{seed}",
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
