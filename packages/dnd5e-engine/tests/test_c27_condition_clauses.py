"""The condition clauses the engine enforces on its own rolls and paths.

SRD 5.2 Frightened: "You have Disadvantage on ability checks and attack rolls
while the source of fear is within line of sight. You can't willingly move
closer to the source of fear." Poisoned: "You have Disadvantage on attack
rolls and ability checks." Petrified: "Poison Immunity. You have Immunity to
the Poisoned condition." Immunity: "it doesn't affect you in any way."
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    CheckRolled,
    CombatantMoved,
    ConditionApplied,
    ConditionRemoved,
    EffectApplied,
    EffectExpired,
    MoveFailed,
    SaveRolled,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
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


def _effect(name: str, *statuses: str, target_id: str = "mon:foe") -> ActiveEffect:
    # Named by ``name``, not by its statuses like ``_status``: two SEPARATE
    # effects that impose the SAME status need distinct ids.
    return ActiveEffect(
        id=f"effect:{name}",
        name=name,
        origin=f"test:{name}",
        target_id=target_id,
        statuses=set(statuses),
    )


def _apply_effect(live, effect: ActiveEffect) -> None:
    # A rider's own order (``activities/effects.py``): ``EffectApplied``
    # first, then its ``ConditionApplied``(s), sorted.
    _emit(live, EffectApplied(effect=effect))
    for status in sorted(effect.statuses):
        _emit(live, ConditionApplied(target_id=effect.target_id, condition=status))


_SESSION_SEQ = itertools.count()


def _start(party, encounter, *, seed: int = 1, grid: GridScene | None = None, effects=()):
    # ``start_combat``'s handle_id is ``f"combat:{session_id}:{seed:08x}"`` —
    # a test that starts two combats at the SAME (default) seed needs a
    # distinct session_id per call, or the second ``start_combat`` overwrites
    # the first's registry slot under an identical key.
    async def _inner():
        start = await start_combat(
            session_id=f"c27-condition-clauses-{next(_SESSION_SEQ)}",
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


def _typed_sources(live, entity_id: str) -> set[tuple[str, str | None]]:
    # Unlike ``_typed``, keeps each entry's ``source_effect_id`` — the
    # per-entry detail that tells two same-named entries apart.
    return {
        (ac.condition, ac.source_effect_id)
        for c in live.initiative
        if c.entity_id == entity_id
        for ac in c.conditions
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


def test_expiring_an_effect_drops_only_its_own_entry_not_a_withheld_one() -> None:
    # A poisons, B petrifies (granting Poisoned immunity), C also poisons —
    # withheld outright since B is already active when C is seeded. Letting
    # A expire must drop A's own Poisoned entry, not keep it alive on C's
    # never-landed listing; letting B expire afterwards must not resurrect
    # C's withheld Poisoned either. Both condition stores agree throughout.
    def _effect(name: str, *statuses: str) -> ActiveEffect:
        return ActiveEffect(
            id=f"effect:{name}",
            name=name,
            origin=f"test:{name}",
            target_id="mon:foe",
            statuses=set(statuses),
        )

    a, b, c = _effect("a", "poisoned"), _effect("b", "petrified"), _effect("c", "poisoned")
    _handle, live = _start([_hero()], [_foe()], effects=(a, b, c))
    assert _typed(live, "mon:foe") == {"poisoned", "petrified"}

    _emit(
        live,
        EffectExpired(effect_id=a.id, target_id="mon:foe", origin=a.origin, reason="duration"),
    )
    assert _typed(live, "mon:foe") == {"petrified"}
    assert live.active_conditions["mon:foe"] == {"petrified"}

    _emit(
        live,
        EffectExpired(effect_id=b.id, target_id="mon:foe", origin=b.origin, reason="duration"),
    )
    assert _typed(live, "mon:foe") == set()
    assert live.active_conditions.get("mon:foe", set()) == set()
    assert _build_hydration_payload(live)["check_modifiers"]["mon:foe"]["disadvantage"] is False


def test_two_runtime_effects_imposing_the_same_status_survive_independently() -> None:
    # Two mid-combat effects BOTH land Paralyzed, each through its own
    # EffectApplied-then-ConditionApplied rider order. E1 timing out must
    # drop only E1's own entry, leaving E2's; E2 timing out afterwards must
    # then clear Paralyzed from both stores.
    e1, e2 = _effect("e1", "paralyzed"), _effect("e2", "paralyzed")
    _handle, live = _start([_hero()], [_foe()])
    _apply_effect(live, e1)
    _apply_effect(live, e2)
    assert _typed_sources(live, "mon:foe") == {("paralyzed", e1.id), ("paralyzed", e2.id)}
    assert live.active_conditions["mon:foe"] == {"paralyzed"}

    _emit(
        live,
        EffectExpired(effect_id=e1.id, target_id="mon:foe", origin=e1.origin, reason="duration"),
    )
    assert _typed_sources(live, "mon:foe") == {("paralyzed", e2.id)}
    assert live.active_conditions["mon:foe"] == {"paralyzed"}

    _emit(
        live,
        EffectExpired(effect_id=e2.id, target_id="mon:foe", origin=e2.origin, reason="duration"),
    )
    assert _typed_sources(live, "mon:foe") == set()
    assert live.active_conditions.get("mon:foe", set()) == set()


def test_two_runtime_effects_imposing_the_same_status_survive_a_save_ends_removal() -> None:
    # Same stacking, but E1 ends the way a repeat-save's success or a
    # concentration drop does: EffectExpired immediately followed by its own
    # ConditionRemoved for the status it carried (``_drop_concentration``;
    # the save-ends repeat-save path). E2's independent entry must still
    # carry Paralyzed afterwards, in both stores.
    e1, e2 = _effect("e1", "paralyzed"), _effect("e2", "paralyzed")
    _handle, live = _start([_hero()], [_foe()])
    _apply_effect(live, e1)
    _apply_effect(live, e2)

    _emit(
        live,
        EffectExpired(
            effect_id=e1.id, target_id="mon:foe", origin=e1.origin, reason="concentration_drop"
        ),
    )
    _emit(live, ConditionRemoved(target_id="mon:foe", condition="paralyzed"))
    assert _typed_sources(live, "mon:foe") == {("paralyzed", e2.id)}
    assert live.active_conditions["mon:foe"] == {"paralyzed"}


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


def test_escaping_a_seeded_grappled_is_refused_before_the_action_is_spent() -> None:
    # A seeded Grappled stores no escape DC, so there is nothing to roll
    # against: refused before the Action is spent, with no d20.
    handle, live = _start([_hero()], [_foe()], effects=(_status("char:hero", "grappled"),))
    with pytest.raises(IntentRejectedError) as rejected:
        _act(handle, "char:hero", intent_type="escape_grapple")
    assert rejected.value.reason == "target_invalid"
    assert events_of(live, CheckRolled) == []
    assert next(c for c in live.initiative if c.entity_id == "char:hero").action_available


def test_escaping_an_effects_grappled_left_after_the_grapple_ends_is_refused() -> None:
    # The bandit grapples the hero and an effect also Grapples it; the bandit
    # is then Stunned, which ends its grapple. The effect's Grappled stays and
    # stores no escape DC: the escape is refused, not crashed.
    handle, live = _start(
        [_hero(initiative=1)], [_foe(initiative=20, monster_template_slug="bandit")]
    )
    _act(handle, "mon:foe", intent_type="grapple", target_id="char:hero")
    _apply_effect(live, _effect("hold", "grappled", target_id="char:hero"))
    _apply_effect(live, _effect("stun", "stunned"))
    assert _typed_sources(live, "char:hero") == {("grappled", "effect:hold")}
    with pytest.raises(IntentRejectedError) as rejected:
        _act(handle, "char:hero", intent_type="escape_grapple")
    assert rejected.value.reason == "target_invalid"
    assert [e for e in events_of(live, CheckRolled) if e.actor_id == "char:hero"] == []
