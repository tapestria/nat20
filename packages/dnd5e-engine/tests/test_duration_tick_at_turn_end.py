"""Regression — ActiveEffect.duration.rounds decrements at turn end.

Codex Phase 6 review iter-6 P1: Phase 6 retired the host-side
``_sweep_effects`` that decremented rounds_remaining; without the
engine taking over, rounds-tracked effects persisted indefinitely.
The fix adds ``_tick_durations_at_turn_end`` at every TurnEnded
emission site (both player and monster paths). Effects with
``rounds is None`` (permanent / item-equipped / non-rounds duration)
are skipped; effects whose rounds counter reaches zero emit
EffectExpired and are removed from live.active_effects.

The bundled-asset-loader cutover (task 9-B) exempted
*concentration-flagged* effects from this tick: Foundry packs ship
``duration.rounds`` purely for the turn-tracker display (Bane's pack
ships ``rounds: 1``), so ticking a concentration spell would expire it
on the caster's own turn-end. Concentration governs those effects'
lifetime via the concentration cascade + per-turn repeat-save, not the
round counter. These tests therefore exercise the tick with
*non-concentration* rounds-tracked effects, which is the population the
tick still owns.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import PlayerIntent
from dnd5e_engine.orchestrator import (
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectDuration,
)


def _party():
    return [
        PartyMemberSpec(
            entity_id="char:hero",
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
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _topology():
    return SceneTopology(zones=["zone:start"], edges=[])


def test_rounds_decrement_at_player_turn_end():
    """A 3-round effect on the hero decrements to 2 after one turn end."""

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=3),
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-tick",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )
        live = _get_live(start.handle)
        # Pre-tick: 3 rounds.
        assert live.active_effects["char:hero"][0].duration.rounds == 3
        # Hero passes their turn.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return live

    live = asyncio.run(_run())
    # Post-tick: 2 rounds.
    assert "char:hero" in live.active_effects
    assert live.active_effects["char:hero"][0].duration.rounds == 2


def test_rounds_zero_expires_effect():
    """A 1-round effect → 0 rounds after one tick → EffectExpired + removal."""

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=1),
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-expire",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return _get_live(start.handle)

    live = asyncio.run(_run())
    # Effect was removed.
    assert not live.active_effects.get("char:hero")


def test_caster_keyed_tick_for_multi_target_effect():
    """A rounds-tracked effect on multiple targets should burn ONE round
    per caster turn — not one per target per round-cycle (Codex iter-7
    P1). Uses non-concentration effects: the cutover (task 9-B) exempts
    concentration-flagged effects from the round tick, so the caster-keyed
    tick is exercised on the population it still owns."""

    async def _run():
        # Two targets cast by the same caster (hero, highest initiative).
        bless1 = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:hero",
            target_id="char:hero",  # self-target
            duration=ActiveEffectDuration(rounds=10),
            flags={"concentration": False},
        )
        bless2 = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:hero",
            target_id="mon:foe",  # also on the monster (hypothetical, for test)
            duration=ActiveEffectDuration(rounds=10),
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-caster-tick",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless1, bless2),
        )
        live = _get_live(start.handle)
        # Hero's turn ends: BOTH Blesses (same caster) decrement once.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return live

    live = asyncio.run(_run())
    # Both effects went from 10 → 9 in ONE caster-turn-end.
    hero_bless = live.active_effects["char:hero"][0]
    monster_bless = live.active_effects["mon:foe"][0]
    assert hero_bless.duration.rounds == 9
    assert monster_bless.duration.rounds == 9


def test_no_tick_when_non_caster_turn_ends():
    """When a non-caster's turn ends, no tick fires on the caster's effects."""

    async def _run():
        # Effect's origin caster is "char:other", not "char:hero".
        eff = ActiveEffect(
            id="effect:test",
            name="Test",
            origin="cast:test:char:other",  # caster is "other"
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=10),
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-no-tick",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(eff,),
        )
        live = _get_live(start.handle)
        # Hero is not the caster — when their turn ends, the effect shouldn't tick.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return live

    live = asyncio.run(_run())
    assert live.active_effects["char:hero"][0].duration.rounds == 10


def test_permanent_effect_no_rounds_does_not_tick():
    """Item-equipped effects (rounds is None) survive turn ends untouched."""

    async def _run():
        sword = ActiveEffect(
            id="effect:weapon_plus_1",
            name="+1 Weapon",
            origin="item:sword_id:effect:weapon_plus_1",
            target_id="char:hero",
            duration=ActiveEffectDuration(),  # all None
        )
        start = await start_combat(
            session_id="sess-permanent",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(sword,),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return _get_live(start.handle)

    live = asyncio.run(_run())
    assert live.active_effects.get("char:hero")
    assert live.active_effects["char:hero"][0].id == "effect:weapon_plus_1"
    # Duration fields still None (no decrement).
    assert live.active_effects["char:hero"][0].duration.rounds is None
