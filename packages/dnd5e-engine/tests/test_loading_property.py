"""C15 Task 5 — Loading weapon property, one-shot-per-turn cap (closes
C15-S05).

SRD 5.2 Loading (verbatim): "You can fire only one piece of ammunition
from a Loading weapon when you use an action, a Bonus Action, or a
Reaction to fire it, regardless of the number of attacks you can
normally make." Engine reading: one fire per TURN — no PC reaction-attack
path exists, so action/bonus/reaction collapse to the turn boundary.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackFailed, AttackRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async

LIGHT_CROSSBOW = "light-crossbow"
LONGBOW = "longbow"


def _fighter5(entity_id: str = "char:hero", **overrides: object) -> PartyMemberSpec:
    kwargs: dict = dict(
        entity_id=entity_id,
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        dexterity=16,
        character_level=5,
        class_slug="fighter",
        zone_id=cell(0, 0),
    )
    kwargs.update(overrides)
    return PartyMemberSpec(**kwargs)


def _foe(entity_id: str = "mon:foe", initiative: int = 1, zone: str = cell(1, 0)):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name="Foe",
        initiative=initiative,
        hp_current=500,
        hp_max=500,
        ac=1,
        zone_id=zone,
    )


def _start(party, encounter, session_id: str):
    return start_combat(
        session_id=session_id,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=1,
    )


# ── (a) second same-turn shot with a Loading weapon is rejected ─────────


def test_second_same_turn_shot_with_loading_weapon_is_rejected():
    async def _run():
        start = await _start([_fighter5()], [_foe()], "c15-t5-a")
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    rolled = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(rolled) == 1, "the second Loading shot must not resolve an attack roll"
    failures = [
        e
        for e in events_of(live, AttackFailed)
        if e.actor_id == "char:hero" and e.target_id == "mon:foe"
    ]
    assert failures
    assert failures[-1].reason == "weapon_already_fired"
    assert live.current_actor_id == "char:hero", "the actor must keep the turn"


# ── (b) the crossbow fires again next turn ───────────────────────────────


def test_crossbow_fires_again_on_a_later_turn():
    async def _run():
        start = await _start(
            [_fighter5(initiative=20), _fighter5(entity_id="char:hero2", initiative=1)],
            [_foe(initiative=10)],
            "c15-t5-b",
        )
        live = _get_live(start.handle)
        # Turn 1 — hero fires the crossbow once.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        # mon:foe's turn (no-op it forward via monster turn if it's next).
        await advance_monster_turn(start.handle)
        # char:hero2's turn.
        await submit_player_intent(
            start.handle, actor_id="char:hero2", intent=PlayerIntent(intent_type="pass")
        )
        # Round wraps — hero's turn again.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    rolled = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(rolled) == 2, "the crossbow must fire again on the hero's next turn"


# ── (c) a non-Loading weapon fires twice fine (fighter-5, Extra Attack) ──


def test_non_loading_weapon_fires_twice_in_the_same_turn():
    async def _run():
        start = await _start([_fighter5()], [_foe()], "c15-t5-c")
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=LONGBOW, target_id="mon:foe"),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=LONGBOW, target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    rolled = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert len(rolled) == 2, "a non-Loading weapon is uncapped by this gate"
    failures = [
        e
        for e in events_of(live, AttackFailed)
        if e.actor_id == "char:hero" and e.reason == "weapon_already_fired"
    ]
    assert not failures


# ── (d) the flag is per-actor, not global ────────────────────────────────


def test_flag_is_per_actor_not_global():
    async def _run():
        start = await _start(
            [_fighter5(initiative=20), _fighter5(entity_id="char:hero2", initiative=19)],
            [_foe()],
            "c15-t5-d",
        )
        live = _get_live(start.handle)
        # hero fires its crossbow once, exhausting ITS cap this turn.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
        # hero2's turn — its own crossbow must be unaffected by hero's cap.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero2",
            intent=PlayerIntent(
                intent_type="attack", weapon_id=LIGHT_CROSSBOW, target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    rolled_hero2 = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:hero2"]
    assert len(rolled_hero2) == 1, "hero2's Loading cap must be independent of hero's"
    failures_hero2 = [
        e
        for e in events_of(live, AttackFailed)
        if e.actor_id == "char:hero2" and e.reason == "weapon_already_fired"
    ]
    assert not failures_hero2
