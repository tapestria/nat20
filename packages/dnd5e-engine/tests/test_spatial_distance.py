"""C12 — ``SpatialTopology.distance_ft`` on both backends.

The distance seam the condition rows (SRD 5.2 Prone) read through
``ActivityResolutionContext.target_distance_ft``.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _ZoneGraph
from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import GridScene, SceneTopology, ZoneEdge


def test_grid_distance_is_chebyshev_times_cell_size() -> None:
    topo = GridTopology(GridScene(width=10, height=10))
    assert topo.distance_ft(cell_id(0, 0), cell_id(0, 0)) == 0
    assert topo.distance_ft(cell_id(0, 0), cell_id(1, 0)) == 5
    assert topo.distance_ft(cell_id(0, 0), cell_id(1, 1)) == 5  # diagonal is one step
    assert topo.distance_ft(cell_id(0, 0), cell_id(6, 0)) == 30
    assert topo.distance_ft(cell_id(0, 0), cell_id(99, 0)) is None  # out of bounds


def test_zone_graph_distance_is_the_shortest_path_sum() -> None:
    topo = _ZoneGraph(
        SceneTopology(
            zones=["a", "b", "c"],
            edges=[ZoneEdge(a="a", b="b", distance_ft=10), ZoneEdge(a="b", b="c", distance_ft=15)],
        )
    )
    assert topo.distance_ft("a", "a") == 0
    assert topo.distance_ft("a", "c") == 25
    assert topo.distance_ft("a", "zz") is None
