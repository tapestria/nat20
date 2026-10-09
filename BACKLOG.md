# Nat20 — Backlog & Gap Inventory

Known gaps in the Nat20 libraries: the `dnd5e-engine` rules/combat engine and
the `dnd5e-srd-data` canonical SRD dataset. This is the single source of truth
for "what the engine does not yet do." It tracks **library** gaps only — host
application concerns (narrators, persistence, world state, UI) are out of scope.

**Update protocol:** when you close a gap, delete its entry in the same PR that
closes it. When you discover one, add it under the right section with a date and
a `packages/…` file anchor. Keep entries engine/data-centric — no host-app paths.

Anchors are current as of `dnd5e-engine` / `dnd5e-srd-data` **v0.7.0**
(re-verified 2026-10-08: every anchor names a file that exists, and any
symbol it names is in that file; never a line number).

The user-facing summary of the same information is
[`docs/capabilities.md`](docs/capabilities.md) — the per-mechanic matrix of what
resolves today. When you close a gap here, update that page too; its published
counts are pinned by `packages/dnd5e-engine/tests/test_capability_matrix.py`.

---

# dnd5e-engine

## Unimplemented activity kinds (2026-08-22)

- **Most `summon`, `transform` and `enchant` activities are narrative no-ops
  (amended 2026-09-25, C21a; 2026-09-26, C21b).**
  `activities/resolver.py::resolve_activity` routes them to a logged no-op, as
  it does a `utility` activity carrying no effect riders, unless the
  orchestrator hands the resolution a conjuration carrier for an allowlisted
  source: Spiritual Weapon, Magic Weapon, Wild Shape and Polymorph resolve
  (C21a), and Summon Dragon seats its Draconic Spirit (C21b; the other
  summons are under "Roster summons"). The measured consequence: **105 of 339
  SRD spells (31%) load correctly and emit no events**, 30 of them
  concentration spells — *Blur, Darkness, Fog Cloud,
  Wall of Force, Silent Image, Globe of Invulnerability, Expeditious
  Retreat* — which at least concentrate now. Several are combat staples a host
  will reach for immediately.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/resolver.py`)
- **Enchantments other than Magic Weapon, and shape-shifts other than Wild
  Shape and Polymorph, stay narrative (2026-09-25, C21a).** `enchant_weapon`
  reads two item-change keys (`system.magicalBonus`, `system.properties`);
  Sacred Weapon, Shillelagh, True Strike, Contingency, Pact of the Blade and
  40 item enchantments need a general item-change interpreter (a damage die,
  an attack ability, a damage type) and a carrier naming their item. True
  Polymorph, Animal Shapes and Shapechange ship no `transform` activity.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/conjuration.py::CONJURATION_ALLOWLIST`)
- **An item's own effect riders resolve nothing on `use_item` (2026-10-06,
  C27).** The context takes the cast spell's or the feature's passive effects,
  never the item's, so an item activity's rider logs `effect_ref_unresolved`
  and applies nothing: Dagger of Venom's poison ("have the Poisoned
  condition") deals its damage on a failed save but never Poisons.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_intent_activities`)
- **Monster summon riders stay narrative (2026-09-25, C21a).** A monster
  attack or an item never gets a conjuration carrier, so the 16 monster
  `summon` riders resolve nothing. Monster casts of a construct or summon
  spell are deferred too (see "No monster casts a construct or summon spell"
  under Conjurations and shape-shifting).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::rank_monster_actions`)

## Monster action economy (2026-08-22)

- **Monster-side ranged-in-melee/Vex/Sap threading is wired but inert
  (2026-09-02, C15).** `orchestrator.py`'s monster attack site
  passes `attacker_ranged_in_melee`, `attacker_vex_advantage`, and
  `attacker_sapped` into the activity context and pops vex grants/sap marks
  after resolution, mirroring the PC site exactly — but a monster attack
  carries its damage on the `AttackActivity` itself, not a separate typed
  `Weapon` (`resolve_activity(activity, actx, weapon=None)`), so
  `attack.py`'s weapon-gated "effectively ranged" check and mastery-proc
  fold never fire for a monster attacker. A monster can still be the
  RECEIVING end of a vex grant or sap mark from a prior PC weapon hit
  (that half is live). Needs a monster weapon-mastery/property model;
  confirmed still open after C18 (2026-09-03), which left it out of scope.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Two Multiattack conditional clauses are not modelled (amended
  2026-10-04, C26b).** An action a Multiattack uses "if available" sits out
  while it isn't, and a Recharge action it uses is spent when it fires (C26b),
  but two other conditions are not read: the Aboleth's "uses either Consume
  Memories or Dominate Mind if available" (its fallback repeats Tentacle, or
  Consume Memories at 30 ft, never the 2/Day Dominate Mind) and the Clay
  Golem's "three Slam attacks if it used Hasten this turn" (always two).
  Limited-use gating is only partial: see "Typed
  `MonsterAction.uses_per_day` is never consulted" below.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::expand_action_to_parts`)
- **The Vampire's Multiattack never Bites (2026-10-06, C27).** SRD 5.2: "The
  vampire makes two Grave Strike attacks and uses Bite." The precise join
  doesn't strip the form qualifier from "Bite (Bat or Vampire Form Only)" —
  only the fallback does — so it falls back to two Grave Strikes. Joining the
  Bite needs its own target clause read first: "one creature within 5 feet
  that is willing or that has the Grappled, Incapacitated, or Restrained
  condition", an `affects.special` nothing reads, and Grave Strike's grapple
  never lands (see "A monster action's effect riders" under the dataset).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::expand_action_to_parts`)
- **A Multiattack alternative with its own count repeats the leading count
  (2026-10-06, C26b).** SRD 5.2 Planetar: "makes three Radiant Sword attacks
  or uses Holy Burst twice." Out of sword reach the fallback repeats Holy
  Burst three times, and the three resolve as one placement (one
  `AreaTargeted`, three saves for each enemy in it) rather than two bursts,
  each aimed.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::expand_action_to_parts`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_monster_parts`)
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
- **A Recharge cast action never ranks first (2026-10-06, C26b).** Tier 1
  requires `_action_has_offense` — an `AttackActivity` or `SaveActivity` on
  the action itself — so a Recharge action whose only activities are
  `CastActivity` (the Stone Golem's Slow: "Recharge 5–6") never qualifies,
  unlike a non-cast Recharge action (a dragon's breath). It falls to tier 4
  instead, behind Multiattack and, in stat-block list order, behind its own
  attacks.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::rank_monster_actions`)
- **The monster AI chooses an area only from where its turn starts
  (2026-10-04, C26b).** It never moves into reach and then breathes: a young
  red dragon 45 feet from its foes walks (or Dashes) closer rather than
  closing to 30 feet and using its 30-foot Fire Breath the same turn, though
  SRD 5.2 lets a creature move before and after its action. The same holds
  for a spell's or a legendary action's area. Only an area a Multiattack
  uses is placed after the Multiattack's walk, and only if it was already an
  option where the turn started.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_monster_aim`)
- **Every behaviour profile aims an area the same way (2026-10-04, C26b).**
  The AI always takes the placement that affects the most enemies minus
  allies and never catches itself, trading allies for enemies one for one:
  one enemy is enough, so it still fires when every placement catches more
  allies than enemies. No profile weighs friendly fire differently, holds an
  area back for a better turn, or prefers the target it would attack.
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::best_aim`)
- **A monster's "one creature" area action lands at any range (2026-10-04,
  C26b).** An action whose template counts one creature keeps the AI's single
  target, as before, with no range check: the Aboleth's Dominate Mind ("one
  creature the aboleth can see within 30 feet"), the Chuul's Paralyzing
  Tentacles, the Chain Devil's Conjure Infernal Chain and Unnerving Gaze, the
  Bugbear Stalker's Quick Grapple and the Stone Giant's Deflect Missile. (Two
  of these, Deflect Missile and Unnerving Gaze, are reactions: see the row
  below.)
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_monster_area`)
- **A monster's offensive reaction is ranked as an action (2026-10-06,
  C26b).** `rank_monster_actions` ranks every offensive entry in
  `Monster.actions`, reactions included: the Stone Giant's Deflect Missile
  (Recharge 5–6; "Trigger: The giant is hit by a ranged attack roll …") is
  its first choice on its own turn and applies its damage-reduction heal to
  its target before the save, and the Chain Devil's Unnerving Gaze ranks
  after its Multiattack.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::rank_monster_actions`)
- **The Lich's Deathly Teleport bursts on an enemy, not on the space it leaves
  (2026-10-04, C26b).** SRD 5.2: "The lich teleports up to 60 feet to an
  unoccupied space it can see, and each creature within 10 feet of the space it
  left takes 11 (2d10) Necrotic damage." Its activity carries a 10-foot circle
  with the teleport's 60-foot range, so the AI centres the burst on a foe up to
  60 feet away; the teleport itself is not modelled (nor the Solar's Radiant
  Teleport).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_take_legendary_action`)
- **A Multiattack that uses a Recharge action is passed over while that action
  is charged (2026-10-04, C26b).** SRD 5.2 Doppelganger: "makes two Slam
  attacks and uses Unsettling Visage if available." A charged Recharge action
  ranks first, so the Doppelganger uses Unsettling Visage on its own rather
  than with its two Slams; its Multiattack runs only while the visage is
  spent or reaches no one.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::rank_monster_actions`)
- **Utility-only and cost > 1 legendary actions are never selected by the
  built-in AI** (2026-09-03, C18). `_take_legendary_action` only considers
  entries whose `legendary_cost` is unset or `1` and that carry an
  attack/save/damage activity (or a castable spell) — a `utility`-only entry
  (e.g. Pounce) and a multi-point legendary action are skipped even when
  legal. The bundled corpus carries no multi-point legendary action today.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_take_legendary_action`)
- **A legendary action's "can't take this action again until the start of
  its next turn" is not enforced (2026-10-06, C26b).** 38 bundled legendary
  actions carry the clause, the Lich's Disrupt Life, the green dragons'
  Noxious Miasma, the silver dragons' Cold Gale, the white dragons' Freezing
  Burst and the Kraken's Toxic Ink among the areas, but
  `_take_legendary_action` takes the first available entry in every window:
  a Lich beside the party uses Disrupt Life (a 20-foot Emanation) three
  times a round.
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
  `intent.intent_type == "attack"` (and Spiritual Weapon's cast, whose force
  attacks at once: C21a), and the monster's shared
  `_resolve_monster_attack_activities` fires it only from the mundane
  attack/legendary-action attack path. A spell attack roll
  (`intent_type == "cast_spell"` on the PC side, `_resolve_monster_cast` on
  the monster side) never pops a target's readied Shield, even though a
  spell attack roll is exactly the kind of "attack roll" Shield's SRD 5.2
  text protects against.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
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
- **A template monster attacks at its spec's `attack_bonus`, +0 by default
  (2026-09-25, C21a).** Its to-hit, every `@mod` it rolls, its passive skill
  scores (`@skills.<code>.passive`: a template Crocodile's grapple escape DC is
  `10 + attack_bonus`, where SRD 5.2 says 12) and its fallback save DC
  (`8 + attack_bonus`) come from `EncounterMemberSpec.attack_bonus`, not its
  stat block, and a natural weapon's base damage (folded into
  `parts[0]` without Foundry's implicit `@mod`) adds no ability modifier: by
  default a Tough's Mace rolls d20 + 0 for 1d6 where SRD 5.2 says +4 and
  1d6 + 2. Only a transformed creature gets its stat block's real numbers
  (`StatBlockMagnitudes`); giving them to every template monster re-pins
  every template-monster fixture. The bridge's `/v1/combat` passes no
  `attack_bonus`, so every foe it builds rolls at +0.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py::_attack_bonus_override`,
  `packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_build_encounter_specs`)

## Core combat rules not modelled (2026-08-22)

- **An opportunity attack never Cleaves, takes a versatile weapon in two hands,
  or redeems a Bardic Inspiration die (2026-10-03, C24).** SRD 5.2 Cleave
  follows any melee hit with the weapon and Bardic Inspiration any failed D20
  Test, but each is a choice the engine can only take from an intent, and an
  opportunity attack has none (the engine never pauses mid-resolution); a
  Versatile weapon rolls its one-handed die for the same reason — never the
  Versatile die, and never Great Weapon Fighting either, since that style's
  own gate for a Versatile (as opposed to strictly Two-Handed) weapon reads
  the same never-set `use_versatile_damage` flag.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_opportunity_attack`)
- **A character's `reach_ft` reaches only its opportunity attacks (2026-10-03,
  C24).** An Unarmed Strike opportunity attack threatens
  `PartyMemberSpec.reach_ft`, but the character's own on-turn Unarmed Strike
  is range-gated at the Unarmed Strike's 5 ft (SRD 5.2 Unarmed Strike: "a
  target within 5 feet of you"), so a host that sets `reach_ft=10` sees a
  10-ft opportunity attack its on-turn attack can't match.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_pc_attack_out_of_range`)
- **An `attack` that names no weapon resolves nothing but spends the Action
  (2026-09-27, C23).** A character's `attack` with neither `weapon_id` nor
  `stat_block_action_id` emits only `IntentSubmitted` and ends the turn: no
  attack roll, the Action gone. It should be refused before anything is spent.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::submit_player_intent`)
- **An `attack` or an unchosen `use_item` resolves every activity on its
  weapon or item, not the one it means to fire (2026-10-04, C26a).** A
  weapon's own non-attack activity (the Mace of Terror's Wave of Terror
  save) and an item's alternative modes (Javelin of Lightning, Rod of
  Lordly Might, the Staff of Power, the Staff of the Magi, the Staff of
  Thunder and Lightning, Thunderous Greatclub, Horn of Blasting) all resolve
  together against the intent's single target whenever nothing names which
  one to fire. C26a's area resolver guards the one visible symptom — none of
  these intents ever area-expands — but the ambiguous resolution itself
  stands: the proper fix resolves only the chosen activity, requiring
  `activity_id` when an item carries alternatives, as a feature already
  does.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_intent_activities`)
- **A seeded Incapacitated effect ends nothing (2026-09-27, C23).** SRD 5.2
  Incapacitated: "Your Concentration is broken." `_seed_active_effects` writes
  a seeded effect's statuses onto the combatant without
  `_end_what_incapacitation_ends`, so a Paralyzed effect passed to
  `start_combat(active_effects=...)` leaves a seeded Rage, concentration or
  grapple in place, where the same effect applied during the combat ends
  them (C20).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_seed_active_effects`)
- **Grapple's/Shove's size gate, free-hand gate, and distance-exceeded
  auto-release are not modelled** (2026-09-01). SRD 5.2 Grapple/Shove
  require "a hand free" (Grapple only) and cap the actor at one size larger
  than the target; "Ending a Grapple" also ends the condition when a forced
  move separates the pair beyond reach. None of the three block or
  auto-release `grapple`/`shove`/`escape_grapple` today: no combatant has a
  size attribute to read. The Push weapon mastery's "if it is Large or smaller" gate
  (2026-09-02, C15) shares the same missing creature-size attribute
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
  hand, a component pouch/focus, or a costed material's gold cost — a host's
  decision.
  (`packages/dnd5e-engine/src/dnd5e_engine/spellcasting.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/events.py::SpellCast`)
- **Rules that suppress or alter an opportunity attack are not modelled
  (2026-10-03, C24).** The trigger knows only Disengage, sight, Charmed and
  Incapacitated. Unmodelled: the Agile trait (Deer, Rat: "doesn't provoke an
  Opportunity Attack when it moves out of an enemy's reach"); "can't make
  Opportunity Attacks" riders (Shocking Grasp, Open Hand Technique's Addle,
  Improved Brutal Strike's Staggering Blow, Mace of Terror); moves "without
  provoking Opportunity Attacks" (Tactical Shift, Cunning Strike's Withdraw,
  Brutal Strike's Forceful Blow, Remarkable Athlete); Disadvantage on
  opportunity attacks against a creature (Hunter's Escape the Horde, Boots of
  Speed). Flyby and Nimble Escape are recorded under "Typed traits are
  hydrated".
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_opportunity_attackers`)
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
- **An earlier concentration ends only after the new concentration spell
  resolves (2026-09-25, C21a; amended 2026-09-26, C21b).** SRD 5.2: "You lose
  Concentration on an effect the moment you start casting a spell that
  requires Concentration". The engine drops the old chain after the new
  spell's resolution, so a self-cast Bless's d4 still applies to Spiritual
  Weapon's immediate attack roll, and a recast of Summon Dragon places its new
  spirit while the old one still stands: the old spirit's space counts as
  occupied, though the old spirit leaves before the new one joins.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_record_effect_lifecycle_links`)
- **A cast longer than a turn resolves as an Action (2026-09-25, C21a;
  amended 2026-09-26, C21b).** `_classify_action_cost` special-cases only
  Bonus Action and Reaction casts, so a 1-minute or 1-hour cast resolves
  within one turn. Of the creature summons, Find Familiar (1 hour or a
  ritual), Animate Dead and Create Undead (1 minute each) can't be cast in a
  combat turn at all, and `start_combat` has no input for a creature summoned
  before the combat that outlives it, so all three stay narrative.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_classify_action_cost`)
- **Concentration can start for a caster who fell Unconscious during its own
  cast (2026-09-26, C21a).** SRD 5.2 Incapacitated: "Your Concentration is
  broken." The fold records concentration after the resolution — C13's
  writeback and the anchor alike — without checking the caster, so a readied
  Wall of Ice that drops its own caster to 0 Hit Points (see "A readied spell
  always targets its own caster") leaves it concentrating until its death.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_apply_concentration_anchor`)
- **A monster's concentration has no duration cap (2026-09-26, C21a).** SRD
  5.2 Concentration: "If the effect has a maximum duration, the effect's
  description specifies how long the creator can concentrate on it: up to 1
  minute, 1 hour, or some other duration." The monster cast site folds its
  cast without `concentration_max_rounds`, so a monster's concentration, an
  anchored one included, outlives the spell's duration and ends only by
  damage, the Incapacitated condition, death or a new concentration spell.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_monster_cast`)
- **A concentration spell cast from an item concentrates only through an
  effect of its own (2026-09-26, C21a).** SRD 5.2 Staff of Frost: "you can
  cast one of the spells on the following table from it" — a cast, so its Fog
  Cloud or Wall of Ice concentrates. The anchor runs at the three cast sites
  (a turn, a monster's stat block, a Ready) but not at `use_item`, whose fold
  gets no spell: a Staff of Frost's Fog Cloud leaves no concentration, while a
  Necklace of Prayer Beads' Bless, which applies a concentration effect, does
  concentrate. Potions are the SRD's stated exception (see "A potion's spell
  concentrates").
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_fold_resolution_outcome`)
- **`CombatOutcome.expended_resources` counts a concentration spell where its
  effect lands (2026-09-26, C21a).** SRD 5.2: "When you cast a spell, you
  expend a slot of that spell's level or higher" — the caster's resource,
  whatever the save. The fold charges a concentration-flagged
  `EffectApplied` to its target when that target is a party member: a PC's
  Hold Person or Polymorph that the monster saves against is counted (the
  anchor sits on the caster), one it fails is not (the effect sits on the
  monster), and a Polymorph on a PC ally charges the ally.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_emit_apply_effect_applied`)
- **"Of your choice" targeting is unmodelled on a `utility` activity or a
  templateless save (2026-10-04, C26a).** Spirit Guardians, Holy Aura and
  Nature's Sanctuary carry their `affects.choice` flag on a `utility`
  activity, and Rod of Rulership's choice save carries no measured template;
  none of the four resolves an area, so `PlayerIntent.excluded_target_ids`
  sent with any of them is refused with `target_invalid`. Spirit Guardians'
  "designate creatures to be unaffected" stays unexpressed until a persistent
  emanation is modelled (see "No ongoing-damage producer").
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::is_choice`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_target_failure`)

## Movement (2026-08-22)

- **No elevation.** The grid is strictly 2-D, so flying creatures have no
  altitude and `movement_modes` beyond walk speed do not affect positioning.
- **No multi-tile creature footprints (amended 2026-09-26, C21b; amended
  2026-10-04, C26b).** Every creature occupies one cell regardless of size, a
  Large summoned Draconic Spirit included: its placement needs one free cell.
  An area in a monster's own space can catch no one else: the Water
  Elemental's Whelm ("each creature in the elemental's space") is never used.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_summon_placement`,
  `::_monster_aim`)
- **`start_combat` seats two combatants on one cell (2026-10-03, C25).** It
  checks that each start cell is in bounds and unblocked, not that it is free,
  so two creatures can start on one cell, which no move can produce (SRD 5.2:
  "You can't willingly end a move in a space occupied by another creature").
  The demo's burning-hands scenario stacks four giant rats this way, and 18
  engine tests start two creatures on one cell (under
  `packages/dnd5e-engine/tests/`: `e2e/test_c20_class_features.py`,
  `test_dodge_help_hide.py`, `test_c20_fighting_styles.py`,
  `test_loading_property.py`, `e2e/test_c21_summons.py`,
  `test_c21_polymorph.py`, `test_c21_wild_shape.py`); refusing a shared
  start cell means re-seating them first.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_topology`)

## Event stream observability (2026-08-22)

- **`ZoneTransit` is never emitted (2026-10-03, C25).** It stays in the closed
  `CombatEvent` union only because a host imports it. Drop it in a later
  breaking minor, once no host does.
  (`packages/dnd5e-engine/src/dnd5e_engine/events.py::ZoneTransit`)
- **`DeathRecord.killer_id` names the current actor, not the attacker
  (2026-09-27, C23).** Every death is recorded with `live.current_actor_id`,
  so a kill landed off the killer's own turn names whoever's turn it is: an
  opportunity attack that kills a moving creature credits the mover itself,
  and a readied spell or a reaction credits the creature whose turn it is.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_record_death`)
- **A second late `narration_events` consumer on an ended combat awaits
  forever (2026-09-27, C23).** `end_combat` enqueues a `None` sentinel;
  `narration_events` takes it off the queue and returns without putting it
  back, unlike `drain_pending_events`, which re-queues it so another
  consumer still sees it. A first late consumer started after `end_combat`
  gets the sentinel and returns cleanly; a second one finds the queue empty
  and blocks on `event_queue.get()` with nothing left to ever wake it.
  Pre-existing, but this release's migration guide now advertises a late
  consumer draining `combat_ended` after close.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::narration_events`)
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

- **A multiclass caster's spellcasting ability comes from its primary class
  (amended 2026-09-24, C20).** `CharacterBuildSpec.classes` carries the build
  (C17 slot tables; C19 per-class features, HP, hit dice, proficiencies and
  non-stacking Extra Attack), and `PartyMemberSpec.classes` carries it into
  combat (C20: features, scale values and `@classes.<class>.levels` per
  class). `_resolve_caster_spellcasting_ability` still reads only
  `class_slug`, so every spell a multiclass caster casts uses that class's
  ability: a Cleric/Wizard whose `class_slug` is the Cleric casts its Wizard
  spells with Wisdom, and a non-caster `class_slug` falls back to the flat
  approximation. A host can name a spell's ability in
  `PartyMemberSpec.spell_abilities` meanwhile (amended 2026-10-06, C28: Magic
  Initiate's carrier).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_caster_spellcasting_ability`)
- **Most feat benefits are recorded, not applied (amended 2026-10-06,
  C28).** The engine applies the four SRD 5.2 Fighting Style feats (C20), and
  Alert's Initiative bonus, Savage Attacker, Grappler's Attack Advantage and
  Magic Initiate's spells (C28), each by slug. Grappler's Advantage carries
  two limits of its own: its construct attack (Spiritual Weapon) gets none,
  since the construct path builds no "grappled by you" map, and only the
  first grappler of a creature counts — a creature an ally grapples first,
  then the Grappler grapples, counts as the ally's. Still not applied: Alert's
  Initiative Swap ("Immediately after you roll Initiative, you can swap your
  Initiative with the Initiative of one willing ally" — the choice follows the
  rolls, so it needs a host decision point); Grappler's Punch and Grab (a
  Grapple riding an Unarmed Strike hit; the engine's Grapple takes the Action
  and ends the turn), Fast Wrestler (see Grappled's "Movable") and its +1
  Strength or Dexterity (see the feat ability increases under `derive_sheet`
  below); Skilled's three proficiencies (the `skill:` tokens are uncapped);
  and every Epic Boon's benefits — Boon of the Night Spirit's activity can't be
  used, since the feature gate covers class, subclass and species features
  only. A Polymorphed character keeps its feats in combat, though SRD 5.2
  Polymorph replaces "The target's game statistics" (Wild Shape keeps
  "feats"). The dataset `Feat` schema has no `passive_effects`, so the effects
  Foundry ships on feats (Archery's and Defense's among them) are dropped at
  translation. A feat's free-text `requirement` (Grappler's "Strength or
  Dexterity 13+") is never validated.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py::_asi_level_feats`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/feat.py`,
  `packages/dnd5e-srd-data/tools/translators/foundry.py`)
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
  cuts).** Recorded but not applied: languages, tool proficiencies, ability
  increases from feats other than the Ability Score Improvement feat, and
  level-20 capstone increases (the Monk's Body and
  Mind is a fixed `points: 0` ASI entry up to 25, the Barbarian's Primal
  Champion a feature). Not validated at all: multiclass ability
  prerequisites (the sheet has no score history, and enforcing them would
  reject the corpus's own default-STR/DEX builds in C19-S09), choice-pool
  capacity (how many skills/invocations/styles a build may pick — Skilled's
  grants are not in the corpus) — and since C20 applies Fighting Style feats
  in combat (2026-09-24), a build listing more styles than its pools allow (a
  Fighter 1 with two) gets every one, `attunement_constraint`, untrained-armor
  penalties (`armor_training` is reported so a host can apply them), and
  magic items' own passive effects (hosts pass them as `active_effects`).
  Nor which spell list a Magic Initiate spell is on — no corpus spell or class
  carries spell lists — or that an Acolyte's Magic Initiate uses the Cleric
  list and a Sage's the Wizard list, which only the background's prose names
  ("Feat: Magic Initiate (Cleric)") (amended 2026-10-06, C28).
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
  the per-spell branches still need to read it (no cluster owns it). Note the
  shipped canonical still stores the inheriting activity's own `type` (e.g.
  Shield's utility activity says `action` while carrying populated
  `reaction_conditions`) — consumers must not gate on
  `activation.type == "reaction"` until the inheritance regen lands; also, an
  empty `reaction_conditions` does not mean "not a reaction" (only the four
  SRD spell phrasings plus exact shape matches are typed).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Engine does not yet read `canonical/conditions/`.** The dataset category
  exists (C22, `AssetLoader.get_condition`), mirroring `rules/conditions.py`;
  the engine should prefer the data when present and
  fall back to the Python registry. Still open after C12 and C18 (neither
  reads the category); unowned.
  (`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`)
- **`orchestrator.py` is ~13.4k lines**, well over a third of the engine,
  holding the reaction queue, item/feature charge accounting, the monster
  turn, the effect lifecycle, the conjurations and the turn loop. Each is a
  coherent module; splitting them would make the combat loop readable
  without changing behaviour.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

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
- **The monster AI's closing walk ignores occupancy; line width is not modelled** (2026-08-27,
  amended 2026-10-03, C24). The closing walk in `advance_monster_turn` calls
  `shortest_path` without `avoid=`, so a monster may path straight through a PC
  where a PC `"move"` intent may not; the flee walk avoids enemy spaces and never
  ends on a creature (C24). `cells_in_template("line")` is one cell wide, so a
  5-ft-wide Lightning Bolt is treated as a 1-cell ray and a wider
  `template.width` is ignored.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::advance_monster_turn`,
  `packages/dnd5e-engine/src/dnd5e_engine/spatial.py::cells_in_template`)
- **A spaced cell id is stored as written (2026-09-27, C21b).**
  `GridTopology.is_valid_cell` parses with `int()`, which also reads `"1, 1"`
  or `" 1,1"`, so `start_combat` seats a combatant at such a `zone_id` and
  Spiritual Weapon places its force at such a `target_zone_id` verbatim: a
  string no other position check matches (another creature can enter that
  space, an area of effect misses it). A `move` to one fails `unreachable`,
  and Summon Dragon refuses one with `target_invalid`.
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.is_valid_cell`)
- **Truesight sees into Heavily Obscured cells (2026-09-27, C23).** SRD 5.2
  Truesight: "your vision pierces through" Darkness, Invisibility, visual
  illusions, transformations and the Ethereal Plane — not fog or foliage. The
  scene model treats Truesight like Blindsight at an `obscurement_cells`
  "heavy" cell (pinned by `test_can_see_heavy_obscurement_beats_darkvision_but_not_blindsight`),
  and a grid cell can't say whether its heavy obscurement is magical
  Darkness or fog, so the fix needs that distinction first. (C23 stopped
  Truesight from working through the Blinded condition.) Since C27 a
  templated monster has its stat block's senses, so the 17 SRD creatures with
  Truesight see into fog this way (amended 2026-10-06, C27).
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.can_see`)
- **Vision is scene-lit only** (2026-08-27, amended 2026-09-02, 2026-09-03).
  No light sources (torches, *Light*, *Darkness*), no viewer-side
  obscurement, no Blinded emission from darkness; `can_see` reads
  `GridScene.lighting` / `obscurement_cells` plus the viewer's projected
  senses. Sunlight Sensitivity's attack-roll half closed C18 (the new
  whole-scene `GridScene.sunlight` flag); its ability-check half (the
  trait disadvantages ALL ability checks in sunlight) is still open (see
  "Typed traits are hydrated..." under "Audit 2026-08-26 — monsters" below).
  No *See Invisibility*-style effect flag
  pierces the Invisible condition either (C16b) — only
  blindsight/
  truesight in range with line of sight do, via
  `orchestrator.py::_pierces_invisibility`; an effect-vocabulary carve-out is
  a future cluster's seam.
  (`packages/dnd5e-engine/src/dnd5e_engine/spatial.py::GridTopology.can_see`)
- **An area the engine can't map onto the grid affects only its named target
  (2026-10-03, C25; amended 2026-10-04, C26a).** A `wall` template (Blade
  Barrier, Tsunami, Wall of Fire, Wall of Thorns, Wind Wall) or a size written
  as a formula (Confusion's `@item.level`) has no grid geometry, so the engine
  logs `aoe_template_unsupported` and resolves it against the named target
  alone (nobody, if the intent names none), with no `AreaTargeted`. A
  monster's (the Efreeti's Wall of Fire, the Glabrezu's Confusion) resolves
  against the creature the AI targets (amended 2026-10-04, C26b).
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::area_template`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_targets`,
  `::_monster_area`)
- **A counted area's named creatures aren't checked against its template
  (2026-10-04, C26a).** For "up to N creatures" (Slow's six, Mass Cure Wounds'
  six, Phantasmal Force's one) the engine takes the creatures
  `PlayerIntent.target_ids` names — or a lone `target_id` when N is 1 —
  wherever they stand: it anchors a Cube, Cone or Line at the caster and can't
  place Slow's 40-foot Cube "within range", and Phantasmal Force's Cube is the
  illusion's size, not its target area. Only too many names, a repeated name
  and a name not in the combat are refused.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_plan`)
- **An area's point of origin is a creature's cell, never an empty one
  (2026-10-04, C26a).** A Sphere or Cylinder centres on the named target's cell
  (else the caster's), and a Cone, Cube, Line or Emanation starts at the
  caster's; SRD 5.2's "a point you choose within range" on an empty cell
  (`target_zone_id`) is not accepted for an area. The monster AI centres a
  Sphere or Cylinder on a foe it can see, so it never places one on an empty
  cell between two groups (amended 2026-10-04, C26b). A monster's own ranged
  Cube spell inherits the caster-anchor too: see the row below.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_origin`,
  `packages/dnd5e-engine/src/dnd5e_engine/areas.py::best_aim`)
- **A monster's ranged Cube spells land only next to it (2026-10-06,
  C26b).** Web, Entangle, Faerie Fire, Hypnotic Pattern and Slow anchor at
  the caster's cell under the point-of-origin model above (see
  `docs/concepts/grid.md`): whatever the spell's own range, the built-in AI
  can only place the Cube at its own feet, in one of the eight directions,
  never offset toward a foe it can see at range.
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::best_aim`)
- **A delegated cast resolves against its named target only (2026-10-04,
  C26a).** An item whose activity casts a spell (the Wand of Fireballs, a Spell
  Scroll) resolves the spell's activities against the item intent's target
  list, which a `cast` activity never expands: a Wand of Fireballs hits one
  creature.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/cast.py`)
- **Monster-cast AoE applies no forced-movement rider** (2026-08-27). Only the
  player-intent cast path calls `activities/forced_movement.py`, so a monster
  casting Thunderwave deals damage but pushes nobody.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::advance_monster_turn`)
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
  set onto the `abilities.*` family (one normalization table, both consumers).
  Not aliased, deliberately, so F1d stayed behaviour-preserving; neither C12
  nor C19 took it up.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py::_KIND_TO_BUCKETS`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_fold_d20_test_bonus`).
## Class / species feature mechanics

- **Unconsumed `system.bonuses.heal.*` buckets (2026-08-26).**
  `activities/heal.py::resolve_heal` never reads any bonus sidecar off
  `ActivityResolutionContext` (unlike `attack.py`'s `passive_*_damage_bonus`
  fields), so a `system.bonuses.heal.*` change on an active effect is inert.
  (The attack/damage, `spell.dc` and — as of F1d — `abilities.check` /
  `abilities.skill` / `abilities.<ab>.save` families are folded.)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/heal.py`)
- **Rage's Heavy-armor rules, its no-spells rule and its 10-minute cap are not
  modelled (2026-09-24, C20 scope cut).** SRD 5.2: "You can enter it as a
  Bonus Action if you aren't wearing Heavy armor"; it "ends early if you don
  Heavy armor"; "No Concentration or Spells. You can't maintain
  Concentration, and you can't cast spells."; "You can maintain a Rage for up
  to 10 minutes." Entry isn't gated on `Combatant.worn_armor`, armor is never
  donned in combat, and a raging barbarian may still cast and concentrate. The
  corpus effect's `rounds: 10` (one minute) stays the outer cap, because
  `rounds` wins over its `seconds: 600`.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_hook_rage_extension`)
- **Persistent Rage's Rage recovery on rolling Initiative is not applied
  (2026-09-25).** SRD 5.2 Persistent Rage (Barbarian 15): "When you roll
  Initiative, you can regain all expended uses of Rage. After you regain uses
  of Rage in this way, you can't do so again until you finish a Long Rest."
  The corpus carries it as an activity triggered "When you roll initiative"
  (`dnd5eactivity000`), which `start_combat` never runs, so Rage uses a host
  seeds as spent (`PartyMemberSpec.custom_counters`) stay spent. The rest of
  the feature applies (no extension needed; only Unconscious ends it early),
  under the same one-minute outer cap as above where SRD 5.2 says it "now
  lasts for 10 minutes".
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::start_combat`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/persistent-rage.json`)
- **Monk's Focus features other than Flurry of Blows don't reach the action
  economy (2026-09-24, C20 scope cut).** SRD 5.2 Patient Defense: "You can take
  the Disengage action as a Bonus Action. Alternatively, you can expend 1
  Focus Point to take both the Disengage and the Dodge actions as a Bonus
  Action." Step of the Wind: "You can take the Dash action as a Bonus Action.
  Alternatively, you can expend 1 Focus Point to take both the Disengage and
  Dash actions as a Bonus Action, and your jump distance is doubled for the
  turn." Both spend the right Focus Points (C20), but their corpus effects are
  markers (a "Disengaged" effect, a `dodging` status) that never set
  `Combatant.disengaging_this_turn` or `dodging`; Step of the Wind adds no
  movement, and the corpus ships only its Focus Point version. Stunning
  Strike's Focus Point isn't spent either: its cost names the Monk's Focus
  pool — another feature's — which `_feature_activity_cost` never charges.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_feature_activity_cost`)
- **A one-attack actor's turn still ends with its Attack action (2026-09-24,
  C20 scope cut).** C14 ends the turn of an actor with one attack per Attack
  action at its first swing (the back-compat pin
  `test_one_attack_actor_ends_turn_on_first_swing_back_compat`), so a Monk 1–4
  has to make its Bonus Unarmed Strike (or, from Monk 2, use Flurry of Blows),
  and a Fighter 2–4 Action Surge, before the Attack action. Strikes a Flurry still owes keep the
  turn open after that Attack action until they are made or the monk passes
  (C20). SRD 5.2 imposes no such order.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_attack_action_is_spent`)
- **Flurry of Blows strikes still owed are lost when a turn-ending Action
  comes next (2026-09-25).** SRD 5.2 Flurry of Blows: "You can expend 1 Focus
  Point to make two Unarmed Strikes as a Bonus Action." The Focus Point and
  the Bonus Action are paid when the Flurry is committed, and the strikes are
  the monk's next Unarmed Strike attacks. They keep the turn open after the
  Attack action, but a Dodge, Help, Grapple or Shove still ends the turn at
  once, so the paid strikes lapse unmade.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_end_action`)
- **A Monk's Grapple or Shove can't be its Bonus Unarmed Strike or a Flurry
  strike, and `use_bonus_action` on either is ignored (2026-09-25).** SRD 5.2
  Martial Arts: "Bonus Unarmed Strike. You can make an Unarmed Strike as a
  Bonus Action." An Unarmed Strike is "a melee attack that involves you using
  your body to damage, grapple, or shove a target within 5 feet of you", and
  Flurry of Blows makes "two Unarmed Strikes". The `grapple` and `shove`
  intents always take the Action, even with `use_bonus_action=True` or Flurry
  strikes owed; the flag is silently ignored rather than refused.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_grapple`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_shove`)
- **Action Surge: a refused cast still ends the turn, and the extra action
  funds no feature or item (2026-09-24, C20 scope cut).** A cast refused for
  want of a slot, countered, attempted as a Ritual or over-counted ends the
  turn as before, even with an extra action left. SRD 5.2 bars only the Magic
  action ("On your turn, you can take one additional action, except the Magic
  action."), but the corpus doesn't mark which features and items need one,
  so every `use_feature` and `use_item` counts as a Magic action.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_MAGIC_ACTION_INTENTS`)
- **Action Surge refuses an Attack action followed by a Magic action
  (2026-09-25).** SRD 5.2 Action Surge: "On your turn, you can take one
  additional action, except the Magic action." A surged turn may hold one
  Magic action and one other action in either order, but the engine pays
  each Action-costed intent with the base Action first and the extra action
  second, and the extra action can't fund a Magic action. So an attack, then
  a `cast_spell`, is refused (`CastFailed(reason="no_action_economy")`,
  nothing spent, turn kept), while the cast, then the attack, works, although
  the attack could have used the extra action.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_action_payment`)
- **A Loading weapon gets no second shot on Action Surge's extra action
  (2026-09-25).** SRD 5.2 Loading: "You can fire only one piece of ammunition
  from a Loading weapon when you use an action, a Bonus Action, or a Reaction
  to fire it, regardless of the number of attacks you can normally make." The
  engine caps a Loading weapon at one shot per turn, a cap that assumed one
  action per turn: after a surge, a Heavy Crossbow shot on the extra action is
  refused with `AttackFailed(reason="weapon_already_fired")`, although that
  action starts a new Attack action.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_loading_weapon_already_fired_failure`)
- **Brutal Strike isn't tied to a Reckless Attack hit (2026-09-25; predates
  C20).** SRD 5.2 Brutal Strike (Barbarian 9): "If you use Reckless Attack,
  you can forgo any Advantage on one Strength-based attack roll of your choice
  on your turn. The chosen attack roll mustn't have Disadvantage. If the
  chosen attack roll hits, the target takes an extra 1d10 damage of the same
  type dealt by the weapon or Unarmed Strike, and you can cause one Brutal
  Strike effect of your choice." The corpus carries it as a
  `special`-activation damage activity, and Reckless Attack has no activity,
  so nothing binds it to an attack roll: `use_feature brutal-strike` costs the
  Action like any feature use and deals its damage with no attack roll, no
  Reckless Attack and no hit.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_feature_invocation`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/brutal-strike.json`)
- **Bardic Inspiration applies to weapon attack rolls only (2026-09-24, C20
  scope cut).** SRD 5.2: "Once within the next hour when the creature fails a
  D20 Test, the creature can roll the Bardic Inspiration die and add the number
  rolled to the d20". `redeem_granted_die` rides only an `attack` intent:
  `cast_spell` ignores it, so a spell attack roll never uses the die. Saves and
  ability checks have no intent field to carry the holder's choice, so the die
  never helps them either. The grant isn't gated on "within 60 feet of yourself
  who can see or hear you", and a die whose bard isn't in the combat can't be
  redeemed (its size is read from that bard's `@scale.bard.inspiration`).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_redeemed_die`)
- **Font of Inspiration and Superior Inspiration are not modelled
  (2026-09-25).** SRD 5.2 Font of Inspiration (Bard 5): "You now regain all
  your expended uses of Bardic Inspiration when you finish a Short or Long
  Rest. In addition, you can expend a spell slot (no action required) to
  regain one expended use of Bardic Inspiration." Superior Inspiration (Bard
  18): "When you roll Initiative, you regain expended uses of Bardic
  Inspiration until you have two if you have fewer than that." Now that
  Bardic Inspiration is capped (C20), this bites: the corpus feature recovers
  on a Long Rest only, so `recover_feature_uses` after a Short Rest leaves a
  Bard 5's spent uses spent, and nothing restores a use from a spell slot or
  at Initiative.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/bardic-inspiration.json`,
  `packages/dnd5e-engine/src/dnd5e_engine/rest.py::recover_feature_uses`)
- **Lay on Hands' Remove Poison spends 5 points but leaves Poisoned in place
  (2026-09-24, C20 scope cut).** SRD 5.2: "You can also expend 5 Hit Points
  from the pool of healing power to remove the Poisoned condition from the
  creature". The corpus activity (`K6UeXQwTyDHWvis8`) carries no effect —
  Foundry leaves the removal to the table — so the engine charges the pool and
  removes nothing.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/lay-on-hands.json`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/resolver.py`)
- **`use_feature cunning-action` does nothing mechanical (2026-09-24, C20
  scope cut).** Dash's and Disengage's corpus activities carry no effect
  rider, so invoking either by `activity_id` spends the Bonus Action and
  resolves nothing; Hide's carries one, but it points at an inert "Hiding"
  marker (no `changes`, no `duration`, and `hiding` isn't a recognized SRD
  condition), so it only emits a cosmetic `EffectApplied`. None of the three
  runs the real mechanic — the feature works through the `dash` and
  `disengage` intents with `use_bonus_action=True`; Hide charges no budget at
  all (see "Hide costs no Action").
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_feature_invocation`)
- **Picked features never reach the live feature gate (2026-09-24, C20 scope
  cut).** `_granted_feature_slugs` walks each class's, the subclass's and the
  species' fixed grants at their own levels, but a feature-choice pick — an
  Eldritch Invocation, Blessed Warrior, a Metamagic option — lives only on
  `DerivedSheet.features`, which `PartyMemberSpec` doesn't carry, so
  `use_feature` rejects it as out of repertoire. Fighting Style picks ride
  `PartyMemberSpec.feats` and do apply.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_granted_feature_slugs`)
- **29 feature activities raise `ValueError` out of `submit_player_intent`
  after their cost is spent (2026-09-25; predates C20).** Each uses a formula
  shape the activity layer can't evaluate yet, and the raise comes after the
  invocation's Action, Bonus Action or Reaction, and any use, is spent, so the
  host gets an exception and a half-paid turn. By cause:
  - a save DC by ability (`save.dc.calculation` `wis`, `dex` or empty), which
    `activities/save.py::_resolve_dc` refuses — SRD 5.2 Monk's Focus: "Some
    features that use Focus Points require your target to make a saving
    throw. The save DC equals 8 plus your Wisdom modifier and Proficiency
    Bonus.": Stunning Strike, Open Hand Technique (2 activities), Deflect
    Attacks, Deflect Energy and Quivering Palm; Cunning Strike: "If a Cunning
    Strike effect requires a saving throw, the DC equals 8 plus your
    Dexterity modifier and Proficiency Bonus." (2), and Devious Strikes (3),
    whose effects "are now among your Cunning Strike options"; Relentless
    Rage: "you can make a DC 10 Constitution saving throw … Each time you use
    this feature after the first, the DC increases by 5."; and Intimidating
    Presence: "a Wisdom saving throw (DC 8 plus your Strength modifier and
    Proficiency Bonus)";
  - a `spellcasting` save DC, which `use_feature` can't meet because it never
    threads the class's spellcasting ability into the context
    (`orchestrator.py::_resolve_intent_activities`) — SRD 5.2 Channel
    Divinity: "If a Channel Divinity effect requires a saving throw, the DC
    equals the spell save DC from this class's Spellcasting feature.":
    Channel Divinity (Cleric, 2), Sear Undead, Land's Aid, Abjure Foes and
    Hurl Through Hell;
  - an unhandled roll-data token in `activities/formula.py`: `@scaling` in
    Disciple of Life, Blessed Healer and Cunning Strike, `@item.uses.spent` in
    Overchannel;
  - a dice expression `activities/dice.py` can't parse: `*` in Relentless
    Rage's heal, Preserve Life, Improved Blessed Strikes and Slow Fall,
    `max(…)` in Tireless and Dark One's Blessing.
  A check that refuses these before anything is spent would end the half-paid
  state until each shape is supported. Over HTTP the bridge answers such an
  intent 422, its half-paid turn included (amended 2026-10-07, C29).
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/save.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/formula.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/dice.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_intent_activities`)
- **An Emanation never includes its creature of origin, even when its text
  says otherwise (2026-10-04, C26a).** SRD 5.2 Dust of Sneezing and Choking:
  "forcing yourself and every creature in a 30-foot Emanation originating
  from you to make a DC 15 Constitution saving throw." `area_template`'s
  `radius` row always sets `includes_origin=False`, so its `use_item` now
  catches everyone else within 30 feet, but never the user. Preserve Life's
  "which can include you" (below) is the healing twin.
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::area_template`)
- **Preserve Life's "divide those Hit Points among them" is not modelled
  (2026-10-04, C26a).** Its heal is an area of your choice (a 30-foot
  Emanation), and an area heal gives every creature it affects the whole
  amount, so once its `5 * @classes.cleric.levels` formula parses (see the
  half-paid row above) each ally in range would regain the whole pool rather
  than a share. The cleric's own space is outside its Emanation (an
  Emanation never includes its creator — see above), so it can't heal
  itself ("which can include you"), and the "no more than half its Hit
  Point maximum" cap is not applied.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_targets`)
- **`affects.special` creature-type restrictions are not honoured
  (2026-10-04, C26a).** Sear Undead's save and the Helm of Brilliance's
  Diamond Light both carry `target.affects.special == "Undead"`; a Calm
  Emotions-style "Each Humanoid" is narrower still — its restriction lives
  only in description prose, with no typed field at all. `select_affected`
  reads `affects_type` (`"enemy"`/`"ally"`), `choice` and `count`, but never
  `special`, so now that these feature and item areas resolve (C26a), they
  catch every creature, or every enemy, in range rather than only the
  named creature type.
  (`packages/dnd5e-engine/src/dnd5e_engine/areas.py::select_affected`)

### Passive-stat projection (`activities/passive_stats.py`)

The interpreter now projects always-on `dr` (damage resistance), `di`
(immunity), `dv` (vulnerability), `ci` (condition immunity), `senses`, and
`movement` (walk-speed bonus + typed non-walk modes) at combat start, plus the
activation-gated Rage `dr` fold on the active-effect path. One entry
of the passive-projection spec allowlist remains recognized-but-deferred for lack of a landing
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

## Conjurations and shape-shifting (2026-09-25, C21a)

- **Only attack-roll actions of a stat block can be commanded, and a
  Multiattack's composition is not enforced (2026-09-25, C21a; amended
  2026-09-26, C21b).** `stat_block_action_id` refuses a save action (a Breath
  Weapon, Venomous Spew, a Roar) and the Multiattack itself; the host picks
  every swing of the Attack action, so "one Bite attack and one Claw attack"
  can be two Bites. A summoned Draconic Spirit's Breath Weapon is refused too,
  so its Multiattack ("…and it uses Breath Weapon") gives only the Rends;
  Summon Dragon's `match.saves` (the caster's spell save DC) lands with the
  first commandable save action. Commanding a save action (deferred,
  2026-10-04, C26a) needs: `_stat_block_attack_failure` to accept one; the
  whole Action as its cost, not one Multiattack swing; aim from `direction` or
  `target_id` through the area resolver; `action_unavailable` when it is spent
  or used up and `out_of_range` when its origin is beyond its range;
  `_mark_monster_action_used` when it commits; and, for a summon, the caster's
  save DC and the Draconic Spirit's damage-type choice.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_stat_block_attack_failure`)
- **A form's melee reach is 5 feet (2026-09-25, C21a; amended 2026-09-26,
  C21b; amended 2026-10-03, C24).** The corpus carries no melee reach for a
  monster, so a transformed creature swings at 5 feet whatever its form — its
  opportunity attack too, now that one resolves through the stat block
  (`_stat_block_opportunity_attack` falls back to the same
  `Combatant.melee_reach_ft` the on-turn path does). A summoned Draconic
  Spirit's `melee_reach_ft` is 5 too, though its Rend reaches 10 feet; a
  commanded Rend reads the action's own range, so only a reader of the field
  sees 5.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_physical_stat_fields`,
  `::_stat_block_opportunity_attack`)
- **A shape-shifted creature keeps its items and class features
  (2026-09-25, C21a).** Casting, readying a spell and weapon attacks are
  refused, but `use_item` is not — SRD 5.2 Wild Shape: "Your ability to
  handle objects is determined by the form's limbs rather than your own";
  Polymorph: "The creature can't use or otherwise benefit from any of that
  equipment" — and a polymorphed creature can still `use_feature`, though
  Polymorph replaces its game statistics (only its Wild Shape is refused).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_shape_shifted_failure`)
- **Beast Spells (Druid 18) is not modelled (2026-09-25, C21a).** SRD 5.2:
  "While using Wild Shape, you can cast spells in Beast form, except for any
  spell that has a Material component with a cost specified or that consumes
  its Material component." A Druid 18 in a form is refused every spell.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_shape_shifted_failure`)
- **A form can't be carried into a combat (2026-09-25, C21a).** An effect
  flagged `transform_form` passed to `start_combat(active_effects=...)` sits
  on the creature without swapping its statistics, so a Wild Shape or
  Polymorph begun before the combat is lost.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_seed_active_effects`)
- **Temporary Hit Points are one bucket (2026-09-25, C21a).** SRD 5.2: "If
  you have Temporary Hit Points and receive more of them, you decide whether
  to keep the ones you have or to gain the new ones." The engine keeps the
  larger and can't tell sources apart: Polymorph's end empties the bucket
  only when its grant raised it; otherwise the creature keeps the older
  Temporary Hit Points, and their running out ends the spell.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_revert_transform_on_expiry`)
- **No monster casts a construct or summon spell (2026-09-26, C21a; amended
  2026-09-26, C21b).** The monster AI skips a spell with no attack, save or
  damage activity of its own, so no monster casts Spiritual Weapon or Summon
  Dragon, whose only activity is a `summon`. Counting Spiritual Weapon as
  offensive waits until the Priest's data slip is fixed (see "The Priest's
  Spiritual Weapon is a data slip" under Conjuration and monster data): with
  the uuid followed, the bundled Priest opens with a Spiritual Weapon the SRD
  5.2 Priest doesn't have, where its SRD Multiattack belongs. The SRD 5.2
  caster, the Cultist Fanatic ("Spiritual Weapon (2/Day)"), then also needs a
  cell for the force (the AI picks none), its uses cap and the Bonus-Action
  move-and-repeat on later turns. A monster's Summon Dragon would also need a
  conjuration carrier (`_resolve_monster_cast` builds none, so the cast would
  stay narrative), and a foe the host drives can't cast it either: an
  `EncounterMemberSpec` carries no spell slots. A summon's allegiance already
  resolves through its caster, on either side.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_monster_cast_candidate`)
- **Spiritual Weapon's force moves through walls (2026-09-25, C21a).** Its
  Bonus-Action move is checked as a distance (the force floats), with no
  pathing, so it can cross a wall to a cell 20 feet away.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_construct_attack_failure`)
- **A monster-turn attacker's ally-enchanted weapon grants no Magic Weapon
  bonus (2026-09-25, C21a; amended 2026-10-03, C24).** Magic Weapon's
  `enchanted_weapon` flag and `weapon_enchantment_to_hit` reach only the
  on-turn `submit_player_intent` attack path; `_monster_context_kwargs` never
  threads either one, and a monster attack carries no `Weapon` object to
  enchant in the first place, so an ally's Magic Weapon on a monster
  combatant's weapon gives no bonus to hit or damage on that monster's own
  driven turn, its legendary action, or (since C24) its opportunity attack —
  all three share `_resolve_monster_attack_activities`.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_monster_context_kwargs`)
- **A Multiattack that "uses" an action counts it as a swing (2026-09-26,
  C21a).** SRD 5.2 Giant Constrictor Snake: "The snake makes one Bite attack
  and uses Constrict." `multiattack_count` sums every item the clause names,
  so the form's Attack action admits two swings and a creature polymorphed
  into the snake can Bite twice, where the SRD gives one Bite plus Constrict
  (a save action a host can't command yet). The other 17 corpus Beast
  Multiattacks count right.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/monster_actions.py::multiattack_count`)
- **A form's Multiattack count outlives the form within its Attack action
  (2026-09-26, C21a).** SRD 5.2 Wild Shape: "Your game statistics are replaced
  by the Beast's stat block" — only while in the form. The revert doesn't
  re-clamp `attacks_remaining`, so a Druid 4 who Rends once as a Black Bear,
  takes the Bonus-Action leave and then swings a Scimitar still gets the
  form's second swing. A monster's own turn has the same shape: a Giant
  Constrictor Snake form whose Bite breaks the Polymorph's concentration still
  resolves its Constrict, at the form's DC, after the revert.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_revert_transform_on_expiry`)
- **A second caster's Polymorph ends the first caster's concentration
  (2026-09-26, C21a).** SRD 5.2 Combining Spell Effects: "The most recent
  effect applies if the castings are equally potent and their durations
  overlap" — the first casting is overridden while both run, and its caster
  keeps concentrating. Polymorphing an already-polymorphed creature ends the
  first form with `remove_ieffect`, which drops the first caster's
  concentration.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_apply_transform`)
- **A form's skill modifiers lose its stat block's Expertise (2026-09-26,
  C21a).** SRD 5.2 Polymorph: "The target's game statistics are replaced by
  the stat block of the chosen Beast"; Wild Shape: "If a skill or saving throw
  modifier in the Beast's stat block is higher than yours, use the one in the
  stat block." A form adds only its skill proficiencies, so the 25 corpus
  Beast skills printed above the ability modifier plus the Proficiency Bonus
  come out low: a polymorphed Wolf's Perception is +3 against the printed +5,
  a Giant Spider's Stealth +5 (+6 wild-shaped at Druid 8) against +7.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_form_stat_fields`)

## Roster summons (2026-09-26, C21b)

- **Only Summon Dragon seats a creature (2026-09-26, C21b).** `SUMMONS` maps
  one spell to its stat block. Giant Insect's SRD stat block is variant-gated
  (its profiles point at excluded variant actors). Animate Objects needs
  objects as targets, count formulas and its Slam's
  `@flags.dnd5e.summon.mod`, and with it the `activities/formula.py` carrier
  for summon roll data (`@flags.dnd5e.summon.*` and `@item.level` still raise
  there). Finger of Death's Zombie ("A Humanoid killed by this spell rises at
  the start of your next turn as a Zombie") joins a turn later, with no
  concentration to end it. The remaining spell summons — illusions, sensors,
  lights, Mage Hand, Unseen Servant, Floating Disk, Secret Chest, Arcane Eye,
  Arcane Hand, Arcane Sword, Flaming Sphere, Guardian of Faith, Conjure
  Animals, Conjure Elemental, Conjure Fey, Faithful Hound — stay narrative.
  The spell-to-stat-block mapping is engine data; `Monster.foundry_uuid` with
  an `AssetLoader.get_monster_by_uuid` would move it into the dataset.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/conjuration.py::SUMMONS`)
- **An uncommanded summon doesn't move (2026-09-26, C21b).** SRD 5.2 Summon
  Dragon: "If you don't issue any, it takes the Dodge action and uses its
  movement to avoid danger." The engine plays the Dodge and leaves the
  creature where it stands.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_run_uncommanded_summon_turn`)
- **Summons take no reactions (2026-09-26, C21b).** A summon is in neither
  side set, and the opportunity-attack trigger takes reactors only from
  those, so it makes no opportunity attack, whoever leaves its reach.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_opportunity_attackers`)
- **The Draconic Spirit's chosen damage type is not modelled (2026-09-26,
  C21b).** SRD 5.2 Shared Resistances: "When you summon the spirit, choose one
  of its Resistances. You have Resistance to the chosen damage type until the
  spell ends." The caster gains no Resistance, and Breath Weapon's "2d6 damage
  of a type this spirit has Resistance to (your choice when you cast the
  spell)" has no choice to read. The spell's `match.saves` (Breath Weapon's
  "DC equals your spell save DC") is not carried either; it lands with the
  first commandable save action (see "Only attack-roll actions of a stat
  block can be commanded").
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_seat_summon`)
- **Summons end with the combat (2026-09-26, C21b).** Summon Dragon lasts up
  to an hour, but `EndCombatResult` and `CombatOutcome` report no surviving
  summon, and
  `start_combat` has no input for one: a concentration anchor seeded through
  `start_combat(active_effects=...)` concentrates with no creature.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_project_outcome`)
- **A departed creature can still be named (2026-09-26, C21b).** Another
  caster's concentration on a creature that left keeps running (SRD 5.2 is
  silent on a spell whose target vanishes), so its later `EffectExpired` or
  `ConditionRemoved` names the departed id. The rest of the resolution that
  drops a summon — a multiattack's later swing, an on-hit rider's save or
  condition, a weapon-mastery mark — still names it after its `CombatantLeft`
  and may leave a stale entry keyed by its id, read by nothing that walks the
  roster.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_purge_entity_state`)
- **A readied conjuration is refused (2026-09-27, C21b).** SRD 5.2 Ready:
  "When you Ready a spell, you cast it as normal (expending any resources used
  to cast it) but hold its energy, which you release with your Reaction when
  the trigger occurs." A `ready` naming Summon Dragon is refused with
  `CastFailed(reason="target_invalid")`, as C21a's Spiritual Weapon, Magic
  Weapon and Polymorph are: the reaction queue's `_PendingReaction` carries
  only the spell and its slot level, never the space, weapon or form the
  conjuration needs.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_readied_conjuration_failure`)
- **Summon Dragon's "space that you can see" ignores light (2026-09-27,
  C21b).** SRD 5.2: "It manifests in an unoccupied space that you can see
  within range." Placement reads range, line of sight, total cover and a
  Blinded caster (with its Blindsight), but not the light or
  obscurement at the space against the caster's senses: a caster without
  Darkvision can place the spirit in Darkness or a Heavily Obscured cell.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_summon_placement`)

## Rest & recovery

- **Non-literal feature-recovery formulas are unhandled** (2026-07-04).
  `rest.recover_feature_uses` honours each feature's typed `uses.recovery`
  rules: `recoverAll` fully recharges, a literal-integer
  `formula` regains that many uses, and a period-miss (with recovery data
  supplied) correctly preserves `spent` (lr-only features do not recharge on a
  Short Rest). The residual: a NON-literal recovery formula (e.g. an
  `@abilities.*` expression) is not evaluated — the counter is left unchanged
  rather than guessed. Zero corpus occurrences today (a structural scan of
  `canonical/features` shows all 5 `formula` recovery entries are the literal
  `"1"`); thread roll-data evaluation through if such data ever lands
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`).

## Audit 2026-08-26 — rolls & modifiers

- **Standalone out-of-combat `resolve_check` has no exhaustion seam**
  (2026-08-27) — the in-combat activity path folds `ctx.d20_test_penalty`, but
  the host-facing `CheckSpec` carries no conditions/exhaustion field, so a
  library consumer rolling a check outside combat cannot express the SRD 5.2
  `-2 x level` D20 Test penalty. Additive fix: an `exhaustion_level: int = 0`
  (or projected `modifier`) on `CheckSpec`.
  (`packages/dnd5e-engine/src/dnd5e_engine/check.py::CheckSpec`)
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
  legality check, even beside a Shield the combatant has equipped
  (`Combatant.shield_equipped`, which only Great Weapon Fighting and Martial
  Arts read). Equip-slot bookkeeping is a host concern.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`)

## Audit 2026-08-26 — action economy & turn structure

- **`search`/`study`/`influence`/`utilize` do not exist as `IntentType`
  values at all** (`dodge`, `help`'s assist-an-attack-roll flavor and `hide`
  closed in C14, 2026-09-01; Help's ability-check flavor is still open, no
  check-advantage producer exists). Deliberately deferred from C14 in full:
  none of the four has an agreed intent shape or acceptance scenario yet.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **Hide costs no Action** (2026-09-01). SRD 5.2 costs an Action to Hide;
  `_handle_hide` deliberately charges no Action/Bonus-Action budget (the
  same turn-keeping shape as Dash/`drop_concentration`) because the
  approved S02 catalog script requires a hide-then-attack sequence inside
  one turn, and the first attack swing hard-requires the Action — an
  Action-consuming Hide would make that script unsatisfiable. Tighten once
  strict Attack-action accounting lands. Cunning Action's Bonus-Action Hide is
  just as free (2026-09-24, C20): Dash and Disengage charge the Bonus Action,
  Hide charges nothing.
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
  clear defect — recorded for a future decision.
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
- **Initiative has no "Delay" option.** C14 (2026-09-01) added the
  engine-rolled `d20 + DEX modifier` path (`initiative=None`) with Surprise
  and Incapacitated Disadvantage; the SRD "Delay" combat option (holding
  your Initiative count to act later) is still absent.
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **Movement rules beyond the budget are absent:** crawling, climb/swim
  cost, jumping; `Combatant.movement_modes` is hydrated and never read.
  Standing from Prone (half Speed, rounded down) closed in C14
  (2026-09-01) via the `stand_up` `IntentType`
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_stand_up`).
  Occupancy (C16) treats every enemy space as
  impassable — the SRD's Tiny / two-sizes-larger pass-through and the "another
  creature's space is Difficult Terrain" cost both need creature size, which is
  not modelled; the forced-Prone consequence of ending a turn in a shared space
  is not applied either.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_move`)

## Audit 2026-08-26 — spellcasting & concentration

- **A spell's turn-boundary activities resolve at cast time (2026-10-04,
  C26a).** Every activity a spell carries resolves when it is cast, including
  the ones Foundry fires on a later turn: Weird's "End of Turn Save" makes
  every creature in the sphere save twice at once, taking the damage twice.
  Vitriolic Sphere's "End of Turn Damage", Incendiary Cloud's "Per Turn Save",
  Storm of Vengeance's turn-2-to-5 activities, Earthquake's "End of Turn
  Fissures", Delayed Blast Fireball's bead activities and the start-of-turn
  activities of Ensnaring Strike, Searing Smite, Stinking Cloud and Tsunami
  have the same shape. Needs a per-activity timing signal and a turn-boundary
  producer (see "No ongoing-damage producer").
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::submit_player_intent`)
- **An item's hazard area saves at use time, not when a creature enters it
  (2026-10-04, C26a).** SRD 5.2 Ball Bearings and Caltrops: "A creature that
  enters this area for the first time on a turn must succeed on a DC …
  Dexterity saving throw." A `use_item` now makes every creature already
  standing in the square save at once — an ally included — rather than
  waiting for a creature to walk into it on a later turn (v0.6: the named
  target only). This is the item-side sibling of the turn-boundary row
  above.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_area_targets`)
- **A creature caught by its own effect repeats the save at the end of the
  current turn, not "the end of its next turn" (2026-10-04, C26a).** Sleep
  cast with `excluded_target_ids=()` catches its own caster: the caster
  saves at the cast, then again when that same casting turn ends, because
  the repeat-save hook fires for whichever actor's turn is ending without
  checking whether the effect was applied on this very turn.
  `test_c26_s05_sleep_spares_its_caster` slices `[:3]` around the extra
  save.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_hook_run_end_of_turn_saves`)
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
  independent rolls (2026-09-03, C17).** SRD RAW rolls each
  dart's `1d4+1` separately; `resolve_damage` rolls the part once per
  activity and applies that single result to every target in the
  count-scaled fan-out, so all darts in one cast always deal identical
  damage. This is a documented deviation kept deliberately for draw-count
  determinism (a seeded replay's RNG draw count does not grow with slot
  level) rather than a gap to close.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/damage.py::resolve_damage`)
- **Pool choice for a multiclass Warlock cast is Spellcasting-first
  (2026-09-03, C17); no per-class spell-list gate or `use_pact_slot`
  flag.** `_slot_available`/`_take_spell_slot` always try the regular
  Spellcasting pool before Pact Magic; SRD §Multiclassing lets either pool
  cast either prepared spell, so this is correct for slot AVAILABILITY, but
  a caller cannot force a specific pool to be spent (e.g. to bank
  Spellcasting slots and burn Pact Magic first, or vice versa).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_take_spell_slot`)
- **Attack-kind repeat instances (Scorching Ray's rays) are not
  count-scaled (2026-09-03, C17).** The target-count scaling
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
- **Four concentration spells raise after spending their slot (2026-09-26,
  pre-existing).** Delayed Blast Fireball and Tsunami read `@item.uses.value`,
  Spider Climb reads `@attributes.movement.walk`, and Phantasmal Killer's save
  names no ability; the formula resolver has no handler for either token and
  the save resolver refuses an empty ability, so `submit_player_intent` raises
  `ValueError` once the slot is spent. All four are SRD 5.2 spells ("When you
  cast a spell, you expend a slot"): the cast should resolve, or be refused
  before the slot goes.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/formula.py::_resolve_token`)
- **A readied spell always targets its own caster (2026-09-26,
  pre-existing).** SRD 5.2 Ready: "When you Ready a spell, you cast it as
  normal ... but hold its energy, which you release with your Reaction when
  the trigger occurs." The engine resolves a readied spell with its reactor as
  the sole target and ignores the `ready` intent's `target_id`, so a readied
  Sunbeam or Wall of Ice hits its own caster; only a self-targeted spell
  (Shield) resolves as written.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_readied_spell_cast`)
- **A potion's spell concentrates (2026-09-26, pre-existing).** SRD 5.2
  potions give a spell's effect "(no Concentration required)" — Potion of
  Speed: "the effect of the *Haste* spell for 1 minute (no Concentration
  required) without suffering the wave of lethargy". A potion's effects keep
  the spell's concentration flag and join the drinker's concentration chain,
  and both options land at once: Potion of Speed applies `effect:hasted` and
  `effect:lethargy`, Potion of Growth `effect:enlarged` and `effect:reduced`.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_writeback_concentration`)

## Audit 2026-08-26 — character derivation

`derive_sheet` (C19) closed most of this audit's findings: HP, AC, hit dice
and skill/save proficiencies are now computed engine-side from
`CharacterBuildSpec`, and `build_party_member` folds them into
`PartyMemberSpec` for any value a host leaves unset. The bridge's `sheet.py`
now calls the engine rather than standing in for it. Residual gaps:

- **Group checks and tool proficiencies are absent.** Neither is derived from
  class/background/equipment, nor accepted as an explicit build input.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
- **Class features that are prose-only in the corpus (amended 2026-09-24,
  C20):** Divine Smite, Metamagic / Sorcery Points and Eldritch Invocations.
  Nothing ties a Divine Smite cast to the Melee weapon or Unarmed Strike hit
  it rides, and Paladin's Smite's free cast ("you can cast it without
  expending a spell slot, but you must finish a Long Rest before you can cast
  it in this way again") has no activity. `metamagic.json`, its option
  features, `eldritch-invocations.json` and the invocation features carry no
  activities. Font of Magic's two conversions price Sorcery Points with
  formulas (`1 + @scaling + floor(@scaling / 3)`, `0 - @scaling`) the engine
  doesn't evaluate, so each spends one point. None of these has an approved
  scenario.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_feature_activity_cost`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/paladins-smite.json`)
- **Equipment:** ammunition decrement, shield don/doff and encumbrance are
  absent (C19 validates `attuned_items` against the attunement limit and
  `requires_attunement`; C15 picks versatile damage from
  `PlayerIntent.two_handed`). Magic-item charges are the one other equipment
  mechanic that is real.
  (`packages/dnd5e-engine/src/dnd5e_engine/build_spec.py`)
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
- **An engine-rolled Initiative reads a monster's Dexterity modifier, never
  its own Initiative modifier (2026-09-27, C23).** SRD 5.2: "A monster's
  Initiative modifier is typically equal to its Dexterity modifier, but some
  monsters have additional modifiers, such as Proficiency Bonus."
  `_initiative_dexterity` (C23) reads only `Monster.ability_scores.dex`, and
  the dataset carries no separate Initiative-modifier field to read
  instead. Measured over the 329 SRD stat blocks, the true Initiative
  modifier differs from the Dexterity modifier in 110 of them (e.g. the
  Aboleth: DEX modifier +0, SRD Initiative modifier +3) — C23 moved the
  rolled total closer to the SRD value for most of them, but not onto it.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_initiative_dexterity`,
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/monster.py::Monster`)
- **Target selection is hard-coded lowest-HP living enemy** (a PC or a
  party-side summon since C21b), with no reach/LoS/threat
  consideration — the monster AI never consults
  `_combatant_can_see` or a Frightened monster's own line-of-sight/
  no-approach rule when choosing a target or walking; confirmed still open
  after C18 (2026-09-03) — a rule card scoped it out as not an SRD rule, so
  this stands as a deliberate scope cut, not an oversight.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_select_monster_targets`)
- **`PartyMemberSpec` has no `physical_resistances_nonmagical_only`
  counterpart** (2026-08-30). PCs are pinned to the nonmagical-only reading of
  host-authored B/P/S resistances; a PC whose resistance should be
  unconditional cannot express it.
  (`packages/dnd5e-engine/src/dnd5e_engine/specs.py`)
- **Bridge does not serve the `conditions` / `traits` categories**
  (2026-08-27) — `routes_content._CATEGORIES` predates C22.
  (`packages/nat20-bridge/src/nat20_bridge/routes_content.py`)
- **Seven stat blocks raise `ValueError` on their own turn (2026-10-07,
  C29).** `advance_monster_turn` raises out of the activity layer whenever
  the turn picks one of these actions, so the monster's turn fails (over
  HTTP, `/advance-monster` answers 500): the Night Hag's Phantasmal Killer
  (Spellcasting) saves with no ability; the Air Elemental's Whirlwind and,
  fought as foes, the Draconic Spirit's Rend and the Giant Insect's attacks
  roll `@mod` with no governing ability; the Homunculus's Bite has an empty
  damage formula; and the Large and Huge Animated Objects' Slam reads
  `@flags.dnd5e.summon.level`. Five of them — the Homunculus, the Draconic
  Spirit, the Giant Insect and the two Animated Objects — raise the same way
  from their opportunity attack: a character moving away from one answers
  422 mid-move, left partway down its path, with the move's own events
  dropped too.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/save.py::_resolve_save_ability`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/formula.py::_resolve_token`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/dice.py::_parse`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_opportunity_attack`)

## Not modelled by design (recorded so nobody re-audits them)

Hiding vs passive
Perception, falling, suffocation/drowning, underwater, extreme weather,
hazards/traps, objects as targets, mounted combat, elevation, multi-tile
footprints. Exploration-tier; revisit only if a host asks. Mounted combat
covers the steeds Find Steed and Phantom Steed summon (SRD 5.2 Find Steed:
the steed "functions as a controlled mount while you ride it"), so both
spells stay narrative (2026-09-26, C21b;
`packages/dnd5e-engine/src/dnd5e_engine/activities/conjuration.py::SUMMONS`).

Two condition rules touch only checks the engine never rolls, so a host
applies them (2026-10-06, C27): Blinded's and Deafened's "automatically fail
any ability check that requires sight" (or hearing) — Hide is Stealth and
escaping a grapple is Athletics or Acrobatics, so no engine check needs a
sense — and Charmed's "The charmer has Advantage on any ability check to
interact with you socially" — the engine rolls no social check.
`docs/concepts/combat.md` gives the recipe for both
(`packages/dnd5e-engine/src/dnd5e_engine/rules/conditions.py`).

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
  Retyping to `int | None = None` changes results for a host that passes an
  explicit 10 for a template whose Dexterity differs, so it waits for a minor
  release with a migration note; an engine-rolled Initiative reads the same
  sentinel since C23.
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
  Unowned since C13.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)
- **A turn-start or round-start hook that removes a creature would strand
  the turn (2026-09-27, C23).** A current actor that leaves the initiative
  order hands its turn on through `_hand_off_departed_turn` once the intent
  or legendary action that removed it has resolved. `_begin_turn` runs the
  `round_start` and `turn_start` hooks and the pending death save with no
  such hand-off, so a removal there would leave `departed_actor_id` set and
  no `TurnStarted`. No registered hook can remove a creature today (the
  turn-start one expires reaction effects); whoever adds one needs the
  hand-off too.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_begin_turn`)

## Damage at 0 Hit Points (2026-08-29)

Surfaced while landing C12-S06 (Characters fall Unconscious at 0 HP).

C15 added `DamageApplied.is_crit`, which closed the Critical Hit half (a
Critical Hit on a creature at 0 Hit Points costs two failures). The
per-instance half below remains: `source_id` names a weapon or activity, not
one hit.

- **A multi-type hit inflicts one death-save failure PER DAMAGE TYPE.** SRD 5.2
  "Damage at 0 Hit Points" charges one failure per instance of damage, but
  `activities/apply.py` emits one `DamageApplied` per damage type and the 0-HP
  fold counts a failure per event, so a fire+slashing hit on a downed Character
  costs two failures. Needs a per-hit instance id on `DamageApplied` so the
  fold can collapse the events of one attack.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_apply_zero_hp_to_character`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py::apply_damage`)
- **A death-save failure from damage at 0 HP surfaces no event.** The failure is
  written straight onto `Combatant.death_saves`; hosts narrating from the event
  stream see the `DamageApplied` but never learn a failure landed (only
  `DeathSaveRolled`, from the turn-start roll, carries counters). The fix needs
  a new `CombatEvent` member or a counters payload on an existing one.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_apply_zero_hp_to_character`)

## Conditions — SRD 5.2 rows not enforced (2026-08-27)

C12 gave all 15 conditions teeth on the live combat path (see
`docs/capabilities.md`). These rows are what is left; each needs a seam another
cluster owns.

- **An engine-rolled Initiative ignores a seeded Poisoned, Frightened or
  Invisible status (2026-10-06, C27).** Initiative is a Dexterity check (SRD
  5.2: "they make a Dexterity check"), so a Poisoned creature, or one
  Frightened of a creature in sight, should roll it at Disadvantage, and SRD
  5.2 Invisible gives "Advantage on the roll"; `_resolve_initiative` reads
  only Surprise and a seeded Incapacitated status, set before any immunity
  check (`_seeded_incapacitated_ids`) — so a Ghost seeded Paralyzed still
  rolls Initiative at Disadvantage.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_initiative`)
- **A condition immunity an active effect grants is not honoured (2026-10-06,
  C27).** The `system.traits.ci.value` change is read only from a character's
  always-on features when it is built (Nature's Ward), so Heroes' Feast
  (Frightened, Poisoned), Heroism (Frightened), Freedom of Movement
  (Paralyzed, Restrained), Mind Blank (Charmed), Calm Emotions (Charmed,
  Frightened), Gaseous Form and Wind Walk (Prone), Mindless Rage while raging
  (Charmed, Frightened) and the Periapt of Proof against Poison (Poisoned)
  grant no immunity in combat. Nor does a spell a stat block casts before
  combat: the Archmage's Spellcasting lists "Mind Blank (cast before
  combat)", and its Charmed immunity comes only from that spell (amended
  2026-10-06, C28). The dying rules don't consult
  `is_condition_immune` either: a character that regains Hit Points, or
  rolls a 20 on a death save, is left Prone even when immune to it (Wind
  Walk, or a host-listed `condition_immunities`).
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_fold_active_effect_changes`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/effects.py::is_condition_immune`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_emit_apply_healing`)
- **Invisible's "Concealed" is not modelled (2026-10-06, C27).** SRD 5.2: "You
  aren't affected by any effect that requires its target to be seen unless
  the effect's creator can somehow see you." No spell or effect checks that
  its creator can see its target, so Hold Person ("a Humanoid that you can
  see") holds an Invisible one.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_combatant_can_see`)
- **Grappled's "Movable" is not modelled (2026-10-06, C27).** SRD 5.2: "The
  grappler can drag or carry you when it moves, but every foot of movement
  costs it 1 extra foot unless you are Tiny or two or more sizes smaller than
  it." A grappler's move leaves the creature it grapples where it stands.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_handle_grapple`)
- **An ending effect also clears a same-name condition entry no effect owns
  (2026-10-06, C27).** `_emit_apply_effect_expired` keeps an entry only when
  a different live effect still owns it (`source_effect_id`); an entry with
  no owning effect at all — an action's Prone (Shove), or the dying rules'
  Unconscious — is cleared too when an unrelated effect that names the same
  status in its own `statuses` expires. The reverse also holds: a condition
  an action applies to a creature that already holds it from an effect gets
  no entry of its own (`_fold_condition_onto_combatant` keeps one entry per
  name), so a Shove's Prone ends with that effect, and a Grapple's escape DC
  is never stored, so `escape_grapple` is refused.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_emit_apply_effect_expired`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_fold_condition_onto_combatant`)
- **`ConditionRemoved` announces an ending effect's condition even while
  another live effect keeps it (2026-10-06, C27).** `_drop_concentration`
  and the end-of-turn repeat-save path emit it for every condition the
  ending effect installed, unconditionally. The state is right — the typed
  list and `active_conditions` keep the entry the other effect owns — but
  narration reading the event stream may report a removal that did not
  happen.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_drop_concentration`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_run_end_of_turn_saves`)
- **A non-condition status an effect brings mid-combat reaches only the typed
  condition list (2026-10-06, C27).** Foundry statuses that are not SRD
  conditions (Hunter's Mark's `marked`, and `cursed`, `ethereal`, `stable`
  and the rest) land on `Combatant.conditions`, and so in
  `LiveCombatView.initiative[*].conditions`, through the `EffectApplied`
  fold. No `ConditionApplied` follows, so `active_conditions` never lists
  them, while a seeded effect writes them to both stores. No rule reads
  them; the two stores just disagree on them.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_emit_apply_effect_applied`)

## C12 deferred minors (2026-08-27)

Small, real and deliberately not worth their own task; recorded so they are not
re-discovered.

- **`activities/check.py::_check_modifier`'s skill-branch penalty fold is
  untested.** The exhaustion penalty is pinned on the ability branch only; the
  `return int(skills[key]) + penalty` line has no direct test.
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/check.py`)
- **`_monster_dash_movement_budget`'s parameter is still named `base_speed`**
  although its caller now passes the condition/exhaustion-PROJECTED speed. A
  rename to `effective_speed` is cosmetic but removes a real reading trap.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_monster_dash_movement_budget`)
- **The `enumerate(live.initiative)` → `model_copy` → slot-replace loop is
  still open-coded 38 times**, although `_update_combatant(live, entity_id,
  **fields)` now exists (C21) and 9 call sites use it.
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`)

## Blocked

- **Lair actions are blocked on translator support** (2026-09-03, C18).
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

- **`over` is always `false` (2026-10-07, C29).** An intent or
  advance-monster response's `over` is `LiveCombatView.ended`, which only
  `/end` sets, and an ended combat's id answers 404, so no response reports
  `true`, not even for a fight whose last foe or last character has dropped.
  A "fight decided" flag, with the outcome and the combat ended for the
  client, needs a client release that reads it.
  (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_envelope`)
- **No legendary routes (2026-10-07, C29).** `/advance-monster` takes no
  body, so a client can't spend a legendary action
  (`advance_monster_turn(legendary=True, actor_id=...)`) or arm a Legendary
  Resistance (`resolve_legendary_resistance`).
  (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_advance_monster_route`)
- **`/v1/check` takes no Expertise, Jack of All Trades or Reliable Talent
  (2026-10-07, C29).** `CheckSpec` has `expertise_skills`,
  `jack_of_all_trades` and `reliable_talent`; the route's request model
  doesn't.
  (`packages/nat20-bridge/src/nat20_bridge/app.py::_CheckRequest`)
- **A bridge combat starts rested, and its view shows no spell slots or
  feature uses (2026-10-07, C29).** `/v1/combat` passes no `spell_slots`,
  `pact_slots` or `custom_counters`, so every fight starts with full slots and
  feature uses, Magic Initiate's slotless cast included; and
  `LiveCombatView.spell_slots_by_entity`, `pact_slots_by_entity` and
  `custom_counters_by_entity` stay engine-side, so a client can't show what a
  character has left. The view omits Temporary Hit Points
  (`tracked_temp_hp`), concentration (`concentration_chain`) and a foe's
  recharge and legendary pools (`monster_action_uses_by_entity`,
  `legendary_actions_by_entity`, `legendary_resistances_by_entity`) too.
  (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_build_party_specs`,
  `packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_view_route`)
- **Two party members with one name share an entity id (2026-10-07, C29).**
  `/v1/combat` derives `char:<name>` when a member omits `entity_id`, and
  `start_combat` accepts two combatants with one `entity_id`: the initiative
  order lists both, but their cells, HP and turns collide.
  (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py::_build_party_specs`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::start_combat`)
- **Sixteen event types narrate through the generic fallback (2026-10-07,
  C29).** `spell_cast`, `effect_applied`, `effect_expired`, `temphp_applied`,
  `recharge_rolled`, `concentration_dropped`, `death_save_started`,
  `death_save_rolled`, `stabilized`, `actor_moved`, `combatant_moved`,
  `dash_taken`, `move_failed`, `reaction_triggered`,
  `legendary_action_used` and `legendary_resistance_used` render as
  `[type] key=value …` dumps in the narration a client hands its model.
  (`packages/nat20-bridge/src/nat20_bridge/narrate.py`)

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
- **`monsters/ancient-gold-dragon.json` ships an unfilled template (amended
  2026-10-06, C26b).** Its multiattack description is literally
  `"makes {count} [[/item]] attacks and uses [[/item]]."`, so the action
  cannot fan out: the engine's Multiattack join reads one attack or breath
  where SRD 5.2 says "The dragon makes three Rend attacks". Every sibling
  ancient dragon names its Rend attack, and the upstream Foundry actor ships
  the same unfilled text, so the translator is faithful: the fix is a
  translator correction plus a regen, or an upstream fix. Registered in
  `tests/oracle/known_prose_defects.json` and gated by
  `tests/test_corpus_prose_integrity.py`; re-check on the next
  `make refresh-upstream` and de-register if upstream has fixed it.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_build_monster_action`)
- **Inherited activation `type` is not resolved** (2026-08-27). An activity
  with `activation.override: false` inherits the item-level activation in
  Foundry (Shield's utility activity is a Reaction, but canonical stores the
  activity's own `type: action`). C22 derives `reaction_conditions` from the
  effective block but leaves `type` as shipped. Resolving it changes bytes on
  every inheriting activity — do it as its own regen PR.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_effective_activation`)

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

## Feature-choice pools (2026-09-24, C20)

The Champion's level-7 Fighting Style `ItemChoice` pool
(`subclasses/champion.json`) copies Foundry's full list. Besides the four SRD
5.2 styles it names Blind Fighting, Dueling, Interception, Protection, Thrown
Weapon Fighting and Unarmed Fighting, whose UUIDs resolve to nothing in the
corpus. Those six are not SRD 5.2 content and must not be implemented;
`FightingStyle` accepts only the four. The translator could drop unresolvable
pool entries.
(`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/subclasses/champion.json`)

## Class scale-value defects (2026-09-25)

- **A Barbarian 16 has 6 Rages; SRD 5.2 gives 5.** The SRD 5.2 Barbarian
  Features table lists 5 Rages from level 12 through 16 and 6 from level 17,
  but the Rages `ScaleValue` in `classes/barbarian.json` steps to 6 at level
  16 (`"16": 6`), so the Rage use cap lets a Barbarian 16 rage once too often.
  This predates C20. The fix belongs in the translator, as a correction like
  `_WEAPON_BASE_DAMAGE_CORRECTIONS`.
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/classes/barbarian.json`,
  `packages/dnd5e-srd-data/tools/translators/foundry.py`)

## Conjuration and monster data (2026-09-25, C21a)

- **26 conjuration actors and 7 magic-item actors are quarantined
  (2026-09-25, C21a).** 24 conjuration and companion stat blocks and the 7
  items fail on `'custom' is not a valid CreatureType`, and 2 stat blocks on
  all-zero ability scores, so none ships. Spiritual Weapon's upstream attack
  lives on one of them; the engine carries that attack in a registry instead
  (`CONSTRUCTS`). Shipping them needs Foundry's `custom` type mapped, and
  belongs with the spells that need them.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py`)
- **The Priest's Spiritual Weapon is a data slip, and the Cultist Fanatic's
  has no uses cap (2026-09-25, C21a).** `actors24/humanoid/priest.yml` points
  the Priest's 1/Day Spellcasting at Spiritual Weapon's uuid, while the
  entry's own text, like the SRD 5.2 Priest, says "1/Day Each: *Spirit
  Guardians*"; the engine follows the uuid. The SRD 5.2 caster is the Cultist
  Fanatic ("Spiritual Weapon (2/Day)", a Bonus Action), whose corpus entry
  carries no uses cap. Monster casts of Spiritual Weapon wait on this row (see
  "No monster casts a construct or summon spell" under Conjurations and
  shape-shifting).
  (`packages/dnd5e-srd-data/tools/translators/foundry.py`)
- **A monster attack's range inherited from its item is not resolved
  (2026-09-25, C21a).** An activity with `range.override: false` takes its
  item's range in Foundry, but canonical stores the activity's own
  (`units: "self"`), so the Ape's Rock (SRD 5.2: range 25/50 ft.) reads as a
  5-foot melee reach, for the monster AI and a commanded stat-block swing
  alike. It is the same inheritance regen as the activation row under
  "Shipped prose quality".
  (`packages/dnd5e-srd-data/tools/translators/foundry.py`)
- **Two monster Armor Classes disagree with SRD 5.2 (2026-09-25, C21a).**
  `elk` ships Foundry's flat natural armor 11 against the SRD's 10 (flat
  values are kept as shipped), and `flying-snake` derives 12 against 14 (a
  recorded divergence in `tests/oracle/known_oracle_divergence.json`).
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_monster_ac`)
- **Five Beast attacks differ from SRD 5.2 (2026-09-26, C21a).** Foundry data
  that Wild Shape and Polymorph now put in a creature's hands: Giant Frog Bite
  1d6 + 1 (SRD "5 (1d6 + 2) Piercing"), Giant Crab Claw and Giant Octopus
  Tentacles Slashing (SRD Bludgeoning), Swarm of Insects Bites Piercing (SRD
  "6 (2d4 + 1) Poison"), and Swarm of Venomous Snakes Bites with no Poison
  rider (SRD "plus 10 (3d6) Poison damage"). Canonical content flows only
  through the translator, so the fix is a correction there or a recorded
  divergence per monster.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py`)
- **A monster action's effect riders ship no effect definitions (2026-10-06,
  C27).** 245 action and legendary-action activities across 176 SRD
  monsters reference effects
  (`activities[].effects`), but `Monster` carries no `passive_effects` for
  them to resolve against and the engine passes none, so none applies: the
  Giant Spider's Web never Restrains and the Vampire's Grave Strike never
  Grapples. The translator would have to carry each action's effects, and
  each of the 40 Grappled riders (39 monsters) its escape DC, which
  `escape_grapple` reads from `ActiveCondition.save_dc` (amended 2026-10-06,
  C28).
  (`packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/monster.py::MonsterAction`,
  `packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_resolve_monster_attack_activities`)
- **Three monster recharges disagree between the pinned Foundry pack and the
  SRD 5.2 creature text (2026-10-04, C26a).** The Ghost's Possession ships no
  recharge (open5e's SRD 5.2 text: Recharge 6), the Minotaur of Baphomet's Gore
  recharges on a 6 (5–6), and the Succubus's Charm on 5–6 (no recharge). None
  is an area action, so C26a's correction table left them; each needs checking
  against the SRD 5.2 document before it gets a correction row.
  (`packages/dnd5e-srd-data/tools/translators/foundry.py::_MONSTER_ACTION_CORRECTIONS`)

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
