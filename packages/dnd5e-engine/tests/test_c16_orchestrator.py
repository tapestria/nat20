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


def test_creatures_never_block_line_of_effect():
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
