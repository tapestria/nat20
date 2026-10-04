"""Areas of effect on the grid (SRD 5.2 §Areas of Effect).

Pure helpers shared by every path that resolves an area: which activity is an
area, where its template lies, and which creatures standing in it it affects.
No I/O and no orchestrator import: the caller passes the topology, the
creatures in the area and their allegiance in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from dnd5e_engine.events import AreaShape
from dnd5e_engine.spatial import GridTopology, SpatialTopology

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


__all__ = [
    "AreaSelection",
    "AreaTemplate",
    "GridShape",
    "OriginAnchor",
    "area_activity",
    "area_cells",
    "area_template",
    "creature_count",
    "has_line_of_effect",
    "is_choice",
    "is_harmful",
    "select_affected",
]
