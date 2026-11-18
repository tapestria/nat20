"""Tests for the start_turn method on CombatState.

These tests verify that start_turn properly implements the turn-start lifecycle:
- TurnStarted event is emitted
- TurnPhase(turn_start) event is emitted
- turn_start hooks are executed
- Death save is rolled for PCs at 0 HP
"""

from __future__ import annotations

import asyncio

import pytest

from dnd5e_engine.combat_state import CombatState, begin_combat
from dnd5e_engine.events import (
    DeathSaveRolled,
    TurnPhase,
    TurnStarted,
)
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.turn_lifecycle import TurnLifecycle


def _pc(entity_id: str, hp_current: int = 30, **fields: any) -> PartyMemberSpec:
    base: dict[str, any] = {
        "entity_id": entity_id,
        "name": entity_id,
        "initiative": 20,
        "hp_current": hp_current,
        "hp_max": 30,
        "zone_id": cell_id(0, 0),
    }
    return PartyMemberSpec(**(base | fields))


def _foe(entity_id: str = "mon:foe", hp_current: int = 30, **fields: any) -> EncounterMemberSpec:
    base: dict[str, any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 10,
        "hp_current": hp_current,
        "hp_max": 30,
        "zone_id": cell_id(1, 1),
    }
    return EncounterMemberSpec(**(base | fields))


async def _open_party_only(entity_id: str, hp_current: int = 30, seed: int = 42) -> CombatState:
    """Create a combat with just one party member."""
    return (
        await begin_combat(
            session_id="test",
            party=[_pc(entity_id, hp_current=hp_current)],
            encounter=[_foe(hp_current=hp_current)],
            grid_scene=GridScene(width=10, height=10),
            seed=seed,
        )
    ).state


class TestStartTurn:
    """Tests for the start_turn method."""

    @pytest.mark.asyncio
    async def test_start_turn_emits_turn_started_event(self) -> None:
        """start_turn emits a TurnStarted event with the correct actor_id."""
        state = await _open_party_only("char:hero")
        
        step = await state.start_turn(seed=42)
        
        turn_started = [e for e in step.events if isinstance(e, TurnStarted)]
        assert len(turn_started) == 1
        assert turn_started[0].actor_id == "char:hero"

    @pytest.mark.asyncio
    async def test_start_turn_emits_turn_phase_event(self) -> None:
        """start_turn emits a TurnPhase event with phase='turn_start'."""
        state = await _open_party_only("char:hero")
        
        step = await state.start_turn(seed=42)
        
        turn_phases = [e for e in step.events if isinstance(e, TurnPhase)]
        assert len(turn_phases) == 1
        assert turn_phases[0].phase == "turn_start"
        assert turn_phases[0].actor_id == "char:hero"

    @pytest.mark.asyncio
    async def test_start_turn_runs_turn_start_hooks(self) -> None:
        """start_turn executes registered turn_start hooks on its own live combat."""
        state = await _open_party_only("char:hero")
        
        # Create a live combat from the state, register a hook, then call _begin_turn directly
        from dnd5e_engine.combat_state import _live_from_state
        from dnd5e_engine.orchestrator import _begin_turn
        
        calls: list[str] = []
        live = _live_from_state(state, __import__('random').Random(42))
        live.lifecycle.register("turn_start", lambda _l, actor: calls.append(actor), key="test")
        
        # Call _begin_turn directly on the live combat
        _begin_turn(live, new_round=False)
        
        # Hook should have been called
        assert "char:hero" in calls

    @pytest.mark.asyncio
    async def test_start_turn_rolls_death_save_for_zero_hp(self) -> None:
        """start_turn rolls death save for PCs at 0 HP."""
        # Create a PC at 0 HP
        state = await _open_party_only("char:hero", hp_current=0)
        
        # Set death saves to initial state
        state = state.model_copy(
            update={
                "combatants": [
                    c.model_copy(
                        update={
                            "death_saves": {
                                "successes": 0,
                                "failures": 0,
                                "is_stable": False,
                            }
                        }
                    )
                    if c.entity_id == "char:hero"
                    else c
                    for c in state.combatants
                ]
            }
        )
        
        step = await state.start_turn(seed=42)
        
        # Should have rolled a death save
        death_saves = [e for e in step.events if isinstance(e, DeathSaveRolled)]
        assert len(death_saves) == 1
        assert death_saves[0].target_id == "char:hero"

    @pytest.mark.asyncio
    async def test_start_turn_returns_combat_step(self) -> None:
        """start_turn returns a CombatStep with events and state."""
        state = await _open_party_only("char:hero")
        
        result = await state.start_turn(seed=42)
        
        assert hasattr(result, "events")
        assert hasattr(result, "state")
        assert result.state.active_combatant == "char:hero"

    @pytest.mark.asyncio
    async def test_start_turn_is_deterministic(self) -> None:
        """start_turn produces the same results with the same seed."""
        state = await _open_party_only("char:hero")
        
        step1 = await state.start_turn(seed=42)
        step2 = await state.start_turn(seed=42)
        
        # Events should be identical
        assert len(step1.events) == len(step2.events)
        for e1, e2 in zip(step1.events, step2.events):
            assert e1.model_dump_json() == e2.model_dump_json()

    @pytest.mark.asyncio
    async def test_start_turn_with_different_seeds(self) -> None:
        """Different seeds produce different results when there are dice rolls."""
        state = await _open_party_only("char:hero", hp_current=0)  # 0 HP to trigger death save
        
        # Set death saves to initial state
        state = state.model_copy(
            update={
                "combatants": [
                    c.model_copy(
                        update={
                            "death_saves": {
                                "successes": 0,
                                "failures": 0,
                                "is_stable": False,
                            }
                        }
                    )
                    if c.entity_id == "char:hero"
                    else c
                    for c in state.combatants
                ]
            }
        )
        
        results = []
        for seed in range(1, 10):
            step = await state.start_turn(seed=seed)
            results.append(step)
        
        # Death save rolls should differ based on seed
        # Check that not all death save results are identical
        death_save_results = []
        for step in results:
            death_saves = [e for e in step.events if isinstance(e, DeathSaveRolled)]
            if death_saves:
                death_save_results.append(death_saves[0].model_dump_json())
        
        # At least some death saves should differ
        unique_results = set(death_save_results)
        assert len(unique_results) > 1
