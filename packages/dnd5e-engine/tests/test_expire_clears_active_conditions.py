"""Regression — expiring an effect clears its statuses from active_conditions.

Codex Phase 6 review iter-8 P1: the EffectExpired path only updated
``initiative[*].conditions`` but left ``live.active_conditions``
untouched. ``orchestrator_bridge.project_combat_state_to_redis``
reads ``active_conditions`` to mirror combatant conditions into Redis,
so the projection would re-attach the expired condition on the next
mirror tick. This test locks the fix that ``active_conditions`` also
clears the status when its imposing effect expires.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import PlayerIntent
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
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


def test_status_clears_from_active_conditions_when_effect_expires():
    """A 1-round seeded paralyzed effect expires → active_conditions
    no longer contains 'paralyzed'.
    """

    async def _run():
        # Seed Hold Person-style effect with 1 round duration. The
        # caster is encoded in origin so the tick fires at the
        # caster's turn-end (which is hero's, since hero is the caster).
        hold = ActiveEffect(
            id="effect:hold_person",
            name="Hold Person",
            origin="cast:hold_person:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(rounds=1),
            statuses={"paralyzed"},
            # Non-concentration: the cutover (task 9-B) exempts
            # concentration-flagged effects from the round tick, so this
            # test exercises the status-clear-on-expiry path via a
            # rounds-tracked effect.
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-expire-status",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(hold,),
        )
        live = _get_live(start.handle)
        # Pre-tick: paralyzed is in active_conditions.
        assert "paralyzed" in live.active_conditions.get("mon:foe", set())
        # Hero's turn ends → caster-keyed tick decrements rounds to 0
        # → EffectExpired emits → status clears.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return live

    live = asyncio.run(_run())
    # The active_effects list is empty for mon:foe.
    assert not live.active_effects.get("mon:foe"), (
        "EffectExpired should have removed the Hold Person effect from "
        "active_effects"
    )
    # And — the load-bearing assertion — active_conditions no longer
    # contains 'paralyzed'.
    remaining = live.active_conditions.get("mon:foe", set())
    assert "paralyzed" not in remaining, (
        "expired effect's status must also be removed from "
        "live.active_conditions — otherwise the orchestrator_bridge "
        "projection re-attaches it to session state on the next mirror "
        f"tick. got: {remaining!r}"
    )


def test_status_stays_when_another_active_effect_still_imposes_it():
    """If two effects impose the same status and one expires, the status
    remains in active_conditions (the other effect still imposes it)."""

    async def _run():
        eff1 = ActiveEffect(
            id="effect:hold_person",
            name="Hold Person 1",
            origin="cast:hold_person:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(rounds=1),  # expires after 1 caster turn
            statuses={"paralyzed"},
            flags={"concentration": False},
        )
        eff2 = ActiveEffect(
            id="effect:hold_person_b",
            name="Hold Person 2",
            origin="cast:hold_person_b:char:hero",
            target_id="mon:foe",
            duration=ActiveEffectDuration(rounds=10),  # still alive
            statuses={"paralyzed"},
            flags={"concentration": False},
        )
        start = await start_combat(
            session_id="sess-stacked-status",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(eff1, eff2),
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="pass"),
        )
        return live

    live = asyncio.run(_run())
    # First effect expired; second is still alive.
    remaining_active = live.active_effects.get("mon:foe", [])
    assert len(remaining_active) == 1
    assert remaining_active[0].id == "effect:hold_person_b"
    # paralyzed STAYS in active_conditions because the second effect still imposes it.
    remaining_cond = live.active_conditions.get("mon:foe", set())
    assert "paralyzed" in remaining_cond, (
        "paralyzed must persist while at least one other active effect "
        "still imposes it"
    )
