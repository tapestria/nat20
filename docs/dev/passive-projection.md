# Passive-stat projection (Cluster 8 design note)

Design note for the "Passive-stat projection" `BACKLOG.md` section — the four
gaps where a creature's always-on or activation-gated defensive/movement stats
(damage resistance while raging, condition immunity, damage vulnerability,
granted-feature movement modes) are declared in the canonical dataset but never
reach the live `Combatant` or the damage/condition pipelines that consume them.
Written before implementation per the autonomous gap-closing campaign's epic
protocol (`specs/e2e-scenario-catalog.md`, Cluster 8: C08-S01..S04).

The four gaps do not share one machinery the way the reaction queue did; what
they share is a diagnosis — a producer/consumer split where the consumer is
already wired and only the producer is missing (S01, S03), or where neither the
field nor the consumer exists yet (S02, S04). This note names the three
projection *tiers* stat data can travel through, places each gap in its tier,
and records the semantic decisions that are not mechanically forced.

## SRD ground truth

Rules verified against the SRD 5.2 content pack under
`packages/dnd5e-srd-data/raw_sources/` (never model memory):

- **Rage** (`classes24/barbarian/class-features/rage.yml`): *"you have
  Resistance to Bludgeoning, Piercing, and Slashing damage"* while raging.
  Canonical `features/rage.json` `passive_effects[0]` carries
  `changes` including `{"key": "system.traits.dr.value", "mode": 2, "value":
  "slashing"}` (+ piercing + bludgeoning) and is `disabled: true` — an
  activation-gated effect, off at rest.
- **Nature's Ward** (`classes24/druid/subclass-features/circle-of-land/natures-ward.yml`):
  *"You can't be Poisoned."* Canonical `features/natures-ward.json`
  `passive_effects[0]` is `disabled: false, transfer: true` (always on) with
  `changes = [{"key": "system.traits.ci.value", "mode": 2, "value":
  "\"poison\""}]`. Note the token is `poison`, not `poisoned`.
- **Damage Vulnerability** (§Damage Vulnerability, rules glossary): *"applying
  twice the normal damage"*. `monsters/skeleton.json` carries
  `damage_vulnerabilities: ["bludgeoning"]`.
- **Roving** (`classes24/ranger/class-features/roving.yml`): *"Your Speed
  increases by 10 feet ... You also have a Climb Speed and a Swim Speed equal
  to your Speed."* Canonical `features/roving.json` `passive_effects[0]` is
  always on with `changes = [{"key": "system.attributes.movement.walk", "mode":
  2, "value": "10"}, {"key": "system.attributes.movement.climb", "mode": 4,
  "value": "@attributes.movement.walk"}, {"key":
  "system.attributes.movement.swim", "mode": 4, "value":
  "@attributes.movement.walk"}]`.

## The three projection tiers

Stat data reaches a resolver through exactly one of three tiers. Every gap
below lands in one of them; the tier choice is forced by *when* the datum is
known and *how long* it is active.

1. **Build-time, always-on** — `activities/passive_stats.py::interpret_passive_stats`,
   called once per PC by `build_party.py::build_party_member`. Reads a PC's
   species `trait_grants`/`senses` and the `changes` of every *always-on*
   granted-feature `passive_effect` (`transfer and not disabled`,
   `build_party.py:81`) and projects them onto the immutable `PartyMemberSpec`
   fields (`damage_resistances`, `damage_immunities`, `senses`, …). This tier
   is the right home for a stat that is **on for the whole combat and known at
   build time**. The interpreter is pure (zero I/O, never raises); allowlist
   misses go to `skipped_keys` for the calling seam to log.

2. **Combat-time, active-effect fold** — `orchestrator.py::_fold_active_effect_changes`,
   run per intent inside `_project_target_modifiers` over each combatant's live
   `active_effects`. Folds a *currently-live* `ActiveEffect`'s Foundry-shaped
   `changes` into the per-target sidecar dicts the resolvers read
   (`passive_damage_modifiers[entity_id]`, save/AC entries). This is the right
   home for a stat that is **gated on a runtime activation** (Rage must be
   invoked first) — the effect only appears in `active_effects` once its
   feature fires, so the fold naturally sees it exactly while it is active and
   never at rest.

3. **Per-intent, target-modifier projection** — `orchestrator.py::_project_target_modifiers`,
   the caller of tiers 2's fold. Merges each combatant's *static* `Combatant`
   defensive lists (`damage_resistances`/`damage_immunities`) plus SRD-condition
   projections (`rules/conditions.py::project_passive_damage_modifiers`) into
   `passive_damage_modifiers[entity_id]`. This is the right home for a stat that
   lives as a **static field on the `Combatant`** (hydrated from a monster
   template or a PC spec) and must be surfaced into the damage sidecar every
   intent.

`apply.py::apply_damage` is the shared consumer for tiers 2 and 3: it unions the
static `Combatant.damage_resistances`/`damage_immunities` with the sidecar's
`resistances`/`immunities`/`vulnerabilities` lists and applies
`vuln ×2 → resist //2 → immune ⇒0`. `effects.py::apply_activity_effects` is the
consumer for the condition path (tier-1 static field, gate at emit).

## Gap → tier placement

| Gap | Tier | Why |
|-----|------|-----|
| **C08-S01** Rage `dr` while raging | **2** (active-effect fold) | Rage is activation-gated (`disabled: true`); the resistance must appear only while the Rage `ActiveEffect` is live. Tier 1 correctly excludes it (fails `not disabled`). The fold is the only tier that sees the effect exactly when active. |
| **C08-S02** Nature's Ward `ci:poison` | **1** (build-time, always-on) for the field + a **consumer gate** at the condition emit | Nature's Ward is always on; the immunity is known at build time and belongs on the static spec/`Combatant`. The blocking itself is a new consumer in the condition-application path. |
| **C08-S03** Skeleton `dv:bludgeoning` | **3** (per-intent target-modifier) | The vulnerability is a static monster-template fact hydrated onto the `Combatant`; it must be folded into the damage sidecar every intent, exactly like the existing resistances/immunities merge. |
| **C08-S04** Roving movement modes | **1** (build-time, always-on) | Roving is always on; the walk bonus and the climb/swim modes are known at build time and belong on the immutable spec (and, copied, the live `Combatant`). |

## S01 — the `system.traits.dr.value` fold and the mode=2 trap

The producer fix is one branch in `_fold_active_effect_changes`. The trap the
catalog calls out: the fold's per-change loop opens with
`if change.mode != "add": continue`, and it then coerces every value into a
signed numeric string (`"+2"`) before dispatching on `key`. Rage's `dr` change
arrives as `mode="add"` (Foundry `mode=2` → `"add"` via `effects.py::_MODE_MAP`)
with `value="bludgeoning"` — a **damage-type string, not a numeric bonus**. It
therefore *passes* the mode guard but is mangled into `"+bludgeoning"` and, with
no matching `key` branch, silently dropped.

**Decision:** handle `system.traits.dr.value` at the very top of the per-change
loop, *before* the mode guard and the numeric-coercion machinery. Foundry
`mode=2` on this key means "add this damage-type to the resistance **set**", not
"add to a numeric bucket"; the branch appends the cleaned type string into
`per_target_dmg["resistances"]` (the list-valued sidecar key `apply.py` already
reads via `sidecar.get("resistances", ())`) and `continue`s. This bypasses the
numeric guard cleanly for this one key and touches no other branch. Pure
producer-side fix — `apply.py`'s consumer is unchanged.

S01 is pinned as a same-seed A/B: `raged_total == base_total // 2` at
`rng_seed=8` (both `6` today). The fix is RNG-neutral — it reads an existing
live effect's data into a sidecar list; it draws no dice and does not reorder
the stream. Same-seed invariance is verified by the A/B test itself.

## S02 — condition-immunity field + gate; the `poison`/`poisoned` bridge

Three pieces, tier-1 field + new consumer:

- **Field:** `Combatant.condition_immunities: list[str]` and matching
  `PartyMemberSpec`/`EncounterMemberSpec.condition_immunities`, mirroring the
  existing `damage_resistances`/`damage_immunities` pattern, threaded through
  `_build_pc_combatants`/`_build_foe_combatants`.
- **Producer:** a `_CI_KEY = "system.traits.ci.value"` branch in
  `interpret_passive_stats`, appending to a new
  `DerivedPassiveStats.condition_immunities` tuple; `build_party_member`
  projects it onto the spec.
- **Consumer gate:** in `effects.py::apply_activity_effects`, the
  `ConditionApplied` emit loop skips a status the target is immune to.

**The `poison`/`poisoned` bridge.** The canonical `ci` token is `poison`
(a damage-type-style trait key — verified in `natures-ward.json` and the raw
Foundry YAML), but the applied condition is `poisoned` (a `ConditionType`
Literal member). Every *other* SRD condition's `ci` token already equals its
condition slug; poison/poisoned is the sole irregular pair. The interpreter
normalizes the one irregular token via a small alias table
(`_CI_TOKEN_TO_CONDITION = {"poison": "poisoned"}`) so `condition_immunities`
stores condition slugs and the emit-gate is a plain `status in
target.condition_immunities` membership test. This is deliberately a
single-entry alias, not a general trait-vocabulary engine (YAGNI).

**Emit-vs-suppress decision:** the gate **suppresses the `ConditionApplied`
outright** for an immune condition (the `EffectApplied` rider still fires
narratively, so the effect's presence is observable but the condition never
attaches). The catalog leaves this to the implementer, citing `di`'s
`DamageApplied(amount=0)` "emit-but-neutralize" precedent as an alternative.
Suppress is chosen here because a condition has no "amount" to neutralize — it
is binary present/absent, so emitting a `ConditionApplied` the engine
simultaneously treats as not-applied would be a lie in the event log that every
downstream condition-duration/tick reader would then have to special-case. The
scenario only pins that `poisoned` must never attach; suppress satisfies that
with the least surprising event stream.

**Out of scope / do not touch:** `dispatch.py::DispatchContext.condition_immunities`
is a *second, dead, host-supplied* condition-immunity surface on the legacy
duck-typed-intent resolver path (`_resolve_combat`), unreachable from
`submit_player_intent`/the typed-Activity resolver. It is not wired to any
`Combatant` field and is irrelevant to this gap. The new
`Combatant.condition_immunities` must not collide with or wire into it; the
BACKLOG "Second, dead condition_immunities surface" entry stays.

## S03 — damage vulnerability producer

The consumer (`apply.py`, `vulnerabilities = set(sidecar.get("vulnerabilities",
()))`) is fully wired; every producer is missing. Tier-3 fix:

- **Field:** `Combatant.damage_vulnerabilities: list[str]` and
  `EncounterMemberSpec.damage_vulnerabilities`, mirroring the resistances/
  immunities fields.
- **Template hydration:** `_build_foe_combatants` hydrates
  `damage_vulnerabilities` from the monster template
  (`get_lib_loader().get_monster(slug).damage_vulnerabilities`) when the spec
  leaves the field empty — so a `monster_template_slug="skeleton"` foe picks up
  its SRD-canonical bludgeoning vulnerability without the host restating it.
  **Scoped to vulnerabilities only** (not resistances/immunities): those two
  already have a field and are host-populated by existing convention; adding
  auto-hydration for them would change existing combats' behavior. Vulnerability
  has *no* prior field, so hydrating it is zero-risk and closes the exact gap.
- **Fold:** `_project_target_modifiers` folds `c.damage_vulnerabilities` into
  `passive_damage_modifiers[c.entity_id]["vulnerabilities"]`, mirroring the
  existing resistances/immunities merge block exactly.

RNG-neutral: no dice drawn, no stream reorder. Pinned by
`vuln_total == 2 * 8` at `rng_seed=1` (the mace's undoubled seeded hit is `8`).

If this work also gives `di` (damage immunity) its missing test coverage
cheaply, that is noted, not expanded into.

## S04 — movement modes: the typed carrier and the `@attributes.movement.*` rule

Tier-1 fix with two parts.

**Walk-speed bonus.** A literal-int `system.attributes.movement.walk` change
(Roving's flat `+10`, `mode=2`) folds additively into a new
`DerivedPassiveStats.walk_speed_bonus: int`; `build_party_member` composes
`base_speed = species_walk + derived.walk_speed_bonus`. This needs no formula
resolution — the value is a plain literal.

**Non-walk modes and the symbolic token.** Climb/swim/fly/burrow modes carry
either a literal int or the symbolic token `@attributes.movement.walk` (Roving's
climb/swim are `mode=4` upgrade, value `@attributes.movement.walk` — "equal to
your Speed"). The interpreter resolves this **single token** against the
resolved walk speed (`base_walk_speed + walk_speed_bonus`), computed after the
walk-bonus fold so the climb/swim inherit the *boosted* speed. This is a
minimal, purpose-built resolution for the one `@attributes.movement.walk` token
this scenario needs — **not** a general formula engine (YAGNI). Any other
`@…`-token movement value falls to `skipped_keys`, unchanged.

**The typed carrier.** Collapsing every mode to a single scalar (as `base_speed`
does for walk) is lossy — a creature with a `40` climb and a `20` swim cannot be
represented by one number. The new field is therefore a typed multi-mode
carrier, `CombatantMovementModes(climb: int | None, swim: int | None, fly: int |
None, burrow: int | None)`, mirroring `CombatantSenses`'s exact shape (frozen,
`extra="forbid"`, `None` = mode unavailable). It lands on both
`PartyMemberSpec` and `Combatant` (and by extension the `LiveCombatView.initiative`
combatant view), closing the "lands on the combatant" half of the gap. Like
`CombatantSenses`, it is a field-type carrier, not a top-level public export.

The pinned e2e asserts only the build-seam `spec.base_speed == 40` (the walk
half); the typed carrier is required by the API-delta contract and is pinned by
unit tests on the interpreter and the build seam.

## Public-surface additions (all additive)

- `CombatantMovementModes` (new type, `activities/passive_stats.py`) — field
  type only, not a top-level `__all__` export (mirrors `CombatantSenses`).
- `DerivedPassiveStats.condition_immunities`, `.walk_speed_bonus`,
  `.movement_modes` (new fields on the interpreter's output type).
- `PartyMemberSpec.condition_immunities`, `.movement_modes` (new fields).
- `EncounterMemberSpec.condition_immunities`, `.damage_vulnerabilities` (new
  fields).
- `Combatant.condition_immunities`, `.damage_vulnerabilities`, `.movement_modes`
  (new fields).

No `CombatEvent` union member is added or changed (`ConditionApplied` already
exists). `rules/` and `dispatch.py` stay pure and untouched.

## Explicitly out of scope

- **Ability scores, proficiency grants, `ac.calc`, languages** — the surviving
  fifth bullet of the BACKLOG subsection. Each needs its own landing zone +
  apply logic (ability-modifier path, proficiency sets + roll-path consumer, AC
  recomputation, a languages field); none has a Cluster 8 catalog scenario.
- **The dead `dispatch.py` condition-immunities surface** (see S02 above).
- **A general Foundry-formula resolver** — only the single
  `@attributes.movement.walk` token is handled.
