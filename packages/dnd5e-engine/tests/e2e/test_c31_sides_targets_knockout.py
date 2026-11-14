"""Combat sides, a host-chosen foe target and knocking out a creature.

One scripted fight on a 10x10 ``GridScene``: two characters and a hired
sword seated with ``EncounterMemberSpec(side="party")`` against three foes.
The host names the creature every living foe attacks, the foes kill the
hired sword, the characters kill two foes and knock the last one out.
Every d20 shows 10 (no natural 20); every other die draws from seed 31.

SRD 5.2 Summon Dragon: "The creature is an ally to you and your allies."

SRD 5.2 Monster Death: "A monster dies the instant it drops to 0 Hit Points,
although a Game Master can ignore this rule for an individual monster and
treat it like a character."

SRD 5.2 Rules Glossary, Knocking Out a Creature: "When you would reduce a
creature to 0 Hit Points with a melee attack, you can instead reduce the
creature to 1 Hit Point. The creature then has the Unconscious condition and
starts a Short Rest. The creature remains Unconscious until it regains any
Hit Points or until someone uses an action to administer first aid to it,
which requires a successful DC 10 Wisdom (Medicine) check."
"""

from __future__ import annotations

import random
from typing import Any

from dnd5e_engine import (
    CombatHandle,
    KnockOutRecord,
    PlayerIntent,
    end_combat,
    get_live,
)
from dnd5e_engine.events import (
    AttackRolled,
    ConditionApplied,
    Death,
    DeathSaveStarted,
    IntentSubmitted,
    KnockedOut,
    Unconscious,
)
from dnd5e_engine.orchestrator import (
    _current_actor,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.testing import rng_factory
from tests.e2e.harness import cell, events_of, grid_scene, run_async

HERO = "char:hero"
SCOUT = "char:scout"
ALLY = "npc:sellsword"
FOE_1, FOE_2, FOE_3 = "mon:bandit-1", "mon:bandit-2", "mon:bandit-3"


class _D20Shows10(random.Random):
    """Every d20 shows 10; every other die draws as seeded."""

    def randint(self, a: int, b: int) -> int:
        return 10 if (a, b) == (1, 20) else super().randint(a, b)


def _character(entity_id: str, **fields: Any) -> PartyMemberSpec:
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("char:").title(),
        "hp_max": 40,
    }
    return PartyMemberSpec(**(base | fields))


def _bandit(entity_id: str, **fields: Any) -> EncounterMemberSpec:
    """A template-less 1-HP foe (of 1, so it never flees), AC 1."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "hp_current": 1,
        "hp_max": 1,
        "ac": 1,
    }
    return EncounterMemberSpec(**(base | fields))


def _start() -> CombatHandle:
    """Initiative: hero 20, scout 18, sellsword 16, bandits 14, 12, 10.

              col 0       col 1   col 2
    row 0     bandit 1    .       .
    row 1     sellsword   hero    bandit 2
    row 2     .           scout   bandit 3

    The hero (1,1) stands beside every bandit; the sellsword (0,1) beside
    bandit 1; the scout (1,2) beside bandit 3.
    """
    party = [
        _character(
            HERO,
            class_slug="fighter",
            character_level=5,
            initiative=20,
            hp_current=40,
            zone_id=cell(1, 1),
        ),
        _character(SCOUT, initiative=18, hp_current=20, zone_id=cell(1, 2)),
    ]
    encounter = [
        EncounterMemberSpec(
            entity_id=ALLY,
            entity_type="NPC",
            name="Sellsword",
            side="party",
            initiative=16,
            hp_current=1,
            hp_max=1,
            ac=1,
            zone_id=cell(0, 1),
        ),
        _bandit(FOE_1, initiative=14, xp_value=100, zone_id=cell(0, 0)),
        _bandit(FOE_2, initiative=12, xp_value=200, zone_id=cell(2, 1)),
        _bandit(FOE_3, initiative=10, xp_value=50, zone_id=cell(2, 2)),
    ]

    async def _inner() -> CombatHandle:
        result = await start_combat(
            session_id="sides-targets-knockout",
            party=party,
            encounter=encounter,
            grid_scene=grid_scene(),
            rng_seed=31,
        )
        return result.handle

    with rng_factory(_D20Shows10):
        handle: CombatHandle = run_async(_inner())
    return handle


def _act(handle: CombatHandle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _foe_turn(handle: CombatHandle, actor_id: str, **kwargs: Any) -> None:
    assert _current_actor(_get_live(handle)).entity_id == actor_id
    run_async(advance_monster_turn(handle, **kwargs))


def _attacks_by(live: Any, attacker_id: str) -> list[str]:
    return [a.target_id for a in events_of(live, AttackRolled) if a.attacker_id == attacker_id]


def test_allies_host_targets_and_a_knock_out_end_in_victory() -> None:
    handle = _start()
    live = _get_live(handle)
    assert live.party_ids == {HERO, SCOUT, ALLY}
    assert live.encounter_ids == {FOE_1, FOE_2, FOE_3}

    # Round 1. The hero kills bandit 2; the fighter's second attack is passed up.
    _act(handle, HERO, intent_type="attack", weapon_id="longsword", target_id=FOE_2)
    _act(handle, HERO, intent_type="pass")
    _act(handle, SCOUT, intent_type="pass")
    _act(handle, ALLY, intent_type="pass")  # a party-side member takes a command

    # The host sends bandit 1 at the sellsword and bandit 3 past the wounded
    # scout (the engine's own lowest-HP pick) at the hero.
    _foe_turn(handle, FOE_1, target_id=ALLY)
    _foe_turn(handle, FOE_2)  # dead: its turn passes
    _foe_turn(handle, FOE_3, target_id=HERO)
    assert _attacks_by(live, FOE_1) == [ALLY]
    assert _attacks_by(live, FOE_3) == [HERO]
    assert [e.target_id for e in events_of(live, IntentSubmitted) if e.actor_id == FOE_3] == [HERO]

    # The sellsword dies as a monster does: no Unconscious, no death saves.
    assert [(d.target_id, d.reason) for d in events_of(live, Death)] == [
        (FOE_2, "damage"),
        (ALLY, "damage"),
    ]
    assert events_of(live, Unconscious) == []
    assert events_of(live, DeathSaveStarted) == []
    assert [d.target_id for d in get_live(handle).deaths] == [FOE_2, ALLY]

    # Round 2. The hero kills bandit 1; the scout pulls the blow on bandit 3.
    _act(handle, HERO, intent_type="attack", weapon_id="longsword", target_id=FOE_1)
    _act(handle, HERO, intent_type="pass")
    _act(
        handle,
        SCOUT,
        intent_type="attack",
        weapon_id="longsword",
        target_id=FOE_3,
        knock_out=True,
    )
    assert events_of(live, KnockedOut) == [KnockedOut(target_id=FOE_3, attacker_id=SCOUT)]
    assert ConditionApplied(target_id=FOE_3, condition="unconscious") in live.event_log
    assert live.tracked_hp[FOE_3] == 1
    assert get_live(handle).knocked_out_ids == {FOE_3}

    outcome = run_async(end_combat(handle)).outcome
    assert outcome.ended_reason == "victory"
    deaths = {d.target_id: d for d in outcome.deaths}
    assert set(deaths) == {FOE_1, FOE_2, ALLY}
    assert (deaths[ALLY].target_kind, deaths[ALLY].killer_id) == ("npc", FOE_1)
    assert deaths[FOE_2].killer_id == HERO
    assert deaths[FOE_1].killer_id == HERO
    assert outcome.knock_outs == [
        KnockOutRecord(target_id=FOE_3, target_kind="monster", attacker_id=SCOUT)
    ]
    # Bandits 1 and 2 are dead (300 XP) and bandit 3 is knocked out (50 XP):
    # "XP is awarded for defeating the monster in combat or otherwise
    # neutralizing it." The sellsword takes no share.
    assert outcome.xp_awarded == {HERO: 175, SCOUT: 175}
