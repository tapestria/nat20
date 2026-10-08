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
nat20-bridge --host 127.0.0.1 --port 8020 --data-dir ~/.nat20-bridge --max-combats 16
```

- `--host` / `--port` — bind address. The bridge binds loopback by default
  and enables permissive CORS (`allow_origins=["*"]`) on the assumption that
  only a same-machine browser tab (the SillyTavern extension) talks to it —
  do not expose this port to an untrusted network.
- `--data-dir` — where homebrew content persists (`homebrew.json`), created
  on first run.
- `--max-combats` — how many combats stay live at once (16 by default);
  starting one more ends the least recently used. See
  [Combat sessions](#combat-sessions).

Check it's alive:

```bash
curl http://127.0.0.1:8020/v1/health
```

which returns the bridge, engine, and dataset versions.

## Endpoints

All routes are under `/v1`. Requests and responses are JSON. An error's
`detail` is a string, except a 422 for a body that doesn't validate (an
unknown intent key, a missing field, a value of the wrong type), whose
`detail` is FastAPI's list of errors.

| Method & path | What it does |
|---|---|
| `GET /v1/health` | Bridge/engine/dataset version report. |
| `POST /v1/roll` | Roll a dice expression (e.g. `"2d6+3"`), optionally seeded. |
| `POST /v1/check` | Resolve a skill/ability/saving-throw check against a DC. |
| `POST /v1/rest/short` | Resolve a short rest (hit-dice spend + healing). |
| `POST /v1/rest/long` | Resolve a long rest (full heal + hit-dice recovery). |
| `POST /v1/party/validate` | Build and validate a character (every `make_build_spec` keyword; see [Requests](#requests)) into a derived sheet — HP, AC, speed, proficiencies, spell slots, feats, computed by the engine's `derive_sheet` — without starting combat. The member carries no `attack_bonus`: to-hit is computed per weapon when an attack resolves. |
| `POST /v1/combat` | Start a combat: party builds + monster slugs → a `combat_id` and the opening events and narration. The engine rolls every Initiative. |
| `POST /v1/combat/{cid}/intent` | Submit one intent (attack, cast, move, …): `actor_id` plus any `PlayerIntent` field. |
| `POST /v1/combat/{cid}/advance-monster` | Let a monster take its turn. |
| `GET /v1/combat/{cid}` | Current combat view: round, initiative order (each row's Initiative, HP, conditions and cell), whose turn it is and its attacks left, the summons, transformations and constructs, the seed, and the combat's `grid` (its `GridScene`). |
| `POST /v1/combat/{cid}/end` | Close the combat, release it, and return its final `CombatOutcome`. |
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

## Requests

**A character** (`POST /v1/party/validate`, and each `party` member of
`POST /v1/combat`) is `name`, an optional `entity_id`, `build`, and optional
`spells_known` and `hp_current`. `build` takes every keyword of the engine's
`make_build_spec`: `species_slug`; `class_slug` and `level`, or `classes`
(`{"fighter": 3, "wizard": 2}`) for a multiclass character, whose level is
their sum; `subclass_slug`; `ability_scores` (`str`, `dex`, `con`, `int`,
`wis`, `cha`, each 10 when omitted); `equipment`; `selected_choices` (the
choice tokens in the
[character-sheet contract](hosting/character-sheet-contract.md));
`background_slug`; `hp_mode` (`"fixed"` or `"rolled"`, with `hp_rolls`);
`ac_calc_mode`; `attuned_items`; and `ability_score_method`. Keys the bridge
doesn't know are ignored, so a saved character can be sent as it stands.
Every keyword it does know is applied exactly as `make_build_spec` would, on
both routes: `hp_rolls` without `hp_mode: "rolled"` is refused with 422,
where both used to accept it.

**An intent** (`POST /v1/combat/{cid}/intent`) is `actor_id` plus the
engine's `PlayerIntent`: an `intent_type` and any of its optional fields —
`weapon_id`; `spell_id` with `slot_level`; `target_id` or `target_ids`;
`target_zone_id`; `direction` and `excluded_target_ids` for an area;
`feature_id` with `activity_id`; `form_id`; `stat_block_action_id` (an attack
from a summon's or a Wild Shape form's stat block); `use_bonus_action`; and the
rest. The actor can be a character or a creature it summoned. An unknown key
or intent type is refused with 422 and reaches nothing.

```json
{"actor_id": "char:elara", "intent_type": "cast_spell", "spell_id": "magic-missile",
 "target_id": "mon:ogre-1", "slot_level": 3}
```

## Combat sessions

`POST /v1/combat` seats the party in column 0 and the foes in column 1 of a
12×12 grid. Each foe comes from its stat block: its Hit Points, AC,
Dexterity, damage resistances, immunities and vulnerabilities, condition
immunities and senses, so a foe with Darkvision or Blindsight sees as its
stat block says. The engine rolls every combatant's Initiative from the
combat's own seeded generator — d20 plus the derived Dexterity modifier (a
background's increase included), plus the Proficiency Bonus for a character
with Alert — so the same `seed` and the same requests replay the same
combat. The view reports the seed and each combatant's Initiative.

Each response reports exactly the events its own request produced. A rejected
intent answers 409 with the engine's reason (`not_actor_turn`,
`no_action_economy`, …); one the engine can't resolve as sent (an activity it
has no context for yet) answers 422, though the engine may already have spent
the actor's Action and a feature's use, or left a PC partway through a move —
moving away from a few foes provokes an opportunity attack their own stat
block can't resolve (`BACKLOG.md` lists these activities and foes). Neither
leaves events behind for the next response, and a 500 leaves none either:
`/advance-monster` answers one on the turn of a foe whose stat block the
engine can't resolve yet (`BACKLOG.md` lists the seven).

At most `--max-combats` combats (16 by default) stay live. Starting one more
ends the least recently used one — every request that names a combat counts
as a use — and a combat that has ended or expired answers 404 (`unknown or
expired combat`). `POST /v1/combat/{cid}/end` releases a combat at once: end
each fight you are done with.

The `over` flag of an intent or advance-monster response is always `false`:
only `/end` ends a combat, and an ended combat's id answers 404. A fight whose
last foe or last character has dropped still reads `false`: read the view's
`order` (`dead`) to tell a decided fight.

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
  concurrent multi-client load. See `BACKLOG.md` for open gaps.
- `POST /v1/combat` seats every character in column 0 and every foe in
  column 1, so a character's first move away from the foe beside it draws that
  foe's opportunity attack, and a foe's walk away draws the character's. A
  character strikes with the first melee weapon in its build's `equipment`,
  else an Unarmed Strike; the bridge doesn't expose
  `opportunity_attack_weapon_id` yet.
- A foe's attacks roll at +0, the encounter spec's default `attack_bonus`,
  not at its stat block's bonus.
- No route spends a legendary action or a Legendary Resistance.
