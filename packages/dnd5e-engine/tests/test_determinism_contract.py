"""Pins the engine's published determinism contract.

Two guarantees are documented and must hold:

1. Combat resolution is reproducible from ``start_combat(rng_seed=...)`` alone,
   and is isolated from the process-global ``random`` module.
2. ``resolve_check`` is reproducible when handed a seeded ``CheckSpec.rng``,
   likewise independent of global ``random`` state.

Both are load-bearing marketing claims (``docs/index.md``: "give it a seed and
the same inputs always produce the same outcome"), so they get a test rather
than a docstring.
"""

from __future__ import annotations

import asyncio
import json
import random

from dnd5e_engine import (
    CheckSpec,
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    __version__,
    advance_monster_turn,
    cell_id,
    end_combat,
    resolve_check,
    roll_dice_str,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.orchestrator import drain_pending_events


def _stealth_spec(seed: int) -> CheckSpec:
    return CheckSpec(
        kind="skill",
        skill="stealth",
        ability_scores={"dexterity": 16, "wisdom": 12},
        proficient_skills=("stealth",),
        proficient_saves=(),
        proficiency_bonus=2,
        dc=15,
        rng=random.Random(seed),
    )


async def _run_combat(global_seed: int) -> str:
    """Run a fixed intent sequence under a hostile global-``random`` state."""
    random.seed(global_seed)
    start = await start_combat(
        session_id="determinism",
        party=[
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=30,
                hp_max=30,
                ac=13,
                zone_id=cell_id(0, 0),
            )
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=20,
                hp_max=20,
                zone_id=cell_id(1, 0),
            )
        ],
        grid_scene=GridScene(width=10, height=10),
        rng_seed=7,
    )
    events = [e.model_dump() for e in drain_pending_events(start.handle)]
    for _ in range(3):
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", target_id="mon:foe", weapon_id="longsword"),
        )
        events += [e.model_dump() for e in drain_pending_events(start.handle)]
        await advance_monster_turn(start.handle)
        events += [e.model_dump() for e in drain_pending_events(start.handle)]
    await end_combat(start.handle)
    return json.dumps(events, sort_keys=True, default=str)


def test_combat_is_reproducible_and_isolated_from_global_random() -> None:
    """Same rng_seed + same intents => identical event stream, whatever the
    process-global ``random`` state happens to be."""
    first = asyncio.run(_run_combat(global_seed=1))
    second = asyncio.run(_run_combat(global_seed=999_999))
    assert first == second
    assert first  # guard against both runs vacuously producing nothing


def test_resolve_check_is_reproducible_with_a_seeded_rng() -> None:
    random.seed(1)
    first = [resolve_check(_stealth_spec(42)).natural_roll for _ in range(5)]
    random.seed(999_999)
    second = [resolve_check(_stealth_spec(42)).natural_roll for _ in range(5)]
    assert first == second


def test_resolve_check_distinct_seeds_diverge() -> None:
    """Guards the test above against a resolver that ignores ``rng`` entirely."""
    samples = {resolve_check(_stealth_spec(seed)).natural_roll for seed in range(30)}
    assert len(samples) > 1


def test_roll_dice_str_is_reproducible_with_a_seeded_rng() -> None:
    first = [roll_dice_str("2d6+1", random.Random(7)) for _ in range(5)]
    second = [roll_dice_str("2d6+1", random.Random(7)) for _ in range(5)]
    assert first == second


def test_version_matches_installed_package_metadata() -> None:
    """``__version__`` is derived from packaging metadata, so it cannot drift
    from ``pyproject.toml`` the way the hand-maintained literal did."""
    from importlib.metadata import version

    assert __version__ == version("dnd5e-engine")
    assert __version__ != "0.0.0+unknown"
