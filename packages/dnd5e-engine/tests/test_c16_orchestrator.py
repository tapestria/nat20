"""C16 — orchestrator-level units: typed surface, AoE shape mapping, cover
occupancy, multi-cell move, forced movement, zone-graph deprecation."""

from __future__ import annotations

import typing
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from dnd5e_engine import events as events_module
from dnd5e_engine.events import ALL_COMBAT_EVENT_TYPES, CombatEvent, MoveFailed
from dnd5e_engine.orchestrator import (
    PlayerIntent,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, run_async

# ── Task 4: typed surface ────────────────────────────────────────────────


def test_move_failed_reason_literal_gained_the_c16_members():
    reasons = set(typing.get_args(MoveFailed.model_fields["reason"].annotation))
    assert {"unreachable", "occupied", "blocked_path"} <= reasons
    assert {"not_adjacent", "insufficient_movement", "combat_ended", "not_actor_turn"} <= reasons


def test_combatant_moved_is_a_registered_discriminated_event():
    cls = events_module.CombatantMoved
    ev = cls(actor_id="mon:foe", from_zone="1,0", to_zone="3,0", distance_ft=10, forced=True)
    assert ev.type == "combatant_moved"
    assert cls in ALL_COMBAT_EVENT_TYPES
    assert "CombatantMoved" in events_module.__all__
    round_tripped = TypeAdapter(CombatEvent).validate_python(ev.model_dump())
    assert isinstance(round_tripped, cls)
    assert round_tripped.forced is True


# ── Task 5: PlayerIntent.direction ───────────────────────────────────────


def test_player_intent_direction_defaults_none_and_accepts_a_vector():
    assert PlayerIntent(intent_type="cast_spell", spell_id="burning-hands").direction is None
    intent = PlayerIntent(intent_type="cast_spell", spell_id="burning-hands", direction=(1, 0))
    assert intent.direction == (1, 0)
    with pytest.raises(ValidationError):
        PlayerIntent(intent_type="cast_spell", spell_id="burning-hands", direction=(0, 0))


# ── Task 6: AoE shape mapping + line of effect ───────────────────────────


def _wiz(spells: list[str], slots: dict[int, int], at: str, level: int = 5) -> PartyMemberSpec:
    return PartyMemberSpec(
        entity_id="char:wiz",
        name="Wizard",
        initiative=20,
        hp_current=60,
        hp_max=60,
        character_level=level,
        class_slug="wizard",
        spells_known=spells,
        spell_slots=slots,
        zone_id=at,
    )


def _mon(eid: str, at: str, initiative: int = 5) -> EncounterMemberSpec:
    return EncounterMemberSpec(
        entity_id=eid,
        entity_type="Monster",
        name=eid,
        initiative=initiative,
        hp_current=200,
        hp_max=200,
        ac=1,
        zone_id=at,
    )


async def _cast(
    scene: GridScene,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    intent: PlayerIntent,
    seed: int = 3,
) -> Any:
    start = await start_combat(
        session_id="c16-aoe",
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=scene,
        rng_seed=seed,
    )
    live = _get_live(start.handle)
    await submit_player_intent(start.handle, actor_id="char:wiz", intent=intent)
    return live


def _damaged(live: Any) -> set[str]:
    return {e.target_id for e in events_of(live, events_module.DamageApplied)}


def test_aoe_template_maps_foundry_types():
    from dnd5e_srd_data.loader import BundledAssetLoader

    from dnd5e_engine.orchestrator import _aoe_template

    # Real corpus, independent of any MemoryAssetLoader set by other tests.
    loader = BundledAssetLoader()
    fireball = _aoe_template(loader.get_spell("fireball").activities)
    assert fireball is not None
    assert (fireball.shape, fireball.size_ft, fireball.origin, fireball.include_origin) == (
        "sphere",
        20,
        "target",
        True,
    )
    thunderwave = _aoe_template(loader.get_spell("thunderwave").activities)
    assert thunderwave is not None
    assert (
        thunderwave.shape,
        thunderwave.size_ft,
        thunderwave.origin,
        thunderwave.include_origin,
    ) == ("cube", 15, "caster", False)
    assert _aoe_template(loader.get_spell("sacred-flame").activities) is None


def test_sphere_line_of_effect_excludes_cells_behind_a_wall():
    # Fireball centred on mon:a; mon:b is in radius but behind a wall.
    scene = GridScene(width=21, height=21, wall_segments=[{"x1": 12, "y1": 8, "x2": 12, "y2": 13}])
    live = run_async(
        _cast(
            scene,
            [_wiz(["fireball"], {3: 1}, cell(0, 10))],
            [_mon("mon:a", cell(10, 10)), _mon("mon:b", cell(13, 10)), _mon("mon:c", cell(8, 10))],
            PlayerIntent(intent_type="cast_spell", spell_id="fireball", target_id="mon:a"),
        )
    )
    assert {"mon:a", "mon:c"} <= _damaged(live)
    assert "mon:b" not in _damaged(live)


def test_line_of_effect_ignores_creature_occupancy_but_not_total_cover():
    """SRD 5.2 §Point of Origin — "To block a line, an obstruction must provide
    Total Cover." A creature provides Half Cover at most, so it never blocks;
    a Total Cover obstruction and an impassable cell both do. All three cases
    use the SAME interposing cell, so the assertions turn on the obstruction
    model rather than on the geometry."""
    from dnd5e_engine.orchestrator import _has_line_of_effect
    from dnd5e_engine.spatial import GridTopology

    open_grid = GridTopology(GridScene(width=5, height=1))
    # An occupied interposing cell IS a cover signal ``cover_between`` reports
    # when it is asked for one...
    assert open_grid.cover_between(cell(0, 0), cell(2, 0), occupied_cells={cell(1, 0)}) == "half"
    # ...but line of effect never asks, so the far cell stays inside the area.
    assert _has_line_of_effect(open_grid, cell(0, 0), cell(2, 0))
    # The same cell tagged Total Cover cuts the line.
    covered = GridTopology(GridScene(width=5, height=1, cover_cells={cell(1, 0): "total"}))
    assert covered.cover_between(cell(0, 0), cell(2, 0)) == "total"
    assert not _has_line_of_effect(covered, cell(0, 0), cell(2, 0))
    # So does an impassable cell (one obstruction model — blocks sight outright).
    blocked = GridTopology(GridScene(width=5, height=1, blocked_cells=[cell(1, 0)]))
    assert not blocked.has_line_of_sight(cell(0, 0), cell(2, 0))
    assert not _has_line_of_effect(blocked, cell(0, 0), cell(2, 0))
    # The origin is always in its own area, whatever sits on it.
    assert _has_line_of_effect(blocked, cell(1, 0), cell(1, 0))


def test_fireball_hits_every_creature_in_a_row_inside_the_radius():
    """The wiring counterpart of the unit above: three creatures single-file in
    the sphere all take damage — none of them shadows the ones behind it."""
    scene = GridScene(width=21, height=21)
    live = run_async(
        _cast(
            scene,
            [_wiz(["fireball"], {3: 1}, cell(0, 10))],
            [
                _mon("mon:a", cell(10, 10)),
                _mon("mon:b", cell(11, 10)),
                _mon("mon:c", cell(12, 10)),
            ],
            PlayerIntent(intent_type="cast_spell", spell_id="fireball", target_id="mon:a"),
        )
    )
    assert {"mon:a", "mon:b", "mon:c"} <= _damaged(live)


def test_cone_direction_defaults_to_the_named_target_and_excludes_caster():
    scene = GridScene(width=11, height=11)
    live = run_async(
        _cast(
            scene,
            [_wiz(["burning-hands"], {1: 1}, cell(5, 5), level=3)],
            [_mon("mon:front", cell(7, 5)), _mon("mon:behind", cell(3, 5))],
            PlayerIntent(intent_type="cast_spell", spell_id="burning-hands", target_id="mon:front"),
        )
    )
    assert "mon:front" in _damaged(live)
    assert "mon:behind" not in _damaged(live)
    assert "char:wiz" not in _damaged(live)


def test_cone_hits_an_unnamed_creature_inside_the_cone():
    """Geometry, not the named target: ``mon:flank`` is never named yet sits
    inside the 15 ft cone, so the cone walk must catch it."""
    scene = GridScene(width=11, height=11)
    live = run_async(
        _cast(
            scene,
            [_wiz(["burning-hands"], {1: 1}, cell(5, 5), level=3)],
            [_mon("mon:front", cell(7, 5)), _mon("mon:flank", cell(7, 6))],
            PlayerIntent(intent_type="cast_spell", spell_id="burning-hands", target_id="mon:front"),
        )
    )
    assert {"mon:front", "mon:flank"} <= _damaged(live)


def test_directional_template_without_target_or_direction_is_rejected():
    """Rejects in the pre-slot validation block, like every other
    ``target_invalid``: the slot, the Action and the turn all survive."""
    scene = GridScene(width=11, height=11)
    live = run_async(
        _cast(
            scene,
            [_wiz(["burning-hands"], {1: 1}, cell(5, 5), level=3)],
            [_mon("mon:front", cell(7, 5))],
            PlayerIntent(intent_type="cast_spell", spell_id="burning-hands"),
        )
    )
    failed = events_of(live, events_module.CastFailed)
    assert failed
    assert failed[0].reason == "target_invalid"
    assert not _damaged(live)
    # Nothing was spent: the 1st-level slot is intact and the Action is still
    # available on the caster's own turn.
    assert live.spell_slots_by_entity["char:wiz"] == {1: 1}
    caster = next(c for c in live.initiative if c.entity_id == "char:wiz")
    assert caster.action_available is True
    assert live.initiative[live.current_turn_index].entity_id == "char:wiz"


# ── Task 7: creature cover ───────────────────────────────────────────────


def _hero(at: str, **kw: Any) -> PartyMemberSpec:
    base: dict[str, Any] = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        zone_id=at,
    )
    base.update(kw)
    return PartyMemberSpec(**base)


def _foe(eid: str, at: str, ac: int = 10, initiative: int = 1, **kw: Any) -> EncounterMemberSpec:
    base: dict[str, Any] = dict(
        entity_id=eid,
        entity_type="Monster",
        name=eid,
        initiative=initiative,
        hp_current=50,
        hp_max=50,
        ac=ac,
        zone_id=at,
    )
    base.update(kw)
    return EncounterMemberSpec(**base)


def _longbow_loader() -> None:
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests
    from tests.test_orchestrator_gating_typed import _ranged_weapon

    set_lib_loader_for_tests(
        MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
    )


async def _shoot(
    scene: GridScene,
    encounter: list[EncounterMemberSpec],
    seed: int = 1,
    party: list[PartyMemberSpec] | None = None,
) -> Any:
    _longbow_loader()
    start = await start_combat(
        session_id="c16-cover",
        party=party or [_hero(cell(0, 0))],
        encounter=encounter,
        scene_zones=None,
        grid_scene=scene,
        rng_seed=seed,
    )
    live = _get_live(start.handle)
    await submit_player_intent(
        start.handle,
        actor_id="char:hero",
        intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
    )
    return live


def test_occupied_cells_lists_alive_combatants_minus_exclusions() -> None:
    from dnd5e_engine.orchestrator import _occupied_cells

    live = run_async(
        _shoot(
            GridScene(width=10, height=10),
            [_foe("mon:foe", cell(2, 0)), _foe("mon:x", cell(5, 5), initiative=2)],
        )
    )
    assert _occupied_cells(live, exclude=()) == {cell(0, 0), cell(2, 0), cell(5, 5)}
    assert _occupied_cells(live, exclude=("char:hero", "mon:foe")) == {cell(5, 5)}
    # A downed creature no longer occupies its space for cover purposes.
    next(c for c in live.initiative if c.entity_id == "mon:x").is_alive = False
    assert _occupied_cells(live, exclude=()) == {cell(0, 0), cell(2, 0)}
    live.dead_ids.add("mon:foe")
    assert _occupied_cells(live, exclude=()) == {cell(0, 0)}


def test_ally_between_attacker_and_target_also_grants_half_cover() -> None:
    ally = PartyMemberSpec(
        entity_id="char:ally",
        name="Ally",
        initiative=19,
        hp_current=20,
        hp_max=20,
        zone_id=cell(1, 0),
    )
    live = run_async(
        _shoot(
            GridScene(width=10, height=10),
            [_foe("mon:foe", cell(2, 0))],
            party=[_hero(cell(0, 0)), ally],
        )
    )
    rolled = next(
        e for e in events_of(live, events_module.AttackRolled) if e.target_id == "mon:foe"
    )
    assert rolled.roll_total == 10
    assert rolled.is_hit is False  # AC 10 + 2 (half cover from the interposed ally)


def test_interposed_creature_does_not_block_targeting() -> None:
    live = run_async(
        _shoot(
            GridScene(width=10, height=10),
            [_foe("mon:foe", cell(2, 0)), _foe("mon:blocker", cell(1, 0), initiative=2)],
        )
    )
    assert not events_of(live, events_module.AttackFailed)
    assert events_of(live, events_module.AttackRolled)


# ── Task 8: multi-cell move ──────────────────────────────────────────────


async def _move(
    scene: GridScene,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    to: str,
    actor: str = "char:hero",
) -> Any:
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests

    set_lib_loader_for_tests(MemoryAssetLoader())
    start = await start_combat(
        session_id="c16-move",
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=scene,
        rng_seed=1,
    )
    live = _get_live(start.handle)
    await submit_player_intent(
        start.handle,
        actor_id=actor,
        intent=PlayerIntent(intent_type="move", target_zone_id=to),
    )
    return live


def _mover(at: str, speed: int = 30) -> PartyMemberSpec:
    return PartyMemberSpec(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        base_speed=speed,
        zone_id=at,
    )


def test_move_route_too_expensive_is_rejected_atomically() -> None:
    live = run_async(
        _move(
            GridScene(width=10, height=10),
            [_mover(cell(0, 0), speed=10)],
            [_foe("mon:foe", cell(9, 9))],
            cell(3, 0),
        )
    )
    failed = events_of(live, MoveFailed)
    assert failed
    assert failed[0].reason == "insufficient_movement"
    assert live.actor_zone["char:hero"] == cell(0, 0)
    assert not events_of(live, events_module.ActorMoved)
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.movement_remaining == 10


def test_move_routes_around_an_enemy_but_through_an_ally() -> None:
    def ally() -> PartyMemberSpec:
        return PartyMemberSpec(
            entity_id="char:ally",
            name="Ally",
            initiative=19,
            hp_current=20,
            hp_max=20,
            zone_id=cell(1, 0),
        )

    # destination occupied by the enemy → occupied
    live = run_async(
        _move(
            GridScene(width=3, height=1),
            [_mover(cell(0, 0)), ally()],
            [_foe("mon:foe", cell(2, 0))],
            cell(2, 0),
        )
    )
    assert events_of(live, MoveFailed)[0].reason == "occupied"

    # passes THROUGH the ally at (1,0) on a 1-row grid
    live2 = run_async(
        _move(
            GridScene(width=4, height=1),
            [_mover(cell(0, 0)), ally()],
            [_foe("mon:foe", cell(3, 0))],
            cell(2, 0),
        )
    )
    moved = events_of(live2, events_module.ActorMoved)
    assert moved
    assert moved[-1].to_zone == cell(2, 0)
    assert moved[-1].distance_ft == 10

    # ending ON the ally is refused — the SRD rule the pass-through turns on
    live_ally_dest = run_async(
        _move(
            GridScene(width=4, height=1),
            [_mover(cell(0, 0)), ally()],
            [_foe("mon:foe", cell(3, 0))],
            cell(1, 0),
        )
    )
    assert events_of(live_ally_dest, MoveFailed)[0].reason == "occupied"
    assert live_ally_dest.actor_zone["char:hero"] == cell(0, 0)

    # an ENEMY at (1,0) on a 1-row grid boxes the mover in → unreachable
    live3 = run_async(
        _move(
            GridScene(width=4, height=1),
            [_mover(cell(0, 0))],
            [_foe("mon:foe", cell(1, 0))],
            cell(3, 0),
        )
    )
    assert events_of(live3, MoveFailed)[0].reason == "unreachable"


def test_single_illegal_step_reports_blocked_path() -> None:
    scene = GridScene(
        width=5,
        height=5,
        blocked_cells=[cell(1, 0)],
        wall_segments=[{"x1": 1, "y1": 0, "x2": 1, "y2": 1}],
    )
    live = run_async(_move(scene, [_mover(cell(0, 0))], [_foe("mon:foe", cell(4, 4))], cell(1, 1)))
    assert events_of(live, MoveFailed)[0].reason == "blocked_path"
    assert live.actor_zone["char:hero"] == cell(0, 0)


def test_move_to_own_cell_or_without_destination_keeps_not_adjacent() -> None:
    live = run_async(
        _move(
            GridScene(width=5, height=5),
            [_mover(cell(0, 0))],
            [_foe("mon:foe", cell(4, 4))],
            cell(0, 0),
        )
    )
    assert events_of(live, MoveFailed)[0].reason == "not_adjacent"


def test_zone_graph_move_into_an_occupied_zone_still_succeeds() -> None:
    """Regression: occupancy is a GRID rule. A zone is an area, not a 5-ft
    square, and ``_ZoneGraph`` does not model occupancy — a PC must still be
    able to move into the zone an enemy holds in order to engage it."""
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests
    from dnd5e_engine.specs import SceneTopology, ZoneEdge

    async def _run() -> Any:
        set_lib_loader_for_tests(MemoryAssetLoader())
        start = await start_combat(
            session_id="c16-zone-move",
            party=[_mover("zone:a")],
            encounter=[_foe("mon:foe", "zone:b")],
            scene_zones=SceneTopology(
                zones=["zone:a", "zone:b"],
                edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=30)],
            ),
            grid_scene=None,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id="zone:b"),
        )
        return live

    live = run_async(_run())
    assert not events_of(live, MoveFailed)
    assert live.actor_zone["char:hero"] == "zone:b"
    moved = events_of(live, events_module.ActorMoved)
    assert len(moved) == 1
    assert moved[0].to_zone == "zone:b"
    assert moved[0].distance_ft == 30


# ── Task 9: forced movement ──────────────────────────────────────────────


def test_forced_movement_registry_is_typed_and_names_thunderwave():
    from dnd5e_engine.activities.forced_movement import (
        FORCED_MOVEMENT_RIDERS,
        ForcedMovementRider,
    )

    rider = FORCED_MOVEMENT_RIDERS["thunderwave"]
    assert rider == ForcedMovementRider(
        distance_ft=10, trigger="failed_save", direction="away_from_caster"
    )


def test_push_combatant_emits_combatant_moved_without_spending_budget():
    from dnd5e_engine.orchestrator import push_combatant

    live = run_async(
        _move(
            GridScene(width=10, height=10),
            [_mover(cell(0, 0))],
            [_foe("mon:foe", cell(1, 0))],
            cell(0, 0),
        )
    )
    before = next(c for c in live.initiative if c.entity_id == "mon:foe").movement_remaining
    push_combatant(live, "mon:foe", cell(0, 0), 10)
    pushed = [e for e in live.event_log if isinstance(e, events_module.CombatantMoved)]
    assert pushed
    assert (pushed[0].from_zone, pushed[0].to_zone, pushed[0].distance_ft, pushed[0].forced) == (
        cell(1, 0),
        cell(3, 0),
        10,
        True,
    )
    assert live.actor_zone["mon:foe"] == cell(3, 0)
    assert next(c for c in live.initiative if c.entity_id == "mon:foe").movement_remaining == before


def test_push_combatant_into_a_wall_moves_as_far_as_possible_and_no_event_when_stuck():
    from dnd5e_engine.orchestrator import push_combatant

    scene = GridScene(width=10, height=10, wall_segments=[{"x1": 3, "y1": 0, "x2": 3, "y2": 1}])
    live = run_async(_move(scene, [_mover(cell(0, 0))], [_foe("mon:foe", cell(1, 0))], cell(0, 0)))
    push_combatant(live, "mon:foe", cell(0, 0), 10)
    pushed = [e for e in live.event_log if isinstance(e, events_module.CombatantMoved)]
    assert pushed[0].to_zone == cell(2, 0)
    assert pushed[0].distance_ft == 5
    push_combatant(live, "mon:foe", cell(0, 0), 10)  # now flush against the wall
    assert len([e for e in live.event_log if isinstance(e, events_module.CombatantMoved)]) == 1


def test_thunderwave_push_skips_a_creature_that_saved():
    # seed 3 → natural 12 vs DC 10 (verified on main): saved, damaged, not pushed
    from dnd5e_engine.lib_loader import set_lib_loader_for_tests

    # The move tests above install a MemoryAssetLoader; this one needs the
    # real corpus (thunderwave's activities) regardless of file order.
    set_lib_loader_for_tests(None)
    live = run_async(
        _cast(
            GridScene(width=10, height=10),
            [_wiz(["thunderwave"], {1: 1}, cell(0, 0), level=3)],
            [_foe("mon:foe", cell(1, 0), dexterity=8)],
            PlayerIntent(intent_type="cast_spell", spell_id="thunderwave", target_id="mon:foe"),
            seed=3,
        )
    )
    assert events_of(live, events_module.SaveRolled)[0].succeeded is True
    assert not [e for e in live.event_log if isinstance(e, events_module.CombatantMoved)]
    assert live.actor_zone["mon:foe"] == cell(1, 0)
