"""C21 — the roster events. SRD 5.2 Summon Dragon: "In combat, the creature
shares your Initiative count, but it takes its turn immediately after yours";
"The creature disappears when it drops to 0 Hit Points or when the spell
ends." ``CombatantJoined`` seats a summoned creature and ``CombatantLeft``
unseats it. Both are members of the closed ``CombatEvent`` union; nothing
emits them yet."""

from __future__ import annotations

import typing

import pytest
from pydantic import TypeAdapter, ValidationError

import dnd5e_engine
from dnd5e_engine import events as events_module
from dnd5e_engine.events import (
    ALL_COMBAT_EVENT_TYPES,
    CombatantJoined,
    CombatantLeft,
    CombatantLeftReason,
    CombatEvent,
)

SUMMON = "summon:char:druid:draconic-spirit:1"
JOINED = CombatantJoined(
    entity_id=SUMMON,
    name="Draconic Spirit",
    stat_block_slug="draconic-spirit",
    origin_caster_id="char:druid",
    spell_id="summon-dragon",
    initiative_count=20,
    after_entity_id="char:druid",
    zone_id="1,0",
    hp_max=50,
    ac=19,
)


def test_combatant_joined_is_a_registered_discriminated_event() -> None:
    assert JOINED.type == "combatant_joined"
    assert CombatantJoined in ALL_COMBAT_EVENT_TYPES
    assert "CombatantJoined" in events_module.__all__
    round_tripped = TypeAdapter(CombatEvent).validate_python(JOINED.model_dump())
    assert isinstance(round_tripped, CombatantJoined)
    assert round_tripped == JOINED


def test_combatant_joined_carries_every_seat_field() -> None:
    # Everything a host needs to seat the creature itself, all required.
    seat = [
        "entity_id",
        "name",
        "stat_block_slug",
        "origin_caster_id",
        "spell_id",
        "initiative_count",
        "after_entity_id",
        "zone_id",
        "hp_max",
        "ac",
    ]
    assert list(CombatantJoined.model_fields) == ["type", *seat]
    required = [name for name, field in CombatantJoined.model_fields.items() if field.is_required()]
    assert required == seat


def test_combatant_left_is_a_registered_discriminated_event() -> None:
    left = CombatantLeft(entity_id=SUMMON, reason="zero_hp")
    assert left.type == "combatant_left"
    assert CombatantLeft in ALL_COMBAT_EVENT_TYPES
    assert "CombatantLeft" in events_module.__all__
    round_tripped = TypeAdapter(CombatEvent).validate_json(left.model_dump_json())
    assert isinstance(round_tripped, CombatantLeft)
    assert round_tripped == left


def test_combatant_left_reasons_are_the_three_disappearances() -> None:
    assert typing.get_args(CombatantLeftReason) == ("concentration_drop", "spell_ended", "zero_hp")
    assert "CombatantLeftReason" in events_module.__all__
    reasons = [
        CombatantLeft(entity_id=SUMMON, reason=reason).reason
        for reason in typing.get_args(CombatantLeftReason)
    ]
    assert reasons == ["concentration_drop", "spell_ended", "zero_hp"]


def test_combatant_left_refuses_a_reason_nothing_produces() -> None:
    with pytest.raises(ValidationError):
        CombatantLeft(entity_id=SUMMON, reason="dismissed")


def test_the_roster_events_stay_out_of_the_top_level_api() -> None:
    new = {"CombatantJoined", "CombatantLeft", "CombatantLeftReason"}
    assert not new & set(dnd5e_engine.__all__)
