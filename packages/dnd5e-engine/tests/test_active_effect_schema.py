"""Phase 6 — Foundry-aligned ActiveEffect schema unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def test_active_effect_round_trip():
    bless = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="check.ability_check.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="save.wisdom.bonus", mode="add", value="1d4"),
        ],
        statuses=set(),
        flags={"concentration": True},
    )
    blob = bless.model_dump()
    re = ActiveEffect.model_validate(blob)
    assert re == bless
    assert re.flags["concentration"] is True
    assert re.duration.rounds == 10


def test_active_effect_defaults():
    ae = ActiveEffect(id="x", name="x", origin="o", target_id="t")
    assert ae.disabled is False
    assert ae.transfer is False
    assert ae.duration.rounds is None
    assert ae.changes == []
    assert ae.statuses == set()
    assert ae.flags == {}


def test_active_effect_change_mode_validation():
    with pytest.raises(ValidationError):
        ActiveEffectChange(key="attack.roll.bonus", mode="not-a-mode", value=1)  # type: ignore[arg-type]


def test_active_effect_change_value_polymorphic():
    flat = ActiveEffectChange(key="ac.bonus", mode="add", value=2)
    formula = ActiveEffectChange(key="damage.bonus", mode="add", value="1d6")
    flag = ActiveEffectChange(key="flags.advantage.skill_check", mode="override", value=True)
    assert flat.value == 2
    assert formula.value == "1d6"
    assert flag.value is True


def test_active_effect_duration_optional_fields():
    d = ActiveEffectDuration()
    assert d.rounds is None
    assert d.turns is None
    assert d.seconds is None

    d2 = ActiveEffectDuration(rounds=10, start_round=2)
    assert d2.rounds == 10
    assert d2.start_round == 2


def test_active_effect_statuses_set_semantics():
    ae = ActiveEffect(
        id="effect:hold_person",
        name="Hold Person",
        origin="cast:hold_person:1",
        target_id="char:foe",
        statuses={"paralyzed"},
    )
    assert "paralyzed" in ae.statuses
    ae.statuses.add("paralyzed")
    assert len(ae.statuses) == 1
