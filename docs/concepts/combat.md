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
AI](monsters.md); `advance_monster_turn(handle, target_id=...)` names the
creature it attacks instead ([Monsters](monsters.md#how-the-ai-chooses)).

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
it, as the creature that dealt the blow: `CombatantJoined.origin_caster_id`
names its caster.

### Sides

Every creature fights on one of two sides: the party's or the encounter's.
The characters (`party`) are always on the party's side. An
`EncounterMemberSpec` is a hostile by default; `side="party"` seats it with the
characters instead, as an ally statted from a monster template (an escort, a
hired sword, a rescued prisoner). SRD 5.2 Summon Dragon states the relation
the engine already models for a summon: "The creature is an ally to you and
your allies."

A party-side ally joins `party_ids`, not `encounter_ids`, and every rule that
reads allegiance follows: Help, Pack Tactics, Sneak Attack's adjacent ally,
opportunity attacks and the monster AI's area aim. Foes target it like a
character, and on its own turn `advance_monster_turn` runs the AI for it
against the encounter side. To decide its turn yourself, command it through
`submit_player_intent(handle, <ally id>, intent)` as you would a summon
(`pass`, `move`, an `attack` naming `stat_block_action_id`).

An ally is still not a character. At 0 Hit Points it dies as a monster does
(`Death(reason="damage")`, no death saves), and its `DeathRecord.target_kind`
is `"npc"` or `"monster"`. It takes no share of the XP, which is divided among
the surviving characters only. `residual_hp` reports its Hit Points with the
party's, for you to persist.

`start_combat` raises `ValueError` unless at least one encounter member
fights on the encounter side. The end reason reads the sides: `victory` once
every encounter-side creature is out of the fight, `defeat_tpk` once every
party-side creature is. A standing ally keeps the party in the fight, so a
combat closed after every character has died while an ally still stands
reads `forced` (or `flee` when every foe still in the fight has fled), not
`defeat_tpk`. Legendary actions and Legendary Resistance stay with the
encounter side.

## Knocking a creature out

SRD 5.2 Knocking Out a Creature: "When you would reduce a creature to 0 Hit
Points with a melee attack, you can instead reduce the creature to 1 Hit
Point. The creature then has the Unconscious condition". A character makes
that choice with `PlayerIntent(intent_type="attack", knock_out=True, ...)`:
every melee hit the intent lands pulls the blow. The choice applies to the
attack's own damage (its weapon damage and riders, Sneak Attack, a Cleave
follow-up, Graze on a miss); a rider resolved by a saving throw after the hit
is not part of it and can still kill.

The intent is refused with `IntentRejectedError("knock_out_not_melee")`,
before anything is spent, unless every attack it resolves is a melee attack:
a ranged weapon, a Thrown weapon at a target beyond its reach, a multiattack
with a ranged part, or an `attack` naming a `spell_id` (a Spiritual Weapon's
repeat) is refused. A summon's or an ally's commanded stat-block melee attack
can pull its blow. `knock_out` on any other intent
type is ignored, so a melee spell attack from `cast_spell` still kills.

A blow that would drop the creature to 0 Hit Points leaves it at 1 and emits
`DamageApplied(knock_out=True)`, then `KnockedOut(target_id, attacker_id)`,
then `ConditionApplied("unconscious")`, so every Unconscious rule applies at
once: Incapacitated, Prone, Speed 0, Advantage on attacks against it, and a
Critical Hit for a hit from within 5 feet. It is not dying: no `Unconscious`
marker, no death saves. A summon is never knocked out (it leaves at 0 Hit
Points as always). A creature immune to Unconscious is left at 1 Hit Point,
conscious and still fighting, with no `KnockedOut`.

A knocked-out creature is listed in `LiveCombatView.knocked_out_ids` and is out
of the fight: no monster targets it, a host may not name it as a
`target_id`, and the end reason counts it with the dead on its side, so a
fight whose every foe is dead or knocked out ends in `victory`. It "remains
Unconscious until it regains any Hit Points": any healing wakes it
(`ConditionRemoved("unconscious")`, and it stays Prone), and so does a
monster's Regeneration. Damage that drops it to 0 Hit Points ends the knock-out
the ordinary way: a monster dies, a character starts dying. An effect that
also holds it Unconscious ending does not wake it.

At `end_combat`, `CombatOutcome.knock_outs` lists the creatures still knocked
out, in the order they went down, each a `KnockOutRecord` naming the
attacker. A foe still knocked out is worth its XP, as a dead one is (SRD 5.2
Experience Points: "XP is awarded for defeating the monster in combat or
otherwise neutralizing it"). What happens to it afterwards, and the Short
Rest the rule starts, is the host's to decide.

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
`deaths`, `knock_outs`, `xp_awarded` and `loot_drops` — plus the final tuple of `ActiveEffect`s, which
the engine discards (effects are combat-scoped). The ended combat stays
readable — a repeat `end_combat`, `get_live`, a last `drain_pending_events`
— until 64 later combats have ended; its handle then raises
`UnknownHandleError`.

Not every SRD rule is resolved. The [capability matrix](../capabilities.md) is
the per-mechanic inventory of what is and is not enforced.
