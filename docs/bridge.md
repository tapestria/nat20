# nat20-bridge — the SillyTavern sidecar

`nat20-bridge` is a small **localhost FastAPI sidecar** that puts `dnd5e-engine`
and `dnd5e-srd-data` behind a plain HTTP/JSON API. It exists so a non-Python
client — in practice, a browser-side SillyTavern extension — can drive
deterministic 5e SRD combat, checks, and rests without embedding a Python
interpreter or talking to the engine's typed Python API directly.

The bridge is a thin routing layer: every request maps to one or two calls
into the engine's public surface (`start_combat`, `submit_player_intent`,
`resolve_check`, `resolve_short_rest`, …) and returns the engine's typed
result as JSON. It holds no rules logic of its own beyond request parsing,
sheet derivation from a `CharacterBuildSpec`, and in-memory combat-session
bookkeeping.

License: **MIT**, same as the engine. It ships no SRD content of its own —
reads (`/v1/srd/...`) resolve through `dnd5e-srd-data`'s bundled dataset
(CC-BY-4.0), plus whatever homebrew JSON you feed it locally.

## Quickstart

Once published to PyPI:

```bash
uvx nat20-bridge
```

Working in this repo (before publish, or for local development):

```bash
uv run nat20-bridge
```

Either way this starts a server on `127.0.0.1:8020` by default. Useful flags:

```bash
nat20-bridge --host 127.0.0.1 --port 8020 --data-dir ~/.nat20-bridge
```

- `--host` / `--port` — bind address. The bridge binds loopback by default
  and enables permissive CORS (`allow_origins=["*"]`) on the assumption that
  only a same-machine browser tab (the SillyTavern extension) talks to it —
  do not expose this port to an untrusted network.
- `--data-dir` — where homebrew content persists (`homebrew.json`), created
  on first run.

Check it's alive:

```bash
curl http://127.0.0.1:8020/v1/health
```

which returns the bridge, engine, and dataset versions.

## Endpoints

All routes are under `/v1`. Requests and responses are JSON.

| Method & path | What it does |
|---|---|
| `GET /v1/health` | Bridge/engine/dataset version report. |
| `POST /v1/roll` | Roll a dice expression (e.g. `"2d6+3"`), optionally seeded. |
| `POST /v1/check` | Resolve a skill/ability/saving-throw check against a DC. |
| `POST /v1/rest/short` | Resolve a short rest (hit-dice spend + healing). |
| `POST /v1/rest/long` | Resolve a long rest (full heal + hit-dice recovery). |
| `POST /v1/party/validate` | Build and validate a `CharacterBuildSpec` into a derived sheet (AC, HP, slots, attack bonus, …) without starting combat. |
| `POST /v1/combat` | Start a combat: party + monster slugs (by name) → a `combat_id` and the opening event narration. |
| `POST /v1/combat/{cid}/intent` | Submit one player intent (attack, cast, move, …) for the given combat. |
| `POST /v1/combat/{cid}/advance-monster` | Let a monster take its turn. |
| `GET /v1/combat/{cid}` | Current combat view: round, initiative order, HP, conditions, whose turn it is. |
| `POST /v1/combat/{cid}/end` | Close the combat and return its final `CombatOutcome`. |
| `GET /v1/srd/{category}` | List slugs in a content category (`items`, `monsters`, `spells`, `species`, `classes`, `subclasses`, `backgrounds`, `feats`, `features`), optionally filtered by a substring query (`?q=`). |
| `GET /v1/srd/{category}/{slug}` | Fetch one canonical (or homebrew) entry by slug. |
| `POST /v1/homebrew/{category}` | Import a raw homebrew JSON entry into that category (see below). |
| `GET /v1/homebrew` | List all homebrew slugs and their categories. |
| `DELETE /v1/homebrew/{slug}` | Remove a homebrew entry. |
| `POST /v1/forge/item` | Generate a homebrew magic-weapon variant (base weapon + bonus + optional extra damage) and store it as homebrew. |

Combat and content routes read through the same overlay loader, so any
homebrew entry you've imported is visible everywhere a canonical slug would
be (`/v1/combat` monster/party lookups, `/v1/srd/...` reads, etc.) without
restarting the process.

## Homebrew content format

Homebrew entries are raw JSON dicts that get re-validated against the same
Pydantic schema models the canonical `dnd5e-srd-data` dataset uses
(`dnd5e_srd_data.schema.*`) — so a homebrew monster, item, or spell must be
shaped like its canonical counterpart. `POST /v1/homebrew/{category}` rejects
anything that fails that validation with a `422` and the Pydantic error
detail.

Every homebrew slug is forced to carry an `hb-` prefix so it can never
collide with (or shadow) a canonical SRD slug. Homebrew persists as a single
`homebrew.json` file under `--data-dir`.

### Example: forging a +1 flaming shortsword

Rather than hand-writing full item JSON, `POST /v1/forge/item` derives a
homebrew weapon variant from an existing canonical base weapon:

```bash
curl -X POST http://127.0.0.1:8020/v1/forge/item \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "Flametongue Shortsword",
        "base": "shortsword",
        "bonus": 1,
        "extra_damage": "1d6:fire"
      }'
```

This returns `{"slug": "hb-...", "summary": "..."}`; the new item is stored
as homebrew and immediately resolvable via `GET /v1/srd/items/{slug}` or as
a party member's weapon in `/v1/party/validate` / `/v1/combat`.

## The SillyTavern extension

The bridge is the server half of a pair — the client half is the
[SillyTavern-nat20](https://github.com/tapestria/SillyTavern-nat20) browser
extension, which runs inside a SillyTavern chat and calls this API to resolve
5e SRD combat, checks, and rests instead of freeform narration. Install the
extension in SillyTavern, run `nat20-bridge` locally, and point the extension
at `http://127.0.0.1:8020`.

## Known limitations

- The bridge is designed for single-user, same-machine use (one SillyTavern
  browser tab talking to one local process) — it is not hardened for
  concurrent multi-client load. See `BACKLOG.md` for open gaps (global-RNG
  seeding under concurrent requests, combat state not being garbage
  collected for sessions that are never explicitly ended via `/end`).
