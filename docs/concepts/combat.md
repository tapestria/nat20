# Combat model

Combat in Nat20 is a stateful, turn-based loop driven through an opaque
**`CombatHandle`**. You open a combat, submit intents turn by turn, and close
it — the engine owns all runtime state in memory behind the handle.

## The loop

`start_combat(...)` takes a `session_id`, a `party` (list of
`PartyMemberSpec`), an `encounter` (list of `EncounterMemberSpec`), an
`rng_seed`, and an optional `grid_scene` or `scene_zones` topology. It rolls
initiative, materializes runtime state, and returns a `StartCombatResult`
wrapping the `CombatHandle` plus the opening `CombatEvent` stream.

On a PC's turn, call `submit_player_intent(handle, actor_id, intent)` with a
`PlayerIntent`. The `intent_type` (an `IntentType` literal — `"attack"`,
`"cast_spell"`, `"move"`, `"dash"`, `"dodge"`, `"disengage"`, `"hide"`,
`"help"`, `"use_item"`, `"use_feature"`, `"pass"`, and more) selects which
optional fields the resolver consumes (`weapon_id`, `spell_id`,
`target_id`, `target_zone_id`, …). Monster turns advance via
`advance_monster_turn(handle)`, which runs the built-in monster AI.

## Determinism and events

Every die roll flows through the seeded RNG you pass to `start_combat`, so a
given seed and intent sequence always reproduce the same combat. Each call
emits a stream of typed `CombatEvent`s (attacks, damage, deaths, turn and
round boundaries) that a host renders or narrates.

## Closing out

`end_combat(handle)` returns an `EndCombatResult` carrying a `CombatOutcome`
— its `ended_reason` (victory, defeat, flee, forced), `residual_hp`,
`deaths`, and `loot_drops` — plus the final tuple of `ActiveEffect`s, which
the engine discards (effects are combat-scoped).
