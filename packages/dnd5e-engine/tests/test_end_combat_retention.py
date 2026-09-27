"""An ended combat stays readable for a while, then leaves the registry.

``end_combat`` used to leave every ``_LiveCombat`` in the module registry for
the life of the process, so a host that opens and closes combats grew without
bound. The engine now keeps only the most recently ended combats: long enough
for the reads a host makes right after a close (a repeat ``end_combat``, a last
``drain_pending_events`` or ``narration_events`` drain, a final ``get_live``),
never forever.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from dnd5e_engine import (
    CombatHandle,
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    drain_pending_events,
    end_combat,
    get_live,
    narration_events,
    orchestrator,
    start_combat,
)
from dnd5e_engine.events import CombatEnded
from dnd5e_engine.orchestrator import UnknownHandleError
from dnd5e_engine.testing import registry, reset_registry


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    reset_registry()
    yield
    reset_registry()


def _start(session: str, seed: int = 1) -> CombatHandle:
    async def _run() -> CombatHandle:
        result = await start_combat(
            session_id=session,
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=10,
                    hp_max=10,
                    zone_id="0,0",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=10,
                    hp_max=10,
                    zone_id="2,0",
                )
            ],
            grid_scene=GridScene(width=5, height=5),
            rng_seed=seed,
        )
        return result.handle

    return asyncio.run(_run())


def _end(handle: CombatHandle) -> None:
    asyncio.run(end_combat(handle))


def test_an_ended_combat_stays_readable() -> None:
    handle = _start("retention-readable")
    first = asyncio.run(end_combat(handle))
    assert get_live(handle).ended is True
    assert drain_pending_events(handle)[-1] == CombatEnded(reason="forced")
    again = asyncio.run(end_combat(handle))
    assert (again.outcome, again.events) == (first.outcome, [])


def test_a_late_narration_consumer_still_terminates() -> None:
    handle = _start("retention-narration")
    _end(handle)

    async def _drain() -> list[str]:
        return [event.type async for event in narration_events(handle)]

    streamed = asyncio.run(_drain())
    assert streamed[-1] == "combat_ended"


def test_only_the_most_recently_ended_combats_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_ENDED_COMBATS_KEPT", 2)
    handles = [_start(f"retention-{n}") for n in range(3)]
    for handle in handles:
        _end(handle)
    with pytest.raises(UnknownHandleError):
        get_live(handles[0])
    with pytest.raises(UnknownHandleError):
        asyncio.run(end_combat(handles[0]))
    assert [get_live(h).ended for h in handles[1:]] == [True, True]
    assert len(registry) == 2


def test_a_live_combat_is_never_released(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_ENDED_COMBATS_KEPT", 1)
    running = _start("retention-running")
    for n in range(3):
        _end(_start(f"retention-closed-{n}"))
    assert get_live(running).ended is False
    assert len(registry) == 2


def test_a_reused_handle_id_keeps_its_new_combat(monkeypatch: pytest.MonkeyPatch) -> None:
    """``start_combat`` derives the handle id from the session and the seed, so
    a host that reuses both registers its next combat under the id an ended one
    still holds. Releasing the ended combat must not drop the new one."""
    monkeypatch.setattr(orchestrator, "_ENDED_COMBATS_KEPT", 1)
    first = _start("retention-reuse")
    _end(first)
    second = _start("retention-reuse")
    assert second == first
    _end(_start("retention-other"))
    assert get_live(second).ended is False


def test_many_closed_combats_leave_a_bounded_registry() -> None:
    for n in range(orchestrator._ENDED_COMBATS_KEPT + 10):
        _end(_start(f"retention-bulk-{n}"))
    assert len(registry) == orchestrator._ENDED_COMBATS_KEPT
