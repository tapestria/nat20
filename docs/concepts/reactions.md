# Reactions

Reactions work — opportunity attacks, Shield, Counterspell — but they work
differently from how a table plays them, and the difference shapes any
integration. Read this before wiring a host.

## The constraint: reactions are pre-armed

**The engine never pauses mid-resolution to ask whether a creature wants to
react.** There is no callback, no "do you want to cast Shield?" prompt, and no
mid-turn round-trip to the host.

This is deliberate. `submit_player_intent` and `advance_monster_turn` are the
only two ways into the engine, and each resolves to completion before it
returns. A reaction is therefore *armed in advance* and fires automatically when
its trigger occurs.

```python
# On the wizard's own turn, arm Shield against being hit.
await submit_player_intent(
    handle,
    actor_id="char:wizard",
    intent=PlayerIntent(
        intent_type="ready",
        spell_id="shield",
        reaction_trigger="hit_by_attack",
    ),
)

# Later, on the goblin's turn, the armed Shield fires by itself if the
# goblin attacks the wizard — no host involvement.
await advance_monster_turn(handle)
```

If you want a player to *choose* in the moment, your host has to ask them
before their turn ends and arm accordingly. You cannot ask them mid-resolution.

## Recognized triggers

`PlayerIntent.reaction_trigger` accepts a closed set:

| Trigger | Fires when |
|---|---|
| `"hit_by_attack"` | The reactor is hit by an attack (Shield) |
| `"cast_spell"` | Another creature casts a spell (Counterspell) |
| `"targeted_by_magic_missile"` | The reactor is targeted by Magic Missile |

Opportunity attacks are separate: they need no arming and fire automatically in
both directions when a creature leaves an enemy's reach, unless the mover took
the Disengage action.

!!! note "This set is not data-driven"

    A new reaction spell cannot be added as data today — the trigger vocabulary
    is a `Literal` in the orchestrator, and Shield / Counterspell / Magic
    Missile carry named special cases. This is a known architectural gap,
    tracked in `BACKLOG.md`.

## Reaction economy

Each creature has one reaction per round, refreshed at the start of its turn —
the same budget an opportunity attack spends. Arming a reaction does not spend
it; firing does.

## Known limits

Two gaps are worth knowing about before you rely on these (both in `BACKLOG.md`):

- **Counterspell ignores its 60 ft range.** An armed reactor counters a cast at
  any distance.
- **A readied spell fires without a slot.** The reaction spends a spell slot
  when one is available but fires regardless, so a reactor with an empty pool
  gets a free cast.

Neither is reachable by accident — the host chooses to arm the reaction — but
neither is gated by the engine.

For the full design, including how the queue drains relative to attack
resolution and why Shield's AC bonus lands before the hit/miss comparison, see
the [reaction queue design note](../dev/reaction-queue.md).
