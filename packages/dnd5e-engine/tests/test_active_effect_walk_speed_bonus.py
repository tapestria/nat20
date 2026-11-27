"""A ``speed.walk.bonus`` change on a combatant's active effects raises its
walking Speed for as long as the effect lasts.

SRD 5.2 §Movement and Position — a creature can move a distance up to its
Speed on its turn; an item or spell that increases Speed raises that budget.
Speed-0 conditions still win (SRD 5.2 Grappled: "Your Speed is 0 and can't
increase").
"""

from __future__ import annotations

from typing import Any

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import ActorMoved, MoveFailed
from dnd5e_engine.orchestrator import (
    _effective_speed,
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange, ActiveEffectDuration
from tests.e2e.harness import cell, events_of, grid_scene, run_async

_HERO = "char:hero"


def _hero() -> PartyMemberSpec:
    return PartyMemberSpec(
        entity_id=_HERO,
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        base_speed=30,
        zone_id=cell(0, 0),
    )


def _foe() -> EncounterMemberSpec:
    return EncounterMemberSpec(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        zone_id=cell(9, 9),
    )


def _speed_bonus(
    value: int | str = 10,
    *,
    mode: Any = "add",
    duration: ActiveEffectDuration | None = None,
) -> ActiveEffect:
    return ActiveEffect(
        id="effect:swift-boots",
        name="Swift Boots",
        origin="item:swift-boots",
        target_id=_HERO,
        changes=[ActiveEffectChange(key="speed.walk.bonus", mode=mode, value=value)],
        duration=duration or ActiveEffectDuration(),
    )


def _status(*statuses: str) -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{'-'.join(statuses)}",
        name="Cond",
        origin="test:cond",
        target_id=_HERO,
        statuses=set(statuses),
    )


def _start(session: str, effects: list[ActiveEffect]) -> Any:
    return run_async(
        start_combat(
            session_id=session,
            party=[_hero()],
            encounter=[_foe()],
            grid_scene=grid_scene(),
            active_effects=effects,
            rng_seed=1,
        )
    )


def _hero_combatant(live: Any) -> Any:
    return next(c for c in live.initiative if c.entity_id == _HERO)


def _move(handle: Any, col: int) -> None:
    run_async(
        submit_player_intent(
            handle,
            actor_id=_HERO,
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(col, 0)),
        )
    )


def test_walk_speed_bonus_raises_the_turn_movement_budget() -> None:
    start = _start("walk-bonus-budget", [_speed_bonus(10)])
    live = _get_live(start.handle)
    assert _hero_combatant(live).movement_remaining == 40


def test_walk_speed_bonus_lets_a_move_cover_the_extra_distance() -> None:
    plain = _start("walk-bonus-plain", [])
    _move(plain.handle, 8)  # 40 ft: past a 30 ft Speed
    plain_live = _get_live(plain.handle)
    assert events_of(plain_live, MoveFailed)[-1].reason == "insufficient_movement"
    assert plain_live.actor_zone[_HERO] == cell(0, 0)

    boosted = _start("walk-bonus-move", [_speed_bonus(10)])
    _move(boosted.handle, 8)
    live = _get_live(boosted.handle)
    assert not events_of(live, MoveFailed)
    assert events_of(live, ActorMoved)
    assert live.actor_zone[_HERO] == cell(8, 0)
    assert _hero_combatant(live).movement_remaining == 0


def test_speed_zero_condition_overrides_the_walk_speed_bonus() -> None:
    start = _start("walk-bonus-grappled", [_speed_bonus(10), _status("grappled")])
    live = _get_live(start.handle)
    assert _hero_combatant(live).movement_remaining == 0


def test_exhaustion_and_slow_apply_after_the_walk_speed_bonus() -> None:
    # SRD 5.2 Exhaustion: Speed is reduced by 5 feet times the level; SRD 5.2
    # §Weapon Mastery, Slow: a flat 10 ft more.
    start = _start("walk-bonus-exhaustion", [_speed_bonus(10)])
    live = _get_live(start.handle)
    hero = _hero_combatant(live).model_copy(
        update={
            "conditions": [
                ActiveCondition(
                    condition="exhaustion",
                    source_entity_id="implied:scenario",
                    scope="combat",
                    exhaustion_level=2,
                )
            ]
        }
    )
    assert _effective_speed(hero, live) == 30
    live.slow_marks[_HERO] = {"mon:foe"}
    assert _effective_speed(hero, live) == 20


def test_walk_speed_bonus_lapses_when_the_effect_expires() -> None:
    start = _start(
        "walk-bonus-expiry",
        [_speed_bonus(10, duration=ActiveEffectDuration(turns=1))],
    )
    live = _get_live(start.handle)
    assert _hero_combatant(live).movement_remaining == 40
    run_async(
        submit_player_intent(start.handle, actor_id=_HERO, intent=PlayerIntent(intent_type="pass"))
    )
    run_async(advance_monster_turn(start.handle))
    assert live.initiative[live.current_turn_index].entity_id == _HERO
    assert _hero_combatant(live).movement_remaining == 30


def test_only_additive_walk_speed_changes_are_read() -> None:
    # The key names an additive bonus; a non-add mode or a dice value has no
    # flat walking-speed meaning and leaves Speed unchanged.
    for effect in (_speed_bonus(30, mode="upgrade"), _speed_bonus("1d4")):
        start = _start(f"walk-bonus-ignored-{effect.changes[0].mode}", [effect])
        assert _hero_combatant(_get_live(start.handle)).movement_remaining == 30
