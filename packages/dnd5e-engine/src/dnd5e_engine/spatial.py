"""Spatial backends for combat resolution.

The engine resolves all positional reasoning through the ``SpatialTopology``
Protocol — a combatant's position is an opaque string handle, and the backend
answers adjacency / distance / range / pathing over it. Two backends exist:
the zone graph (``_ZoneGraph`` in ``orchestrator.py``) and the grid
(``GridTopology`` here). Call sites never branch on which backend is live.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol, runtime_checkable

from dnd5e_engine.specs import GridScene


def cell_id(col: int, row: int) -> str:
    """Encode a grid coordinate as the opaque position handle ``"col,row"``."""
    return f"{col},{row}"


def parse_cell(cid: str) -> tuple[int, int]:
    """Decode a ``"col,row"`` handle. Raises ValueError on malformed input."""
    col_s, _, row_s = cid.partition(",")
    if not col_s or not row_s or "," in row_s:
        raise ValueError(f"malformed cell id: {cid!r}")
    return int(col_s), int(row_s)


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


class GridTopology:
    """Chebyshev (8-direction, one cell = ``cell_size_ft``) grid backend.

    Position handles are ``"col,row"`` cell ids. ``blocked_cells`` are
    impassable squares — movement may not enter them and paths route around
    them. Line-of-sight / cover over wall geometry is deferred (v1
    ``has_line_of_sight`` always returns ``True``); see ``BACKLOG.md``.
    """

    def __init__(self, scene: GridScene) -> None:
        self._width = scene.width
        self._height = scene.height
        self._cell_size_ft = scene.cell_size_ft
        self._blocked: set[str] = set(scene.blocked_cells)

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
        if not self.is_adjacent(a, b):
            return None
        return self._cell_size_ft

    def within_range(self, caster: str, target: str, range_ft: int) -> bool:
        dist = self._chebyshev(caster, target)
        if dist is None:
            return False
        return dist * self._cell_size_ft <= range_ft

    def has_line_of_sight(self, a: str, b: str) -> bool:
        # v1: walls-as-geometry block movement (blocked_cells) but not sight.
        # LoS over wall segments is deferred — see BACKLOG.md.
        return self._in_bounds(a) and self._in_bounds(b)

    def is_valid_cell(self, cid: str) -> bool:
        """True iff ``cid`` is in bounds and not impassable — a legal occupancy."""
        return self._in_bounds(cid) and cid not in self._blocked

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
