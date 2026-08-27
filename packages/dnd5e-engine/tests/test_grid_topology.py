from itertools import pairwise

import pytest
from pydantic import ValidationError

from dnd5e_engine.spatial import GridTopology, cell_id, cover_bonus, parse_cell
from dnd5e_engine.specs import GridScene, WallSegment


def test_grid_scene_defaults_to_no_blocked_cells():
    scene = GridScene(width=10, height=10)
    assert scene.width == 10
    assert scene.height == 10
    assert scene.cell_size_ft == 5
    assert scene.blocked_cells == []
    assert scene.wall_segments == []
    assert scene.cover_cells == {}
    assert scene.difficult_terrain_cells == []


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


def test_has_line_of_sight_false_through_a_blocked_cell():
    # C16: "one obstruction model" — a blocked cell is Total Cover and blocks sight.
    g = _grid(blocked=["2,0"])
    assert g.has_line_of_sight("0,0", "4,0") is False
    assert g.has_line_of_sight("0,0", "1,0") is True  # obstacle not between
    assert g.has_line_of_sight("0,1", "4,1") is True  # parallel row is clear


def test_has_line_of_sight_false_when_wall_crosses_the_sightline():
    scene = GridScene(width=10, height=10, wall_segments=[WallSegment(x1=2, y1=0, x2=2, y2=10)])
    g = GridTopology(scene)
    assert g.has_line_of_sight("0,0", "4,0") is False  # crosses the x=2 wall


def test_has_line_of_sight_true_when_wall_does_not_cross():
    # Same wall, but both cells are on the SAME side of it — no crossing.
    scene = GridScene(width=10, height=10, wall_segments=[WallSegment(x1=2, y1=0, x2=2, y2=10)])
    g = GridTopology(scene)
    assert g.has_line_of_sight("0,0", "1,0") is True


def test_has_line_of_sight_accepts_wall_segments_as_plain_dicts():
    # The e2e catalog constructs wall_segments as dicts — pydantic must coerce.
    scene = GridScene(width=10, height=10, wall_segments=[{"x1": 2, "y1": 0, "x2": 2, "y2": 10}])
    g = GridTopology(scene)
    assert g.has_line_of_sight("0,0", "4,0") is False


def test_has_line_of_sight_false_out_of_bounds():
    g = _grid()
    assert g.has_line_of_sight("0,0", "99,99") is False


def test_wall_segment_rejects_extra_fields():
    with pytest.raises(ValidationError):
        WallSegment(x1=0, y1=0, x2=1, y2=1, z1=0)  # type: ignore[call-arg]


def test_cover_between_defaults_to_none():
    g = _grid()
    assert g.cover_between("0,0", "2,0") == "none"


def test_cover_between_returns_highest_degree_on_the_line():
    scene = GridScene(width=10, height=10, cover_cells={"1,0": "half"})
    g = GridTopology(scene)
    assert g.cover_between("0,0", "2,0") == "half"
    # No cover cell on this line at all.
    assert g.cover_between("0,5", "2,5") == "none"


def test_cover_between_ignores_cover_on_the_origin_cell():
    # A cover tag on the attacker's own cell never counts; the TARGET's own
    # cell DOES count (an object in its own space shields it) — see
    # tests/test_c16_spatial.py::test_cover_between_target_own_cover_cell_counts_but_origin_does_not.
    scene = GridScene(width=10, height=10, cover_cells={"0,0": "total", "2,0": "total"})
    g = GridTopology(scene)
    assert g.cover_between("0,0", "2,0") == "total"


def test_cover_between_total_beats_half_when_both_lie_on_the_line():
    scene = GridScene(
        width=10, height=10, cover_cells={"1,0": "half", "2,0": "total", "3,0": "half"}
    )
    g = GridTopology(scene)
    assert g.cover_between("0,0", "4,0") == "total"


def test_cover_bonus_mapping():
    assert cover_bonus("none") == 0
    assert cover_bonus("half") == 2
    assert cover_bonus("three_quarters") == 5
    assert cover_bonus("total") == 0


def test_edge_distance_doubles_for_difficult_terrain_destination():
    scene = GridScene(width=10, height=10, difficult_terrain_cells=["1,0"])
    g = GridTopology(scene)
    assert g.edge_distance("0,0", "1,0") == 10  # doubled entering difficult terrain
    assert g.edge_distance("1,0", "0,0") == 5  # normal cost leaving it


def test_edge_distance_flat_when_no_difficult_terrain():
    g = _grid()
    assert g.edge_distance("0,0", "1,0") == 5


def test_cells_in_template_sphere_trims_at_grid_boundary():
    # A 3x3 grid with a 20 ft (4-cell) radius sphere centered at the corner —
    # every cell in the tiny grid is included, none out of bounds.
    g = GridTopology(GridScene(width=3, height=3, cell_size_ft=5))
    cells = g.cells_in_template(origin="0,0", shape="sphere", size_ft=20)
    assert set(cells) == {f"{c},{r}" for c in range(3) for r in range(3)}


def test_cells_in_template_line_cardinal_direction():
    g = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    cells = g.cells_in_template(origin="10,10", shape="line", size_ft=15, direction=(1, 0))
    assert cells == ["10,10", "11,10", "12,10", "13,10"]  # origin + 3 steps east


def test_cells_in_template_line_diagonal_direction():
    g = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    cells = g.cells_in_template(origin="10,10", shape="line", size_ft=10, direction=(-1, -1))
    assert cells == ["10,10", "9,9", "8,8"]


def test_cells_in_template_cone_widens_with_distance():
    g = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    cells = set(g.cells_in_template(origin="10,10", shape="cone", size_ft=15, direction=(1, 0)))
    assert "10,10" in cells  # origin included
    assert "11,10" in cells  # 1 cell forward, on-axis
    assert "13,10" in cells  # 3 cells forward (radius), on-axis
    assert "13,13" in cells  # 3 forward, 3 lateral — right at the 45 deg edge
    assert "13,7" in cells  # symmetric on the other side
    assert "14,10" not in cells  # beyond the radius
    assert "5,10" not in cells  # behind the origin (wrong direction)
    assert "10,13" not in cells  # off-axis relative to an EAST-facing cone


def test_cells_in_template_cone_or_line_requires_direction():
    g = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    with pytest.raises(ValueError):
        g.cells_in_template(origin="10,10", shape="cone", size_ft=15)
    with pytest.raises(ValueError):
        g.cells_in_template(origin="10,10", shape="line", size_ft=15)


def test_cells_in_template_rejects_zero_direction():
    g = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    with pytest.raises(ValueError):
        g.cells_in_template(origin="10,10", shape="line", size_ft=15, direction=(0, 0))


def test_cells_in_template_out_of_bounds_origin_returns_empty():
    g = _grid()
    assert g.cells_in_template(origin="99,99", shape="sphere", size_ft=5) == []


def test_zone_graph_cover_between_always_none():
    from dnd5e_engine.orchestrator import _ZoneGraph
    from dnd5e_engine.specs import SceneTopology

    zg = _ZoneGraph(SceneTopology(zones=["a", "b"], edges=[]))
    assert zg.cover_between("a", "b") == "none"


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


def test_has_line_of_sight_blocked_when_wall_endpoint_grazes_the_sightline():
    # Regression pin for the endpoint-touch convention: a sightline that
    # passes exactly through a wall's ENDPOINT (T-touch, not a through-
    # crossing) counts as blocked — the intersection test's conservative
    # on-segment fallback. The diagonal "0,0" -> "2,2" sightline runs along
    # y = x and grazes the (1, 1) endpoint of a wall dropping to (1, 0).
    scene = GridScene(width=10, height=10, wall_segments=[WallSegment(x1=1, y1=1, x2=1, y2=0)])
    g = GridTopology(scene)
    assert g.has_line_of_sight("0,0", "2,2") is False
