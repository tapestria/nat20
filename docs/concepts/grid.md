# Grid

Nat20 supports both abstract zone topologies and a concrete 2-D grid. Pass a
**`GridScene`** to `start_combat` and combat resolves over a square grid using
Chebyshev (8-direction) distance, where one cell equals `cell_size_ft`
(default 5).

## Positioning

Combatant positions reuse the `zone_id` string already on
`PartyMemberSpec` and `EncounterMemberSpec`. On a grid, that string is a cell
encoded as `"col,row"`. Two helpers handle the encoding:

- `cell_id(col, row)` — build the `"col,row"` string for a cell.
- `parse_cell(zone_id)` — decode it back into coordinates.

A `GridScene` declares `width`, `height`, an optional `cell_size_ft`, and a
list of `blocked_cells` — impassable squares movement may not enter. Four
more fields are additive (each defaults empty, preserving prior behavior):

- `wall_segments` — a list of `WallSegment(x1, y1, x2, y2)` grid-corner
  endpoints (mirroring Foundry's `Wall.c` convention) that block line of
  sight between two cells.
- `cover_cells` — a `{cell_id: "half" | "three_quarters" | "total"}` map of
  obstruction cells granting cover (SRD 5.2 §Cover): half/three-quarters add
  +2/+5 to a target's AC and Dexterity saves; total makes it untargetable.
- `difficult_terrain_cells` — a list of cell ids that cost double to enter
  (SRD 5.2 §Difficult Terrain).
- `lighting` / `default_lighting` / `obscurement_cells` — the vision model, see
  [Vision and light](#vision-and-light) below.

## Movement

To move, submit a `PlayerIntent` with `intent_type="move"` and a
`target_zone_id` (built with `cell_id`).

### Pathing

The destination may be **any** cell, not just an adjacent one. The engine routes
with `GridTopology.shortest_path`, walks the route, and charges each leg's cost
against the remaining movement budget; entering a `difficult_terrain_cells` cell
costs double. The whole intent produces exactly **one** `ActorMoved`, carrying
the total distance travelled.

A step is legal when it stays on the map, does not cross a `wall_segments`
entry, does not enter a `blocked_cells` square, and — for a diagonal — does not
cut a wall's corner. Occupancy follows SRD 5.2 §Moving Around Other Creatures:
**allies are passable, enemies are not**, and a move may not *end* on a cell
another creature occupies. (Occupancy is grid-only; the zone backend ignores it.)

A rejected move emits `MoveFailed` with one of:

| Reason | Meaning |
|---|---|
| `not_adjacent` | no destination given, or it is the mover's own cell |
| `unreachable` | no legal route, or the route costs more than the budget left |
| `occupied` | the destination holds another creature |
| `blocked_path` | every route is cut by a wall or a blocked cell |

The route search minimises the number of *squares*, not their cost, so a mover
may be routed through difficult terrain when an equally long detour would be
cheaper. Distance for range and reach checks is measured in Chebyshev cells
scaled to feet.

### Forced movement

Movement a creature does not choose — Thunderwave's push today — goes through
`push_combatant(live, target_id, origin_cell, distance_ft)` and emits
`CombatantMoved(..., forced=True)` rather than `ActorMoved`, so a renderer can
distinguish "is pushed 10 feet" from "moves". Forced movement provokes no
opportunity attack and spends none of the target's budget.

## Line of sight, cover, and AoE templates

`GridTopology.has_line_of_sight` blocks sight when the straight line between two
cells' centers crosses a `wall_segments` entry **or passes through a
`blocked_cells` square**; a blocked ranged attack/cast is rejected the same way
an out-of-range one is.

`cover_between` folds three obstruction sources into one tier (SRD 5.2 §Cover):
`cover_cells`, `blocked_cells` (Total Cover), and **any other live creature
standing on the line** (Half Cover). Half / three-quarters add +2 / +5 to the
target's AC and Dexterity saves; total makes it untargetable. A save activity
carrying `ignore_cover` (Sacred Flame) skips the save-side bonus.

`GridTopology.cells_in_template(origin, shape, size_ft, *, direction=None)`
returns the cell set for a `"sphere"`, `"cone"`, `"line"`, `"cube"` or
`"cylinder"` area of effect; `"cone"`, `"line"` and `"cube"` require a
`direction` vector.

AoE **spells** use this automatically: the spell's typed template is placed at
its SRD point of origin, expanded, and trimmed to the cells with line of effect
from that origin ("To block a line, an obstruction must provide Total Cover").
Every alive creature in a surviving cell is a target — including the caster and
their allies. Aim a directional template with `PlayerIntent.direction`; omit it
and the engine aims caster → named target. A self-origin cone/line/cube with
neither is rejected before the slot is spent, with
`CastFailed(reason="target_invalid")`.

## Vision and light

Three optional `GridScene` fields model SRD 5.2 §Vision and Light:

- `lighting` — `{cell_id: "bright" | "dim" | "dark"}`.
- `default_lighting` — the level for unlisted cells (default `"bright"`).
- `obscurement_cells` — `{cell_id: "light" | "heavy"}` for fog, foliage and the
  like.

`GridTopology.can_see(a, b, senses)` answers whether a viewer at `a` perceives a
creature at `b`. It requires line of sight, then checks the target's cell:
Darkness and Heavy Obscurement make it unseen unless the viewer's senses reach —
darkvision covers a dark cell, blindsight and truesight see regardless of light.
**Tremorsense is not sight**: the SRD defines it as sensing *location* through
vibration, which does not satisfy "a target you can see".

The result feeds attack rolls **both ways** (SRD §Unseen Attackers and Targets):
attacking a target you cannot see is Disadvantage, and attacking from a position
the target cannot see is Advantage, tagged with the `unseen` `AdvantageSource`.
The model is entirely opt-in — a scene with no lighting data resolves exactly as
a scene did before the fields existed. No light sources, and darkness does not
apply the Blinded condition.

## Zones vs grid

!!! warning "The zone graph is deprecated"

    `start_combat(scene_zones=...)` raises a `DeprecationWarning` as of 0.6.0
    and the backend is **removed in 0.7.0**. Pass a `GridScene` instead; if you
    have no tactical map, a one-row grid preserves the zone semantics:
    `GridScene(width=len(zones), height=1)` with `zone_id = cell_id(i, 0)`.

`scene_zones` (a `SceneTopology` of named `zones` connected by `ZoneEdge`s)
resolves combat over an abstract graph of locations. It and `GridScene` are
mutually exclusive inputs to the same combat loop. The zone backend has no
positional model at all — sight is always clear, cover is always `"none"`,
`can_see` is always true between any two known zones, AoE spells fall back to
zone-equality targeting, occupancy is not enforced, and every spatial feature
added in 0.6 is grid-only.
