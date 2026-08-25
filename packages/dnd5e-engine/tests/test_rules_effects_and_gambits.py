"""Behavioral tests for ``rules/effects.py`` and ``rules/gambits.py``.

``effects.apply_changes_to_check`` is the fold that turns a bag of active
effects into a single roll bonus plus the narrator's breakdown. The rules
that matter and are easy to regress:

- Changes apply in ascending ``priority``, so a ``multiply`` can deliberately
  scale an earlier ``add`` regardless of which effect was declared first.
- ``multiply``/``upgrade``/``downgrade`` operate on the *bucket contribution*,
  never on ``base_total`` — folding in a base total that contains an
  RNG-rolled die would make the result seed-dependent.
- Unparseable values degrade to a breakdown note and are skipped rather than
  raising mid-roll, and ``custom`` is a documented no-op.

``gambits`` resolves a monster's chosen action. The load-bearing rule is the
downed-target path: attacking a creature at 0 HP auto-hits, auto-crits, and
costs the victim two death-save failures.
"""

from __future__ import annotations

import random

import pytest

from dnd5e_engine.rules.effects import (
    apply_changes_to_check,
    dedupe_by_identity,
    filter_changes_by_bucket,
    roll_dice_str,
)
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange


def _effect(
    *changes: ActiveEffectChange,
    effect_id: str = "effect:bless",
    origin: str = "cast:bless:1",
    target_id: str = "char:abc123def456",
) -> ActiveEffect:
    return ActiveEffect(
        id=effect_id,
        name=effect_id,
        origin=origin,
        target_id=target_id,
        changes=list(changes),
    )


def _change(key: str, mode: str, value: object, priority: int = 20) -> ActiveEffectChange:
    return ActiveEffectChange(key=key, mode=mode, value=value, priority=priority)


# ---------------------------------------------------------------------------
# roll_dice_str
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,low,high",
    [
        ("1d4", 1, 4),
        ("2d6", 2, 12),
        ("1d4+2", 3, 6),
        ("2d6-1", 1, 11),
        ("d8", 1, 8),  # implicit count of 1
        ("-1d4", -4, -1),  # leading sign negates the whole roll
    ],
)
def test_roll_dice_str_stays_within_the_expression_range(expr: str, low: int, high: int) -> None:
    random.seed(21)
    for _ in range(100):
        assert low <= roll_dice_str(expr) <= high


def test_roll_dice_str_of_empty_expression_is_zero() -> None:
    assert roll_dice_str("") == 0
    assert roll_dice_str("   ") == 0


# ---------------------------------------------------------------------------
# filter_changes_by_bucket
# ---------------------------------------------------------------------------


def test_filter_selects_only_matching_keys_in_order() -> None:
    effects = [
        _effect(
            _change("attack.roll.bonus", "add", 1),
            _change("damage.bonus", "add", 2),
            effect_id="effect:a",
        ),
        _effect(_change("attack.roll.bonus", "add", 3), effect_id="effect:b"),
    ]

    changes = filter_changes_by_bucket(effects, "attack.roll.bonus")

    assert [c.value for c in changes] == [1, 3]


def test_filter_of_an_unused_bucket_is_empty() -> None:
    effects = [_effect(_change("damage.bonus", "add", 2))]

    assert filter_changes_by_bucket(effects, "ac.bonus") == []


# ---------------------------------------------------------------------------
# apply_changes_to_check — add mode
# ---------------------------------------------------------------------------


def test_no_effects_leaves_the_total_untouched() -> None:
    total, breakdown = apply_changes_to_check(10, "attack.roll.bonus", [])

    assert total == 10
    assert breakdown == []


def test_add_integer_change() -> None:
    total, breakdown = apply_changes_to_check(
        10, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", 3))]
    )

    assert total == 13
    assert breakdown == ["effect(+3)"]


def test_add_negative_integer_change() -> None:
    total, breakdown = apply_changes_to_check(
        10, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", -2))]
    )

    assert total == 8
    assert breakdown == ["effect(-2)"]


def test_add_flat_integer_string_is_not_treated_as_dice() -> None:
    """Regression: SRD asset templates encode flat bonuses as "1"/"-1"
    strings. Routing those through the dice parser would raise or randomize
    a value that should be flat."""
    total, breakdown = apply_changes_to_check(
        10, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", "-1"))]
    )

    assert total == 9
    assert breakdown == ["effect(-1)"]


def test_add_dice_formula_rolls_within_range_and_reports_the_roll() -> None:
    random.seed(22)
    for _ in range(50):
        total, breakdown = apply_changes_to_check(
            10, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", "1d4"))]
        )

        assert 11 <= total <= 14
        assert breakdown[0].startswith("effect(1d4:")


def test_add_boolean_change_counts_as_one() -> None:
    total, breakdown = apply_changes_to_check(
        0, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", True))]
    )

    assert total == 1
    assert breakdown == ["effect(+1)"]


def test_unparseable_add_string_is_skipped_with_a_breakdown_note() -> None:
    total, breakdown = apply_changes_to_check(
        10, "attack.roll.bonus", [_effect(_change("attack.roll.bonus", "add", "banana"))]
    )

    assert total == 10
    assert breakdown == ["effect(banana:unparsed)"]


def test_multiple_add_changes_accumulate() -> None:
    total, _ = apply_changes_to_check(
        10,
        "attack.roll.bonus",
        [
            _effect(_change("attack.roll.bonus", "add", 2), effect_id="effect:a"),
            _effect(_change("attack.roll.bonus", "add", 3), effect_id="effect:b"),
        ],
    )

    assert total == 15


# ---------------------------------------------------------------------------
# apply_changes_to_check — override mode
# ---------------------------------------------------------------------------


def test_advantage_flag_is_reported_without_changing_the_total() -> None:
    """Advantage is a roll mechanic, not a numeric bonus — folding it into
    the total would double-count it against the caller's own adv handling."""
    total, breakdown = apply_changes_to_check(
        10,
        "flags.advantage.attack",
        [_effect(_change("flags.advantage.attack", "override", True))],
    )

    assert total == 10
    assert breakdown == ["effect(advantage)"]


def test_disadvantage_flag_is_reported_without_changing_the_total() -> None:
    total, breakdown = apply_changes_to_check(
        10,
        "flags.disadvantage.attack",
        [_effect(_change("flags.disadvantage.attack", "override", True))],
    )

    assert total == 10
    assert breakdown == ["effect(disadvantage)"]


def test_non_flag_override_is_surfaced_generically() -> None:
    total, breakdown = apply_changes_to_check(
        10, "ac.override", [_effect(_change("ac.override", "override", 18))]
    )

    assert total == 10
    assert breakdown == ["effect(ac.override=override)"]


# ---------------------------------------------------------------------------
# apply_changes_to_check — multiply / upgrade / downgrade
# ---------------------------------------------------------------------------


def test_multiply_scales_the_bucket_contribution_not_the_base_total() -> None:
    """base 10 + add 3, then x2 -> 10 + 6, NOT (10+3)*2. Multiplying the base
    would make the result depend on an RNG-rolled base."""
    total, breakdown = apply_changes_to_check(
        10,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 3, priority=10),
                _change("damage.bonus", "multiply", 2, priority=20),
            )
        ],
    )

    assert total == 16
    assert breakdown == ["effect(+3)", "effect(x2)"]


def test_upgrade_raises_the_contribution_but_never_lowers_it() -> None:
    raised, _ = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 2, priority=10),
                _change("damage.bonus", "upgrade", 5, priority=20),
            )
        ],
    )
    kept, _ = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 7, priority=10),
                _change("damage.bonus", "upgrade", 5, priority=20),
            )
        ],
    )

    assert raised == 5
    assert kept == 7


def test_downgrade_caps_the_contribution_but_never_raises_it() -> None:
    capped, _ = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 9, priority=10),
                _change("damage.bonus", "downgrade", 4, priority=20),
            )
        ],
    )
    kept, _ = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 1, priority=10),
                _change("damage.bonus", "downgrade", 4, priority=20),
            )
        ],
    )

    assert capped == 4
    assert kept == 1


@pytest.mark.parametrize("mode", ["multiply", "upgrade", "downgrade"])
def test_unparseable_scalar_modes_are_skipped(mode: str) -> None:
    total, breakdown = apply_changes_to_check(
        5,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 2, priority=10),
                _change("damage.bonus", mode, "1d4", priority=20),
            )
        ],
    )

    assert total == 7  # the add still landed; the bad scalar was dropped
    assert breakdown[-1] == "effect(1d4:unparsed)"


@pytest.mark.parametrize("mode", ["multiply", "upgrade", "downgrade"])
def test_scalar_modes_accept_integer_strings(mode: str) -> None:
    total, _ = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(
                _change("damage.bonus", "add", 3, priority=10),
                _change("damage.bonus", mode, " 2 ", priority=20),
            )
        ],
    )

    assert total == {"multiply": 6, "upgrade": 3, "downgrade": 2}[mode]


def test_custom_mode_is_a_documented_no_op() -> None:
    total, breakdown = apply_changes_to_check(
        10, "damage.bonus", [_effect(_change("damage.bonus", "custom", 5))]
    )

    assert total == 10
    assert breakdown == []


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


def test_changes_apply_in_ascending_priority_across_effects() -> None:
    """The multiply is declared on the *first* effect but carries the higher
    priority, so it must still run after the second effect's add."""
    total, breakdown = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(_change("damage.bonus", "multiply", 3, priority=30), effect_id="effect:a"),
            _effect(_change("damage.bonus", "add", 2, priority=10), effect_id="effect:b"),
        ],
    )

    assert total == 6
    assert breakdown == ["effect(+2)", "effect(x3)"]


def test_equal_priority_preserves_declaration_order() -> None:
    total, breakdown = apply_changes_to_check(
        0,
        "damage.bonus",
        [
            _effect(_change("damage.bonus", "add", 5, priority=20), effect_id="effect:a"),
            _effect(_change("damage.bonus", "downgrade", 2, priority=20), effect_id="effect:b"),
        ],
    )

    assert total == 2
    assert breakdown == ["effect(+5)", "effect(downgrade:2)"]


def test_changes_for_other_buckets_are_ignored() -> None:
    total, _ = apply_changes_to_check(
        10,
        "attack.roll.bonus",
        [_effect(_change("attack.roll.bonus", "add", 1), _change("damage.bonus", "add", 100))],
    )

    assert total == 11


# ---------------------------------------------------------------------------
# dedupe_by_identity
# ---------------------------------------------------------------------------


def test_dedupe_keeps_the_first_instance_of_an_identity() -> None:
    first = _effect(_change("damage.bonus", "add", 1))
    duplicate = _effect(_change("damage.bonus", "add", 99))

    result = dedupe_by_identity([first, duplicate])

    assert len(result) == 1
    assert result[0].changes[0].value == 1


def test_dedupe_treats_a_different_target_as_a_distinct_effect() -> None:
    """The same Bless instance on two party members is two effects."""
    a = _effect(target_id="char:aaa111222333")
    b = _effect(target_id="char:bbb444555666")

    assert len(dedupe_by_identity([a, b])) == 2


def test_dedupe_treats_a_different_origin_as_a_distinct_effect() -> None:
    """Two castings of the same spell on the same target are distinct."""
    a = _effect(origin="cast:bless:1")
    b = _effect(origin="cast:bless:2")

    assert len(dedupe_by_identity([a, b])) == 2


def test_dedupe_of_an_empty_iterable() -> None:
    assert dedupe_by_identity([]) == []


# ---------------------------------------------------------------------------
# gambits — parse_damage_dice
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# gambits — resolve_monster_action
# ---------------------------------------------------------------------------


def _target(hp_current: int = 20, armor_class: int = 15) -> dict[str, object]:
    return {
        "entity_id": "char:abc123def456",
        "name": "Hero",
        "hp_current": hp_current,
        "armor_class": armor_class,
    }


# ---------------------------------------------------------------------------
# gambits — assign_behavior_profile
# ---------------------------------------------------------------------------
