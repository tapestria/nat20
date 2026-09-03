"""C16b — vision & light CONSUMERS: the composite ``_combatant_can_see``
predicate and every SRD 5.2 "can see" conjunct it feeds (Dodge, Ranged
Attacks in Close Combat, Opportunity Attacks, Hide, Frightened, Invisible).
Every rule quotes the SRD 5.2 sentence it pins."""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.orchestrator import (
    _combatant_can_see,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from dnd5e_engine.types.conditions import ActiveCondition
from tests.e2e.harness import cell, events_of, run_async


def _hero(**overrides):
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
        dexterity=16,
        attack_bonus=5,
        zone_id=cell(0, 0),
    )
    base.update(overrides)
    return PartyMemberSpec(**base)


def _foe(**overrides):
    base = dict(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=10,
        zone_id=cell(1, 0),
    )
    base.update(overrides)
    return EncounterMemberSpec(**base)


def _start(party, encounter, grid, seed=1, session="c16b"):
    async def _inner():
        start = await start_combat(
            session_id=session,
            party=party,
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid,
            rng_seed=seed,
        )
        return start.handle, _get_live(start.handle)

    return run_async(_inner())


def _combatant(live, entity_id):
    return next(c for c in live.initiative if c.entity_id == entity_id)


def _give_condition(live, entity_id, condition, source="implied:test"):
    c = _combatant(live, entity_id)
    c.conditions.append(
        ActiveCondition(condition=condition, source_entity_id=source, scope="combat")
    )
    live.active_conditions.setdefault(entity_id, set()).add(condition)


def _give_senses(live, entity_id, **senses):
    _combatant(live, entity_id).senses = CombatantSenses(**senses)


# ── Task 1: composite predicate ──────────────────────────────────────────


def test_combatant_can_see_lit_scene_defaults_true():
    _handle, live = _start([_hero()], [_foe()], GridScene(width=10, height=10))
    assert (
        _combatant_can_see(live, _combatant(live, "char:hero"), _combatant(live, "mon:foe")) is True
    )


def test_blinded_viewer_cannot_see_without_special_sense():
    """SRD 5.2 Blinded: "You can't see"."""
    _handle, live = _start([_hero()], [_foe()], GridScene(width=10, height=10))
    _give_condition(live, "char:hero", "blinded")
    hero, foe = _combatant(live, "char:hero"), _combatant(live, "mon:foe")
    assert _combatant_can_see(live, hero, foe) is False
    _give_senses(live, "char:hero", blindsight=10)
    assert _combatant_can_see(live, hero, foe) is True  # "even if you have the Blinded condition"
    _give_senses(live, "char:hero", blindsight=0)
    assert _combatant_can_see(live, hero, foe) is False  # out of range


def test_invisible_target_unseen_unless_blindsight_or_truesight():
    """SRD 5.2 Invisible / Blindsight / Truesight (R3): darkvision never pierces."""
    _handle, live = _start([_hero()], [_foe()], GridScene(width=10, height=10))
    _give_condition(live, "mon:foe", "invisible")
    hero, foe = _combatant(live, "char:hero"), _combatant(live, "mon:foe")
    assert _combatant_can_see(live, hero, foe) is False
    _give_senses(live, "char:hero", darkvision=60)
    assert _combatant_can_see(live, hero, foe) is False
    _give_senses(live, "char:hero", truesight=30)
    assert _combatant_can_see(live, hero, foe) is True
    _give_senses(live, "char:hero", blindsight=30)
    assert _combatant_can_see(live, hero, foe) is True


def test_composite_defers_to_scene_vision_for_darkness():
    grid = GridScene(width=10, height=10, lighting={cell(1, 0): "dark"})
    _handle, live = _start([_hero()], [_foe()], grid)
    hero, foe = _combatant(live, "char:hero"), _combatant(live, "mon:foe")
    assert _combatant_can_see(live, hero, foe) is False
    assert _combatant_can_see(live, foe, hero) is True  # directional


def test_untracked_position_is_always_seen():
    _handle, live = _start([_hero()], [_foe()], GridScene(width=10, height=10))
    hero, foe = _combatant(live, "char:hero"), _combatant(live, "mon:foe")
    del live.actor_zone["mon:foe"]
    _give_condition(live, "char:hero", "blinded")
    assert _combatant_can_see(live, hero, foe) is True


# ── Task 1: Ranged Attacks in Close Combat "who can see you" ─────────────


def test_ranged_in_melee_disadvantage_dropped_when_adjacent_hostile_is_blinded():
    """SRD 5.2: "within 5 feet of an enemy who can see you" — a Blinded
    adjacent enemy does not impose the disadvantage. Same-seed A/B."""

    def _party():
        return [_hero()]

    def _near_foe():
        return _foe(entity_id="mon:near", initiative=2, hp_current=10, zone_id=cell(1, 0))

    def _far_foe():
        return _foe(entity_id="mon:far", initiative=1, hp_current=100, zone_id=cell(6, 0))

    async def _run(blind_near: bool):
        start = await start_combat(
            session_id=f"c16b-ranged-in-melee-{blind_near}",
            party=_party(),
            encounter=[_far_foe(), _near_foe()],
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        if blind_near:
            _give_condition(live, "mon:near", "blinded")
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:far"),
        )
        return live

    live_a = run_async(_run(False))
    live_b = run_async(_run(True))

    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:far")
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:far")

    assert "ranged_in_melee" in rolled_a.sources
    assert "ranged_in_melee" not in rolled_b.sources
