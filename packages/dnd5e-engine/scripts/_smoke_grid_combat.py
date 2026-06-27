"""Clean-room smoke: exercise the installed dnd5e-engine wheel end-to-end.

Run by scripts/smoke_clean_install.sh inside a fresh venv that has ONLY the
built wheels installed. Exits non-zero on any failure.
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
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.orchestrator import get_live

# A genuine bundled monster slug — canonical/monsters/ ships goblin-warrior.json
# (there is no bare "goblin.json"). The smoke asserts the corpus resolves a slug
# that really ships in the dnd5e-srd-data wheel.
_BUNDLED_MONSTER_SLUG = "goblin-warrior"


def _check_corpus() -> None:
    loader = get_lib_loader()  # BundledAssetLoader → reads bundled canonical/
    monster = loader.get_monster(_BUNDLED_MONSTER_SLUG)
    assert monster is not None, (
        f"bundled corpus did not resolve monster {_BUNDLED_MONSTER_SLUG!r}"
    )


async def _run_grid_combat() -> None:
    start = await start_combat(
        session_id="smoke",
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
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
    assert get_live(start.handle).actor_zone["char:hero"] == "0,0"
    # One legal single-cell move proves the grid MOVE path resolves end-to-end.
    await submit_player_intent(
        start.handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 1)),
    )
    # get_live returns a point-in-time snapshot, so re-fetch after the move.
    assert get_live(start.handle).actor_zone["char:hero"] == "1,1", "grid move did not apply"
    result = await end_combat(start.handle)
    assert result is not None
    print("SMOKE OK: corpus loaded + grid combat ran (hero moved 0,0 -> 1,1)")


def main() -> None:
    _check_corpus()
    asyncio.run(_run_grid_combat())


if __name__ == "__main__":
    main()
