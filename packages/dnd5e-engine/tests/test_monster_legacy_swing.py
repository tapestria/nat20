"""Template-less monsters attack via the legacy-field fallback.

specs.py has always documented that a missing ``monster_template_slug``
"falls back to the legacy damage_dice / damage_type single-attack
heuristic"; the typed-activity cutover dropped the fallback and such foes
silently passed every turn. The synthesized AttackActivity restores it.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    advance_monster_turn,
    cell_id,
    start_combat,
)
from dnd5e_engine.events import AttackRolled, DamageApplied, IntentSubmitted
from dnd5e_engine.orchestrator import _get_live


def _run(damage_dice: str, *, ac: int = 1):
    async def _inner():
        start = await start_combat(
            session_id="legacy-swing",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=200,
                    hp_max=200,
                    ac=ac,
                    zone_id=cell_id(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=12,
                    attack_bonus=10,
                    damage_dice=damage_dice,
                    damage_type="fire",
                    zone_id=cell_id(1, 0),
                )
            ],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        from dnd5e_engine import PlayerIntent
        from dnd5e_engine.orchestrator import submit_player_intent

        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        await advance_monster_turn(start.handle)
        return live

    return asyncio.run(_inner())


def test_template_less_monster_attacks_with_legacy_fields() -> None:
    live = _run("2d6")
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert attacks
    assert attacks[0].attacker_id == "mon:foe"
    intents = [
        e for e in live.event_log if isinstance(e, IntentSubmitted) and e.actor_id == "mon:foe"
    ]
    assert intents
    assert intents[-1].intent_type == "attack"
    # AC 1 + attack_bonus 10 ⇒ only a natural 1 misses; under seed 3 the hit lands.
    damage = [
        e for e in live.event_log if isinstance(e, DamageApplied) and e.target_id == "char:hero"
    ]
    assert damage
    assert damage[0].damage_type == "fire"
    assert damage[0].amount >= 2


def test_unparseable_damage_dice_still_noops() -> None:
    live = _run("banana")
    attacks = [e for e in live.event_log if isinstance(e, AttackRolled)]
    assert not attacks
    intents = [
        e for e in live.event_log if isinstance(e, IntentSubmitted) and e.actor_id == "mon:foe"
    ]
    assert intents
    assert intents[-1].intent_type == "pass"


def test_synthesize_helper_parses_bonus() -> None:
    from dnd5e_engine import orchestrator as orch
    from dnd5e_engine.types.combat import Combatant

    c = Combatant(
        entity_id="mon:x",
        entity_type="Monster",
        name="X",
        initiative=1,
        hp_current=10,
        hp_max=10,
        damage_dice="2d8+3",
        damage_type="cold",
    )
    act = orch._synthesize_attack_from_legacy_fields(c)
    assert act is not None
    part = act.damage.parts[0]
    assert (part.number, part.denomination, part.bonus, part.types) == (2, 8, "+3", ["cold"])
    assert (
        orch._synthesize_attack_from_legacy_fields(c.model_copy(update={"damage_dice": ""})) is None
    )
