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

The template supplies the creature's actions, ability scores (Dexterity too,
while the spec leaves it at 10), proficiencies, traits and spellcasting
ability. Its Armor Class, Hit Points, speed and `attack_bonus` stay the
spec's. A template monster's attacks roll to hit at that `attack_bonus` and
add no ability modifier to their damage, and with no spellcasting ability its
save DC is `8 + attack_bonus` — so with the default `attack_bonus=0` a Tough's
Mace rolls d20 + 0 for 1d6, where its stat block says +4 and 1d6 + 2. Pin `ac`
and `attack_bonus` from the stat block: every SRD monster in the dataset now
carries its Armor Class (`Monster.ac`, C21).

Only a transformed creature — a druid in a Wild Shape form, or a creature
under *Polymorph* — rolls at a stat block's real numbers: the form's ability
scores and Proficiency Bonus, so a Wolf form bites at +4 for 1d6 + 2 (C21). A
host can command one attack from a creature's current stat block with
`PlayerIntent(intent_type="attack", stat_block_action_id=..., target_id=...)`.

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

## Monster action economy

A monster's turn picks the most powerful option it has: a charged Recharge
action first, then a Spellcasting action whose N/Day offensive spell still has
a use left, then Multiattack, then its other attacks and at-will spells in
stat-block order. At the start of a living monster's own turn the engine rolls
Recharge for each spent recharge action, applies Regeneration and refills its
legendary-action pool. Legendary actions are host-driven:
`advance_monster_turn(handle, legendary=True)` after another creature's turn
ends. Legendary Resistance is armed ahead of a save with
`resolve_legendary_resistance`. The capability matrix lists the traits the
engine consumes.

## What is not modelled

- **Lair actions** — the corpus ships none.
- Some `special_abilities` (Flyby, Nimble Escape) and the ability-check half of
  Sunlight Sensitivity.
- Real stat-block numbers for a template monster that is not transformed, and
  commanding a stat block's save actions (a Breath Weapon).

All are tracked in `BACKLOG.md`. If you need them, resolve them host-side and
apply the results through the engine's normal paths.
