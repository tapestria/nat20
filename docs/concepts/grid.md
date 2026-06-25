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
list of `blocked_cells` — impassable squares movement may not enter.

## Movement

To move, submit a `PlayerIntent` with `intent_type="move"` and a
`target_zone_id` (built with `cell_id`). The engine validates the path
against the grid — range, blocked cells, and reachability — and emits the
movement events. Distance for range and reach checks is measured in
Chebyshev cells scaled to feet.

## Zones vs grid

If you don't need a tactical map, pass `scene_zones` (a `SceneTopology` of
named `zones` connected by `ZoneEdge`s) instead of a `GridScene` — combat
then resolves over an abstract graph of locations. The two are mutually
exclusive inputs to the same combat loop.

Line-of-sight, cover, and AoE templates over wall geometry are deferred; the
current grid backend handles movement, range, and blocked cells.
