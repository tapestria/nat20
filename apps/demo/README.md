# nat20-demo — playable web demo of the engine

A small FastAPI + HTMX app that plays 5e SRD combat through the **public
`dnd5e_engine` API only**. Pick a scenario, take turns on a grid, and watch the
engine's event stream fill the tape. Its purpose is to show the engine is real and
complete; it is also a worked example of hosting the engine from a plain web app.

`nat20-demo` is a private workspace member — it is never published to PyPI.

## Run it locally

Prerequisite: [uv](https://docs.astral.sh/uv/). From the **repository root**, once:

```bash
uv sync --all-packages --all-extras
```

Then start the server:

```bash
uv run nat20-demo
```

Open <http://127.0.0.1:8000>. The catalog lists the five scenarios; each card names
the engine subsystem it demonstrates and carries an editable seed.

While editing code, run uvicorn directly for auto-reload:

```bash
cd apps/demo
uv run uvicorn nat20_demo.app:app --reload
```

## How to play

- **Catalog (`/`)** — choose a scenario and, optionally, change the seed.
- **Board (`/play/<scenario>`)** — the grid on the left, initiative and status on the
  side, contextual actions below. On a PC's turn, highlighted cells are candidate
  moves (click to move) and the action panel lists attacks, spells, and other intents
  with one button per legal target. On a monster's turn there is a single
  **Resolve monster turn** button. When the fight ends, an outcome card shows the
  result, XP, and residual HP.
- **Engine tape** — every `CombatEvent` the engine emits, one structured line each
  (roll totals, DCs, damage, conditions, concentration checks…), with a `raw` toggle
  that shows the event as JSON. This is the engine's actual output, not a narrative.
- **Seeds** — the seed drives every die roll. Replay the same scenario with the same
  seed and every roll repeats; change one digit and the fight diverges.

## Scenarios

| Scenario | Demonstrates |
| --- | --- |
| Goblin Ambush | Attack rolls, AC, cover folding into AC, grid movement and walls |
| Burning Hands at the Bottleneck | AoE save spells: per-target Dex saves, half damage on a save, spell-slot spend |
| Hold the Line | Conditions and effects: casting a hold, concentration under fire, concentration breaking |
| Marsh Crossing | Difficult terrain halving movement, Dash, ranged attacks at range, terrain cover |
| Last Stand | Healing, death saving throws, a dramatic near-loss and recovery |

Every creature and spell references a real slug from `dnd5e-srd-data`, so the demo
exercises the dataset as well as the engine.

## How it works: a stateless replay server

The server keeps **nothing** between requests. A fight is a small document the
browser holds:

```json
{"v": 1, "scenario_id": "goblin-ambush", "seed": 1337, "commands": [...]}
```

Each command is either a player intent (`{"t": "intent", "actor": ..., "intent":
{...PlayerIntent...}}`) or a monster turn (`{"t": "monster_turn"}`). On every
action the browser posts the full log plus the new command; the server replays it
from `start_combat(rng_seed=seed)` through the public seam
(`submit_player_intent` / `advance_monster_turn` / `drain_pending_events`),
applies the new command, returns the new tape lines and refreshed board fragments,
calls `end_combat`, and forgets the combat. See `src/nat20_demo/replay.py`.

Consequences:

- **Permalinks.** The log is mirrored into the URL and `localStorage`, so the
  address bar (or **Copy permalink**) reproduces the exact fight state — same
  rolls, same HP — for anyone who opens it. `/play/<scenario>?seed=<n>&log=<base64>`
  is the shareable form.
- **Determinism you can check.** Same seed + same ordered commands ⇒ identical
  event stream. The test suite asserts this for every scenario.
- **Bug reports are one line.** If the engine raises mid-replay, the error page
  prints the scenario, seed, and encoded log — a complete reproduction.
- **Limits.** A log is capped at 500 commands / 64 KB encoded; a command the engine
  rejects (wrong turn, illegal move) leaves the log untouched and explains why.

No rules logic runs in the browser: `static/log.js` only persists the log, and
every clickable move or target was rendered by the server. Candidate move cells are
a geometric hint — the engine remains the authority and rejects illegal moves.

## Development

```bash
cd apps/demo
make check      # ruff lint + format check, mypy (strict), pytest
make test       # pytest only
uv run pytest tests/test_replay.py -q   # one file
```

`make check` at the repository root includes this app as `check-demo`, and CI runs it
on Python 3.12 and 3.13.

Layout:

| Path | Role |
| --- | --- |
| `src/nat20_demo/app.py` | FastAPI factory and the four routes (`/`, `/play/{id}`, `/play/{id}/act`, `/about`) |
| `src/nat20_demo/replay.py` | Command model, `replay_fight`, log encoding and caps |
| `src/nat20_demo/scenarios.py` | The five scenarios as typed data |
| `src/nat20_demo/render.py` | Engine views/events → template contexts (grid, tape, actions…) |
| `src/nat20_demo/templates/` | Jinja templates; `_*.html` are HTMX fragments |
| `src/nat20_demo/static/` | `style.css`, vendored `htmx.min.js` (2.0.10), `log.js` |
| `tests/` | Replay-equivalence proof, scenario proof scripts, renderer and route tests, and the public-surface guard |

Rules of the house:

- Import only names from `dnd5e_engine.__all__` — `tests/test_engine_surface_usage.py`
  fails otherwise. The demo is proof that the public surface is enough.
- Scenarios are data. Add a new one in `scenarios.py` and give it a proof script in
  `tests/test_scenarios.py` naming the event types it must produce.
- Attacks need an explicit `weapon_id`; the engine silently resolves a weapon-less
  attack to nothing (tracked in the root `BACKLOG.md`).

## Hosting

This repository ships no deployment logic on purpose: `nat20-demo` is a plain ASGI app
(`nat20_demo.app:app`) that any host can run behind uvicorn, and it holds no state, so it
needs no volume, database, or session store. Deployment of the public Tapestria-hosted
instance lives in the Tapestria repository, not here.

---

Nat20 implements the D&D 5e SRD 5.2 (CC-BY-4.0); not affiliated with or endorsed by
Wizards of the Coast. Built by the team behind [Tapestria](https://github.com/tapestria).
