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

## Movement

To move, submit a `PlayerIntent` with `intent_type="move"` and a
`target_zone_id` (built with `cell_id`).

!!! warning "One step per intent"

    A move intent must name a cell **adjacent** to the mover. The engine does
    not path-find: a non-adjacent target is rejected with
    `MoveFailed(reason="not_adjacent")` even when it is well within the
    movement budget. Crossing 30 ft means submitting six move intents.
    `GridTopology.shortest_path` is available if you want to plan the route
    yourself.

Each step is validated against the grid — adjacency, blocked cells, and the
remaining movement budget — before emitting `ActorMoved`. Distance for range
and reach checks is measured in Chebyshev cells scaled to feet; entering a
`difficult_terrain_cells` cell costs double.

## Line of sight, cover, and AoE templates

`GridTopology.has_line_of_sight` blocks sight when the straight line between
two cells' centers crosses a `wall_segments` entry; a blocked ranged
attack/cast is rejected the same way an out-of-range one is. `cover_cells`
raises the covered target's effective AC (and Dexterity saves) for an
attack, or makes it untargetable at the `"total"` tier. `GridTopology.
cells_in_template(origin, shape, size_ft)` returns the Chebyshev cell set for
a `"sphere"`/`"cone"`/`"line"` area of effect (a `direction` vector is
required for cone/line).

## Zones vs grid

If you don't need a tactical map, pass `scene_zones` (a `SceneTopology` of
named `zones` connected by `ZoneEdge`s) instead of a `GridScene` — combat
then resolves over an abstract graph of locations. The two are mutually
exclusive inputs to the same combat loop. The zone backend has no positional
LoS/cover model — sight is always clear and cover is always `"none"` between
any two known zones.
