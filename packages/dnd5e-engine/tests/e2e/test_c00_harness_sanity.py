"""C00 — harness sanity: a seeded zone combat runs end-to-end green."""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import events_of, run_async, single_zone


def test_c00_harness_sanity_seeded_attack():
    async def _run():
        start = await start_combat(
            session_id="e2e-c00-sanity",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    strength=16,
                    zone_id="zone:start",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=1,
                    zone_id="zone:start",
                )
            ],
            scene_zones=single_zone(),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="mace", target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    attacks = events_of(live, AttackRolled)
    assert attacks
    assert attacks[0].is_hit
