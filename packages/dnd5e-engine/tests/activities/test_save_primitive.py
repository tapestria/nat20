"""Behavioral tests for the shared saving-throw primitive.

``roll_save`` is the single place a save is resolved, used by both the ``save``
activity kind and weapon mastery's topple. The rules it owns:

- **Auto-fail short-circuits without drawing a d20.** Paralyzed/Stunned/
  Petrified/Unconscious creatures auto-fail STR and DEX saves; drawing a die
  anyway would perturb the seeded RNG stream and desync every later roll in
  the combat.
- **Advantage and disadvantage** come from the per-target sidecar and cancel
  when both are present.
- **The modifier is read, not rebuilt** — the resolved per-ability integer off
  the sidecar, +0 when absent.
- **Bless/Bane dice roll inside the seeded stream**, not through ``d20``'s
  global RNG, so a seeded combat stays reproducible.
- **The ``force_save_d20`` seam is scoped to the first target only**, so a
  multi-target save cannot silently reuse one kept die for everyone.
- **Cover adds to Dexterity saves only** (SRD 5.2 §Cover: "a bonus to AC and
  Dexterity saving throws").
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.save_primitive import FORCE_SAVE_D20, roll_save
from dnd5e_engine.types.combat import Combatant

ABILITIES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def _target(entity_id: str = "mon:foe") -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=13,
    )


def _ctx(
    *, forced_d20: int | None = None, seed: int = 1, **kwargs: Any
) -> ActivityResolutionContext:
    variables: dict[str, Any] = {}
    if forced_d20 is not None:
        variables[FORCE_SAVE_D20] = forced_d20
    return ActivityResolutionContext(
        rng=random.Random(seed),
        caster=Combatant(
            entity_id="char:hero",
            entity_type="Character",
            name="Hero",
            initiative=10,
            hp_current=20,
            hp_max=20,
        ),
        targets=[],
        event_emitter=lambda ev: None,
        caster_abilities=dict(ABILITIES),
        variables=variables,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def test_empty_sidecars_roll_a_flat_d20() -> None:
    _roll = roll_save(_ctx(forced_d20=13), _target(), "wis", dc=13)
    total, succeeded = _roll.total, _roll.succeeded

    assert total == 13
    assert succeeded is True


def test_meeting_the_dc_exactly_succeeds() -> None:
    _roll = roll_save(_ctx(forced_d20=15), _target(), "wis", dc=15)
    _, succeeded = _roll.total, _roll.succeeded

    assert succeeded is True


def test_falling_one_short_fails() -> None:
    _roll = roll_save(_ctx(forced_d20=14), _target(), "wis", dc=15)
    _, succeeded = _roll.total, _roll.succeeded

    assert succeeded is False


# ---------------------------------------------------------------------------
# Auto-fail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ability", ["str", "dex"])
def test_auto_fail_short_circuits_regardless_of_the_roll(ability: str) -> None:
    ctx = _ctx(
        forced_d20=20,
        passive_save_auto_fail={"mon:foe": ["STR", "DEX"]},
        passive_save_modifiers={"mon:foe": {ability: 10}},
    )

    _roll = roll_save(ctx, _target(), ability, dc=5)
    total, succeeded = _roll.total, _roll.succeeded

    assert (total, succeeded) == (0, False)


def test_auto_fail_does_not_consume_the_rng_stream() -> None:
    """A drawn-then-discarded die would desync every later roll in the combat."""
    ctx = _ctx(passive_save_auto_fail={"mon:foe": ["DEX"]})
    expected_next = random.Random(1).randint(1, 20)

    roll_save(ctx, _target(), "dex", dc=10)

    assert ctx.rng.randint(1, 20) == expected_next


def test_auto_fail_does_not_apply_to_other_abilities() -> None:
    """Paralysis auto-fails STR and DEX only — a WIS save still rolls."""
    ctx = _ctx(forced_d20=18, passive_save_auto_fail={"mon:foe": ["STR", "DEX"]})

    _roll = roll_save(ctx, _target(), "wis", dc=15)
    total, succeeded = _roll.total, _roll.succeeded

    assert total == 18
    assert succeeded is True


def test_auto_fail_is_scoped_to_the_listed_target() -> None:
    ctx = _ctx(forced_d20=18, passive_save_auto_fail={"mon:other": ["DEX"]})

    _roll = roll_save(ctx, _target(), "dex", dc=10)
    total, _ = _roll.total, _roll.succeeded

    assert total == 18


# ---------------------------------------------------------------------------
# Modifier sourcing
# ---------------------------------------------------------------------------


def test_resolved_per_ability_modifier_is_added() -> None:
    ctx = _ctx(forced_d20=10, passive_save_modifiers={"mon:foe": {"wis": 4}})

    _roll = roll_save(ctx, _target(), "wis", dc=14)
    total, _ = _roll.total, _roll.succeeded

    assert total == 14


def test_a_negative_modifier_lowers_the_total() -> None:
    ctx = _ctx(forced_d20=10, passive_save_modifiers={"mon:foe": {"str": -2}})

    _roll = roll_save(ctx, _target(), "str", dc=10)
    total, succeeded = _roll.total, _roll.succeeded

    assert total == 8
    assert succeeded is False


def test_a_modifier_for_another_ability_is_not_applied() -> None:
    ctx = _ctx(forced_d20=10, passive_save_modifiers={"mon:foe": {"wis": 5}})

    _roll = roll_save(ctx, _target(), "con", dc=10)
    total, _ = _roll.total, _roll.succeeded

    assert total == 10


def test_an_absent_target_contributes_no_modifier() -> None:
    ctx = _ctx(forced_d20=10, passive_save_modifiers={"mon:other": {"wis": 5}})

    _roll = roll_save(ctx, _target(), "wis", dc=10)
    total, _ = _roll.total, _roll.succeeded

    assert total == 10


# ---------------------------------------------------------------------------
# Advantage / disadvantage
# ---------------------------------------------------------------------------


def test_advantage_keeps_the_higher_of_two_dice() -> None:
    ctx = _ctx(passive_save_adv={"mon:foe": ["WIS"]})
    rolls = random.Random(1)
    expected = max(rolls.randint(1, 20), rolls.randint(1, 20))

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == expected


def test_disadvantage_keeps_the_lower_of_two_dice() -> None:
    ctx = _ctx(passive_save_dis={"mon:foe": ["WIS"]})
    rolls = random.Random(1)
    expected = min(rolls.randint(1, 20), rolls.randint(1, 20))

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == expected


def test_advantage_and_disadvantage_cancel_to_a_single_die() -> None:
    ctx = _ctx(passive_save_adv={"mon:foe": ["WIS"]}, passive_save_dis={"mon:foe": ["WIS"]})
    expected = random.Random(1).randint(1, 20)

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == expected


def test_advantage_for_another_ability_does_not_apply() -> None:
    ctx = _ctx(passive_save_adv={"mon:foe": ["STR"]})
    expected = random.Random(1).randint(1, 20)

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == expected


# ---------------------------------------------------------------------------
# The forced-d20 seam
# ---------------------------------------------------------------------------


def test_the_forced_d20_applies_to_the_first_target_only() -> None:
    """Otherwise one pinned die would silently stand in for every target of a
    multi-target save."""
    ctx = _ctx(forced_d20=20)

    _roll = roll_save(ctx, _target(), "wis", dc=1, target_index=0)
    first, _ = _roll.total, _roll.succeeded
    _roll = roll_save(ctx, _target("mon:second"), "wis", dc=1, target_index=1)
    second, _ = _roll.total, _roll.succeeded

    assert first == 20
    # The second target's die is drawn live off the seeded rng, so it matches
    # the next value in that stream rather than the forced one.
    assert second == random.Random(1).randint(1, 20)


def test_a_forced_d20_bypasses_advantage() -> None:
    ctx = _ctx(forced_d20=7, passive_save_adv={"mon:foe": ["WIS"]})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 7


# ---------------------------------------------------------------------------
# Bless / Bane bonus dice
# ---------------------------------------------------------------------------


def test_bless_adds_its_bonus_die() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "+1d4"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert 11 <= total <= 14


def test_bane_subtracts_its_bonus_die() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "-1d4"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert 6 <= total <= 9


def test_a_flat_bonus_expression_is_added() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "+2"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 12


def test_stacked_bonus_expressions_combine() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "1d4 - 1d4"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert 7 <= total <= 13


def test_a_parenthesised_bonus_expression_is_supported() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "(2 + 3)"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 15


def test_an_empty_bonus_expression_contributes_nothing() -> None:
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": ""})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 10


def test_bonus_dice_are_drawn_from_the_seeded_stream() -> None:
    """Same seed, same bonus — d20's global RNG would break reproducibility."""
    totals = [
        roll_save(
            _ctx(forced_d20=10, seed=7, passive_save_bonus={"mon:foe": "+1d4"}),
            _target(),
            "wis",
            dc=1,
        ).total
        for _ in range(2)
    ]

    assert totals[0] == totals[1]


def test_an_unparseable_bonus_expression_raises_a_clear_error() -> None:
    """Silently ignoring it would drop a Bless the player can see on their
    sheet."""
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "not-a-roll"})

    with pytest.raises(ValueError, match="Unparseable passive_save_bonus"):
        roll_save(ctx, _target(), "wis", dc=1)


# ---------------------------------------------------------------------------
# Cover
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cover,bonus", [("half", 2), ("three_quarters", 5), ("none", 0)])
def test_cover_adds_to_dexterity_saves(cover: str, bonus: int) -> None:
    ctx = _ctx(forced_d20=10, target_cover={"mon:foe": cover})

    _roll = roll_save(ctx, _target(), "dex", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 10 + bonus


def test_cover_does_not_apply_to_non_dexterity_saves() -> None:
    """SRD 5.2 §Cover is scoped to AC and Dexterity saves."""
    ctx = _ctx(forced_d20=10, target_cover={"mon:foe": "three_quarters"})

    _roll = roll_save(ctx, _target(), "wis", dc=1)
    total, _ = _roll.total, _roll.succeeded

    assert total == 10


# ---------------------------------------------------------------------------
# F2c — D20 Test provenance (the shared ``roll_d20_test`` primitive)
# ---------------------------------------------------------------------------


def test_the_roll_reports_its_kept_natural_and_flat_modifier() -> None:
    ctx = _ctx(forced_d20=12, passive_save_modifiers={"mon:foe": {"wis": 3}})

    roll = roll_save(ctx, _target(), "wis", dc=1)

    assert roll.natural == 12
    assert roll.modifier == 3
    assert roll.total == roll.natural + roll.modifier
    assert roll.sources == ()


def test_cover_lands_in_the_reported_modifier_on_a_dex_save() -> None:
    """Cover is deterministic, so it folds into the flat modifier rather than
    being an unexplained gap between ``natural + modifier`` and ``total``."""
    ctx = _ctx(
        forced_d20=10,
        passive_save_modifiers={"mon:foe": {"dex": 2}},
        target_cover={"mon:foe": "three_quarters"},
    )

    roll = roll_save(ctx, _target(), "dex", dc=1)

    assert roll.modifier == 2 + 5
    assert roll.total == 10 + 7


def test_bless_dice_are_excluded_from_the_reported_modifier() -> None:
    """The Bless/Bane sidecar must be rolled AFTER the d20 to keep the seeded
    draw ORDER, so it lands in ``total`` but not ``modifier`` — the same
    convention ``AttackRolled.modifier`` documents."""
    ctx = _ctx(forced_d20=10, passive_save_bonus={"mon:foe": "+1d4"})

    roll = roll_save(ctx, _target(), "wis", dc=1)

    assert roll.modifier == 0
    assert 1 <= roll.total - (roll.natural or 0) - roll.modifier <= 4


def test_advantage_is_reported_as_a_target_condition_source() -> None:
    """``passive_save_adv`` / ``passive_save_dis`` are produced only by
    ``rules/conditions.py::project_passive_save_modifiers`` — always a
    condition on the SAVING creature (see ``_roll_save_d20``)."""
    ctx = _ctx(passive_save_adv={"mon:foe": ["WIS"]})

    roll = roll_save(ctx, _target(), "wis", dc=1)

    assert roll.sources == ("condition:target",)


def test_disadvantage_is_reported_as_a_target_condition_source() -> None:
    ctx = _ctx(passive_save_dis={"mon:foe": ["DEX"]})

    roll = roll_save(ctx, _target(), "dex", dc=1)

    assert roll.sources == ("condition:target",)


def test_cancelling_sources_are_both_reported() -> None:
    """SRD 5.2 §Advantage and Disadvantage: they cancel to a normal roll, but
    both contributions are still real and are surfaced for narration."""
    ctx = _ctx(passive_save_adv={"mon:foe": ["WIS"]}, passive_save_dis={"mon:foe": ["WIS"]})

    roll = roll_save(ctx, _target(), "wis", dc=1)

    assert roll.sources == ("condition:target", "condition:target")
    # ...and still exactly one die was drawn.
    assert roll.natural == random.Random(1).randint(1, 20)


def test_an_auto_failed_save_reports_no_natural() -> None:
    ctx = _ctx(passive_save_auto_fail={"mon:foe": ["DEX"]})

    roll = roll_save(ctx, _target(), "dex", dc=5)

    assert (roll.total, roll.succeeded, roll.natural, roll.modifier) == (0, False, None, 0)


@pytest.mark.parametrize(
    ("sidecars", "expected_draws"),
    [
        ({}, 1),
        ({"passive_save_adv": {"mon:foe": ["WIS"]}}, 2),
        ({"passive_save_dis": {"mon:foe": ["WIS"]}}, 2),
        (
            {
                "passive_save_adv": {"mon:foe": ["WIS"]},
                "passive_save_dis": {"mon:foe": ["WIS"]},
            },
            1,
        ),
    ],
)
def test_draw_counts_are_unchanged_by_the_primitive(
    sidecars: dict[str, Any], expected_draws: int
) -> None:
    """Determinism contract: routing through ``roll_d20_test`` must not add or
    remove a single draw from any seeded stream."""
    ctx = _ctx(**sidecars)
    reference = random.Random(1)
    for _ in range(expected_draws):
        reference.randint(1, 20)

    roll_save(ctx, _target(), "wis", dc=1)

    assert ctx.rng.randint(1, 20) == reference.randint(1, 20)


def test_a_forced_natural_draws_nothing_even_under_advantage() -> None:
    ctx = _ctx(forced_d20=17, passive_save_adv={"mon:foe": ["WIS"]})
    expected_next = random.Random(1).randint(1, 20)

    roll = roll_save(ctx, _target(), "wis", dc=1)

    assert roll.natural == 17
    assert ctx.rng.randint(1, 20) == expected_next
