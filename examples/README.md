# Examples

Self-contained, runnable scripts that use only the public `dnd5e_engine` API.
Each is short and heavily commented so it doubles as a docs snippet.

| Script | Shows |
| --- | --- |
| [`grid_combat.py`](grid_combat.py) | A full round against a real SRD goblin: move, attack, monster response, and the streamed `CombatEvent` output — `start_combat` / `submit_player_intent` / `advance_monster_turn` / `narration_events` / `end_combat`. |
| [`skill_check.py`](skill_check.py) | Resolve a single skill check, seeded via `CheckSpec.rng` — `resolve_check` / `CheckSpec`. |
| [`build_party_member.py`](build_party_member.py) | Resolve a `CharacterBuildSpec` into combat-ready stats — `make_build_spec` / `build_party_member`. |

## Running

From the repo root (`uv` syncs the workspace automatically):

```bash
uv run python examples/grid_combat.py
uv run python examples/skill_check.py
uv run python examples/build_party_member.py
```

For a full playable application built on this same public API, see
[`apps/demo`](../apps/demo).

---

Nat20 implements the D&D 5e SRD 5.2 (CC-BY-4.0); not affiliated with or endorsed by Wizards of the Coast.
