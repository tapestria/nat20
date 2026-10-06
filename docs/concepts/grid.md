# Grid

Combat resolves on a 2-D grid. `start_combat` requires a **`GridScene`**: its
square cells use Chebyshev (8-direction) distance, and one cell equals
`cell_size_ft` (default 5). (0.7.0 removed the abstract zone graph; the
[v0.6 → v0.7 migration guide](../migration/v0.6-to-v0.7.md) shows how to port a
zone layout.)

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
with `GridTopology.shortest_path` and prices the *whole* route up front — each
leg's `edge_distance`, with a `difficult_terrain_cells` cell costing double — so
a route the budget cannot pay for is rejected atomically without moving. A route
it can pay for is walked, decrementing the budget cell by cell, and produces
one `ActorMoved` carrying the total distance — two or more when a step on the
way provokes an opportunity attack, which then lands between them.

A step is legal when it stays on the map, does not enter a `blocked_cells`
square, does not cross a `wall_segments` entry, and — for a diagonal — does not
cut an obstruction's corner. Occupancy follows SRD 5.2 §Moving Around Other
Creatures: **allies are passable, enemies are not**, and a move may not *end* on
a cell another creature occupies, ally or enemy.

A step that takes the mover out of an enemy's reach draws that enemy's
opportunity attack first, whoever drives the mover: a `move` intent, the
monster AI's closing walk, or its flee. Reach is measured in Chebyshev cells, so
moving around inside it never provokes. A mover the attack drops to 0 HP, or to
Speed 0, stops on the cell it was leaving; a mover the attack pushes stops
where the push leaves it, keeping its unspent movement. Forced movement
provokes nothing.

A rejected move emits `MoveFailed` with one of:

| Reason | Meaning |
|---|---|
| `not_adjacent` | no destination given, an untracked position, or the destination is the mover's own cell (the legacy reason name is kept for hosts) |
| `occupied` | the destination holds another creature — ally or enemy |
| `blocked_path` | the destination is adjacent, but the single step crosses a wall or cuts a blocked corner |
| `unreachable` | no legal route at all (enemy-occupied cells are impassable; allies may be passed through) |
| `insufficient_movement` | a legal route exists but costs more than the remaining budget — atomic, nothing moves |

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

### Areas of effect

Every cast, item use and feature use whose save, damage or heal activity
carries a measured template resolves as an area: a Fireball or a Sleep, a
Dragonborn's Breath Weapon, the Pipes of Haunting. (An attack roll is never an
area: it targets one creature.) Nor is a `use_item` that resolves several of
an item's activities at once because no `activity_id` names one and none is
charged. The engine places the template at its SRD 5.2 point of origin — the
named target's cell for a Sphere or Cylinder, else the
actor's; the actor's own cell for an Emanation, Cone, Cube or Line, whose
origin is not part of the area — expands it, and keeps the cells with line of
effect from that origin ("To block a line, an obstruction must provide Total
Cover"). Aim a Cone, Cube or Line with `PlayerIntent.direction`; omit it and
the engine aims actor → named target. An area with neither is refused before
anything is spent, with `target_invalid`.

Who in the area is affected follows the activity's `target.affects`:

| The activity says | It affects |
|---|---|
| nothing more ("each creature in a 20-foot-radius Sphere") | every living creature in the area, the actor and its allies included (a Fireball still catches its caster) |
| "each enemy" / "each ally" (`affects.type`) | only that side, relative to the actor |
| "of your choice" (`affects.choice`) | the actor's enemies when the area harms (a save or damage), the actor and its allies when it heals — unless `PlayerIntent.excluded_target_ids` says otherwise |
| "up to N creatures" (a whole-number `affects.count`) | the creatures `target_ids` names (a lone `target_id` when N is 1), else the first N the default keeps, in initiative order |

`excluded_target_ids` lists the creatures an area of your choice spares, and
replaces the default: `("char:ally",)` spares that ally and nobody else, and
`()` spares nobody, so a caster standing in its own Sleep opts itself in. Sent
with an intent that resolves no area of your choice — a Fireball, a sword
swing — or naming a creature not in the combat, it refuses the intent with
`target_invalid` before anything is spent.

Each placed area emits `AreaTargeted` before anything in it rolls: the actor,
the source slug, the shape (`sphere`, `cylinder`, `emanation`, `cube`, `cone`
or `line`), its size, its origin cell and aim, the creatures it affects
(`affected_ids`) and the creatures standing in it that it spares
(`excluded_ids`), both in initiative order.

A template the engine can't place on the grid (the five `wall` spells: Blade
Barrier, Tsunami, Wall of Fire, Wall of Thorns and Wind Wall; and Confusion,
whose size is a formula) affects its named target only, and so does a counted
area whose creatures the intent names; neither emits `AreaTargeted`.
`BACKLOG.md` tracks both.

### A monster's areas

The monster AI places its own areas — a breath, a stat-block spell, a
legendary action — under the same rules for whom they affect, with no
exclusions. It aims from the cell it stands in when its turn's action is
chosen (an area its Multiattack uses, from the cell the Multiattack's walk
ends on, skipped and unspent if it then affects no enemy) and takes the
placement that affects the most enemies minus allies,
never itself: an Emanation from its cell; a Cone, Cube or Line in each of the
eight directions (north first, then clockwise); a Sphere or Cylinder centred on
each foe it can see within the action's or spell's range. The area then
affects every creature it catches there, a creature at 0 Hit Points included —
only a choice or counted area spares the monster's own charmer — though the AI
scores the placement itself only against enemies above 0 Hit Points. A tie
goes to the placement that affects fewer allies, then to the one whose foes
sit nearest its centre line, then to the earlier candidate, so the aim is
deterministic and draws no dice. An area that would affect no enemy is not an
option that turn: the monster takes its next action, spell or legendary
action. An action whose template counts "one creature" (the Aboleth's Dominate
Mind) and a template the grid can't place keep the AI's single target. Each
placed area emits `AreaTargeted`, whose `source_id` is the action's slug
(`"fire-breath"`) or the spell's (`"fireball"`).

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

A composite predicate (`orchestrator.py::_combatant_can_see`) layers Blinded
(viewer) and Invisible (target) on top of `can_see`: only Blindsight in range
sees through Blinded, and Blindsight or Truesight in range, with line of
sight, sees an Invisible target — never darkvision. Every SRD
5.2 rule phrased as "if you can see" other than the raw attack-roll `unseen`
row reads this composite: the Dodge action's attack-disadvantage half, Ranged
Attacks in Close Combat, the Opportunity Attack trigger in both directions,
Hide's "out of any enemy's line of sight" gate, and Frightened's line-of-sight
gate (attack-roll disadvantage and the "can't willingly move closer to the
source of fear" movement rule). See
[`docs/dev/spatial-geometry.md`](../dev/spatial-geometry.md#composite-predicate)
for the exact step order.
