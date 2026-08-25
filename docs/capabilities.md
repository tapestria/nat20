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
| Initiative order, rounds, turns | ✅ Resolved | Deterministic tie-break (initiative → dex → entity id) |
| Attack rolls, crits, damage, resistances/immunities/vulnerabilities | ✅ Resolved | |
| Saving throws, half-on-save, save-for-effect | ✅ Resolved | |
| Ability & skill checks (in and out of combat) | ✅ Resolved | `resolve_check`; seed via `CheckSpec.rng` |
| Action economy (action, bonus action, reaction, movement) | ✅ Resolved | |
| Dash, Dodge, Disengage, Hide, Help | ✅ Resolved | |
| Opportunity attacks | ✅ Resolved | Both directions (PC↔monster) |
| Death saves, stabilization, instant death | ✅ Resolved | |
| Concentration, incl. damage-triggered saves and cascade drop | ✅ Resolved | |
| Temporary HP, healing | ✅ Resolved | |
| Conditions (the 15 SRD conditions) | ⚠️ Partial | Applied/removed and gated by immunities; **mechanical effects are enforced only for the subset that projects into roll modifiers** |
| Exhaustion | ❌ Not modelled | Levels are tracked but apply no penalty; the text also still describes the 2014 ladder, not SRD 5.2 |
| Surprise | ❌ Not modelled | |
| Grapple / Shove | ❌ Not modelled | The `grappled` condition exists, but no contest resolves it |
| Two-weapon fighting | ❌ Not modelled | |
| Cover, line of sight | ✅ Resolved | Grid backend only — see below |
| Flanking | ❌ Not modelled | Not an SRD rule (optional variant) |

## Spatial

| Mechanic | Status | Notes |
|---|---|---|
| Zone-graph topology | ✅ Resolved | Weighted, undirected; shortest-path distance |
| 2-D grid, Chebyshev distance | ✅ Resolved | `GridScene`; one cell = `cell_size_ft` |
| Blocked cells, difficult terrain | ✅ Resolved | Difficult terrain doubles entry cost |
| Walls / line of sight | ✅ Resolved | Grid only; the zone backend always has clear sight |
| Cover (half / three-quarters / total) | ✅ Resolved | Grid only; folds into AC and Dexterity saves |
| AoE templates (sphere / cone / line) | ✅ Resolved | |
| **Multi-cell movement in one intent** | ❌ Not modelled | A `"move"` intent must name an **adjacent** cell. Crossing 30 ft = six `submit_player_intent` calls. `GridTopology.shortest_path` exists but the PC move handler does not use it. |
| Elevation / flying altitude | ❌ Not modelled | The grid is strictly 2-D |
| Multi-tile (Large+) creature footprints | ❌ Not modelled | Every creature occupies one cell |
| Threat-aware or cost-aware pathfinding | ❌ Not modelled | `shortest_path` is uniform-cost BFS |

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
| Spell slots, upcasting, at-will/innate casting | ✅ Resolved |
| Spell attack rolls & save DCs (incl. flat overrides) | ✅ Resolved |
| Concentration (one at a time, drop on failed save) | ✅ Resolved |
| Counterspell, Shield, Hellish Rebuke, Magic Missile interactions | ⚠️ Partial | Implemented, but as named special cases rather than data-driven rules |
| Ritual casting | ❌ Not modelled | 28 rituals flagged in the data; the flag is not read |
| Material components / component pouches | ❌ Not modelled | Components are in the data; never enforced |
| Dispel Magic | ❌ Not modelled | Inert (no mechanical activity) |
| Summoning / polymorph / enchant-a-weapon | ❌ Not modelled | The three activity kinds are narrative no-ops |

## Monsters

| Mechanic | Status | Notes |
|---|---|---|
| Typed action selection + built-in AI | ✅ Resolved | Targets lowest-HP living PC; three behavior profiles |
| Multiattack fan-out | ⚠️ Mostly | **119 of 180** multiattacks resolve to the exact SRD attack mix. The other 61 fall back to repeating one attack N times, logged at WARNING; 5 of those are heterogeneous and therefore wrong. |
| Monster spellcasting | ✅ Resolved | |
| Flee / retreat behaviour | ✅ Resolved | |
| **Legendary actions** | ❌ Not modelled | 30 monsters carry them in the data; no legendary action economy exists |
| **Lair actions** | ❌ Not modelled | Schema field exists; corpus ships none |
| Recharge (5–6) abilities | ❌ Not modelled | |
| Regeneration | ❌ Not modelled | |
| `special_abilities` | ❌ Not modelled | Carried by the schema, never consumed |

## Characters

| Mechanic | Status | Notes |
|---|---|---|
| Class, subclass, level 1–20, species, background | ✅ Resolved | |
| Ability scores, proficiency, expertise, saves | ✅ Resolved | |
| Class/species feature activities (Rage, Second Wind, …) | ✅ Resolved | Use-capped where the cap is a literal or `@scale` value |
| Weapon mastery (2024) | ✅ Resolved | |
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
suffocation, light/vision and obscurement (darkvision *is* projected onto
combatants but never consumed), mounted combat, underwater combat, improvised
weapons, object interaction, and encumbrance.

## Event stream

Every call returns typed `CombatEvent`s. Two known limits on what they carry:

- `AttackRolled` reports `roll_total` but not the natural d20, the attack bonus,
  or the target's AC — so a host cannot render "14 + 5 = 19 vs AC 16".
- `DamageApplied` carries no source/attacker id, so damage cannot be attributed.

Both are tracked in `BACKLOG.md`.
