"""C21a — the additive host surface: two ``PlayerIntent`` fields (SRD 5.2
Wild Shape and Polymorph name a Beast form; a stat-block action can be
commanded) and four Literal members. Nothing reads them yet."""

from __future__ import annotations

import typing
from typing import Any

import pytest
from pydantic import ValidationError

from dnd5e_engine.events import (
    AttackFailed,
    CastFailed,
    CastFailedReason,
    EffectExpired,
    EffectExpiryReason,
)
from dnd5e_engine.orchestrator import PlayerIntent


def test_cast_failed_reason_gained_the_c21_members() -> None:
    assert {"invalid_form", "no_spellcasting"} <= set(typing.get_args(CastFailedReason))


def test_attack_failed_reason_gained_action_unavailable() -> None:
    reasons = set(typing.get_args(AttackFailed.model_fields["reason"].annotation))
    assert "action_unavailable" in reasons


def test_effect_expiry_reason_gained_temp_hp_depleted() -> None:
    assert "temp_hp_depleted" in set(typing.get_args(EffectExpiryReason))


def test_the_new_reasons_validate_on_their_events() -> None:
    cast_reasons = [
        CastFailed(actor_id="char:druid", spell_id="", reason="invalid_form").reason,
        CastFailed(actor_id="char:wiz", spell_id="fly", reason="no_spellcasting").reason,
    ]
    assert cast_reasons == ["invalid_form", "no_spellcasting"]
    failed = AttackFailed(actor_id="char:druid", target_id="mon:foe", reason="action_unavailable")
    assert failed.reason == "action_unavailable"
    expired = EffectExpired(
        effect_id="effect:polymorph",
        target_id="mon:foe",
        origin="cast:polymorph:char:wiz",
        reason="temp_hp_depleted",
    )
    assert expired.reason == "temp_hp_depleted"


def test_the_new_intent_fields_default_to_none() -> None:
    intent = PlayerIntent(intent_type="pass")
    assert intent.form_id is None
    assert intent.stat_block_action_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "intent_type": "use_feature",
            "feature_id": "wild-shape",
            "target_id": "char:druid",
            "form_id": "giant-badger",
        },
        {
            "intent_type": "cast_spell",
            "spell_id": "polymorph",
            "target_id": "mon:foe",
            "form_id": "giant-badger",
        },
        {"intent_type": "attack", "stat_block_action_id": "bite", "target_id": "mon:foe"},
    ],
)
def test_the_new_intent_fields_round_trip(payload: dict[str, Any]) -> None:
    intent = PlayerIntent.model_validate(payload)
    assert intent.form_id == payload.get("form_id")
    assert intent.stat_block_action_id == payload.get("stat_block_action_id")
    assert PlayerIntent.model_validate(intent.model_dump()) == intent
    assert PlayerIntent.model_validate_json(intent.model_dump_json()) == intent


def test_unknown_intent_keys_are_still_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlayerIntent.model_validate({"intent_type": "attack", "beast_form": "wolf"})
