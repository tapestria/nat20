"""C12 — orchestrator-level condition gates (incapacitated, speed, charmed)."""

from __future__ import annotations

from typing import Any

import pytest

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    IntentSubmitted,
    MoveFailed,
    SaveRolled,
    TurnEnded,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _hero(**kw: Any) -> PartyMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        base_speed=30,
        zone_id=cell(0, 0),
    )
    base.update(kw)
    return PartyMemberSpec(**base)


def _foe(**kw: Any) -> EncounterMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=1,
        zone_id=cell(1, 0),
    )
    base.update(kw)
    return EncounterMemberSpec(**base)


def _status(target_id: str, *statuses: str, origin: str = "test:cond") -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{'-'.join(statuses)}:{target_id}",
        name="Cond",
        origin=origin,
        target_id=target_id,
        statuses=set(statuses),
    )


def _start(
    session: str,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    effects: Any = (),
) -> Any:
    return run_async(
        start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene(),
            active_effects=list(effects),
            rng_seed=1,
        )
    )


@pytest.mark.parametrize(
    "status", ["incapacitated", "paralyzed", "stunned", "petrified", "unconscious"]
)
def test_incapacitating_condition_rejects_an_attack(status: str) -> None:
    start = _start(f"c12-incap-{status}", [_hero()], [_foe()], [_status("char:hero", status)])
    with pytest.raises(IntentRejectedError) as exc:
        run_async(
            submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
        )
    assert exc.value.reason == "actor_incapacitated"
    live = _get_live(start.handle)
    assert not events_of(live, IntentSubmitted)  # rejected BEFORE IntentSubmitted


def test_incapacitated_actor_may_still_pass_the_turn() -> None:
    start = _start("c12-incap-pass", [_hero()], [_foe()], [_status("char:hero", "incapacitated")])
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    live = _get_live(start.handle)
    assert [e.actor_id for e in events_of(live, TurnEnded)] == ["char:hero"]


def test_stunned_actor_may_still_move_but_not_dash() -> None:
    # SRD 5.2 Stunned has no Speed clause; Dash is an action and is blocked.
    start = _start(
        "c12-stunned-move",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "stunned")],
    )
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 0)),
        )
    )
    assert _get_live(start.handle).actor_zone["char:hero"] == cell(1, 0)
    with pytest.raises(IntentRejectedError) as exc:
        run_async(
            submit_player_intent(
                start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dash")
            )
        )
    assert exc.value.reason == "actor_incapacitated"


def test_incapacitated_monster_turn_records_a_pass() -> None:
    start = _start(
        "c12-incap-monster",
        [_hero(initiative=1)],
        [_foe(initiative=20, monster_template_slug="goblin-warrior")],
        [_status("mon:foe", "paralyzed")],
    )
    # NOTE: slug is "goblin-warrior" (the brief said "goblin", which is not a
    # canonical SRD slug and would make this assertion vacuous via
    # monster_unresolved).
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert not events_of(live, AttackRolled)
    submitted = events_of(live, IntentSubmitted)
    assert submitted
    assert submitted[-1].actor_id == "mon:foe"
    assert submitted[-1].intent_type == "pass"


def _combatant(live: Any, entity_id: str) -> Any:
    return next(c for c in live.initiative if c.entity_id == entity_id)


@pytest.mark.parametrize(
    "status", ["grappled", "restrained", "paralyzed", "petrified", "unconscious"]
)
def test_speed_zero_condition_projects_zero_movement_and_fails_moves(status: str) -> None:
    start = _start(
        f"c12-speed0-{status}",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", status)],
    )
    live = _get_live(start.handle)
    assert _combatant(live, "char:hero").movement_remaining == 0
    run_async(
        submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 0)),
        )
    )
    failed = events_of(live, MoveFailed)
    assert failed
    assert failed[-1].reason == "speed_zero"
    assert live.actor_zone["char:hero"] == cell(0, 0)


def test_dash_cannot_increase_a_zero_speed() -> None:
    # SRD 5.2 Grappled: "Your Speed is 0 and can't increase."
    start = _start(
        "c12-speed0-dash",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "restrained")],
    )
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dash")
        )
    )
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 0


def test_exhaustion_reduces_the_movement_budget_by_five_feet_per_level() -> None:
    start = _start(
        "c12-exh-speed",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "exhaustion")],
    )
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 25


def test_unconditioned_actor_keeps_the_full_budget() -> None:
    start = _start("c12-speed-baseline", [_hero()], [_foe(zone_id=cell(5, 5))])
    assert _combatant(_get_live(start.handle), "char:hero").movement_remaining == 30


def test_speed_zero_monster_cannot_dash_toward_its_target() -> None:
    # SRD 5.2 Grappled: "Your Speed is 0 and can't increase." — the monster
    # approach gambit Dashes to close a gap it cannot otherwise cross; a
    # Speed-0 monster may not buy movement that way either.
    start = _start(
        "c12-speed0-monster-dash",
        [_hero(initiative=1, zone_id=cell(0, 0))],
        [_foe(initiative=20, zone_id=cell(3, 0), monster_template_slug="goblin-warrior")],
        [_status("mon:foe", "grappled")],
    )
    run_async(advance_monster_turn(start.handle))
    live = _get_live(start.handle)
    assert live.actor_zone["mon:foe"] == cell(3, 0)
    assert not [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:foe"]
    assert _combatant(live, "mon:foe").movement_remaining == 0


def test_end_of_turn_repeat_save_honours_auto_fail_and_restrained_disadvantage() -> None:
    """SRD 5.2 Conditions on the ORCHESTRATOR repeat-save path: a Paralyzed
    creature auto-fails STR/DEX saves (no d20 drawn) while an unaffected
    ability still rolls; a Restrained creature rolls DEX at disadvantage."""
    start = _start(
        "c12-repeat-save",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "paralyzed")],
    )
    live = _get_live(start.handle)
    live.repeat_save_on_turn_end[("char:hero", "effect:hold", "cast:hold-person:mon:foe")] = [
        {"ability": "wis", "dc": 13, "condition": "paralyzed", "caster_id": "mon:foe"}
    ]
    # ``pass`` is legal while Incapacitated and ends the turn.
    run_async(
        submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    saves = [e for e in events_of(live, SaveRolled) if e.target_id == "char:hero"]
    assert saves
    assert saves[-1].ability == "wis"
    # WIS is not auto-failed; the roll happened normally.
    assert saves[-1].natural is not None

    start2 = _start(
        "c12-repeat-save-dex",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "restrained")],
    )
    live2 = _get_live(start2.handle)
    live2.repeat_save_on_turn_end[("char:hero", "effect:web", "cast:web:mon:foe")] = [
        {"ability": "dex", "dc": 13, "condition": "restrained", "caster_id": "mon:foe"}
    ]
    run_async(
        submit_player_intent(
            start2.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    dex = [e for e in events_of(live2, SaveRolled) if e.target_id == "char:hero"][-1]
    assert dex.advantage == "disadvantage"
    assert "condition:target" in dex.sources

    start3 = _start(
        "c12-repeat-save-str",
        [_hero()],
        [_foe(zone_id=cell(5, 5))],
        [_status("char:hero", "paralyzed")],
    )
    live3 = _get_live(start3.handle)
    live3.repeat_save_on_turn_end[("char:hero", "effect:hold2", "cast:hold-person:mon:foe")] = [
        {"ability": "str", "dc": 13, "condition": "paralyzed", "caster_id": "mon:foe"}
    ]
    run_async(
        submit_player_intent(
            start3.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
        )
    )
    strength = [e for e in events_of(live3, SaveRolled) if e.target_id == "char:hero"][-1]
    assert strength.succeeded is False
    assert strength.natural is None
    assert strength.roll_total == 0
