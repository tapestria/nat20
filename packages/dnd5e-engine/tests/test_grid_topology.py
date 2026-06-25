from itertools import pairwise

import pytest
from pydantic import ValidationError

from dnd5e_engine.spatial import GridTopology, cell_id, parse_cell
from dnd5e_engine.specs import GridScene


def test_grid_scene_defaults_to_no_blocked_cells():
    scene = GridScene(width=10, height=10)
    assert scene.width == 10
    assert scene.height == 10
    assert scene.cell_size_ft == 5
    assert scene.blocked_cells == []


def test_grid_scene_rejects_extra_fields():
    with pytest.raises(ValidationError):
        GridScene(width=10, height=10, zones=["a"])  # type: ignore[call-arg]


def test_cell_id_roundtrip():
    assert cell_id(3, 4) == "3,4"
    assert parse_cell("3,4") == (3, 4)


def test_parse_cell_rejects_malformed():
    with pytest.raises(ValueError):
        parse_cell("3-4")
    with pytest.raises(ValueError):
        parse_cell("x,y")


def _grid(width=10, height=10, blocked=None):
    return GridTopology(GridScene(width=width, height=height, blocked_cells=blocked or []))


def test_adjacent_includes_diagonals():
    g = _grid()
    assert g.is_adjacent("5,5", "5,6") is True  # orthogonal
    assert g.is_adjacent("5,5", "6,6") is True  # diagonal
    assert g.is_adjacent("5,5", "5,5") is False  # self
    assert g.is_adjacent("5,5", "5,7") is False  # two away


def test_adjacent_false_into_blocked_or_out_of_bounds():
    g = _grid(blocked=["5,6"])
    assert g.is_adjacent("5,5", "5,6") is False  # into blocked
    assert g.is_adjacent("0,0", "-1,0") is False  # out of bounds


def test_edge_distance_is_cell_size_when_adjacent():
    g = _grid()
    assert g.edge_distance("5,5", "6,6") == 5
    assert g.edge_distance("5,5", "5,7") is None


def test_within_range_uses_chebyshev_feet():
    g = _grid()
    assert g.within_range("0,0", "0,0", 0) is True  # same cell
    assert g.within_range("0,0", "1,1", 5) is True  # 1 cell = 5ft
    assert g.within_range("0,0", "3,0", 15) is True  # 3 cells = 15ft
    assert g.within_range("0,0", "4,0", 15) is False  # 4 cells = 20ft > 15


def test_has_line_of_sight_true_v1():
    g = _grid(blocked=["1,0"])
    assert g.has_line_of_sight("0,0", "2,0") is True  # walls don't block sight in v1


def test_is_valid_cell():
    g = _grid(blocked=["2,2"])
    assert g.is_valid_cell("0,0") is True
    assert g.is_valid_cell("2,2") is False  # blocked
    assert g.is_valid_cell("99,99") is False  # out of bounds


def test_shortest_path_degenerate_and_unknown():
    g = _grid()
    assert g.shortest_path("2,2", "2,2") == ["2,2"]
    assert g.shortest_path("2,2", "99,99") == []  # out of bounds endpoint


def test_shortest_path_consecutive_pairs_are_adjacent():
    g = _grid()
    path = g.shortest_path("0,0", "3,0")
    assert path[0] == "0,0"
    assert path[-1] == "3,0"
    for x, y in pairwise(path):
        assert g.is_adjacent(x, y), f"{x}->{y} not adjacent"
    assert len(path) == 4  # chebyshev-optimal: 3 steps


def test_shortest_path_routes_around_blocked():
    # Block the whole column x=1 from row 0..2 except leave (1,3) open.
    g = _grid(blocked=["1,0", "1,1", "1,2"])
    path = g.shortest_path("0,0", "2,0")
    assert path
    assert path[0] == "0,0"
    assert path[-1] == "2,0"
    for c in path:
        assert c not in {"1,0", "1,1", "1,2"}
    for x, y in pairwise(path):
        assert g.is_adjacent(x, y)


def test_zone_graph_satisfies_spatial_topology():
    from dnd5e_engine.orchestrator import _ZoneGraph
    from dnd5e_engine.spatial import SpatialTopology
    from dnd5e_engine.specs import SceneTopology

    zg = _ZoneGraph(SceneTopology(zones=["a", "b"], edges=[]))
    assert isinstance(zg, SpatialTopology)  # runtime_checkable structural check


def test_grid_topology_satisfies_spatial_topology():
    from dnd5e_engine.spatial import SpatialTopology

    assert isinstance(_grid(), SpatialTopology)


def test_grid_types_exported_from_package_root():
    import dnd5e_engine

    assert hasattr(dnd5e_engine, "GridScene")
    assert hasattr(dnd5e_engine, "cell_id")
    assert hasattr(dnd5e_engine, "parse_cell")
