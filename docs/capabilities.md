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
| Attack rolls, crits, damage, resistances/immunities/vulnerabilities | ⚠️ Partial | Advantage/disadvantage is rolled on **activity** attacks: attacker `flags.advantage.attack` / `flags.disadvantage.attack` effects plus the condition-derived sources (Invisible attacker; Blinded/Poisoned/Frightened/Restrained attacker; Paralyzed/Stunned/Unconscious/Blinded target), cancelling per SRD §Advantage and Disadvantage. **Opportunity attacks still roll flat `normal`** (pending C14). Prone (advantage within 5 ft, disadvantage beyond) and Grappled (disadvantage vs anyone but the grappler) are live (C12); the remaining distance-derived sources (unseen attacker, ranged-in-melee, long range) are still inert. Proficiency is assumed on every attack (pending C15). Magic weapons and spells overcome resistance to *nonmagical* B/P/S (`Weapon.magical`; host-authored resistances default to the nonmagical reading via `physical_resistances_nonmagical_only`). |
| Saving throws, half-on-save, save-for-effect | ✅ Resolved | Every save adds `d20 + ability modifier + proficiency bonus (if proficient)` for all six abilities, on all three paths (activity saves, the damage-triggered concentration check, the end-of-turn repeat save). Monster ability scores, save proficiencies and proficiency bonus hydrate from the `monster_template_slug`. The condition projections (auto-fail, Restrained DEX disadvantage, exhaustion's `-2 × level`) apply on all three paths (C12). **Not yet folded in:** effect-derived bonuses (Bless/Bane) on the two orchestrator-level paths. |
| Ability & skill checks (in and out of combat) | ✅ Resolved | `resolve_check`; seed via `CheckSpec.rng` |
| Action economy (action, bonus action, reaction, movement) | ⚠️ Partial | One action per turn; **Extra Attack / Action Surge are not modelled**. Incapacitated blocks action/bonus/reaction intents (C12). |
| Dash, Disengage | ✅ Resolved | |
| Dodge | ✅ Resolved | Attacker Disadvantage + Dexterity save Advantage until the start of your next turn; lost under Incapacitated or Speed 0. No "can see the attacker" check yet (no vision model). |
| Help | ✅ Resolved | Assist-an-attack-roll flavor only (the ability-check flavor has no check-advantage producer yet): the next ally attack against a target within 5 ft of the helper rolls with Advantage, consumed by that one attack roll (hit, miss, or cancelled to normal) and otherwise expiring at the start of the helper's own next turn. |
| Hide | ✅ Resolved | Gated on Three-Quarters/Total cover or Heavy obscurement on the hider's own cell (no "out of any enemy's line of sight" check yet — no vision model); on a successful DC 15 Dexterity (Stealth) check grants the Invisible condition, which ends the moment the hider makes an attack roll or casts a spell with a Verbal component. Touches no Action-economy budget (see BACKLOG.md). |
| Opportunity attacks | ✅ Resolved | Both directions (PC↔monster); same-zone reach approximation, no "can see" check |
| Death saves, stabilization | ✅ Resolved | |
| Instant death (massive damage) | ✅ Resolved | A Character whose damage remainder equals or exceeds their Hit Point maximum dies outright — `Death(reason="instant_kill")` (C12) |
| Concentration, incl. damage-triggered saves and cascade drop | ✅ Resolved | Damage save with real CON modifier + DC clamped to [10, 30]; one-at-a-time (a new concentration cast cascades the old drop); ends on death and Incapacitated-implying conditions; voluntary "drop_concentration" intent (no action cost); maximum-duration expiry from the typed spell duration at the caster's turn end. Magic Resistance on this path is C18. |
| Temporary HP, healing | ✅ Resolved | |
| Conditions (the 15 SRD conditions) | ⚠️ Partial | Applied/removed and gated by immunities (an immune creature never acquires the condition on either store). Enforced on the live path: attack-roll advantage/disadvantage for every SRD 5.2 row incl. Prone (distance-aware) and Grappled (grappler-aware); Incapacitated (and Paralyzed/Stunned/Petrified/Unconscious) rejects action/bonus/reaction intents with `IntentRejectedError("actor_incapacitated")` and skips reactions; Speed 0 (`MoveFailed(reason="speed_zero")`); auto-failed STR/DEX saves and Restrained DEX disadvantage on every save path; Paralyzed/Unconscious auto-crit within 5 ft; Charmed cannot attack or harmfully target the charmer (a charmed monster will not select them either); Characters fall Unconscious at 0 HP, including a Character hydrated into combat already at 0 HP (massive damage kills). **Partial because three SRD rows are still unenforced:** Frightened line-of-sight gate / can't-approach, Blinded/Deafened sense-based check auto-fail, Invisible's "can somehow see you" carve-out — each needs a seam another cluster owns (C16b). Incapacitated's initiative disadvantage closed via C14 Task 8 (2026-09-01) — `start_combat` rolls Initiative at Disadvantage for entities with a seeded incapacitated-implying `active_effects` status. See BACKLOG.md "Conditions — SRD 5.2 rows not enforced". |
| Exhaustion | ✅ Resolved | SRD 5.2: every D20 Test (attacks, saves incl. death saves, checks) is reduced by `2 × level`; Speed by `5 ft × level`. Level-6 death and Long-Rest recovery are C17. |
| Surprise | ✅ Resolved | `is_surprised=True` on a party/encounter spec (only consulted when that spec's `initiative` is `None`) imposes Disadvantage on the engine-rolled Initiative roll (C14 Task 8). Host is still responsible for deciding *who* is surprised. |
| Grapple / Shove | ❌ Not modelled | The `grappled` condition exists, but no contest resolves it |
| Two-weapon fighting | ❌ Not modelled | |
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
| Forced movement (push) | ✅ Resolved | `push_combatant` → `CombatantMoved(forced=True)`; wired for Thunderwave; Push mastery / Shove land in C15 / C14 |
| Vision and light (darkness, darkvision, blindsight, truesight, obscurement) | ⚠️ Partial | Grid only; `GridScene.lighting` / `obscurement_cells` + `GridTopology.can_see` feed the `unseen` attack advantage/disadvantage both ways; no light sources, no Blinded emission |

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
| Spell slots, upcasting, at-will/innate casting | ⚠️ Partial — upcasting scales dice only (not target count); **rests never restore slots**; no Pact Magic |
| Spell attack rolls & save DCs (incl. flat overrides) | ✅ Resolved |
| Concentration | ✅ full lifecycle (C13) |
| Counterspell, Shield, Hellish Rebuke, Magic Missile interactions | ⚠️ Partial | Implemented, but as named special cases rather than data-driven rules |
| Ritual casting | ❌ Not modelled | 28 rituals flagged in the data; the flag is not read |
| Material components / component pouches | ❌ Not modelled | Components are in the data; never enforced |
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
| Class/species feature activities (Rage, Second Wind, …) | ⚠️ Partial | Data-driven where the corpus carries a typed activity. **Prose-only, so inert:** Extra Attack, Fighting Style, Divine Smite, Metamagic, Invocations; `selected_choices` is never read |
| Weapon mastery (2024) | ⚠️ Partial | Graze and Topple only; the other six log and do nothing |
| Sneak Attack | ✅ Resolved | Once per turn, ally-adjacency or advantage trigger |
| Short/long rest, hit dice, feature & item recharge | ✅ Resolved | |
| **Multiclassing** | ❌ Not modelled | `CharacterBuildSpec` takes a single class |
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
| Counterspell | ⚠️ Partial — fires regardless of the 60 ft range limit |
| Readied spell cast | ⚠️ Partial — fires even with no slot available |
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
