"""Tests for the CombatEvent narration renderer."""

from __future__ import annotations

from dnd5e_engine.events import (
    AttackRolled,
    DamageApplied,
    Death,
    RoundStarted,
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
