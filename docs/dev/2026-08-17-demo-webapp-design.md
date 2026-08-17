# Nat20 demo web app — design spec

**Date:** 2026-08-17
**Status:** approved design, pre-implementation
**Location rationale:** lives in `docs/dev/` (already `not_in_nav` for the MkDocs
strict build) alongside the other developer design docs.

## Purpose

A public, playable web demo of the `dnd5e-engine` + `dnd5e-srd-data` stack. Its
job is **engine credibility for developers evaluating the library**: prove the
engine resolves real 5e SRD combat — attacks, saves, spells, effects,
concentration, conditions, grid movement, cover, death saves — and that it is
deterministic and easy to host. Tapestria appears only as light attribution
(one footer link). The demo is also a living integration reference: it may use
**only** the engine's public surface (`dnd5e_engine.__all__`).

## Core architectural decision: stateless replay backend

The server holds **zero state between requests**. The durable representation of
a fight is a client-held document:

```json
{"v": 1, "scenario_id": "goblin-ambush", "seed": 1337, "commands": [...]}
```

- The **client** (browser) persists this in `localStorage` and mirrors it into
  the URL fragment (`#s=<scenario>&seed=<n>&log=<base64>`), so any fight state
  is a copy-pasteable permalink that reproduces bit-identical dice.
- On every mutating request the client sends the full log plus the new command.
  The server replays from `start_combat(rng_seed=seed)`, applies each logged
  command in order, applies the new command, collects the events the new
  command produced, and responds. The combat handle is closed/discarded within
  the request.
- This rests on the engine's stated guarantee: same seed + same ordered intent
  sequence ⇒ identical event stream. A replay-equivalence test is the **first
  thing built**; the architecture is invalid if it fails.

Consequences embraced: no SSE/streaming (each POST returns the event delta for
that command — natural for turn-based play); replay cost is O(commands) pure
CPU per request (negligible at demo scale); restarts, replicas, and rolling
deploys are free; the architecture itself demonstrates the engine's zero-I/O
purity boundary.

### Command vocabulary

A small, versioned, JSON-serializable union (the only persistent schema):

- `{"t": "intent", "actor": "<entity_id>", "intent": {…PlayerIntent fields…}}`
  → `submit_player_intent`
- `{"t": "monster_turn"}` → `advance_monster_turn`

Every RNG-consuming step, including monster turns, is a log entry, in order.

## Package layout

New uv workspace member **`apps/demo/`** (distribution name `nat20-demo`,
private / never published; `apps/` = consumers, `packages/` = published libs).
Depends on `dnd5e-engine` via the workspace.

```
apps/demo/
  pyproject.toml            # fastapi, uvicorn, jinja2; dev: httpx, pytest, ruff, mypy
  Makefile                  # check = ruff lint+format-check + mypy + pytest
  src/nat20_demo/
    app.py                  # FastAPI factory + routes
    replay.py               # core: (scenario, seed, commands) -> replayed combat + event delta
    scenarios.py            # curated scenario catalog (typed, data-only)
    render.py               # LiveCombatView / CombatEvent -> template-context dicts
    templates/              # Jinja: shell, catalog, grid, initiative, status, actions, tape
    static/                 # style.css, vendored htmx.min.js, log.js (~20 lines)
  tests/
  Dockerfile
```

## Routes & UI

Server-rendered Jinja + HTMX fragment swaps. **No client-side rules logic** —
legal moves/targets are computed server-side and rendered as the only
clickable elements.

- `GET /` — scenario catalog: one card per scenario stating the engine
  subsystem it proves; editable seed field (defaults to a curated showcase
  seed). The catalog is the feature matrix, playable.
- `GET /play/{scenario_id}?seed=N&log=B64` — the play shell; replays the log
  (empty on first visit) and renders the full board. This route is the
  permalink target.
- `POST /play/{scenario_id}/act` — body `{seed, commands[], new_command}`;
  replays, applies, responds with an HTMX out-of-band fragment bundle: grid,
  initiative rail, status panel, action panel, and new tape lines. The
  canonical updated log rides back in the response; `log.js` writes it to
  `localStorage` + URL fragment.
- `GET /about` — project links; the shared shell footer carries the single
  Tapestria attribution: "Built by the team behind Tapestria."

UI regions (one template each):

1. **Grid map** — CSS grid; tokens, walls, difficult-terrain shading, cover
   indicators; legal cells/targets clickable.
2. **Initiative rail** — from `LiveCombatView.initiative`; current turn
   highlighted, dead greyed.
3. **Status panel** — HP/temp HP bars, conditions, spell slots, concentration.
4. **Action panel** — contextual: PC turn → legal intents as buttons/forms;
   monster turn → one "Resolve monster turn" button; combat over → outcome
   card (`ended_reason`, XP, residual HP) + replay / copy-permalink actions.
5. **Engine tape** — the credibility centerpiece: each `CombatEvent` rendered
   as a structured line (type, actor, dice expression, raw roll, modifiers,
   DC/AC, result) with a raw-JSON toggle.

## Scenario catalog

Five hand-authored scenarios in `scenarios.py`, typed data only
(`PartyMemberSpec` / `EncounterMemberSpec` / `GridScene`), all entities
referencing real SRD dataset slugs:

1. **Goblin Ambush** — melee/ranged attacks, walls, cover AC fold. Hello-world.
2. **Burning Hands at the Bottleneck** — AoE save spell: area targeting,
   per-target Dex saves, half on save, slot spend.
3. **Hold the Line** — conditions & effects; concentration held and broken by
   damage.
4. **The Marsh Crossing** — difficult-terrain movement budgets, dash, ranged
   at range, terrain cover.
5. **Last Stand** — healing, temp HP, death saves; showcase seed tuned to a
   dramatic 1-HP victory.

Curated default seeds; the seed field stays editable to demonstrate the
seeding contract live.

## Error handling

- Command rejected by the engine (wrong turn, illegal move) or garbled mid-log
  → replay stops at the last valid prefix; response renders the board at that
  prefix, truncates the log to it, and says which command failed and why.
- Unknown scenario / malformed base64 → friendly 404/400 with a back link.
- Engine exception during replay → 500 fragment that includes scenario + seed
  + log so any visitor can file a perfect one-line reproduction (stated on the
  error page — stateless replay makes every bug a repro).

## Testing

- **Replay-equivalence (first):** scripted fight live vs. fresh replay of the
  same log — event streams must be identical. Parametrized over all five
  scenarios × several seeds.
- **Public-surface guard:** every `dnd5e_engine` name the demo imports must be
  in `__all__`.
- **Route tests** (`httpx.AsyncClient`): catalog, empty-log play page,
  `POST /act` happy path, rejected-command path, malformed-log path.
- **Scenario smoke:** each scenario's showcase seed plays a scripted command
  list to a terminal state — doubles as an engine integration regression
  suite.
- Wired into root `make check` and a per-app CI job mirroring the packages
  (ruff, mypy, pytest).

## Deployment

- uv-based Dockerfile (engine + data + demo installed, uvicorn entrypoint).
- Fly.io, single small machine; statelessness means no volume, replicas and
  scale-to-zero are acceptable.
- `deploy.yml` GitHub workflow on main/tag.
- Abuse guard: request-size cap on the log (500 commands) + platform rate
  limiting. No accounts, no data at rest.
- README + docs get screenshots and the live URL.

## Out of scope

Sandbox encounter builder, narrated/AI-DM layer, persistence beyond the
client-held log, mobile-first polish, non-combat play (rests, downtime),
authentication of any kind.
