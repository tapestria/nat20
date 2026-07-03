# Spatial geometry (Cluster 5 design note)

Design note for the "Spatial mechanics" BACKLOG.md section — wall geometry +
real line-of-sight, the SRD 5.2 cover model, Chebyshev AoE templates, and
difficult-terrain path costs. Written before implementation per the
autonomous gap-closing campaign's epic protocol
(`specs/e2e-scenario-catalog.md`, Cluster 5: C05-S01..S05).

All additions are **additive** on `GridScene` / `GridTopology` — the
`SpatialTopology` Protocol call sites (`orchestrator.py`, `activities/attack.py`,
`activities/save.py`) never branch on which backend (zone graph vs grid) is
live; an empty/default field on `GridScene` reproduces today's behavior
byte-for-byte.

## Wall geometry + line of sight

`GridScene.wall_segments: list[WallSegment] = []` — a new value type,
`WallSegment(x1, y1, x2, y2)`, grid-**corner** coordinates (a wall between
column 2 and column 3 is `x1=2, x2=2`, not `2.5`), mirroring Foundry's own
`Wall.c` four-coordinate convention (`raw_sources/foundry` wall document
shape). Pydantic accepts plain mapping dicts for the field (no bespoke
validator needed).

`GridTopology.has_line_of_sight(a, b)` traces the straight segment between
`a`'s and `b`'s CELL-CENTER points (`col+0.5, row+0.5`) and returns `False`
iff that segment properly intersects any `wall_segments` entry — a standard
orientation-based segment-intersection test (CCW/orientation + on-segment
fallback for the collinear case), not a coarser cell-traversal heuristic,
since walls are edge geometry, not cells. Default (no walls) preserves the
prior "always True" behavior.

This directly grounds SRD 5.2 §Areas of Effect's blocking rule (an
obstruction blocks a line only by providing Total Cover — i.e. a wall) and is
the geometry the existing `_in_range_with_los` gate (`orchestrator.py`) was
already wired to consume; no consumer-side change was needed, only the
geometry backing it.

## Cover model

`GridScene.cover_cells: dict[str, Literal["half", "three_quarters", "total"]] = {}`
tags an obstruction CELL (distinct from `blocked_cells`, which blocks
movement, and from `wall_segments`, which blocks LoS outright) with the cover
degree it grants a creature standing behind it.

`SpatialTopology.cover_between(a, b) -> Literal["none", "half", "three_quarters", "total"]`
is a new Protocol method. `GridTopology`'s implementation walks the cells a
Bresenham line from `a`'s to `b`'s cell traverses (excluding the two
endpoints) and returns the HIGHEST cover degree tagged on any intervening
cell (`none < half < three_quarters < total`). The zone-graph backend
(`_ZoneGraph`) has no positional cover model — its `cover_between` always
returns `"none"`, preserving current (no-cover) zone-combat behavior; this is
a deliberate, documented backend split, not a gap (see "Zone-backend
decision" below).

Consumers:

- `activities/attack.py::resolve_attack` folds `+2` (half) / `+5`
  (three-quarters) onto the target's AC before the `total >= target_ac`
  comparison. Total cover never reaches this point — it is filtered upstream.
- `activities/save.py` / `activities/save_primitive.py::roll_save` folds the
  SAME `+2`/`+5` onto a **Dexterity** save's total (SRD 5.2 §Cover: cover
  grants "a bonus to AC **and Dexterity saving throws**" — it is a bonus to
  the covered creature's own roll, not a DC adjustment). Non-DEX saves are
  unaffected.
- `orchestrator._in_range_with_los` gains a third conjunct,
  `topology.cover_between(a, b) != "total"` — total cover makes a target
  untargetable (SRD 5.2 §Cover: "can't be targeted directly"), reusing the
  existing `AttackFailed(reason="out_of_range")` surface every other
  range/LoS rejection already uses.

Both bonuses are threaded through a new `ActivityResolutionContext.target_cover:
dict[str, str]` sidecar, computed once per activity resolution by the
orchestrator (`_target_cover_map`, mirroring the existing
`passive_damage_modifiers`-style sidecar convention) from the caster's and
each target's live zone via `topology.cover_between` — the two resolvers
never import the spatial seam directly.

**Per-activity "ignores cover for save" flag — shrunk, not built.** The
BACKLOG entry named a per-activity override (Sacred Flame's SRD 5.2 text:
"The target gains no benefit from Half Cover or Three-Quarters Cover for this
save"). No such boolean exists on `SaveActivity`/`SaveBlock` in the canonical
schema today (`dnd5e_srd_data.schema.common.SaveBlock` carries only
`ability`/`dc`) — inventing one without a real data-layer field to back it
would be a data fabrication, which this campaign's licensing/ground-truth
rules forbid. This sub-piece remains open, narrowed to: add a
`SaveBlock.ignore_cover: bool` (or similar) field to the schema + translator,
then have `activities/save.py` skip the cover fold when set. Tracked as a
shrunk BACKLOG line, not closed.

## AoE templates

`GridTopology.cells_in_template(origin, shape, size_ft, *, direction=None) ->
list[str]` — the BACKLOG's named seam. All three shapes share the settled
**Chebyshev** metric (maintainer decision, catalog C05-S04 — not
relitigated): `radius_cells = size_ft // cell_size_ft`.

- **`"sphere"`** (C05-S04, e2e-pinned): every cell with
  `max(|dx|, |dy|) <= radius_cells` from the origin, origin included. 20 ft on
  a 5 ft grid → `radius_cells=4` → the full `9x9 = 81`-cell block.
- **`"line"`** (unit-tested only — no e2e entry): a `direction` unit vector
  (any of the 8 grid directions) is required; the cells are the
  `radius_cells + 1` cells stepping from the origin along that direction
  (Bresenham-exact for cardinal/diagonal directions), origin included. Models
  a 1-cell-wide line (Lightning Bolt's 5 ft width on a 5 ft grid); a
  variable-width line is not modeled (no SRD spell in the corpus needs it
  today).
- **`"cone"`** (unit-tested only — no e2e entry): a `direction` unit vector is
  required. A cell at grid offset `(dx, dy)` is in the cone iff its
  projection onto `direction` (`forward = dx*dir.x + dy*dir.y`) is within
  `[0, radius_cells]` AND its perpendicular offset (`lateral = |dx*dir.y -
  dy*dir.x|`) does not exceed `forward` — a widening 45°, Chebyshev-bounded
  triangle from the origin, closed under all 8 grid directions. This is an
  engine convention (a "square cone"), not a literal transcription of SRD
  prose geometry — the SRD's continuous-cone-on-a-square-grid problem has no
  single canonical grid rasterization; this definition is monotonic, cheap,
  and consistent with the Chebyshev metric governing every other spatial
  query.

Obstruction-aware trimming (an obstruction providing Total Cover excludes a
location from a template, per SRD 5.2 §Areas of Effect) is an explicit,
recorded follow-up — `cells_in_template` does no `wall_segments`/`cover_cells`
filtering today.

## Terrain cost model

`GridScene.difficult_terrain_cells: list[str] = []` — a first-class floor-cell
set, distinct from `blocked_cells` (impassable) and `cover_cells`
(AC/save-only). `GridTopology.edge_distance(a, b)` doubles its returned cost
(`2 * cell_size_ft` instead of `cell_size_ft`) when the cell being ENTERED
(`b`) is tagged difficult terrain — SRD 5.2 §Difficult Terrain: "every foot of
movement in Difficult Terrain costs 1 extra foot." `_handle_move`
(`orchestrator.py`) needs no change: it already reads `edge_distance` as its
per-step cost and rejects a move that would exceed `movement_remaining`
without mutating the budget.

**What stays out (shrinks, does not delete, the "Richer pathfinding" BACKLOG
line):** `shortest_path` remains uniform-cost BFS (fewest CELLS) — it does
NOT become a cost-aware search (e.g. Dijkstra weighted by `edge_distance`).
Threat-aware routing (avoiding opportunity-attack reach) and multi-tile
creature footprints are unaddressed and remain BACKLOG'd; only the terrain
COST primitive (`edge_distance`) is closed here, consumed today by
`_handle_move`'s single-step budget check, not by any multi-step path
planner.

## Zone-backend decision

The zone-graph backend (`_ZoneGraph` in `orchestrator.py`) gains the two new
Protocol methods (`cover_between`) needed to satisfy `SpatialTopology`
structurally, both returning the behavior-preserving no-op: `cover_between`
always `"none"`. `has_line_of_sight` was already `True`-for-any-known-pair on
the zone backend before this change and is unmodified — zone combats have no
coordinate system to hang wall/cover geometry off of, so this is the
documented, permanent split, not a temporary gap. `cells_in_template` is
**not** added to the `SpatialTopology` Protocol at all (grid-only — an
abstract zone graph has no cell coordinates to enumerate a template over);
callers reach it via `isinstance(topology, GridTopology)` / direct
`GridTopology` construction, same as any other grid-only capability.
