# dnd5e-engine — coverage audit (Nat20 Plan 2, Task 6)

Bounded public-API coverage audit + backfill. The bound is **public-API
behaviors only** (a symbol in a module `__all__`): every such behavior must have
≥1 hermetic engine test, or be explicitly logged as deferred. Non-public
internals and host-only (Redis/PG/WS) concerns are out of scope and logged, not
built.

## Baseline

- Command:
  `uv run --with pytest-cov pytest -q --cov=dnd5e_engine --cov-report=term-missing`
  (run in `packages/dnd5e-engine`).
- **Before backfill:** 252 tests passed, **TOTAL coverage 73%**.
- **After backfill:** 263 tests passed, **TOTAL coverage 75%**.

Line coverage is NOT the target. Many low-coverage modules are internal helpers
(`activities/cast.py` 26%, `activities/check.py` 28%, `rules/resolution.py` 24%,
`rules/combat_helpers.py` 19%, etc.) — none of these declare an `__all__`, so
they are not public surface. They are exercised indirectly through the public
orchestrator path and through the host integration suite; their uncovered lines
are internal branches, not public-API gaps.

## Public surface enumerated

- Top-level `dnd5e_engine.__all__` (`src/dnd5e_engine/__init__.py`): 35 symbols.
- Submodule `__all__` lists: `orchestrator`, `check`, `specs`, `spatial`,
  `events`, `death_saves`, `dispatch`, `outcome`, `results`, `build_spec`,
  `build_party`, `types.*`, `lib_loader`, `testing`, `rules.*`, `activities`.

`tests/test_public_api_surface.py` already pins the surface shape (exact
top-level `__all__`; every public module declares `__all__`; every name
importable). The audit below covers *behavioral* coverage of those symbols.

## Step 2 — Tapestria integration mapping

19 integration files import `dnd5e_engine`
(`grep -rln dnd5e_engine .../backend/tests/integration/`). The behaviors they
assert split into:

- **Engine behaviors already covered by ported engine tests** (verified): combat
  start/attack/move/dash, bonus-action economy, weapon-reach range gate, passive
  resistances, USE_FEATURE (rage), skill-tier dispatch, combat-end outcome,
  grid topology, active-effect projection — covered by `test_orchestrator_*`,
  `test_combat_*`, `test_resolve_check*`, `test_grid_topology.py`,
  `test_get_actor_active_effects.py`, etc.
- **Host-only concerns (OUT OF SCOPE):** Redis projection
  (`test_orchestrator_redis_projection.py`), WS routing/broadcast
  (`test_orchestrator_ws_routing.py`, `test_ws_stability.py`), PG persistence
  (`test_combat_end_outcome_persistence.py`). These assert the host bridge, not
  engine behavior — not backfilled.

## Candidate gaps + dispositions

| Public symbol(s) | Module | Disposition |
|---|---|---|
| `roll_death_save`, `reset_death_saves`, `DeathSaveResult`, `DeathSaveOutcome` | `death_saves.py` | **backfilled-with-test** `tests/test_coverage_backfill_death_saves.py`. Module was 32% → 100%. Public death-save loop helper wired into orchestrator `_maybe_roll_death_save`; integration tests asserted the resulting `DeathSaveRolled` events only *through* the orchestrator + Redis projection (host-only). No ported engine test exercised the helper directly. Backfill covers all SRD outcomes: success, failure, nat-20 revive (HP=1, counters reset), nat-1 double-failure, third-success stabilize, third-failure death. |
| `UnknownHandleError`, `CombatSeamError`, `get_live`, `CombatHandle` | `orchestrator.py` | **backfilled-with-test** `tests/test_coverage_backfill_seam_errors.py`. Public seam error class + read accessor; integration `test_combat_pc_dash.py` / `test_combat_castfailed_reasons_via_ws.py` assert typed errors propagate, but no ported engine test raised them. Backfill covers the registry-miss verdict via `get_live`, `advance_monster_turn`, and `submit_player_intent`, plus the `UnknownHandleError ⊂ CombatSeamError` subclass contract. `get_live` line (UnknownHandleError raise) now covered. |
| `IntentRejectedError` — `"no_action_economy"` / `"not_actor_turn"` / `"combat_ended"` variants | `orchestrator.py` | **deferred-cross-store-only** (heavy live-combat setup). The error *class* is now covered (shares base `CombatSeamError` with the backfilled `UnknownHandleError`). The specific *rejection-reason* variants (orchestrator lines 712-745, 2446-2457, 3176-3180) require a fully-built live combat with exhausted action economy / wrong-turn actor; these are asserted by integration `test_combat_pc_dash.py` (`IntentRejectedError("no_action_economy")`) end-to-end. Re-deriving a full Dash/second-action flow hermetically is high-setup and brittle for marginal value; the reasons are plain literal strings, the class is covered, and the orchestrator turn-loop those branches sit in is exercised throughout the ported `test_orchestrator_*` suite. Logged as a follow-up, not built. |
| `dispatch.resolve_combat_action`, `DispatchContext`, `CombatResolverResult` | `dispatch.py` (70%) | **already-covered-by** `tests/test_get_actor_active_effects.py`, `tests/test_enchantment_sidecar_projection.py` (engine tests import + exercise the dispatch path). Uncovered `dispatch.py` lines (166-273, 286-322) are internal resolver branches, not unexercised public entry points. |
| `GridTopology`, `SpatialTopology`, `cell_id`, `parse_cell` (`spatial.py`) | `spatial.py` (95%) | **already-covered-by** `tests/test_grid_topology.py`, `tests/test_orchestrator_grid_combat.py`. |
| `drain_pending_events`, `narration_events`, `advance_monster_turn`, `submit_player_intent`, `start_combat`, `end_combat`, `get_actor_active_effects` | `orchestrator.py` | **already-covered-by** the ported `test_orchestrator_*` / `test_start_combat_*` / `test_end_combat_snapshot.py` / `test_use_feature_intent.py` suite (`drain_pending_events`/`get_live` are the standard event-draining idiom across 18 engine tests). |
| All `types.*`, `events`, `outcome`, `results`, `build_spec`, `build_party`, `check`, `specs`, `lib_loader`, `testing`, `rules.*` public symbols | various | **already-covered-by** existing ported tests + `test_public_api_surface.py` (importability/`__all__` shape) + their dedicated unit tests (`test_build_party.py`, `test_resolve_check*.py`, `test_types_smoke.py`, `test_rules_smoke.py`, `test_scale_resolver.py`, etc.). |

## Backfill summary

- `tests/test_coverage_backfill_death_saves.py` — 7 tests (death-save SRD loop).
- `tests/test_coverage_backfill_seam_errors.py` — 4 tests (unknown-handle seam errors).
- Net: +11 tests (252 → 263). `death_saves.py` 32% → 100%. TOTAL 73% → 75%.
- Idiom followed: real target module read first for exact signatures
  (`roll_death_save(combatant, rng)`, `submit_player_intent(handle, actor_id, intent)`,
  `PlayerIntent(intent_type=...)`); deterministic RNG via a fixed-`randint` stub;
  `Combatant` constructed per the existing `test_build_party.py` idiom; zero I/O.

## Stopping-condition confirmation

Every **public-API behavior** (symbol in a module `__all__`) now has ≥1 hermetic
engine test OR is explicitly logged deferred above. The single deferred item is
the `IntentRejectedError` *rejection-reason variant* (class covered; specific
reason strings deferred as cross-store/heavy-setup, asserted by Tapestria
integration `test_combat_pc_dash.py`). No host-only behavior (Redis/PG/WS) was
backfilled into the engine package. Bound respected: 2 backfill files, 11 tests.
