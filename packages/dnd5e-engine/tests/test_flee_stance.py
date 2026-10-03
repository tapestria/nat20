"""C24 — the flee stance on a grid (``_apply_monster_flee_stance``): an
Incapacitated monster takes none, and a fleeing monster an
opportunity attack kills stops where it stood. Monster flee is
DM-adjudicated AI, not SRD text; SRD 5.2 Incapacitated: "You can't take any
action, Bonus Action, or Reaction."
"""

from __future__ import annotations

import asyncio
from typing import Any

from dnd5e_engine import ActiveEffect
from dnd5e_engine.events import ActorMoved, AttackRolled, IntentSubmitted
from dnd5e_engine.orchestrator import (
    _current_actor,
    _get_live,
    _LiveCombat,
    advance_monster_turn,
    start_combat,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec


def _fight(goblin_cell: str, *, hero: dict[str, Any] | None = None, effects=()) -> _LiveCombat:
    """The hero on 0,0 (initiative 1) and a goblin warrior at 1/20 HP — under
    its 10% AGGRESSIVE flee threshold — that acts first; runs its turn."""

    async def _inner() -> _LiveCombat:
        result = await start_combat(
            session_id="c24-flee-stance",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=12,
                    zone_id=cell_id(0, 0),
                    **(hero or {}),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:goblin",
                    entity_type="Monster",
                    name="Goblin",
                    initiative=20,
                    hp_current=1,
                    hp_max=20,
                    ac=15,
                    monster_template_slug="goblin-warrior",
                    zone_id=goblin_cell,
                )
            ],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
            active_effects=list(effects),
        )
        await advance_monster_turn(result.handle)
        return _get_live(result.handle)

    return asyncio.run(_inner())


def _goblin(live: _LiveCombat):
    return next(c for c in live.initiative if c.entity_id == "mon:goblin")


def _goblin_moves(live: _LiveCombat) -> list[ActorMoved]:
    return [e for e in live.event_log if isinstance(e, ActorMoved) and e.actor_id == "mon:goblin"]


def _goblin_intents(live: _LiveCombat) -> list[str]:
    return [
        e.intent_type
        for e in live.event_log
        if isinstance(e, IntentSubmitted) and e.actor_id == "mon:goblin"
    ]


def test_an_incapacitated_monster_below_its_threshold_takes_no_flee_stance() -> None:
    stunned = ActiveEffect(
        id="effect:stun",
        name="Stun",
        origin="test:stun",
        target_id="mon:goblin",
        statuses={"stunned"},
    )
    live = _fight(cell_id(3, 0), effects=[stunned])
    assert _goblin_moves(live) == []
    assert _goblin(live).has_fled is False
    assert _goblin_intents(live) == ["pass"]


def test_the_same_monster_unhindered_flees() -> None:
    live = _fight(cell_id(3, 0))
    assert len(_goblin_moves(live)) == 6
    assert _goblin(live).has_fled is True


def test_a_fleeing_monster_killed_by_an_opportunity_attack_stops_and_passes() -> None:
    # The hero (to-hit +20) strikes as the goblin's first step leaves its
    # reach; the 1-HP goblin dies on 1,0 and never takes the step.
    live = _fight(cell_id(1, 0), hero={"attack_bonus": 20})
    [aoo] = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert (aoo.attacker_id, aoo.is_opportunity_attack, aoo.is_hit) == ("char:hero", True, True)
    assert "mon:goblin" in live.dead_ids
    assert _goblin_moves(live) == []
    assert live.actor_zone["mon:goblin"] == cell_id(1, 0)
    assert _goblin_intents(live) == ["pass"]
    assert _current_actor(live).entity_id == "char:hero"
