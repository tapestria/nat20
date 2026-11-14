"""Wall-segment index on ``GridTopology``: a step test and a sight test read
only the walls near the segment tested, with results identical to testing
every wall.

The two rules the walls serve, SRD 5.2:

* Playing on a Grid, "Corners": "Diagonal movement can't cross the corner of
  a wall, a large tree, or another terrain feature that fills its space."
* Areas of Effect, Point of Origin: "To block a line, an obstruction must
  provide Total Cover."

The index only narrows the candidate walls; the segment test still decides.
These tests compare every answer against a brute-force reference that loops
over all walls, and count segment tests to show the per-step cost no longer
grows with the number of walls.
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine import spatial
from dnd5e_engine.spatial import GridTopology, cell_id, parse_cell
from dnd5e_engine.specs import GridScene, WallSegment

SCENE_SEEDS = range(200)


def _ref_step_is_legal(g: GridTopology, scene: GridScene, a: str, b: str) -> bool:
    """The step test over every wall, no index."""
    ac, ar = parse_cell(a)
    bc, br = parse_cell(b)
    dc, dr = bc - ac, br - ar
    blocked = set(scene.blocked_cells)
    if dc != 0 and dr != 0 and (cell_id(ac + dc, ar) in blocked or cell_id(ac, ar + dr) in blocked):
        return False
    p1 = (ac + 0.5, ar + 0.5)
    p2 = (bc + 0.5, br + 0.5)
    return not any(
        spatial._segments_intersect(p1, p2, (w.x1, w.y1), (w.x2, w.y2)) for w in scene.wall_segments
    )


def _ref_line_of_sight(scene: GridScene, a: str, b: str) -> bool:
    """``has_line_of_sight`` over every wall, no index (blocked cells
    unchanged by the index, so the reference reuses the scene's)."""
    ac, ar = parse_cell(a)
    bc, br = parse_cell(b)
    blocked = set(scene.blocked_cells)
    for cid in spatial._bresenham_cells(ac, ar, bc, br):
        if cid != a and cid != b and cid in blocked:
            return False
    p1 = (ac + 0.5, ar + 0.5)
    p2 = (bc + 0.5, br + 0.5)
    return not any(
        spatial._segments_intersect(p1, p2, (w.x1, w.y1), (w.x2, w.y2)) for w in scene.wall_segments
    )


def _random_wall(rng: random.Random, width: int, height: int) -> WallSegment:
    kind = rng.choice(["grid", "grid", "diagonal", "float", "outside", "zero", "corner"])
    if kind == "grid":
        x = rng.randint(0, width)
        y = rng.randint(0, height)
        length = rng.randint(1, 6)
        if rng.random() < 0.5:
            return WallSegment(x1=x, y1=y, x2=x, y2=y + length)
        return WallSegment(x1=x, y1=y, x2=x + length, y2=y)
    if kind == "diagonal":
        x = rng.randint(0, width)
        y = rng.randint(0, height)
        d = rng.randint(1, 5)
        return WallSegment(x1=x, y1=y, x2=x + d, y2=y + rng.choice([-d, d]))
    if kind == "float":
        return WallSegment(
            x1=rng.uniform(-2, width + 2),
            y1=rng.uniform(-2, height + 2),
            x2=rng.uniform(-2, width + 2),
            y2=rng.uniform(-2, height + 2),
        )
    if kind == "outside":
        x = rng.uniform(width + 1, width + 50)
        y = rng.uniform(-50, -1)
        return WallSegment(x1=x, y1=y, x2=-x, y2=y - rng.uniform(0, 5))
    if kind == "zero":
        # A zero-length wall: a point, on a cell centre or a grid corner.
        x = rng.randint(0, width - 1) + rng.choice([0.0, 0.5])
        y = rng.randint(0, height - 1) + rng.choice([0.0, 0.5])
        return WallSegment(x1=x, y1=y, x2=x, y2=y)
    # A wall whose end only touches a cell corner, lying along a diagonal
    # step's centre line or grazing it.
    x = rng.randint(1, width - 1)
    y = rng.randint(1, height - 1)
    return WallSegment(x1=x, y1=y, x2=x + rng.choice([-1, 1]), y2=y + rng.choice([-1, 0, 1]))


def _random_scene(seed: int) -> GridScene:
    rng = random.Random(seed)
    width = rng.randint(2, 40)
    height = rng.randint(2, 40)
    walls = [_random_wall(rng, width, height) for _ in range(rng.randint(0, 25))]
    blocked = {
        cell_id(rng.randrange(width), rng.randrange(height)) for _ in range(rng.randint(0, 10))
    }
    return GridScene(width=width, height=height, wall_segments=walls, blocked_cells=sorted(blocked))


@pytest.mark.parametrize("seed", SCENE_SEEDS)
def test_index_answers_match_brute_force(seed: int) -> None:
    scene = _random_scene(seed)
    g = GridTopology(scene)
    rng = random.Random(seed + 10_000)
    cells = [cell_id(c, r) for c in range(scene.width) for r in range(scene.height)]
    for a in rng.sample(cells, min(len(cells), 40)):
        ac, ar = parse_cell(a)
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                b = cell_id(ac + dc, ar + dr)
                if (dc, dr) == (0, 0) or not g.is_valid_cell(b):
                    continue
                assert g._step_is_legal(a, b) == _ref_step_is_legal(g, scene, a, b), (
                    f"step {a}->{b} differs, scene seed {seed}"
                )
    for _ in range(300):
        a, b = rng.choice(cells), rng.choice(cells)
        assert g.has_line_of_sight(a, b) == _ref_line_of_sight(scene, a, b), (
            f"sight {a}->{b} differs, scene seed {seed}"
        )


def test_boundary_walls_and_corner_touches_match_brute_force() -> None:
    """Hand-built cases on the integer boundaries the bucketing widens over."""
    scene = GridScene(
        width=6,
        height=6,
        wall_segments=[
            WallSegment(x1=3, y1=0, x2=3, y2=6),  # full-height boundary wall
            WallSegment(x1=1, y1=1, x2=1, y2=1),  # point on a corner
            WallSegment(x1=1.5, y1=4.5, x2=1.5, y2=4.5),  # point on a centre
            WallSegment(x1=4, y1=4, x2=5, y2=5),  # along a diagonal step
            WallSegment(x1=5, y1=1, x2=6, y2=0),  # touches the grid corner
        ],
    )
    g = GridTopology(scene)
    cells = [cell_id(c, r) for c in range(6) for r in range(6)]
    for a in cells:
        for b in cells:
            assert g.has_line_of_sight(a, b) == _ref_line_of_sight(scene, a, b), (a, b)
            if g._chebyshev(a, b) == 1:
                assert g._step_is_legal(a, b) == _ref_step_is_legal(g, scene, a, b), (a, b)


def _dense_scene() -> GridScene:
    rng = random.Random(64)
    walls = []
    for _ in range(2000):
        x = rng.uniform(0, 64)
        y = rng.uniform(0, 64)
        walls.append(WallSegment(x1=x, y1=y, x2=x + rng.uniform(-0.4, 0.4), y2=y))
    return GridScene(width=64, height=64, wall_segments=walls)


def test_step_and_sight_tests_do_not_scale_with_wall_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = _dense_scene()
    g = GridTopology(scene)
    calls = {"intersect": 0, "steps": 0}
    real_intersect = spatial._segments_intersect
    real_step = GridTopology._step_is_legal

    def counting_intersect(*args):  # type: ignore[no-untyped-def]
        calls["intersect"] += 1
        return real_intersect(*args)

    def counting_step(self, a, b):  # type: ignore[no-untyped-def]
        calls["steps"] += 1
        return real_step(self, a, b)

    monkeypatch.setattr(spatial, "_segments_intersect", counting_intersect)
    monkeypatch.setattr(GridTopology, "_step_is_legal", counting_step)

    reached = g.reachable_cells("32,32", 30)
    path = g.shortest_path("0,0", "63,63")

    assert reached
    assert path
    steps = calls["steps"]
    # Each step test reads at most the walls bucketed in a 2x2 block of cells;
    # testing every wall would cost ``steps * 2000``.
    assert calls["intersect"] < steps * 16
    assert calls["intersect"] < steps * len(scene.wall_segments) // 50

    calls["intersect"] = 0
    for c in range(64):
        g.has_line_of_sight("0,0", cell_id(c, 63))
    # A sight line reads only the walls bucketed along it. Testing every
    # wall in order until one blocks costs over 10,000 segment tests on these
    # 64 lines; the index stays under a tenth of that.
    assert calls["intersect"] < 1_000
    assert calls["intersect"] < 64 * len(scene.wall_segments) // 4


def test_scene_without_walls_builds_empty_index() -> None:
    g = GridTopology(GridScene(width=5, height=5))
    assert g._wall_index == {}
    assert g._step_is_legal("0,0", "1,1")
    assert g.has_line_of_sight("0,0", "4,4")


def test_walls_entirely_off_the_grid_are_never_candidates() -> None:
    scene = GridScene(
        width=5, height=5, wall_segments=[WallSegment(x1=100, y1=100, x2=1e9, y2=1e9)]
    )
    g = GridTopology(scene)
    assert g._wall_index == {}
    assert list(g._walls_near((0.5, 0.5), (4.5, 4.5))) == []
    assert g.has_line_of_sight("0,0", "4,4")


def test_non_finite_wall_is_offered_to_every_query() -> None:
    scene = GridScene(
        width=4,
        height=4,
        wall_segments=[WallSegment(x1=2, y1=float("-inf"), x2=2, y2=float("inf"))],
    )
    g = GridTopology(scene)
    assert g._wall_index == {}
    assert list(g._walls_near((0.5, 0.5), (1.5, 0.5))) == list(scene.wall_segments)
    cells = [cell_id(c, r) for c in range(4) for r in range(4)]
    for a in cells:
        for b in cells:
            assert g.has_line_of_sight(a, b) == _ref_line_of_sight(scene, a, b), (a, b)
            if g._chebyshev(a, b) == 1:
                assert g._step_is_legal(a, b) == _ref_step_is_legal(g, scene, a, b), (a, b)


@pytest.mark.parametrize(
    "wall",
    [
        WallSegment(x1=-1e154, y1=-1e154, x2=1e154, y2=1e154),
        WallSegment(x1=-1e308, y1=1e308, x2=1e308, y2=-1e308),
        WallSegment(x1=2.5, y1=-1e300, x2=2.5, y2=1e300),
        WallSegment(x1=-1e200, y1=2.5, x2=1e200, y2=2.5),
    ],
)
def test_walls_with_huge_finite_coordinates_build_and_match_brute_force(
    wall: WallSegment,
) -> None:
    """A wall far larger than the grid, whose slab arithmetic could overflow,
    still builds and answers every step and sight test like the brute force."""
    scene = GridScene(width=5, height=5, wall_segments=[wall])
    g = GridTopology(scene)
    cells = [cell_id(c, r) for c in range(5) for r in range(5)]
    for a in cells:
        for b in cells:
            assert g.has_line_of_sight(a, b) == _ref_line_of_sight(scene, a, b), (a, b)
            if g._chebyshev(a, b) == 1:
                assert g._step_is_legal(a, b) == _ref_step_is_legal(g, scene, a, b), (a, b)
