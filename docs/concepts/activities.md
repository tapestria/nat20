# Activities

Nat20 resolves combat against a **typed activity corpus**, not hard-coded
rule branches. Weapons, spells, monster actions, and class features each
carry a list of *activities* — Foundry-aligned, Pydantic-typed descriptions
of what happens when the thing is used (an attack roll, a save-for-damage, an
applied effect, and so on). The dataset lives in the companion
`dnd5e-srd-data` package and is loaded through `BundledAssetLoader`.

## How an intent becomes activities

When you call `submit_player_intent(handle, actor_id, intent)`, the engine
reads the `PlayerIntent`'s `intent_type` to pick the relevant asset
reference: `"attack"` consumes `weapon_id`, `"cast_spell"` consumes
`spell_id` (and optional `slot_level`), `"use_item"` consumes `item_id`, and
`"use_feature"` consumes `feature_id`. It fetches that typed entity from the
loader and walks its activities through the per-kind resolvers, emitting the
resulting `CombatEvent` stream.

## Why typed activities

This is the core design choice: the engine is **edition-agnostic** and
consumes whatever typed content it is handed. Adding a new weapon, spell, or
monster is a data change to the SRD corpus, not an engine change. Because the
shapes mirror the Foundry VTT dnd5e schema, content can be sourced and
validated against an existing, battle-tested model rather than a bespoke
Nat20-only one.

The activity layer is where attack rolls, damage expressions, area-of-effect
targeting, and effect application are uniformly described — so combat
resolution stays a single code path regardless of which game object triggered
it.
