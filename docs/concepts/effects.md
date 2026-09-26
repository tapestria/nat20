# Effects

Ongoing conditions and buffs are modeled as **`ActiveEffect`** documents — a
Foundry-aligned, Pydantic-typed shape. A spell like *bless*, a *poisoned*
condition, or a magic-item bonus all become `ActiveEffect`s attached to a
combatant for the duration of combat.

## The model

An `ActiveEffect` carries:

- `id` — the template id analog (e.g. `"effect:bless"`).
- `origin` — what produced it (e.g. `"cast:bless:1"`, `"item:sword+1:abc12"`).
- `target_id` — the combatant it is attached to.
- `duration` — an `ActiveEffectDuration` (see *Durations* below).
- `changes` — a list of `ActiveEffectChange` entries (the mechanical
  modifications it applies).
- `statuses` — the set of condition slugs it imposes.
- `flags` — a free-form dict. The engine reads a few keys: `concentration`
  (the effect is its caster's concentration), `applicable_action_types` (a
  weapon-only bonus), and three from C21: `concentration_anchor` (the marker a
  concentration spell that applied no effect of its own leaves on its caster),
  `enchanted_weapon` (a weapon slug: the effect's changes apply to attacks with
  that weapon only) and `transform_form` (a monster slug: the effect carries a
  Wild Shape or *Polymorph* form).

## Durations

`ActiveEffectDuration` carries three counters, all of which tick at a turn
boundary (`turn_lifecycle`'s `turn_end` hooks). SRD 5.2 §Duration puts a round
at about 6 seconds, which is the whole conversion:

| Field | Ticks at | Notes |
|---|---|---|
| `rounds` | the **caster's** turn end (parsed from `origin`; item/environment origins fall back to the target's) | reaching zero emits `EffectExpired(reason="duration")` |
| `turns` | the **target's own** turn end | independent of `rounds` — whichever counter hits zero first expires the effect |
| `seconds` | the caster's turn end, as `ceil(seconds / 6)` rounds | materialised once into `rounds`; `seconds` is never mutated. **If both are set, `rounds` wins** |

`flags["until_end_of_next_turn_of"] = "<entity_id>"` expresses SRD's "until the
end of your next turn": the effect expires at that actor's next turn end, with
a one-turn grace if it was applied during that actor's own turn.

Concentration-flagged effects are exempt from all of the above — the
concentration cascade and the per-turn repeat save own their lifetime, and the
imported packs carry display-only counters on them.

## Concentration anchors, enchantments and forms

Every concentration spell concentrates. When a cast applies no concentration
effect of its own — *Spiritual Weapon*, a *Hold Person* every target saved
against — the engine puts an anchor on the caster: `effect:<spell>`, origin
`cast:<spell>:<caster>`, flags `concentration` and `concentration_anchor`, and
no changes. It joins `concentration_chain` and ends like any concentration
effect, and what depends on it (a *Spiritual Weapon* force) ends with it.

*Magic Weapon* lands on the creature it touches, with `enchanted_weapon`
naming the weapon (`PlayerIntent.weapon_id`); the engine applies the effect's
`system.magicalBonus` (upgrade) and `mgc` property changes to that weapon's
attacks only. A host can carry one into a combat:

```python
ActiveEffect(
    id="effect:magic_weapon_+1",
    name="Magic Weapon +1",
    origin="cast:magic_weapon_+1:char:hero",
    target_id="char:hero",
    changes=[
        ActiveEffectChange(key="system.magicalBonus", mode="upgrade", value="1"),
        ActiveEffectChange(key="system.properties", mode="add", value="mgc"),
    ],
    duration=ActiveEffectDuration(seconds=3600),
    flags={"enchanted_weapon": "longsword"},
)
```

A Wild Shape or *Polymorph* form rides `effect:wild-shape` or
`effect:polymorph`, with `transform_form` naming the Beast. The form's
statistics show on the creature's `initiative` entry, and the effect's expiry
restores its own. Seeding a form through `start_combat(active_effects=...)`
does not transform the creature (BACKLOG.md).

## Lifecycle and scope

Effects are **combat-scoped and engine-owned**. The engine holds active
effects in memory during the encounter; concentration and repeat-save linkage
key on `(target_id, id, origin)` identity. You can pass starting effects into
`start_combat(..., active_effects=...)` and read a combatant's current effects
during combat with `get_actor_active_effects(handle, entity_id)`.

When combat ends, `end_combat` returns the final tuple on
`EndCombatResult.final_active_effects` — but the engine itself discards them:
effects do not persist across combats. Cross-combat persistence is a host
concern, not the engine's. This is a deliberate boundary: the engine is the
in-combat effect authority and nothing more.
