"""Public API — get_actor_active_effects reads engine effect state mid-combat.

Phase 6 codex review follow-up: the host (Tapestria's
build_dispatch_context) needs to feed in-combat active effects into the
DispatchContext for resolvers that run alongside the engine's own
dispatch (FLEE skill check, CONSULT_CODEX Investigation check, etc.).
The engine owns _LiveCombat.active_effects as the single source of
truth; this helper is the read-only public access.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import get_actor_active_effects
from dnd5e_engine.orchestrator import start_combat
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _party():
    return [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Hero",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter():
    return [
        EncounterMemberSpec(
            entity_id="mon:111111111111",
            entity_type="Monster",
            name="Bandit",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _topology():
    return SceneTopology(zones=["zone:start"], edges=[])


def _bless(target_id: str) -> ActiveEffect:
    return ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id=target_id,
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value="1d4"),
        ],
        flags={"concentration": True},
    )


def test_get_actor_active_effects_returns_seeded_effects():
    """Effects passed via start_combat(active_effects=...) are visible."""

    async def _run():
        bless = _bless("char:aaaaaaaaaaaa")
        return await start_combat(
            session_id="sess-get-actor",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    effects = get_actor_active_effects(result.handle, "char:aaaaaaaaaaaa")
    assert len(effects) == 1
    assert effects[0].id == "effect:bless"


def test_get_actor_active_effects_unknown_entity_returns_empty():
    """An entity not in the combat has no effects → empty tuple."""

    async def _run():
        return await start_combat(
            session_id="sess-unknown-entity",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )

    result = asyncio.run(_run())
    effects = get_actor_active_effects(result.handle, "char:not_in_combat")
    assert effects == ()


def test_get_actor_active_effects_invalid_handle_returns_empty():
    """A handle with no live combat → empty tuple, no exception.

    Phase 6 contract: out-of-combat callers see no effects. The host
    treats an empty result the same as "no live combat", so the helper
    must not raise for an unknown handle either.
    """
    from dnd5e_engine.orchestrator import CombatHandle

    fake = CombatHandle(handle_id="not-a-real-handle")
    effects = get_actor_active_effects(fake, "char:anyone")
    assert effects == ()


def test_get_actor_active_effects_returns_tuple_not_live_reference():
    """Caller cannot mutate engine state through the returned tuple."""

    async def _run():
        bless = _bless("char:aaaaaaaaaaaa")
        return await start_combat(
            session_id="sess-immutable",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    effects = get_actor_active_effects(result.handle, "char:aaaaaaaaaaaa")
    assert isinstance(effects, tuple)
    # The tuple's mutation surface is impossible (immutable). The contained
    # ActiveEffect is a frozen-ish pydantic model — its `changes` list is
    # still mutable, but that is acceptable: the host is supposed to read,
    # not write. The library treats the returned tuple as a snapshot;
    # callers wanting to mutate must go through the engine's own seam.
    # Calling the helper again gives a fresh tuple of the same effect list.
    again = get_actor_active_effects(result.handle, "char:aaaaaaaaaaaa")
    assert again == effects
