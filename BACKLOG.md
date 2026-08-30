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

- **Legendary actions are not modelled.** `Monster.legendary_actions` is
  populated for **30 monsters** in the corpus and never read; only
  `Monster.actions` drives a turn. Needs a legendary-point pool per creature,
  spent between other creatures' turns, and reset at the start of the
  creature's turn. Same for `lair_actions` (schema field exists; the corpus
  ships none today) and `special_abilities` (never consumed).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)
- **Monster `recharge` (5–6) abilities are not gated.** A breath weapon can be
  used every turn. Needs a per-creature recharge roll at turn start.
- **Regeneration is not modelled.**
- **Multiattack conditional clauses are not modelled.** Since C22 every
  multiattack token is labelled, so the five opaque-key monsters join
  precisely; doppelganger and chain-devil now ALSO count their conditional
  feat use ("uses Unsettling Visage if…") as one fixed use per turn. The
  "if …" clause needs a carve-out in `_parse_item_counts`. More important: the
  precise join emits limited-use special abilities unconditionally —
  doppelganger's Recharge-6 Unsettling Visage now fires every round because
  `expand_action_to_activities` never reads `MonsterAction.recharge`/
  `uses_per_day`. Recharge/limited-use gating is C18's
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py`)

## Core combat rules not modelled (2026-08-22)

- **Surprise is not modelled.** SRD 5.2 gives a surprised creature disadvantage
  on its initiative roll; `start_combat` has no surprise input.
- **Grapple and Shove are not modelled.** The `grappled` condition exists and
  can be applied by an effect, but no contested check resolves either action,
  and neither has an `IntentType`.
- **Two-weapon fighting is not modelled.** The `light` weapon property is
  parsed but grants no bonus-action attack.
- **Ritual casting is not modelled.** 28 spells carry `ritual: true`; the flag
  is never read.
- **Spell components are not enforced.** `components` / `materials` ship on
  every spell and are never checked.

## Movement (2026-08-22)

- **No elevation.** The grid is strictly 2-D, so flying creatures have no
  altitude and `movement_modes` beyond walk speed do not affect positioning.
- **No multi-tile creature footprints.** Every creature occupies one cell
  regardless of size.

## Event stream observability (2026-08-22)

- **Damage is not attributed.** `DamageApplied` carries no `source_id`, so
  damage cannot be credited to an attacker or effect — a killing blow cannot be
  attributed. Additive on the event model; owned by C15. (The roll-breakdown
  half of this entry closed in F2c: `AttackRolled` / `SaveRolled` /
  `CheckRolled` now carry `natural`, `modifier` and `sources`; the target's
  effective AC is still not reported.)
  (`packages/dnd5e-engine/src/dnd5e_engine/events.py`)

## Character building (2026-08-22)

- **No multiclassing.** `CharacterBuildSpec` carries a single `class_slug` +
  `level`. Multiclass spell-slot progression and per-class feature grants are
  unmodelled.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **Feats are almost entirely inert.** 1 of the 17 corpus feats carries a
  mechanical activity; the rest resolve to nothing.

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
  fall back to the Python registry. Owner: C12/C18 follow-up.
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
- **Vision is scene-lit only** (2026-08-27). No light sources (torches, *Light*,
  *Darkness*), no viewer-side obscurement, no Blinded emission from darkness;
  `can_see` reads `GridScene.lighting` / `obscurement_cells` plus the viewer's
  projected senses. Sunlight Sensitivity is C18.
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.can_see`)
- **Monster-cast AoE applies no forced-movement rider** (2026-08-27). Only the
  player-intent cast path calls `activities/forced_movement.py`, so a monster
  casting Thunderwave deals damage but pushes nobody.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::advance_monster_turn`)
- **Mutual unseen is reported twice** (2026-08-27). When neither combatant can
  see the other, `AttackRolled.sources` is `["unseen", "unseen"]` — one entry
  for the disadvantage and one for the advantage — because an `AdvantageSource`
  records presence only, not direction. A host rendering the source list shows
  the same word twice.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)
- **Opportunity attacks bypass the activity context** (2026-08-27). The AoO path
  hardcodes `advantage="normal"` and never calls `build_activity_context`, so an
  opportunity attack sees no cover, no conditions and no visibility — despite
  SRD 5.2's "a hostile creature that *you can see*" trigger. C14 seam.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Reactions (2026-07-03)

- **No-slot readied reactions fire for free.** `_resolve_readied_spell_cast`
  and `_drain_counterspell_reaction` decrement the reactor's spell slot only
  when one is available, but fire the reaction (spending the Reaction and
  applying the full effect) regardless — a reactor armed with an empty slot
  pool gets a free Shield/Counterspell. Host-gated today (the host chooses to
  arm), unpinned by any catalog scenario; the fix is a slot-availability gate
  at drain time (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`).
- **Counterspell range ungated at drain time.** SRD 5.2 Counterspell has a
  60-foot range, but `_drain_counterspell_reaction` fires for any armed
  reactor regardless of reactor↔caster distance. Unpinned — every catalog
  scenario co-locates them; needs a topology distance check at drain
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`).

## Weapon mastery (2026-07-03)

- **Weapon-mastery Topple bypasses `condition_immunities`.** C08's
  condition-immunity gate lives in `activities/effects.py::apply_activity_effects`,
  but `activities/mastery.py` (~line 199) is a second `ConditionApplied` emit
  site with no gate — a Topple-mastery hit still knocks a prone-immune target
  prone. Fix: factor the immunity check into a shared helper both emit sites
  call (grep-verified: exactly two emit sites today)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/mastery.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/effects.py`).

## Effect-change sidecars (2026-07-02)

- **Weapon-tagged to-hit bonus sidecar never consumed.** The orchestrator's
  `_fold_active_effect_changes` folds a weapon-tagged (`applicable_action_types
  == ["attack"]`) `attack.roll.bonus` change into the
  `passive_weapon_to_hit_bonus` sidecar key, but nothing downstream reads it —
  `build_activity_context` only lifts the untagged `passive_to_hit_bonus` into
  `ActivityResolutionContext.passive_attack_bonus`. A +N weapon's to-hit bonus
  therefore never reaches the attack roll via this sidecar (the sibling
  damage-side gap, `passive_weapon_damage_bonus`, has been closed —
  see `docs/migration/v0.1-to-v0.2.md`)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`).
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
activation-gated Rage `dr` fold on the active-effect path . One entry
of the the passive-projection spec allowlist remains recognized-but-deferred for lack of a landing
zone + apply logic:

- **Ability scores, proficiency grants, `ac.calc`, languages** — each needs its
  own landing zone + apply logic (ability-modifier path, proficiency sets +
  roll-path consumer, AC recomputation, languages field). No pinned scenario covers these; they stay deferred (routed to `skipped_keys`).

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

- **Opportunity attacks bypass the d20 pipeline.**
  `_resolve_pc_opportunity_attack` / monster OA path (`orchestrator.py` ~5007,
  ~5107) emit `AttackRolled(advantage="normal")` without consulting
  `roll_d20_test` sources; route them through `resolve_attack`'s primitive in
  C14. (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Standalone out-of-combat `resolve_check` has no exhaustion seam**
  (2026-08-27) — the in-combat activity path folds `ctx.d20_test_penalty`, but
  the host-facing `CheckSpec` carries no conditions/exhaustion field, so a
  library consumer rolling a check outside combat cannot express the SRD 5.2
  `-2 x level` D20 Test penalty. Additive fix: an `exhaustion_level: int = 0`
  (or projected `modifier`) on `CheckSpec`.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py:36`)
- **Attack proficiency is assumed.** `build_context.py:278` hard-codes
  `is_proficient_attack=True`; a wizard swinging a greatsword adds PB.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py`)
- **Weapon properties beyond `finesse`/`reach` are ignored.** `loading`,
  `thrown`, `light`, `two_handed`, `versatile` (`versatile_damage` is shipped
  and never chosen), `ammunition`, `heavy` are parsed by the data schema and
  never read. (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)
- **Weapon mastery: 2 of 8 resolve.** Only `graze` and `topple` are
  implemented; `sap`/`vex`/`slow`/`push`/`nick`/`cleave` log `mastery_deferred`
  and apply nothing. (`packages/dnd5e-engine/src/dnd5e_engine/activities/mastery.py`)
- **Upcasting scales dice only, never target count** (Magic Missile darts,
  Hold Person extra targets). (`packages/dnd5e-engine/src/dnd5e_engine/activities/dice.py`)

## Audit 2026-08-26 — action economy & turn structure

- **`dodge`, `hide` and `help` intents are no-ops.** They are valid
  `IntentType` values with no handler — `orchestrator.py` dispatches only
  `move_mark`/`move`/`dash`/`disengage`; the three fall through to the generic
  tail, consume the Action, end the turn and change nothing. Worse than a
  rejection because hosts see them "work". `search`/`study`/`influence`/
  `utilize` do not exist at all. (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Extra Attack for PCs is not modelled.** No attacks-per-action counter
  exists (only monster Multiattack via prose parsing). `extra-attack.json`
  ships `activities: []`. Action Surge, Flurry of Blows and two-weapon fighting
  are all blocked on the same missing "extra attack/action this turn" economy;
  Sneak Attack's once-per-turn flag is consequently never re-read
  (`orchestrator.py:604`). The generic-action tail calls `_advance_turn`, so a
  turn cannot hold two actions today.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **No ongoing-damage / regeneration / recharge producers.** (2026-08-26) F3a
  gave them a place to land — `turn_lifecycle.py` runs `round_start` /
  `turn_start` / `turn_end` hooks off the single `_end_turn_and_advance` path —
  but the only registered hooks are the pre-existing duration tick and
  reaction-effect expiry, plus F3b's timed-effect expiry. Start-of-turn damage
  (Acid Arrow, Spirit Guardians), regeneration and recharge rolls still have no
  producer.
  (`packages/dnd5e-engine/src/dnd5e_engine/turn_lifecycle.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_register_default_turn_hooks`)
- **Opportunity attacks ignore the exhaustion penalty and the condition attack
  rows** (2026-08-27) — the two OA paths still roll
  `live.rng.randint(1, 20) + attack_bonus` outside `resolve_attack`, so
  `d20_test_penalty`, Prone and Grappled do not reach them. C14 routes them
  through the shared primitive and inherits all three.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Initiative is host-supplied, not rolled.** `start_combat` orders the
  `initiative` values from the specs; no DEX-mod roll, no surprise, no delay.
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **`ended_reason="flee"` is never returned.** `_derive_ended_reason`
  (`orchestrator.py:5382`) yields victory / defeat_tpk / forced only.
- **Movement rules beyond the budget are absent:** standing from prone (half
  speed), crawling, climb/swim cost, jumping; `Combatant.movement_modes` is
  hydrated and never read. Occupancy (C16) treats every enemy space as
  impassable — the SRD's Tiny / two-sizes-larger pass-through and the "another
  creature's space is Difficult Terrain" cost both need creature size, which is
  not modelled; the forced-Prone consequence of ending a turn in a shared space
  is not applied either.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_move`)

## Audit 2026-08-26 — spellcasting & concentration

- **"One concentration spell at a time" is not enforced.** `orchestrator.py:2201`
  builds `existing_concentration` and nothing consumes it;
  `_record_effect_lifecycle_links` appends to `concentration_chain`. Casting a
  second concentration spell keeps both.
- **Concentration ends only on a failed damage save.** `_drop_concentration`
  has one call site (`orchestrator.py:1552`). Caster death, unconscious,
  incapacitated and voluntary drop never end it; concentration-flagged effects
  are also skipped by the duration tick (`:2549`) so they never expire by time.
- **Rests never restore spell slots.** `rest.py` has no slot handling; hosts
  must reset `spell_slots` themselves. Pact Magic and per-class slot tables do
  not exist — `spell_slots` is a host-supplied `dict[int, int]`.
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`)
- **Monster spellcasting never happens.** `_activity_is_offensive`
  (`monster_actions.py:83`) accepts attack/save only, so a `cast`-only
  Spellcasting action (49 monsters) is never selected, and the monster context
  is built with `spell_book={}` (`orchestrator.py:5303`).
- **Absorb Elements has no reaction path**; Hellish Rebuke is only a
  `last_damaged_by` target validator, not a trigger. (See "Reactions are not
  data-driven" above.)

## Audit 2026-08-26 — character derivation

`CharacterBuildSpec` → `build_party_member` derives only passive
resistances/senses/movement. HP, AC, proficiency bonus, skill/save
proficiencies and hit dice arrive pre-computed on the host-supplied
`CombatInstance`. The bridge's `sheet.py::derive_sheet` is a partial host-side
stand-in, not an engine capability. Specifically:

- **`CharacterBuildSpec.selected_choices` is a dead field** — accepted, never
  read. Fighting Styles, Expertise, Eldritch Invocations and every
  `Class.feature_choices` pool are unreachable.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_party.py`)
- **No `background_slug`.** `canonical/backgrounds/` (skills, tools, starting
  feat, ability options) is never consumed.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **Advancement types other than `ScaleValue` are ignored** (`activities/scale.py:73`):
  `AbilityScoreImprovement`, `HitPoints`, `Subclass`, `Trait`, `ItemGrant`.
  No ASI/feat at 4/8/12/16/19; no level-≥3 gate on subclass (`build_party.py:59`).
- **No AC computation in the engine** — armor + DEX cap, shields, Unarmored
  Defense, natural armor, Mage Armor, heavy-armor STR requirement (no schema
  field either), `Armor.stealth_disadvantage` (shipped, zero consumers).
  `passive_stats.py` explicitly defers `ac.calc`.
- **Skill/save proficiencies are caller-supplied strings**; nothing derives
  them from class/background. `validate_point_buy` / `STANDARD_ARRAY`
  (`rules/dice.py`) and `passive_perception` (`rules/skills.py:132`) have no
  callers; `CheckSpec` has no field for Jack of All Trades so
  `skill_check(jack_of_all_trades=...)` is unreachable from the public API;
  Reliable Talent, group checks and tool proficiencies are absent.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py`)
- **Class features that are prose-only in the corpus:** Extra Attack, Fighting
  Style, Divine Smite, Metamagic / sorcery points, Eldritch Invocations. Martial
  Arts ships passive changes (`system.damage.base.custom.formula`) that are not
  in the `passive_stats` allowlist. Bardic Inspiration grants a die nothing
  consumes. Rage never ends for "didn't attack / take damage". Cunning Action's
  bonus-action Dash is gated on `class_slug == "rogue"` rather than the feature.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/passive_stats.py`)
- **Equipment:** attunement limit (`requires_attunement` shipped, unread),
  ammunition decrement, versatile damage choice, shield don/doff, encumbrance —
  all absent. Magic-item charges are the one equipment mechanic that is real.
- **No Heroic Inspiration** (reroll) anywhere; XP is summed at `end_combat`
  but no threshold table / level-up path exists (host concern; noting the hook).

## Audit 2026-08-26 — monsters

- **Typed traits are hydrated but only Magic Resistance is consumed.**
  `Combatant.trait_mechanics` carries the 14 `MonsterTraitMechanic` values
  (C22); Magic Resistance grants save advantage against spell-sourced saves
  only ("other magical effects" — magic-item and spell-like monster saves —
  are not yet recognised, and the two orchestrator-level save paths (repeat
  save, concentration) do not read it). Pack Tactics, Legendary Resistance,
  Sunlight Sensitivity, Undead Fortitude, Regeneration, Flyby, … are C18.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/save_primitive.py`)
- **79 monster actions carry `recharge`; zero `.recharge` reads** (sharpens
  the "recharge not gated" entry above).
- **Monster damage resistances/immunities are never hydrated** onto `Combatant`
  (`_build_foe_combatants`); only vulnerabilities auto-hydrate from the template,
  so resistances/immunities must be host-supplied on `EncounterMemberSpec`.
  (Ability scores, save/skill proficiencies and the proficiency bonus DO
  hydrate as of F1b.)
- **Target selection is hard-coded lowest-HP living PC** (`orchestrator.py:5069`)
  with no reach/LoS/threat consideration; flee planning returns `None` on a
  grid (`_plan_flee_destination:695`) so a fleeing monster holds still.
- **Concentration is not dropped in `_record_death`** — only via the damage
  path — so any death that bypasses `_emit_apply_damage` leaves it standing.
- **Corpus damage resistances must carry their magical-bypass qualifier when
  hydrated** (2026-08-27). `Combatant.physical_resistances_nonmagical_only`
  defaults True (host-authored "…from nonmagical attacks" convention, C22-S04).
  When C18 hydrates `Monster.damage_resistances`, it must set the flag from
  Foundry `dr.bypasses` (`"mgc" in bypasses`), which is empty for every 2024
  SRD actor — otherwise SRD 5.2 unconditional B/P/S resistances would be
  bypassed by magic weapons. Immunities have no bypass axis at all.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py`)
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

## Catalog v2 scenarios without a prior entry (2026-08-26)

Seven e2e catalog-v2 scenarios (`specs/catalog-v2/c12.md`, `c13.md`, `c17.md`)
name a gap with no standalone bullet filed anywhere above — recorded here so
the close-gap protocol (delete-on-close) has an entry to delete.

- **C13-S01 — Casting a second concentration spell doesn't end the first.**
  `existing_concentration` is built in the orchestrator but nothing
  consumes it before `_record_effect_lifecycle_links` appends to
  `concentration_chain` — the chain grows unbounded instead of dropping the
  prior effect. (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **C13-S03 — Caster reduced to 0 HP does not end concentration.**
  `_record_death` never drops the dying caster's concentration effect.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **C13-S04 — Voluntary concentration drop has no intent path.** No
  `"drop_concentration"` `IntentType` exists; a caster who wants to end
  their own concentration (no action required, per SRD) has no seam to do
  so. (`packages/dnd5e-engine/src/dnd5e_engine/events.py`)
- **C17-S01 — No engine-side per-class spell-slot table derivation.** The
  engine only accepts a host-precomputed flat `spell_slots` dict; nothing
  reads a class's `spellcasting.progression` to project a level → slot-table
  row. (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **C17-S02 — Pact Magic has no separate slot pool.** Warlock spell slots
  are folded into the same flat `spell_slots` dict as every other caster;
  Pact Magic's Short-Rest recovery (the SRD's only Short-Rest-recovering
  pool) has no seam — `resolve_short_rest` carries no `pact_slots` param.
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`)
- **C17-S04 — Long Rest doesn't restore spell slots or reduce Exhaustion.**
  `resolve_long_rest`'s signature is `(pool, hp_current, hp_max) ->
  RestOutcome` — no `spell_slots`/`exhaustion_level` parameter exists, and
  `RestOutcome` has no field to report either.
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`)
- **C17-S05 — Upcast target-count scaling never fires (Magic Missile).**
  `activities/dice.py`'s scaling machinery reads only `DamagePart.scaling`,
  never a target's `target.affects.count` field; `PlayerIntent.target_id`
  is a single `str | None` with no multi-target/dart-count shape to route
  through, so a 3rd-level Magic Missile still fires only 1 dart, not 5.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/dice.py`)

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
  Retype to `int | None = None` (additive; needs a migration note) in C18/C23.
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
  today's scale; when C12/C18 add a *second* log-reading turn hook, hoist a
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

- **Frightened's line-of-sight gate and "can't approach the source of fear".**
  The disadvantage applies unconditionally (no `can_see` check) and movement
  toward the fear source is not blocked. Needs C16b's `can_see`.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)
- **Blinded / Deafened "automatically fail ability checks that require
  sight/hearing".** There is no per-check sense vocabulary on `CheckSpec` /
  `CheckActivity`, so a check cannot declare it requires sight or hearing.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/check.py`)
- **Incapacitated breaks Concentration and imposes Initiative disadvantage.**
  The concentration break lands with C13's one-concentration-at-a-time rules;
  initiative is host-supplied until C14 rolls it.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Invisible's "unless a creature can somehow see you" carve-out.** Both
  attack directions apply unconditionally; the per-observer sense check is
  C16b. (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)
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

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
