"""Areas of effect on the grid (SRD 5.2 §Areas of Effect).

Pure helpers shared by every path that resolves an area: which activity is an
area, where its template lies, which creatures standing in it it affects, and
where a creature that aims for itself places it (``best_aim``). No I/O and no
orchestrator import: the caller passes the topology, the creatures in the area
and their allegiance in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from dnd5e_engine.events import AreaShape
from dnd5e_engine.spatial import GridTopology, SpatialTopology, parse_cell

#: The shapes ``GridTopology.cells_in_template`` rasterises.
GridShape = Literal["sphere", "cone", "line", "cube", "cylinder"]

#: Where a template's point of origin sits: the named target's cell, or the
#: acting creature's own.
OriginAnchor = Literal["target", "actor"]

# Foundry ``target.template.type`` -> (SRD shape, grid shape, origin anchor,
# origin inside the area). SRD 5.2: a Sphere's or a Cylinder's point of origin
# is in its area; a Cone's, a Cube's, an Emanation's and a Line's "isn't
# included in the area of effect unless its creator decides otherwise", and the
# engine never decides otherwise. ``wall`` has no single point of origin, so it
# is absent: the engine can't place it.
_TEMPLATE_TYPES: Final[dict[str, tuple[AreaShape, GridShape, OriginAnchor, bool]]] = {
    "sphere": ("sphere", "sphere", "target", True),
    "circle": ("sphere", "sphere", "target", True),
    "cylinder": ("cylinder", "cylinder", "target", True),
    "radius": ("emanation", "sphere", "actor", False),
    "cube": ("cube", "cube", "actor", False),
    "square": ("cube", "cube", "actor", False),
    "cone": ("cone", "cone", "actor", False),
    "line": ("line", "line", "actor", False),
}

# SRD 5.2 §Areas of Effect: a Cone, a Cube and a Line extend "in a direction
# its creator chooses", so they can't be placed without an aim.
_DIRECTIONAL: Final[frozenset[GridShape]] = frozenset({"cone", "cube", "line"})

# The activity kinds that resolve against every creature in an area. An attack
# roll targets one creature, so a templated attack is never an area: the
# corpus's two (the Torch's light radius, the Hammer of Thunderbolts' thunderclap)
# describe something other than whom the attack hits.
_AREA_KINDS: Final[frozenset[str]] = frozenset({"save", "damage", "heal"})

# Foundry ``target.affects.type`` values whose ``count`` counts something other
# than creatures: Earthquake's one 100-foot circle is a ``space``.
_NOT_CREATURES: Final[frozenset[str]] = frozenset({"self", "object", "space"})

#: The eight grid directions a Cone, Cube or Line can be aimed in, as
#: ``(column step, row step)``: north (row - 1) first, then clockwise. A
#: creature that aims for itself tries them in this order, so a tie between
#: two directions goes to the earlier one.
AIM_DIRECTIONS: Final[tuple[tuple[int, int], ...]] = (
    (0, -1),
    (1, -1),
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
)


@dataclass(frozen=True)
class AreaTemplate:
    """An area activity's template, mapped onto the grid."""

    shape: AreaShape
    grid_shape: GridShape
    size_ft: int
    anchor: OriginAnchor
    includes_origin: bool

    @property
    def directional(self) -> bool:
        """True for a Cone, a Cube or a Line, which need an aim."""
        return self.grid_shape in _DIRECTIONAL


@dataclass(frozen=True)
class AreaSelection:
    """Whom an area affects, and whom it spares, among the creatures in it."""

    affected_ids: tuple[str, ...]
    spared_ids: tuple[str, ...]


@dataclass(frozen=True)
class AreaAim:
    """Where a creature places an area, and whom the area then affects."""

    origin: str
    direction: tuple[int, int] | None
    selection: AreaSelection


def area_activity(activities: Sequence[Any]) -> Any | None:
    """The first save, damage or heal activity that carries a measured
    template, or ``None`` when the activities resolve against a named target."""
    return next(
        (a for a in activities if a.kind in _AREA_KINDS and a.target.template.type),
        None,
    )


def area_template(activity: Any) -> AreaTemplate | None:
    """The activity's template on the grid, or ``None`` when the engine can't
    place it: a ``wall``, or a size that isn't a positive number of feet
    (Confusion's ``@item.level`` formula)."""
    template = activity.target.template
    mapped = _TEMPLATE_TYPES.get(template.type)
    try:
        size_ft = int(float(template.size))
    except (TypeError, ValueError):
        return None
    if mapped is None or size_ft <= 0:
        return None
    shape, grid_shape, anchor, includes_origin = mapped
    return AreaTemplate(shape, grid_shape, size_ft, anchor, includes_origin)


def creature_count(activity: Any) -> int | None:
    """The N of "up to N creatures": a positive whole-number
    ``target.affects.count`` on an activity that affects creatures (Slow's 6,
    Phantasmal Force's 1). ``None`` for no count, a formula, or a count of
    spaces or objects."""
    affects = activity.target.affects
    count = affects.count.strip()
    if affects.type in _NOT_CREATURES or not count.isdigit() or int(count) == 0:
        return None
    return int(count)


def is_choice(activity: Any) -> bool:
    """SRD 5.2 "each creature of your choice": the activity's
    ``target.affects.choice`` flag."""
    return bool(activity.target.affects.choice)


def is_harmful(activities: Sequence[Any]) -> bool:
    """An area with a save or damage harms; one without (a heal) helps."""
    return any(a.kind in ("save", "damage") for a in activities)


def has_line_of_effect(topology: SpatialTopology, origin: str, cell: str) -> bool:
    """SRD 5.2 §Point of Origin — "If all straight lines extending from the
    point of origin to a location ... are blocked, that location isn't included
    ... To block a line, an obstruction must provide Total Cover." Walls and
    blocked cells block; creatures (Half Cover at most) never do, so no
    occupied cells are passed."""
    return origin == cell or (
        topology.has_line_of_sight(origin, cell) and topology.cover_between(origin, cell) != "total"
    )


def area_cells(
    topology: GridTopology,
    template: AreaTemplate,
    origin: str,
    direction: tuple[int, int] | None,
) -> frozenset[str]:
    """The cells in the area: the template's cells with line of effect from
    its point of origin, the origin itself dropped where the shape excludes it.
    ``direction`` is required for a directional template."""
    cells = topology.cells_in_template(
        origin, template.grid_shape, template.size_ft, direction=direction
    )
    area = {c for c in cells if has_line_of_effect(topology, origin, c)}
    if not template.includes_origin:
        area.discard(origin)
    return frozenset(area)


def select_affected(
    in_area: Sequence[str],
    *,
    affects_type: str,
    choice: bool,
    count: int | None,
    harmful: bool,
    excluded_ids: tuple[str, ...] | None,
    is_enemy: Callable[[str], bool],
    is_ally: Callable[[str], bool],
) -> AreaSelection:
    """Pick the creatures an area affects from those standing in it
    (``in_area``, in a stable order), relative to the acting creature.

    - ``affects_type`` ``"enemy"`` / ``"ally"`` keeps only that side
      ("each enemy in a 20-foot-radius Sphere").
    - A choice area ("each creature of your choice") or a counted one ("up to
      six creatures") with no ``excluded_ids`` keeps the acting creature's
      enemies when it harms and the creature and its allies when it helps;
      ``excluded_ids`` replaces that default with "everyone but these", so
      ``()`` keeps everyone.
    - ``count`` keeps the first N.

    ``is_ally`` is true for the acting creature itself."""
    picked = list(in_area)
    if affects_type == "enemy":
        picked = [i for i in picked if is_enemy(i)]
    elif affects_type == "ally":
        picked = [i for i in picked if is_ally(i)]
    if excluded_ids is not None:
        picked = [i for i in picked if i not in excluded_ids]
    elif choice or count is not None:
        keep = is_enemy if harmful else is_ally
        picked = [i for i in picked if keep(i)]
    if count is not None:
        picked = picked[:count]
    affected = tuple(picked)
    return AreaSelection(
        affected_ids=affected,
        spared_ids=tuple(i for i in in_area if i not in affected),
    )


def best_aim(
    topology: GridTopology,
    activity: Any,
    template: AreaTemplate,
    *,
    actor_id: str,
    actor_cell: str,
    target_cells: Sequence[str],
    creatures: Sequence[tuple[str, str]],
    is_enemy: Callable[[str], bool],
    is_ally: Callable[[str], bool],
) -> AreaAim | None:
    """Where a creature that aims for itself places ``activity``'s area: the
    aim whose affected creatures hold the most enemies minus allies, never the
    creature itself and at least one enemy; ``None`` when no aim qualifies.
    Draws no dice.

    The candidates, tried in a fixed order: an Emanation from ``actor_cell``;
    a Cone, Cube or Line from ``actor_cell`` in each of ``AIM_DIRECTIONS``; a
    Sphere or Cylinder centred on each of ``target_cells``, the cells of the
    enemies the creature can see within range, which the caller picks. A tie
    goes to the aim that affects fewer allies, then to the one whose enemies
    sit nearest its axis (a Cone, Cube or Line) or its point of origin (any
    other shape), then to the earlier candidate.

    ``creatures`` are the ``(id, cell)`` pairs of every creature an area can
    affect, in a stable order; whom an aim affects follows ``select_affected``
    with no exclusions, so "each enemy", "of your choice" and "up to N"
    apply as they do for any other actor. ``is_ally`` is true for the
    creature itself."""
    if template.anchor == "target":
        candidates: list[tuple[str, tuple[int, int] | None]] = [(c, None) for c in target_cells]
    elif template.directional:
        candidates = [(actor_cell, d) for d in AIM_DIRECTIONS]
    else:
        candidates = [(actor_cell, None)]
    cell_of = dict(creatures)
    best: AreaAim | None = None
    best_score: tuple[int, int, int] | None = None
    for origin, direction in candidates:
        cells = area_cells(topology, template, origin, direction)
        selection = select_affected(
            [i for i, cell in creatures if cell in cells],
            affects_type=activity.target.affects.type,
            choice=is_choice(activity),
            count=creature_count(activity),
            harmful=is_harmful([activity]),
            excluded_ids=None,
            is_enemy=is_enemy,
            is_ally=is_ally,
        )
        affected = selection.affected_ids
        enemies = [i for i in affected if is_enemy(i)]
        allies = sum(1 for i in affected if is_ally(i))
        if actor_id in affected or not enemies:
            continue
        spread = sum(_off_centre(origin, cell_of[i], direction) for i in enemies)
        score = (len(enemies) - allies, -allies, -spread)
        if best_score is None or score > best_score:
            best, best_score = AreaAim(origin, direction, selection), score
    return best


def _off_centre(origin: str, cell: str, direction: tuple[int, int] | None) -> int:
    """How far ``cell`` sits from an area's centre line: its sideways offset
    from a Cone's, Cube's or Line's axis (the measure
    ``GridTopology.cells_in_template`` widens a Cone by), else its distance
    from the point of origin, in cells."""
    origin_col, origin_row = parse_cell(origin)
    col, row = parse_cell(cell)
    d_col, d_row = col - origin_col, row - origin_row
    if direction is None:
        return max(abs(d_col), abs(d_row))
    step_col, step_row = direction
    return abs(d_col * step_row - d_row * step_col)


__all__ = [
    "AIM_DIRECTIONS",
    "AreaAim",
    "AreaSelection",
    "AreaTemplate",
    "GridShape",
    "OriginAnchor",
    "area_activity",
    "area_cells",
    "area_template",
    "best_aim",
    "creature_count",
    "has_line_of_effect",
    "is_choice",
    "is_harmful",
    "select_affected",
]
