# Spatial geometry

How the grid backend models space: wall geometry and real line-of-sight, the
SRD 5.2 cover model, Chebyshev AoE templates, and difficult-terrain path costs.

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
**Chebyshev** metric (maintainer decision, catalog a pinned scenario — not
relitigated): `radius_cells = size_ft // cell_size_ft`.

- **`"sphere"`** (a pinned scenario, e2e-pinned): every cell with
  `max(|dx|, |dy|) <= radius_cells` from the origin, origin included. 20 ft on
  a 5 ft grid → `radius_cells=4` → the full `9x9 = 81`-cell block.
- **`"line"`** (unit-tested only — no e2e entry): a `direction` unit vector
  (any of the 8 grid directions) is required; the cells are the
  `radius_cells + 1` cells stepping from the origin along that direction
  (Bresenham-exact for cardinal/diagonal directions), origin included. Models
  a 1-cell-wide line (Lightning Bolt's 5 ft width on a 5 ft grid); a
  variable-width line is not modeled (no SRD spell in the corpus needs it
  today; the ignored `template.width` is a recorded BACKLOG line).
- **`"cube"`** — a `direction` unit vector is required. The cube's SRD point of
  origin is a *face*, not the centre, so the cube is placed **adjacent to and
  extending away from** the origin cell along `direction`: a `size_ft` cube is
  the `n x n` block (`n = size_ft // cell_size_ft`) whose near face abuts the
  origin, and the origin cell itself is **not** in the area.
- **`"cylinder"`** — the grid is strictly 2-D, so a cylinder's height carries no
  geometry: its footprint is exactly its `"sphere"` disc of the same radius,
  origin included. This is a deliberate collapse, not an omission; modelling it
  properly needs elevation, which is a separate recorded gap.
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

**Line of effect.** `cells_in_template` itself is pure geometry and does no
obstruction filtering — trimming happens one level up, in
`orchestrator._expand_aoe_target_list`, which drops every produced cell for
which `_has_line_of_effect(topology, origin, cell)` is false. Per SRD 5.2
§Areas of Effect, "If all straight lines extending from the point of origin to a
location ... are blocked, that location isn't included ... To block a line, an
obstruction must provide **Total Cover**" — so the test is precisely
`has_line_of_sight` (walls and `blocked_cells`) plus a `cover_between(...) ==
"total"` check. Half and three-quarters cover do **not** exclude a cell; they
only feed the covered creature's AC / Dexterity save.

## Legal steps

`GridTopology.edge_distance(a, b)` is the single legality oracle for one step:
it returns `None` when the step is illegal and the cost in feet otherwise.
A step is illegal when `b` is not Chebyshev-adjacent to `a`, `b` is off the map,
`b` is in `blocked_cells`, the centre-to-centre segment `a → b` crosses (or
touches) a `wall_segments` entry, or — for a **diagonal** — when either of the
two orthogonal cells the step passes between is blocked. That last clause is the
**corner rule** (SRD 5.2 §Playing on a Grid, "Corners"): a diagonal move may not
cut the corner of an obstruction, even though the two cell centres are not
themselves separated. Walls therefore block movement as well as sight, which was
not true before C16.

`shortest_path(a, b, *, avoid=())` is BFS over legal steps, skipping every cell
in `avoid` (the caller passes enemy-occupied cells). The neighbour enumeration
order is fixed and part of the determinism contract: every seeded monster walk
must reproduce byte-identically across releases.

## Visibility

`GridTopology.can_see(a, b, senses=None) -> bool` is a five-step predicate,
short-circuiting in order:

1. No line of sight from `a` to `b` (walls, blocked cells) ⇒ **unseen** — this
   gate applies to *every* sense, including blindsight, which sees "anything
   that isn't behind Total Cover".
2. Blindsight or truesight whose range reaches `b` ⇒ **seen**, whatever the
   light.
3. `b`'s cell is Heavily Obscured ⇒ **unseen**; darkvision does not help (it
   re-grades light, not opacity).
4. `b`'s cell is Bright or Dim ⇒ **seen**.
5. `b`'s cell is Dark ⇒ **seen** only with darkvision reaching it.

(A cell the engine has no position for never reaches the predicate:
`_target_visibility_maps` treats an untracked combatant as seen, so a scene with
no positional data can never silently impose disadvantage.)

**Tremorsense is deliberately excluded** from steps 3–5. SRD 5.2: a creature
with Tremorsense "can pinpoint the location of creatures and moving objects
within a specific range, provided that the creature and the source of the
vibrations are in contact with the same surface" — pinpointing a *location* is
not seeing a *target*, so it does not defeat the Unseen Attackers and Targets
disadvantage. A host that wants tremorsense to grant sight must say so; the
engine will not infer it.

`_target_visibility_maps` (orchestrator) evaluates the predicate in both
directions per target and hands the two boolean maps to the activity context, so
`activities/attack.py` can add the `unseen` `AdvantageSource` without importing
the spatial seam.

### Composite predicate

`GridTopology.can_see` answers the raw scene question ("is `b` lit and
unobstructed from `a`"), but several SRD 5.2 rules ask a narrower "can see"
question that also depends on the *viewer's* and *target's* conditions —
Blinded blocks a viewer's sight outright, and Invisible defeats a target's
visibility, unless a special sense pierces either. `orchestrator.py`'s
`_combatant_can_see(live, viewer, target)` (C16b, plan ruling R4) composes
the two:

1. Untracked position on either side ⇒ **seen** — a scene with no positional
   data never imposes a penalty (the same convention `_target_visibility_maps`
   uses for the raw `unseen` maps).
2. Blinded viewer (SRD 5.2 Blinded: "You can't see") ⇒ **unseen**, unless
   `_special_sense_reaches` — blindsight or truesight in range — says
   otherwise.
3. Invisible target (SRD 5.2 Invisible: "If a creature can somehow see you,
   you don't gain this benefit against that creature") ⇒ **unseen**, unless
   the same special-sense reach test pierces it. A creature hidden via the
   Hide action carries the Invisible condition, so this step covers Hide too.
4. Otherwise, fall through to `GridTopology.can_see` with the viewer's own
   projected senses — the scene vision model above.

Darkvision is never a special sense for step 2 or 3: it only re-grades
light (step 3/4 of the base predicate), so a Darkvision-only viewer still
can't pierce Blinded or Invisible.

This predicate is *not* what feeds the `unseen` `AdvantageSource` — that stays
the raw `_target_visibility_maps` / `can_see` pair, since Blinded and Invisible
already emit their own `condition:*` advantage sources and double-counting
would be wrong. `_combatant_can_see` instead backs every OTHER SRD "can see"
conjunct: the Dodge action's "if you can see the attacker" attack-disadvantage
half (both at the regular-attack context build sites and on opportunity
attacks), the Ranged Attacks in Close Combat "enemy who can see you" gate, the
Opportunity Attack "creature that you can see" trigger (both PC↔monster
directions — a sight-blocked reactor spends no Reaction and fires no attack),
Hide's "out of any enemy's line of sight" conjunct, and Frightened's
line-of-sight gate (both the attack-roll disadvantage and the "can't
willingly move closer to the source of fear" movement rule).

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
