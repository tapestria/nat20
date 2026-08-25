# Quickstart

Install:

```bash
pip install dnd5e-engine
```

`dnd5e-srd-data` comes along as a dependency — the engine reads its rules
content from it and performs no I/O of its own. To drive the engine from your
own typed corpus instead, install a loader with `configure_lib_loader`.

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

For an out-of-combat ability, skill, or saving-throw roll, `resolve_check`
takes a `CheckSpec` and returns a `CheckResult`. Pass a seeded
`CheckSpec.rng` to make the roll reproducible — unlike combat, which is seeded
once via `start_combat(rng_seed=...)`, a standalone check carries its own
generator:

```python
--8<-- "examples/skill_check.py"
```

## Building a combat-ready character

`make_build_spec` constructs a `CharacterBuildSpec`; `build_party_member`
resolves it against the SRD 5.2 corpus into a `PartyMemberSpec`:

```python
--8<-- "examples/build_party_member.py"
```

Next: read the [combat model](concepts/combat.md), check the
[capability matrix](capabilities.md) to see which rules are actually resolved,
or browse the full [API reference](api.md).
