# Monsters

Monsters take their turns through `advance_monster_turn(handle)`. The engine
picks the action, resolves it, and emits events — there is no monster intent for
a host to submit.

## Getting a real monster

Pass `monster_template_slug` on an `EncounterMemberSpec` and the engine resolves
that creature from the bundled SRD corpus, giving it its actual actions,
resistances, senses and saves:

```python
EncounterMemberSpec(
    entity_id="mon:goblin",
    entity_type="Monster",
    name="Goblin Warrior",
    monster_template_slug="goblin-warrior",   # <- the SRD creature
    initiative=1,
    hp_current=7,
    hp_max=7,
    zone_id=cell_id(2, 0),
)
```

Omit it and you get a generic combatant driven by the inline `attack_bonus` /
`damage_dice` fields — fine for a training dummy, but it has no real repertoire.

## How the AI chooses

The built-in AI is deliberately simple and predictable:

1. **Target** the lowest-HP living PC.
2. **Prefer Multiattack** when the creature has it — it is the full-action play.
3. **Otherwise** pick an action whose own range covers the target, closing the
   distance first if needed (and Dashing when that helps).
4. **Flee** when badly hurt, unless the creature is `DEFENSIVE`.

`EncounterMemberSpec.behavior_profile` selects between three profiles:

| Profile | Behaviour |
|---|---|
| `AGGRESSIVE` (default) | Closes and attacks; flees below 10% HP |
| `RANGED` | Prefers to keep distance; flees below 25% HP |
| `DEFENSIVE` | Never flees |

This is a reasonable default opponent, not a tactical AI. If you want smarter
monsters, drive them yourself and use the engine as the resolver.

## Multiattack

A multiattack names its sub-attacks only in prose, so the engine parses the
description to fan it out — "makes two Claw attacks and uses Roar" becomes two
claws and one roar.

**119 of the 180 multiattacks in the corpus resolve to the exact SRD attack
mix.** The remaining 61 fall back to repeating one attack N times and log
`multiattack_join_unresolved` at WARNING, so the loss is always visible in your
logs rather than silent. For homogeneous multiattacks ("three Rend attacks")
the fallback is correct; 5 monsters are heterogeneous and get the wrong mix.
See the [capability matrix](../capabilities.md) for the specifics.

## What is not modelled

- **Legendary actions.** 30 monsters carry them in the data; the engine reads
  only `Monster.actions`, so a legendary creature acts once per round like any
  other.
- **Lair actions**, **recharge (5–6) abilities**, **regeneration**, and
  `special_abilities`.

All are tracked in `BACKLOG.md`. If you need them, resolve them host-side and
apply the results through the engine's normal paths.
