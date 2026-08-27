"""C16 — pure GridTopology geometry units (obstruction model, legal steps,
cube/cylinder templates, push path, can_see). Every rule quotes the SRD 5.2
card in specs/rule-cards/c16-spatial-vision.md."""

from __future__ import annotations

from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import GridScene


def _grid(**kw) -> GridTopology:
    kw.setdefault("width", 10)
    kw.setdefault("height", 10)
    return GridTopology(GridScene(**kw))


# ── Task 1: obstruction model ────────────────────────────────────────────


def test_cover_between_blocked_cell_is_total_cover():
    g = _grid(blocked_cells=["2,0"])
    assert g.cover_between("0,0", "4,0") == "total"


def test_cover_between_occupied_cell_grants_half_cover():
    g = _grid()
    assert g.cover_between("0,0", "2,0") == "none"
    assert g.cover_between("0,0", "2,0", occupied_cells={"1,0"}) == "half"


def test_cover_between_occupied_endpoints_never_count():
    g = _grid()
    # attacker's and target's own cells are always "occupied" — never cover.
    assert g.cover_between("0,0", "2,0", occupied_cells={"0,0", "2,0"}) == "none"


def test_cover_between_target_own_cover_cell_counts_but_origin_does_not():
    # SRD 5.2 §Cover, Half: "an object that covers at least half of the
    # target" — an obstacle IN the target's own space shields it; one in the
    # attacker's space does not. Shared ruling with C22 Task 6 (C22-S03 tags
    # the target's own cell). Re-pins
    # tests/test_grid_topology.py::test_cover_between_ignores_cover_on_the_endpoints_themselves
    # to this rule (rename it ``..._ignores_cover_on_the_origin_cell``).
    g = _grid(cover_cells={"2,0": "half", "0,0": "three_quarters"})
    assert g.cover_between("0,0", "2,0") == "half"
    assert g.cover_between("2,0", "0,0") == "three_quarters"


def test_cover_between_highest_degree_wins_over_creature_half():
    g = _grid(cover_cells={"1,0": "three_quarters"})
    assert g.cover_between("0,0", "3,0", occupied_cells={"2,0"}) == "three_quarters"


def test_cover_between_accepts_any_collection_and_default_is_unchanged():
    g = _grid(cover_cells={"1,0": "half"})
    assert g.cover_between("0,0", "2,0") == "half"
    assert g.cover_between("0,0", "2,0", ["1,0"]) == "half"
    assert g.cover_between("0,0", "2,0", ()) == "half"


# ── Task 2: legal steps ──────────────────────────────────────────────────


def test_edge_distance_none_when_a_wall_crosses_the_step():
    # wall on the boundary between column 0 and column 1, rows 0..1
    g = _grid(wall_segments=[{"x1": 1, "y1": 0, "x2": 1, "y2": 2}])
    assert g.edge_distance("0,0", "1,0") is None
    assert g.edge_distance("0,0", "0,1") == 5
    assert g.is_adjacent("0,0", "1,0") is True  # geometry unchanged


def test_edge_distance_none_for_diagonal_cutting_a_blocked_corner():
    g = _grid(blocked_cells=["1,0"])
    assert g.edge_distance("0,0", "1,1") is None  # corner cell (1,0) blocked
    assert g.edge_distance("0,0", "0,1") == 5


def test_edge_distance_none_for_diagonal_touching_a_wall_endpoint():
    # C16-S05 part B geometry: wall (1,0)-(1,1) ends at grid corner (1,1).
    g = _grid(
        width=5,
        height=5,
        blocked_cells=["1,0"],
        wall_segments=[{"x1": 1, "y1": 0, "x2": 1, "y2": 1}],
    )
    assert g.edge_distance("0,0", "1,1") is None


def test_shortest_path_routes_around_walls_and_reports_unreachable():
    boxed = _grid(
        wall_segments=[
            {"x1": -2, "y1": -2, "x2": 3, "y2": -2},
            {"x1": -2, "y1": 3, "x2": 3, "y2": 3},
            {"x1": -2, "y1": -2, "x2": -2, "y2": 3},
            {"x1": 3, "y1": -2, "x2": 3, "y2": 3},
        ]
    )
    assert boxed.shortest_path("0,0", "2,2") == ["0,0", "1,1", "2,2"]
    assert boxed.shortest_path("0,0", "9,9") == []


def test_shortest_path_avoid_cells_are_never_entered():
    g = _grid()
    path = g.shortest_path("0,0", "3,0", avoid={"1,0", "1,1"})
    assert path[0] == "0,0"
    assert path[-1] == "3,0"
    assert "1,0" not in path
    assert "1,1" not in path
    assert g.shortest_path("0,0", "3,0", avoid={"3,0"}) == []


def test_shortest_path_neighbour_order_is_unchanged_without_obstacles():
    # Determinism guard: the BFS tie-break on main picks the straight row.
    g = _grid(difficult_terrain_cells=["2,0"])
    assert g.shortest_path("0,0", "3,0") == ["0,0", "1,0", "2,0", "3,0"]


# ── Task 3: cube / cylinder templates ────────────────────────────────────


def test_cell_size_ft_property():
    assert _grid().cell_size_ft == 5
    assert _grid(cell_size_ft=10).cell_size_ft == 10


def test_cells_in_template_cylinder_matches_sphere_and_includes_origin():
    g = _grid()
    assert g.cells_in_template("5,5", "cylinder", 10) == g.cells_in_template("5,5", "sphere", 10)
    assert "5,5" in g.cells_in_template("5,5", "cylinder", 10)


def test_cells_in_template_cube_cardinal_is_face_anchored_and_excludes_origin():
    g = _grid()
    cells = set(g.cells_in_template("0,5", "cube", 15, direction=(1, 0)))
    assert "0,5" not in cells
    assert cells == {cell_id(c, r) for c in (1, 2, 3) for r in (4, 5, 6)}


def test_cells_in_template_cube_clips_to_bounds():
    g = _grid()
    cells = set(g.cells_in_template("0,0", "cube", 15, direction=(1, 0)))
    assert cells == {cell_id(c, r) for c in (1, 2, 3) for r in (0, 1)}


def test_cells_in_template_cube_diagonal_is_the_corner_block():
    g = _grid()
    cells = set(g.cells_in_template("2,2", "cube", 10, direction=(-1, -1)))
    assert cells == {"0,0", "1,0", "0,1", "1,1"}


def test_cells_in_template_cube_requires_direction():
    import pytest

    with pytest.raises(ValueError):
        _grid().cells_in_template("0,0", "cube", 15)
