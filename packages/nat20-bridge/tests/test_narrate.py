"""Tests for the CombatEvent narration renderer."""

from __future__ import annotations

from typing import Literal, get_args

from dnd5e_engine.events import (
    AreaTargeted,
    AttackRolled,
    CombatantJoined,
    CombatantLeft,
    CombatEvent,
    ConcentrationCheck,
    DamageApplied,
    Death,
    EffectApplied,
    IntentSubmitted,
    RoundStarted,
    SpellCast,
    TurnPhase,
    TurnStarted,
)
from dnd5e_engine.types import ActiveEffect
from pydantic import BaseModel

from nat20_bridge.narrate import _FORMATTERS, _SKIPPED_EVENT_TYPES, narrate

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
    # Stands in for a type added to the engine's union after this module.
    class FutureEvent(BaseModel):
        type: Literal["future_event"] = "future_event"
        actor_id: str

    out = narrate([FutureEvent(actor_id="char:elara")], NAMES)  # type: ignore[list-item]
    assert out.startswith("[future_event]")
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
    """The engine reports a concentration save as one ``ConcentrationCheck``
    and nothing else, so it narrates as one readable line, never the raw
    ``[concentration_check] k=v`` fallback dump."""
    text = narrate(
        [ConcentrationCheck(target_id="char:elara", dc=10, roll_total=14, succeeded=True)],
        NAMES,
    )
    lines = text.splitlines()
    assert len(lines) == 1
    assert "concentration_check" not in text
    assert "Elara" in lines[0] and "concentration save" in lines[0]
    assert "14" in lines[0] and "DC 10" in lines[0] and "succeeds" in lines[0]


def test_a_failed_concentration_save_says_so() -> None:
    text = narrate(
        [ConcentrationCheck(target_id="char:elara", dc=12, roll_total=7, succeeded=False)],
        NAMES,
    )
    assert "fails" in text and "DC 12" in text


def test_an_area_names_whom_it_catches_and_spares() -> None:
    area = AreaTargeted(
        actor_id="char:elara",
        source_id="sleep",
        shape="sphere",
        size_ft=5,
        origin="5,5",
        direction=None,
        affected_ids=["mon:gob-1", "mon:gob-2"],
        excluded_ids=["char:elara"],
    )
    text = narrate([area], NAMES)
    assert text == (
        "Elara's sleep fills a 5-ft sphere at 5,5: catches Goblin 1, mon:gob-2; spares Elara."
    )


def test_an_area_that_catches_no_one_says_so() -> None:
    area = AreaTargeted(
        actor_id="char:elara",
        source_id="burning-hands",
        shape="cone",
        size_ft=15,
        origin="0,0",
        direction=(1, 0),
        affected_ids=[],
        excluded_ids=[],
    )
    assert narrate([area], NAMES) == (
        "Elara's burning-hands fills a 15-ft cone at 0,0: catches no one."
    )


_SPIRIT = "summon:char:elara:draconic-spirit:1"


def test_a_summon_joining_narrates_its_name_and_its_summoner() -> None:
    joined = CombatantJoined(
        entity_id=_SPIRIT,
        name="Draconic Spirit",
        stat_block_slug="draconic-spirit",
        origin_caster_id="char:elara",
        spell_id="summon-dragon",
        initiative_count=14,
        after_entity_id="char:elara",
        zone_id="0,1",
        hp_max=50,
        ac=19,
    )
    assert narrate([joined], NAMES) == "Draconic Spirit joins the fight, summoned by Elara."
    # A name the map already holds wins over the event's.
    assert narrate([joined], NAMES | {_SPIRIT: "Ember"}) == (
        "Ember joins the fight, summoned by Elara."
    )


def test_a_summon_leaving_narrates_why() -> None:
    left = CombatantLeft(entity_id=_SPIRIT, reason="zero_hp")
    names = NAMES | {_SPIRIT: "Draconic Spirit"}
    assert narrate([left], names) == "Draconic Spirit leaves the fight (zero_hp)."


def test_every_event_type_has_a_formatter_or_is_skipped() -> None:
    # The `[type] k=v` fallback exists so narration never raises, but its dump
    # reaches the host's LLM verbatim; every type the engine emits today gets a
    # readable line or is deliberately dropped.
    union = get_args(CombatEvent)[0]
    emitted = {get_args(m.model_fields["type"].annotation)[0] for m in get_args(union)}
    assert emitted - _FORMATTERS.keys() - _SKIPPED_EVENT_TYPES == set()


def test_a_spell_cast_and_its_concentration_effect_read_as_prose() -> None:
    events = [
        IntentSubmitted(actor_id="char:elara", intent_type="cast_spell"),
        SpellCast(
            actor_id="char:elara",
            spell_id="summon-dragon",
            slot_level=5,
            ritual=False,
            components=["V", "S", "M"],
            material="an object with the image of a dragon engraved on it worth 500+ GP",
            material_consumed=False,
            material_cost_gp=0,
        ),
        EffectApplied(
            effect=ActiveEffect(
                id="effect:summon-dragon",
                name="Summon Dragon",
                origin="cast:summon-dragon:char:elara",
                target_id="char:elara",
                flags={"concentration": True},
            )
        ),
    ]
    assert narrate(events, NAMES).splitlines() == [
        "Elara attempts cast spell.",
        "Elara casts Summon Dragon with a level 5 slot.",
        "Summon Dragon takes effect on Elara (concentration).",
    ]


def test_a_cantrip_names_no_slot() -> None:
    cast = SpellCast(
        actor_id="char:elara",
        spell_id="fire-bolt",
        slot_level=None,
        ritual=False,
        components=["V", "S"],
        material=None,
        material_consumed=False,
        material_cost_gp=0,
    )
    assert narrate([cast], NAMES) == "Elara casts Fire Bolt."
