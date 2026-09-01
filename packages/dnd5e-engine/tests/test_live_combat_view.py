"""Plan 4 — public LiveCombatView read-model returned by get_live.

The host consumes a stable projection of live combat state, never the
private _LiveCombat. This locks field coverage and snapshot isolation.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import LiveCombatView, get_live
from dnd5e_engine.orchestrator import _get_live, _LiveCombat, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Hero",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:111111111111",
            entity_type="Monster",
            name="Bandit",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _start():
    return asyncio.run(
        start_combat(
            session_id="sess-view",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:start"], edges=[]),
            rng_seed=0,
        )
    )


def test_get_live_returns_view_with_full_field_coverage():
    handle = _start().handle
    view = get_live(handle)
    assert isinstance(view, LiveCombatView)
    assert {c.entity_id for c in view.initiative} == {
        "char:aaaaaaaaaaaa",
        "mon:111111111111",
    }
    assert "char:aaaaaaaaaaaa" in view.party_ids
    assert "mon:111111111111" in view.encounter_ids
    assert view.dead_ids == set()
    assert view.round_number == 1
    assert view.ended is False
    assert view.final_outcome is None
    # every documented field is present
    for field in (
        "tracked_hp",
        "tracked_temp_hp",
        "active_conditions",
        "actor_zone",
        "spell_slots_by_entity",
        "spells_known_by_entity",
        "custom_counters_by_entity",
        "current_turn_index",
    ):
        assert hasattr(view, field)


def test_view_is_a_snapshot_not_a_live_handle():
    handle = _start().handle
    view = get_live(handle)
    live = _get_live(handle)
    # mutate live engine state after the snapshot is taken
    live.dead_ids.add("mon:111111111111")
    live.active_conditions.setdefault("char:aaaaaaaaaaaa", set()).add("blessed")
    # the snapshot does not observe later mutations (outer + inner copies)
    assert "mon:111111111111" not in view.dead_ids
    assert "blessed" not in view.active_conditions.get("char:aaaaaaaaaaaa", set())


def test_custom_counters_snapshot_is_three_levels_deep():
    party = [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Hero",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
            custom_counters={"item_use:wand": {"spent": 1}},
        ),
    ]
    handle = asyncio.run(
        start_combat(
            session_id="sess-view-counters",
            party=party,
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:start"], edges=[]),
            rng_seed=0,
        )
    ).handle
    view = get_live(handle)
    live = _get_live(handle)
    live.custom_counters_by_entity["char:aaaaaaaaaaaa"]["item_use:wand"]["spent"] = 99
    assert view.custom_counters_by_entity["char:aaaaaaaaaaaa"]["item_use:wand"]["spent"] == 1


def _make_live() -> _LiveCombat:
    """Construct a minimal _LiveCombat for testing view projections."""
    import random

    from dnd5e_engine.orchestrator import _LiveCombat, _ZoneGraph
    from dnd5e_engine.specs import SceneTopology

    return _LiveCombat(
        handle_id="test:handle",
        session_id="test:session",
        initiative=[],
        party_ids=set(),
        encounter_ids=set(),
        topology=_ZoneGraph(SceneTopology(zones=["zone:test"], edges=[])),
        rng=random.Random(0),
        event_queue=asyncio.Queue(),
        scene_location_id="scene:test",
    )


def test_from_live_projects_concentration_chain_as_a_copy() -> None:
    live = _make_live()
    live.concentration_chain["char:a"] = [("char:b", "effect:bless", "cast:bless:char:a")]
    view = LiveCombatView.from_live(live)
    assert view.concentration_chain == {"char:a": [("char:b", "effect:bless", "cast:bless:char:a")]}
    # Snapshot semantics: mutating the view must not touch live state.
    view.concentration_chain["char:a"].append(("x", "y", "z"))
    assert len(live.concentration_chain["char:a"]) == 1
