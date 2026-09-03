# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Core-mechanics **foundations** (F1 actor stat projection, F2 unified d20 test,
F3 turn lifecycle) and clusters **C12 — conditions enforced**, **C13 —
concentration lifecycle**, **C14 — action economy** (Dodge, Help, Hide,
Extra Attack, two-weapon fighting, Grapple/Shove/`stand_up`, engine-rolled
initiative with Surprise, and opportunity attacks through the shared d20
primitive), **C15 — attack rules** (weapon proficiency, range tiers,
thrown weapons, Ranged Attacks in Close Combat, Heavy, versatile grip,
damage attribution, crit-at-0-HP, Loading, and all eight 2024 weapon
masteries) and **C17 — spell slots, rests and upcasting** (per-class/
multiclass/Pact Magic slot derivation, rest-based slot recovery and
Exhaustion reduction, upcast target-count scaling, Counterspell/readied-cast
slot+range gating, and out-of-combat Ritual resolution). Nothing is removed
and no signature changes shape — every new field is optional and defaults
to the pre-0.6 behaviour. C12/C14/C15/C17 do change *results* for hosts that
carry conditions, exhaustion, turn-keeping attacks, weapon proficiency/
mastery data, or casters on a combatant. Behavioural deltas (and the
fixtures they move) are enumerated in
[`docs/migration/v0.5-to-v0.6.md`](../../docs/migration/v0.5-to-v0.6.md).

- **Action economy (C14).** Extra Attack reads a caster's granted
  `extra-attack` / `two-extra-attacks` / `three-extra-attacks` feature slugs
  (highest tier wins, never summed) into a per-Action `attacks_remaining`
  counter; a turn now keeps going after a main-hand attack until that
  counter — and any open two-weapon-fighting Bonus Action window — is spent
  (`LiveCombatView.turn: TurnCombatView`). A Light main-hand weapon opens a
  same-turn off-hand Bonus Action swing (SRD 5.2 §Two-Weapon Fighting). Dodge,
  Help (assist-an-attack-roll flavor) and Hide (DC 15 Stealth, cover/
  obscurement gate, Invisible-while-hidden) now have live dispatch handlers.
  New `IntentType` members `"grapple"`, `"shove"`, `"stand_up"`,
  `"escape_grapple"` resolve the Unarmed Strike Grapple/Shove options, the
  SRD 5.2 "Ending a Grapple" escape check and standing from Prone at half
  Speed. `PlayerIntent.shove_push: bool = False` picks the shover's Prone-or-
  push outcome. `PartyMemberSpec.initiative` / `EncounterMemberSpec.initiative`
  widen to `int | None`: `None` rolls an engine `d20 + DEX modifier` (spec
  order, before all other combat draws), with Disadvantage from the new
  `is_surprised: bool = False` field or a seeded incapacitated-implying
  status. Opportunity attacks now roll through `roll_d20_test` like every
  other attack, picking up condition/Dodge/Exhaustion sources.

- **Concentration lifecycle (C13).** The damage-triggered save DC is capped at
  the SRD 5.2 maximum of 30. A new concentration cast cascades the drop of the
  caster's prior concentration effect (SRD "the moment you start casting…").
  Concentration now ends on death and on gaining any Incapacitated-implying
  condition. New `IntentType` member `"drop_concentration"`: a voluntary,
  turn-keeping drop that costs no action economy. Concentration spells now
  expire at their maximum typed duration (1 minute = 10 rounds, …) at the
  caster's turn end via the new `engine:concentration-expiry` turn hook, with
  `EffectExpired(reason="duration")`. `LiveCombatView.concentration_chain`
  projects the caster-keyed ownership map for hosts.

- **Attack rules (C15).** Weapon proficiency is a real gate: a host that never
  sets `PartyMemberSpec.weapon_proficiencies` is assumed proficient (the R1
  sentinel — legacy behaviour, byte-identical); an explicit (possibly empty)
  list enforces proficiency by the weapon's category or slug, omitting
  Proficiency Bonus (never subtracting it) when unproficient. Attack range now
  has three tiers — normal, a middle disadvantage tier beyond normal range
  (`"range:long"`), and beyond max range is rejected — and a melee weapon with
  the Thrown property can now attack at range using its throw bands (both were
  previously flatly rejected). Ranged Attacks in Close Combat (SRD 5.2):
  disadvantage when a living, sighted, non-Incapacitated hostile is within 5
  ft of the attacker (`"ranged_in_melee"`). Heavy weapons impose disadvantage
  on a wielder with a raw Strength score below 13 — this and the Vex/Sap
  mastery riders below all ride the same `"trait"` advantage-source token.
  `PlayerIntent.two_handed: bool = False` selects a Versatile weapon's
  two-handed damage die on a melee swing. `DamageApplied` gains `source_id`
  (weapon slug / synthesized activity id / `"mastery:<slug>"`; spell/save/heal
  damage paths still report `None`, a C17+ seam) and `is_crit`; a critical hit
  against a target already making death saves now counts as two failures (SRD
  §Damage at 0 Hit Points). Loading weapons cap at one fired shot per actor
  per turn (`AttackFailed(reason="weapon_already_fired")`, gated ahead of the
  Charmed-target gate). All eight 2024 weapon masteries are live: Graze
  (miss-damage), Topple (Con save vs. `prone`, honoring condition immunity),
  Vex (a 2-round Advantage grant against the same target), Sap (a
  Disadvantage mark on the target until the source's next turn), Slow (a
  flat, non-stacking −10 ft Speed penalty, cleared at the source's next turn
  start), Push (a full 10 ft forced move via `push_combatant`; the "Large or
  smaller" size gate is unmodelled), Cleave (a deterministic, once-per-turn
  chained attack against the nearest eligible living hostile within 5 ft of
  the first target and within reach) and Nick (the off-hand extra attack
  spends no Bonus Action — SRD 5.2 lets it ride the Attack action instead).

- **Spell slots, rests and upcasting (C17).** `spellcasting.py` derives
  per-class Spellcasting slots (`derive_spell_slots`), multiclass slots
  (`derive_multiclass_slots`, per-class half/third rounding summed, SRD
  §Multiclassing) and Pact Magic (`derive_pact_slots`,
  `derive_multiclass_pact_slots`); `CharacterBuildSpec.classes: dict[str,
  int]` is the multiclass carrier, reconciled with the existing
  `class_slug`/`level` single-class fields. `resolve_long_rest` restores
  Spellcasting/Pact Magic slots and reduces Exhaustion by 1 (floored at 0);
  `resolve_short_rest` restores only Pact Magic (SRD's only
  Short-Rest-recovering slot pool). A Magic Missile-shaped cast now scales
  its DART COUNT, not just its damage dice, via `target.affects.count` /
  `spellcasting.resolve_target_count` and `PlayerIntent.target_ids`. An
  armed Counterspell/readied-cast reaction is now gated on slot
  availability at its readied level and, for Counterspell, its own 60 ft
  range with line of sight — an ineligible reactor's reaction is skipped,
  not consumed. A new `SpellCast` event carries component/material
  metadata (never enforced) on every PC cast path. `PlayerIntent.
  as_ritual` + `spellcasting.resolve_ritual_cast` resolve Ritual-tagged
  spells out-of-combat only; an in-combat ritual cast is rejected
  (`CastFailedReason` gains `"ritual_in_combat"`). An **upcast** Magic
  Missile previously over-rolled its single dart (`Nd4+1`, reading the
  corpus's empty `scaling.mode` as whole-mode scaling); it now rolls
  `1d4+1` once per cast and applies it to N darts, changing the RNG draw
  count for that one path (base-level Magic Missile is unaffected). See
  the migration guide for the full behavioural-delta list, including the
  Magic Missile event-count change and the `build_party_member`
  empty-pool fallback.

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
- **Vision & light consumers (C16b).** A new composite predicate,
  `orchestrator.py::_combatant_can_see(live, viewer, target)`, folds Blinded
  (viewer) and Invisible (target) — piercing only via blindsight/truesight
  reach with line of sight, never darkvision — on top of `GridTopology.can_see`.
  It now backs every SRD 5.2 "can see" conjunct outside the raw `unseen`
  attack-roll row: Dodge's "if you can see the attacker" attack-disadvantage
  half (both the regular-attack context sites and opportunity attacks),
  Ranged Attacks in Close Combat's "enemy who can see you", the Opportunity
  Attack "creature that you can see" trigger (both PC↔monster directions — a
  sight-blocked reactor spends no Reaction), Hide's "out of any enemy's line
  of sight" gate (skipped only when the hider's own cell already carries
  Three-Quarters/Total cover), and Frightened's line-of-sight gate. The
  Invisible "can somehow see you" carve-out is threaded through
  `rules/conditions.py::conditions_grant_advantage_on_attack`'s new
  keyword-only `attacker_invisibility_pierced` / `target_invisibility_pierced`
  parameters (default `False`, preserving pre-C16b behaviour); Frightened's
  attack-roll disadvantage gets a matching `fear_source_in_sight` keyword.
  New `SpatialTopology.light_on_cell(cell) -> LightLevel` reports per-cell
  light, so a dark cell now also satisfies Hide's "Heavily Obscured" gate
  (SRD 5.2 glossary: "An area of darkness is Heavily Obscured"). New
  `MoveFailed.reason` member `"frightened"`: a `"move"` intent that would
  bring the mover strictly closer to a visible, known, living fear source is
  now rejected (SRD 5.2 "You can't willingly move closer to the source of
  fear"). `AttackRolled` gains additive `advantage_sources` /
  `disadvantage_sources: list[AdvantageSource]` fields — the directional
  split of `sources` — so a mutual-unseen swing now reports `["unseen"]` on
  each list instead of the old `sources = ["unseen", "unseen"]` merge
  (`sources` itself is unchanged).
- `SaveBlock.ignore_cover` is honoured when present (`roll_save(...,
  ignore_cover=)`); the dataset field itself ships with C22.
- **C22 dataset consumers.** `Combatant.trait_mechanics` (hydrated from the
  monster template's typed `special_abilities[].mechanic`): **Magic
  Resistance** now rolls saving throws against spells with Advantage
  (`AdvantageSource` gains `"trait"`). `roll_save(..., ignore_cover=)` +
  `SaveBlock.ignore_cover` — Sacred Flame's target gets no cover bonus.
  `apply_damage(..., magical=)` — a magic weapon's (`Weapon.magical`) or a
  spell's Bludgeoning/Piercing/Slashing damage overcomes resistance to
  *nonmagical* B/P/S; `Combatant.physical_resistances_nonmagical_only`
  (also on `EncounterMemberSpec`, default `True`) makes the qualifier explicit.
  Save-path target cover is hydrated for templated spell casts; when an AoE's
  origin cell IS the target's cell, the new `GridTopology.cover_on_cell` reads
  the tag on that cell (`cover_between` itself is unchanged — its target-cell
  walk shipped with C16). Multiattacks for the five opaque-key monsters
  resolve to their exact attack mix.
- **`dnd5e_engine.spellcasting` (C17)** — pure SRD 5.2 spell-slot tables and
  derivations, zero I/O. `derive_spell_slots(class_slug, progression,
  level)`, `derive_pact_slots(level)`, `multiclass_caster_level(classes)`,
  `slots_for_caster_level(caster_level)`, `effective_caster_level(
  progression, level)`, `resolve_target_count(count_formula, *,
  cast_level=)` (a restricted `ast`-walker roll-data evaluator — never
  `eval`), `count_scales_with_cast_level(count_formula)`,
  `spell_component_metadata(spell)`, `resolve_ritual_cast(spell, *,
  prepared, ritual_adept=False) -> RitualCast`, and the `SPELL_SLOT_TABLE`
  / `PACT_SLOT_TABLE` constants. `derive_spell_slots`, `derive_multiclass_
  slots`, `derive_pact_slots`, `resolve_ritual_cast` and `RitualCast` are
  new top-level `dnd5e_engine` exports.
- **`build_spec.derive_multiclass_slots` / `derive_multiclass_pact_slots`**
  — project `CharacterBuildSpec.classes` through a `loader` (explicit or the
  lazy default `get_lib_loader()`) into a Spellcasting/Pact Magic pool;
  `build_party_member` calls both to fill an empty `CombatInstance.
  spell_slots`/`pact_slots`.
- **`PartyMemberSpec.pact_slots` / `CombatInstance.pact_slots` /
  `LiveCombatView.pact_slots_by_entity`** — the Pact Magic pool, all
  defaulting to `{}` and mirroring the existing `spell_slots` shape.
- **`PlayerIntent.target_ids: tuple[str, ...] | None`** — explicit
  multi-target aiming for a count-scaled cast (Magic Missile darts);
  `PlayerIntent.as_ritual: bool = False` — request a Ritual cast (rejected
  in-combat).
- **`resolve_short_rest(..., *, pact_slots=None, pact_slot_max=None)`** and
  **`resolve_long_rest(..., *, spell_slots=None, spell_slot_max=None,
  pact_slots=None, pact_slot_max=None, exhaustion_level=None)`** — all
  keyword-only, all default `None`. `RestOutcome` gains `spell_slots`,
  `pact_slots`, `exhaustion_level`, each populated only when its matching
  input pair was supplied.
- **`SpellCast` event** — `actor_id`, `spell_id`, `slot_level`, `ritual`,
  `components`, `material`, `material_consumed`, `material_cost_gp`.
  Emitted after the slot gate on every PC cast path (on-turn, readied
  reaction, Counterspell). `CastFailedReason` gains `"ritual_in_combat"`.

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
  Effect-derived `passive_save_bonus` (Bless/Bane) on these two paths is
  still unenforced; see `BACKLOG.md`.
- Walls now block movement as well as sight; `edge_distance` returns `None` for
  an illegal step. On the grid, `ActorMoved` carries the whole intent's distance
  (one event per `move`); the zone backend still emits one per step.
- **`start_combat(grid_scene=...)` raises `ValueError`** when a combatant's
  `zone_id` is out of bounds or blocked, instead of silently seating them on an
  unusable cell.
- **A main-hand attack keeps the turn (R1, C14)** when `attacks_remaining > 0`
  after the swing, or when a two-weapon-fighting off-hand window is still
  open; the turn ends only once neither condition holds. A subsequent swing
  in the same Attack action no longer re-pays the Action (R2): only the
  first swing hard-gates on `action_available`, and an exhausted
  `attacks_remaining` on a later swing is a turn-KEEPING `AttackFailed`
  rather than the "no Action" rejection every other Action-costed intent
  raises. `AttackFailed` / `CheckRolled` (Hide, `escape_grapple`) /
  `SaveRolled` (Grapple, Shove) / `CombatantMoved` (Shove's push option) are
  new observable events on these paths; see the migration guide for the
  exact keep-turn predicate and draw discipline.
- **A monster with no `monster_template_slug` now attacks.** The legacy
  evaluator that used to swing template-less monsters was retired without a
  replacement, so they silently passed every turn; `_synthesize_attack_from_legacy_fields`
  now builds one typed `AttackActivity` per turn from the spec-level
  `attack_bonus` / `damage_dice` / `damage_type` fields (unparseable dice
  still no-op). Hosts with template-less monster party members will see them
  start attacking; seeded streams containing a template-less monster's turn
  move.
- **Weapon proficiency gates the Proficiency Bonus on an attack roll (C15).**
  `Combatant.weapon_proficiencies: list[str] | None` — `None` (the field
  never explicitly set on `PartyMemberSpec`) assumes proficient with every
  weapon; an explicit list, even empty, is enforced by weapon category or
  slug. Monsters are always proficient (never carry the field explicitly).
- **Attack range widens to three tiers (C15).** `_weapon_attack_range_ft`
  returns `(normal, max)`; a shot between `normal` and `max` now resolves at
  disadvantage (`"range:long"`) instead of the pre-C15 binary in-range/
  rejected split, and a melee weapon carrying the Thrown property can attack
  beyond its melee reach using its thrown bands instead of being rejected.
- **Ranged Attacks in Close Combat (C15).** A ranged (or effectively-ranged
  thrown) attack rolls with disadvantage (`"ranged_in_melee"`) when a living,
  sighted (`SpatialTopology.can_see`), non-Incapacitated hostile is within 5
  ft of the attacker.
- **Heavy-property disadvantage (C15).** A wielder with a raw Strength score
  below 13 rolls a Heavy weapon's attack with disadvantage.
- **Versatile grip (C15).** `PlayerIntent.two_handed: bool = False` — when
  `True` and the weapon carries `versatile_damage`, a melee swing uses the
  two-handed damage die instead of the one-handed die.
- **Damage attribution and crit tracking (C15).** `DamageApplied.source_id:
  str | None` (weapon slug / synthesized activity id / `"mastery:<slug>"`)
  and `DamageApplied.is_crit: bool = False`. A critical hit against a target
  already making death saves counts as two failures instead of one (SRD
  §Damage at 0 Hit Points).
- **Loading property (C15).** `Combatant.loading_weapon_fired_this_turn:
  bool = False`, reset at the actor's own turn start. A second Loading-weapon
  shot in the same turn is rejected pre-resolution with
  `AttackFailed(reason="weapon_already_fired")`, gated ahead of the Charmed
  target gate.
- **All eight 2024 weapon masteries (C15).** `activities/mastery.py`
  resolves Graze (flat governing-ability-mod damage on a miss) and Topple
  (Constitution save vs. `8 + proficiency + governing-ability mod`, prone on
  a failure, gated by the shared `is_condition_immune` helper) directly.
  Vex, Sap, Slow, Push, Cleave and Nick report through
  `ActivityResolutionContext.mastery_procs`, which the orchestrator folds
  into live combat state: Vex grants Advantage against the same target for
  the attacker's next 2 attack-roll turns (one-use); Sap marks the target
  with Disadvantage until the attacker's next turn start (one-use); Slow
  applies a flat, non-stacking −10 ft Speed penalty cleared at the source's
  next turn start; Push forces a full 10 ft move via `push_combatant`
  (controller ruling: always the full distance; the "Large or smaller" size
  gate is unmodelled); Cleave chains one extra attack+damage roll against the
  nearest eligible living hostile within 5 ft of the first target and within
  reach (deterministic tie-break by `entity_id`, once per turn, no re-proc);
  Nick's off-hand extra attack spends no Bonus Action and does not require
  one — `_offhand_window_open` now keeps the turn open after any Light
  main-hand swing even when the Bonus Action is already spent, so a host
  must submit `"pass"` to end such a turn (see the migration guide).
- **`test_capability_matrix.py`** gains six probes pinning the C15 rows in
  `docs/capabilities.md` (attack rolls, conditions, forced movement, weapon
  mastery).
- **A count-scaled cast now emits N `DamageApplied`, not one (C17).** A
  `damage`-kind activity whose `target.affects.count` formula references
  `@item.level` (Magic Missile) resolves N separate `DamageApplied` events
  sharing one rolled damage instance — 3 darts at slot level 1, +1 per slot
  level above 1. Total damage now scales ×N for every such cast; the draw
  count is unchanged (shared roll, applied N times). Targeting more
  entities than the resolved count, or an unknown `target_ids` entry, is
  rejected pre-slot with `CastFailed(reason="target_invalid")`.
- **An armed Counterspell/readied-cast reaction with no slot at its readied
  level is now skipped, not fired (C17).** `_pop_pending_reaction` gained
  an `eligible=` predicate; an ineligible reactor's reaction stays queued
  and its Reaction/slot are untouched. Counterspell is additionally gated
  on its own 60 ft range with line of sight (`_in_range_with_los`) — an
  out-of-range or LoS-blocked reactor's Counterspell is likewise skipped.
- **`build_party_member` fills an empty `spell_slots`/`pact_slots` from
  `CharacterBuildSpec.classes` (C17).** Previously an empty
  `CombatInstance.spell_slots` was copied verbatim (a caster with no
  slots); now an empty (falsy) pool falls back to `derive_multiclass_slots`
  / `derive_multiclass_pact_slots`. A host that relied on an empty
  `spell_slots` dict to make every cast fail with `CastFailed(reason=
  "no_slot")` will now see real, derived slots instead. A non-empty pool
  is untouched.
- **`CharacterBuildSpec.classes: dict[str, int]`** is the multiclass
  carrier (C17), reconciled with the single-class `class_slug`/`level`
  fields by a `model_validator(mode="before")`; `model_copy(update=...)`
  bypasses that validator (Pydantic does not re-run `mode="before"` on
  `model_copy`), so changing only one of `level`/`classes` via `model_copy`
  can desync them — construct a fresh instance instead.

### Fixed

- **A `PartyMemberSpec` that never set `attack_bonus` was pinned to a 0
  to-hit bonus (2026-09-02, C15 Task 1).** `Combatant.attack_bonus` widens
  from `int = 0` to `int | None = None`; `None` (the host never explicitly
  set `PartyMemberSpec.attack_bonus`) now correctly falls through to the
  real governing-ability-modifier + proficiency-bonus computation instead of
  being silently treated as a genuine `0` override. A host-supplied value
  (including every monster's, always threaded as a concrete int) is
  unaffected — byte-identical to every pre-C15 fixture. The engine's own
  `build_party.py` host-party-building path always sets `attack_bonus`
  explicitly (from the pre-computed character sheet), so this fix does not
  change its output — pre-existing behaviour there, unchanged.

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
