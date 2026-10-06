# Combat model

Combat in Nat20 is a stateful, turn-based loop driven through an opaque
**`CombatHandle`**. You open a combat, submit intents turn by turn, and close
it — the engine owns all runtime state in memory behind the handle.

## The loop

`start_combat(...)` takes a `session_id`, a `party` (list of
`PartyMemberSpec`), an `encounter` (list of `EncounterMemberSpec`), an
`rng_seed`, and the `grid_scene` (a [`GridScene`](grid.md)) to fight on. It rolls
initiative, materializes runtime state, and returns a `StartCombatResult`
wrapping the `CombatHandle` plus the opening `CombatEvent` stream.

On a PC's turn, call `submit_player_intent(handle, actor_id, intent)` with a
`PlayerIntent`. The `intent_type` (an `IntentType` literal — `"attack"`,
`"cast_spell"`, `"move"`, `"dash"`, `"dodge"`, `"disengage"`, `"hide"`,
`"help"`, `"use_item"`, `"use_feature"`, `"pass"`, and more) selects which
optional fields the resolver consumes (`weapon_id`, `spell_id`,
`target_id`, `target_zone_id`, …). Monster turns advance via
`advance_monster_turn(handle)`, which runs the [built-in monster
AI](monsters.md).

A `"move"` intent names a destination cell, and the engine walks the
fewest-cells legal route there in one intent ([Grid](grid.md#pathing)). Off-turn reactions
(Shield, Counterspell, opportunity attacks) are never prompted for
mid-resolution; they must be [pre-armed](reactions.md).

### Summoned creatures

The initiative order can grow and shrink mid-combat. SRD 5.2 Summon Dragon
seats a Draconic Spirit that "shares your Initiative count, but it takes its
turn immediately after yours": the engine inserts it in the slot after its
caster and emits `CombatantJoined`, which carries everything a host needs to
seat the creature itself — its id, name, stat block, caster, spell, count, the
creature it acts after, its cell, Hit Point maximum and Armor Class. "The
creature disappears when it drops to 0 Hit Points or when the spell ends": the
engine removes it and emits `CombatantLeft` with the reason (`"zero_hp"`,
`"concentration_drop"` or `"spell_ended"`). If it was the current actor, the
next creature's turn starts once the intent or legendary action that removed
it has resolved; if it left during its own intent, its own turn first ends as
any turn does, with `TurnEnded`.

A summon's id starts with `summon:` and its `entity_type` is `"Monster"`, so a
host loop that calls `advance_monster_turn` whenever the engine's pointer names
a non-PC needs no summon tracking: on the summon's turn the engine plays the
SRD default, the Dodge action. To command it instead, submit its intents
through `submit_player_intent(handle, <summon id>, intent)` — each Rend is one
`attack` naming `stat_block_action_id="rend"`; an attack off its stat block,
or a spell, is refused. `LiveCombatView.summons` maps each summon's id to its
owner, spell, stat block and slot level. A summon is its caster's ally, but it
never enters `party_ids` or `encounter_ids`, and the `CombatOutcome` holds no
Hit Points, XP or death of its own. A `DeathRecord.killer_id` can still name
it, as the current actor that dealt the blow: `CombatantJoined.origin_caster_id`
names its caster.

## Conditions a host adjudicates

The engine applies every condition rule that touches a roll it makes. Two SRD
5.2 rules touch only checks it never rolls, so they are a host's to apply:

- **Blinded and Deafened:** "You can't see and automatically fail any ability
  check that requires sight" (Deafened: hearing). No check the engine rolls
  needs a sense — Hide is Stealth, escaping a grapple is Athletics or
  Acrobatics. When a check of your own does (a Wisdom (Perception) check to
  spot something), read the creature's conditions from
  `get_live(handle).active_conditions` and fail the check without rolling it.
- **Charmed:** "The charmer has Advantage on any ability check to interact with
  you socially." When the charmer makes a social check against the creature it
  charmed, pass `CheckSpec(advantage=True)` to `resolve_check`. The
  `EffectApplied` that charmed the creature names its caster at the end of the
  effect's `origin`.

## Determinism and events

Every die roll flows through the seeded RNG you pass to `start_combat`, so a
given seed and intent sequence always reproduce the same combat. Each call
emits a stream of typed `CombatEvent`s (attacks, damage, deaths, turn and
round boundaries) that a host renders or narrates.

## Closing out

Between combats, `resolve_short_rest` / `resolve_long_rest` restore hit points,
hit dice, spell slots and feature uses; `resolve_check` resolves a one-off
ability, skill or saving throw with no handle at all.

`end_combat(handle)` returns an `EndCombatResult` carrying a `CombatOutcome`
— its `ended_reason` (victory, defeat, flee, forced), `residual_hp`,
`deaths`, and `loot_drops` — plus the final tuple of `ActiveEffect`s, which
the engine discards (effects are combat-scoped). The ended combat stays
readable — a repeat `end_combat`, `get_live`, a last `drain_pending_events`
— until 64 later combats have ended; its handle then raises
`UnknownHandleError`.

Not every SRD rule is resolved. The [capability matrix](../capabilities.md) is
the per-mechanic inventory of what is and is not enforced.
