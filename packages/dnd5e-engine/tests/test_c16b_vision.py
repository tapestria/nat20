"""C16b — vision & light CONSUMERS: the composite ``_combatant_can_see``
predicate and every SRD 5.2 "can see" conjunct it feeds (Dodge, Ranged
Attacks in Close Combat, Opportunity Attacks, Hide, Frightened, Invisible).
Every rule quotes the SRD 5.2 sentence it pins."""

from __future__ import annotations

import pytest

from dnd5e_engine import PlayerIntent
from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.events import AttackRolled, CheckRolled
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _combatant_can_see,
    _fire_monster_opportunity_attacks_on_move,
    _fire_pc_opportunity_attacks_on_move,
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


def _attacks(live, attacker_id):
    return [e for e in events_of(live, AttackRolled) if e.attacker_id == attacker_id]


def _run(coro):
    return run_async(coro)


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


# ── Task 2: Dodge "if you can see the attacker" ──────────────────────────


def test_dodge_disadvantage_dropped_when_dodger_cannot_see_attacker():
    """SRD 5.2 Dodge: "any attack roll made against you has Disadvantage if
    you can see the attacker". Same-seed A/B: foe dodges; hero attacks from a
    dark cell (foe has no darkvision) → no "dodge" source."""

    async def run(dark: bool):
        grid = GridScene(width=10, height=10, lighting={cell(0, 0): "dark"} if dark else {})
        start = await start_combat(
            session_id=f"c16b-dodge-{dark}",
            party=[_hero(initiative=1)],
            encounter=[_foe(initiative=20)],
            scene_zones=None,
            grid_scene=grid,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        # foe (initiative 20) acts first: flag it as dodging directly
        # (mirrors tests/test_dodge_help_hide.py's ``c.dodging = True``
        # seam — no engine-sanctioned monster-dodge AI path exists) and
        # advance the turn pointer past it (test-only seam, same class as
        # the direct condition/dodging writes above) to hero's turn.
        _combatant(live, "mon:foe").dodging = True
        live.current_turn_index = 1
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return _attacks(live, "char:hero")[0]

    lit = run_async(run(False))
    dark = run_async(run(True))
    assert "dodge" in lit.sources
    assert "dodge" not in dark.sources
    assert (
        "unseen" in dark.sources
    )  # foe can't see the hero → hero has advantage (pre-existing producer)


# ── Task 2: Opportunity Attacks "a creature that you can see" ────────────


def test_opportunity_attack_not_triggered_when_reactor_cannot_see_mover():
    """SRD 5.2: "when a creature that you can see leaves your reach". A
    Blinded reactor makes no opportunity attack and keeps its Reaction."""

    grid = GridScene(width=10, height=10)
    _handle, live = _start([_hero()], [_foe(zone_id=cell(0, 0))], grid)
    _give_condition(live, "char:hero", "blinded")
    _fire_pc_opportunity_attacks_on_move(
        live, mover_id="mon:foe", from_zone=cell(0, 0), to_zone=cell(5, 5)
    )
    assert _attacks(live, "char:hero") == []
    assert _combatant(live, "char:hero").reaction_available is True


def test_opportunity_attack_has_advantage_when_mover_cannot_see_reactor():
    """Unseen Attackers and Targets on the AoO roll: the mover is Blinded →
    the reactor's AoO carries the "unseen" advantage source."""

    grid = GridScene(width=10, height=10)
    _handle, live = _start([_hero()], [_foe(zone_id=cell(0, 0))], grid)
    _give_condition(live, "mon:foe", "blinded")
    _fire_pc_opportunity_attacks_on_move(
        live, mover_id="mon:foe", from_zone=cell(0, 0), to_zone=cell(5, 5)
    )
    rolled = _attacks(live, "char:hero")[0]
    assert "unseen" in rolled.sources
    assert "condition:target" in rolled.sources


def test_opportunity_attack_not_triggered_when_monster_reactor_cannot_see_mover():
    """SRD 5.2: "when a creature that you can see leaves your reach" — the
    monster-reactor / PC-mover mirror of the PC-reactor test above. A
    Blinded monster reactor makes no opportunity attack and keeps its
    Reaction."""

    grid = GridScene(width=10, height=10)
    _handle, live = _start([_hero()], [_foe(zone_id=cell(0, 0))], grid)
    _give_condition(live, "mon:foe", "blinded")
    _fire_monster_opportunity_attacks_on_move(
        live, mover_id="char:hero", from_zone=cell(0, 0), to_zone=cell(5, 5)
    )
    assert _attacks(live, "mon:foe") == []
    assert _combatant(live, "mon:foe").reaction_available is True


def test_opportunity_attack_has_advantage_when_pc_mover_cannot_see_monster_reactor():
    """Unseen Attackers and Targets on the monster-reactor AoO roll: the PC
    mover is Blinded → the reactor's AoO carries the "unseen" advantage
    source."""

    grid = GridScene(width=10, height=10)
    _handle, live = _start([_hero()], [_foe(zone_id=cell(0, 0))], grid)
    _give_condition(live, "char:hero", "blinded")
    _fire_monster_opportunity_attacks_on_move(
        live, mover_id="char:hero", from_zone=cell(0, 0), to_zone=cell(5, 5)
    )
    rolled = _attacks(live, "mon:foe")[0]
    assert "unseen" in rolled.sources
    assert "condition:target" in rolled.sources


# ── Task 3: Invisible carve-out end-to-end ───────────────────────────────


def test_attack_on_invisible_target_normal_when_attacker_has_blindsight():
    """Same-seed A/B: foe Invisible. Run A hero has no special sense →
    "condition:target" disadvantage. Run B hero has blindsight 30 → no
    condition:target source, advantage mode "normal"."""

    async def run(has_blindsight: bool):
        grid = GridScene(width=10, height=10)
        start = await start_combat(
            session_id=f"c16b-t3-target-invis-{has_blindsight}",
            party=[_hero()],
            encounter=[_foe()],
            scene_zones=None,
            grid_scene=grid,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        _give_condition(live, "mon:foe", "invisible")
        if has_blindsight:
            _give_senses(live, "char:hero", blindsight=30)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return _attacks(live, "char:hero")[0]

    no_sense = run_async(run(False))
    blindsight = run_async(run(True))

    assert "condition:target" in no_sense.sources
    assert no_sense.advantage == "disadvantage"
    assert "condition:target" not in blindsight.sources
    assert blindsight.advantage == "normal"


def test_invisible_attacker_loses_advantage_against_truesight_target():
    """Hero Invisible (e.g. after a successful Hide, or a bare condition);
    foe with truesight 30 → the hero's attack has NO "condition:attacker"
    advantage source."""

    async def run(foe_truesight: bool):
        grid = GridScene(width=10, height=10)
        start = await start_combat(
            session_id=f"c16b-t3-attacker-invis-{foe_truesight}",
            party=[_hero()],
            encounter=[_foe()],
            scene_zones=None,
            grid_scene=grid,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        _give_condition(live, "char:hero", "invisible")
        if foe_truesight:
            _give_senses(live, "mon:foe", truesight=30)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="dagger", target_id="mon:foe"),
        )
        return _attacks(live, "char:hero")[0]

    no_pierce = run_async(run(False))
    pierced = run_async(run(True))

    assert "condition:attacker" in no_pierce.sources
    assert no_pierce.advantage == "advantage"
    assert "condition:attacker" not in pierced.sources
    assert pierced.advantage == "normal"


def test_opportunity_attack_against_invisible_mover_seen_by_blindsight_is_normal():
    """AoO path threads the same booleans: reactor with blindsight vs an
    Invisible mover → no condition:target disadvantage on the AoO. Same-seed
    A/B: run A (no special sense) never triggers the AoO at all — the
    trigger gate (``_combatant_can_see``) itself requires a special sense to
    see an Invisible mover, SRD 5.2 "a creature that you can see". Run B
    (blindsight 30) triggers the AoO and pierces the SAME Invisible
    condition for the condition-derived disadvantage row, so
    "condition:target" is absent."""

    def run(has_blindsight: bool):
        grid = GridScene(width=10, height=10)
        _handle, live = _start(
            [_hero()], [_foe(zone_id=cell(0, 0))], grid, session=f"c16b-t3-aoo-{has_blindsight}"
        )
        _give_condition(live, "mon:foe", "invisible")
        if has_blindsight:
            _give_senses(live, "char:hero", blindsight=30)
        _fire_pc_opportunity_attacks_on_move(
            live, mover_id="mon:foe", from_zone=cell(0, 0), to_zone=cell(5, 5)
        )
        return _attacks(live, "char:hero")

    no_sense = run(False)
    blindsight = run(True)

    assert no_sense == []
    assert len(blindsight) == 1
    assert "condition:target" not in blindsight[0].sources


# ── Task 4: Hide line-of-sight gate ──────────────────────────────────────


def test_hide_behind_three_quarters_cover_still_allowed_with_adjacent_enemy():
    """R1: per-cell cover already breaks line of sight for every viewer —
    the approved C14-S02 shape stays legal."""
    grid = GridScene(width=10, height=10, cover_cells={cell(0, 0): "three_quarters"})
    handle, live = _start([_hero()], [_foe()], grid)
    _run(
        submit_player_intent(handle, actor_id="char:hero", intent=PlayerIntent(intent_type="hide"))
    )
    assert [e for e in events_of(live, CheckRolled) if e.skill == "stealth"]


def test_hide_in_darkness_is_allowed_and_rejected_when_enemy_has_darkvision():
    """R2: "An area of darkness is Heavily Obscured." + R1: an enemy whose
    darkvision reaches the dark cell can see the hider → target_invalid, no
    d20 draw."""
    grid = GridScene(width=10, height=10, lighting={cell(0, 0): "dark"})
    handle, live = _start([_hero()], [_foe()], grid)
    _run(
        submit_player_intent(handle, actor_id="char:hero", intent=PlayerIntent(intent_type="hide"))
    )
    assert [e for e in events_of(live, CheckRolled) if e.skill == "stealth"]

    handle2, live2 = _start([_hero()], [_foe()], grid, session="c16b-dv")
    _give_senses(live2, "mon:foe", darkvision=60)
    before = live2.rng.getstate() if hasattr(live2.rng, "getstate") else None
    with pytest.raises(IntentRejectedError) as exc:
        _run(
            submit_player_intent(
                handle2, actor_id="char:hero", intent=PlayerIntent(intent_type="hide")
            )
        )
    assert exc.value.reason == "target_invalid"
    if before is not None:
        assert live2.rng.getstate() == before


def test_hide_in_heavy_obscurement_rejected_when_enemy_has_blindsight():
    grid = GridScene(width=10, height=10, obscurement_cells={cell(0, 0): "heavy"})
    handle, live = _start([_hero()], [_foe()], grid)
    _give_senses(live, "mon:foe", blindsight=30)
    with pytest.raises(IntentRejectedError) as exc:
        _run(
            submit_player_intent(
                handle, actor_id="char:hero", intent=PlayerIntent(intent_type="hide")
            )
        )
    assert exc.value.reason == "target_invalid"


def test_hide_ignores_incapacitated_and_dead_enemies_for_line_of_sight():
    grid = GridScene(width=10, height=10, obscurement_cells={cell(0, 0): "heavy"})
    handle, live = _start([_hero()], [_foe()], grid)
    _give_senses(live, "mon:foe", blindsight=30)
    _give_condition(live, "mon:foe", "incapacitated")
    _run(
        submit_player_intent(handle, actor_id="char:hero", intent=PlayerIntent(intent_type="hide"))
    )
    assert [e for e in events_of(live, CheckRolled) if e.skill == "stealth"]
