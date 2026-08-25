"""Run a grid combat end-to-end with the public dnd5e-engine API.

A lone Hero faces a Goblin Warrior on a 10x10 grid. The Hero steps into reach,
swings a longsword, and the goblin answers — then we close the encounter. Every
name used here comes from ``dnd5e_engine.__all__`` (the public surface).

Two things worth noticing:

* ``rng_seed`` makes the whole combat reproducible. Run this twice and you get
  byte-identical output.
* ``narration_events`` is consumed concurrently — it streams until
  ``end_combat`` closes it.
* A ``"move"`` intent steps to an **adjacent** cell only — the engine does not
  path-find, so closing two cells takes two intents.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import (
    CombatEvent,
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    advance_monster_turn,
    cell_id,
    end_combat,
    narration_events,
    start_combat,
    submit_player_intent,
)


def describe(event: CombatEvent) -> str:
    """Render one typed event as a line of text.

    The engine decides *what happened*; turning that into prose is the host's
    job. This is the smallest possible version of that job.
    """
    match event.type:
        case "attack_rolled":
            outcome = "CRIT" if event.is_crit else "hit" if event.is_hit else "miss"
            return f"  {event.attacker_id} attacks {event.target_id}: {event.roll_total} ({outcome})"
        case "damage_applied":
            return f"  {event.target_id} takes {event.amount} {event.damage_type} damage"
        case "death":
            return f"  {event.entity_id} drops!"
        case "move_failed":
            return f"  move rejected: {event.reason}"
        case "actor_moved":
            return f"  {event.actor_id} moves {event.from_zone} -> {event.to_zone}"
        case _:
            return f"  [{event.type}]"


async def main() -> None:
    # Hero at (0,0); a real SRD goblin two cells away at (2,0).
    start = await start_combat(
        session_id="example",
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,  # high initiative => the Hero acts first
                hp_current=12,
                hp_max=12,
                ac=12,
                zone_id=cell_id(0, 0),
            )
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:goblin",
                entity_type="Monster",
                name="Goblin Warrior",
                # Resolved from the bundled SRD corpus: gives the goblin its real
                # Scimitar/Shortbow actions instead of the generic fallback.
                monster_template_slug="goblin-warrior",
                initiative=1,
                hp_current=7,
                hp_max=7,
                zone_id=cell_id(2, 0),
            )
        ],
        grid_scene=GridScene(width=10, height=10),
        rng_seed=1,
    )
    handle = start.handle

    # ``narration_events`` streams until ``end_combat`` closes the queue, so a
    # host consumes it concurrently with driving the combat. That is the real
    # integration shape: the engine decides what happens, you render it.
    async def narrate() -> None:
        async for event in narration_events(handle):
            print(describe(event))

    narrator = asyncio.create_task(narrate())

    print("Round 1 — Hero closes and attacks:")
    # One step per intent: (0,0) -> (1,0) puts the Hero in longsword reach.
    await submit_player_intent(
        handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 0)),
    )
    await submit_player_intent(
        handle,
        actor_id="char:hero",
        intent=PlayerIntent(
            intent_type="attack", target_id="mon:goblin", weapon_id="longsword"
        ),
    )

    await advance_monster_turn(handle)

    result = await end_combat(handle)
    await narrator  # end_combat closes the stream, so this now returns

    print(f"\nCombat ended ({result.outcome.ended_reason}).")
    print(f"Residual HP: {result.outcome.residual_hp}")


if __name__ == "__main__":
    asyncio.run(main())
