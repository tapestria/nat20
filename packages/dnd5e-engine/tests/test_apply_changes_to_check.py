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
    monkeypatch.setattr(eff_mod, "roll_dice_str", lambda s: 3)
    bless = _bless()
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="check.skill_check.bonus", effects=[bless]
    )
    assert total == 13
    assert any("1d4" in b for b in breakdown)


def test_apply_changes_to_check_ignores_non_matching_bucket(monkeypatch):
    bless = _bless()
    monkeypatch.setattr(eff_mod, "roll_dice_str", lambda s: 3)
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
            ActiveEffectChange(key="flags.advantage.skill_check", mode="override", value=True)
        ],
    )
    total, breakdown = apply_changes_to_check(
        base_total=10, bucket="flags.advantage.skill_check", effects=[bless_adv]
    )
    assert total == 10
    assert any("advantage" in b.lower() for b in breakdown)


def _add_then_multiply(add_value: int, multiply_value: int) -> ActiveEffect:
    return ActiveEffect(
        id="effect:add_multiply",
        name="Add then Multiply",
        origin="test:add_multiply",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=add_value),
            ActiveEffectChange(key="check.bonus", mode="multiply", value=multiply_value),
        ],
    )


def test_apply_changes_to_check_multiply_scales_bucket_contribution_only():
    # base_total already includes the d20 + ability mod; multiply must scale
    # only the effect bucket's own accumulated contribution (3 -> 3*2=6), not
    # the whole running total (which would make the result RNG-dependent).
    effect = _add_then_multiply(add_value=3, multiply_value=2)
    total, breakdown = apply_changes_to_check(base_total=10, bucket="check.bonus", effects=[effect])
    assert total == 16  # 10 (base) + 6 (bucket contribution 3 * 2)
    assert any("effect" in b for b in breakdown)


def test_apply_changes_to_check_multiply_with_no_prior_add_is_still_a_noop_on_zero():
    # Multiplying an empty (zero) bucket contribution stays zero regardless
    # of the multiplier — there is nothing to scale.
    effect = ActiveEffect(
        id="effect:multiply_only",
        name="Multiply Only",
        origin="test:multiply_only",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="check.bonus", mode="multiply", value=5)],
    )
    total, _breakdown = apply_changes_to_check(
        base_total=10, bucket="check.bonus", effects=[effect]
    )
    assert total == 10


def test_apply_changes_to_check_upgrade_raises_lower_bucket_contribution():
    effect = ActiveEffect(
        id="effect:add_upgrade",
        name="Add then Upgrade",
        origin="test:add_upgrade",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=2),
            ActiveEffectChange(key="check.bonus", mode="upgrade", value=5),
        ],
    )
    total, breakdown = apply_changes_to_check(base_total=10, bucket="check.bonus", effects=[effect])
    assert total == 15  # 10 (base) + max(2, 5) == 15
    assert any("effect" in b for b in breakdown)


def test_apply_changes_to_check_upgrade_never_lowers_bucket_contribution():
    effect = ActiveEffect(
        id="effect:add_upgrade_noop",
        name="Add then Upgrade (no-op)",
        origin="test:add_upgrade_noop",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=7),
            ActiveEffectChange(key="check.bonus", mode="upgrade", value=5),
        ],
    )
    total, _breakdown = apply_changes_to_check(
        base_total=10, bucket="check.bonus", effects=[effect]
    )
    assert total == 17  # 10 (base) + max(7, 5) == 17 — upgrade must not pull it down


def test_apply_changes_to_check_downgrade_lowers_higher_bucket_contribution():
    effect = ActiveEffect(
        id="effect:add_downgrade",
        name="Add then Downgrade",
        origin="test:add_downgrade",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=7),
            ActiveEffectChange(key="check.bonus", mode="downgrade", value=5),
        ],
    )
    total, breakdown = apply_changes_to_check(base_total=10, bucket="check.bonus", effects=[effect])
    assert total == 15  # 10 (base) + min(7, 5) == 15
    assert any("effect" in b for b in breakdown)


def test_apply_changes_to_check_downgrade_is_noop_when_current_is_already_lower():
    # The mirror of upgrade's "never lowers" invariant: downgrade must never
    # RAISE the bucket contribution when the current value is already below
    # the downgrade's value.
    effect = ActiveEffect(
        id="effect:add_downgrade_noop",
        name="Add then Downgrade (no-op)",
        origin="test:add_downgrade_noop",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="add", value=2),
            ActiveEffectChange(key="check.bonus", mode="downgrade", value=5),
        ],
    )
    total, _breakdown = apply_changes_to_check(
        base_total=10, bucket="check.bonus", effects=[effect]
    )
    assert total == 12  # 10 (base) + min(2, 5) == 12 — downgrade must not raise it


def test_apply_changes_to_check_priority_orders_add_before_multiply_when_lower():
    # Foundry applies changes in ascending `priority` order. A multiply
    # explicitly given a LOWER priority than the add it's meant to scale
    # must still run after it once sorted, per the documented ordering
    # contract — this pins the sort-by-priority behavior itself, not just
    # the default-priority-ties case exercised by the other tests above.
    effect = ActiveEffect(
        id="effect:priority_order",
        name="Priority Order",
        origin="test:priority_order",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="check.bonus", mode="multiply", value=2, priority=10),
            ActiveEffectChange(key="check.bonus", mode="add", value=3, priority=20),
        ],
    )
    total, _breakdown = apply_changes_to_check(
        base_total=10, bucket="check.bonus", effects=[effect]
    )
    assert total == 13  # sorted by priority: multiply(0*2=0) runs first, then add(0+3=3) -> 10+3


def test_apply_changes_to_check_custom_mode_is_a_documented_noop():
    # `custom` mode has no Foundry-core semantics to port (host-callback
    # driven in Foundry proper) — see BACKLOG.md's "## Blocked" section.
    # Pinned here as a documented no-op so a future accidental
    # implementation doesn't silently change behavior without discussion.
    effect = ActiveEffect(
        id="effect:custom_noop",
        name="Custom Noop",
        origin="test:custom_noop",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="check.bonus", mode="custom", value=99)],
    )
    total, breakdown = apply_changes_to_check(base_total=10, bucket="check.bonus", effects=[effect])
    assert total == 10
    assert breakdown == []
