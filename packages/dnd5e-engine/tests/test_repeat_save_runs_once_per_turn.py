"""F3a follow-up — the SRD end-of-turn repeat save is a ``turn_end`` hook.

SRD 5.2 §Hold Person / §Hold Monster / §Dominate Person: *"At the end of each
of its turns, the target repeats the save."* — **each of its turns**, once.

Before this fix ``_run_end_of_turn_saves`` was a hand-placed call at two sites
that sat ABOVE the ``if is_bonus_action:`` early return, so an actor who took a
bonus action rolled the repeat save, did *not* end its turn, and rolled it again
on its real Action: two escape attempts per turn, and (since F2c routed the save
through ``roll_d20_test``) one extra ``rng.randint(1, 20)`` draw. Registering it
as the ``engine:repeat-save`` ``turn_end`` hook makes the bonus-action path
unable to reach it at all, because it never reaches ``_end_turn_and_advance``.
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)

_HOLD_IDENTITY = ("char:hero", "effect:hold_person", "cast:hold-person:mon:foe")


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=40,
            hp_max=40,
            attack_bonus=5,
            strength=18,
            constitution=16,
            wisdom=10,
            character_level=5,
            class_slug="barbarian",
            zone_id="zone:start",
        )
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            zone_id="zone:start",
        )
    ]


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def _seed_pending_repeat_save(live) -> None:
    """One pending Hold Person repeat save on the hero, DC 30 so it never
    succeeds — the spec therefore stays pending and every attempt is visible
    in the stream as its own ``SaveRolled``."""
    live.repeat_save_on_turn_end[_HOLD_IDENTITY] = [
        {
            "ability": "wis",
            "dc": 30,
            "effect_name": "Hold Person",
            "condition": "paralyzed",
            "caster_id": "mon:foe",
        }
    ]


def _repeat_saves(live, since: int) -> list[object]:
    return [
        e
        for e in live.event_log[since:]
        if e.type == "save_rolled" and e.target_id == "char:hero" and e.dc == 30
    ]


def _run(session_id: str, intents: list[PlayerIntent]):
    async def _go():
        start = await start_combat(
            session_id=session_id,
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        _seed_pending_repeat_save(live)
        pre = len(live.event_log)
        for intent in intents:
            await submit_player_intent(start.handle, actor_id="char:hero", intent=intent)
        return live, pre

    return asyncio.run(_go())


def test_action_only_turn_rolls_exactly_one_repeat_save():
    """The baseline: one Action, one turn end, one repeat save."""
    live, pre = _run(
        "sess-repeat-save-action",
        [PlayerIntent(intent_type="attack", target_id="mon:foe")],
    )
    assert len(_repeat_saves(live, pre)) == 1


def test_bonus_action_then_action_rolls_exactly_one_repeat_save():
    """Rage (a Bonus Action) does not end the turn, so it must not trigger the
    repeat save; the follow-up Action does, exactly once."""
    live, pre = _run(
        "sess-repeat-save-bonus",
        [
            PlayerIntent(intent_type="use_feature", feature_id="rage"),
            PlayerIntent(intent_type="attack", target_id="mon:foe"),
        ],
    )
    assert len(_repeat_saves(live, pre)) == 1


def test_repeat_save_lands_inside_the_turn_end_phase():
    """Stream contract: the ``SaveRolled`` sits between ``TurnPhase(turn_end)``
    and ``TurnEnded``, so a host using the phase markers to attribute boundary
    effects attributes this one correctly."""
    live, pre = _run(
        "sess-repeat-save-phase",
        [PlayerIntent(intent_type="attack", target_id="mon:foe")],
    )
    tail = live.event_log[pre:]
    types = [e.type for e in tail]
    marker = next(
        i
        for i, e in enumerate(tail)
        if e.type == "turn_phase" and e.phase == "turn_end" and e.actor_id == "char:hero"
    )
    save = next(i for i, e in enumerate(tail) if e.type == "save_rolled" and e.dc == 30)
    ended = types.index("turn_ended")
    assert marker < save < ended
