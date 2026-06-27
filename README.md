# Nat20 — Pure-Python D&D 5e SRD 5.2 rules engine

[![Engine: MIT](https://img.shields.io/badge/engine-MIT-blue.svg)](packages/dnd5e-engine/LICENSE)
[![Data: CC-BY-4.0](https://img.shields.io/badge/data-CC--BY--4.0-lightgrey.svg)](packages/dnd5e-srd-data/LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/python-3.12%2B-green.svg)](https://www.python.org/)

**Nat20** is an open-source, host-agnostic, zero-I/O **D&D 5e SRD 5.2 (CC-BY-4.0)**
rules engine for Python. Deterministic combat, skill checks, saving throws, effects,
and grid or zone-graph movement — driven by a typed, bundled SRD dataset. No network,
no database, no game host required.

## What is Nat20

Nat20 is a `uv` workspace of two complementary packages:

| Package | What it is | License |
|---------|-----------|---------|
| [`dnd5e-engine`](packages/dnd5e-engine) | Pure-Python 5e SRD rules engine — combat, checks, effects, grid/zone movement. Ships no rules data; reads the dataset at runtime. | **MIT** (code) |
| [`dnd5e-srd-data`](packages/dnd5e-srd-data) | The typed, canonical SRD 5.2 dataset the engine consumes via `BundledAssetLoader`. | **CC-BY-4.0** (data) |

The engine is edition-agnostic: it resolves whatever typed content it is handed. The
shipped dataset is the 2024 SRD (5.2) corpus.

## Quickstart

Install the engine (the dataset comes along as a dependency):

```bash
uv add dnd5e-engine
```

Run a tiny grid combat end-to-end. Every name below comes from the engine's public
surface (`dnd5e_engine.__all__`):

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
    # One Hero at cell (0,0), one Foe at (5,0), on a 10x10 grid. rng_seed makes
    # the dice deterministic; cell_id(col, row) encodes the "col,row" position.
    start = await start_combat(
        session_id="example",
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,  # high initiative => the Hero acts first
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

    # The Hero takes one diagonal step toward the Foe.
    await submit_player_intent(
        start.handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 1)),
    )

    # Close the encounter; the result carries the projected outcome.
    result = await end_combat(start.handle)
    print(f"Combat ended ({result.outcome.ended_reason}).")
    print(f"Residual HP: {result.outcome.residual_hp}")


asyncio.run(main())
```

The full, verified-runnable version lives in [`examples/grid_combat.py`](examples/grid_combat.py).

## Documentation

📖 **[tapestria.github.io/nat20](https://tapestria.github.io/nat20/)** — concepts, the
public API reference, a feature comparison, and developer guides.

The site is built with MkDocs from [`docs/`](docs/). Build and browse it locally:

```bash
uv run --group docs mkdocs serve
```

The published site is generated from the same sources (`mkdocs build --strict`).

## Licensing & provenance

- **Engine code** (`dnd5e-engine`): **MIT** — see [`packages/dnd5e-engine/LICENSE`](packages/dnd5e-engine/LICENSE).
  The engine ships no SRD data.
- **Dataset** (`dnd5e-srd-data`): **CC-BY-4.0** — see [`packages/dnd5e-srd-data/LICENSE`](packages/dnd5e-srd-data/LICENSE).
  Portions derived from the [Foundry VTT dnd5e](https://github.com/foundryvtt/dnd5e)
  system (CC-BY-4.0), cross-checked against [open5e](https://open5e.com) (CC-BY-4.0)
  and the [5e-bits/5e-database](https://github.com/5e-bits/5e-database) project (MIT).
- **Original source**: System Reference Document 5.1 and 5.2 by Wizards of the Coast
  LLC, distributed under CC-BY-4.0.

See [`NOTICE`](NOTICE) for the consolidated attribution.

## Disclaimer

Nat20 implements rules from the **D&D 5e System Reference Document (SRD 5.2)**, which
is published by Wizards of the Coast LLC under the Creative Commons Attribution 4.0
International License (CC-BY-4.0). Nat20 is an independent, unofficial project. It is
**not affiliated with or endorsed by Wizards of the Coast**. "Dungeons & Dragons" and
"D&D" are trademarks of Wizards of the Coast LLC; their use here is nominative, to
identify the SRD ruleset this project implements.

---

Built by the [Tapestria](https://github.com/tapestria) team.
