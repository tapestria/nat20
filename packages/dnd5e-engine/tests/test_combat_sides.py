"""Encounter members that fight on the party's side.

SRD 5.2 Summon Dragon: "The creature is an ally to you and your allies." A
host seats such a creature with ``EncounterMemberSpec(side="party")``: it
joins ``party_ids``, so every ally rule and the monster AI read it as one of
the characters' side, while it stays a monster in every rule meant for
characters only. SRD 5.2 Monster death: a monster dies the instant it drops
to 0 Hit Points, so an ally gets a ``Death``, never Unconscious and death
saves, and Encounter XP is divided among the surviving characters alone.
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import pytest
from pydantic import BaseModel

from dnd5e_engine import end_combat, start_combat
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    Death,
    DeathSaveRolled,
    DeathSaveStarted,
    IntentSubmitted,
    Unconscious,
)
from dnd5e_engine.orchestrator import _current_actor, _is_enemy
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene
from dnd5e_engine.testing import rng_factory
from tests.c21_support import (
    act,
    anchor_effect,
    events,
    foe,
    monster_turn,
    pc,
    seat_summon,
    start,
)

ALLY = "npc:ally"


class _D20Always(random.Random):
    """Every d20 shows ``face``; every other die draws as seeded."""

    face = 20

    def randint(self, a: int, b: int) -> int:
        return self.face if (a, b) == (1, 20) else super().randint(a, b)


def ally(**fields: object) -> EncounterMemberSpec:
    """A template-less NPC on the party's side at cell 0,1, acting second."""
    base: dict[str, object] = {
        "entity_id": ALLY,
        "entity_type": "NPC",
        "name": "Ally",
        "side": "party",
        "initiative": 10,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell_id(0, 1),
    }
    return foe(**(base | fields))


def test_a_party_side_member_is_on_the_party_side() -> None:
    _, live = start(
        [pc(), pc("char:owner", zone_id=cell_id(0, 2))],
        seed=1,
        encounter=[ally(), foe(), foe(entity_id="mon:foe-2", zone_id=cell_id(2, 0))],
        active_effects=[anchor_effect("char:owner")],
    )
    spirit = seat_summon(live, "char:owner", zone_id=cell_id(1, 2))
    assert ALLY in live.party_ids
    assert ALLY not in live.encounter_ids
    assert live.encounter_ids == {"mon:foe", "mon:foe-2"}
    for enemy in ("mon:foe", "mon:foe-2"):
        assert _is_enemy(live, ALLY, enemy)
        assert _is_enemy(live, enemy, ALLY)
    for friend in ("char:hero", "char:owner", spirit):
        assert not _is_enemy(live, ALLY, friend)
        assert not _is_enemy(live, friend, ALLY)


def test_a_foe_picks_the_ally_when_its_hp_is_lowest() -> None:
    handle, live = start([pc()], seed=2, encounter=[ally(hp_current=3), foe()])
    act(handle, "char:hero", intent_type="pass")
    act(handle, ALLY, intent_type="pass")
    monster_turn(handle)
    [intent] = [e for e in events(live, IntentSubmitted) if e.actor_id == "mon:foe"]
    assert intent.intent_type == "attack"
    assert intent.target_id == ALLY
    assert [a.target_id for a in events(live, AttackRolled)] == [ALLY]


def test_the_ally_turn_runs_the_ai_against_a_foe_and_accepts_a_command() -> None:
    far_foe = foe(zone_id=cell_id(4, 1))
    handle, live = start([pc()], seed=3, encounter=[ally(), far_foe])
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == ALLY
    monster_turn(handle)
    moved = [e for e in events(live, ActorMoved) if e.actor_id == ALLY]
    assert moved
    [attack] = [a for a in events(live, AttackRolled) if a.attacker_id == ALLY]
    assert attack.target_id == "mon:foe"
    assert live.event_log.index(moved[0]) < live.event_log.index(attack)

    monster_turn(handle)  # the foe's turn
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == ALLY
    act(handle, ALLY, intent_type="pass")
    assert [e.intent_type for e in events(live, IntentSubmitted) if e.actor_id == ALLY] == [
        "attack",
        "pass",
    ]
    assert _current_actor(live).entity_id == "mon:foe"


def test_the_ally_dies_at_0_hp_as_a_monster_does() -> None:
    with rng_factory(_D20Always):
        handle, live = start(
            [pc()],
            seed=4,
            encounter=[ally(hp_current=1), foe(hp_current=1, hp_max=1, xp_value=100)],
        )
    act(handle, "char:hero", intent_type="pass")
    act(handle, ALLY, intent_type="pass")
    monster_turn(handle)  # the foe drops the ally
    assert [(d.target_id, d.reason) for d in events(live, Death)] == [(ALLY, "damage")]
    assert ALLY in live.dead_ids
    assert not events(live, Unconscious)
    assert not events(live, DeathSaveStarted)

    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == ALLY
    monster_turn(handle)  # the dead ally's turn: no death save
    assert not events(live, DeathSaveRolled)
    assert [e.intent_type for e in events(live, IntentSubmitted) if e.actor_id == ALLY] == [
        "pass",
        "pass",
    ]

    monster_turn(handle)  # the foe's turn
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")

    outcome = asyncio.run(end_combat(handle)).outcome
    [ally_death, _] = outcome.deaths
    assert ally_death.target_id == ALLY
    assert ally_death.target_kind == "npc"
    assert ally_death.killer_id == "mon:foe"
    assert ALLY in outcome.residual_hp
    assert outcome.xp_awarded == {"char:hero": 100}


def test_only_a_character_seated_at_0_hp_starts_unconscious() -> None:
    _, live = start([pc(hp_current=0)], seed=4, encounter=[ally(hp_current=0), foe()])
    conditions = {c.entity_id: [x.condition for x in c.conditions] for c in live.initiative}
    assert conditions["char:hero"] == ["unconscious"]
    assert conditions[ALLY] == []


def test_xp_goes_to_surviving_characters_only_while_the_ally_lives() -> None:
    with rng_factory(_D20Always):
        handle, _ = start(
            [pc()],
            seed=5,
            encounter=[ally(hp_current=17), foe(hp_current=1, hp_max=1, xp_value=100)],
        )
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.ended_reason == "victory"
    assert outcome.xp_awarded == {"char:hero": 100}
    assert outcome.residual_hp[ALLY] == 17


def _foe_kills(hero_hp: int, ally_hp: int, *, rounds: int) -> str:
    """A 1-HP-max hero (massive damage kills it outright) and an ally face a
    foe whose every d20 is a natural 20; the foe acts ``rounds`` times."""
    with rng_factory(_D20Always):
        handle, live = start(
            [pc(hp_current=hero_hp, hp_max=hero_hp)],
            seed=6,
            encounter=[ally(hp_current=ally_hp, hp_max=ally_hp), foe()],
        )
    for _ in range(rounds):
        while _current_actor(live).entity_id != "mon:foe":
            actor = _current_actor(live).entity_id
            if actor in live.dead_ids:
                monster_turn(handle) if actor == ALLY else act(handle, actor, intent_type="pass")
            else:
                act(handle, actor, intent_type="pass")
        monster_turn(handle)
    return asyncio.run(end_combat(handle)).outcome.ended_reason


def test_a_standing_ally_keeps_the_fight_open_until_it_falls_too() -> None:
    assert _foe_kills(1, 2, rounds=1) == "forced"  # the hero is dead, the ally stands
    assert _foe_kills(1, 2, rounds=2) == "defeat_tpk"


def test_a_start_with_no_encounter_side_member_is_refused() -> None:
    with pytest.raises(ValueError, match="encounter"):
        asyncio.run(
            start_combat(
                session_id="sides",
                party=[pc()],
                encounter=[ally()],
                grid_scene=GridScene(width=10, height=10),
                rng_seed=1,
            )
        )


def _fixture_fight(side: dict[str, str]) -> list[BaseModel]:
    """The fight the stored 0.7.0 payloads were taken from."""
    goblins = [
        foe(
            entity_id="mon:goblin",
            name="Goblin",
            monster_template_slug="goblin-warrior",
            hp_current=1,
            hp_max=30,
            **side,
        ),
        foe(
            entity_id="mon:goblin-2",
            name="Goblin 2",
            monster_template_slug="goblin-warrior",
            hp_current=30,
            hp_max=30,
            zone_id=cell_id(0, 1),
            **side,
        ),
    ]
    hero = pc(class_slug="fighter", character_level=5, strength=16, equipment=("greatsword",))
    handle, live = start([hero], seed=7, encounter=goblins)
    act(handle, "char:hero", intent_type="attack", weapon_id="greatsword", target_id="mon:goblin")
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    asyncio.run(end_combat(handle))
    return list(live.event_log)


def _assert_reproduces(log: list[BaseModel], stored: list[dict[str, object]]) -> None:
    """Every stored event comes back with the same values; a field added to an
    event since the payloads were stored dumps at its default."""
    assert len(log) == len(stored)
    for event, old in zip(log, stored, strict=True):
        dumped = event.model_dump(mode="json")
        added = {key: dumped.pop(key) for key in set(dumped) - set(old)}
        assert added == {key: type(event).model_fields[key].default for key in added}
        assert dumped == old


def test_specs_without_a_side_reproduce_the_stored_event_log() -> None:
    stored = json.loads((Path(__file__).parent / "fixtures" / "payloads_0_7_0.json").read_text())[
        "event_log"
    ]
    _assert_reproduces(_fixture_fight({}), stored)
    _assert_reproduces(_fixture_fight({"side": "encounter"}), stored)
