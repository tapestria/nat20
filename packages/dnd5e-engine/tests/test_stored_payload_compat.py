"""Stored 0.7.0 payloads stay readable.

A host may persist what the engine hands it (the specs it seated a combat
with, the intents it submitted, the event log and the ``CombatOutcome`` of an
ended fight) and parse it again later with a newer engine. The fixture holds
payloads dumped with ``model_dump(mode="json")`` by dnd5e-engine 0.7.0. Every
payload must validate on today's models, and dumping it again must keep every
stored key with its stored value: a release may add defaulted fields, but a
rename or a removal of a stored field fails here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter

from dnd5e_engine import (
    CombatEvent,
    CombatOutcome,
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
)

_STORED: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "payloads_0_7_0.json").read_text()
)
_EVENT: TypeAdapter[CombatEvent] = TypeAdapter(CombatEvent)


def _kept(stored: Any, redumped: Any, where: str = "$") -> None:
    """Every key in ``stored`` is in ``redumped`` with the same value; extra
    keys in ``redumped`` are new defaulted fields and allowed."""
    if isinstance(stored, dict):
        assert isinstance(redumped, dict), where
        missing = set(stored) - set(redumped)
        assert not missing, f"{where}: stored keys no longer dumped: {sorted(missing)}"
        for key, value in stored.items():
            _kept(value, redumped[key], f"{where}.{key}")
    elif isinstance(stored, list):
        assert isinstance(redumped, list), where
        assert len(redumped) == len(stored), where
        for i, (old, new) in enumerate(zip(stored, redumped, strict=True)):
            _kept(old, new, f"{where}[{i}]")
    else:
        assert redumped == stored, f"{where}: {stored!r} became {redumped!r}"


@pytest.mark.parametrize(
    ("key", "model"),
    [
        ("party_member_spec", PartyMemberSpec),
        ("encounter_member_spec", EncounterMemberSpec),
        ("grid_scene", GridScene),
        ("combat_outcome", CombatOutcome),
    ],
)
def test_a_stored_model_payload_still_validates(key: str, model: type[BaseModel]) -> None:
    stored = _STORED[key]
    parsed = model.model_validate(stored)
    _kept(stored, parsed.model_dump(mode="json", exclude_defaults=False), key)


def test_every_stored_intent_still_validates() -> None:
    stored = _STORED["player_intents"]
    assert {i["intent_type"] for i in stored} >= {"attack", "cast_spell", "move", "pass"}
    for i, payload in enumerate(stored):
        parsed = PlayerIntent.model_validate(payload)
        _kept(payload, parsed.model_dump(mode="json", exclude_defaults=False), f"intent[{i}]")


def test_every_stored_event_still_validates() -> None:
    stored = _STORED["event_log"]
    assert {"attack_rolled", "damage_applied", "death", "combat_ended"} <= {
        e["type"] for e in stored
    }
    for i, payload in enumerate(stored):
        parsed = _EVENT.validate_python(payload)
        _kept(payload, parsed.model_dump(mode="json", exclude_defaults=False), f"event[{i}]")


def test_the_stored_outcome_records_a_death() -> None:
    """The fixture fight ends with a recorded death, so the guard covers
    ``DeathRecord`` and not only an empty list."""
    outcome = CombatOutcome.model_validate(_STORED["combat_outcome"])
    assert [d.target_id for d in outcome.deaths] == ["mon:goblin"]
