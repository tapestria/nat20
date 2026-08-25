"""Spatial backends for combat resolution.

The engine resolves all positional reasoning through the ``SpatialTopology``
Protocol — a combatant's position is an opaque string handle, and the backend
answers adjacency / distance / range / pathing over it. Two backends exist:
the zone graph (``_ZoneGraph`` in ``orchestrator.py``) and the grid
(``GridTopology`` here). Call sites never branch on which backend is live.
"""

from __future__ import annotations

from collections import deque
from typing import Literal, Protocol, runtime_checkable

from dnd5e_engine.specs import GridScene, WallSegment

CoverDegree = Literal["none", "half", "three_quarters", "total"]

# Ranking for "does this cell grant MORE cover than the best seen so far" —
# SRD 5.2 §Cover: none < half < three-quarters < total.
_COVER_RANK: dict[str, int] = {"none": 0, "half": 1, "three_quarters": 2, "total": 3}

# SRD 5.2 §Cover: "A target with half cover has a +2 bonus to AC and
# Dexterity saving throws... three-quarters cover has a +5 bonus...". Single
# source of truth for both consumers (``activities/attack.py``'s AC fold and
# ``activities/save_primitive.py``'s Dexterity-save fold) so the two numbers
# never drift. "total" never reaches either comparison in practice
# (``_in_range_with_los`` rejects targeting before an activity resolves) but
# maps to 0 defensively rather than raising.
_COVER_BONUS: dict[str, int] = {"none": 0, "half": 2, "three_quarters": 5, "total": 0}


def cover_bonus(degree: str) -> int:
    """SRD 5.2 §Cover — the flat AC / Dexterity-save bonus a cover degree grants."""
    return _COVER_BONUS.get(degree, 0)


def cell_id(col: int, row: int) -> str:
    """Encode a grid coordinate as the opaque position handle ``"col,row"``."""
    return f"{col},{row}"


def parse_cell(cid: str) -> tuple[int, int]:
    """Decode a ``"col,row"`` handle. Raises ValueError on malformed input."""
    col_s, _, row_s = cid.partition(",")
    if not col_s or not row_s or "," in row_s:
        raise ValueError(f"malformed cell id: {cid!r}")
    return int(col_s), int(row_s)


def _orientation(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> int:
    """Sign of the cross product ``(b-a) x (c-b)`` — the turn direction a->b->c.

    Standard building block for a robust segment-segment intersection test
    (CCW / orientation method): 0 collinear, >0 counter-clockwise, <0 clockwise.
    """
    val = (by - ay) * (cx - bx) - (bx - ax) * (cy - by)
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0


def _on_segment(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
    """True iff collinear point ``c`` lies within the bounding box of segment a-b."""
    return min(ax, bx) <= cx <= max(ax, bx) and min(ay, by) <= cy <= max(ay, by)


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    """True iff segment ``p1-p2`` properly or collinearly intersects ``p3-p4``.

    The classic orientation-based test: the two segments intersect iff each
    straddles the other's line (general case), OR an endpoint of one lies on
    the other segment (the collinear/touching edge case).
    """
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    dx, dy = p4
    o1 = _orientation(ax, ay, bx, by, cx, cy)
    o2 = _orientation(ax, ay, bx, by, dx, dy)
    o3 = _orientation(cx, cy, dx, dy, ax, ay)
    o4 = _orientation(cx, cy, dx, dy, bx, by)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(ax, ay, bx, by, cx, cy):
        return True
    if o2 == 0 and _on_segment(ax, ay, bx, by, dx, dy):
        return True
    if o3 == 0 and _on_segment(cx, cy, dx, dy, ax, ay):
        return True
    return bool(o4 == 0 and _on_segment(cx, cy, dx, dy, bx, by))


def _bresenham_cells(x0: int, y0: int, x1: int, y1: int) -> list[str]:
    """Cell ids on the Bresenham line from ``(x0,y0)`` to ``(x1,y1)``, inclusive.

    Used for ``cover_between``'s "does an obstruction lie on the straight
    line between these two cells" query — a cell-traversal walk, distinct
    from the continuous-geometry segment test ``has_line_of_sight`` uses for
    wall edges.
    """
    cells = [cell_id(x0, y0)]
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while (x, y) != (x1, y1):
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
        cells.append(cell_id(x, y))
    return cells


@runtime_checkable
class SpatialTopology(Protocol):
    """The positional seam every combat resolves over.

    Position handles are opaque strings (zone ids for the graph backend,
    ``"col,row"`` cell ids for the grid backend).
    """

    def is_adjacent(self, a: str, b: str) -> bool: ...

    def edge_distance(self, a: str, b: str) -> int | None: ...

    def within_range(self, caster: str, target: str, range_ft: int) -> bool: ...

    def shortest_path(self, a: str, b: str) -> list[str]: ...

    def has_line_of_sight(self, a: str, b: str) -> bool: ...

    def cover_between(self, a: str, b: str) -> CoverDegree: ...


class GridTopology:
    """Chebyshev (8-direction, one cell = ``cell_size_ft``) grid backend.

    Position handles are ``"col,row"`` cell ids. ``blocked_cells`` are
    impassable squares — movement may not enter them and paths route around
    them. ``wall_segments`` block line of sight, ``cover_cells`` grant
    half/three-quarters/total cover, and ``difficult_terrain_cells`` double
    entry cost — see ``docs/dev/spatial-geometry.md`` for the geometry design.
    """

    def __init__(self, scene: GridScene) -> None:
        self._width = scene.width
        self._height = scene.height
        self._cell_size_ft = scene.cell_size_ft
        self._blocked: set[str] = set(scene.blocked_cells)
        self._walls: list[WallSegment] = list(scene.wall_segments)
        self._cover_cells: dict[str, str] = dict(scene.cover_cells)
        self._difficult: set[str] = set(scene.difficult_terrain_cells)

    def _in_bounds(self, cid: str) -> bool:
        try:
            col, row = parse_cell(cid)
        except ValueError:
            return False
        return 0 <= col < self._width and 0 <= row < self._height

    def _chebyshev(self, a: str, b: str) -> int | None:
        if not self._in_bounds(a) or not self._in_bounds(b):
            return None
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        return max(abs(ac - bc), abs(ar - br))

    def is_adjacent(self, a: str, b: str) -> bool:
        if a == b or b in self._blocked:
            return False
        dist = self._chebyshev(a, b)
        return dist == 1

    def edge_distance(self, a: str, b: str) -> int | None:
        """One step's movement cost, in feet, entering ``b`` from adjacent ``a``.

        SRD 5.2 §Difficult Terrain: entering a difficult-terrain cell costs
        double. The cost keys off the cell being ENTERED (``b``), not ``a`` —
        "every foot of movement IN Difficult Terrain."
        """
        if not self.is_adjacent(a, b):
            return None
        cost = self._cell_size_ft
        if b in self._difficult:
            cost *= 2
        return cost

    def within_range(self, caster: str, target: str, range_ft: int) -> bool:
        dist = self._chebyshev(caster, target)
        if dist is None:
            return False
        return dist * self._cell_size_ft <= range_ft

    def has_line_of_sight(self, a: str, b: str) -> bool:
        """SRD 5.2 §Areas of Effect — a wall blocks sight between two cells.

        Traces the straight segment between ``a``'s and ``b``'s CELL-CENTER
        points against every ``wall_segments`` entry (grid-corner endpoints);
        any proper intersection blocks the line. No walls ⇒ always True
        (preserves prior behavior byte-for-byte).
        """
        if not self._in_bounds(a) or not self._in_bounds(b):
            return False
        if not self._walls:
            return True
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        p1 = (ac + 0.5, ar + 0.5)
        p2 = (bc + 0.5, br + 0.5)
        for wall in self._walls:
            p3 = (wall.x1, wall.y1)
            p4 = (wall.x2, wall.y2)
            if _segments_intersect(p1, p2, p3, p4):
                return False
        return True

    def cover_between(self, a: str, b: str) -> CoverDegree:
        """SRD 5.2 §Cover — the highest cover degree an obstruction cell
        lying on the straight line between ``a`` and ``b`` grants.

        Walks the Bresenham line of cells from ``a`` to ``b`` (excluding both
        endpoints — a combatant's own/target's cell never grants itself
        cover) and returns the HIGHEST tagged ``cover_cells`` degree among
        them (``none < half < three_quarters < total``). No cover geometry ⇒
        always ``"none"`` (preserves prior no-cover behavior).
        """
        if not self._cover_cells or not self._in_bounds(a) or not self._in_bounds(b):
            return "none"
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        best: CoverDegree = "none"
        for cid in _bresenham_cells(ac, ar, bc, br):
            if cid in (a, b):
                continue
            degree = self._cover_cells.get(cid)
            if degree is not None and _COVER_RANK[degree] > _COVER_RANK[best]:
                best = degree  # type: ignore[assignment]
        return best

    def is_valid_cell(self, cid: str) -> bool:
        """True iff ``cid`` is in bounds and not impassable — a legal occupancy."""
        return self._in_bounds(cid) and cid not in self._blocked

    def cells_in_template(
        self,
        origin: str,
        shape: Literal["sphere", "cone", "line"],
        size_ft: int,
        *,
        direction: tuple[int, int] | None = None,
    ) -> list[str]:
        """SRD 5.2 §Areas of Effect — the in-bounds cell set for a template.

        Chebyshev metric throughout (maintainer decision, catalog —
        settled, not relitigated): ``radius_cells = size_ft // cell_size_ft``.

        * ``"sphere"``: every cell with ``max(|dx|, |dy|) <= radius_cells``
          from ``origin`` (origin included — SRD: "a Sphere's point of origin
          is included in the Sphere's area of effect").
        * ``"line"``: requires ``direction`` (a nonzero grid-offset vector,
          normalized to one of the 8 unit grid directions); the
          ``radius_cells + 1`` cells stepping from the origin along that
          direction, origin included.
        * ``"cone"``: requires ``direction``; a cell at offset ``(dx, dy)``
          from the origin is included iff its projection onto the direction
          (``forward``) is in ``[0, radius_cells]`` and its perpendicular
          offset (``lateral``) does not exceed ``forward`` — a widening 45°
          triangle from the origin. See ``docs/dev/spatial-geometry.md`` for
          the full rationale (an engine convention, not literal SRD prose
          geometry — squares have no single canonical cone rasterization).

        See ``docs/dev/spatial-geometry.md``. Not part of the
        ``SpatialTopology`` Protocol — grid-only (the zone-graph backend has
        no cell coordinates to enumerate a template over).
        """
        if not self._in_bounds(origin):
            return []
        radius_cells = size_ft // self._cell_size_ft
        oc, orow = parse_cell(origin)

        if shape == "sphere":
            cells: list[str] = []
            for dc in range(-radius_cells, radius_cells + 1):
                for dr in range(-radius_cells, radius_cells + 1):
                    if max(abs(dc), abs(dr)) <= radius_cells:
                        cid = cell_id(oc + dc, orow + dr)
                        if self._in_bounds(cid):
                            cells.append(cid)
            return cells

        if direction is None:
            raise ValueError(f"shape={shape!r} requires a direction vector")
        ddc, ddr = direction
        if ddc == 0 and ddr == 0:
            raise ValueError("direction must be a nonzero vector")
        sdc = (ddc > 0) - (ddc < 0)
        sdr = (ddr > 0) - (ddr < 0)

        if shape == "line":
            line_cells: list[str] = []
            for step in range(radius_cells + 1):
                cid = cell_id(oc + sdc * step, orow + sdr * step)
                if self._in_bounds(cid):
                    line_cells.append(cid)
            return line_cells

        if shape == "cone":
            cone_cells: list[str] = []
            for dc in range(-radius_cells, radius_cells + 1):
                for dr in range(-radius_cells, radius_cells + 1):
                    if max(abs(dc), abs(dr)) > radius_cells:
                        continue
                    forward = dc * sdc + dr * sdr
                    lateral = abs(dc * sdr - dr * sdc)
                    if 0 <= forward <= radius_cells and lateral <= forward:
                        cid = cell_id(oc + dc, orow + dr)
                        if self._in_bounds(cid):
                            cone_cells.append(cid)
            return cone_cells

        raise ValueError(f"unknown template shape: {shape!r}")

    def _neighbors(self, cid: str) -> list[str]:
        col, row = parse_cell(cid)
        out: list[str] = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nid = cell_id(col + dc, row + dr)
                if self._in_bounds(nid) and nid not in self._blocked:
                    out.append(nid)
        return out

    def shortest_path(self, a: str, b: str) -> list[str]:
        if not self._in_bounds(a) or not self._in_bounds(b):
            return []
        if a == b:
            return [a]
        # BFS over 8-neighbours (uniform 1-step cost ⇒ fewest cells). Blocked
        # cells are never enqueued, so paths route around them.
        prev: dict[str, str] = {}
        seen: set[str] = {a}
        queue: deque[str] = deque([a])
        while queue:
            node = queue.popleft()
            if node == b:
                path = [b]
                while path[-1] != a:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for nb in self._neighbors(node):
                if nb not in seen:
                    seen.add(nb)
                    prev[nb] = node
                    queue.append(nb)
        return []


__all__ = [
    "GridTopology",
    "SpatialTopology",
    "cell_id",
    "parse_cell",
]
