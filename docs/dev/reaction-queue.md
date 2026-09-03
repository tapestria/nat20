# Reaction queue

How the engine models reactions: the pre-armed reaction queue, cross-actor
trigger detection, Counterspell, Shield, the monster-reactor opportunity
attack, and Disengage. These share one piece of machinery and were designed
together rather than piecemeal; this note is that shared design.

**Hard governing constraint: reactions are pre-armed auto-fire.** There is no mid-resolution host round-trip anywhere
in this design — `submit_player_intent` / `advance_monster_turn` remain the
only two ingress points, and a queued reaction is drained and fully resolved
entirely inside whichever of those two calls processes the trigger. A host
never gets asked "do you want to react?" mid-resolution; it must pre-declare
the reaction (via a normal on-turn `"ready"` intent) before the trigger ever
fires.

## SRD ground truth

- **Ready** (`the Foundry SRD source packs, content24/chapter-1/actions.yml`,
  journal entry "Ready"): *"Prepare to take an action in response to a
  trigger you define... you take your Reaction to take that action."*
- **Reactions** (`appendices/appendix-d-rule-references.yml`, journal page
  `2VqLyxMyMxgXe2wC`): *"You can take a Reaction on another creature's turn
  ... Once you take a Reaction, you can't take another one until the start
  of your next turn."*
- **Opportunity Attacks** (`chapter-1/combat.yml`): *"You can make an
  Opportunity Attack when a creature that you can see leaves your reach... The
  attack occurs right before it leaves your reach."*
- **Disengage** (`chapter-1/actions.yml`): *"Your movement doesn't provoke
  Opportunity Attacks for the rest of the turn."*
- **Counterspell** / **Shield** (`canonical/spells/counterspell.json` /
  `shield.json` `description` fields, traced verbatim to
  `the Foundry SRD source packs, spells24/...`) — quoted in full in each
  reaction's own section below.

## Modeling decision: `"ready"` is the pre-arm intent, not true SRD Ready

The engine has no interactive prompt seam and the hard constraint forbids
adding one. Real SRD Ready lets a player define an arbitrary trigger in
prose; Counterspell/Shield's own casting time is literally `"reaction"` with
a fixed trigger condition baked into the spell. This cluster reuses the
existing, already-unhandled `IntentType` literal `"ready"` as the engine's
**pre-arm mechanism**: a combatant spends their on-turn Action submitting
`PlayerIntent(intent_type="ready", spell_id=..., slot_level=..., reaction_trigger=...)`,
which register a pending reaction and do nothing else (no dice, no
`ReactionTriggered` yet). No new `IntentType` member is needed — `"ready"`
was already in the closed enum, previously handled as an inert
Action-consuming no-op. The action-economy shape is unchanged: readying
still spends the Action (not the Reaction) at declaration time; the
Reaction itself is spent later, only when the trigger actually fires.

`reaction_trigger` moves from `str | None` to a closed
`ReactionTrigger = Literal["cast_spell", "hit_by_attack",
"targeted_by_magic_missile"]` (`orchestrator.py`) — the three trigger
values this cluster's concrete reactions need, matching the examples
already named in `PlayerIntent.reaction_trigger`'s own docstring. Additive
only in the sense that no public name changes; the field's *accepted value
set* narrows from "any string" to these three, which is the point of the
typed-semantics rule (an unconsumed `str` sidecar cannot be validated at
all).

## Queue data structure

```python
@dataclass(frozen=True)
class _PendingReaction:
    owner_id: str
    trigger: ReactionTrigger
    spell_id: str | None
    slot_level: int | None
```

`_LiveCombat` gains:

- `pending_reactions: list[_PendingReaction]` — the queue itself. A `"ready"`
  intent appends one entry (replacing any prior entry for the same owner —
  a combatant has at most one action per turn, so at most one freshly-armed
  reaction at a time). List, not a per-owner dict, so multiple different
  combatants can have independent pending reactions live simultaneously and
  the drain can walk them in a defined order.
- `reaction_effects_pending_expiry: dict[str, list[tuple[str, str, str]]]` —
  the off-turn-buff-expiry companion structure (see "Duration-fix
  semantics" below), keyed by the effect's caster/owner id.

## Cross-actor trigger detection + firing order

`_pop_pending_reaction(live, trigger, *, triggering_actor_id, only_owner_id=None)`
scans `live.initiative` **in initiative order** (documented firing order —
ties and multi-reactor cases resolve deterministically by whoever acts
first in the round) for the first combatant that: is not the triggering
actor itself, matches `only_owner_id` when given (the `hit_by_attack` /
`targeted_by_magic_missile` triggers are owned by the creature actually
under attack/targeted — a bystander's readied reaction never fires for
someone else's hit), is alive, has `reaction_available`, and holds a
`_PendingReaction` for `trigger`. The match is removed from the queue and
returned; a reaction is drained (and spent) exactly once. `None` when
nothing qualifies — the triggering action proceeds untouched, which is the
overwhelmingly common case and must stay cheap (a linear scan over a queue
that is empty for almost every intent).

`_drain_targeted_reactions(live, *, trigger, triggering_actor_id, targets)`
is the per-target-list wrapper `hit_by_attack` / `targeted_by_magic_missile`
share: for each target in the triggering action's resolved target list, pop
+ fully resolve one matching reaction (below), returning the set of target
ids whose reaction fired (Shield vs. Magic Missile's force carve-out needs
that set — see below).

## Interaction points in the orchestrator

Three call sites drain the queue, each for a different trigger:

1. **`submit_player_intent`, `cast_spell` branch, BEFORE `_consume_spell_slot`**
   — `trigger="cast_spell"`, `triggering_actor_id` = the caster. This is
   Counterspell's hook. It runs earlier than every other cast-time gate
   (out-of-range / Hellish-Rebuke-target / action-economy have already been
   validated and the Action already consumed by this point, matching "the
   action... used to cast it is wasted" — only the SLOT gate has not yet
   run).
2. **`submit_player_intent`, `cast_spell`/`attack` branches, right after
   `_resolve_targets`** — `trigger="hit_by_attack"` for an `"attack"` intent,
   `trigger="targeted_by_magic_missile"` for a `spell_id == "magic-missile"`
   cast, both scoped to the resolved `targets` list. This is Shield's hook
   for the PC-attacker / PC-attacked and PC-caster / PC-targeted directions.
3. **`advance_monster_turn`, right before `_build_hydration_payload`** (the
   monster attack path) — `trigger="hit_by_attack"`, `targets=[chosen_target]`
   (the PC the monster is about to attack). This is Shield's hook for the
   monster-attacker / PC-defender direction — the one a pinned scenario actually pins.

A fourth, unrelated interaction point — `_handle_move` (the PC move
handler) — fires the monster-reactor opportunity attack (see below). It
does **not** go through `pending_reactions` at all (see "Why AoO is not a
queued reaction").

## Counterspell (a pinned scenario, S02)

> "You attempt to interrupt a creature in the process of casting a spell.
> The creature makes a Constitution saving throw. On a failed save, the
> spell dissipates with no effect, and the action, Bonus Action, or Reaction
> used to cast it is wasted. If that spell was cast with a spell slot, the
> slot isn't expended." — `canonical/spells/counterspell.json`

The canonical Counterspell activity (`dnd5eactivity000`) is already
`kind: "save"`, `save.ability: ["con"]`, `save.dc.calculation:
"spellcasting"` — the SRD 5.2 (2024) mechanic (an unconditional CON save
against the counterspeller's own spell save DC), not the retired 2014
ability-check-vs-DC-10-plus-level mechanic a stale prior BACKLOG line still
names (corrected in the same PR that lands this cluster, per BACKLOG's own
"close a gap → delete/correct its entry" protocol). Because the canonical
data is already right, the implementation is narrow: no bespoke DC formula,
no new check-kind invocation — Counterspell's own `SaveActivity` is resolved
through the **existing, unmodified** `activities/save.py::resolve_save`
resolver, with the interrupted caster as sole target.

`_drain_counterspell_reaction(live, current, actor_id, intent)`:

1. Pop a `"cast_spell"`-trigger reaction (any owner other than the caster).
   `None` → not countered, fall through to the caster's normal cast.
2. Consume the reactor's `reaction_available` and spell slot (Counterspell's
   own slot is spent regardless of outcome — only the *interrupted* spell's
   slot is conditionally spared, below) and emit
   `ReactionTriggered(actor_id=reactor, reaction_name="counterspell")`.
3. Build an `ActivityResolutionContext` with `caster=reactor`,
   `targets=[the interrupted caster]`, resolving the reactor's REAL
   spellcasting ability via the already-shipped
   `_resolve_caster_spellcasting_ability` (an earlier release's real-ability-score
   path — see "Independently-verified gap already closed" below) and run
   Counterspell's `SaveActivity` through `resolve_activity`. This emits
   exactly one `SaveRolled` (no damage, no effect riders — Counterspell's
   own `damage.parts` / `effects` are both empty).
4. `succeeded=True` → return `False` (not countered); the caller proceeds
   to `_consume_spell_slot` and resolves the triggering spell exactly as if
   no reaction had fired.
5. `succeeded=False` → emit `CastFailed(actor_id=<interrupted caster>,
   spell_id=<their spell>, reason="countered")`, call `_advance_turn`
   directly (mirroring the existing `no_slot` / `no_action_economy`
   `CastFailed` branches' own `_advance_turn` call — the shipped precedent
   for "a failed cast still ends the turn, with no further activity this
   turn"), and return `True` — the caller returns immediately, **before**
   `_consume_spell_slot` ever runs for the triggering spell.

### Slot-consumption redesign (closes the discovered "slots consumed at
submission" entry)

Two options were on the table (per the BACKLOG entry and this cluster's
task brief): move `_consume_spell_slot`'s decrement to resolution-time, or
add a refund path that undoes an already-applied decrement. **Chosen: a
third option, already implied by a pinned scenario's own catalog entry — drain the
reaction queue even earlier than `_consume_spell_slot`, so a countered cast
never reaches the gate at all.** `_consume_spell_slot` itself is completely
unmodified. Rationale: a refund path needs to reverse a decrement + risks
double-refund bugs across `_advance_turn` call variations; moving the gate
later would ripple through every other cast-time check that currently runs
before it (out-of-range, Hellish Rebuke, action economy) for no benefit.
Short-circuiting before the gate is the smallest, most surgical change —
zero risk of the slot ever being touched for a countered cast, and zero
new code paths for the *uncountered* case (which is byte-identical to
today).

### Independently-verified gap already closed

The task brief's source material (and a prior BACKLOG-adjacent note) flagged
a second, compounding bug: PC spell save DC allegedly still used the flat
Avrae-era approximation (`8 + 2 + max(0, attack_bonus-2)`) instead of the
real `8 + proficiency_bonus + ability_mod(spellcasting_ability)` formula,
which would make this scenario's `dc=15` assertion unreachable. **Verified
empirically before writing any C06 code:** `build_context.py::_save_dc`
already implements the real formula whenever a `spellcasting_ability`
resolves (landed in an earlier release, per that function's own docstring —
`"per an earlier release (a pinned scenario), its save DC now runs the honest SRD 5.2
formula"`). A direct probe (casting `counterspell` on-turn as a level-5
INT-18 wizard, `rng_seed=9` then `rng_seed=1`) reproduced the catalog's
exact pinned numbers — `dc=15, roll_total=15, succeeded=True` and
`dc=15, roll_total=5, succeeded=False` — with **zero** new code. This
sub-bug needed no fix in this design; it is called out here so the
"compounding gap" language in the BACKLOG/brief is not silently
re-litigated by a future reader.

### Slot and range gating (C17 R4) — skip, don't pop

C17 added an `eligible=` predicate to `_pop_pending_reaction` (the shared
queue-pop primitive both Counterspell and readied-cast drains call): a
candidate reaction that matches the trigger and owner is only popped when
`eligible(reactor, pending)` also returns `True`. `_drain_counterspell_
reaction`'s own `_eligible` closure looks up the ARMED spell per candidate
(`get_lib_loader().get_spell(pending.spell_id or "counterspell")`) — a
non-Counterspell readied spell armed on the `"cast_spell"` trigger is
therefore gated by ITS OWN level and range, not Counterspell's — and checks
two things: an unexpended slot at the readied level (`_slot_available`,
checked against BOTH pools — see below) when the spell's `level > 0`, and,
when the spell carries a `range.value`, `_in_range_with_los(topology,
reactor_zone, caster_zone, range.value)`. Geometry-free setups (zone
topology, or either zone untracked) skip the range check entirely — "no
geometry ⇒ no penalty" is the engine-wide convention, unchanged. A
candidate that fails `eligible` is left in `live.pending_reactions` (still
armed for a later trigger) and the scan continues to the next candidate in
initiative order — the reactor's own Reaction and slot are both untouched.
This is a **skip**, never a pop-then-refund: the reaction was never
consumed in the first place.

### Two-pool slot consumption (C17 R3)

Every slot-consuming site in this module — the Counterspell drain, a
readied-cast resolve (Shield), and the on-turn cast gate — now routes
through `_slot_available(live, entity_id, slot_level)` /
`_take_spell_slot(live, entity_id, slot_level)` rather than reading
`live.spell_slots_by_entity` directly. SRD §Multiclassing lets either pool
cast either prepared spell (the engine has no spell-list gate), so both
functions check/draw from the regular Spellcasting pool FIRST, then Pact
Magic — a caster holding a slot at the same level in both pools always
spends the Spellcasting one. There is no way to force a specific pool
(BACKLOG.md).

## Shield (a pinned scenario, S04)

> "Until the start of your next turn, you have a +5 bonus to AC, including
> against the triggering attack, and you take no damage from *Magic
> Missile*." — `canonical/spells/shield.json`

Shield's own canonical activity (`dnd5eactivity000`) is a `utility` kind
carrying one effect ref (`Bv3EoHGfYCprLdG1`) whose `PassiveEffect` change is
`{key: "system.attributes.ac.bonus", mode: add, value: "5"}`,
`duration.rounds: 1`. Casting it through the **existing, unmodified**
activity resolver (a `utility` activity with effect riders already applies
them per target — Task 9-A FIX 2) needs three additive consumption-side
fixes; nothing about the resolver itself changes.

`_resolve_readied_spell_cast(live, reactor, popped)` is the shared "auto-fire
a readied self-buff reaction spell to completion" helper (used by both the
`hit_by_attack` and `targeted_by_magic_missile` hooks): consume the
reactor's reaction + spell slot, emit `ReactionTriggered`, build a context
with `caster=reactor, targets=[reactor]`, and walk the spell's own
activities. For Shield this emits `EffectApplied` (the +5 AC rider) with no
attack roll and no dice at all — consistent with a pinned scenario's "Shield never
touches the roll, only the AC comparison" pin.

### AC-bonus consumption (three compounding drop points, closed together)

1. `_fold_active_effect_changes` gains a key alias:
   `"system.attributes.ac.bonus"` normalizes to the existing `"ac.bonus"`
   branch (which already writes `per_target_entry["passive_ac_bonus"]`) —
   an alias, not a new branch. The branch existed; the Foundry-native key
   Shield's own effect actually carries never reached it.
2. `ActivityResolutionContext` gains `passive_ac_bonus: dict[str, int]`.
   `build_activity_context` extracts `save_modifiers[id]["passive_ac_bonus"]`
   (a signed string, e.g. `"5"`) via `roll_expr` into this int-keyed sidecar
   — `roll_expr` on a plain literal draws no dice, so this extraction never
   perturbs the seeded stream (verified: Shield's own bonus is a flat `"5"`,
   never a dice formula, in the SRD corpus).
3. `attack.py::resolve_attack` folds `ctx.passive_ac_bonus.get(target_id, 0)`
   into `effective_ac` alongside the existing cover-bonus fold, symmetric
   with a pinned scenario's cover-AC consumer shape.

### Duration-fix semantics (closes the discovered "1-round buffs expire on
caster's own turn end" entry, for the reaction-applied path)

`_tick_durations_at_turn_end` ticks a round-scoped effect at its **caster's
own** `TurnEnded` — correct for the common case (a buff cast on the
caster's own turn: Bless cast on your turn lasts through your next
`N` turn-ends). It is wrong for a reaction-applied buff: Shield fires
*during the attacker's turn*, so the caster's (the reactor's) own
`TurnEnded` doesn't recur until the caster's NEXT turn ends — one full turn
too late; the SRD text is explicit that Shield lasts only "until the start
of your next turn."

Rather than rewriting the generic per-turn-end tick (which the wide
existing on-turn-cast test surface depends on staying exactly as-is), this
cluster adds a narrow, additive companion mechanism scoped to
reaction-applied effects only: `_resolve_readied_spell_cast` inspects the
`EffectApplied` events it just caused; any effect landing on the reactor
with a non-`None` `duration.rounds` is registered in
`live.reaction_effects_pending_expiry[reactor_id]`. `_emit_apply_turn_started`
(already the single reset point for Action/Bonus Action/Reaction/movement
budgets) gains one more step: pop any pending entries keyed to the
combatant whose turn is starting and, if the effect is still present, emit
`EffectExpired(reason="duration")` immediately (before any other event this
turn). This expires the effect at the **owner's own next `TurnStarted`** —
exactly the SRD boundary — rather than waiting for a `TurnEnded` that may
be an entire round later. The existing turn-end tick is untouched and
simply never finds the effect still present by the time it would otherwise
run (already-expired entries are no-ops for it). Scoped deliberately to
reaction-fired effects only: a hypothetical multi-round reaction buff isn't
in this design's SRD scope, so no richer round-counting rule was built for
a case nothing here exercises.

### Magic Missile carve-out (a pinned scenario) — narrow, not a force-immunity mechanic

> "...and you take no damage from *Magic Missile*." (same Shield text,
> above) — an explicit SRD *spell-specific* carve-out, not a general force
> resistance/immunity the creature otherwise has.

`_drain_targeted_reactions(..., trigger="targeted_by_magic_missile", ...)`
returns the set of target ids whose Shield reaction just fired. When the
triggering cast's `spell_id == "magic-missile"`, `submit_player_intent`
injects a **transient** `"force"` entry into
`payload["passive_damage_modifiers"][target_id]["immunities"]` for exactly
this one hydration payload (rebuilt fresh per resolution — nothing
persists past this call) before it flows into `build_activity_context`.
`activities/apply.py::apply_damage` already merges the sidecar's
`immunities` list unconditionally (no new consumer code) — a `force`
`DamageApplied` amount rolls, then floors to `0` through the existing
immune-type path (still emits `DamageApplied(amount=0)`, per that module's
documented "never a suppressed event" contract). No new field, no general
force-immunity flag on `Combatant` — deliberately narrower than a real
force-resistance mechanic, matching the SRD's spell-specific wording and
the smallest change that satisfies it.

### Slot gating on the readied-cast path (C17 R4)

Shield's own hook, `_drain_targeted_reactions`, passes `eligible=lambda
reactor, pending: _readied_cast_eligible(live, reactor, pending)` into
every `_pop_pending_reaction` call it makes. `_readied_cast_eligible` is
the readied-cast mirror of Counterspell's `_eligible` closure above, minus
the range check (Shield's own canonical activity carries no `range`): a
cantrip-level readied spell (`level == 0`) is always eligible; a leveled
one needs an unexpended slot at its readied level via `_slot_available`
(same Spellcasting-then-Pact-Magic order as everywhere else — see the
Counterspell section's "Two-pool slot consumption"). A zero-slot reactor's
readied Shield is skipped exactly like an ineligible Counterspell — left
armed, Reaction and slot both untouched — so a Magic Missile or melee hit
against a reactor with no slot left at the readied level now actually
lands, where it previously always triggered the buff for free.

## Monster opportunity attack (a pinned scenario) + Disengage (a pinned scenario)

### Why AoO is not a queued reaction

An opportunity attack is not "readied" via an on-turn intent — SRD
Opportunity Attacks are always-available, gated only on
`reaction_available`, exactly like the shipped PC-reactor direction
(`_fire_pc_opportunity_attacks_on_move`, unmodified by this cluster). This
scenario needs only the "any combatant, either direction" generalization of
that existing scan, not the `pending_reactions` queue machinery the rest of
this cluster builds.

`_fire_monster_opportunity_attacks_on_move(live, *, mover_id, from_zone,
to_zone)` mirrors `_fire_pc_opportunity_attacks_on_move` with reactor/mover
roles swapped (`live.encounter_ids` instead of `live.party_ids`) and one
additional guard the shipped direction does not need: skip entirely when
`mover.disengaging_this_turn` is set. It inherits the same same-zone-only
reach approximation the shipped direction carries (`melee_reach_ft` is not
yet consulted for cross-zone reach on either direction — out of scope here,
tracked already under "Richer pathfinding" / the reach BACKLOG history).
Called from `_handle_move` (the PC move handler) **before** `ActorMoved` is
emitted — "the attack occurs right before it leaves your reach."

### Disengage (real handler; closes the discovered turn-ending fall-through)

`"disengage"` becomes a fourth turn-non-ending early-return branch in
`submit_player_intent`, alongside `"move"` / `"move_mark"` / `"dash"`:
`_handle_disengage` validates + consumes the Action (Disengage **is** your
Action — distinct from Dash's Action/Bonus-Action dual economy), sets a new
per-turn `Combatant.disengaging_this_turn: bool = False` flag to `True`,
emits `IntentSubmitted(intent_type="disengage")`, and — critically — does
**not** call `_advance_turn`. This is the fix for the discovered defect:
previously `"disengage"` fell through to the generic Action-consuming tail
that unconditionally advances the turn, making a same-turn
Disengage→Move sequence raise `IntentRejectedError(reason="not_actor_turn")`
on the follow-up `move` call. `disengaging_this_turn` resets to `False` at
the actor's own next `TurnStarted` (added to `_emit_apply_turn_started`'s
existing per-turn-budget reset, alongside `action_available` etc.) — "your
movement doesn't provoke... for the rest of the turn," not permanently.

## Explicitly out of scope

- **Interactive prompts.** A host asking "do you want to Counterspell
  this?" mid-resolution is a host concern; this engine only supports
  pre-armed auto-fire, by hard constraint.
- **PC-reactor AoO changes.** `_fire_pc_opportunity_attacks_on_move` is
  unmodified — it already shipped in an earlier cluster.
- **Monster spellcasting.** `select_typed_monster_action` still never picks
  a `CastActivity`-only action (Spellcasting/Protective Magic), so a monster
  cannot cast Counterspell/Shield on its own turn through the public API;
  a pinned scenario model the "enemy caster" as a second PC for this reason (a
  documented substitution, not an error — see the catalog's own
  "Constructibility finding").
- **A general force-immunity / resistance mechanic.** Deliberately not
  built — see the Magic Missile carve-out above.
- **Richer opportunity-attack reach** (`melee_reach_ft` consulted for
  cross-zone reach on either AoO direction) — unchanged pre-existing gap,
  inherited by the new monster-reactor direction identically to the
  shipped PC-reactor direction.
- **Multi-round reaction-applied buffs.** The off-turn expiry mechanism
  fires at the owner's very next `TurnStarted` regardless of the effect's
  `duration.rounds` value — correct for every reaction buff this cluster's
  SRD scope contains (`rounds == 1`, i.e. "until the start of your next
  turn"); a hypothetical longer-duration reaction buff would need a richer
  round-counting rule not built here.
