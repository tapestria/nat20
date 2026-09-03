# Capability matrix — what Nat20 resolves

Nat20 is a working engine with real gaps. This page is the honest inventory:
what it resolves mechanically, what it accepts but treats as a narrative no-op,
and what it does not model at all. **If a rule is not listed as resolved here,
assume it is not enforced.**

Anything marked *not modelled* is tracked in
[`BACKLOG.md`](https://github.com/tapestria/nat20/blob/main/BACKLOG.md), which is
the authoritative gap ledger. The counts below are measured against the shipped
`dnd5e-srd-data` corpus and pinned by
`packages/dnd5e-engine/tests/test_capability_matrix.py`, so they cannot go stale
without failing CI.

!!! tip "The fastest way to check one thing"

    Content resolves if it carries an activity of a *mechanical* kind — `attack`,
    `damage`, `save`, `heal`, `check`, `cast`, or a `utility` activity carrying
    effect riders. A `summon`, `transform`, or `enchant` activity, or a bare
    `utility`, loads fine and emits **no events**.

## Combat loop

| Mechanic | Status | Notes |
|---|---|---|
| Initiative order, rounds, turns | ✅ Resolved | Deterministic tie-break (initiative → dex → entity id); one shared turn-advance path, and each boundary is marked in the stream by a `TurnPhase` event. `PartyMemberSpec`/`EncounterMemberSpec.initiative` accepts `int | None`: `None` rolls an engine `d20 + DEX modifier` (in spec order, using the combat's seeded RNG) with Disadvantage when `is_surprised` or a seeded incapacitated-implying `active_effects` status applies (C14 Task 8). No "Delay" combat option yet. |
| Turn lifecycle — start/end of turn, top-of-round hooks | ⚠️ Partial | The seam exists (`turn_lifecycle.py`, run off the single advance path in registration order); the registered hooks are the round-duration tick, the timed-effect expiry (`seconds` / `turns` / until-end-of-next-turn) and the reaction-effect expiry — ongoing damage, regeneration and recharge have no producer yet |
| Effect durations (`rounds`, `turns`, `seconds`, until end of next turn) | ✅ Resolved | `rounds` and `ceil(seconds / 6)` tick at the caster's turn end, `turns` at the target's; `flags["until_end_of_next_turn_of"]` expires at that actor's next turn end. `rounds` wins when an effect carries both counters; concentration-flagged effects are exempt (the concentration cascade owns them); a concentration spell's own maximum duration is tracked separately by the engine (caster-keyed rounds counter from the typed spell duration) |
| Attack rolls, crits, damage, resistances/immunities/vulnerabilities | ⚠️ Partial | Advantage/disadvantage is rolled on **activity** attacks: attacker `flags.advantage.attack` / `flags.disadvantage.attack` effects plus the condition-derived sources (Invisible attacker; Blinded/Poisoned/Frightened/Restrained attacker; Paralyzed/Stunned/Unconscious/Blinded target), cancelling per SRD §Advantage and Disadvantage. Opportunity attacks now roll through the same `roll_d20_test` primitive and honor the same condition, dodging-target, Exhaustion, `unseen` and Invisible-carve-out sources (C16b composite `_combatant_can_see`). Prone (advantage within 5 ft, disadvantage beyond) and Grappled (disadvantage vs anyone but the grappler) are live (C12); the distance-derived sources are now all live: unseen attacker (C16b), Ranged Attacks in Close Combat (C15) and long-range disadvantage (C15) each append their own `AdvantageSource`. A Heavy weapon (raw Strength score below 13) rolls with disadvantage (C15) — this and the Vex/Sap mastery riders below all ride the same `"trait"` source token, so a host cannot distinguish them from the token alone. Attack proficiency is a real gate (C15): a host that never sets `PartyMemberSpec.weapon_proficiencies` is assumed proficient (legacy behavior, unchanged); an explicit (possibly empty) list enforces proficiency by the weapon's category or slug, omitting Proficiency Bonus (never subtracting it) when unproficient. `DamageApplied` now carries `source_id` (weapon slug / synthesized activity id / `mastery:<slug>`) and `is_crit` for weapon-attack damage (C15; spell/save/heal damage still reports `source_id=None`, a C17+ seam); a critical hit against a target already making death saves counts as two failures (SRD §Damage at 0 Hit Points, C15). Magic weapons and spells overcome resistance to *nonmagical* B/P/S (`Weapon.magical`; host-authored resistances default to the nonmagical reading via `physical_resistances_nonmagical_only`). |
| Saving throws, half-on-save, save-for-effect | ✅ Resolved | Every save adds `d20 + ability modifier + proficiency bonus (if proficient)` for all six abilities, on all three paths (activity saves, the damage-triggered concentration check, the end-of-turn repeat save). Monster ability scores, save proficiencies and proficiency bonus hydrate from the `monster_template_slug`. The condition projections (auto-fail, Restrained DEX disadvantage, exhaustion's `-2 × level`) apply on all three paths (C12). **Not yet folded in:** effect-derived bonuses (Bless/Bane) on the two orchestrator-level paths. |
| Ability & skill checks (in and out of combat) | ✅ Resolved | `resolve_check`; seed via `CheckSpec.rng` |
| Action economy (action, bonus action, reaction, movement) | ⚠️ Partial | Extra Attack (`attacks_remaining` per Action, `LiveCombatView.turn`) and two-weapon fighting (Light-property off-hand Bonus Action) are modelled (C14); Action Surge and Flurry of Blows are not. Incapacitated blocks action/bonus/reaction intents (C12). |
| Dash, Disengage | ✅ Resolved | |
| Dodge | ✅ Resolved | Attacker Disadvantage + Dexterity save Advantage until the start of your next turn; lost under Incapacitated or Speed 0. SRD 5.2 "if you can see the attacker" is now enforced (C16b `_combatant_can_see`) at both the regular-attack context sites and on Opportunity Attacks — a Blinded dodger imposes no attack disadvantage. |
| Help | ✅ Resolved | Assist-an-attack-roll flavor only (the ability-check flavor has no check-advantage producer yet): the next ally attack against a target within 5 ft of the helper rolls with Advantage, consumed by that one attack roll (hit, miss, or cancelled to normal) and otherwise expiring at the start of the helper's own next turn. |
| Hide | ✅ Resolved | Gated on Three-Quarters/Total cover, Heavy obscurement, or Darkness on the hider's own cell (SRD 5.2 glossary: "An area of darkness is Heavily Obscured", `GridTopology.light_on_cell`); the hider must also be out of every living, non-Incapacitated hostile's line of sight (C16b `_combatant_can_see`) — skipped only when the hider's own cell already carries Three-Quarters/Total cover, since per-cell cover is omnidirectional and already breaks every line (SRD 5.2 §Cover). On a successful DC 15 Dexterity (Stealth) check grants the Invisible condition, which ends the moment the hider makes an attack roll or casts a spell with a Verbal component. Touches no Action-economy budget (see BACKLOG.md). |
| Opportunity attacks | ✅ Resolved | Both directions (PC↔monster); same-zone reach approximation. Rolls through `roll_d20_test` with condition, dodging-target and Exhaustion sources (C14), and now also honors the C16b "can see" trigger (`_combatant_can_see`, both directions — a sight-blocked reactor never triggers, no Reaction spent) plus the `unseen`, Invisible and Frightened carve-outs; cover on the AoO roll itself remains unmodelled (BACKLOG.md) |
| Death saves, stabilization | ✅ Resolved | |
| Instant death (massive damage) | ✅ Resolved | A Character whose damage remainder equals or exceeds their Hit Point maximum dies outright — `Death(reason="instant_kill")` (C12) |
| Concentration, incl. damage-triggered saves and cascade drop | ✅ Resolved | Damage save with real CON modifier + DC clamped to [10, 30]; one-at-a-time (a new concentration cast cascades the old drop); ends on death and Incapacitated-implying conditions; voluntary "drop_concentration" intent (no action cost); maximum-duration expiry from the typed spell duration at the caster's turn end. Magic Resistance on this path is C18. |
| Temporary HP, healing | ✅ Resolved | |
| Conditions (the 15 SRD conditions) | ⚠️ Partial | Applied/removed and gated by immunities (an immune creature never acquires the condition on either store) — Weapon-mastery Topple honors condition immunity too (C15: the save still rolls, only the resulting `prone` is gated, via the shared `is_condition_immune` helper). Enforced on the live path: attack-roll advantage/disadvantage for every SRD 5.2 row incl. Prone (distance-aware), Grappled (grappler-aware), Frightened — now gated on line of sight to a known, living, tracked fear source (C16b `_fear_source_in_sight`; an unknown/dead/untracked source keeps the SRD-conservative disadvantage) — and Invisible — the "can somehow see you" carve-out now pierces only via blindsight/truesight in range with line of sight (C16b `_pierces_invisibility`), which also covers a hidden creature; Incapacitated (and Paralyzed/Stunned/Petrified/Unconscious) rejects action/bonus/reaction intents with `IntentRejectedError("actor_incapacitated")` and skips reactions; Speed 0 (`MoveFailed(reason="speed_zero")`) and Frightened's "can't willingly move closer" rule toward a fear source it can see (`MoveFailed(reason="frightened")`, C16b; SRD 5.2 imposes this unconditionally with no line-of-sight conjunct on the no-approach sentence — an engine deviation, see BACKLOG.md); auto-failed STR/DEX saves and Restrained DEX disadvantage on every save path; Paralyzed/Unconscious auto-crit within 5 ft; Charmed cannot attack or harmfully target the charmer (a charmed monster will not select them either); Characters fall Unconscious at 0 HP, including a Character hydrated into combat already at 0 HP (massive damage kills). **Partial because two SRD rows are still unenforced:** Frightened's ability-check line-of-sight gate (the attack-roll half and the no-approach movement rule are now enforced, C16b) and Blinded/Deafened sense-based check auto-fail — each needs a seam another cluster owns. Incapacitated's initiative disadvantage closed via C14 Task 8 (2026-09-01) — `start_combat` rolls Initiative at Disadvantage for entities with a seeded incapacitated-implying `active_effects` status. See BACKLOG.md "Conditions — SRD 5.2 rows not enforced". |
| Exhaustion | ✅ Resolved | SRD 5.2: every D20 Test (attacks, saves incl. death saves, checks) is reduced by `2 × level`; Speed by `5 ft × level`. Long Rest reduces the level by 1 (`resolve_long_rest(exhaustion_level=)`); level-6 death is still unmodelled. |
| Surprise | ✅ Resolved | `is_surprised=True` on a party/encounter spec (only consulted when that spec's `initiative` is `None`) imposes Disadvantage on the engine-rolled Initiative roll (C14 Task 8). Host is still responsible for deciding *who* is surprised. |
| Grapple / Shove | ⚠️ Partial | Unarmed Strike options (C14): the target saves STR or DEX, whichever modifier is higher (tie → STR), vs DC `8 + STR mod + PB`; Grapple applies the Grappled condition with the escape DC stored on it, Shove applies Prone (default) or a 5-ft push per `PlayerIntent.shove_push`. Size gate, free-hand gate, and distance-exceeded auto-release are not modelled (BACKLOG.md). |
| Two-weapon fighting | ✅ Resolved | A Light main-hand weapon opens a same-turn off-hand Bonus Action swing (C14); the ability modifier is added to off-hand damage only if negative. |
| Cover, line of sight | ✅ Resolved | Grid backend only; walls, blocked cells and interposed creatures — see below |
| Flanking | ❌ Not modelled | Not an SRD rule (optional variant) |

## Spatial

| Mechanic | Status | Notes |
|---|---|---|
| Zone-graph topology | ⚠️ Deprecated | Weighted, undirected; shortest-path distance. `start_combat(scene_zones=...)` warns since 0.6.0 and is removed in 0.7.0 — migrate to `GridScene` |
| 2-D grid, Chebyshev distance | ✅ Resolved | `GridScene`; one cell = `cell_size_ft` |
| Blocked cells, difficult terrain | ✅ Resolved | Difficult terrain doubles entry cost |
| Walls / line of sight | ✅ Resolved | Grid only; walls and blocked cells block sight and movement; the zone backend always has clear sight |
| Cover (half / three-quarters / total) | ✅ Resolved | Grid only; scene cover cells, blocked cells (total) and interposed creatures (half); folds into AC and Dexterity saves; a `cover_cells` tag on the target's own cell counts (an object it shelters behind); Sacred Flame's `ignore_cover` strips the Dexterity-save bonus |
| AoE templates (sphere / cone / line / cube / cylinder) | ✅ Resolved | Grid only; `cells_in_template` with line of effect from the point of origin (walls / blocked cells exclude cells); `PlayerIntent.direction` aims cones, lines and cubes |
| **Multi-cell movement in one intent** | ✅ Resolved | A `"move"` intent paths to any reachable cell within budget (allies passable, enemies block, no ending in an occupied cell); one `ActorMoved` per intent; `MoveFailed` reasons `unreachable` / `occupied` / `blocked_path` |
| Elevation / flying altitude | ❌ Not modelled | The grid is strictly 2-D |
| Multi-tile (Large+) creature footprints | ❌ Not modelled | Every creature occupies one cell |
| Threat-aware or cost-aware pathfinding | ❌ Not modelled | `shortest_path` is fewest-squares BFS; the route's terrain cost is charged but not minimised |
| Forced movement (push) | ✅ Resolved | `push_combatant` → `CombatantMoved(forced=True)`; wired for Thunderwave, Shove's push option (C14), and the Push weapon mastery (C15, always the full 10 ft — the "Large or smaller" size gate is unmodelled, see BACKLOG.md) |
| Vision and light (darkness, darkvision, blindsight, truesight, obscurement) | ⚠️ Partial | Grid only; `GridScene.lighting` / `obscurement_cells` + `GridTopology.can_see` feed the `unseen` attack advantage/disadvantage both ways. The composite `_combatant_can_see` predicate (Blinded viewer, Invisible target, blindsight/truesight reach, else the scene model) gates every other SRD "can see" conjunct: the "if you can see the attacker" half of a dodging combatant's attack-disadvantage, Ranged Attacks in Close Combat, the Opportunity Attack trigger (both directions), Hide's "out of any enemy's line of sight" check, and Frightened's line-of-sight gate (attack-roll disadvantage and the "can't willingly move closer" movement rule). A dark cell now also satisfies Hide's Heavily Obscured gate. Still no light sources (torches, *Light*, *Darkness*) and no Blinded emission from darkness |

## Spells

The engine resolves a spell by walking its typed activities. Spells whose only
activities are `summon`, `transform`, `enchant`, or a rider-less `utility` load
correctly and **emit no events**.

| | Count |
|---|---|
| Spells in the corpus | **339** |
| Resolve to at least one mechanical activity | **231** (68%) |
| Load but resolve to nothing | **108** (32%) |
| …of which are concentration spells | **32** |

Inert concentration spells include staples a combat host will reach for:
*Blur, Darkness, Fog Cloud, Spiritual Weapon, Wall of Force, Silent Image,
Globe of Invulnerability, Expeditious Retreat.* Others in the inert set
(*Alarm, Augury, Clairvoyance, Create Food and Water*) are out of scope for a
combat engine by nature.

| Spell mechanic | Status |
|---|---|
| Spell slots, upcasting, at-will/innate casting | ⚠️ Partial — per-class/multiclass/Pact tables derived engine-side (`derive_spell_slots`, `derive_multiclass_slots`, `derive_pact_slots`); rests restore slots; Pact Magic is a second pool; upcasting scales dice AND target count (`target.affects.count`); attack-kind repeat instances still not scaled |
| Spell attack rolls & save DCs (incl. flat overrides) | ✅ Resolved |
| Concentration | ✅ full lifecycle (C13) |
| Counterspell, Shield, Hellish Rebuke, Magic Missile interactions | ⚠️ Partial | Implemented, but as named special cases rather than data-driven rules; slot-gated and range-gated at drain time |
| Ritual casting | ⚠️ Partial | Out-of-combat via `resolve_ritual_cast`; in-combat rejected |
| Material components / component pouches | ⚠️ Partial | Metadata on `SpellCast`, not enforced |
| Dispel Magic | ❌ Not modelled | Inert (no mechanical activity) |
| Summoning / polymorph / enchant-a-weapon | ❌ Not modelled | The three activity kinds are narrative no-ops |

## Monsters

| Mechanic | Status | Notes |
|---|---|---|
| Typed action selection + built-in AI | ✅ Resolved | Targets lowest-HP living PC; three behavior profiles |
| Multiattack fan-out | ⚠️ Partial | Multiattacks with named/labelled tokens resolve precisely (C22 labelled every bare sibling token, fixing the five opaque-key monsters — bandit captain, doppelganger, chain devil, scout, ettin); "in any combination" clauses distribute range-aware. Conditional clauses ("uses X if …") and recharge/limited-use gating are not modelled (BACKLOG, C18). |
| Monster spellcasting | ❌ Not modelled | The monster AI never selects a `cast` action and its context carries an empty spell book |
| Flee / retreat behaviour | ⚠️ Partial | Zone-graph only; on a grid the monster holds still |
| **Legendary actions** | ❌ Not modelled | 30 monsters carry them in the data; no legendary action economy exists |
| **Lair actions** | ❌ Not modelled | Schema field exists; corpus ships none |
| Recharge (5–6) abilities | ❌ Not modelled | |
| Regeneration | ❌ Not modelled | |
| `special_abilities` | ⚠️ Partial | Typed as `MonsterTraitMechanic` on 14 trait names (C22); **Magic Resistance** grants save advantage against spells; the rest hydrate onto `Combatant.trait_mechanics` but are not consumed (C18) |
| Dataset categories `conditions/` + `traits/` | ✅ Resolved | 15 SRD 5.2 conditions with typed effects (`AssetLoader.get_condition`); de-duplicated monster traits (`get_trait`). The engine still enforces conditions from its Python registry (D3) |

## Characters

| Mechanic | Status | Notes |
|---|---|---|
| Class, subclass, level 1–20, species | ✅ Resolved | Subclass has no level-3 gate |
| Background | ❌ Not modelled | No `background_slug` on the build spec |
| HP, AC, hit dice, skill/save proficiencies | ❌ Host-supplied | The engine derives none of them; they arrive pre-computed on the party spec |
| Ability scores, proficiency, expertise | ⚠️ Partial | Proficient/expertise skill lists are caller-supplied, never derived. ASI/feat advancements are ignored. |
| Class/species feature activities (Rage, Second Wind, …) | ⚠️ Partial | Data-driven where the corpus carries a typed activity. Extra Attack is now read from granted feature slugs (C14: `extra-attack` / `two-extra-attacks` / `three-extra-attacks`, highest tier wins, never summed). **Still prose-only, so inert:** Fighting Style, Divine Smite, Metamagic, Invocations; `selected_choices` is never read |
| Weapon mastery (2024) | ✅ Resolved | All eight (C15): Graze, Topple, Vex, Sap, Slow, Push, Cleave, Nick. Push ignores the "Large or smaller" size gate (no creature-size attribute yet) |
| Sneak Attack | ✅ Resolved | Once per turn, ally-adjacency or advantage trigger |
| Short/long rest, hit dice, feature & item recharge | ✅ Resolved | Long Rest also restores Spellcasting/Pact Magic slots and reduces Exhaustion by 1; Short Rest restores only the Pact Magic pool |
| **Multiclassing** | ⚠️ Partial | `CharacterBuildSpec.classes` carrier + multiclass/Pact slot-table derivation (C17); per-class feature grants, proficiencies and HP accumulation are C19 |
| Feats | ⚠️ Partial | 1 of 17 corpus feats carries a mechanical activity |

## Reactions

Reactions work, with one constraint that shapes any host integration:

> **The engine never pauses mid-resolution to ask whether you want to react.**
> A creature must *pre-arm* its reaction on its own turn with a `"ready"`
> intent. The engine then fires it automatically when the trigger occurs.

| Reaction | Status |
|---|---|
| Opportunity attack | ✅ Resolved (both directions) |
| Shield (incl. vs. Magic Missile) | ✅ Resolved |
| Counterspell | ✅ Resolved — slot-gated at the readied level and 60 ft range/LoS-gated at drain time (an ineligible reactor's armed reaction is skipped, not popped) |
| Readied spell cast | ✅ Resolved — a readied leveled spell (e.g. Shield) needs an unexpended slot at its readied level; an ineligible reactor's armed reaction is skipped, not popped |
| Arbitrary SRD "Ready an action with a custom trigger" | ❌ Not modelled |

## Environment & exploration

Deliberately out of scope for a combat engine, and not modelled: falling damage,
suffocation, mounted combat, underwater combat, improvised weapons, object
interaction, and encumbrance.

## Event stream

Every call returns typed `CombatEvent`s.

`AttackRolled`, `SaveRolled`, `CheckRolled` and `ConcentrationCheck` all
carry the roll breakdown: `natural` (the die kept after advantage/disadvantage),
`modifier` (the flat bonus) and `sources` (which advantage/disadvantage sources
applied) — so a host can render "14 + 5 = 19". Two residual limits:

- The target's effective AC is not reported, so a miss cannot be explained as
  "vs AC 16"; and `modifier` excludes Bless/Bane-style bonus DICE, which must be
  rolled after the d20 to keep the seeded stream stable.
- `DamageApplied` carries no source/attacker id, so damage cannot be attributed.

`TurnPhase(phase, actor_id, round_number)` marks each turn boundary —
`round_start` / `turn_start` / `turn_end` — immediately before the engine runs
that phase's lifecycle hooks, so "top of round 3" and "end of Alice's turn" are
readable directly rather than inferred from `TurnStarted`/`TurnEnded` adjacency.

`ConcentrationCheck(target_id, dc, roll_total, succeeded, …)` is emitted for the
damage-triggered concentration save. Until v0.7 the legacy `SaveRolled` for the
same roll is emitted alongside it, so a host that counts saves must skip one of
the pair — see [the v0.5 → v0.6 migration guide](migration/v0.5-to-v0.6.md).

Every residual limit in that list is tracked in `BACKLOG.md`.
