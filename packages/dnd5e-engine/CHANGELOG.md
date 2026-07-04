# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0]

Lockstep release with `dnd5e-srd-data` 0.2.0 — the outcome of the gap-closing
campaign (ten scenario clusters). See `docs/migration/v0.1-to-v0.2.md` for the
full, host-facing migration guide. The engine now depends on
`dnd5e-srd-data>=0.2.0` (the rest-cap path reads the new `Feature.uses` schema).

### Added

- **Rest & recovery** — new public, zero-I/O module `dnd5e_engine.rest`, called
  *between* combats: `resolve_short_rest`, `resolve_long_rest`,
  `recover_feature_uses`, the `HitDicePool` / `RestOutcome` value types, the
  `RecoveryPeriod` literal, and `FEATURE_USE_COUNTER_PREFIX`. All added to the
  top-level `__all__`.
- **Spatial (grid) surface** — `WallSegment` value type (also a top-level
  export); `GridScene.wall_segments`, `GridScene.cover_cells`, and
  `GridScene.difficult_terrain_cells` fields (all default empty/off);
  `SpatialTopology.cover_between(...)`; and `GridTopology.cells_in_template(...)`
  for sphere/cone/line AoE templates.
- **Passive-stat fields** — `condition_immunities` and `damage_vulnerabilities`
  on `PartyMemberSpec` / `EncounterMemberSpec` / `Combatant`, and
  `movement_modes` (`CombatantMovementModes`) plus `walk_speed_bonus` on
  `PartyMemberSpec` / `Combatant`. All default empty and only take effect when
  the backing dataset carries the trait.
- **Intent field** `PlayerIntent.activity_id` (default `None`) — disambiguates a
  `USE_FEATURE` invocation of a multi-activity feature (Channel Divinity,
  Cunning Strike).
- `PartyMemberSpec.reach_ft` (default `5`) — threads onto the live
  `Combatant.melee_reach_ft`, making a reach weapon's opportunity-attack reach
  reachable from the boundary spec.
- **Reaction surface** — `"ready"` intents now register a pre-armed reaction;
  `PlayerIntent.reaction_trigger` narrows to the `ReactionTrigger` literal.
- `CastFailedReason` gained the values `"countered"` (Counterspell) and
  `"no_uses_remaining"` (a capped, rest-recharged feature invoked over its cap).
- New additive `ActivityResolutionContext` sidecar fields backing the above
  (cover, per-category damage-bonus buckets, Sneak Attack gates, reaction AC
  bonus) — all default empty.

### Changed

- **Spell save DC is now the real SRD 5.2 formula** (`8 + proficiency +
  spellcasting-ability modifier`) for PC caster spells, replacing a flat
  Avrae-era approximation — the campaign's widest-blast-radius change. Any host
  casting a PC save-DC spell sees a different, SRD-correct DC. Item casts and
  monster casters are unchanged.
- **Sneak Attack rider** — a qualifying finesse/ranged rogue hit now deals the
  `@scale`-resolved extra damage, doubled on a critical hit.
- **Passive-projection behavioral flips** — Rage damage resistance now halves
  matching damage; an immune condition never attaches; a matching damage
  vulnerability doubles the hit; movement-mode / walk-speed bonuses (Fast
  Movement, Roving) now fold onto `base_speed`.
- **Monster behavior** — fleeing monsters now retreat away from their nearest
  threat instead of standing still; a mixed melee+ranged multiattack now fires
  the weapon that fits the current distance instead of always the first-listed
  one; monsters Dash to close an out-of-reach movement gap.
- **Reactions & action economy** — a countered `cast_spell` does **not** expend
  its spell slot; a reaction-applied 1-round buff (Shield's +5 AC) now survives
  until the owner's next turn; `"disengage"` is now a real turn-non-ending
  action; PCs moving out of a monster's reach now provoke opportunity attacks.
- **Active-effect changes** — `multiply` / `upgrade` / `downgrade` change modes
  now apply; the `rwak` / `msak` / `rsak` damage and `spell.dc` bonus buckets
  now fold; a weapon-tagged `damage.bonus` change now reaches swing damage.
- Feature-owned `@scale` ids now resolve; the Foundry `(@scale.x)dN` dice-count
  idiom now normalizes; capped features (Second Wind) are now per-rest limited.

### Removed

- `ActionType.SHORT_REST` (`dnd5e_engine.types.intent`) — a dead, unreachable
  member of the legacy dispatch enum with no handler. It was never the
  live-combat intent surface (`events.py::IntentType` has no `"short_rest"`).
  Hosts wanting rest resolution use the new `dnd5e_engine.rest` module.
- `rules/gambits.select_action` (with the private helpers `_PASS_ACTION` /
  `_get_alive_targets` only it used) — the legacy per-profile gambit AI the live
  monster-turn path never called. Every behaviour it offered now lives in
  `advance_monster_turn` / `activities/monster_actions.py`. Verified caller-free;
  it was not a top-level `__all__` export.
  (`rules/gambits.assign_behavior_profile` was reviewed and **retained** — it is
  a host-facing utility for constructing `EncounterMemberSpec.behavior_profile`
  from raw monster stats, not dead code.)

## [0.1.1]

### Added
- `LiveCombatView` — public read-model projection of live combat state.
- `get_live(handle) -> LiveCombatView` is now part of the public API (`__all__`);
  it returns a point-in-time snapshot view instead of the private `_LiveCombat`.
- `roll_dice_str` — the dice-expression evaluator is now a public test seam
  (renamed from the private `_roll_dice_str`).

## [0.1.0]

First public release.

### Added

- Pure-Python, host-agnostic D&D 5e SRD rules engine: combat orchestration,
  ability checks and saving throws, and combat-scoped effects.
- SRD 5.2 (2024) content resolution against the typed-Activity corpus via
  `BundledAssetLoader`, reading the canonical dataset from the
  `dnd5e-srd-data` package.
- Curated public API surface (`__all__`) with a surface guard test.
- `py.typed` marker — the package ships inline type information.
- Zero-I/O guarantee: no DB, network, or async dependencies in the engine.
