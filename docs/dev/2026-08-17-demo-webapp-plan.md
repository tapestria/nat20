# Nat20 Demo Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stateless, publicly deployable FastAPI + HTMX web demo (`apps/demo/`, distribution `nat20-demo`, never published) that plays five curated SRD combats by replaying a client-held command log through the public `dnd5e_engine` API on every request.

**Architecture:** The server holds zero state between requests. A fight is `{v, scenario_id, seed, commands[]}` held by the browser (localStorage + URL fragment). Every mutating request replays the full log from `start_combat(rng_seed=seed)`, applies the new command, returns HTMX fragment swaps plus the event delta, and discards the combat handle. Rests on the engine guarantee: same seed + same ordered commands ⇒ identical events.

**Tech Stack:** Python 3.12+, uv workspace, FastAPI, Jinja2, HTMX (vendored), pytest + httpx, ruff + mypy, Docker + Fly.io.

**Spec:** `docs/dev/2026-08-17-demo-webapp-design.md` — read it first; this plan implements it.

## Global Constraints

- The demo imports **only** names in `dnd5e_engine.__all__` (guarded by a test, Task 8). Task 1 adds the two missing names it needs.
- `requires-python = ">=3.12"`; `nat20-demo` is `private` (classifier `Private :: Do Not Upload`), never released to PyPI.
- No client-side rules logic: the browser stores the log and clicks server-rendered buttons; the engine is the sole authority (candidate move cells are geometric hints; the engine's rejection is handled gracefully).
- Log size hard cap: **500 commands** → HTTP 400 beyond it.
- Command schema is versioned: every log carries `"v": 1`.
- All new Python is ruff-clean (repo config), mypy-clean, and formatted with `uv run ruff format`.
- Branding: shell footer only — "Nat20 — an open-source 5e SRD engine · Built by the team behind [Tapestria](https://tapestria.app)". No other marketing copy.
- Prose says "5e"/"SRD", not "D&D"; keep the standard not-affiliated footer line (copy it from `examples/README.md`).
- All engine calls are async — demo test functions use `pytest.mark.asyncio` conventions matching the engine package (check `packages/dnd5e-engine/pyproject.toml` for `asyncio_mode`; mirror it in the demo's pyproject).

---

### Task 1: Export `drain_pending_events` and `IntentRejectedError` from the engine

The replay core needs (a) a non-blocking per-command event drain and (b) a typed rejection to catch. Both exist (`orchestrator.py:5318` `drain_pending_events`, `orchestrator.py:195` `IntentRejectedError`) but are not in the public `__all__`. This is a deliberate, minimal public-surface addition — the demo is the first standalone host to need the same seam Tapestria's WS bridge uses.

**Files:**
- Modify: `packages/dnd5e-engine/src/dnd5e_engine/__init__.py`
- Test: `packages/dnd5e-engine/tests/test_public_api_surface.py`

**Interfaces:**
- Produces: `dnd5e_engine.drain_pending_events(handle: CombatHandle) -> list[CombatEvent]` and `dnd5e_engine.IntentRejectedError` (attrs: `.reason: Literal["actor_not_in_initiative","not_actor_turn","combat_ended","no_action_economy"]`, `.detail: str`) — consumed by Task 3.

- [ ] **Step 1: Extend the exact-surface test**

In `tests/test_public_api_surface.py`, add `"drain_pending_events"` and `"IntentRejectedError"` to the `TOP_LEVEL` set (keep it alphabetically ordered — `IntentRejectedError` sorts with the capitals, `drain_pending_events` with the lowercase group).

- [ ] **Step 2: Run to verify it fails**

Run (from `packages/dnd5e-engine/`): `uv run pytest tests/test_public_api_surface.py -q`
Expected: FAIL — `test_top_level_surface_is_exact` reports the two names missing from `dnd5e_engine.__all__`.

- [ ] **Step 3: Export the names**

In `src/dnd5e_engine/__init__.py`: add `drain_pending_events` and `IntentRejectedError` to the existing `from dnd5e_engine.orchestrator import (...)` block, and insert both into `__all__` in alphabetical position.

- [ ] **Step 4: Run the full engine gate**

Run (from `packages/dnd5e-engine/`): `make check`
Expected: PASS (lint, format, mypy, coverage floor 73, bandit).

- [ ] **Step 5: Commit**

```bash
git add packages/dnd5e-engine/src/dnd5e_engine/__init__.py packages/dnd5e-engine/tests/test_public_api_surface.py
git commit -m "feat(engine): export drain_pending_events + IntentRejectedError for standalone hosts"
```

---

### Task 2: Scaffold the `apps/demo` workspace member

**Files:**
- Modify: `pyproject.toml` (root — workspace members)
- Create: `apps/demo/pyproject.toml`
- Create: `apps/demo/Makefile`
- Create: `apps/demo/src/nat20_demo/__init__.py`
- Test: `apps/demo/tests/__init__.py`, `apps/demo/tests/test_scaffold.py`

**Interfaces:**
- Produces: importable `nat20_demo` package; `make check` inside `apps/demo` running ruff + mypy + pytest. Later tasks add modules under `src/nat20_demo/`.

- [ ] **Step 1: Root workspace membership**

In root `pyproject.toml`, change `members = ["packages/*"]` to `members = ["packages/*", "apps/*"]`.

- [ ] **Step 2: Demo pyproject**

`apps/demo/pyproject.toml`:

```toml
[project]
name = "nat20-demo"
version = "0.1.0"
description = "Playable web demo of the dnd5e-engine + dnd5e-srd-data stack (never published)"
requires-python = ">=3.12"
classifiers = ["Private :: Do Not Upload"]
dependencies = [
    "dnd5e-engine",
    "fastapi>=0.115",
    "jinja2>=3.1",
    "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = [
    "httpx>=0.27",
    "mypy>=1.11",
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
]

[tool.uv.sources]
dnd5e-engine = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/nat20_demo"]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.mypy]
strict = true

[tool.ruff]
line-length = 100
```

Before writing, open `packages/dnd5e-engine/pyproject.toml` and copy its actual `[tool.ruff]`, `[tool.mypy]`, and pytest-asyncio settings so the demo matches repo convention exactly (the block above is the fallback if the engine has no divergent settings). If the engine pins a different asyncio mode or ruff rule set, mirror the engine.

- [ ] **Step 3: Makefile + package init**

`apps/demo/Makefile` (mirrors the engine's shape, minus bandit/coverage-floor):

```make
.PHONY: check lint format format-check type test
check: lint format-check type test
lint:
	uv run ruff check .
format:
	uv run ruff format .
format-check:
	uv run ruff format --check .
type:
	uv run mypy src/
test:
	uv run pytest -q
```

`apps/demo/src/nat20_demo/__init__.py`:

```python
"""nat20-demo — stateless web demo of the dnd5e-engine public API."""

__all__: list[str] = []
```

- [ ] **Step 4: Scaffold test**

`apps/demo/tests/__init__.py` (empty) and `apps/demo/tests/test_scaffold.py`:

```python
def test_package_imports() -> None:
    import nat20_demo

    assert nat20_demo.__all__ == []
```

- [ ] **Step 5: Sync and run the gate**

Run (from root): `uv sync --all-packages --all-extras`
Run (from `apps/demo/`): `make check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/demo
git commit -m "feat(demo): scaffold nat20-demo workspace member under apps/"
```

---

### Task 3: Replay core — command model + stateless replay + equivalence proof

The heart of the architecture. If replay-equivalence fails here, stop and report — the design is invalid (spec §Core architectural decision).

**Files:**
- Create: `apps/demo/src/nat20_demo/replay.py`
- Test: `apps/demo/tests/test_replay.py`

**Interfaces:**
- Consumes: `dnd5e_engine.start_combat / submit_player_intent / advance_monster_turn / end_combat / get_live / drain_pending_events / IntentRejectedError / PlayerIntent / PartyMemberSpec / EncounterMemberSpec / GridScene / CombatEvent / LiveCombatView / CombatOutcome`.
- Produces (used by Tasks 4–7):

```python
MAX_COMMANDS: int = 500

class IntentCommand(BaseModel):      # extra="forbid"
    t: Literal["intent"] = "intent"
    actor: str
    intent: PlayerIntent

class MonsterTurnCommand(BaseModel): # extra="forbid"
    t: Literal["monster_turn"] = "monster_turn"

Command = Annotated[IntentCommand | MonsterTurnCommand, Field(discriminator="t")]

class FightLog(BaseModel):           # extra="forbid"
    v: Literal[1] = 1
    scenario_id: str
    seed: int
    commands: list[Command] = Field(default_factory=list)

class LogTooLargeError(Exception): ...

@dataclass(frozen=True)
class ReplayOutcome:
    view: LiveCombatView            # snapshot BEFORE end_combat cleanup
    all_events: list[CombatEvent]   # open events + every applied command's events (+ close events when is_over)
    delta_events: list[CombatEvent] # events of the LAST applied command (open events when commands is empty)
    accepted: int                   # commands applied successfully
    rejected_reason: str | None     # e.g. "not_actor_turn: ..." for commands[accepted]; None if all applied
    is_over: bool                   # all foes dead or all PCs dead
    outcome: CombatOutcome | None   # projected outcome iff is_over

async def replay_fight(log: FightLog, party, encounter, grid) -> ReplayOutcome
def encode_log(log: FightLog) -> str      # urlsafe base64 of model_dump_json
def decode_log(raw: str) -> FightLog      # raises ValueError on garbage
```

`replay_fight` takes specs as arguments (not a scenario id) so this module has zero dependency on Task 4; the app layer looks the scenario up and passes fresh spec copies.

- [ ] **Step 1: Write the failing tests**

`apps/demo/tests/test_replay.py`. Use one minimal inline fixture (NOT a Task-4 scenario): a Hero (`ac=12, hp=20, attack_bonus=5, initiative=20, zone_id=cell_id(0, 0)`) vs a `goblin-warrior` (`monster_template_slug="goblin-warrior"`, `initiative=1, hp_current=7, hp_max=7, ac=13, zone_id=cell_id(1, 0)`, `xp_value=50`) on a `GridScene(width=6, height=6)`, seed `1337`. Helper:

```python
def hero_attack() -> Command:
    return IntentCommand(
        actor="char:hero",
        intent=PlayerIntent(intent_type="attack", target_id="mon:gob"),
    )
```

(The engine resolves an attack without `weapon_id` through the PC's `attack_bonus` fallback path — if the first run shows `attack_failed` events instead, check `packages/dnd5e-engine/tests/test_orchestrator_grid_combat.py` for the canonical minimal attack-intent shape and mirror it.)

Tests:

```python
SCRIPT = [hero_attack(), MonsterTurnCommand(), hero_attack(), MonsterTurnCommand(), hero_attack()]

def dumps(events):  # comparable, order-preserving projection
    return [e.model_dump() for e in events]

async def test_prefix_replays_compose():
    # replaying commands[:i] yields a strict prefix of replaying commands[:i+1]
    prev: list = []
    for i in range(len(SCRIPT) + 1):
        out = await replay_fight(make_log(SCRIPT[:i]), *fresh_specs())
        assert out.rejected_reason is None or i == len(SCRIPT)  # script may end the fight early
        assert dumps(out.all_events)[: len(prev)] == prev or out.is_over
        prev = dumps(out.all_events) if not out.is_over else prev

async def test_same_log_twice_is_identical():
    a = await replay_fight(make_log(SCRIPT[:3]), *fresh_specs())
    b = await replay_fight(make_log(SCRIPT[:3]), *fresh_specs())
    assert dumps(a.all_events) == dumps(b.all_events)
    assert a.view.tracked_hp == b.view.tracked_hp

async def test_different_seed_diverges():
    a = await replay_fight(make_log(SCRIPT[:1], seed=1337), *fresh_specs())
    b = await replay_fight(make_log(SCRIPT[:1], seed=1338), *fresh_specs())
    assert dumps(a.all_events) != dumps(b.all_events)  # attack roll totals differ

async def test_delta_is_last_command_events():
    two = await replay_fight(make_log(SCRIPT[:2]), *fresh_specs())
    one = await replay_fight(make_log(SCRIPT[:1]), *fresh_specs())
    assert dumps(one.all_events) + dumps(two.delta_events) == dumps(two.all_events)

async def test_rejected_command_stops_at_prefix():
    # Hero acts on the goblin's turn: command 1 is a second hero intent right
    # after `hero_attack()` already ended the hero's turn.
    out = await replay_fight(make_log([hero_attack(), hero_attack()]), *fresh_specs())
    assert out.accepted == 1
    assert out.rejected_reason is not None and "not_actor_turn" in out.rejected_reason

async def test_empty_log_renders_opening_state():
    out = await replay_fight(make_log([]), *fresh_specs())
    assert out.accepted == 0 and not out.is_over
    assert any(e.type == "round_started" for e in out.all_events)
    assert out.delta_events == out.all_events

async def test_log_cap_enforced():
    with pytest.raises(LogTooLargeError):
        await replay_fight(make_log([MonsterTurnCommand()] * 501), *fresh_specs())

def test_encode_decode_roundtrip():
    log = make_log(SCRIPT[:2])
    assert decode_log(encode_log(log)) == log

def test_decode_garbage_raises():
    with pytest.raises(ValueError):
        decode_log("not-base64!!")
```

`fresh_specs()` must return **newly constructed** spec models each call (never share model instances across replays). `make_log(commands, seed=1337)` builds a `FightLog(scenario_id="test", ...)`.

- [ ] **Step 2: Run to verify failure**

Run (from `apps/demo/`): `uv run pytest tests/test_replay.py -q`
Expected: FAIL — `nat20_demo.replay` does not exist.

- [ ] **Step 3: Implement `replay.py`**

```python
async def replay_fight(log, party, encounter, grid):
    if len(log.commands) > MAX_COMMANDS:
        raise LogTooLargeError(f"{len(log.commands)} commands > cap {MAX_COMMANDS}")
    start = await start_combat(
        session_id=f"demo:{uuid.uuid4().hex}",
        party=party, encounter=encounter, grid_scene=grid, rng_seed=log.seed,
    )
    handle = start.handle
    try:
        all_events: list[CombatEvent] = list(start.events)
        delta_start = 0            # index into all_events where the last command's events begin
        accepted, rejected_reason = 0, None
        for cmd in log.commands:
            marker = len(all_events)
            try:
                if isinstance(cmd, IntentCommand):
                    await submit_player_intent(handle, actor_id=cmd.actor, intent=cmd.intent)
                else:
                    await advance_monster_turn(handle)
            except IntentRejectedError as exc:
                all_events.extend(drain_pending_events(handle))
                rejected_reason = f"{exc.reason}: {exc.detail}"
                break
            all_events.extend(drain_pending_events(handle))
            delta_start, accepted = marker, accepted + 1
            if _is_over(get_live(handle)):
                break              # further commands are unreachable; treat as trailing junk? No —
                                   # a well-formed client never sends them; if present they are
                                   # simply not applied and rejected_reason stays None.
        view = get_live(handle)
        is_over = _is_over(view)
        end = await end_combat(handle)          # always: cleanup + registry removal
        outcome = None
        if is_over:
            all_events.extend(end.events)       # CombatEnded with the real reason
            outcome = end.outcome
        return ReplayOutcome(view=view, all_events=all_events,
                             delta_events=all_events[delta_start:], accepted=accepted,
                             rejected_reason=rejected_reason, is_over=is_over, outcome=outcome)
    except LogTooLargeError:
        raise
    except Exception:
        # ensure no leaked registry entry on unexpected engine errors
        with contextlib.suppress(Exception):
            await end_combat(handle)
        raise

def _is_over(view: LiveCombatView) -> bool:
    return (view.encounter_ids <= view.dead_ids) or (view.party_ids <= view.dead_ids)
```

Note the try wraps everything after `start_combat` — restructure into `try/except` around the loop with the cleanup `end_combat` in the success path as shown (do NOT use `finally` for the success-path `end_combat`; it must run before the return so `end.events` can be folded in). `encode_log`/`decode_log`: `base64.urlsafe_b64encode(log.model_dump_json().encode()).decode()` and the reverse with `FightLog.model_validate_json`; wrap `binascii.Error`/`ValidationError` into `ValueError`.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_replay.py -q`
Expected: PASS. If `test_prefix_replays_compose` or `test_same_log_twice_is_identical` fails on event mismatches, that is a **determinism break in the engine** — STOP, capture the two event dumps' first divergence, and report to the human partner before any further task.

- [ ] **Step 5: Gate + commit**

Run: `make check` (from `apps/demo/`)

```bash
git add apps/demo/src/nat20_demo/replay.py apps/demo/tests/test_replay.py
git commit -m "feat(demo): stateless replay core with equivalence proof"
```

---

### Task 4: Scenario catalog — five curated encounters

**Files:**
- Create: `apps/demo/src/nat20_demo/scenarios.py`
- Test: `apps/demo/tests/test_scenarios.py`

**Interfaces:**
- Consumes: Task 3's `replay_fight`, `FightLog`, `IntentCommand`, `MonsterTurnCommand`; engine spec types.
- Produces:

```python
class ActionOption(BaseModel):
    label: str                     # "Attack — Longsword"
    intent: PlayerIntent           # template; target_id filled per living foe at render time
    needs_target: bool = False     # expand into one button per living enemy
    # movement is NOT an ActionOption — the grid renders candidate move cells directly

class Scenario(BaseModel):
    id: str
    title: str
    tagline: str                   # one sentence for the catalog card
    proves: str                    # the engine subsystem this scenario demonstrates
    default_seed: int
    party: list[PartyMemberSpec]
    encounter: list[EncounterMemberSpec]
    grid: GridScene
    actions: dict[str, list[ActionOption]]   # PC entity_id -> options

def get_scenario(scenario_id: str) -> Scenario          # raises KeyError
def all_scenarios() -> list[Scenario]                   # catalog order
def fresh_specs(s: Scenario) -> tuple[list[PartyMemberSpec], list[EncounterMemberSpec], GridScene]
    # deep model_copy of every spec — replay must never see shared mutable instances
```

- [ ] **Step 1: Verify dataset slugs before authoring**

Run: `ls packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/monsters/ | grep -E "goblin-warrior|goblin-boss|skeleton|zombie|wolf|giant-rat|bandit"` and `ls .../canonical/spells/ | grep -E "burning-hands|hold-person|cure-wounds|healing-word|bless|magic-missile"` and `ls .../canonical/items/ | grep -E "longsword|shortbow|dagger|mace|spear"`. All scenario slugs below must appear in the output; substitute the nearest real slug for any miss.

- [ ] **Step 2: Write the failing tests**

`apps/demo/tests/test_scenarios.py`:

```python
async def test_every_scenario_opens_and_replays_empty_log():
    for s in all_scenarios():
        out = await replay_fight(FightLog(scenario_id=s.id, seed=s.default_seed), *fresh_specs(s))
        assert out.accepted == 0 and not out.is_over

async def test_scenario_scripts_run_without_rejection():
    for s in all_scenarios():
        script = SHOWCASE_SCRIPTS[s.id]
        out = await replay_fight(
            FightLog(scenario_id=s.id, seed=s.default_seed, commands=script), *fresh_specs(s)
        )
        assert out.rejected_reason is None, f"{s.id}: {out.rejected_reason}"
        got = {e.type for e in out.all_events}
        assert PROOF_EVENTS[s.id] <= got, f"{s.id} missing {PROOF_EVENTS[s.id] - got}"

async def test_replay_equivalence_across_all_scenarios():
    for s in all_scenarios():
        log = FightLog(scenario_id=s.id, seed=s.default_seed, commands=SHOWCASE_SCRIPTS[s.id])
        a = await replay_fight(log, *fresh_specs(s))
        b = await replay_fight(log, *fresh_specs(s))
        assert [e.model_dump() for e in a.all_events] == [e.model_dump() for e in b.all_events]

def test_fresh_specs_returns_new_instances():
    s = all_scenarios()[0]
    p1, _, _ = fresh_specs(s)
    p2, _, _ = fresh_specs(s)
    assert p1[0] is not p2[0]
```

`PROOF_EVENTS` pins each scenario to its subsystem (subsets of `CombatEvent.type` literals):

```python
PROOF_EVENTS = {
    "goblin-ambush":  {"attack_rolled", "damage_applied"},
    "burning-hands":  {"save_rolled", "damage_applied"},
    "hold-the-line":  {"effect_applied", "concentration_check"},
    "marsh-crossing": {"actor_moved", "dash_taken", "attack_rolled"},
    "last-stand":     {"healing_applied", "death_save_rolled"},
}
```

`SHOWCASE_SCRIPTS` lives in the test module. Author each script by running a small REPL loop (script prints `view` + last delta after each command) and choosing commands a player would; tune `default_seed` (search seeds 1..200) until every `PROOF_EVENTS` entry fires without rejection. This curation is expected to take iteration — the test is the acceptance record of the result.

- [ ] **Step 3: Implement the five scenarios**

Author in `scenarios.py` as module-level constructor functions (`def _goblin_ambush() -> Scenario:`) registered in an ordered dict. Full first scenario (pattern for the rest):

```python
def _goblin_ambush() -> Scenario:
    return Scenario(
        id="goblin-ambush",
        title="Goblin Ambush",
        tagline="Two heroes, three goblins, a wall to hide behind.",
        proves="Attack rolls, AC, cover folding into AC, grid movement and walls.",
        default_seed=1337,
        party=[
            PartyMemberSpec(
                entity_id="char:brynn", name="Brynn", initiative=18,
                hp_current=24, hp_max=24, ac=16, attack_bonus=5,
                strength=16, dexterity=12, constitution=14,
                zone_id=cell_id(1, 4), equipment=("longsword",), character_level=3,
            ),
            PartyMemberSpec(
                entity_id="char:sera", name="Sera", initiative=14,
                hp_current=18, hp_max=18, ac=14, attack_bonus=5,
                strength=10, dexterity=16, constitution=12,
                zone_id=cell_id(0, 6), equipment=("shortbow",), character_level=3,
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id=f"mon:gob{i}", entity_type="Monster", name=f"Goblin {i}",
                initiative=init, hp_current=10, hp_max=10, ac=13, dexterity=14,
                monster_template_slug="goblin-warrior", xp_value=50,
                zone_id=cell_id(col, row),
            )
            for i, (init, col, row) in enumerate([(12, 8, 3), (9, 9, 5), (7, 8, 7)], start=1)
        ],
        grid=GridScene(
            width=12, height=10,
            wall_segments=[WallSegment(x1=6, y1=2, x2=6, y2=5)],
            cover_cells={cell_id(6, 6): "half"},
            blocked_cells=[cell_id(5, 0), cell_id(5, 1)],
        ),
        actions={
            "char:brynn": [
                ActionOption(label="Attack — Longsword",
                             intent=PlayerIntent(intent_type="attack", weapon_id="longsword"),
                             needs_target=True),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:sera": [
                ActionOption(label="Attack — Shortbow",
                             intent=PlayerIntent(intent_type="attack", weapon_id="shortbow"),
                             needs_target=True),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )
```

The other four, same structure (author fully; key deltas only listed here):

- **`burning-hands`** ("Burning Hands at the Bottleneck") — proves AoE save spells: per-target Dex saves, half on save, slot spend. Party: a wizard (`spell_slots={1: 2}`, `spells_known=["burning-hands", "magic-missile"]`, `character_level=3`) + a spear fighter. Encounter: four `giant-rat`s clustered in a 2×2 corridor mouth behind `blocked_cells` forming the bottleneck. Actions include `ActionOption(label="Burning Hands", intent=PlayerIntent(intent_type="cast_spell", spell_id="burning-hands", slot_level=1), needs_target=True)`. **Before finalizing:** grep the engine's own tests for how an AoE cast is targeted (`grep -rn "burning-hands\|cast_spell" packages/dnd5e-engine/tests/ | head`) and mirror that intent shape exactly (target_id vs target_zone_id); adjust `needs_target` semantics in Task 6's renderer if it proves to be cell-targeted.
- **`hold-the-line`** — proves conditions/effects + concentration held and broken. Party: a cleric (`spells_known=["hold-person", "bless", "cure-wounds"]`, `spell_slots={1: 3, 2: 2}`) + a mace fighter. Encounter: two `bandit`s + one `bandit-captain` (the captain's hits break the cleric's concentration). Script casts `hold-person` (concentration `effect_applied`), then lets a monster turn damage the cleric (`concentration_check`).
- **`marsh-crossing`** — proves difficult terrain, dash, ranged at range, terrain cover. `GridScene(width=14, height=8, difficult_terrain_cells=[...a marsh band of ~12 cells across columns 5–8...], cover_cells={...two reed clumps: "half"...})`. Party: two archers with shortbows. Encounter: three `zombie`s shambling from the far edge. Script includes `move` intents into difficult terrain (budget halving visible), a `dash` intent, ranged attacks.
- **`last-stand`** — proves healing, temp HP, death saves, dramatic near-loss. Party: a battered fighter (`hp_current=9, hp_max=28`) + a healer (`spells_known=["healing-word", "cure-wounds"]`, `spell_slots={1: 2}`). Encounter: one `skeleton` + two `wolf`s. Seed tuned so the fighter drops (death saves roll) and healing brings them back; victory at low HP.

`fresh_specs`:

```python
def fresh_specs(s: Scenario):
    return (
        [p.model_copy(deep=True) for p in s.party],
        [e.model_copy(deep=True) for e in s.encounter],
        s.grid.model_copy(deep=True),
    )
```

- [ ] **Step 4: Iterate scripts/seeds until green**

Run: `uv run pytest tests/test_scenarios.py -q` — iterate scenario data, scripts, and seeds until PASS. Never weaken a `PROOF_EVENTS` set to pass; change the script/seed/scenario instead.

- [ ] **Step 5: Gate + commit**

Run: `make check` (from `apps/demo/`)

```bash
git add apps/demo/src/nat20_demo/scenarios.py apps/demo/tests/test_scenarios.py
git commit -m "feat(demo): five curated scenarios with subsystem proof scripts"
```

---

### Task 5: Renderers — engine state/events → template contexts

**Files:**
- Create: `apps/demo/src/nat20_demo/render.py`
- Test: `apps/demo/tests/test_render.py`

**Interfaces:**
- Consumes: `LiveCombatView`, `CombatEvent`, `parse_cell`, `cell_id`, Task 4's `Scenario`/`ActionOption`, Task 3's `ReplayOutcome`, `encode_log`.
- Produces (all plain dict/list contexts, consumed by Task 6/7 templates):

```python
def grid_context(scenario, out: ReplayOutcome) -> dict
# {"width", "height", "cells": [{"col","row","cell_id","kind": "floor|blocked|difficult|cover_half|cover_three_quarters|cover_total",
#   "token": {"entity_id","name","side": "pc|foe","dead": bool,"current": bool} | None,
#   "move_candidate": bool}]}
def initiative_context(out) -> list[dict]      # [{"entity_id","name","side","dead","current"}]
def status_context(scenario, out) -> list[dict]# [{"entity_id","name","hp","hp_max","temp_hp","conditions": [...],
                                               #   "slots": {level: n}, "concentrating": bool}]
def actions_context(scenario, out) -> dict
# {"mode": "pc_turn"|"monster_turn"|"over",
#  "actor": {...} | None,
#  "options": [{"label", "command_json"}],   # needs_target expanded per living foe
#  "rejected": str | None}
def tape_lines(events: list[CombatEvent], names: dict[str, str]) -> list[dict]
# [{"kind": event.type, "text": friendly one-liner, "raw": json string}]
```

- [ ] **Step 1: Write the failing tests**

Drive each renderer from a real `ReplayOutcome` (goblin-ambush, empty log, plus a two-command log):

```python
async def test_grid_marks_tokens_and_terrain(): ...   # hero token at its cell, wall cells rendered, blocked flagged
async def test_move_candidates_only_on_pc_turn(): ... # empty log (Brynn's turn): candidate cells within base_speed
                                                      # Chebyshev distance, excluding blocked + occupied
async def test_actions_expand_targets(): ...          # "Attack — Longsword" appears once per LIVING goblin,
                                                      # command_json parses back into a valid IntentCommand
async def test_actions_monster_turn_mode(): ...       # after a script that ends the PC round → mode == "monster_turn"
async def test_tape_friendly_lines(): ...             # attack_rolled renders "Brynn attacks Goblin 1 — 17 vs AC: hit";
                                                      # unknown/other events fall back to "type + payload" and never raise
async def test_status_tracks_hp_and_slots(): ...
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_render.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

Key logic:

- `grid_context`: iterate `range(height) × range(width)`; classify cell kind from `GridScene` fields; place tokens from `out.view.actor_zone` (name/side from scenario specs; `dead` from `view.dead_ids`; `current` = `view.initiative[view.current_turn_index].entity_id`). Move candidates: only when the current actor is a PC and `not out.is_over` — cells with `chebyshev(actor_cell, cell) * grid.cell_size_ft <= actor base_speed`, not blocked, not occupied. Use `parse_cell` for coordinates. This is a geometric HINT — the engine remains authority; a rejected move renders through the Task 7 rejection path.
- `actions_context`: current actor from initiative; PC → look up `scenario.actions[actor_id]`; `needs_target=True` options expand to one entry per living encounter member with `intent.model_copy(update={"target_id": foe_id})`; each entry's `command_json` = `IntentCommand(actor=actor_id, intent=...).model_dump_json()`. Monster current → `mode="monster_turn"` with the single command `MonsterTurnCommand().model_dump_json()`. `out.is_over` → `mode="over"`.
- `tape_lines`: a `_FRIENDLY: dict[str, Callable[[CombatEvent, dict[str, str]], str]]` table covering at least `attack_rolled, save_rolled, damage_applied, healing_applied, temphp_applied, effect_applied, condition_applied, concentration_check, concentration_dropped, death_save_rolled, unconscious, death, actor_moved, dash_taken, turn_started, round_started, cast_failed, attack_failed, combat_ended`; every other type falls back to `f"{e.type}: {e.model_dump()}"`. `raw` = `json.dumps(e.model_dump(), default=str)`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_render.py -q` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add apps/demo/src/nat20_demo/render.py apps/demo/tests/test_render.py
git commit -m "feat(demo): pure renderers from engine views/events to template contexts"
```

---

### Task 6: App shell — catalog page + play page (GET routes, templates, CSS)

**Files:**
- Create: `apps/demo/src/nat20_demo/app.py`
- Create: `apps/demo/src/nat20_demo/templates/` — `shell.html`, `catalog.html`, `play.html`, `about.html`, and partials `_grid.html`, `_initiative.html`, `_status.html`, `_actions.html`, `_tape.html`, `_outcome.html`
- Create: `apps/demo/src/nat20_demo/static/style.css`, `static/htmx.min.js` (vendored, pinned release), `static/log.js`
- Test: `apps/demo/tests/test_routes.py`

**Interfaces:**
- Consumes: Tasks 3–5 surfaces.
- Produces: `create_app() -> FastAPI` (used by Task 7 tests and the Task 9 Docker entrypoint `uvicorn nat20_demo.app:app`); module-level `app = create_app()`. Routes: `GET /`, `GET /play/{scenario_id}` (query `seed: int | None`, `log: str | None`), `GET /about`, `GET /static/*`.

- [ ] **Step 1: Vendor HTMX**

Download the current htmx 2.x `htmx.min.js` release into `static/` and record the exact version in a one-line comment at the top of `app.py`. No CDN at runtime.

- [ ] **Step 2: Write the failing route tests**

```python
@pytest.fixture
def client():
    from httpx import ASGITransport, AsyncClient
    from nat20_demo.app import create_app
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://demo")

async def test_catalog_lists_all_scenarios(client): ...      # 200; every scenario title + `proves` text present
async def test_play_empty_log_renders_board(client): ...     # GET /play/goblin-ambush → 200; grid cells, initiative
                                                             # rail, action buttons for Brynn present
async def test_play_with_log_param_renders_replayed_state(client): ...  # encode a 1-command log; tape shows the attack
async def test_play_unknown_scenario_404(client): ...        # friendly page, link back to catalog
async def test_play_malformed_log_400(client): ...           # log="!!!" → 400 friendly page
async def test_about_has_attribution(client): ...            # footer string present
```

- [ ] **Step 3: Run to verify failure**, then implement.

`app.py` essentials:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Nat20 demo")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    # GET /            -> catalog.html with all_scenarios()
    # GET /play/{sid}  -> resolve scenario (KeyError -> 404 page); log = decode_log(param) if given
    #                     else FightLog(scenario_id=sid, seed=seed or scenario.default_seed)
    #                     (ValueError -> 400 page); out = await replay_fight(log, *fresh_specs(s))
    #                     render play.html with all five region contexts + encoded canonical log
    # GET /about       -> about.html
    return app

app = create_app()
```

Template shapes (`shell.html` holds `<head>` with `style.css`, `htmx.min.js`, `log.js`, and the footer attribution + not-affiliated line; pages extend it):

`play.html` composes the board and carries the state the client persists:

```html
{% extends "shell.html" %}
{% block content %}
<main class="board" data-scenario="{{ scenario.id }}">
  <input type="hidden" id="fight-log" name="log" value="{{ encoded_log }}">
  <input type="hidden" id="fight-seed" name="seed" value="{{ seed }}">
  <section id="grid">{% include "_grid.html" %}</section>
  <aside id="initiative">{% include "_initiative.html" %}</aside>
  <aside id="status">{% include "_status.html" %}</aside>
  <section id="actions">{% include "_actions.html" %}</section>
  <section id="tape"><ol id="tape-lines">{% include "_tape.html" %}</ol></section>
</main>
{% endblock %}
```

`_grid.html` — CSS grid; every move-candidate cell is itself the move button:

```html
<div class="grid" style="--cols: {{ grid.width }}; --rows: {{ grid.height }};">
  {% for cell in grid.cells %}
  <div class="cell {{ cell.kind }}{% if cell.move_candidate %} candidate{% endif %}">
    {% if cell.move_candidate %}
    <button class="move-btn"
            hx-post="/play/{{ scenario.id }}/act" hx-include="#fight-log,#fight-seed"
            hx-vals='{"command": {{ cell.move_command_json | tojson }}}'
            hx-target="#tape-lines" hx-swap="beforeend"
            title="Move to {{ cell.cell_id }}"></button>
    {% endif %}
    {% if cell.token %}
    <span class="token {{ cell.token.side }}{% if cell.token.dead %} dead{% endif %}{% if cell.token.current %} current{% endif %}">
      {{ cell.token.name[:2] }}
    </span>
    {% endif %}
  </div>
  {% endfor %}
</div>
```

(`grid_context` gains a `move_command_json` field per candidate cell in this task — `IntentCommand(actor=current_pc, intent=PlayerIntent(intent_type="move", target_zone_id=cell_id)).model_dump_json()`; add a renderer test for it.)

`_actions.html` — one button per expanded option, same `hx-post`/`hx-include` pattern with `hx-vals` carrying `command`; monster mode renders the single "Resolve monster turn" button; `over` mode includes `_outcome.html` (ended_reason, XP awards, residual party HP, "Play again" link to `/play/{{ scenario.id }}?seed={{ seed }}`, "Copy permalink" button handled by `log.js`).

`_tape.html` renders `{% for line in tape %}<li class="ev ev-{{ line.kind }}"><span>{{ line.text }}</span><details><summary>raw</summary><pre>{{ line.raw }}</pre></details></li>{% endfor %}`.

`style.css`: single dark-parchment theme; `.grid { display: grid; grid-template-columns: repeat(var(--cols), 2.2rem); }`; distinct fills for `blocked/difficult/cover_*`; `.token.pc`/.`token.foe` colored discs, `.current` ring, `.dead` desaturated; tape as a monospace scrolling column. ~150 lines, no framework.

`log.js` (whole file, this is the entire client):

```js
// Persist the canonical fight log the server returns after every action.
function persistLog() {
  const el = document.getElementById("fight-log");
  const seed = document.getElementById("fight-seed");
  if (!el || !el.value) return;
  const scenario = document.querySelector("main.board")?.dataset.scenario;
  if (!scenario) return;
  localStorage.setItem("nat20:" + scenario, el.value);
  const h = "#s=" + scenario + "&seed=" + seed.value + "&log=" + el.value;
  history.replaceState(null, "", h);
}
document.addEventListener("htmx:afterSwap", persistLog);
document.addEventListener("DOMContentLoaded", persistLog);
document.addEventListener("click", (e) => {
  if (e.target.id !== "copy-permalink") return;
  const u = new URL(window.location);
  u.searchParams.set("log", document.getElementById("fight-log").value);
  u.hash = "";
  navigator.clipboard.writeText(u.toString());
});
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_routes.py -q` → PASS. Then eyeball it live: `uv run uvicorn nat20_demo.app:app --reload` (from `apps/demo/`), open `http://127.0.0.1:8000`, click through goblin-ambush's opening state.

- [ ] **Step 5: Gate + commit**

```bash
git add apps/demo/src/nat20_demo apps/demo/tests/test_routes.py
git commit -m "feat(demo): app shell — catalog + play pages, templates, vendored htmx"
```

---

### Task 7: Act endpoint — apply a command, OOB fragment bundle, error paths

**Files:**
- Modify: `apps/demo/src/nat20_demo/app.py`
- Create: `apps/demo/src/nat20_demo/templates/_act_response.html`, `templates/_rejection.html`
- Test: `apps/demo/tests/test_act_route.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `POST /play/{scenario_id}/act` — form fields `seed: int`, `log: str` (b64), `command: str` (JSON of one `Command`). Response: HTML fragment — new tape `<li>`s as the direct swap target, plus `hx-swap-oob` replacements for `#grid`, `#initiative`, `#status`, `#actions`, `#fight-log`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_act_applies_command_and_returns_fragments(client):
    # empty-log goblin-ambush + Brynn attack command → 200; response contains
    # hx-swap-oob="true" fragments for grid/actions and new tape lines with attack_rolled;
    # the returned #fight-log value decodes to a 1-command log.
async def test_act_appends_to_existing_log(client): ...      # send a 1-command log + next command → decoded value has 2
async def test_act_rejected_command_returns_prefix_state(client):
    # send a wrong-turn command → 200; _rejection.html content names the reason;
    # returned #fight-log is UNCHANGED (rejected command not appended).
async def test_act_malformed_command_400(client): ...
async def test_act_oversized_log_400(client): ...            # 501 monster_turn commands
async def test_act_after_combat_over_shows_outcome(client):  # replay a full showcase script via /act once more
    ...                                                      # → actions region is the outcome card
```

- [ ] **Step 2: Run to verify failure**, then implement.

Handler: decode + validate (`ValueError` → 400 fragment; `LogTooLargeError` → 400), parse `command` via the `Command` discriminated union (pydantic `TypeAdapter(Command).validate_json`), append to `log.commands`, `replay_fight`. If `out.rejected_reason` is set AND `out.accepted == len(original_commands)` (i.e. the NEW command was the rejected one): respond with the prefix state, `_rejection.html` inside the actions region, and the **original** log in `#fight-log`. Otherwise respond with the applied state and the grown log. `_act_response.html`:

```html
{% for line in tape %}<li class="ev ev-{{ line.kind }}"><span>{{ line.text }}</span><details><summary>raw</summary><pre>{{ line.raw }}</pre></details></li>{% endfor %}
<section id="grid" hx-swap-oob="true">{% include "_grid.html" %}</section>
<aside id="initiative" hx-swap-oob="true">{% include "_initiative.html" %}</aside>
<aside id="status" hx-swap-oob="true">{% include "_status.html" %}</aside>
<section id="actions" hx-swap-oob="true">{% include "_actions.html" %}</section>
<input type="hidden" id="fight-log" name="log" value="{{ encoded_log }}" hx-swap-oob="true">
```

(The direct target is `#tape-lines` with `hx-swap="beforeend"`, so the loose `<li>`s append; everything else swaps out-of-band. `tape` here is `tape_lines(out.delta_events, names)` — the delta only.)

Unexpected engine exception → 500 fragment stating scenario + seed + b64 log verbatim with "copy this block into a GitHub issue — it reproduces the bug exactly" (spec §Error handling).

- [ ] **Step 3: Run tests** — PASS. Then a live end-to-end click-through: play goblin-ambush from catalog to victory in the browser; confirm the URL fragment grows and a copied permalink restores the fight in a fresh private window.

- [ ] **Step 4: Gate + commit**

```bash
git add apps/demo/src/nat20_demo apps/demo/tests/test_act_route.py
git commit -m "feat(demo): act endpoint with OOB fragments, rejection + repro error paths"
```

---

### Task 8: Quality gates — public-surface guard, root Makefile, CI

**Files:**
- Create: `apps/demo/tests/test_engine_surface_usage.py`
- Modify: `Makefile` (root), `.github/workflows/ci.yml`

**Interfaces:** none new.

- [ ] **Step 1: Surface-guard test**

```python
import ast
from pathlib import Path

import dnd5e_engine

SRC = Path(__file__).parent.parent / "src" / "nat20_demo"

def test_demo_uses_only_public_engine_names() -> None:
    public = set(dnd5e_engine.__all__)
    violations: list[str] = []
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("dnd5e_engine"):
                if node.module != "dnd5e_engine":
                    violations.append(f"{py.name}: submodule import {node.module}")
                else:
                    violations.extend(
                        f"{py.name}: {a.name}" for a in node.names if a.name not in public
                    )
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{py.name}: bare import {a.name}"
                    for a in node.names if a.name.startswith("dnd5e_engine")
                )
    assert violations == []
```

Run it; expected PASS immediately (Tasks 3–7 already comply). If it fails, fix the demo import, never the test.

- [ ] **Step 2: Root Makefile**

Add to root `Makefile`: `check-demo:` target (`$(MAKE) -C apps/demo check`) and append `check-demo` to the `check:` prerequisite list; extend the `.PHONY` line.

- [ ] **Step 3: CI job**

Add to `.github/workflows/ci.yml`, mirroring the `engine` job exactly (same uv setup, matrix `["3.12", "3.13"]`, timeout 15) with `working-directory: apps/demo` and steps `uv sync --extra dev` then `make check`. Name: `nat20-demo (py${{ matrix.python-version }})`.

- [ ] **Step 4: Verify**

Run (from root): `make check` → all four legs pass. Run `uv run --group docs mkdocs build --strict` (this plan + spec live under `docs/dev/`, covered by `not_in_nav`) → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/demo/tests/test_engine_surface_usage.py Makefile .github/workflows/ci.yml
git commit -m "chore(demo): surface guard, root make check leg, CI job"
```

---

### Task 9: Deployment — Docker, Fly.io, deploy workflow, README/docs

**Files:**
- Create: `apps/demo/Dockerfile`, `apps/demo/.dockerignore`, `fly.toml` (root)
- Create: `.github/workflows/deploy-demo.yml`
- Modify: `README.md`, `docs/index.md`, `examples/README.md` (one pointer line)

**Interfaces:** none new.

- [ ] **Step 1: Dockerfile**

Build context is the REPO ROOT (the image needs both workspace packages):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/ apps/
RUN uv sync --frozen --no-dev --all-packages
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "nat20_demo.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

`.dockerignore`: `**/__pycache__`, `**/.pytest_cache`, `**/.mypy_cache`, `docs/`, `.git/`.

Verify locally: `docker build -f apps/demo/Dockerfile -t nat20-demo . && docker run -p 8080:8080 nat20-demo`, then `curl -s localhost:8080/ | grep "Goblin Ambush"`. (If Docker is unavailable locally, note it and rely on the Fly remote builder in Step 3.)

- [ ] **Step 2: fly.toml (root)**

```toml
app = "nat20-demo"
primary_region = "gru"

[build]
dockerfile = "apps/demo/Dockerfile"

[http_service]
internal_port = 8080
force_https = true
auto_stop_machines = "stop"
auto_start_machines = true
min_machines_running = 0

[[vm]]
size = "shared-cpu-1x"
memory = "512mb"
```

- [ ] **Step 3: Deploy workflow**

`.github/workflows/deploy-demo.yml`: on `push: branches: [main]` with `paths: [apps/demo/**, packages/**, fly.toml]` + `workflow_dispatch`; single job: checkout, `superfly/flyctl-actions/setup-flyctl@master`, `flyctl deploy --remote-only`, `env: FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}`; guard the job with `if: ${{ vars.DEPLOY_DEMO == 'true' }}` so forks and the pre-account period are inert. Run `actionlint` locally if available (CI has the actionlint job regardless).

**Human-partner step (cannot be done by the executor):** create the Fly app (`fly apps create nat20-demo`), add the `FLY_API_TOKEN` secret and set repo variable `DEPLOY_DEMO=true`. List this in the PR description as the activation checklist.

- [ ] **Step 4: README + docs**

- `README.md`: new "## Live demo" section after Quickstart — two sentences (what it is, that the server is stateless and every fight is a permalink), local run instructions (`uv run uvicorn nat20_demo.app:app` from `apps/demo/`), and the demo URL once deployed (until then: "public URL coming with the first deploy — run it locally meanwhile").
- `docs/index.md`: one paragraph + link mirroring the README section.
- `examples/README.md`: one line pointing to `apps/demo` as the full-application example.
- Verify: `uv run --group docs mkdocs build --strict` → PASS.

- [ ] **Step 5: Final full gate + commit**

Run (from root): `make check`

```bash
git add apps/demo/Dockerfile apps/demo/.dockerignore fly.toml .github/workflows/deploy-demo.yml README.md docs/index.md examples/README.md
git commit -m "feat(demo): dockerized Fly.io deployment + demo docs"
```

---

## Post-plan notes for the executor

- Task order is strict: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Task 3's determinism proof is a go/no-go gate for the whole architecture.
- Screenshots for README/docs are a manual follow-up after the UI stabilizes — not part of this plan.
- `BACKLOG.md` protocol check at the end: this work adds no engine gaps and closes none; no BACKLOG edit expected. If Task 4's AoE-targeting investigation reveals a genuine engine gap (e.g. burning-hands not castable through the public seam), ADD it to BACKLOG.md with a file anchor and swap the scenario's spell for one that works — do not hack the engine mid-plan.
