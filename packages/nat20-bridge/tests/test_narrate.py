"""Tests for the CombatEvent narration renderer."""

from __future__ import annotations

from dnd5e_engine.events import (
    AttackRolled,
    ConcentrationCheck,
    DamageApplied,
    Death,
    RoundStarted,
    SaveRolled,
    TurnPhase,
    TurnStarted,
)

from nat20_bridge.narrate import narrate

NAMES = {"char:elara": "Elara", "mon:gob-1": "Goblin 1"}


def test_attack_hit_line() -> None:
    text = narrate(
        [
            AttackRolled(
                attacker_id="char:elara",
                target_id="mon:gob-1",
                roll_total=18,
                advantage="normal",
                is_crit=False,
                is_hit=True,
            ),
            DamageApplied(target_id="mon:gob-1", amount=6, damage_type="fire", is_overkill=False),
        ],
        NAMES,
    )
    lines = text.splitlines()
    assert "Elara" in lines[0] and "Goblin 1" in lines[0] and "18" in lines[0]
    assert "hit" in lines[0].lower()
    assert "6" in lines[1] and "fire" in lines[1]


def test_attack_miss_line() -> None:
    text = narrate(
        [
            AttackRolled(
                attacker_id="char:elara",
                target_id="mon:gob-1",
                roll_total=8,
                advantage="disadvantage",
                is_crit=False,
                is_hit=False,
            ),
        ],
        NAMES,
    )
    assert "miss" in text.lower()
    assert "Elara" in text and "Goblin 1" in text


def test_attack_crit_line() -> None:
    text = narrate(
        [
            AttackRolled(
                attacker_id="char:elara",
                target_id="mon:gob-1",
                roll_total=20,
                advantage="advantage",
                is_crit=True,
                is_hit=True,
            ),
        ],
        NAMES,
    )
    assert "crit" in text.lower()


def test_round_turn_death_lines() -> None:
    text = narrate(
        [
            RoundStarted(round_number=2),
            TurnStarted(actor_id="mon:gob-1"),
            Death(target_id="mon:gob-1", reason="damage"),
        ],
        NAMES,
    )
    assert "Round 2" in text
    assert "Goblin 1" in text


def test_unknown_event_never_raises() -> None:
    from dnd5e_engine.events import DashTaken

    out = narrate(
        [
            DashTaken.model_construct(
                type="dash_taken",
                actor_id="char:elara",
                doubled_movement_remaining=60,
                budget_consumed="action",
            )
        ],
        NAMES,
    )
    assert out  # some line rendered


def test_unhandled_event_uses_generic_fallback() -> None:
    from dnd5e_engine.events import ZoneTransit

    out = narrate(
        [ZoneTransit(actor_id="char:elara", from_zone="z1", to_zone="z2", feet_spent=30)],
        NAMES,
    )
    assert out.startswith("[zone_transit]")
    assert "actor_id=char:elara" in out


def test_names_fallback_to_raw_id() -> None:
    text = narrate([TurnStarted(actor_id="unknown:1")], NAMES)
    assert "unknown:1" in text


def test_turn_phase_markers_produce_no_narration() -> None:
    """``turn_phase`` is a structural marker, not narration.

    Engine F3a emits two or three ``TurnPhase`` events at every turn boundary
    so a host can locate the boundary programmatically. This narration is fed
    to an LLM, and the boundary is already stated by the ``-- Round N --`` /
    turn-start lines, so rendering the marker through the generic fallback
    (``[turn_phase] actor_id=... phase=... round_number=...``) would spend
    tokens on pure noise. It must contribute no line at all.
    """
    text = narrate(
        [
            TurnPhase(actor_id="char:elara", phase="turn_end", round_number=1),
            RoundStarted(round_number=2),
            TurnPhase(actor_id=None, phase="round_start", round_number=2),
            TurnStarted(actor_id="char:elara"),
            TurnPhase(actor_id="char:elara", phase="turn_start", round_number=2),
        ],
        NAMES,
    )
    assert "turn_phase" not in text
    # Only the two real structural events survive — one line each, no blanks.
    lines = text.split("\n")
    assert len(lines) == 2
    assert all(line.strip() for line in lines)
    assert lines[0] == "-- Round 2 --"
    assert "Elara" in lines[1]


def test_narrating_only_markers_yields_empty_text() -> None:
    """The degenerate case: a delta containing nothing but markers narrates to
    the empty string rather than a run of blank lines."""
    assert narrate([TurnPhase(actor_id=None, phase="round_start", round_number=3)], NAMES) == ""


def test_concentration_save_narrates_exactly_one_line() -> None:
    """The engine emits ``ConcentrationCheck`` *and* a twin ``SaveRolled`` for
    one concentration save until v0.7. Narrating both would tell the LLM the
    same save happened twice, so the transitional ``concentration_check`` is
    skipped and the human-readable ``save_rolled`` line is the one kept.
    """
    events = [
        SaveRolled(
            target_id="char:elara",
            ability="con",
            dc=10,
            roll_total=14,
            succeeded=True,
        ),
        ConcentrationCheck(
            target_id="char:elara",
            dc=10,
            roll_total=14,
            succeeded=True,
        ),
    ]
    text = narrate(events, NAMES)
    lines = text.splitlines()
    assert len(lines) == 1
    assert "concentration_check" not in text
    assert "Elara" in lines[0] and "con save" in lines[0] and "14" in lines[0]
