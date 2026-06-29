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

- **Real line-of-sight over wall geometry.** `GridTopology.has_line_of_sight`
  returns `True` for any in-bounds pair — it is wired at the range gates but has
  no real model. Needs wall-segment geometry on `GridScene` (today it carries
  only `blocked_cells`, impassable squares) plus a segment-intersection test.
  `packages/dnd5e-engine/src/dnd5e_engine/spatial.py` (`has_line_of_sight`),
  `…/specs.py` (`GridScene`).
- **Cover model** (half / three-quarters / total → AC and DEX-save bonus). No
  `cover_between(a, b)` seam exists; combatants are zone/cell-scoped with no
  positional cover. Surfaces needed: a cover query on the spatial seam, a
  consumer in the attack/save resolvers, and a per-activity "ignores cover for
  save" flag (Sacred Flame / Magic-Missile-style targeting).
- **Grid AoE templates** (cone / sphere / line over cells). No
  `cells_in_template(origin, shape, size)` for AoE target selection.
- **Richer pathfinding.** `GridTopology.shortest_path` is uniform-cost BFS
  (`spatial.py`) — no difficult-terrain cost, threat-aware routing, or
  multi-tile creatures. `GridScene` models only `blocked_cells`; a first-class
  floor-cell set + wall-segment geometry lands together with the LoS model that
  consumes it.

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
- **Counterspell** — ability-check branch (DC 10 + target spell level when
  countering a higher-level slot).
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

- **Monster Dash.** `_handle_dash` (`orchestrator.py`) only services the PC
  bonus-action (Cunning Action) path; a monster cannot double its movement
  budget.
- **Behavior-aware monster action selection.** `select_monster_action`
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)
  returns the first attack by dict order and leaves behavior/flee gating to the
  caller; the monster's authored `BehaviorProfile` does not influence its choice
  inside the engine.
- **Polearm reach > 5 ft.** `Combatant.melee_reach_ft` exists
  (`types/combat.py`) but `PartyMemberSpec` (`specs.py`) has no `reach_ft` field
  to thread an equipped weapon's reach in; the effective reach is always 5 ft.
- **Weapon-damage sidecar asymmetry.** The attack handler reads
  `passive_weapon_to_hit_bonus`, but the damage handler does not symmetrically
  read `passive_weapon_damage_bonus`
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/damage.py`), so a passive
  weapon damage bonus tagged for attacks never reaches the swing's damage.
- **`CheckSpec` has no expertise.** `CheckSpec` carries `proficient_skills` /
  `proficiency_bonus` but no expertise (double-proficiency) input, so
  `resolve_check` cannot apply Expertise
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py`).

## Active-effect change modes

- **Only `add` and `override` modes implemented.**
  `apply_changes_to_check` handles Foundry's `add` and `override`
  `ActiveEffectChange` modes; `multiply` / `downgrade` / `upgrade` / `custom`
  are accepted by the schema but ignored
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/effects.py`). Implement as
  product need surfaces.

## Class / species feature mechanics

- **Sneak Attack & conditional damage riders.** Needs (1) per-target advantage
  *production* — `activities/attack.py` resolves `mode="normal"`, so nothing can
  satisfy an "if you have advantage" precondition; (2) once-per-turn actor state;
  (3) crit-window injection of the conditional extra-damage part. None exist yet.
- **Multi-activity features (e.g. Channel Divinity).** A feature that is a
  *repertoire of alternatives* needs an activity-selection seam (choose Turn
  Undead vs Divine Spark); the engine cannot select among a feature's activities.
- **Real spellcasting-ability mapping.** Caster `@mod` / save-DC resolves
  against a hardcoded `spellcasting_ability="int"`
  (`activities/build_context.py` + the cast path in `orchestrator.py`); the
  class→ability mapping (cleric→WIS, wizard→INT, …) is not read.
- **Feature/subclass-owned `@scale` ids.** `build_scale_values`
  (`activities/scale.py`) resolves `@scale.<owner>.<key>` only when `<owner>` is
  a class/subclass/species slug on a loader owner doc; feature-owned scales
  (e.g. `@scale.channel-divinity-cleric.spark`) are unresolved.
- **Unconsumed `system.bonuses.*` buckets.** The hydration payload folds only
  `system.bonuses.mwak.damage`; the sibling buckets (`rwak`/`msak`/`rsak`
  attack+damage, `spell.dc`, `heal.*`, `abilities.*`) are not normalized, so
  features riding them are inert (`orchestrator.py` `_build_hydration_payload`).

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

---

# dnd5e-srd-data

- **Typeless damage parts in 3 canonical spells.** A `DamagePartBlock` with
  non-empty dice but `types: []` carries no SRD damage type, so the resolver
  logs `damage_part_untyped` and skips the part (the spell under-applies). The
  data must carry the SRD-correct type:
  - `call-lightning` — 4d10 → **lightning**
  - `freezing-sphere` — 10d6 → **cold**
  - `meld-into-stone` — custom "50" → **bludgeoning**

  `packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/`.
- **`applied_effects` not modeled.** Foundry persists a legacy flat
  `appliedEffects` id list alongside the structured `effects[]` slice; the
  per-kind Activity models in `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/common.py`
  don't carry it (the translator drops it). Add the field for round-trip
  fidelity; resolver impact is currently nil (behavior comes from `effects[]`).

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
