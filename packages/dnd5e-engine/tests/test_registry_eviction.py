"""_REGISTRY eviction on end_combat + bounded _ENDED idempotency cache.

Closes the BACKLOG entry: the registry retained every ended _LiveCombat
forever (~43KB RSS per stateless open/close cycle). end_combat now evicts
the live entry and parks a small outcome snapshot in a bounded FIFO cache
so the documented double-call idempotency survives eviction.
"""

from __future__ import annotations

import asyncio

import pytest

import dnd5e_engine.orchestrator as orch
from dnd5e_engine.orchestrator import (
    UnknownHandleError,
    end_combat,
    get_live,
    start_combat,
)
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)
from dnd5e_engine.testing import registry, reset_registry
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Aria",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:entrance",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:bbbbbbbbbbbb",
            entity_type="Monster",
            name="Goblin",
            initiative=12,
            hp_current=7,
            hp_max=7,
            zone_id="zone:entrance",
        ),
    ]


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:entrance", "zone:back"],
        edges=[ZoneEdge(a="zone:entrance", b="zone:back", distance_ft=30)],
    )


async def _open_combat():
    return await start_combat(
        session_id="sess",
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
    )


def test_end_combat_evicts_registry_entry():
    reset_registry()

    async def _run():
        start = await _open_combat()
        assert start.handle.handle_id in registry
        await end_combat(start.handle)
        return start.handle

    handle = asyncio.run(_run())
    assert handle.handle_id not in registry
    assert len(registry) == 0


def test_end_combat_double_call_idempotent_after_eviction():
    reset_registry()
    bless = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=5),
    )

    async def _run():
        start = await start_combat(
            session_id="sess",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )
        first = await end_combat(start.handle)
        second = await end_combat(start.handle)
        return first, second

    first, second = asyncio.run(_run())
    assert second.outcome == first.outcome
    assert second.events == []
    assert second.final_active_effects == first.final_active_effects
    assert any(eff.id == "effect:bless" for eff in second.final_active_effects)


def test_get_live_after_end_combat_raises_unknown_handle():
    reset_registry()

    async def _run():
        start = await _open_combat()
        await end_combat(start.handle)
        return start.handle

    handle = asyncio.run(_run())
    with pytest.raises(UnknownHandleError):
        get_live(handle)


def test_ended_cache_is_bounded_fifo(monkeypatch):
    reset_registry()
    monkeypatch.setattr(orch, "_ENDED_CAP", 2)

    async def _run():
        handles = []
        for seed in (1, 2, 3):  # distinct seeds -> distinct handle ids
            start = await start_combat(
                session_id="sess",
                party=_party(),
                encounter=_encounter(),
                scene_zones=_topology(),
                rng_seed=seed,
            )
            await end_combat(start.handle)
            handles.append(start.handle)
        return handles

    oldest, middle, newest = asyncio.run(_run())

    # Newest two still answer idempotently; the oldest fell off the cache.
    async def _reend(h):
        return await end_combat(h)

    assert asyncio.run(_reend(newest)).events == []
    assert asyncio.run(_reend(middle)).events == []
    with pytest.raises(UnknownHandleError):
        asyncio.run(_reend(oldest))


def test_sequential_open_close_cycles_leave_registry_empty():
    reset_registry()

    async def _run():
        for _ in range(50):
            start = await _open_combat()
            await end_combat(start.handle)

    asyncio.run(_run())
    assert len(registry) == 0


def test_reused_handle_id_prefers_new_live_combat_over_stale_snapshot():
    """Handle ids are deterministic (combat:{session}:{seed}); re-opening the
    same pair after an end must resolve to the NEW live combat."""
    reset_registry()

    async def _run():
        first = await _open_combat()
        first_end = await end_combat(first.handle)
        second = await _open_combat()  # same session + seed -> same handle_id
        assert second.handle.handle_id == first.handle.handle_id
        live_view = get_live(second.handle)  # must not raise: combat 2 is live
        second_end = await end_combat(second.handle)
        return first_end, second_end, live_view  # first_end pinned live above

    _first_end, second_end, live_view = asyncio.run(_run())
    # The second combat really ran and ended (fresh close events, not the
    # cached empty-events snapshot of the first).
    assert second_end.events != []
    assert live_view is not None
