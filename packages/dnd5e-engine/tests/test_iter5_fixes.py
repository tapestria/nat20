"""Regression test — Codex Phase 6 review iter-5 fix.

Seeded statuses must populate live.active_conditions so the
orchestrator_bridge projection mirrors them into Redis on the next tick.
Without this, statuses land only on initiative[*].conditions and disappear
from the client-facing combat state.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.orchestrator import (
    _get_live,
    start_combat,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectDuration,
)
from tests.e2e.harness import adjacent_cells, grid_scene

_RANGER1_CELL, _RANGER2_CELL, _FOE_CELL = adjacent_cells(3)


def _party():
    return [
        PartyMemberSpec(
            entity_id="char:ranger1",
            name="Ranger One",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id=_RANGER1_CELL,
        ),
        PartyMemberSpec(
            entity_id="char:ranger2",
            name="Ranger Two",
            initiative=12,
            hp_current=20,
            hp_max=20,
            zone_id=_RANGER2_CELL,
        ),
    ]


def _encounter():
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=10,
            hp_current=50,
            hp_max=50,
            zone_id=_FOE_CELL,
        ),
    ]


def _topology():
    return grid_scene()


def test_seeded_status_populates_active_conditions():
    """Seeded Hold Person → live.active_conditions[target] contains 'paralyzed'.

    Without this, the orchestrator_bridge projection (which reads
    active_conditions to rebuild Redis conditions) would drop the
    seeded status from session state.
    """

    async def _run():
        hold = ActiveEffect(
            id="effect:hold_person",
            name="Hold Person",
            origin="cast:hold_person:char:caster",
            target_id="mon:foe",
            duration=ActiveEffectDuration(rounds=10),
            statuses={"paralyzed"},
            flags={"concentration": True},
        )
        return await start_combat(
            session_id="sess-seeded-status",
            party=_party(),
            encounter=_encounter(),
            grid_scene=_topology(),
            rng_seed=1,
            active_effects=(hold,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    assert "mon:foe" in live.active_conditions, (
        "seeded effect with statuses must populate live.active_conditions "
        "so the orchestrator_bridge projection sees it"
    )
    assert "paralyzed" in live.active_conditions["mon:foe"]
