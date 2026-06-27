"""Coverage backfill — public death-save loop helpers.

``roll_death_save`` and ``reset_death_saves`` are in
``dnd5e_engine.death_saves.__all__`` and are wired into the orchestrator's
``_maybe_roll_death_save`` dying-PC turn loop. Tapestria's integration suite
asserts the resulting ``DeathSaveRolled`` events through the orchestrator +
Redis projection (host-only), but no ported *engine* test exercised the helper
directly. These hermetic tests cover the SRD outcomes (success, failure,
nat-20 revive, nat-1 double-failure, stabilize, die) against the real public
signature. Zero I/O; RNG injected.
"""

from __future__ import annotations

from dnd5e_engine.death_saves import reset_death_saves, roll_death_save
from dnd5e_engine.types.combat import Combatant


class _FixedRng:
    """Minimal ``random.Random`` stand-in returning a fixed d20 roll."""

    def __init__(self, value: int) -> None:
        self._value = value

    def randint(self, a: int, b: int) -> int:
        return self._value


def _dying_pc(death_saves: dict | None = None) -> Combatant:
    return Combatant(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="Korg",
        initiative=10,
        hp_current=0,
        hp_max=20,
        is_alive=True,
        death_saves=death_saves or {},
    )


def test_first_roll_success_emits_started_and_rolled() -> None:
    result = roll_death_save(_dying_pc(), _FixedRng(15))

    event_types = [e.type for e in result.events]
    assert event_types == ["death_save_started", "death_save_rolled"]
    rolled = result.events[1]
    assert rolled.outcome == "success"
    assert rolled.roll_total == 15
    assert result.outcome == "ongoing"
    assert result.combatant.death_saves == {
        "successes": 1,
        "failures": 0,
        "is_stable": False,
    }


def test_normal_failure_increments_failures() -> None:
    result = roll_death_save(_dying_pc(), _FixedRng(7))

    assert result.events[-1].outcome == "failure"
    assert result.outcome == "ongoing"
    assert result.combatant.death_saves["failures"] == 1


def test_third_success_stabilizes() -> None:
    result = roll_death_save(
        _dying_pc({"successes": 2, "failures": 0, "is_stable": False}),
        _FixedRng(11),
    )

    assert result.outcome == "stabilized"
    assert any(e.type == "stabilized" for e in result.events)
    assert result.combatant.death_saves["is_stable"] is True
    # Not a first roll → no DeathSaveStarted.
    assert not any(e.type == "death_save_started" for e in result.events)


def test_third_failure_kills() -> None:
    result = roll_death_save(
        _dying_pc({"successes": 0, "failures": 2, "is_stable": False}),
        _FixedRng(3),
    )

    assert result.outcome == "dead"
    death_events = [e for e in result.events if e.type == "death"]
    assert death_events
    assert death_events[0].reason == "death_saves"
    assert result.combatant.is_alive is False


def test_nat_one_counts_as_two_failures() -> None:
    result = roll_death_save(_dying_pc(), _FixedRng(1))

    assert result.events[-1].outcome == "crit_failure"
    assert result.combatant.death_saves["failures"] == 2
    assert result.outcome == "ongoing"


def test_nat_twenty_revives_with_one_hp_and_clears_counters() -> None:
    result = roll_death_save(
        _dying_pc({"successes": 1, "failures": 2, "is_stable": False}),
        _FixedRng(20),
    )

    assert result.outcome == "critical_success"
    assert result.events[-1].outcome == "crit_success"
    assert result.combatant.hp_current == 1
    assert result.combatant.is_alive is True
    assert result.combatant.death_saves == {
        "successes": 0,
        "failures": 0,
        "is_stable": False,
    }


def test_reset_death_saves_clears_dict() -> None:
    pc = _dying_pc({"successes": 2, "failures": 1, "is_stable": False})
    cleared = reset_death_saves(pc)
    assert cleared.death_saves == {}
    # Original is untouched (pydantic model_copy).
    assert pc.death_saves == {"successes": 2, "failures": 1, "is_stable": False}
