# Quickstart

Install (once published):

```bash
pip install dnd5e-engine dnd5e-srd-data
```

The engine reads its rules content from the companion `dnd5e-srd-data`
package — install both. The engine itself performs no I/O; content is loaded
explicitly through `BundledAssetLoader`.

## A grid combat in ~20 lines

This runnable example opens a combat on a 10×10 grid, moves a hero one step,
and closes the encounter — using only names from `dnd5e_engine.__all__`:

```python
--8<-- "examples/grid_combat.py"
```

The combat loop is four public coroutines:

- `start_combat(...)` — open the encounter, returns a `StartCombatResult`
  carrying the `CombatHandle` you thread through every later call.
- `submit_player_intent(handle, actor_id, intent)` — resolve one PC turn.
- `advance_monster_turn(handle)` — let a monster take its turn.
- `end_combat(handle)` — close out, returning an `EndCombatResult` with the
  projected `CombatOutcome`.

## A one-shot skill check

For an out-of-combat ability, skill, or saving-throw roll, `resolve_check` is
a pure function that takes a `CheckSpec` and returns a `CheckResult`:

```python
--8<-- "examples/skill_check.py"
```

## Building a combat-ready character

`make_build_spec` constructs a `CharacterBuildSpec`; `build_party_member`
resolves it against the SRD 5.2 corpus into a `PartyMemberSpec`:

```python
--8<-- "examples/build_party_member.py"
```

Next: read the [combat model](concepts/combat.md) or browse the full
[API reference](api.md).
