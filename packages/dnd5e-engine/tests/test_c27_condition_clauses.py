"""The condition clauses the engine enforces on its own rolls and paths.

SRD 5.2 Frightened: "You have Disadvantage on ability checks and attack rolls
while the source of fear is within line of sight. You can't willingly move
closer to the source of fear." Poisoned: "You have Disadvantage on attack
rolls and ability checks." Petrified: "Poison Immunity. You have Immunity to
the Poisoned condition." Immunity: "it doesn't affect you in any way."
"""

from __future__ import annotations

from typing import Any

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    CheckRolled,
    CombatantMoved,
    ConditionApplied,
    EffectApplied,
    MoveFailed,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    _build_hydration_payload,
    _emit,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def _hero(**fields: Any) -> PartyMemberSpec:
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _foe(**fields: Any) -> EncounterMemberSpec:
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 1,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _status(target_id: str, *statuses: str, by: str = "mon:foe") -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{'-'.join(sorted(statuses))}:{target_id}",
        name="Condition",
        origin=f"cast:condition:{by}",
        target_id=target_id,
        statuses=set(statuses),
    )


def _start(party, encounter, *, seed: int = 1, grid: GridScene | None = None, effects=()):
    async def _inner():
        start = await start_combat(
            session_id="c27-condition-clauses",
            party=party,
            encounter=encounter,
            grid_scene=grid or grid_scene(),
            rng_seed=seed,
            active_effects=list(effects),
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _act(handle, actor_id: str, **intent: Any) -> None:
    run_async(submit_player_intent(handle, actor_id=actor_id, intent=PlayerIntent(**intent)))


def _typed(live, entity_id: str) -> set[str]:
    return {
        ac.condition for c in live.initiative if c.entity_id == entity_id for ac in c.conditions
    }


# ── Frightened / Poisoned on ability checks ──────────────────────────────────


def test_the_check_projection_drops_frightened_disadvantage_when_the_source_is_unseen() -> None:
    # The projection every CheckActivity reads: Disadvantage only while the
    # hero can see the creature it fears.
    for dark, expected in ((False, True), (True, False)):
        grid = grid_scene(lighting={cell(1, 0): "dark"} if dark else {})
        _handle, live = _start(
            [_hero()], [_foe()], grid=grid, effects=(_status("char:hero", "frightened"),)
        )
        payload = _build_hydration_payload(live)
        assert payload["check_modifiers"]["char:hero"]["disadvantage"] is expected


def test_a_poisoned_creature_escapes_a_grapple_at_disadvantage() -> None:
    handle, live = _start(
        [_hero(initiative=1)],
        [_foe(initiative=20, monster_template_slug="bandit")],
        effects=(_status("char:hero", "poisoned"),),
    )
    _act(handle, "mon:foe", intent_type="grapple", target_id="char:hero")
    _act(handle, "char:hero", intent_type="escape_grapple")
    escape = next(e for e in events_of(live, CheckRolled) if e.actor_id == "char:hero")
    assert (escape.advantage, escape.sources) == ("disadvantage", ["condition:attacker"])


# ── Frightened: no approach, seen or not ─────────────────────────────────────


def test_a_frightened_creature_may_approach_a_dead_or_unknown_source() -> None:
    # Nothing to move closer to: an unknown source (no creature named) or a
    # dead one imposes no restriction.
    unknown = ActiveEffect(
        id="effect:frightened:char:hero",
        name="Frightened",
        origin="test:frightened",
        target_id="char:hero",
        statuses={"frightened"},
    )
    handle, live = _start([_hero()], [_foe(zone_id=cell(5, 0))], effects=(unknown,))
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(1, 0))
    assert events_of(live, MoveFailed) == []
    assert live.actor_zone["char:hero"] == cell(1, 0)

    handle, live = _start(
        [_hero()],
        [_foe(zone_id=cell(5, 0))],
        effects=(_status("char:hero", "frightened"),),
    )
    foe = next(c for c in live.initiative if c.entity_id == "mon:foe")
    foe.is_alive = False
    _act(handle, "char:hero", intent_type="move", target_zone_id=cell(1, 0))
    assert events_of(live, MoveFailed) == []
    assert [e.to_zone for e in events_of(live, ActorMoved)] == [cell(1, 0)]


# ── one immunity check on every action and effect path ───────────────────────


def test_shoving_a_ghost_prone_rolls_the_save_but_leaves_it_standing() -> None:
    # SRD 5.2 Ghost: "Condition Immunities ... Prone ..."; the push still lands.
    for push in (False, True):
        handle, live = _start([_hero(strength=16)], [_foe(monster_template_slug="ghost")], seed=1)
        _act(handle, "char:hero", intent_type="shove", target_id="mon:foe", shove_push=push)
        assert [(e.target_id, e.succeeded) for e in events_of(live, SaveRolled)] == [
            ("mon:foe", False)
        ]
        assert events_of(live, ConditionApplied) == []
        assert "prone" not in _typed(live, "mon:foe")
        assert [e.actor_id for e in events_of(live, CombatantMoved)] == (
            ["mon:foe"] if push else []
        )


def test_an_effect_that_petrifies_and_poisons_leaves_its_target_petrified_only() -> None:
    # The start_combat seed and the mid-combat EffectApplied fold read the same
    # predicate.
    _handle, live = _start(
        [_hero()], [_foe()], effects=(_status("mon:foe", "petrified", "poisoned"),)
    )
    assert _typed(live, "mon:foe") == {"petrified"}
    assert live.active_conditions["mon:foe"] == {"petrified"}

    _handle, live = _start([_hero()], [_foe()])
    _emit(live, EffectApplied(effect=_status("mon:foe", "petrified", "poisoned")))
    assert _typed(live, "mon:foe") == {"petrified"}


def test_a_hider_immune_to_invisible_is_not_hidden() -> None:
    dark = grid_scene(lighting={cell(0, 0): "dark"})
    handle, live = _start(
        [_hero(dexterity=20, condition_immunities=["invisible"])],
        [_foe(zone_id=cell(5, 0))],
        seed=7,
        grid=dark,
    )
    _act(handle, "char:hero", intent_type="hide")
    assert [e.succeeded for e in events_of(live, CheckRolled)] == [True]
    assert events_of(live, ConditionApplied) == []
    assert "char:hero" not in live.hidden_entities
