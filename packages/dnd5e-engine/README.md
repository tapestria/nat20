# dnd5e-engine

Pure-Python D&D 5e SRD rules engine — host-agnostic, zero I/O. Combat, checks, effects,
on a zone graph or a 2-D grid.

## Status

Working engine. It resolves combat against the typed 2024-SRD corpus shipped by
[`dnd5e-srd-data`](../dnd5e-srd-data) (the `BundledAssetLoader` reads the bundled
`canonical/` data — no network, no DB). The engine is edition-agnostic: it consumes
whatever typed content it is handed.

Two spatial backends are supported, selected at `start_combat`:

- **Zone graph** — pass `scene_zones=SceneTopology(zones=..., edges=...)`; range/reach are
  resolved as shortest-path distance over a weighted, undirected zone graph.
- **2-D grid** — pass `grid_scene=GridScene(width, height)`; positions are `"col,row"` cell
  ids (`cell_id(col, row)`), distance is Chebyshev (8-direction, one cell = `cell_size_ft`).

## Install

Dev (editable, from this directory):

```bash
cd packages/dnd5e-engine
uv venv && uv pip install -e '.[dev]'
uv run --extra dev pytest -q
uv run --extra dev ruff check src/ tests/ scripts/
uv run --extra dev mypy src/
```

Standalone wheel:

```bash
uv build          # builds dist/dnd5e_engine-*.whl (+ sdist)
```

A clean-room install smoke builds both wheels, installs them into a throwaway venv with no
editable path deps, and runs a real grid combat through the public API:

```bash
bash scripts/smoke_clean_install.sh   # ends with "==> SMOKE PASSED"
```

## Quickstart

A minimal grid combat: open it, move a PC one cell, then close it.

```python
import asyncio

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    cell_id,
    end_combat,
    start_combat,
    submit_player_intent,
)


async def main() -> None:
    start = await start_combat(
        session_id="demo",
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=12,
                hp_max=12,
                ac=12,
                zone_id=cell_id(0, 0),
            )
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=7,
                hp_max=7,
                zone_id=cell_id(5, 0),
            )
        ],
        grid_scene=GridScene(width=10, height=10),
        rng_seed=1,
    )

    # The hero won initiative; move one cell diagonally.
    await submit_player_intent(
        start.handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 1)),
    )

    result = await end_combat(start.handle)
    print("ended reason:", result.outcome.ended_reason)


asyncio.run(main())
```

An attack instead of a move: submit
`PlayerIntent(intent_type="attack", target_id="mon:foe", weapon_id="longsword")` — the
engine fetches the typed weapon from the bundled corpus and walks its activities.

## Public API

All exported names live in `__all__` in `src/dnd5e_engine/__init__.py`. The key entry points:

- `start_combat(*, session_id, party, encounter, scene_zones=|grid_scene=, rng_seed, ...)` —
  open a combat, materialize runtime state, return a `StartCombatResult` (`.handle`, opening
  `.events`).
- `submit_player_intent(handle, actor_id, intent)` — validate and resolve a PC's
  `PlayerIntent` for the current turn.
- `advance_monster_turn(handle)` — resolve the active monster's turn via its typed action
  repertoire + behavior gambits.
- `end_combat(handle)` — close a combat and return an `EndCombatResult` (`.outcome`,
  `.events`, `.final_active_effects`).
- `narration_events(handle)` — async iterator streaming the `CombatEvent` union for the
  narrator.
- `get_actor_active_effects(handle, entity_id)` — read-only snapshot of one combatant's
  active effects.
- `resolve_check(spec)` — resolve an out-of-combat ability check / saving throw
  (`CheckSpec` → `CheckResult`).
- `build_party_member(spec, ...)` — project a `CharacterBuildSpec` into a combat-ready
  `PartyMemberSpec`.
- `make_build_spec(...)` — assemble a `CharacterBuildSpec` (ability scores, class, species).

Spatial helpers and spec types:

- `GridScene` / `cell_id(col, row)` / `parse_cell(cell_id)` — 2-D grid scene + cell-id codec.
- `SceneTopology` / `ZoneEdge` — zone-graph scene description.
- `PartyMemberSpec` / `EncounterMemberSpec` — combatant inputs to `start_combat`.
- `PlayerIntent` — a PC's submitted intent (move / attack / cast_spell / use_item / ...).
- `CombatHandle`, `StartCombatResult`, `EndCombatResult`, `CombatOutcome`, `CombatEvent`,
  `ActiveEffect`, `CheckSpec`/`CheckResult`/`CheckKind`, `CharacterBuildSpec`,
  `AbilityScores`, and the `IntentType` / `ActionType` literals.

## Layout

```
packages/dnd5e-engine/
├── pyproject.toml          hatchling build; pydantic + d20 + dnd5e-srd-data deps
├── LICENSE                 MIT (engine code)
├── scripts/
│   ├── _smoke_grid_combat.py     clean-room smoke program (runs in a fresh venv)
│   └── smoke_clean_install.sh    builds wheels + installs them + runs the smoke
├── src/dnd5e_engine/
│   ├── __init__.py         public API (__all__)
│   ├── orchestrator.py     start/submit/advance/end combat seam + live state
│   ├── spatial.py          grid + zone topologies, cell_id / parse_cell
│   ├── specs.py            GridScene, SceneTopology, party/encounter specs
│   ├── check.py            out-of-combat ability check / saving throw resolver
│   ├── build_party.py / build_spec.py   character build → combat spec projection
│   ├── lib_loader.py       BundledAssetLoader singleton (typed SRD corpus)
│   ├── events.py / outcome.py / results.py   event union, outcome, result envelopes
│   ├── activities/         typed-Activity resolvers (attack / save / monster actions)
│   ├── rules/              dice, conditions, gambits, ...
│   └── types/              combat / effects / conditions / intent value types
└── tests/                  pytest suite
```

## License

- Engine code: MIT — see [`LICENSE`](LICENSE). The engine ships no SRD data.
- SRD content (the typed corpus consumed via `dnd5e-srd-data`): CC-BY-4.0 — see the
  [`dnd5e-srd-data`](../dnd5e-srd-data) package's `LICENSE` and `NOTICE` for the
  dataset license and attribution chain.
