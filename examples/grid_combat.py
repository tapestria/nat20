"""Run a tiny grid combat end-to-end with the public dnd5e-engine API.

A lone Hero (acting first) faces a single Foe on a 10x10 grid. The Hero
takes one step, then we close the encounter and print the outcome. Every
name used here comes from ``dnd5e_engine.__all__`` (the public surface).
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    cell_id,
    end_combat,
    start_combat,
    submit_player_intent,
)


async def main() -> None:
    # Open combat: one PC at cell (0,0), one monster at (5,0), on a 10x10 grid.
    # ``rng_seed`` makes dice deterministic; ``cell_id(col, row)`` encodes "col,row".
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
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=7,
                hp_max=7,
                zone_id=cell_id(5, 0),
            )
        ],
        grid_scene=GridScene(width=10, height=10),
        rng_seed=1,
    )

    # The Hero takes one diagonal step toward the Foe (a "move" PlayerIntent).
    await submit_player_intent(
        start.handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 1)),
    )

    # Close the encounter; the result carries the projected CombatOutcome.
    result = await end_combat(start.handle)
    print(f"Combat ended ({result.outcome.ended_reason}).")
    print(f"Residual HP: {result.outcome.residual_hp}")


if __name__ == "__main__":
    asyncio.run(main())
