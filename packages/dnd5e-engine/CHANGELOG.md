# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Core-mechanics **foundations** (F1 actor stat projection, F2 unified d20 test,
F3 turn lifecycle) and cluster **C12 — conditions enforced**. Nothing is removed
and no signature changes shape — every new field is optional and defaults to the
pre-0.6 behaviour. C12 does change *results* for hosts that carry conditions or
exhaustion on a combatant. Behavioural deltas
(and the fixtures they move) are enumerated in
[`docs/migration/v0.5-to-v0.6.md`](../../docs/migration/v0.5-to-v0.6.md).

### Added

- **`activities/actor_stats.py`** — the per-actor D20-test modifier projection
  (SRD 5.2 §D20 Tests / §Proficiency). `save_modifier(combatant, ability)` and
  `check_modifier(combatant, ability, skill=None)` return a typed
  `D20Modifier(ability, ability_mod, proficiency, expertise, total)`;
  `ability_modifier_of` / `proficiency_bonus_of` / `skill_ability` are the
  supporting primitives.
- **`activities/d20.py`** — the single SRD 5.2 D20 Test primitive.
  `roll_d20_test(rng, modifier, sources, *, forced_natural=None) -> D20Result`
  with a typed `AdvantageSources(advantage, disadvantage)` and
  `resolve_mode(...)` implementing the SRD's cancel-to-normal rule. Normal mode
  still consumes exactly one RNG draw, so pre-0.6 seeded streams are unmoved.
- **`dnd5e_engine.AdvantageSource`** (new top-level export) — the closed
  `Literal` naming *why* a roll had advantage/disadvantage (`flag`,
  `condition:self`, `condition:target`, …), carried on the roll events.
- **Roll-breakdown fields on the roll events.** `AttackRolled`, `SaveRolled`,
  `CheckRolled` and `ConcentrationCheck` gained `natural` (the die kept after
  advantage/disadvantage), `modifier` (the flat bonus) and `sources`, plus
  `advantage` on `SaveRolled` / `CheckRolled` / `ConcentrationCheck`. All
  optional; hosts that ignore them are unaffected.
- **`TurnPhase(phase, actor_id, round_number)` event** — marks each
  `round_start` / `turn_start` / `turn_end` boundary immediately before that
  phase's hooks run. It is a marker event with no mechanical payload; renderers
  should skip event types they do not recognise.
- **`turn_lifecycle.py`** — the `TurnLifecycle` hook registry
  (`register` / `unregister` / `run`) that the single turn-advance path drives.
  Every "at the start/end of a turn" rule registers here instead of being
  open-coded into the advance path.
- **Timed effect expiry.** Effect durations in `seconds` (materialised as
  `ceil(seconds / 6)` rounds), `turns`, and `flags["until_end_of_next_turn_of"]`
  now expire, alongside the pre-existing `rounds` counter.
- **Proficiency fields on `PartyMemberSpec` and `Combatant`** —
  `save_proficiencies`, `skill_proficiencies`, `skill_expertise`,
  `weapon_proficiencies`, plus `Combatant.proficiency_bonus_override` (monsters
  carry their template's CR-derived bonus). All default to empty / `None`, so a
  host that sets none reproduces pre-0.6 behaviour exactly.
- **`test_capability_matrix.py::test_status_rows_match_code_probes`** pins
  `docs/capabilities.md` status rows to grep-level code probes, in both
  directions.
- **Conditions enforced (C12).** `rules/conditions.py` gains
  `d20_test_penalty`, `exhaustion_level_of`, `project_speed`,
  `conditions_block_actions`, `conditions_auto_crit_within_5ft`,
  `SPEED_ZERO_CONDITIONS` and `AUTO_CRIT_WITHIN_5FT_CONDITIONS`;
  `conditions_grant_advantage_on_attack` accepts keyword-only `distance_ft`,
  `grappler_id` and `target_id` (the Prone and Grappled rows).
  `SpatialTopology.distance_ft(a, b)` is a new Protocol method implemented by
  both backends. `ActivityResolutionContext` gains `target_distance_ft`,
  `attacker_grappler_id` and `d20_test_penalty`. New reasons on existing
  closed sets: `IntentRejectedError` `"actor_incapacitated"`,
  `MoveFailed.reason="speed_zero"`, `AttackFailed` / `CastFailed`
  `"target_is_charmer"`. No new event class and no new top-level export.
- **Grid AoE targeting (C16).** `_expand_aoe_target_list` enumerates the typed
  template (`sphere` / `cone` / `line` / `cube` / `cylinder`; Foundry `radius`
  = emanation, `circle`, `square` mapped) via `GridTopology.cells_in_template`
  and drops cells without line of effect from the point of origin (SRD 5.2
  §Point of Origin). New `PlayerIntent.direction: tuple[int, int] | None`
  aims cones, lines and cubes (defaults to caster → named target).
- **Creature cover.** `GridTopology.cover_between(a, b, occupied_cells=())`
  — every other live combatant on the line grants half cover; blocked cells
  grant total cover and block sight (`has_line_of_sight`). A `cover_cells` tag
  on the **target's own** cell now counts (the origin's still never does); a
  creature on a `"total"` cover cell is therefore untargetable.
- **AoE cover is measured from the point of origin** (SRD 5.2 §Cover), not from
  the caster: the AoE cast path threads the resolved template origin
  (`_aoe_cover_origin`) into the per-target cover map.
- **Multi-cell `move` intent — grid backend only.** `_handle_move` paths with
  `GridTopology.shortest_path` (walls block, no diagonal corner-cutting,
  enemies impassable, allies passable, no ending in an occupied cell) and
  charges each leg's `edge_distance`; new `MoveFailed.reason` members
  `unreachable`, `occupied`, `blocked_path`. The legacy zone graph keeps its
  pre-0.6 single-adjacent-step contract, `not_adjacent` rejection included.
- **Forced movement.** `orchestrator.push_combatant(live, target_id,
  origin_cell, distance_ft)` and the `CombatantMoved(forced=True)` event;
  `activities/forced_movement.py` wires Thunderwave's push.
- **Vision & light (C16b).** `GridScene.lighting`, `default_lighting`,
  `obscurement_cells` (`LightLevel` / `Obscurement` Literals) and
  `GridTopology.can_see(a, b, senses)`; `ActivityResolutionContext.target_unseen`
  / `attacker_unseen_by` feed the `unseen` `AdvantageSource` both directions.
- `SaveBlock.ignore_cover` is honoured when present (`roll_save(...,
  ignore_cover=)`); the dataset field itself ships with C22.

### Changed

- **Saving throws apply real modifiers.** All three save paths (activity saves,
  the damage-triggered concentration check, the end-of-turn repeat save) now add
  `ability modifier + proficiency bonus (if proficient)` for all six abilities,
  where v0.5 projected DEX only and the two orchestrator paths rolled a raw d20.
  Monster ability scores, save/skill proficiencies and proficiency bonus hydrate
  from `monster_template_slug`.
- **Ability checks apply the actor projection** and fold the
  `abilities.check` / `abilities.skill` / `abilities.<ab>.save` (and Foundry-native
  `system.bonuses.abilities.*`) effect-change families, where
  `build_activity_context` previously hard-coded `check_modifiers={}`.
- **Activity attack rolls honour advantage/disadvantage**: attacker
  `flags.advantage.attack` / `flags.disadvantage.attack` effects plus the
  condition-derived sources, cancelling per SRD §Advantage and Disadvantage.
  Opportunity attacks still roll flat `normal`.
- **Every d20 in the engine goes through `roll_d20_test`** — attacks, saves,
  ability/skill checks, death saves and the concentration check.
- **`ConcentrationCheck` is now emitted** for the damage-triggered concentration
  save. *Transitional:* the legacy `SaveRolled(ability="con")` for the same roll
  is emitted alongside it until v0.7; a host that counts saves must filter one
  of the pair out.
- **`D20Result.first`** is the first die drawn, deliberately not named
  `natural` — `AttackRolled.natural` is the *kept* die (the one the natural-20
  crit / natural-1 fumble test reads).
- Turn advancement runs through one shared path, so every boundary rule fires
  in a single, registration-ordered place.
- **The SRD 5.2 conditions now have teeth (C12)** — the Incapacitated
  action/bonus/reaction gate, Speed 0, exhaustion's `-2 × level` on every D20
  Test (death saves included) and `-5 ft × level` Speed, the Prone and Grappled
  attack rows, auto-crit within 5 ft of a Paralyzed/Unconscious target, the
  Charmed target restriction (on the monster turn path as well as the player's
  — a charmed monster will not select its charmer), and Unconscious at 0 HP —
  including a Character *hydrated* into combat already at 0 HP — with
  massive-damage instant death plus one death-save failure per damaging hit
  while down. Four SRD condition rows remain unenforced and the capability row
  stays `⚠️ Partial`; see `docs/capabilities.md` and `BACKLOG.md`.
- **`conditions_grant_disadvantage_on_ability_checks` /
  `project_passive_check_modifiers` changed their answer for two slugs**
  (both PyPI-live): `exhaustion` no longer reports disadvantage (SRD 5.2
  replaced the 2014 rule with the numeric penalty), and `frightened` now does.
  See the migration guide.
- **Condition immunity is honoured by the state folds, not only the event.**
  A status on a creature listed in `Combatant.condition_immunities` no longer
  lands on `Combatant.conditions` or `active_conditions` — neither through the
  `start_combat` effect seed nor the runtime `EffectApplied` fold, which
  previously unioned it in behind the already-suppressed `ConditionApplied`.
  Before C12 that was near-cosmetic; with the gates above it decided whether an
  immune creature could act at all.
- **`ConditionApplied` / `ConditionRemoved` now materialise on
  `Combatant.conditions`**, so a condition applied mid-combat reaches every
  condition consumer (a Topple-proned target is attacked at advantage in
  melee). Reviving from 0 HP leaves the creature Prone: `ConditionRemoved`
  (`unconscious`) followed by `ConditionApplied` (`prone`).
- **The two orchestrator-level save paths** (the concentration check and the
  end-of-turn repeat save) now honour the condition projections: STR/DEX
  auto-fail, Restrained DEX disadvantage and the exhaustion penalty.
  Effect-derived `passive_save_bonus` (Bless/Bane) is still C13's.
- Walls now block movement as well as sight; `edge_distance` returns `None` for
  an illegal step. On the grid, `ActorMoved` carries the whole intent's distance
  (one event per `move`); the zone backend still emits one per step.
- **`start_combat(grid_scene=...)` raises `ValueError`** when a combatant's
  `zone_id` is out of bounds or blocked, instead of silently seating them on an
  unusable cell.

### Deprecated

- `start_combat(scene_zones=...)` — `DeprecationWarning` since 0.6.0, removed in
  0.7.0. Pass `grid_scene=GridScene(...)` instead.

## [0.5.0]

Lockstep release with `dnd5e-srd-data` 0.5.0 and `nat20-bridge` 0.5.0.

Removes the legacy (Gen 1) rules surface deprecated in 0.4.0. The engine now
ships exactly one, seedable, documented rules implementation
(`orchestrator` + `activities/`). See `docs/migration/v0.4-to-v0.5.md`.

### Removed

- Modules `dispatch`, `event_dicts`, `types.dice`, `types.intent`, and
  `rules.{combat, combat_data, combat_helpers, equipment, gambits, resolution,
  spells}` (plus the private `rules._parsing` / `rules._class_meta`).
- `dnd5e_engine.ActionType`, `CombatNPC`, and the lazy
  `dnd5e_engine.types.{ActionType, CombatOutcome, DiceOutcome, CombatNPC}`
  re-exports; the 0.4.0 `DeathSaveState` / `BehaviorProfile` re-export shims.
- The cross-generation parity test; its Gen 2 assertions live on in
  `tests/test_attack_classification.py`.

## [0.4.0]

Lockstep release with `dnd5e-srd-data` 0.4.0 and `nat20-bridge` 0.4.0.

Deprecates the legacy (Gen 1) rules surface. **Nothing is removed**; every
deprecated import warns. Removal lands in 0.5.0 — see
`docs/migration/v0.3-to-v0.4.md`.

### Deprecated

- **The legacy (Gen 1) rules surface — removed in 0.5.0.** `dispatch`,
  `event_dicts`, `types.dice`, `types.intent`, and `rules.{combat, combat_data,
  combat_helpers, equipment, gambits, resolution, spells}` emit a
  `DeprecationWarning` on import. The top-level `dnd5e_engine.ActionType` and
  `dnd5e_engine.types.{ActionType, CombatOutcome, DiceOutcome, CombatNPC}`
  re-exports now resolve lazily and warn on access. Every symbol's supported
  route is in `docs/migration/v0.3-to-v0.4.md`. Rationale: two drifting
  implementations of the same SRD rules, a non-seedable legacy path, and host
  transport/persistence shapes inside a zero-I/O package.

### Changed

- `DeathSaveState` canonical home is now `dnd5e_engine.death_saves`;
  `BehaviorProfile` is now `dnd5e_engine.types.combat`. The old locations
  re-export until 0.5.0. The supported engine's import tree no longer reaches
  any legacy module (pinned by `tests/test_gen2_has_no_gen1_imports.py`).

### Added

- Cross-generation attack-roll parity test
  (`tests/test_generation_parity_attack.py`): `rules/combat.attack_roll` /
  `resolve_player_attack` and `activities/attack.py` are fed the same d20
  stream and must keep the same natural die and agree on hit / crit / miss
  under advantage, disadvantage and flat rolls. This is the guard that would
  have caught the drift fixed in 0.3.1 (#11). No runtime behavior change.

## [0.3.2]

Lockstep release with `dnd5e-srd-data` 0.3.2 and `nat20-bridge` 0.3.2.

Additive maturity pass from an independent review of the packages as a
standalone engine. **No public name is removed or changed shape.**

### Fixed

- **Multiattack fan-out resolved the wrong attack mix for most monsters.** The
  prose parser only matched `[[/item .id]]{label}`, but the corpus mostly ships
  `[[/item Name]]` or bare mnemonic ids, so 174 of 180 multiattacks fell back to
  "repeat one sibling N times" — silently wrong for every heterogeneous
  multiattacker. The parser now reads per-token counts from the multiattack's
  first sentence (excluding "It can replace one attack with …" riders) and
  recovers names from Foundry's mnemonic ids. Precise joins: **6/180 → 119/180**.
  Chuul, Otyugh, Cloaker, Unicorn, Mummy, Pit Fiend, Xorn and Marilith now make
  their correct attack sequences. **Behaviour change for consumers:** affected
  monsters deal their correct (higher) damage per round and consume more of the
  dice stream, so combat transcripts seeded against 0.3.x will diverge.
- `__version__` now derives from installed package metadata instead of a
  hand-maintained literal, so it cannot drift from `pyproject.toml` (0.3.0 shipped
  reporting `0.2.0`). Pinned by `tests/test_determinism_contract.py`.

### Added

- **`CheckSpec.rng`** — `resolve_check` previously drew its d20 from the
  process-global `random` module with no way to inject a generator,
  contradicting the documented determinism guarantee. Pass a seeded
  `random.Random` for a reproducible standalone check; `None` preserves the old
  behaviour. `rules.dice`, `rules.skills` and `roll_dice_str` /
  `apply_changes_to_check` gain matching optional `rng` parameters. Combat
  resolution was already seeded and is unchanged.
- **`docs/capabilities.md`** — a per-mechanic matrix of what the engine
  resolves, what loads but produces no events, and what is not modelled. Its
  published counts are recomputed from the corpus by
  `tests/test_capability_matrix.py`.
- Concept pages for reactions (the pre-armed model) and monsters (the built-in
  AI, multiattack join rate, absent legendary actions).
- `tests/test_docstrings_are_host_agnostic.py` — fails the build on a docstring
  that names a private downstream application, retired tooling, or a doc path
  that does not exist in this repo. 104 such references were rendered onto the
  public API site; all removed.

### Changed

- `CONDITION_EFFECTS[EXHAUSTION]` / `[PRONE]` descriptive strings corrected from
  2014 to SRD 5.2 wording and labelled as not-enforced; the enforced exhaustion
  rule is still the 2014 one (tracked in `BACKLOG.md`).
- Sphinx cross-reference roles in docstrings, which rendered as literal markup
  on the API site, converted to inline code.
- Monkeypatching `roll_dice_str` now requires a two-parameter double
  (`lambda expr, rng=None: …`).

## [0.3.0]

Lockstep release with `dnd5e-srd-data` 0.3.0 — the item charge lifecycle: gate
→ spend → cast-delegate → upcast → recharge → observe. See
`docs/migration/v0.2-to-v0.3.md` for the full, host-facing migration guide.
The engine now depends on `dnd5e-srd-data>=0.3.0` (the charge-gate and
cast-delegation paths read the new `Item.uses` / `Spell.foundry_uuid` schema).

### Added

- **Item charges** — `use_item` now validates and spends `consumption.targets[type=itemUses]`
  costs against the item's `uses.max` pool, tracked in the `custom_counters` sidecar under
  `item_use:<slug>` (`{"spent": n}`). Exhausted pools reject with
  `CastFailed(reason="no_charges_remaining")` before the action budget is touched. Items
  without a pool are unaffected. `CastFailedReason` also gains `invalid_charge_spend`, emitted
  when a `charges_to_spend` request violates the activity's `consumption.scaling` (see
  "Charge upcasting" below).
- **Item recharge** — `dnd5e_engine.rest.recover_item_uses` (+ `ITEM_USE_COUNTER_PREFIX`,
  submodule-only export): pure recharge over `item_use:` pools. The engine's own
  `rest.RecoveryPeriod` gains `"dawn"`/`"day"`/`"dusk"` (previously just `"sr"`/`"lr"`;
  the data package's `RecoveryRule` already knew `"day"` — this widens the engine's
  narrower rest-period literal to match); formula recovery now rolls dice ("1d6 + 1")
  through an optional `rng` (also available on `recover_feature_uses`).
- **Cast delegation** — a used item's `CastActivity` now resolves its referenced spell
  (uuid→Spell via `dnd5e-srd-data`'s `get_spell_by_uuid`) on the PC-intent path, honoring
  the item's flat DC / attack / level overrides. `cast_spell_unresolved` now signals a
  genuinely missing uuid, not missing plumbing.
- **Charge upcasting** — `PlayerIntent.charges_to_spend` casts at
  `base level + extra charges`, validated against `consumption.scaling`
  (`invalid_charge_spend` on violation). New `ActivityResolutionContext.cast_level_override`.
- **Charge read path** — `LiveCombatView.custom_counters_by_entity` (three-level snapshot
  copy): hosts mirror `item_use:` / `feature_use:` pools per turn the same way they mirror
  `spell_slots_by_entity`.

## [0.2.0]

Lockstep release with `dnd5e-srd-data` 0.2.0 — the outcome of the gap-closing
campaign (ten scenario clusters). See `docs/migration/v0.1-to-v0.2.md` for the
full, host-facing migration guide. The engine now depends on
`dnd5e-srd-data>=0.2.0` (the rest-cap path reads the new `Feature.uses` schema).

### Added

- **Rest & recovery** — new public, zero-I/O module `dnd5e_engine.rest`, called
  *between* combats: `resolve_short_rest`, `resolve_long_rest`,
  `recover_feature_uses`, the `HitDicePool` / `RestOutcome` value types, the
  `RecoveryPeriod` literal — all added to the top-level `__all__`.
  `FEATURE_USE_COUNTER_PREFIX` is also public, but is exported from the
  submodule only: `from dnd5e_engine.rest import FEATURE_USE_COUNTER_PREFIX`.
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
## [0.1.2]

### Added
- `ActionType.USE_ITEM` parser-facing action member.

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
