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
- `duration` — an `ActiveEffectDuration`.
- `changes` — a list of `ActiveEffectChange` entries (the mechanical
  modifications it applies).
- `statuses` — the set of condition slugs it imposes.
- `flags` — a free-form dict (Phase 6 uses it for concentration and
  applicable-action-type metadata).

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
