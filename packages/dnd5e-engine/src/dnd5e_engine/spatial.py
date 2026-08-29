"""Spatial backends for combat resolution.

The engine resolves all positional reasoning through the ``SpatialTopology``
Protocol — a combatant's position is an opaque string handle, and the backend
answers adjacency / distance / range / pathing over it. Two backends exist:
the zone graph (``_ZoneGraph`` in ``orchestrator.py``) and the grid
(``GridTopology`` here). Call sites never branch on which backend is live.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection
from typing import Literal, Protocol, runtime_checkable

from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.specs import GridScene, LightLevel, Obscurement, WallSegment

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

    def shortest_path(self, a: str, b: str, *, avoid: Collection[str] = ()) -> list[str]: ...

    def has_line_of_sight(self, a: str, b: str) -> bool: ...

    def cover_between(
        self, a: str, b: str, occupied_cells: Collection[str] = ()
    ) -> CoverDegree: ...

    def can_see(self, a: str, b: str, senses: CombatantSenses | None = None) -> bool: ...


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
        self._lighting: dict[str, LightLevel] = dict(scene.lighting)
        self._default_lighting: LightLevel = scene.default_lighting
        self._obscurement: dict[str, Obscurement] = dict(scene.obscurement_cells)

    @property
    def cell_size_ft(self) -> int:
        """Feet per cell — the scale every ``*_ft`` argument is divided by."""
        return self._cell_size_ft

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

    def _step_is_legal(self, a: str, b: str) -> bool:
        """SRD 5.2 §Playing on a Grid, "Corners" — a single step ``a -> b``
        (already Chebyshev-adjacent, ``b`` not blocked) is legal unless the
        centre-to-centre segment crosses or touches a wall, or the step is a
        diagonal whose orthogonal corner cells include a blocked cell."""
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        dc, dr = bc - ac, br - ar
        if (
            dc != 0
            and dr != 0
            and (cell_id(ac + dc, ar) in self._blocked or cell_id(ac, ar + dr) in self._blocked)
        ):
            return False
        if self._walls:
            p1 = (ac + 0.5, ar + 0.5)
            p2 = (bc + 0.5, br + 0.5)
            for wall in self._walls:
                if _segments_intersect(p1, p2, (wall.x1, wall.y1), (wall.x2, wall.y2)):
                    return False
        return True

    def edge_distance(self, a: str, b: str) -> int | None:
        """One step's movement cost, in feet, entering ``b`` from adjacent ``a``;
        ``None`` when the step is illegal (not adjacent, ``b`` blocked, a wall
        crosses the step, or a diagonal cuts a blocked corner — SRD 5.2
        §Playing on a Grid "Corners"). SRD 5.2 §Difficult Terrain: entering a
        difficult-terrain cell costs double (keyed on the cell ENTERED)."""
        if not self.is_adjacent(a, b) or not self._step_is_legal(a, b):
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
        """SRD 5.2 §Point of Origin — "To block a line, an obstruction must
        provide Total Cover." Two obstruction sources share one walk:

        * ``wall_segments`` — the straight segment between the two cells'
          CENTER points is tested against every wall edge (grid-corner
          endpoints); any intersection blocks.
        * ``blocked_cells`` — a terrain feature that fills its space is Total
          Cover: any cell strictly between ``a`` and ``b`` on the Bresenham
          line that is blocked blocks sight. Endpoints never count.

        No walls and no blocked cells ⇒ always True (unchanged behaviour).
        """
        if not self._in_bounds(a) or not self._in_bounds(b):
            return False
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        if self._blocked:
            for cid in _bresenham_cells(ac, ar, bc, br):
                if cid != a and cid != b and cid in self._blocked:
                    return False
        if not self._walls:
            return True
        p1 = (ac + 0.5, ar + 0.5)
        p2 = (bc + 0.5, br + 0.5)
        for wall in self._walls:
            if _segments_intersect(p1, p2, (wall.x1, wall.y1), (wall.x2, wall.y2)):
                return False
        return True

    def cover_between(self, a: str, b: str, occupied_cells: Collection[str] = ()) -> CoverDegree:
        """SRD 5.2 §Cover — the highest cover degree an obstruction on the
        straight line between ``a`` and ``b`` grants (``none < half <
        three_quarters < total``). Three sources, one Bresenham walk over the
        cells strictly between the endpoints:

        * ``cover_cells`` — host-authored degree per cell. The TARGET's own
          cell counts (an object in its space covers it); the ORIGIN cell
          never does. Ruling shared with C22 Task 6 — keep at merge;
        * ``blocked_cells`` — "an object that covers the whole target" ⇒ ``total``;
        * ``occupied_cells`` — "another creature … that covers at least half
          of the target" ⇒ ``half``. The caller passes the cells of every
          OTHER live combatant (never the attacker's or the target's own cell —
          those are skipped here defensively as well). Ally or enemy makes no
          difference (rule card: creature cover ignores alignment).

        Empty geometry and no occupants ⇒ ``"none"`` (unchanged behaviour).
        """
        if not self._in_bounds(a) or not self._in_bounds(b):
            return "none"
        occupied = set(occupied_cells)
        if not self._cover_cells and not self._blocked and not occupied:
            return "none"
        ac, ar = parse_cell(a)
        bc, br = parse_cell(b)
        best: CoverDegree = "none"
        for cid in _bresenham_cells(ac, ar, bc, br):
            if cid == a:
                continue
            degree: CoverDegree | None = None
            if cid in self._blocked and cid != b:
                degree = "total"
            else:
                tagged = self._cover_cells.get(cid)
                if tagged is not None:
                    degree = tagged  # type: ignore[assignment]
                # Creature cover: the target's own cell is occupied by the
                # target itself and never grants it cover.
                if (
                    cid != b
                    and cid in occupied
                    and (degree is None or _COVER_RANK[degree] < _COVER_RANK["half"])
                ):
                    degree = "half"
            if degree is not None and _COVER_RANK[degree] > _COVER_RANK[best]:
                best = degree
        return best

    def can_see(self, a: str, b: str, senses: CombatantSenses | None = None) -> bool:
        """SRD 5.2 §Vision and Light — can a viewer in ``a`` with ``senses`` see
        a creature standing in ``b``?

        1. Line of sight (walls / blocked cells) is required for every sense —
           Blindsight: "you can see anything that isn't behind Total Cover".
        2. Blindsight or Truesight whose range reaches ``b`` sees through
           Darkness and heavy obscurement.
        3. A Heavily Obscured cell (``obscurement_cells == "heavy"``) is
           opaque to sight; Darkvision does not help (it only re-grades light).
        4. Bright or Dim Light in ``b`` is visible ("in a Lightly Obscured area
           ... you have Disadvantage on Wisdom (Perception) checks" — attacks
           are unaffected).
        5. Darkness in ``b`` needs Darkvision reaching ``b`` ("in Darkness
           within that range as if it were Dim Light").

        Tremorsense is deliberately not consulted — "it doesn't count as a
        form of sight" (SRD 5.2 glossary, Tremorsense). Conditions (Blinded)
        are the caller's concern (``rules/conditions.py``).
        """
        if not self.has_line_of_sight(a, b):
            return False
        distance = self._chebyshev(a, b)
        if distance is None:
            return False
        distance_ft = distance * self._cell_size_ft

        def reaches(range_ft: int | None) -> bool:
            return range_ft is not None and range_ft >= distance_ft

        if senses is not None and (reaches(senses.blindsight) or reaches(senses.truesight)):
            return True
        if self._obscurement.get(b) == "heavy":
            return False
        if self._lighting.get(b, self._default_lighting) != "dark":
            return True
        return senses is not None and reaches(senses.darkvision)

    def is_valid_cell(self, cid: str) -> bool:
        """True iff ``cid`` is in bounds and not impassable — a legal occupancy."""
        return self._in_bounds(cid) and cid not in self._blocked

    def cells_in_template(
        self,
        origin: str,
        shape: Literal["sphere", "cone", "line", "cube", "cylinder"],
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
        * ``"cylinder"``: the same cell set as ``"sphere"`` — SRD: "a
          Cylinder's point of origin is included in the area of effect"; the
          height dimension has no 2-D meaning on a grid template.
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
        * ``"cube"``: requires ``direction``; a face-anchored ``n x n`` block
          (``n = radius_cells``) whose near face touches the origin cell —
          SRD: "A Cube's point of origin isn't included in the area of
          effect unless its creator decides otherwise" (origin excluded).
          See ``docs/dev/spatial-geometry.md`` for the placement convention.

        See ``docs/dev/spatial-geometry.md``. Not part of the
        ``SpatialTopology`` Protocol — grid-only (the zone-graph backend has
        no cell coordinates to enumerate a template over).
        """
        if not self._in_bounds(origin):
            return []
        radius_cells = size_ft // self._cell_size_ft
        oc, orow = parse_cell(origin)

        if shape in ("sphere", "cylinder"):
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

        if shape == "cube":
            # radius_cells = size_ft // cell_size_ft is already the cube's
            # side length in cells (not a radius here) — see docstring.
            return self._cube_cells(oc, orow, sdc, sdr, radius_cells)

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

    def push_path(
        self,
        origin: str,
        target: str,
        distance_ft: int,
        *,
        occupied_cells: Collection[str] = (),
    ) -> list[str]:
        """Forced movement "straight away from" ``origin``: the cells a creature
        at ``target`` crosses when pushed ``distance_ft`` (SRD 5.2 Thunderwave
        "pushed 10 feet away from you", Push mastery "straight away from
        yourself"). Direction is the sign of ``target - origin`` per axis (one
        of the 8 grid directions). The walk stops early at the grid edge, a
        blocked cell, a wall, a corner cut (``edge_distance`` is ``None``) or an
        occupied cell — the creature is moved as far as it can go. Grid-only;
        not part of ``SpatialTopology``."""
        if not self._in_bounds(origin) or not self._in_bounds(target) or origin == target:
            return []
        oc, orow = parse_cell(origin)
        tc, tr = parse_cell(target)
        sdc = (tc > oc) - (tc < oc)
        sdr = (tr > orow) - (tr < orow)
        occupied = set(occupied_cells)
        out: list[str] = []
        current = target
        for _ in range(distance_ft // self._cell_size_ft):
            cc, cr = parse_cell(current)
            nxt = cell_id(cc + sdc, cr + sdr)
            if (
                not self._in_bounds(nxt)
                or nxt in occupied
                or self.edge_distance(current, nxt) is None
            ):
                break
            out.append(nxt)
            current = nxt
        return out

    def _cube_cells(self, oc: int, orow: int, sdc: int, sdr: int, side: int) -> list[str]:
        """The face-anchored ``side x side`` block for ``"cube"`` — see the
        placement convention in ``cells_in_template``'s docstring and
        ``docs/dev/spatial-geometry.md``."""
        if sdc != 0 and sdr != 0:
            cols = [oc + sdc * k for k in range(1, side + 1)]
            rows = [orow + sdr * k for k in range(1, side + 1)]
        elif sdc != 0:
            cols = [oc + sdc * k for k in range(1, side + 1)]
            rows = [orow - side // 2 + k for k in range(side)]
        else:
            cols = [oc - side // 2 + k for k in range(side)]
            rows = [orow + sdr * k for k in range(1, side + 1)]
        cube_cells: list[str] = []
        for c in cols:
            for r in rows:
                cid = cell_id(c, r)
                if self._in_bounds(cid):
                    cube_cells.append(cid)
        return cube_cells

    def _neighbors(self, cid: str) -> list[str]:
        col, row = parse_cell(cid)
        out: list[str] = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nid = cell_id(col + dc, row + dr)
                if self._in_bounds(nid) and self.edge_distance(cid, nid) is not None:
                    out.append(nid)
        return out

    def shortest_path(self, a: str, b: str, *, avoid: Collection[str] = ()) -> list[str]:
        """Fewest-cells path from ``a`` to ``b`` over LEGAL steps (BFS, 8
        neighbours in fixed order — the tie-break is part of the seeded
        contract). ``avoid`` cells are never entered (occupied-by-enemy cells,
        SRD 5.2 §Moving Around Other Creatures); ``b`` in ``avoid`` ⇒ ``[]``.
        Route cost is NOT minimised — callers charge each leg's
        ``edge_distance`` against the budget."""
        if not self._in_bounds(a) or not self._in_bounds(b):
            return []
        if a == b:
            return [a]
        avoid_set = set(avoid)
        if b in avoid_set:
            return []
        # BFS over 8-neighbours (uniform 1-step cost ⇒ fewest cells). Illegal
        # or avoided cells are never enqueued, so paths route around them.
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
                if nb not in seen and nb not in avoid_set:
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
