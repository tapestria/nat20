# Nat20 — Backlog & Gap Inventory

Known gaps in the Nat20 libraries: the `dnd5e-engine` rules/combat engine and
the `dnd5e-srd-data` canonical SRD dataset. This is the single source of truth
for "what the engine does not yet do." It tracks **library** gaps only — host
application concerns (narrators, persistence, world state, UI) are out of scope.

**Update protocol:** when you close a gap, delete its entry in the same PR that
closes it. When you discover one, add it under the right section with a date and
a `packages/…` file anchor. Keep entries engine/data-centric — no host-app paths.

Anchors are current as of `dnd5e-engine` / `dnd5e-srd-data` **v0.2.0**.

---

# dnd5e-engine

## Spatial mechanics (grid backend is in place; these are additive)

- **Per-activity "ignores cover for save" flag.** SRD 5.2's Sacred Flame text
  ("The target gains no benefit from Half Cover or Three-Quarters Cover for
  this save") names a per-activity override that no canonical field backs
  today: `dnd5e_srd_data.schema.common.SaveBlock` carries only `ability`/`dc`,
  no boolean. Closed-2026-07-02 shrink of the former "Cover model" entry —
  `cover_between`, the AC fold, and the Dexterity-save fold all landed (see
  `packages/dnd5e-engine/src/dnd5e_engine/spatial.py::cover_between`,
  `activities/attack.py::resolve_attack`, `activities/save_primitive.py::roll_save`);
  only this per-activity carve-out remains, and it is a DATA-schema addition
  (`schema/feature.py`-style `advancement` field precedent — add a
  `SaveBlock.ignore_cover: bool` + translator support), not an engine gap.
  `packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/common.py` (`SaveBlock`).
- **Richer pathfinding.** `GridTopology.shortest_path` is uniform-cost BFS
  (`spatial.py`) — no threat-aware routing or multi-tile creatures. (Terrain
  COST is closed: `edge_distance` doubles entering a `difficult_terrain_cells`
  cell, consumed by `_handle_move`'s single-step budget check; `shortest_path`
  itself is not yet a cost-aware search over that cost, which is what
  "richer" now refers to.)

## Discovered during Cluster 6 review (2026-07-03)

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

## Discovered during Cluster 8 review (2026-07-03)

- **Weapon-mastery Topple bypasses `condition_immunities`.** C08's
  condition-immunity gate lives in `activities/effects.py::apply_activity_effects`,
  but `activities/mastery.py` (~line 199) is a second `ConditionApplied` emit
  site with no gate — a Topple-mastery hit still knocks a prone-immune target
  prone. Fix: factor the immunity check into a shared helper both emit sites
  call (grep-verified: exactly two emit sites today)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/mastery.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/effects.py`).

## Discovered during e2e catalog research (2026-07-02)

- **Weapon-tagged to-hit bonus sidecar never consumed.** The orchestrator's
  `_fold_active_effect_changes` folds a weapon-tagged (`applicable_action_types
  == ["attack"]`) `attack.roll.bonus` change into the
  `passive_weapon_to_hit_bonus` sidecar key, but nothing downstream reads it —
  `build_activity_context` only lifts the untagged `passive_to_hit_bonus` into
  `ActivityResolutionContext.passive_attack_bonus`. A +N weapon's to-hit bonus
  therefore never reaches the attack roll via this sidecar (the sibling
  damage-side gap, `passive_weapon_damage_bonus`, was closed in Cluster 2 —
  see `docs/migration/v0.1-to-v0.2.md`)
  (`packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py`,
  `packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py`).
- **Second, dead `condition_immunities` surface.** `dispatch.py` carries a
  host-owned condition-immunities path unused by live combat; a future
  `Combatant.condition_immunities` fix must not collide with it
  (`packages/dnd5e-engine/src/dnd5e_engine/dispatch.py`).
## Class / species feature mechanics

- **Attack-roll advantage/disadvantage on the live path (`activities/attack.py`).**
  Cluster 7 added attacker-side `flags.advantage.attack` / `flags.disadvantage.attack`
  *detection* (`attacker_advantage_flags`), but it currently only GATES the Sneak
  Attack trigger — the natural d20 still rolls `mode="normal"`. Rolling the base
  attack itself with advantage/disadvantage would shift the seeded dice stream and
  crit outcome (the C07-S01/S04 pinned per-scenario damage deltas isolate the
  Sneak Attack rider as the only delta, so they require the base roll to stay
  stream-invariant to the advantage flag). Wire the flag into `_roll_natural_d20`'s
  `mode`, plus the target-side producer (Faerie Fire granting attackers advantage —
  `rules/combat.py:459-471` already models it off-path), once a scenario exercises
  the base-roll delta directly. See `docs/migration/v0.1-to-v0.2.md`.
- **Unconsumed `system.bonuses.*` buckets (partial — Cluster 4 closed the
  attack/damage + spell.dc families).** `heal.*` and `abilities.check` /
  `abilities.skill` remain inert: no per-actor sidecar consumer exists for
  them today. `activities/heal.py::resolve_heal` never reads any bonus
  sidecar off `ActivityResolutionContext` (unlike `attack.py`'s
  `passive_*_damage_bonus` fields). `activities/check.py::resolve_check`
  reads a `ctx.check_modifiers[actor_id]["ability_mods"/"skills"]` sidecar,
  but `build_activity_context` always passes `check_modifiers={}` —
  `_fold_active_effect_changes` (`orchestrator.py`) has no branch that
  populates it from active-effect changes (only condition-derived
  projections land there). (`mwak`/`rwak`/`msak`/`rsak` attack+damage and
  `spell.dc` are now folded — see `docs/migration/v0.1-to-v0.2.md`.)

### Passive-stat projection (`activities/passive_stats.py`)

The interpreter now projects always-on `dr` (damage resistance), `di`
(immunity), `dv` (vulnerability), `ci` (condition immunity), `senses`, and
`movement` (walk-speed bonus + typed non-walk modes) at combat start, plus the
activation-gated Rage `dr` fold on the active-effect path (Cluster 8). One entry
of the spec-§D allowlist remains recognized-but-deferred for lack of a landing
zone + apply logic:

- **Ability scores, proficiency grants, `ac.calc`, languages** — each needs its
  own landing zone + apply logic (ability-modifier path, proficiency sets +
  roll-path consumer, AC recomputation, languages field). No Cluster 8 catalog
  scenario pins these; they stay deferred (routed to `skipped_keys`).

## Rest & recovery

- **Non-`@scale` symbolic feature-use caps fall back to uncapped** (2026-07-03,
  narrowed 2026-07-04, Cluster 9). `orchestrator.py::_feature_use_cap` now
  resolves a literal-integer `uses.max` exactly AND a `@scale.<owner>.<key>`
  max against the caster's real ScaleValue map (`build_scale_values`), so
  Second Wind caps at its true level-scaled value (3 at Fighter L5 via the
  `{1: 2, 4: 3, 10: 4}` table). The residual gap: a NON-`@scale` symbolic max
  — `@prof` (9 features), `max(1, @abilities.cha.mod)` / `5 * @classes.paladin.levels`
  (~6 more) — is not resolved and falls back to UNCAPPED rather than a wrong
  floor (a capped resource is never wrongly rejected; this preserves pre-C09
  behaviour for those features). Thread the caster's proficiency bonus / ability
  modifiers into the cap resolver to close it
  (`packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py`).
- **Non-literal feature-recovery formulas are unhandled** (2026-07-04,
  Cluster 9 fix round). `rest.recover_feature_uses` honours each feature's
  typed `uses.recovery` rules: `recoverAll` fully recharges, a literal-integer
  `formula` regains that many uses, and a period-miss (with recovery data
  supplied) correctly preserves `spent` (lr-only features do not recharge on a
  Short Rest). The residual: a NON-literal recovery formula (e.g. an
  `@abilities.*` expression) is not evaluated — the counter is left unchanged
  rather than guessed. Zero corpus occurrences today (a structural scan of
  `canonical/features` shows all 5 `formula` recovery entries are the literal
  `"1"`); thread roll-data evaluation through if such data ever lands
  (`packages/dnd5e-engine/src/dnd5e_engine/rest.py`).

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

# dnd5e-srd-data

No open entries.

---

# Test & fidelity

- **Real-Foundry parity fixtures.** Engine activity-resolution tests run against
  author-derived expected event streams, not byte-for-byte Foundry ground truth.
  Capturing ~12 parity fixtures (concentration cascades, multi-target ordering,
  forward/delayed activity composition) behind a Foundry license would replace
  the author-derived expectations. The fixture schema is already capture-ready
  (`{scenario_id, inputs, expected_events}`), so the swap is drop-in.
