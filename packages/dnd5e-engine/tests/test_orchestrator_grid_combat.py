import asyncio

import pytest
from dnd5e_srd_data import MemoryAssetLoader

from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    yield
    set_lib_loader_for_tests(None)


def _party(cell: str) -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            attack_bonus=5,
            zone_id=cell,
        )
    ]


def _encounter(cell: str) -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=50,
            hp_max=50,
            zone_id=cell,
        )
    ]


def _templated_encounter(cell: str, *, slug: str = "grid-brute") -> list[EncounterMemberSpec]:
    """A foe with a typed melee action repertoire so ``advance_monster_turn``
    has a resolvable action — required for the monster-approach / movement
    branch to run (a no-template foe has ``has_action`` False and never moves).
    The matching ``Monster`` template must be registered in the lib loader.
    """
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=30,  # acts before the PC
            hp_current=20,
            hp_max=20,
            ac=12,
            attack_bonus=7,
            zone_id=cell,
            monster_template_slug=slug,
            base_speed=30,
        )
    ]


def _grid_party(cell: str) -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=1,  # acts after the monster
            hp_current=20,
            hp_max=20,
            ac=10,
            zone_id=cell,
        )
    ]


def test_start_combat_on_grid_seeds_cell_positions():
    set_lib_loader_for_tests(MemoryAssetLoader())

    async def _run():
        start = await start_combat(
            session_id="sess-grid-start",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(3, 0)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = asyncio.run(_run())
    assert live.actor_zone["char:hero"] == "0,0"
    assert live.actor_zone["mon:foe"] == "3,0"
    from dnd5e_engine.spatial import GridTopology

    assert isinstance(live.topology, GridTopology)


def test_start_combat_rejects_out_of_bounds_or_blocked_start_cell():
    set_lib_loader_for_tests(MemoryAssetLoader())

    async def _run():
        await start_combat(
            session_id="sess-grid-badstart",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(99, 99)),  # out of bounds on a 10x10
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=2,
        )

    with pytest.raises(ValueError, match="out of bounds or blocked"):
        asyncio.run(_run())


def test_attack_in_range_with_los_resolves():
    # Hero adjacent to foe, melee weapon → attack is NOT gated out.
    from dnd5e_engine.orchestrator import PlayerIntent, submit_player_intent
    from tests.test_orchestrator_gating_typed import _melee_weapon

    weapon = _melee_weapon()
    set_lib_loader_for_tests(MemoryAssetLoader(items=[weapon]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-atk",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(1, 0)),  # adjacent
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon.slug, target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    failed = [e for e in live.event_log if type(e).__name__ == "AttackFailed"]
    assert not failed, f"unexpected AttackFailed: {[getattr(e, 'reason', None) for e in failed]}"


def test_false_line_of_sight_gates_pc_attack():
    from dnd5e_engine.orchestrator import PlayerIntent, submit_player_intent
    from tests.test_orchestrator_gating_typed import _melee_weapon

    weapon = _melee_weapon()
    set_lib_loader_for_tests(MemoryAssetLoader(items=[weapon]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-nolos",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(1, 0)),  # adjacent → in feet range
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=9,
        )
        live = _get_live(start.handle)
        # Force no line of sight; range is satisfied (adjacent) so ONLY the LoS
        # term can gate the attack.
        live.topology.has_line_of_sight = lambda a, b: False  # type: ignore[method-assign]
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon.slug, target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" in reasons, "LoS=False did not gate an in-range attack"


def test_start_combat_rejects_start_on_blocked_cell():
    set_lib_loader_for_tests(MemoryAssetLoader())

    async def _run():
        await start_combat(
            session_id="sess-grid-blockedstart",
            party=_party(cell_id(1, 1)),
            encounter=_encounter(cell_id(3, 0)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, blocked_cells=["1,1"]),
            rng_seed=2,
        )

    with pytest.raises(ValueError, match="out of bounds or blocked"):
        asyncio.run(_run())


def test_pc_single_cell_move_decrements_budget_and_updates_position():
    from dnd5e_engine.orchestrator import PlayerIntent, submit_player_intent

    set_lib_loader_for_tests(MemoryAssetLoader())

    async def _run():
        start = await start_combat(
            session_id="sess-grid-move",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(9, 9)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 1)),
        )
        return live

    live = asyncio.run(_run())
    assert live.actor_zone["char:hero"] == "1,1"
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.movement_remaining == hero.base_speed - 5
    moved = [e for e in live.event_log if type(e).__name__ == "ActorMoved"]
    assert moved
    assert moved[-1].to_zone == "1,1"
    assert moved[-1].distance_ft == 5


def test_pc_move_to_non_adjacent_cell_is_rejected():
    from dnd5e_engine.orchestrator import PlayerIntent, submit_player_intent

    set_lib_loader_for_tests(MemoryAssetLoader())

    async def _run():
        start = await start_combat(
            session_id="sess-grid-badmove",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(9, 9)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=4,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(5, 5)),
        )
        return live

    live = asyncio.run(_run())
    assert live.actor_zone["char:hero"] == "0,0"  # unchanged
    failed = [e for e in live.event_log if type(e).__name__ == "MoveFailed"]
    assert failed
    assert failed[-1].reason == "not_adjacent"


def test_ranged_attack_out_of_range_is_gated_on_grid():
    from dnd5e_engine.orchestrator import PlayerIntent, submit_player_intent
    from tests.test_orchestrator_gating_typed import _melee_weapon

    weapon = _melee_weapon()  # 5ft reach
    set_lib_loader_for_tests(MemoryAssetLoader(items=[weapon]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-oor",
            party=_party(cell_id(0, 0)),
            encounter=_encounter(cell_id(5, 0)),  # 25ft away, melee reach 5ft
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=5,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id=weapon.slug, target_id="mon:foe"),
        )
        return live

    live = asyncio.run(_run())
    reasons = [
        getattr(e, "reason", None) for e in live.event_log if type(e).__name__ == "AttackFailed"
    ]
    assert "out_of_range" in reasons


def test_monster_approaches_across_grid_then_attacks():
    from dnd5e_engine.orchestrator import advance_monster_turn, end_combat
    from tests.test_orchestrator_monster_typed import _melee_attack, _monster

    # Templated foe with a 5ft-reach melee attack so the monster has a
    # resolvable action and the approach branch runs.
    foe = _monster("grid-brute", [_melee_attack("Slam")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[foe]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-approach",
            party=_grid_party(cell_id(0, 0)),
            encounter=_templated_encounter(cell_id(3, 0)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=11,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        await end_combat(start.handle)
        return live

    live = asyncio.run(_run())
    # The monster should have moved at least one cell toward the hero.
    moved = [
        e for e in live.event_log if type(e).__name__ == "ActorMoved" and e.actor_id == "mon:foe"
    ]
    assert moved, "monster did not move toward the target across the grid"
    # Final position must be strictly closer than the start (col decreased from 3).
    final_col = int(live.actor_zone["mon:foe"].split(",")[0])
    assert final_col < 3


def test_monster_approach_routes_around_blocked_cells():
    from dnd5e_engine.orchestrator import advance_monster_turn, end_combat
    from tests.test_orchestrator_monster_typed import _melee_attack, _monster

    foe = _monster("grid-brute", [_melee_attack("Slam")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[foe]))

    async def _run():
        # Wall the entire row y=2 across the foe's straight-line approach except
        # the far end, forcing a detour.
        blocked = [cell_id(c, 2) for c in range(0, 9)]  # 0..8 blocked, (9,2) open
        start = await start_combat(
            session_id="sess-grid-detour",
            party=_grid_party(cell_id(0, 0)),
            encounter=_templated_encounter(cell_id(0, 3)),
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, blocked_cells=blocked),
            rng_seed=13,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        await end_combat(start.handle)
        return live, set(blocked)

    live, blocked = asyncio.run(_run())
    steps = [
        e for e in live.event_log if type(e).__name__ == "ActorMoved" and e.actor_id == "mon:foe"
    ]
    assert steps, "monster did not move"
    for e in steps:
        assert e.to_zone not in blocked, f"monster stepped into blocked cell {e.to_zone}"


def test_false_line_of_sight_skips_monster_attack():
    from dnd5e_engine.orchestrator import advance_monster_turn, end_combat
    from tests.test_orchestrator_monster_typed import _melee_attack, _monster

    # Working templated foe ADJACENT to the hero (so range alone would let the
    # attack land); forcing LoS False must suppress the damage.
    foe = _monster("grid-brute", [_melee_attack("Slam")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[foe]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-monnolos",
            party=_grid_party(cell_id(0, 0)),
            encounter=_templated_encounter(cell_id(1, 0)),  # adjacent
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=17,
        )
        live = _get_live(start.handle)
        live.topology.has_line_of_sight = lambda a, b: False  # type: ignore[method-assign]
        await advance_monster_turn(start.handle)
        await end_combat(start.handle)
        return live

    live = asyncio.run(_run())
    hero_dmg = [
        e
        for e in live.event_log
        if type(e).__name__ == "DamageApplied" and getattr(e, "target_id", None) == "char:hero"
    ]
    assert not hero_dmg, "monster dealt damage despite LoS=False"


def test_baseline_monster_attack_lands_with_los_true():
    """Guard: the LoS=False suppression test is non-vacuous — the same adjacent
    templated foe DOES land an attack when LoS is True (default v1)."""
    from dnd5e_engine.events import AttackRolled
    from dnd5e_engine.orchestrator import advance_monster_turn, end_combat
    from tests.test_orchestrator_monster_typed import _melee_attack, _monster

    foe = _monster("grid-brute", [_melee_attack("Slam")])
    set_lib_loader_for_tests(MemoryAssetLoader(monsters=[foe]))

    async def _run():
        start = await start_combat(
            session_id="sess-grid-monlos",
            party=_grid_party(cell_id(0, 0)),
            encounter=_templated_encounter(cell_id(1, 0)),  # adjacent
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=17,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        await end_combat(start.handle)
        return live

    live = asyncio.run(_run())
    rolled = [
        e
        for e in live.event_log
        if isinstance(e, AttackRolled) and getattr(e, "target_id", None) == "char:hero"
    ]
    assert rolled, "baseline: adjacent foe with LoS=True did not even roll an attack"
