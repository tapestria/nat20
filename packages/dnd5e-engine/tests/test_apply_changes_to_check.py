"""Phase 6 — apply_changes_to_check unit coverage."""

from __future__ import annotations

import dnd5e_engine.rules.dice as dice_mod
import dnd5e_engine.rules.effects as eff_mod
from dnd5e_engine.rules.effects import (
    apply_changes_to_check,
    filter_changes_by_bucket,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _bless(target_id: str = "char:hero") -> ActiveEffect:
    return ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id=target_id,
        duration=ActiveEffectDuration(rounds=10),
        changes=[
            ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="check.ability_check.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="check.skill_check.bonus", mode="add", value="1d4"),
            ActiveEffectChange(key="save.wisdom.bonus", mode="add", value="1d4"),
        ],
        flags={"concentration": True},
    )


def test_filter_changes_by_bucket_skill():
    bless = _bless()
    filtered = filter_changes_by_bucket([bless], "check.skill_check.bonus")
    assert len(filtered) == 1
    assert filtered[0].key == "check.skill_check.bonus"


def test_apply_changes_to_check_add_flat(monkeypatch):
    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)
    effect = ActiveEffect(
        id="effect:cloak",
        name="Cloak of Protection",
        origin="item:cloak:1",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="save.wisdom.bonus", mode="add", value=1)],
    )
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="save.wisdom.bonus", effects=[effect]
    )
    assert total == 11
    assert breakdown != []


def test_apply_changes_to_check_add_dice(monkeypatch):
    monkeypatch.setattr(eff_mod, "_roll_dice_str", lambda s: 3)
    bless = _bless()
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="check.skill_check.bonus", effects=[bless]
    )
    assert total == 13
    assert any("1d4" in b for b in breakdown)


def test_apply_changes_to_check_ignores_non_matching_bucket(monkeypatch):
    bless = _bless()
    monkeypatch.setattr(eff_mod, "_roll_dice_str", lambda s: 3)
    total, _breakdown = apply_changes_to_check(
        base_total=10, bucket="attack.roll.bonus", effects=[bless]
    )
    assert total == 13
    total2, breakdown2 = apply_changes_to_check(
        base_total=10, bucket="damage.bonus", effects=[bless]
    )
    assert total2 == 10
    assert breakdown2 == []


def test_apply_changes_to_check_advantage_flag():
    bless_adv = ActiveEffect(
        id="effect:guidance_adv",
        name="Guidance(adv variant)",
        origin="cast:guidance:1",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(
                key="flags.advantage.skill_check", mode="override", value=True
            )
        ],
    )
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="flags.advantage.skill_check", effects=[bless_adv]
    )
    assert total == 10
    assert any("advantage" in b.lower() for b in breakdown)
