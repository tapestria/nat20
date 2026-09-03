"""C17 — spell slots & rests, orchestrator-level units: the second Pact Magic
pool, the reaction drain gates (slot availability, Counterspell range), upcast
target-count expansion (Magic Missile darts), the SpellCast event and the
in-combat ritual rejection. Every rule quotes the SRD 5.2 sentence it pins."""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.events import CastFailed, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live
from dnd5e_engine.spatial import cell_id as cell


@pytest.fixture(autouse=True)
def _bundled_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _run(coro):
    return asyncio.run(coro)


def _events(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


def _caster(
    entity_id="char:caster",
    *,
    spells,
    spell_slots=None,
    pact_slots=None,
    col=0,
    initiative=20,
    **kw,
):
    return PartyMemberSpec(
        entity_id=entity_id,
        name=entity_id,
        initiative=initiative,
        hp_current=30,
        hp_max=30,
        intelligence=16,
        class_slug="wizard",
        character_level=5,
        spells_known=list(spells),
        spell_slots=dict(spell_slots or {}),
        pact_slots=dict(pact_slots or {}),
        zone_id=cell(col, 0),
        **kw,
    )


def _foe(entity_id="mon:foe", *, col=3, hp=100, ac=1):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id,
        initiative=1,
        hp_current=hp,
        hp_max=hp,
        ac=ac,
        zone_id=cell(col, 0),
    )


async def _start(party, encounter, *, seed=1, width=10, session="c17"):
    start = await start_combat(
        session_id=session,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=GridScene(width=width, height=10, cell_size_ft=5),
        rng_seed=seed,
    )
    return start.handle, _get_live(start.handle)


# ── Task 3: two pools ────────────────────────────────────────────────────────


def test_pact_slots_reach_live_state_and_view():
    handle, live = _run(_start([_caster(spells=["magic-missile"], pact_slots={1: 2})], [_foe()]))
    assert live.pact_slots_by_entity["char:caster"] == {1: 2}
    assert get_live(handle).pact_slots_by_entity["char:caster"] == {1: 2}


def test_cast_draws_from_pact_pool_when_spellcasting_pool_lacks_the_level():
    """SRD Multiclassing Pact Magic: either pool casts either prepared spell (R3)."""

    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], spell_slots={2: 1}, pact_slots={1: 2})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert not _events(live, CastFailed)
    assert live.pact_slots_by_entity["char:caster"] == {1: 1}
    assert live.spell_slots_by_entity["char:caster"] == {2: 1}


def test_spellcasting_pool_is_consumed_before_pact_pool():
    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], spell_slots={1: 1}, pact_slots={1: 1})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert live.spell_slots_by_entity["char:caster"] == {1: 0}
    assert live.pact_slots_by_entity["char:caster"] == {1: 1}


def test_no_slot_in_either_pool_rejects_with_no_slot():
    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], pact_slots={1: 0})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert [e.reason for e in _events(live, CastFailed)] == ["no_slot"]
    assert not _events(live, DamageApplied)
