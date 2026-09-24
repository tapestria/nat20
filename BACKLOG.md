# Nat20 — Backlog & Gap Inventory

Known gaps in the Nat20 libraries: the `dnd5e-engine` rules/combat engine and
the `dnd5e-srd-data` canonical SRD dataset. This is the single source of truth
for "what the engine does not yet do." It tracks **library** gaps only — host
application concerns (narrators, persistence, world state, UI) are out of scope.

**Update protocol:** when you close a gap, delete its entry in the same PR that
closes it. When you discover one, add it under the right section with a date and
a `packages/…` file anchor. Keep entries engine/data-centric — no host-app paths.

Anchors are current as of `dnd5e-engine` / `dnd5e-srd-data` **v0.5.0** (Gen 1
`dispatch.py` / `rules/combat.py` were removed in 0.5.0; anchors re-verified
2026-08-26 by a code audit — see the "Audit 2026-08-26" sections).

The user-facing summary of the same information is
[`docs/capabilities.md`](docs/capabilities.md) — the per-mechanic matrix of what
resolves today. When you close a gap here, update that page too; its published
counts are pinned by `packages/dnd5e-engine/tests/test_capability_matrix.py`.

---

# dnd5e-engine

## Unimplemented activity kinds (2026-08-22)

- **`summon`, `transform` and `enchant` activities are narrative no-ops.**
  `activities/resolver.py::resolve_activity` routes all three to a logged
  no-op, as it does a `utility` activity carrying no effect riders. The
  measured consequence: **108 of 339 SRD spells (32%) load correctly and emit
  no events**, including 32 concentration spells — *Blur, Darkness, Fog Cloud,
  Spiritual Weapon, Wall of Force, Silent Image, Globe of Invulnerability,
  Expeditious Retreat*. Several are combat staples a host will reach for
  immediately. `summon` is the largest single bucket (35 spell activities) and
  needs a design decision first: summoned creatures imply adding combatants
  mid-combat, which the initiative model does not currently support.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/resolver.py`)

## Monster action economy (2026-08-22)

- **Monster-side ranged-in-melee/Vex/Sap threading is wired but inert
  (2026-09-02, C15 Task 6/3).** `orchestrator.py`'s monster attack site
  passes `attacker_ranged_in_melee`, `attacker_vex_advantage`, and
  `attacker_sapped` into the activity context and pops vex grants/sap marks
  after resolution, mirroring the PC site exactly — but a monster attack
  carries its damage on the `AttackActivity` itself, not a separate typed
  `Weapon` (`resolve_activity(activity, actx, weapon=None)`), so
  `attack.py`'s weapon-gated "effectively ranged" check and mastery-proc
  fold never fire for a monster attacker. A monster can still be the
  RECEIVING end of a vex grant or sap mark from a prior PC weapon hit
  (that half is live). Needs a monster weapon-mastery/property model;
  confirmed still open after C18 (2026-09-03) — out of that cluster's scope
  per its R10 ruling.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Multiattack conditional clauses are not modelled.** Since C22 every
  multiattack token is labelled, so the five opaque-key monsters join
  precisely; doppelganger and chain-devil now ALSO count their conditional
  feat use ("uses Unsettling Visage if…") as one fixed use per turn. The
  "if …" clause needs a carve-out in `_parse_item_counts`. (Recharge gating
  for the joined action itself — e.g. doppelganger's Recharge-6 Unsettling
  Visage — closed 2026-09-03, C18, via `rank_monster_actions` and the
  turn-start recharge roll. Limited-use gating is only partial: see "Typed
  `MonsterAction.uses_per_day` is never consulted" below.)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)
- **Typed `MonsterAction.uses_per_day` is never consulted, and a non-cast
  N/Day `uses.max` is never decremented** (2026-09-23).
  `_hydrate_monster_action_uses` reads only activity-level `uses.max`, so the
  24 bundled actions typed with `uses_per_day` (Aboleth Dominate Mind 2/Day,
  Quasit Scare 1/Day, Vrock Stunning Screech 1/Day, Dretch Fetid Cloud,
  Troll Loathsome Limbs 4/Day, …) are at will to the engine; and a
  non-cast activity with an integer `uses.max` (Sphinx of Valor's Roar) is
  hydrated into `uses_remaining` but only the cast path
  (`_resolve_monster_cast`) ever decrements it. Not a regression —
  Multiattack still outranks every such action — but none of them is
  limited. Fix shape: seed `uses_remaining` from `uses_per_day` when no
  activity carries a digit, and decrement non-cast uses on selection.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_hydrate_monster_action_uses`)
- **`_mark_monster_action_used` spends only the ranked action itself**
  (2026-09-23). When the chosen action is a Multiattack whose join
  substitutes a recharge sibling (a "uses X" clause resolving to a Recharge
  action), only `ranked[0]` — the Multiattack — is marked; the substituted
  recharge sibling is never marked spent, so it would fire every turn. No
  bundled Multiattack joins a recharge sibling today, so the corpus is
  unaffected; a corpus change that adds one would silently un-gate it.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_mark_monster_action_used`)
- **A monster's own AoE (cone/sphere/etc.) still resolves against a single
  chosen target, not the template** (2026-09-03, C18). Grid AoE template
  expansion (C16) is wired for the PC cast path; a monster save/damage
  action with an area shape resolves the same way every monster action
  always has — one picked target — rather than enumerating
  `cells_in_template` the way a PC's cast does.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Monster AI is friendly-fire unaware** (2026-09-03, C18). Nothing checks
  whether an ally stands in a chosen action's blast/save area (or a
  Multiattack's own reach) before the monster acts, unlike the PC-facing
  `PlayerIntent.direction` aiming a host controls by hand.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Utility-only and cost > 1 legendary actions are never selected by the
  built-in AI** (2026-09-03, C18). `_take_legendary_action` only considers
  entries whose `legendary_cost` is unset or `1` and that carry an
  attack/save/damage activity (or a castable spell) — a `utility`-only entry
  (e.g. Pounce) and a multi-point legendary action are skipped even when
  legal. The bundled corpus carries no multi-point legendary action today.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_take_legendary_action`)
- **Legendary Resistance is host-armed only — no AI policy decides when to
  spend it** (2026-09-03, C18). `resolve_legendary_resistance` is a pure
  seam a host calls before submitting the intent that will force a save;
  the built-in monster AI never calls it itself, so a monster never
  protects its own concentration or avoids a status condition unless a host
  makes that call on its behalf.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::resolve_legendary_resistance`)
- **Lair-variant Legendary Resistance counts are not modelled** (2026-09-23,
  noted at C18 final review). The corpus carries no "or N/Day in Lair"
  text for any monster's Legendary Resistance — e.g. the Ancient Gold
  Dragon keeps Foundry's flat 3 — so a monster fought in its own lair gets
  no extra uses.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/monsters/`)
- **Magic Resistance still does not reach the orchestrator-level save
  paths** (2026-09-03, C18 — unchanged from the prior "Typed traits" entry).
  The end-of-turn repeat save, the damage-triggered concentration check, and
  the Grapple/Shove Unarmed Strike save all bypass the typed activity
  resolver (`activities/save_primitive.py`) where Magic Resistance's
  advantage is granted; C18 wired Legendary Resistance's *conversion* onto
  all three via `_consume_armed_legendary_resistance`, but Magic Resistance's
  advantage grant was not threaded onto the same three paths.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Recharge state does not persist across combats** (2026-09-03, C18).
  `MonsterActionUses` (recharge_spent, uses_remaining) lives on
  `_LiveCombat`, discarded at `end_combat` like every other combat-scoped
  engine state (by design, per this engine's effects-are-combat-scoped
  convention) — a monster that used its recharge ability in one encounter
  always starts its next encounter fully recharged, with no cross-combat
  "still on cooldown" model.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Neither PC nor monster cast path drains a readied Shield reaction on a
  spell ATTACK** (2026-09-03). Both `hit_by_attack`-trigger drain sites gate
  on an ATTACK activity, not any attack roll: the PC's
  `_drain_pre_resolution_reactions` fires the drain only for
  `intent.intent_type == "attack"`, and the monster's shared
  `_resolve_monster_attack_activities` fires it only from the mundane
  attack/legendary-action attack path. A spell attack roll
  (`intent_type == "cast_spell"` on the PC side, `_resolve_monster_cast` on
  the monster side) never pops a target's readied Shield, even though a
  spell attack roll is exactly the kind of "attack roll" Shield's SRD 5.2
  text protects against.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Flee stance ignores Incapacitated** (2026-09-03; pre-existing, sharpened
  by C18 Task 9's new `has_fled` persistence). `_apply_monster_flee_stance`
  gates only on `current.is_alive and current.hp_current > 0` — an
  Incapacitated monster under its behavior profile's flee threshold still
  "retreats" and is marked `has_fled=True`, even though SRD 5.2's
  Incapacitated condition ("can't take any Action or Bonus Action") should
  block it from taking the Disengage-equivalent retreat action at all.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_apply_monster_flee_stance`)
- **Undead Fortitude's trigger ignores temporary HP on the live combat
  path** (2026-09-23). `activities/apply.py::apply_damage` gates the trait's
  CON save on `final_amount >= target.hp_current` — the pure resolver's
  snapshot of REAL HP only. Temp HP is a separate bucket the orchestrator
  absorbs damage from AFTER this event is emitted
  (`_emit_apply_damage`/`_emit_apply_temp_hp`), so a hit that the bearer's
  temp HP would have fully absorbed (no real-HP loss at all) can still force
  a needless CON save and, on a failure, an incorrect Death. Relatedly, the
  gate compares EACH damage part's amount against the same un-decremented
  `hp_current` snapshot, so a multi-type hit whose parts each fall short of
  the bearer's HP but together exceed it never triggers the save at all and
  the bearer drops without rolling.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py`)

## Core combat rules not modelled (2026-08-22)

- **Grapple's/Shove's size gate, free-hand gate, and distance-exceeded
  auto-release are not modelled** (2026-09-01). SRD 5.2 Grapple/Shove
  require "a hand free" (Grapple only) and cap the actor at one size larger
  than the target; "Ending a Grapple" also ends the condition when a forced
  move separates the pair beyond reach. None of the three block or
  auto-release `grapple`/`shove`/`escape_grapple` today — deferred to C14
  Task 10. The Push weapon mastery's "if it is Large or smaller" gate
  (2026-09-02, C15 Task 7) shares the same missing creature-size attribute
  and pushes every target.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_grapple`,
  `::_handle_shove`, `::_fold_mastery_procs`)
- **Ritual casting is out-of-combat only (2026-09-03, C17).** `spellcasting.
  resolve_ritual_cast(spell, *, prepared, ritual_adept=False)` is the host
  seam: it validates the Ritual tag + prepared/Ritual-Adept gate and returns
  the `RitualCast` (10-minute tax, no slot expended). An in-combat
  `PlayerIntent.as_ritual=True` is rejected (`CastFailed(reason=
  "ritual_in_combat")`) before any slot logic — the turn economy has no model
  for a 10-minute action, so ritual casting only resolves between combats,
  through the host calling `resolve_ritual_cast` directly.
  (`packages/dnd5e-engine/src/dnd5e_engine/spellcasting.py`)
- **Spell components are metadata-only, not enforced (2026-09-03, C17).**
  `SpellCast` now carries `components` / `material` / `material_consumed` /
  `material_cost_gp` (via `spellcasting.spell_component_metadata`) on every
  PC cast path, but nothing gates a cast on a gagged/Silenced caster, a free
  hand, a component pouch/focus, or a costed material's gold cost — a host
  decision per spec §5 C17.
  (`packages/dnd5e-engine/src/dnd5e_engine/spellcasting.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/events.py::SpellCast`)
- **The Cleave chain's damage routes through `_apply_on_hit_damage`, which
  folds Sneak Attack BEFORE the orchestrator writes the once-per-turn cap
  — the chained hit is structurally unguarded against a second Sneak
  Attack fold on the same turn** (2026-09-02, C15 final-review F7). Not
  reachable today: no shipped Cleave weapon (greataxe, halberd) carries
  Finesse or a ranged category, so `sneak_attack_triggers`'s qualifying-
  weapon gate always excludes them — but nothing in `_resolve_cleave_chain`
  itself re-checks `ctx.sneak_attack_spent` between the main hit and the
  chained one, so a future data change (a Finesse/ranged weapon gaining
  the `cleave` mastery) would silently double-fold the rider.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py::_resolve_cleave_chain`)

## Movement (2026-08-22)

- **No elevation.** The grid is strictly 2-D, so flying creatures have no
  altitude and `movement_modes` beyond walk speed do not affect positioning.
- **No multi-tile creature footprints.** Every creature occupies one cell
  regardless of size.

## Event stream observability (2026-08-22)

- **Spell/save/heal damage is not attributed (2026-09-02, narrowed by C15).**
  C15 added `DamageApplied.source_id` (weapon slug / synthesized activity id
  / `"mastery:<slug>"` for a mastery proc) and `is_crit`, and threads both
  through the weapon-attack path. Spell, saving-throw, and healing-adjacent
  damage paths still emit `source_id=None` — a C17+ seam. (The roll-breakdown
  half of the original entry closed in F2c: `AttackRolled` / `SaveRolled` /
  `CheckRolled` now carry `natural`, `modifier` and `sources`; the target's
  effective AC is still not reported.)
  (`packages/dnd5e-engine/src/dnd5e_engine/events.py`)

## Character building (2026-08-22)

- **Multiclassing: carrier, slot derivation, and per-class feature/HP/
  proficiency accumulation landed at build time; live combat still projects
  the primary class only (amended 2026-09-23, C19).**
  `CharacterBuildSpec.classes: dict[str, int]` (a `{class_slug: level}` map,
  reconciled with the single-class `class_slug`/`level` aliases) is the
  multiclass carrier; `derive_multiclass_slots` /
  `derive_multiclass_pact_slots` (`build_spec.py`) project it through
  `spellcasting.multiclass_caster_level` (per-class half/third rounding,
  summed, ONE table lookup — SRD §Multiclassing) into the Spellcasting and
  Pact Magic pools, and
  `derive_sheet` grants each class's own features, HP and hit dice, and
  proficiencies at that class's own level, including the non-stacking Extra
  Attack rule. The live-combat projection gap this leaves is its own entry
  below ("Live multiclass still projects the primary class only").
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **Feats are almost entirely inert.** 1 of the 17 corpus feats carries a
  mechanical activity; the rest resolve to nothing. Prerequisites are only
  partly checked (2026-09-24): a feat's free-text `requirement` (Grappler's
  "Strength or Dexterity 13+") is never validated, and the two epic boons
  whose corpus `prerequisites` carry no `level` entry at all — `boon-of-fate`
  and `boon-of-irresistible-offense` — are accepted below the SRD's Epic Boon
  floor of character level 19, unlike `boon-of-combat-prowess`, whose entry
  does carry `level: 19`.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py::_asi_level_feats`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/feat.py`)
- **Live multiclass still projects the primary class only (2026-09-23, C19
  scope cut, owner C20).** `Combatant` carries one class and its total
  level; `orchestrator.py::_granted_feature_slugs`, `_attacks_per_action` and
  `_pc_condition_immunities`, plus `activities/scale.py::build_scale_values`,
  all still resolve features from the PRIMARY class at TOTAL character
  level, so a live Fighter 1 / Wizard 4 is still granted the Fighter's
  level-5 Extra Attack mid-combat even though its build-time
  `DerivedSheet.extra_attack_count` correctly reports 0. Carrying per-class
  levels onto `Combatant` and through `build_scale_values` is C20's
  territory.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_granted_feature_slugs`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/scale.py::build_scale_values`)
- **Magic weapons named by slug aren't matched to their base weapon for
  proficiency (2026-09-24).** A class granted specific weapon slugs rather
  than a whole category — Rogue and Monk get `rapier`/`scimitar`/
  `shortsword`/… individually — gets no Proficiency Bonus against a magic
  variant of one of them, such as a Scimitar of Speed: Foundry's own
  `system.type.baseItem` links a magic weapon back to its mundane base
  weapon (the translator already reads `baseItem` for another purpose), but
  the canonical `Item` schema has no equivalent field yet, so
  `_is_proficient_with_weapon` can only match a `weapon_category` or the
  item's own slug. Root fix: a dataset `base_weapon` field built from
  `baseItem`, read by `_is_proficient_with_weapon`. A host can pin
  `attack_bonus` on `CombatInstance` meanwhile.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/item.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_is_proficient_with_weapon`)
- **`derive_sheet` does not apply several SRD inputs (2026-09-23, C19 scope
  cuts).** Recorded but not applied: languages, tool proficiencies, the
  background's Origin feat (`starting_feat_slug` is an unresolved Foundry
  id), ability increases from feats other than the Ability Score
  Improvement feat, and level-20 capstone increases (the Monk's Body and
  Mind is a fixed `points: 0` ASI entry up to 25, the Barbarian's Primal
  Champion a feature). Not validated at all: multiclass ability
  prerequisites (the sheet has no score history, and enforcing them would
  reject the corpus's own default-STR/DEX builds in C19-S09), choice-pool
  capacity (how many skills/invocations/styles a build may pick — Skilled's
  grants are not in the corpus), `attunement_constraint`, untrained-armor
  penalties (`armor_training` is reported so a host can apply them), and
  magic items' own passive effects (hosts pass them as `active_effects`).
  Feat repeatability is also prose-only, so `DerivedSheet.feats` is not
  de-duplicated: a feat reachable both as a bare feature-choice-pool pick
  and as a `feat:<class>:<level>:<feat>` token lands twice.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py::derive_sheet`)
- **In-combat consumers of several C19-derived sheet fields don't exist yet
  (2026-09-23, C19 scope cut).** `DerivedSheet.stealth_disadvantage`,
  `jack_of_all_trades` and `reliable_talent` are computed but never read
  in combat — `orchestrator.py`'s Hide handler applies no Stealth
  disadvantage for a hidden PC in noisy armor, and no in-combat skill/
  ability check applies Jack of All Trades or Reliable Talent (the
  standalone `check.py::resolve_check` is the only consumer today). A Mage
  Armor cast does not flip a target's derived `ac_calc_mode`. Feature-
  driven skill bonuses (Divine Order Thaumaturge, Primal Order Magician,
  Primal Knowledge) are similarly unread anywhere.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Architecture (2026-08-22)

- **Reactions are not data-driven.** `orchestrator.py` recognizes reactions
  through a closed `ReactionTrigger` literal that names a specific spell
  (`"targeted_by_magic_missile"`), plus per-spell branches
  (`_apply_magic_missile_shield_carveout`, `_hellish_rebuke_target_invalid`,
  `_drain_counterspell_reaction`). This contradicts the project's central design
  claim that new content is a data change, not an engine change: The typed
  vocabulary now ships (`ActivationBlock.reaction_conditions` /
  `ReactionTriggerKind`, C22); the orchestrator's `ReactionTrigger` Literal and
  the per-spell branches still need to read it (C13/C14 follow-up). Note the
  shipped canonical still stores the inheriting activity's own `type` (e.g.
  Shield's utility activity says `action` while carrying populated
  `reaction_conditions`) — consumers must not gate on
  `activation.type == "reaction"` until the inheritance regen lands; also, an
  empty `reaction_conditions` does not mean "not a reaction" (only the four
  SRD spell phrasings plus exact shape matches are typed).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Engine does not yet read `canonical/conditions/`.** The dataset category
  exists (C22, `AssetLoader.get_condition`), mirroring `rules/conditions.py`;
  per campaign design D3 the engine should prefer the data when present and
  fall back to the Python registry. Still open after C12 and C18 (neither
  reads the category); unowned.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)
- **`orchestrator.py` is ~5.5k lines**, about a third of the engine, holding the
  reaction queue, item/feature charge accounting, the monster turn, the effect
  lifecycle and the turn loop. Each is a coherent module; splitting them would
  make the combat loop readable without changing behaviour.

## Spatial mechanics (grid backend is in place; these are additive)

- **Route choice is fewest-squares, not cheapest.** `GridTopology.shortest_path`
  (`spatial.py`) is BFS over legal steps — walls, diagonal corner-cutting and
  enemy-occupied cells are all honoured (C16) — and `_handle_move` charges each
  leg's `edge_distance` to the movement budget, but the SEARCH does not minimise
  that cost. A mover is therefore routed straight through difficult terrain when
  a same-length detour would be cheaper (pinned by C16-S06). No threat-aware
  routing, no multi-tile creatures.
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.shortest_path`)

- **Thunderwave's push is an engine-side registry, not data** (2026-08-27).
  `activities/forced_movement.py::FORCED_MOVEMENT_RIDERS` names the spell by
  slug because the canonical activity carries the push only as prose. C22 seam:
  a typed push field on the save activity + a translator rule, then delete the
  registry.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/forced_movement.py`)
- **Monster walks ignore occupancy; line width is not modelled** (2026-08-27).
  `_walk_zone_path`, `_execute_flee_retreat` and the closing walk in
  `advance_monster_turn` all call `shortest_path` without `avoid=`, so a monster
  may path straight through a PC where a PC `"move"` intent may not — a
  deliberate, documented asymmetry, not an oversight;
  `cells_in_template("line")` is one cell wide, so a 5-ft-wide Lightning Bolt is
  treated as a 1-cell ray and a wider `template.width` is ignored.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_walk_zone_path`,
  `packages/dnd5e-engine/src/dnd5e_engine/spatial.py::cells_in_template`)
- **Vision is scene-lit only** (2026-08-27, amended 2026-09-02, 2026-09-03).
  No light sources (torches, *Light*, *Darkness*), no viewer-side
  obscurement, no Blinded emission from darkness; `can_see` reads
  `GridScene.lighting` / `obscurement_cells` plus the viewer's projected
  senses. Sunlight Sensitivity's attack-roll half closed C18 (the new
  whole-scene `GridScene.sunlight` flag); its ability-check half (the
  trait disadvantages ALL ability checks in sunlight) is still open (see "Typed traits are hydrated..." under "Audit 2026-08-26 —
  monsters" below). No *See Invisibility*-style effect flag
  pierces the Invisible condition either (C16b plan ruling R3) — only
  blindsight/
  truesight in range with line of sight do, via
  `orchestrator.py::_pierces_invisibility`; an effect-vocabulary carve-out is
  a future cluster's seam.
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.can_see`)
- **Monster-cast AoE applies no forced-movement rider** (2026-08-27). Only the
  player-intent cast path calls `activities/forced_movement.py`, so a monster
  casting Thunderwave deals damage but pushes nobody.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::advance_monster_turn`)
- **Opportunity attacks bypass the activity context — cover only**
  (2026-08-27, condition gap closed 2026-09-01 C14 Task 9, visibility gap
  closed 2026-09-02 C16b). The AoO path never calls `build_activity_context`,
  so an opportunity attack still sees no cover — despite SRD 5.2's cover
  rules applying to any attack roll. Condition-derived advantage/
  disadvantage, Exhaustion's D20 Test penalty, Dodge, the "a creature that
  you can see" trigger (`_combatant_can_see` — no Reaction spent on
  failure), the `unseen` advantage source, and the Invisible/Frightened
  carve-outs all now reach the roll. Remaining gap is cover on the AoO roll
  itself.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Effect-change sidecars (2026-07-02)

- **Two effect-key namespaces for check/save bonuses (2026-08-26).** The public
  standalone check resolver folds `check.bonus` / `check.skill_check.bonus` /
  `check.ability_check.bonus` / `save.bonus` / `save.saving_throw.bonus` /
  `save.<long ability>.bonus` (e.g. `save.wisdom.bonus`), while the activity path
  (F1d) folds `abilities.check` / `abilities.skill` / `abilities.<ab>.save` (plus
  the Foundry-native `system.bonuses.abilities.*` / `system.abilities.<ab>.
  bonuses.save` spellings) into the `check_modifiers` / `save_modifiers`
  sidecars. An ActiveEffect authored against one key set is therefore INERT on
  the other surface. Recommended resolution: alias the standalone resolver's key
  set onto the `abilities.*` family (one normalization table, both consumers) as
  part of C12 / C19 — not aliased now, deliberately, to keep the F1d change
  behaviour-preserving.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py:108`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_fold_d20_test_bonus`).
## Class / species feature mechanics

- **Unconsumed `system.bonuses.heal.*` buckets (2026-08-26).**
  `activities/heal.py::resolve_heal` never reads any bonus sidecar off
  `ActivityResolutionContext` (unlike `attack.py`'s `passive_*_damage_bonus`
  fields), so a `system.bonuses.heal.*` change on an active effect is inert.
  (The attack/damage, `spell.dc` and — as of F1d — `abilities.check` /
  `abilities.skill` / `abilities.<ab>.save` families are folded.)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/heal.py`)

### Passive-stat projection (`activities/passive_stats.py`)

The interpreter now projects always-on `dr` (damage resistance), `di`
(immunity), `dv` (vulnerability), `ci` (condition immunity), `senses`, and
`movement` (walk-speed bonus + typed non-walk modes) at combat start, plus the
activation-gated Rage `dr` fold on the active-effect path. One entry
of the the passive-projection spec allowlist remains recognized-but-deferred for lack of a landing
zone + apply logic:

- **Ability scores (direct passive overrides) and languages** (amended
  2026-09-23, C19) — each still needs its own landing zone + apply logic.
  `ac.calc`, `weaponProf`, `armorProf` and HP bonuses are now read by
  `derive_sheet` — outside this interpreter's own allowlist,
  `rules/character.py` reads the same always-on `changes` list directly
  (`ac_modes_from_changes`, `armor_training_from_changes`,
  `weapon_proficiencies_from_changes`, `hit_point_bonus`). A feature that
  overrides an ability score directly (rather than through a
  `background:`/`asi:` choice token) and species/feature language grants
  are still routed to `skipped_keys`.
- **Fast Movement's heavy-armor condition and Unarmored Movement's symbolic
  `@scale` value are not modelled** (2026-09-23, C19 scope cut). Fast
  Movement's own passive change is an unconditional flat `+10` walk-speed
  add — its "doesn't function while wearing heavy armor" text lives only in
  corpus prose, not in a structured field, so the interpreter (which never
  sees worn equipment) has no way to suppress it for a character in heavy
  armor. Unarmored Movement's bonus is the symbolic value
  `@scale.monk.unarmored-movement`, which `_resolve_movement_modes` already
  defends against reaching a numeric field — it lands in `skipped_keys`
  rather than resolving the level-scaled bonus a real ScaleValue lookup would
  give.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/passive_stats.py`)

## Rest & recovery

- **Non-`@scale` symbolic feature-use caps fall back to uncapped** (2026-07-03,
  narrowed 2026-07-04). `orchestrator.py::_feature_use_cap` now
  resolves a literal-integer `uses.max` exactly AND a `@scale.<owner>.<key>`
  max against the caster's real ScaleValue map (`build_scale_values`), so
  Second Wind caps at its true level-scaled value (3 at Fighter L5 via the
  `{1: 2, 4: 3, 10: 4}` table). The residual gap: a NON-`@scale` symbolic max
  — `@prof` (9 features), `max(1, @abilities.cha.mod)` / `5 * @classes.paladin.levels`
  (~6 more) — is not resolved and falls back to UNCAPPED rather than a wrong
  floor (a capped resource is never wrongly rejected; this preserves pre-existing
  behaviour for those features). Thread the caster's proficiency bonus / ability
  modifiers into the cap resolver to close it
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`).
- **Non-literal feature-recovery formulas are unhandled** (2026-07-04). `rest.recover_feature_uses` honours each feature's
  typed `uses.recovery` rules: `recoverAll` fully recharges, a literal-integer
  `formula` regains that many uses, and a period-miss (with recovery data
  supplied) correctly preserves `spent` (lr-only features do not recharge on a
  Short Rest). The residual: a NON-literal recovery formula (e.g. an
  `@abilities.*` expression) is not evaluated — the counter is left unchanged
  rather than guessed. Zero corpus occurrences today (a structural scan of
  `canonical/features` shows all 5 `formula` recovery entries are the literal
  `"1"`); thread roll-data evaluation through if such data ever lands
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`).

## Discovered during demo webapp final review (2026-08-19)

- **`_REGISTRY` retains `_LiveCombat` entries after `end_combat` — no
  eviction.** `_REGISTRY: dict[str, _LiveCombat] = {}`
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:969`) is a
  module-global dict keyed by `handle.handle_id`. `end_combat` reads the
  live combat, builds the outcome, and returns — it never pops the entry
  out of `_REGISTRY`. The only way an entry ever leaves the dict is a
  wholesale `_reset_registry_for_tests()` `.clear()` (line ~5474), a
  test-only seam with no production caller. Every caller that opens and
  closes a combat therefore leaks one dict entry per combat, unbounded,
  for the lifetime of the process. The nat20 demo app
  (`apps/demo/src/nat20_demo/replay.py::replay_fight`) is a stateless
  HTTP handler that calls `start_combat` + `end_combat` once per request —
  a textbook case of exactly this pattern — and measurably leaks: ~43KB
  RSS retained per request, 201 combats still resident in `_REGISTRY`
  after 200 sequential /play requests against a single process. The
  demo mitigates operationally rather than fixing the root cause (Fly.io
  auto-stop recycles the machine on idle; `MAX_COMMANDS = 500` in
  `replay.py` caps per-combat size), but neither bounds total leaked
  entries under sustained traffic. Suggested engine fix: evict the
  `_REGISTRY` entry inside `end_combat` once the outcome is built, while
  caching the built `CombatOutcome` (e.g. keyed by `handle_id`, or
  returned from a small completed-handles cache) so a second `end_combat`
  call on the same handle still returns the same outcome rather than
  raising `UnknownHandleError` — `end_combat` is documented as
  idempotent under double-call and that guarantee must survive the fix.

## Audit 2026-08-26 — rolls & modifiers

- **Standalone out-of-combat `resolve_check` has no exhaustion seam**
  (2026-08-27) — the in-combat activity path folds `ctx.d20_test_penalty`, but
  the host-facing `CheckSpec` carries no conditions/exhaustion field, so a
  library consumer rolling a check outside combat cannot express the SRD 5.2
  `-2 x level` D20 Test penalty. Additive fix: an `exhaustion_level: int = 0`
  (or projected `modifier`) on `CheckSpec`.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py:36`)
- **`ammunition` is parsed and never read (2026-09-02, narrowed by C15).**
  C15 wired `finesse`, `reach`, `loading` (one-shot-per-turn cap),
  `thrown` (thrown-at-range attacks), `light` (Nick's off-hand-swing
  exemption), `two_handed`/`versatile` (grip selection via
  `PlayerIntent.two_handed`; `versatile_damage` is now chosen when
  two-handed), and `heavy` (the raw-Strength-13 disadvantage gate) into the
  attack-resolution path. `ammunition` — tracking how many pieces of
  ammunition a combatant carries, and blocking an attack when the supply
  runs out — is deliberately out of scope: it is host inventory-tracking
  state, not a rules computation, and the engine models no inventory.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)
- **Two-Handed weapon equip legality is out of engine scope (2026-09-02).**
  SRD 5.2 requires both hands free to wield a Two-Handed weapon (and bars
  it alongside a shield); the engine has no equipped-item/hand-occupancy
  model, so `PlayerIntent.two_handed` is accepted at face value with no
  legality check. Equip-slot bookkeeping is a host concern.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)

## Audit 2026-08-26 — action economy & turn structure

- **`search`/`study`/`influence`/`utilize` do not exist as `IntentType`
  values at all** (`dodge` closed C14 Task 3, `help` assist-an-attack-roll
  flavor closed C14 Task 4, `hide` closed C14 Task 5 — all 2026-09-01;
  Help's ability-check flavor is still open, no check-advantage producer
  exists). Deliberately deferred from C14 in full: the campaign design
  (spec §5, row C14) lists all four intents, but none has an approved
  catalog acceptance scenario or a harmonised API-DELTAS row — a maintainer
  flag, not an oversight.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Hide costs no Action** (2026-09-01). SRD 5.2 costs an Action to Hide;
  `_handle_hide` deliberately charges no Action/Bonus-Action budget (the
  same turn-keeping shape as Dash/`drop_concentration`) because the
  approved S02 catalog script requires a hide-then-attack sequence inside
  one turn, and the first attack swing hard-requires the Action — an
  Action-consuming Hide would make that script unsatisfiable. Tighten once
  strict Attack-action accounting lands.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_hide`)
- **Help's ability-check flavor is unimplemented.** No check-advantage
  producer exists on the check-resolution path, so a helper cannot grant
  Advantage on an ally's upcoming ability check (only the attack-roll
  flavor is wired).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/check.py`)
- **Help has no "target is an enemy of the helper" gate.** SRD 5.2 Help's
  ability-check flavor requires the helped creature to be "an enemy of the
  one you're helping"; the attack-roll flavor's `help_grants` bookkeeping
  accepts any `target_id`, including the helper's own ally or self, with no
  validation.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_dispatch_simple_turn_ending_intent`)
- **A redundant second Grapple attempt appends an orphaned, inert
  `ActiveEffect`.** `_handle_grapple` never checks whether the target is
  already Grappled by the same attacker before rolling a fresh save and
  appending another `"Grappled"` effect; the pre-existing condition's
  `source_effect_id` still wins, so the second effect sits in
  `live.active_effects` doing nothing until combat ends. Compounding this:
  `escape_grapple`/`_handle_escape_grapple` clears the Grappled condition
  outright on a successful escape check rather than decrementing a
  grappler-count, so a victim held by TWO grapplers (the original plus this
  redundant-attempt orphan) is freed from BOTH by a single successful escape
  — a one-check-escapes-two leniency — while the second, never-consulted
  `ActiveEffect` remains orphaned in `live.active_effects` regardless.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_grapple`,
  `::_handle_escape_grapple`)
- **A grappler killed without a `ConditionApplied` (Incapacitated) path
  does not auto-release its victim.** `_release_grapple_victims_of` fires
  only from the Incapacitated fold inside `_fold_condition_onto_combatant`;
  a grappler removed from combat by a path that never applies Incapacitated
  leaves its victim's Grappled condition stuck. SRD 5.2 "Ending a Grapple"
  names only the Incapacitated case, so this is RAW-arguable rather than a
  clear defect — recorded for a future ruling.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_release_grapple_victims_of`)
- **Monster AI never selects Dodge, Hide, Help, Grapple, or Shove.**
  `advance_monster_turn` has no branch that chooses any of the five C14
  actions; a monster only ever attacks, casts, moves, or flees.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::advance_monster_turn`)
- **No ongoing-damage producer.** (2026-08-26, narrowed 2026-09-03 C18) F3a
  gave it a place to land — `turn_lifecycle.py` runs `round_start` /
  `turn_start` / `turn_end` hooks off the single `_end_turn_and_advance` path —
  but the only registered hooks are the pre-existing duration tick and
  reaction-effect expiry, plus F3b's timed-effect expiry. Start-of-turn damage
  (Acid Arrow, Spirit Guardians) still has no producer. (Regeneration and
  recharge rolls closed C18 — they run at the head of a driven monster turn,
  `_run_monster_turn_start`, rather than as a registered `turn_start` hook;
  see `docs/migration/v0.5-to-v0.6.md`.)
  (`packages/dnd5e-engine/src/dnd5e_engine/turn_lifecycle.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_register_default_turn_hooks`)
- **Initiative has no "Delay" option.** C14 Task 8 (2026-09-01) added the
  engine-rolled `d20 + DEX modifier` path (`initiative=None`) with Surprise
  and Incapacitated Disadvantage; the SRD "Delay" combat option (holding
  your Initiative count to act later) is still absent.
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **Movement rules beyond the budget are absent:** crawling, climb/swim
  cost, jumping; `Combatant.movement_modes` is hydrated and never read.
  Standing from Prone (half Speed, rounded down) closed C14 Task 7
  (2026-09-01) via the `stand_up` `IntentType`
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_stand_up`).
  Occupancy (C16) treats every enemy space as
  impassable — the SRD's Tiny / two-sizes-larger pass-through and the "another
  creature's space is Difficult Terrain" cost both need creature size, which is
  not modelled; the forced-Prone consequence of ending a turn in a shared space
  is not applied either.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_move`)

## Audit 2026-08-26 — spellcasting & concentration

- **Empty `scaling.mode` is treated as whole-mode dice scaling on upcast
  (2026-09-03, C17).** `activities/dice.py::_scaling_steps` scales dice for
  any leveled spell whose damage part carries the corpus-default
  `scaling {number: 1, mode: ""}`; Foundry treats `mode: ""` as no scaling.
  C17 added a narrow guard in `activities/damage.py` (count-bearing
  activities — those whose `target.affects.count` contains `@item.level`,
  per `spellcasting.count_scales_with_cast_level` — roll at base level so
  Magic Missile darts stay 1d4+1), but every OTHER leveled spell with an
  empty mode still gains dice per slot above base. Needs a corpus scan and
  a decision on whether `""` should mean "none" (would shift results for
  hosts upcasting such spells).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/dice.py`)
- **Magic Missile darts share ONE damage roll applied N times, not N
  independent rolls (2026-09-03, C17, ruling R5).** SRD RAW rolls each
  dart's `1d4+1` separately; `resolve_damage` rolls the part once per
  activity and applies that single result to every target in the
  count-scaled fan-out, so all darts in one cast always deal identical
  damage. This is a documented deviation kept deliberately for draw-count
  determinism (a seeded replay's RNG draw count does not grow with slot
  level) rather than a gap to close.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/damage.py::resolve_damage`)
- **Pool choice for a multiclass Warlock cast is Spellcasting-first
  (2026-09-03, C17 R3); no per-class spell-list gate or `use_pact_slot`
  flag.** `_slot_available`/`_take_spell_slot` always try the regular
  Spellcasting pool before Pact Magic; SRD §Multiclassing lets either pool
  cast either prepared spell, so this is correct for slot AVAILABILITY, but
  a caller cannot force a specific pool to be spent (e.g. to bank
  Spellcasting slots and burn Pact Magic first, or vice versa).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_take_spell_slot`)
- **Attack-kind repeat instances (Scorching Ray's rays) are not
  count-scaled (2026-09-03, C17).** R5's target-count scaling
  (`resolve_target_count` / `target.affects.count`) only expands a
  `damage`-kind activity's target list; the corpus encodes an
  `attack`-kind spell's multiple-instances count (Scorching Ray: "three
  rays", one attack roll each) only in description prose, not in a typed
  field the resolver reads, so a single Scorching Ray cast still resolves
  one attack roll regardless of slot level.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)
- **Long Rest 16-hour cooldown / rest interruption are host time-model
  concerns (2026-09-03, C17).** SRD 5.2 §Long Rest: "After you finish a
  Long Rest, you must wait at least 16 hours before starting another one."
  It also lists interrupting activity (walking, fighting, casting a spell)
  as voiding progress; `resolve_long_rest`/
  `resolve_short_rest` are pure functions with no calendar/clock input, so
  neither the cooldown nor interruption tracking exists — a host wanting
  either must gate its OWN call to these resolvers.
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`)
- **Absorb Elements has no reaction path**; Hellish Rebuke is only a
  `last_damaged_by` target validator, not a trigger. (See "Reactions are not
  data-driven" above.)

## Audit 2026-08-26 — character derivation

`derive_sheet` (C19) closed most of this audit's findings: HP, AC, hit dice
and skill/save proficiencies are now computed engine-side from
`CharacterBuildSpec`, and `build_party_member` folds them into
`PartyMemberSpec` for any value a host leaves unset. The bridge's `sheet.py`
now calls the engine rather than standing in for it. Residual gaps:

- **Group checks and tool proficiencies are absent.** Neither is derived from
  class/background/equipment, nor accepted as an explicit build input.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **Class features that are prose-only in the corpus:** Fighting Style, Divine
  Smite, Metamagic / sorcery points, Eldritch Invocations. (Extra Attack
  closed C14 Task 1 — `_attacks_per_action` reads the granted
  `extra-attack`/`two-extra-attacks`/`three-extra-attacks` feature slugs.)
  **Action Surge and Flurry of Blows are still not modelled** (2026-09-01):
  both grant an extra Action/action-equivalent mid-turn, which needs its own
  seam distinct from the per-Action `attacks_remaining` counter C14 added —
  neither feature's `activities` array carries a typed effect the resolver
  reads. Martial Arts ships passive changes
  (`system.damage.base.custom.formula`) that are not in the `passive_stats`
  allowlist. Bardic Inspiration grants a die nothing consumes. Rage never
  ends for "didn't attack / take damage". Cunning Action's bonus-action Dash
  is gated on `class_slug == "rogue"` rather than the feature.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/passive_stats.py`)
- **Equipment:** attunement limit (`requires_attunement` shipped, unread),
  ammunition decrement, versatile damage choice, shield don/doff, encumbrance —
  all absent. Magic-item charges are the one equipment mechanic that is real.
- **No Heroic Inspiration** (reroll) anywhere; XP is summed at `end_combat`
  but no threshold table / level-up path exists (host concern; noting the hook).

## Audit 2026-08-26 — monsters

- **Typed traits are hydrated; only Flyby, Nimble Escape, Keen Senses and
  Aggressive are still unconsumed (amended 2026-09-03, C18).**
  `Combatant.trait_mechanics` carries the 14 `MonsterTraitMechanic` values
  (C22). Magic Resistance grants save advantage against spell-sourced saves
  only ("other magical effects" — magic-item and spell-like monster saves —
  are not yet recognised, and the orchestrator-level save paths — repeat
  save, concentration, Grapple/Shove — still do not read it). C18 landed
  Pack Tactics (attack advantage), Sunlight Sensitivity (attack
  disadvantage — its ability-check half is not modelled: the bundled trait
  text is "While in sunlight, the monster has Disadvantage on ability checks
  and attack rolls.", so every ability check the bearer makes in sunlight
  should roll at Disadvantage), Undead Fortitude
  (CON save to hold at 1 HP), Swarm (no HP/temp-HP gain) and Legendary
  Resistance. Flyby (no flying-movement tracking) and Nimble Escape
  (untyped bonus action; the monster AI takes no bonus actions) are not
  modelled; Keen Senses and Aggressive are absent from the SRD 5.2 corpus
  entirely.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/save_primitive.py`)
- **Target selection is hard-coded lowest-HP living PC** (`orchestrator.py:5069`)
  with no reach/LoS/threat consideration — the monster AI never consults
  `_combatant_can_see` or a Frightened monster's own line-of-sight/
  no-approach rule when choosing a target or walking; confirmed still open
  after C18 (2026-09-03) — a rule card scoped it out as not an SRD rule, so
  this stands as a deliberate scope cut, not an oversight. Same status for
  flee planning, which returns `None` on a grid (`_plan_flee_destination:695`,
  C18 S08 needs only the `has_fled` flag, not movement) so a fleeing
  monster holds still.
- **`PartyMemberSpec` has no `physical_resistances_nonmagical_only`
  counterpart** (2026-08-30). PCs are pinned to the nonmagical-only reading of
  host-authored B/P/S resistances; a PC whose resistance should be
  unconditional cannot express it.
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **Bridge does not serve the `conditions` / `traits` categories**
  (2026-08-27) — `routes_content._CATEGORIES` predates C22.
  (`packages/nat20-bridge/src/nat20_bridge/routes_content.py`)

## Not modelled by design (recorded so nobody re-audits them)

Hiding vs passive
Perception, falling, suffocation/drowning, underwater, extreme weather,
hazards/traps, objects as targets, mounted combat, elevation, multi-tile
footprints. Exploration-tier; revisit only if a host asks.

## Documentation drift

- `docs/capabilities.md` had ten ✅ rows the code did not back (Dodge/Hide/Help,
  monster spellcasting, saves, background, weapon mastery, concentration
  exclusivity, AoE templates, Extra Attack-less action economy, opportunity
  attacks' "can see" check, ability-score/proficiency derivation). Corrected
  2026-08-26. Closed 2026-08-26: `test_capability_matrix.py::
  test_status_rows_match_code_probes` now pins ten representative rows to a
  grep-level code probe in both directions (five added by C16, 2026-08-27). The probe set is a sample, not
  exhaustive — **add a probe entry whenever a status row is flipped.**

## Foundations follow-ups (2026-08-26)

Reviewed and deliberately deferred during the F1–F3 foundations pass (actor
stat projection, unified d20, turn lifecycle). Each is additive and none blocks
a cluster; they are consolidated here so they are not re-discovered.

- **`AdvantageMode` and `TurnPhase` are not top-level exports.** Both live on
  `dnd5e_engine.events` and are reachable there, and the package exports no
  other event class or roll-mode alias from `__init__.py`, so the asymmetry is
  consistent rather than an omission. Revisit only if the whole event surface is
  re-exported. (`packages/dnd5e-engine/src/dnd5e_engine/__init__.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/events.py`)
- **`EncounterMemberSpec.dexterity: int = 10` is a lossy sentinel.** The monster
  template hydration cannot distinguish "host left the default" from "host
  explicitly set 10", so an explicit 10 always defers to the template's DEX.
  Retype to `int | None = None` (additive; needs a migration note) in C23
  (C18 did not retype it).
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **Roll events cannot report bonus DICE.** `roll_total == natural + modifier`
  only when no Bless/Bane-style bonus die applied; `modifier` deliberately
  excludes them (they are rolled after the d20 to keep the seeded stream
  stable), so the printed breakdown does not add up in that case. Fix shape: an
  additive `bonus_dice_total: int | None` on `AttackRolled` / `SaveRolled` /
  `CheckRolled` / `ConcentrationCheck`.
  (`packages/dnd5e-engine/src/dnd5e_engine/events.py`)
- **`TurnLifecycle` has no public registry introspection.** The registration
  ORDER of turn hooks is a determinism contract, and the only way to assert it
  is reading the private `_hooks` list (`tests/test_turn_lifecycle.py` does).
  A `registered_keys(phase) -> tuple[str, ...]` accessor is the clean fix.
  (`packages/dnd5e-engine/src/dnd5e_engine/turn_lifecycle.py`)
- **The turn-start log index is recomputed per candidate effect.**
  `_effect_applied_during_current_turn` rescans the event log for each
  until-end-of-next-turn effect at a turn boundary. Bounded and immaterial at
  today's scale (C18 added no such hook — its monster turn-start mechanics
  run from `_run_monster_turn_start`); if a *second* log-reading turn hook is
  ever added, hoist a
  single `current_turn_start_index` computed once in `_begin_turn` and have
  both hooks read it.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_begin_turn`)
- **The two orchestrator-level save paths skip effect-derived save bonuses.**
  The concentration check and the end-of-turn repeat save now honour the
  condition projections (auto-fail, Restrained DEX disadvantage, exhaustion)
  but still not the effect-derived `passive_save_bonus` (Bless/Bane). The
  repeat-save path also honours `passive_save_dis` but not `passive_save_adv`.
  Owned by C13.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Damage at 0 Hit Points (2026-08-29)

Surfaced while landing C12-S06 (Characters fall Unconscious at 0 HP).

The first two entries are **ACCEPTED KNOWINGLY** by the C12 controller ruling
(2026-08-29): both are halves of the same missing seam — per-damage-instance
attribution on `DamageApplied` (a shared `source_id` / instance id, plus the
crit flag). **C15 (attack rules) owns that seam and therefore owns both fixes**;
neither is repairable inside C12 without inventing the event field C15 will add.

- **A multi-type hit inflicts one death-save failure PER DAMAGE TYPE.** SRD 5.2
  "Damage at 0 Hit Points" charges one failure per instance of damage, but
  `activities/apply.py` emits one `DamageApplied` per damage type and the 0-HP
  fold counts a failure per event, so a fire+slashing hit on a downed Character
  costs two failures. Needs per-event attribution (a shared `source_id` /
  instance id on `DamageApplied`) so the fold can collapse the events of one
  attack — the same seam the Critical-Hit entry below needs. Owner: **C15**.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:1877`
  `_apply_zero_hp_to_character`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py:75`)
- **Two death-save failures on a Critical Hit at 0 HP are not applied.** SRD 5.2
  "Damage at 0 Hit Points": a Critical Hit inflicts two failures. C12 landed the
  auto-crit itself (Paralyzed/Unconscious target within 5 ft), so the engine now
  produces exactly the situation the rule covers — but `DamageApplied` carries
  no crit flag, so `_apply_zero_hp_to_character` calls
  `state.apply_damage_while_unconscious(False)` with the argument hard-coded and
  always records one failure. Same `DamageApplied` attribution seam as the
  multi-type entry above; fixing either alone would be guesswork. Owner: **C15**.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:1920`
  `_apply_zero_hp_to_character`)
- **A death-save failure from damage at 0 HP surfaces no event.** The failure is
  written straight onto `Combatant.death_saves`; hosts narrating from the event
  stream see the `DamageApplied` but never learn a failure landed (only
  `DeathSaveRolled`, from the turn-start roll, carries counters). The fix needs
  a new `CombatEvent` member (or a counters payload on an existing one), which
  the C12 constraints forbid mid-cluster.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:1877`)

## Conditions — SRD 5.2 rows not enforced (2026-08-27)

C12 gave all 15 conditions teeth on the live combat path (see
`docs/capabilities.md`). These rows are what is left; each needs a seam another
cluster owns.

- **Frightened's ability-check half of the line-of-sight gate** (2026-09-02).
  SRD 5.2 Frightened: "Disadvantage on ability checks and attack rolls while
  the source of fear is within line of sight." C16b gated the attack-roll
  half (`conditions_grant_advantage_on_attack`'s `fear_source_in_sight`
  kwarg) and the "can't willingly move closer to the source of fear"
  movement rule (`MoveFailed(reason="frightened")`); the ability-check half
  still applies the disadvantage unconditionally.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py::conditions_grant_disadvantage_on_ability_checks`)
- **Frightened's no-approach rule is additionally gated on line of sight to
  the source (plan ruling R5); SRD 5.2 imposes it unconditionally**
  (2026-09-03). SRD 5.2 Frightened's "You can't willingly move closer to the
  source of fear." sentence carries no line-of-sight conjunct — only the
  disadvantage sentence does — but the engine's `_frightened_approach_blocked`
  reuses `_combatant_can_see` for both, a deliberate (kept) deviation: a
  Frightened creature that cannot currently see its fear source may move
  toward it unimpeded, where SRD 5.2 would still block the approach.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_frightened_approach_blocked`)
- **Blinded / Deafened "automatically fail ability checks that require
  sight/hearing".** There is no per-check sense vocabulary on `CheckSpec` /
  `CheckActivity`, so a check cannot declare it requires sight or hearing.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/check.py`)
- **Charmed grants the charmer advantage on social ability checks.** The
  engine has no social-interaction check surface to attach it to (no
  `influence` intent, no interaction DC), so the row is unrepresentable rather
  than merely unimplemented.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)
- **Petrified's "immunity to the Poisoned condition".** The shipped projection
  gives poison *damage* immunity; SRD 5.2 grants immunity to poison damage AND
  to the Poisoned condition, and condition immunity is keyed off
  `Combatant.condition_immunities`, which no projection writes.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)

## C12 deferred minors (2026-08-27)

Small, real and deliberately not worth their own task; recorded so they are not
re-discovered.

- **`_condition_source_entity`'s effect-origin fallback is untested.** The
  `ActiveCondition.source_entity_id` branch is covered; the branch that walks
  `live.active_effects` for a `cast:<slug>:<id>` origin has no test.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:600`)
- **`activities/check.py::_check_modifier`'s skill-branch penalty fold is
  untested.** The exhaustion penalty is pinned on the ability branch only; the
  `return int(skills[key]) + penalty` line has no direct test.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/check.py`)
- **`_monster_dash_movement_budget`'s parameter is still named `base_speed`**
  although its caller now passes the condition/exhaustion-PROJECTED speed. A
  rename to `effective_speed` is cosmetic but removes a real reading trap.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py:736`)
- **The `enumerate(live.initiative)` → `model_copy` → slot-replace loop is
  open-coded 32 times** (four of them added by C12). A single
  `_update_combatant(live, entity_id, **update)` helper would collapse them.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Blocked

- **Lair actions are blocked on translator support** (2026-09-03, C18 R10).
  All 341 bundled monsters ship `lair_actions == []` (schema field exists,
  the translator never populates it from a Foundry source), so there is
  nothing for the engine to spend. The initiative-20 pseudo-turn a lair
  action needs (a scene-owned action outside any creature's own turn) is
  designed but unimplemented; blocked on dataset/translator work to source
  lair-action content before an engine seam is worth building.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/monster.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)
- **`custom` `ActiveEffectChange` mode — needs a product decision** (2026-07-02).
  No Foundry-core semantics to port: Foundry itself delegates `custom` to
  host-registered `applyChangeCustom` callbacks, so there is no SRD or
  in-repo ground truth for what it should do in this engine
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/effects.py`,
  `apply_changes_to_check` — `multiply`/`upgrade`/`downgrade` are
  implemented; `custom` is left a documented no-op). Downstream data
  carries none today — verified: `grep -rn '"mode": "custom"'
  packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/` returns zero
  matches. Blocked on a maintainer decision for what (if anything) `custom`
  should mean in a host-agnostic engine with no callback registry.

---

# nat20-bridge

The SillyTavern sidecar (`packages/nat20-bridge`) is a thin FastAPI routing
layer over the engine — see `docs/bridge.md`. Gaps found while shipping it:

- **`BuildRequest` lacks the C19 build-spec fields (2026-09-23).** The
  bridge's HTTP model still exposes only `species_slug`, `class_slug`,
  `subclass_slug`, `level`, `ability_scores` and `equipment` — a caller
  cannot reach `classes` (multiclass), `background_slug`,
  `selected_choices`, `hp_mode`/`hp_rolls`, `ac_calc_mode`, `attuned_items`
  or `ability_score_method` over `/v1/party/validate` or `/v1/combat`, even
  though `sheet.py` now derives from all of them.
  (`packages/nat20-bridge/src/nat20_bridge/models.py::BuildRequest`)
- **Global-`random` seeding is not safe under concurrent requests**
  (2026-08-21). `_start_route` (and `app.py`'s `_do_roll`/`_do_check`) seed the
  stdlib global `random` module to make the engine's legacy dice seam
  (`roll_dice_str`, `rules/effects.py`) reproducible per request, since that
  seam reads the global module rather than an injectable RNG. Two `/v1/roll`,
  `/v1/check`, or `/v1/combat` requests racing concurrently (different seeds)
  can have one request's reseed clobber the other's before its dice resolve —
  fine for the bridge's current single-connection, same-machine ST usage, not
  safe for concurrent multi-client load. Real fix: thread an injectable
  `random.Random` through the legacy dice paths instead of reading the global
  module (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py`).
- **Collector tasks + event logs leak for combats never `/end`ed**
  (2026-08-21). `BridgeState.combats`/`events_log`/`names`/`seeds`/`collectors`
  are only cleaned up by `_end_route` (`state.combats.pop`, `_stop_collector`)
  — a combat a client abandons without calling `POST /v1/combat/{cid}/end`
  keeps its background collector task running and its event log growing for
  the life of the bridge process. Needs either a TTL/idle-reap sweep or an
  explicit cap on live combats (`packages/nat20-bridge/src/nat20_bridge/state.py`).
- **`attack_bonus` derivation ignores Dexterity / finesse weapons**
  (2026-08-21). `derive_sheet`'s `attack_bonus = proficiency + str_mod`
  (`sheet.py`) always uses the Strength modifier, regardless of whether the
  character's weapon is finesse (SRD 5.2: finesse lets the wielder use either
  Strength or Dexterity, typically Dexterity for a Rogue/ranged-leaning build)
  or a ranged weapon (which SRD-legally uses Dexterity, not Strength, absent a
  feat). A Dex-based Rogue or ranged character gets an under- or over-stated
  attack bonus in `/v1/party/validate` and `/v1/combat` party derivation.
  Needs the weapon's `properties`/`weapon_kind` consulted to pick
  `max(str_mod, dex_mod)` for finesse or `dex_mod` for ranged
  (`packages/nat20-bridge/src/nat20_bridge/sheet.py`).

---

# dnd5e-srd-data

## Oracle coverage (2026-08-22)

- **The monster oracle covers 3 of 341 monsters (0.9%).** `tests/oracle/
  srd_monster_oracle.json` holds three entries; `test_canonical_against_oracle.py`
  compares only slugs the oracle contains, so **338 monsters have no fidelity
  check at all** and the suite still reports green. Spells (93%) and items (75%)
  are well covered by comparison. `tests/test_oracle_coverage_floor.py` now pins
  the current ratios so they cannot regress — raise the `monsters` floor as
  entries are added. Subclasses are similarly thin at 4 of 12 (33%).
  (`packages/dnd5e-srd-data/tests/oracle/srd_monster_oracle.json`)

## Shipped prose quality (2026-08-22)

- **All 341 monsters ship `description: ""`.** A host has nothing to render for
  any creature in the corpus. The translator populates per-action descriptions
  but never the top-level one.
  (`packages/dnd5e-srd-data/tools/translators/`)
- **Residual Foundry enricher markup and HTML entities in shipped prose.**
  Roughly 1,000 of 1,545 canonical files carry unresolved markup: 728
  `&Reference[…]`, 2,162 `[[lookup …]]`, 717 `&amp;` double-escapes, 1,018 HTML
  tags. **268 of the 931 monster action descriptions (28%) are essentially raw
  macros** — goblin-warrior's Scimitar reads
  `"[[/attack extended]]. [[/damage average extended]]…"`. A `cleanup_prose`
  translator exists and is unit-tested but is evidently not applied to these
  fields. Note that `[[/item …]]` tokens are load-bearing — the engine's
  multiattack fan-out parses them — so cleanup must preserve them while
  resolving `[[lookup]]`, `&Reference[]` and entity escapes.
  (`packages/dnd5e-srd-data/tools/translators/prose_cleanup.py`)
- **`monsters/ancient-gold-dragon.json` ships an unfilled template.** Its
  multiattack description is literally
  `"makes {count} [[/item]] attacks and uses [[/item]]"`, so the action cannot
  fan out. Every sibling ancient dragon names its Rend attack correctly, so the
  defect appears to be upstream rather than in our translator. Registered in
  `tests/oracle/known_prose_defects.json` and gated by
  `tests/test_corpus_prose_integrity.py`; re-check on the next
  `make refresh-upstream` and de-register if upstream has fixed it.
- **Inherited activation `type` is not resolved** (2026-08-27). An activity
  with `activation.override: false` inherits the item-level activation in
  Foundry (Shield's utility activity is a Reaction, but canonical stores the
  activity's own `type: action`). C22 derives `reaction_conditions` from the
  effective block but leaves `type` as shipped. Resolving it changes bytes on
  every inheriting activity — do it as its own regen PR.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_effective_activation`)

## Missing categories (2026-08-22)

- **`lair_actions` is empty for all 341 monsters** even though SRD 5.2 defines
  them for several creatures, and the schema field exists.

## Monster spellcasting ability gaps (2026-09-04)

- **`mummy-lord.spellcasting_ability` is `None` despite the monster casting
  spells.** Its Foundry source (`actors24/undead/mummy-lord.yml`) carries no
  usable signal: the top-level `attributes.spellcasting` is the `"str"`
  non-caster placeholder and every one of its cast activities' own
  `spell.ability` is empty — the ability is stated only in trait prose. It is
  the sole cast-bearing monster (of 65) the translator cannot resolve.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_spellcasting_ability`)
- **Coven-shared casting can outvote a monster's own spellcasting ability.**
  `sea-hag.spellcasting_ability` resolves to `"int"` because its shared
  "Coven Magic" trait contributes 6 cast activities at `int` versus 1 at its
  true personal ability (`con`, per `attributes.spellcasting: con` and its
  own "Illusory Appearance" cast activity) — majority-vote-by-activity-count
  picks the coven ability over the personal one. `green-hag` has the
  equivalent issue (resolves `"int"` via Coven Magic instead of its personal
  `"wis"`). A future pass could special-case or exclude coven/shared-trait
  cast activities from the vote.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_spellcasting_ability`)

## Magic-armor category and template defects (2026-09-23, C19)

`derive_sheet`'s AC formula reads each worn armor's `armor_category` and
`dex_bonus_max`. Several corpus items disagree with real armor math:
`dwarven-plate` ships `armor_category: "light"` with `dex_bonus_max: null`
(uncapped) on a base AC of 18, so a derived sheet adds the wearer's FULL
Dexterity modifier on top of 18 instead of a capped or ignored one;
`elven-chain`, `demon-armor` and `plate-armor-of-etherealness` carry the
same class of category/cap defect. The `armor-1-2-or-3`, `shield-1-2-or-3`,
`adamantine-armor` and `mithral-armor` crafting templates all ship
`base_ac: 10` regardless of the real armor they are meant to modify —
placeholders for a translator rule that never resolves the underlying base
item. None of this is a `derive_sheet` bug; the fix belongs in the
translator/dataset.
(`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/items/dwarven-plate.json`,
`elven-chain.json`, `demon-armor.json`, `plate-armor-of-etherealness.json`,
`armor-1-2-or-3.json`, `adamantine-armor.json`, `mithral-armor.json`)

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
