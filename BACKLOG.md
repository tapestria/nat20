# Nat20 — Backlog & Gap Inventory

Known gaps in the Nat20 libraries: the `dnd5e-engine` rules/combat engine and
the `dnd5e-srd-data` canonical SRD dataset. This is the single source of truth
for "what the engine does not yet do." It tracks **library** gaps only — host
application concerns (narrators, persistence, world state, UI) are out of scope.

**Update protocol:** when you close a gap, delete its entry in the same PR that
closes it. When you discover one, add it under the right section with a date and
a `packages/…` file anchor. Keep entries engine/data-centric — no host-app paths.

Anchors are current as of `dnd5e-engine` / `dnd5e-srd-data` **v0.1.1**.

---

# dnd5e-engine

## Spatial mechanics (grid backend is in place; these are additive)

- **Per-activity "ignores cover for save" flag.** SRD 5.2's Sacred Flame text
  ("The target gains no benefit from Half Cover or Three-Quarters Cover for
  this save") names a per-activity override that no canonical field backs
  today: `dnd5e_srd_data.schema.common.SaveBlock` carries only `ability`/`dc`,
  no boolean. Closed-2026-07-02 shrink of the former "Cover model" entry —
  `cover_between`, the AC fold, and the Dexterity-save fold all landed (see
  `packages/dnd5e-engine/src/dnd5e_engine/spatial.py::cover_between`,
  `activities/attack.py::resolve_attack`, `activities/save_primitive.py::roll_save`);
  only this per-activity carve-out remains, and it is a DATA-schema addition
  (`schema/feature.py`-style `advancement` field precedent — add a
  `SaveBlock.ignore_cover: bool` + translator support), not an engine gap.
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/common.py` (`SaveBlock`).
- **Richer pathfinding.** `GridTopology.shortest_path` is uniform-cost BFS
  (`spatial.py`) — no threat-aware routing or multi-tile creatures. (Terrain
  COST is closed: `edge_distance` doubles entering a `difficult_terrain_cells`
  cell, consumed by `_handle_move`'s single-step budget check; `shortest_path`
  itself is not yet a cost-aware search over that cost, which is what
  "richer" now refers to.)

## Reactions & off-turn intents (one epic — build as a unit)

The largest missing piece. Every item below depends on the same off-turn
trigger machinery and should be designed together, not piecemeal.

- **Pre-armed reaction queue.** A combatant readies a reaction (e.g.
  "Counterspell vs that caster") on its own turn; the engine holds the intent
  until the trigger fires. No such queue exists in the orchestrator.
- **Cross-actor trigger detection.** When any combatant submits a triggering
  intent (e.g. `CAST_SPELL`), the engine must scan pending reactions and surface
  the match before the triggering action resolves. (`ReactionTriggered` exists
  but is emitted only in a narrow path —
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`.)
- **Off-turn reaction submission.** Every `submit_player_intent` path advances
  the active turn; there is no path for an off-turn actor to spend a reaction.
- **Counterspell** — SRD 5.2 mechanic: the interrupted caster makes a CON
  saving throw against the counterspeller's spell save DC; on failure the spell
  dissipates, the action is wasted, and a slot-cast spell's slot is NOT
  expended. (Entry corrected 2026-07-02 — the previous "ability check DC 10 +
  spell level" text was the retired SRD 5.1/2014 rule; the canonical
  `counterspell.json` save-activity data is already correct.) Two blockers
  discovered while pinning this behavior are tracked below: slot consumption at
  submission, and the flat spell-save-DC approximation.
- **Shield** — the +5 AC reaction does not persist onto the incoming attack roll
  (no per-target AC-bonus rider from an active effect into the attack resolver).
- **Magic Missile force-immunity hook** — with Shield active, the damage path
  must drop the pending force damage.
- **Monster reactions** and **symmetric monster opportunity attacks.** Only the
  PC-reactor / monster-mover direction ships; the monster-reactor / PC-mover
  mirror is deferred pending the reaction queue (`orchestrator.py` notes this at
  the AoO site).
- **Disengage.** The action is named in the intent/event enums
  (`packages/dnd5e-engine/src/dnd5e_engine/events.py`) but has no handler.

## Other combat mechanics

- **Behavior-aware monster action selection.** `select_monster_action`
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)
  returns the first attack by dict order and leaves behavior/flee gating to the
  caller; the monster's authored `BehaviorProfile` does not influence its choice
  inside the engine.
## Discovered during e2e catalog research (2026-07-02)

- **Weapon-tagged to-hit bonus sidecar never consumed.** The orchestrator's
  `_fold_active_effect_changes` folds a weapon-tagged (`applicable_action_types
  == ["attack"]`) `attack.roll.bonus` change into the
  `passive_weapon_to_hit_bonus` sidecar key, but nothing downstream reads it —
  `build_activity_context` only lifts the untagged `passive_to_hit_bonus` into
  `ActivityResolutionContext.passive_attack_bonus`. A +N weapon's to-hit bonus
  therefore never reaches the attack roll via this sidecar (the sibling
  damage-side gap, `passive_weapon_damage_bonus`, was closed in Cluster 2 —
  see `docs/migration/v0.1-to-v0.2.md`)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`).
- **Spell slots consumed at submission, before resolution.**
  `_consume_spell_slot` decrements unconditionally when the intent is
  submitted, before activities resolve, with no refund path — incompatible
  with SRD 5.2 Counterspell's "slot isn't expended" clause and with any future
  cast-interruption
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`, `_consume_spell_slot`).
- **One-round buffs expire on the caster's own turn end.** Casting Shield (or
  any 1-round self-buff) emits `effect_applied` then `effect_expired(reason=
  duration)` in the same tail — `_tick_durations_at_turn_end` collapses the
  duration before the effect could ever matter
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`,
  `_tick_durations_at_turn_end`).
- **Disengage falls through to the generic Action pipeline and ends the
  turn.** A same-turn Disengage→Move sequence raises
  `IntentRejectedError(reason="not_actor_turn")` because the disengage intent
  calls `_advance_turn` (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`);
  subsumed by the Disengage handler item above but the turn-ending fall-through
  is a distinct defect.
- **Second, dead `condition_immunities` surface.** `dispatch.py` carries a
  host-owned condition-immunities path unused by live combat; a future
  `Combatant.condition_immunities` fix must not collide with it
  (`packages/dnd5e-engine/src/dnd5e_engine/dispatch.py`).
- **Dead code: `rules/gambits.py::select_action`** (the legacy per-profile
  gambit picker) has no callers in `src/`; `ActionType.SHORT_REST`
  (`types/intent.py`) is an orphaned member of the legacy dispatch enum —
  decide disposition when the rest seam and monster-behavior clusters land.

## Class / species feature mechanics

- **Sneak Attack & conditional damage riders.** Needs (1) per-target advantage
  *production* — `activities/attack.py` resolves `mode="normal"`, so nothing can
  satisfy an "if you have advantage" precondition; (2) once-per-turn actor state;
  (3) crit-window injection of the conditional extra-damage part. None exist yet.
- **Multi-activity features (e.g. Channel Divinity).** A feature that is a
  *repertoire of alternatives* needs an activity-selection seam (choose Turn
  Undead vs Divine Spark); the engine cannot select among a feature's activities.
- **Unconsumed `system.bonuses.*` buckets (partial — Cluster 4 closed the
  attack/damage + spell.dc families).** `heal.*` and `abilities.check` /
  `abilities.skill` remain inert: no per-actor sidecar consumer exists for
  them today. `activities/heal.py::resolve_heal` never reads any bonus
  sidecar off `ActivityResolutionContext` (unlike `attack.py`'s
  `passive_*_damage_bonus` fields). `activities/check.py::resolve_check`
  reads a `ctx.check_modifiers[actor_id]["ability_mods"/"skills"]` sidecar,
  but `build_activity_context` always passes `check_modifiers={}` —
  `_fold_active_effect_changes` (`orchestrator.py`) has no branch that
  populates it from active-effect changes (only condition-derived
  projections land there). (`mwak`/`rwak`/`msak`/`rsak` attack+damage and
  `spell.dc` are now folded — see `docs/migration/v0.1-to-v0.2.md`.)

### Passive-stat projection (`activities/passive_stats.py`)

The interpreter projects always-on `dr` (damage resistance), `di` (immunity),
and `senses` at combat start. The rest of the spec-§D allowlist is recognized
but routed to `skipped_keys` (deferred) for lack of a `Combatant` landing zone:

- **Activation-gated resistances** (e.g. Rage's slashing/piercing/bludgeoning
  resistance while raging). Honored as `disabled`/`transfer` and deliberately
  not projected at rest; closing this means reading `system.traits.dr.value` off
  *active* effects in the damage path.
- **Movement changes** (`system.attributes.movement.*`) — typed non-walk modes
  (climb/swim/fly/burrow) and symbolic `@scale` values; needs a typed movement-
  modes field on `Combatant` + formula resolution (collapsing to scalar is lossy).
- **`condition_immunities`** (`system.traits.ci.value`) — needs a new
  `Combatant.condition_immunities` field *and* a consumer in the condition-
  application path (Nature's Ward `ci:poison` is the first real case).
- **`di` / `dv`** (damage immunity / vulnerability) from features/species — `di`
  is handled defensively but untested; vulnerability has no `Combatant` field.
- **Ability scores, proficiency grants, `ac.calc`, languages** — each needs its
  own landing zone + apply logic (ability-modifier path, proficiency sets +
  roll-path consumer, AC recomputation, languages field).

## Rest & recovery

- **No Short Rest handler.** `SHORT_REST` is in the intent enum
  (`types/intent.py`) but the orchestrator has no handler — no hit-dice spend,
  class-feature recovery, or Second Wind.
- **No Long Rest.** No HP/slot recovery or daily-feature reset.

## Blocked

- **`custom` `ActiveEffectChange` mode — needs a product decision** (2026-07-02).
  No Foundry-core semantics to port: Foundry itself delegates `custom` to
  host-registered `applyChangeCustom` callbacks, so there is no SRD or
  in-repo ground truth for what it should do in this engine
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/effects.py`,
  `apply_changes_to_check` — `multiply`/`upgrade`/`downgrade` are
  implemented; `custom` is left a documented no-op). Downstream data
  carries none today — verified: `grep -rn '"mode": "custom"'
  packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/` returns zero
  matches. Blocked on a maintainer decision for what (if anything) `custom`
  should mean in a host-agnostic engine with no callback registry.

---

# dnd5e-srd-data

No open entries.

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
