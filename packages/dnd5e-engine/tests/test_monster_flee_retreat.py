"""Unit tests for the C10-S01 fleeing-retreat seam (``_plan_flee_destination``).

The planner is the inverse of ``advance_monster_turn``'s greedy CLOSING walk:
given the monster's zone, the threat's zone, and a movement budget, it returns
the reachable zone that MAXIMIZES topology distance from the threat (or ``None``
when nothing reachable improves on standing still). Exercised directly against
the concrete ``_ZoneGraph`` so the selection logic is pinned independent of the
full turn machinery.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _plan_flee_destination, _ZoneGraph
from dnd5e_engine.specs import SceneTopology, ZoneEdge


def _linear_graph() -> _ZoneGraph:
    # retreat --15-- foe --15-- pc
    return _ZoneGraph(
        SceneTopology(
            zones=["zone:retreat", "zone:foe", "zone:pc"],
            edges=[
                ZoneEdge(a="zone:retreat", b="zone:foe", distance_ft=15),
                ZoneEdge(a="zone:foe", b="zone:pc", distance_ft=15),
            ],
        )
    )


def test_flee_picks_zone_that_increases_distance_within_budget() -> None:
    graph = _linear_graph()
    # From foe (15 ft from pc), a 30 ft budget can reach retreat (30 ft from pc).
    dest = _plan_flee_destination(graph, "zone:foe", "zone:pc", movement_remaining=30)
    assert dest == "zone:retreat"


def test_flee_returns_none_when_budget_cannot_reach_a_farther_zone() -> None:
    graph = _linear_graph()
    # A 10 ft budget cannot pay the 15 ft edge to retreat — nothing reachable
    # strictly increases distance, so the monster holds its ground.
    assert _plan_flee_destination(graph, "zone:foe", "zone:pc", movement_remaining=10) is None


def test_flee_returns_none_when_already_farthest() -> None:
    graph = _linear_graph()
    # Standing in retreat (already the farthest zone), no move improves.
    assert _plan_flee_destination(graph, "zone:retreat", "zone:pc", movement_remaining=30) is None


def test_flee_prefers_the_farthest_reachable_of_several() -> None:
    # A star: center adjacent to near (10 ft) and far (10 ft); threat sits past
    # near. Fleeing must pick ``far`` (the zone that maximizes distance).
    graph = _ZoneGraph(
        SceneTopology(
            zones=["zone:far", "zone:center", "zone:near", "zone:threat"],
            edges=[
                ZoneEdge(a="zone:center", b="zone:far", distance_ft=10),
                ZoneEdge(a="zone:center", b="zone:near", distance_ft=10),
                ZoneEdge(a="zone:near", b="zone:threat", distance_ft=10),
            ],
        )
    )
    dest = _plan_flee_destination(graph, "zone:center", "zone:threat", movement_remaining=30)
    assert dest == "zone:far"
