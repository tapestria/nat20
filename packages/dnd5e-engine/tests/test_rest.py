"""Unit tests for the standalone rest resolvers (``dnd5e_engine.rest``).

Cluster 9 (Rest & recovery). Ground truth: SRD 5.2 (2024 ruleset) §Short Rest /
§Long Rest / feature recovery. Every dice draw flows through a seeded ``rng`` so the
resolver is deterministic.
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine.rest import (
    FEATURE_USE_COUNTER_PREFIX,
    HitDicePool,
    recover_feature_uses,
    recover_item_uses,
    resolve_long_rest,
    resolve_short_rest,
)


def test_short_rest_spends_dice_and_heals_within_per_die_bounds():
    """Each spent die heals ``max(1, 1d10 + CON)``; three dice at CON +2 fall in
    ``[9, 36]`` (each die ``[3, 12]``), and the pool loses exactly the spent dice."""
    pool = HitDicePool(hit_die_size=10, dice_remaining=5, dice_total=5)
    outcome = resolve_short_rest(pool, dice_to_spend=3, con_modifier=2, rng=random.Random(7))

    assert outcome.dice_spent == 3
    assert outcome.dice_remaining == 2
    assert len(outcome.rolls) == 3
    assert 9 <= outcome.healed <= 36
    assert outcome.healed == sum(outcome.rolls)
    # Pool mirror reflects the spend but keeps the full total intact.
    assert outcome.pool is not None
    assert outcome.pool.dice_remaining == 2
    assert outcome.pool.dice_total == 5


def test_short_rest_per_die_floor_applies_to_each_die_not_the_sum():
    """A large negative CON modifier can never drive an individual die below 1 — the
    floor is per die, so N dice heal AT LEAST N total (never a floored-once sum)."""
    pool = HitDicePool(hit_die_size=6, dice_remaining=4, dice_total=4)
    outcome = resolve_short_rest(pool, dice_to_spend=4, con_modifier=-10, rng=random.Random(1))

    assert all(r == 1 for r in outcome.rolls)  # every die floored to 1 individually
    assert outcome.healed == 4  # 4 × 1, NOT max(1, sum) == 1


def test_short_rest_is_deterministic_under_same_seed():
    pool = HitDicePool(hit_die_size=10, dice_remaining=5, dice_total=5)
    a = resolve_short_rest(pool, dice_to_spend=3, con_modifier=2, rng=random.Random(7))
    b = resolve_short_rest(pool, dice_to_spend=3, con_modifier=2, rng=random.Random(7))
    assert a.rolls == b.rolls
    assert a.healed == b.healed


def test_short_rest_rejects_overspend():
    pool = HitDicePool(hit_die_size=10, dice_remaining=2, dice_total=5)
    with pytest.raises(ValueError, match="only 2 remaining"):
        resolve_short_rest(pool, dice_to_spend=3, con_modifier=2, rng=random.Random(7))


def test_short_rest_rejects_negative_spend():
    pool = HitDicePool(hit_die_size=10, dice_remaining=5, dice_total=5)
    with pytest.raises(ValueError, match="non-negative"):
        resolve_short_rest(pool, dice_to_spend=-1, con_modifier=2, rng=random.Random(7))


def test_short_rest_zero_dice_is_a_noop_heal():
    pool = HitDicePool(hit_die_size=10, dice_remaining=5, dice_total=5)
    outcome = resolve_short_rest(pool, dice_to_spend=0, con_modifier=2, rng=random.Random(7))
    assert outcome.healed == 0
    assert outcome.rolls == ()
    assert outcome.dice_remaining == 5


def test_long_rest_restores_all_hp_and_all_hit_dice():
    """SRD 2024 full recovery — NOT the stale 2014 half-hit-dice rule (which would
    leave ``1 + max(1, 5 // 2) == 3`` dice)."""
    pool = HitDicePool(hit_die_size=10, dice_remaining=1, dice_total=5)
    outcome = resolve_long_rest(pool, hp_current=10, hp_max=50)

    assert outcome.hp_current == 50
    assert outcome.dice_remaining == 5
    assert outcome.pool is not None
    assert outcome.pool.dice_remaining == outcome.pool.dice_total == 5
    assert outcome.healed == 40
    assert outcome.rolls == ()


def test_long_rest_at_full_health_heals_nothing():
    pool = HitDicePool(hit_die_size=8, dice_remaining=3, dice_total=3)
    outcome = resolve_long_rest(pool, hp_current=30, hp_max=30)
    assert outcome.hp_current == 30
    assert outcome.healed == 0
    assert outcome.dice_remaining == 3


def test_recover_feature_uses_resets_spent_counters():
    counters = {
        f"{FEATURE_USE_COUNTER_PREFIX}second-wind": {"spent": 1},
        f"{FEATURE_USE_COUNTER_PREFIX}action-surge": {"spent": 2},
        "some-host-counter": {"value": 3, "max": 3},  # untouched
    }
    # No recovery rules supplied → conservative full recovery (spent → 0) on any rest.
    for period in ("sr", "lr"):
        recovered = recover_feature_uses(counters, period)
        assert recovered == {"second-wind": 0, "action-surge": 0}
    # Pure: the input mapping is not mutated.
    assert counters[f"{FEATURE_USE_COUNTER_PREFIX}second-wind"]["spent"] == 1


def test_recover_feature_uses_ignores_non_feature_counters():
    counters = {"charges": {"value": 0, "max": 5}}
    assert recover_feature_uses(counters, "lr") == {}


class _Recovery:
    """Structural stand-in for a ``uses.recovery[]`` rule."""

    def __init__(self, period: str, type_: str, formula: str = "") -> None:
        self.period = period
        self.type = type_
        self.formula = formula


# Second Wind's real recovery: one use back on a Short Rest, all on a Long Rest.
_SECOND_WIND_RECOVERY = [_Recovery("lr", "recoverAll"), _Recovery("sr", "formula", "1")]


def test_recover_feature_uses_short_rest_formula_regains_one_use():
    """SRD Second Wind Short Rest recovery (``formula: "1"``): regain exactly one
    expended use → ``spent`` decreases by 1, floored at 0, not reset to 0."""
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}second-wind": {"spent": 3}}
    recovery = {"second-wind": _SECOND_WIND_RECOVERY}
    assert recover_feature_uses(counters, "sr", recovery) == {"second-wind": 2}
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}second-wind": {"spent": 1}}
    assert recover_feature_uses(counters, "sr", recovery) == {"second-wind": 0}


def test_recover_feature_uses_long_rest_recovers_all():
    """Second Wind Long Rest recovery (``recoverAll``): the whole pool refills."""
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}second-wind": {"spent": 3}}
    recovery = {"second-wind": _SECOND_WIND_RECOVERY}
    assert recover_feature_uses(counters, "lr", recovery) == {"second-wind": 0}


def test_recover_feature_uses_unhandled_formula_leaves_counter_unchanged():
    """A non-literal recovery formula is not guessed at — the counter is preserved."""
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}odd": {"spent": 2}}
    recovery = {"odd": [_Recovery("sr", "formula", "@abilities.cha.mod")]}
    assert recover_feature_uses(counters, "sr", recovery) == {"odd": 2}


def test_recover_feature_uses_no_rule_for_period_preserves_spent():
    """With recovery data SUPPLIED and no entry for this rest's period, the
    feature does not recharge — ``spent`` is preserved, never over-recovered."""
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}day-only": {"spent": 2}}
    recovery = {"day-only": [_Recovery("day", "recoverAll")]}
    assert recover_feature_uses(counters, "sr", recovery) == {"day-only": 2}


def test_recover_feature_uses_lr_only_feature_does_not_recharge_on_short_rest():
    """SRD: an lr-only feature (Arcane Recovery / Divine Intervention — the
    corpus majority, 41 lr vs 10 sr recovery entries) does NOT recharge on a
    Short Rest; a Long Rest recovers it in full."""
    counters = {f"{FEATURE_USE_COUNTER_PREFIX}arcane-recovery": {"spent": 1}}
    recovery = {"arcane-recovery": [_Recovery("lr", "recoverAll")]}
    assert recover_feature_uses(counters, "sr", recovery) == {"arcane-recovery": 1}
    assert recover_feature_uses(counters, "lr", recovery) == {"arcane-recovery": 0}


class _Rule:
    def __init__(self, period: str, type: str, formula: str = "") -> None:
        self.period = period
        self.type = type
        self.formula = formula


def test_recover_item_uses_filters_prefix_and_recovers_all():
    counters = {
        "item_use:wand-of-binding": {"spent": 3},
        "feature_use:second-wind": {"spent": 1},
    }
    out = recover_item_uses(counters, "dawn", {"wand-of-binding": [_Rule("dawn", "recoverAll")]})
    assert out == {"wand-of-binding": 0}  # feature key untouched/absent


def test_recover_item_uses_dice_formula_rolls_with_rng():
    counters = {"item_use:wand-of-lightning-bolts": {"spent": 7}}
    rules = {"wand-of-lightning-bolts": [_Rule("dawn", "formula", "1d6 + 1")]}
    out = recover_item_uses(counters, "dawn", rules, rng=random.Random(1))
    regained = 7 - out["wand-of-lightning-bolts"]
    assert 2 <= regained <= 7  # 1d6+1 ∈ [2,7]
    # determinism: same seed, same roll
    again = recover_item_uses(counters, "dawn", rules, rng=random.Random(1))
    assert again == out


def test_recover_item_uses_dice_formula_without_rng_preserves():
    counters = {"item_use:x": {"spent": 4}}
    out = recover_item_uses(counters, "dawn", {"x": [_Rule("dawn", "formula", "1d6 + 1")]})
    assert out == {"x": 4}


def test_recover_item_uses_wrong_period_preserves():
    counters = {"item_use:x": {"spent": 2}}
    out = recover_item_uses(counters, "sr", {"x": [_Rule("dawn", "recoverAll")]})
    assert out == {"x": 2}


def test_recover_feature_uses_still_literal_int_without_rng():
    counters = {"feature_use:second-wind": {"spent": 1}}
    out = recover_feature_uses(counters, "sr", {"second-wind": [_Rule("sr", "formula", "1")]})
    assert out == {"second-wind": 0}
