"""C16 — orchestrator-level units: typed surface, AoE shape mapping, cover
occupancy, multi-cell move, forced movement, zone-graph deprecation."""

from __future__ import annotations

import typing

import pytest
from pydantic import TypeAdapter, ValidationError

from dnd5e_engine import events as events_module
from dnd5e_engine.events import ALL_COMBAT_EVENT_TYPES, CombatEvent, MoveFailed
from dnd5e_engine.orchestrator import PlayerIntent

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
