"""C24 — the opportunity-attack trigger: who a step provokes
(``_opportunity_attackers``), the attacks it makes and when the walk stops
(``_fire_opportunity_attacks_on_step``, ``_walk_must_stop``). SRD 5.2
Opportunity Attacks: "You can make an Opportunity Attack when a creature that
you can see leaves your reach ... The attack occurs right before the creature
leaves your reach." All on a 10x10 grid.
"""

from __future__ import annotations

import asyncio
from typing import Any

from dnd5e_engine.events import AttackRolled
from dnd5e_engine.orchestrator import (
    _fire_opportunity_attacks_on_step,
    _get_live,
    _LiveCombat,
    _opportunity_attackers,
    _update_combatant,
    _walk_must_stop,
    start_combat,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from tests.c21_support import anchor_effect, seat_summon, summoner
from tests.c21_support import foe as c21_foe
from tests.c21_support import start as c21_start


def _hero(**fields: Any) -> PartyMemberSpec:
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "ac": 12,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _foe(entity_id: str = "mon:foe", **fields: Any) -> EncounterMemberSpec:
    """A template-less foe (legacy ``attack_bonus`` / ``damage_dice`` swing)."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "initiative": 1,
        "hp_current": 50,
        "hp_max": 50,
        "ac": 10,
        "zone_id": cell_id(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _start(party: list[PartyMemberSpec], encounter: list[EncounterMemberSpec]) -> _LiveCombat:
    async def _inner() -> _LiveCombat:
        result = await start_combat(
            session_id="c24-trigger",
            party=party,
            encounter=encounter,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
        )
        return _get_live(result.handle)

    return asyncio.run(_inner())


def _give(live: _LiveCombat, entity_id: str, condition: str, source: str = "implied:test") -> None:
    combatant = next(c for c in live.initiative if c.entity_id == entity_id)
    combatant.conditions.append(
        ActiveCondition(condition=condition, source_entity_id=source, scope="combat")
    )
    live.active_conditions.setdefault(entity_id, set()).add(condition)


def test_a_step_provokes_only_when_it_leaves_reach() -> None:
    live = _start([_hero()], [_foe()])
    # 1,0 -> 1,1 stays 5 ft from the hero (a diagonal neighbour is in reach).
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(1, 1)
        )
        == []
    )
    assert _opportunity_attackers(
        live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
    ) == ["char:hero"]
    # A step that starts outside reach leaves nothing.
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(2, 0), to_cell=cell_id(3, 0)
        )
        == []
    )


def test_only_the_movers_enemies_react_and_never_a_summon() -> None:
    # The summoner on 0,0 and its spirit on 0,1 both stand beside the foe on
    # 1,0; so does the foe's ally on 2,1. Only the summoner reacts: an ally
    # never does, and a summon takes no reactions.
    _handle, live = c21_start(
        [summoner()],
        seed=1,
        encounter=[c21_foe(), c21_foe(entity_id="mon:ally", name="Ally", zone_id=cell_id(2, 1))],
        active_effects=[anchor_effect("char:summoner")],
    )
    seat_summon(live, "char:summoner", zone_id=cell_id(0, 1))
    assert _opportunity_attackers(
        live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(3, 0)
    ) == ["char:summoner"]


def test_an_incapacitated_reactor_or_one_without_its_reaction_never_reacts() -> None:
    live = _start([_hero()], [_foe()])
    _give(live, "char:hero", "stunned")
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
        )
        == []
    )

    live = _start([_hero()], [_foe()])
    _update_combatant(live, "char:hero", reaction_available=False)
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
        )
        == []
    )


def test_a_disengaging_mover_provokes_no_one() -> None:
    live = _start([_hero()], [_foe()])
    _update_combatant(live, "mon:foe", disengaging_this_turn=True)
    assert (
        _opportunity_attackers(
            live, mover_id="mon:foe", from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
        )
        == []
    )


def test_a_charmed_reactor_never_attacks_its_charmer() -> None:
    # SRD 5.2 Charmed: "You can't attack the charmer." The hero, charmed by
    # the foe on 1,0, still strikes the other foe on 0,1. (A condition's
    # ``source_entity_id`` takes a 12-hex-digit id.)
    charmer = "mon:00000000beef"
    live = _start([_hero()], [_foe(charmer), _foe("mon:other", zone_id=cell_id(0, 1))])
    _give(live, "char:hero", "charmed", source=charmer)
    assert (
        _opportunity_attackers(
            live, mover_id=charmer, from_cell=cell_id(1, 0), to_cell=cell_id(2, 0)
        )
        == []
    )
    assert _opportunity_attackers(
        live, mover_id="mon:other", from_cell=cell_id(0, 1), to_cell=cell_id(0, 2)
    ) == ["char:hero"]


def test_a_prone_mover_ten_feet_away_imposes_disadvantage() -> None:
    # SRD 5.2 Prone: attack rolls against it have Advantage only "if the
    # attacker is within 5 feet"; otherwise Disadvantage. A 10-ft reach hero
    # strikes the Prone foe as it crawls from 10 ft to 15 ft.
    live = _start([_hero(reach_ft=10)], [_foe(zone_id=cell_id(2, 0))])
    _give(live, "mon:foe", "prone")
    _fire_opportunity_attacks_on_step(
        live, mover_id="mon:foe", from_cell=cell_id(2, 0), to_cell=cell_id(3, 0)
    )
    [rolled] = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert rolled.advantage == "disadvantage"
    assert "condition:target" in rolled.disadvantage_sources


def test_the_reactors_after_the_one_that_drops_the_mover_attack_nothing() -> None:
    # Both foes beside the 1-HP hero on 1,1 are left by its step to 1,2; the
    # first (initiative 15) drops it, so it never leaves the second's reach.
    live = _start(
        [_hero(zone_id=cell_id(1, 1), hp_current=1)],
        [
            _foe("mon:one", zone_id=cell_id(0, 0), initiative=15, attack_bonus=20),
            _foe("mon:two", zone_id=cell_id(2, 0), initiative=10, attack_bonus=20),
        ],
    )
    stopped = _fire_opportunity_attacks_on_step(
        live, mover_id="char:hero", from_cell=cell_id(1, 1), to_cell=cell_id(1, 2)
    )
    assert stopped is True
    attackers = [e.attacker_id for e in live.event_log if isinstance(e, AttackRolled)]
    assert attackers == ["mon:one"]
    two = next(c for c in live.initiative if c.entity_id == "mon:two")
    assert two.reaction_available is True


def test_a_walk_stops_at_zero_hp_or_zero_speed() -> None:
    live = _start([_hero()], [_foe()])
    assert _walk_must_stop(live, "char:hero") is False
    _give(live, "char:hero", "grappled")  # SRD 5.2 Grappled: "Speed 0"
    assert _walk_must_stop(live, "char:hero") is True

    live = _start([_hero()], [_foe()])
    _update_combatant(live, "char:hero", hp_current=0)
    assert _walk_must_stop(live, "char:hero") is True
    assert _walk_must_stop(live, "char:nobody") is True
