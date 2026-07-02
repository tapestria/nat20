"""C03 — Active-effect change modes.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 3.
"""

from __future__ import annotations

import random

from dnd5e_engine.check import CheckSpec, resolve_check
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange
from tests.e2e.harness import xfail_cluster


@xfail_cluster(3, "Active-effect change modes")
def test_c03_s01_multiply_mode_multiplies_accumulated_bucket_bonus():
    """C03-S01: `multiply` mode change multiplies the accumulated bucket
    bonus on a check.

    core-Foundry `ActiveEffect` change-mode semantics,
    `CONST.ACTIVE_EFFECT_MODES.MULTIPLY` (a `multiply`-mode change
    multiplies the current numeric value at its target key) — this is
    Foundry dnd5e-system plumbing, not SRD rules text; engine:
    packages/dnd5e-engine/src/dnd5e_engine/rules/effects.py
    (`apply_changes_to_check` — `mode == "add"` / `mode == "override"` are
    handled; `multiply` reserved and ignored in Phase 6).
    """
    add_effect = ActiveEffect(
        id="effect:add3",
        name="Add 3",
        origin="test:add3",
        target_id="char:test",
        changes=[ActiveEffectChange(key="check.bonus", mode="add", value=3)],
    )
    multiply_effect = ActiveEffect(
        id="effect:multiply2",
        name="Multiply 2",
        origin="test:multiply2",
        target_id="char:test",
        changes=[ActiveEffectChange(key="check.bonus", mode="multiply", value=2)],
    )

    baseline_spec = CheckSpec(
        kind="ability",
        ability="strength",
        ability_scores={"strength": 14},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=2,
        active_effects=(add_effect,),
    )
    multiplied_spec = CheckSpec(
        kind="ability",
        ability="strength",
        ability_scores={"strength": 14},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=2,
        active_effects=(add_effect, multiply_effect),
    )

    random.seed(4242)
    baseline = resolve_check(baseline_spec)
    random.seed(4242)
    multiplied = resolve_check(multiplied_spec)

    assert multiplied.modifier - baseline.modifier == 3
    assert multiplied.roll_total - baseline.roll_total == 3


@xfail_cluster(3, "Active-effect change modes")
def test_c03_s02_upgrade_mode_only_raises_never_lowers_bucket_bonus():
    """C03-S02: `upgrade` mode only raises a check's bucket bonus, never
    lowers it (A/B pair).

    core-Foundry `ActiveEffect` change-mode semantics,
    `CONST.ACTIVE_EFFECT_MODES.UPGRADE` (`upgrade` = `max(current, value)`,
    symmetric with `DOWNGRADE` = `min(current, value)`) — Foundry
    dnd5e-system plumbing, not SRD rules text; engine:
    packages/dnd5e-engine/src/dnd5e_engine/rules/effects.py
    (`apply_changes_to_check`, same `ignored in Phase 6` gap as C03-S01,
    verified empirically ignored for `upgrade` too).
    """

    def _spec(active_effects):
        return CheckSpec(
            kind="ability",
            ability="strength",
            ability_scores={"strength": 14},
            proficient_skills=(),
            proficient_saves=(),
            proficiency_bonus=2,
            active_effects=active_effects,
        )

    upgrade_effect = ActiveEffect(
        id="effect:upgrade5",
        name="Upgrade to 5",
        origin="test:upgrade5",
        target_id="char:test",
        changes=[ActiveEffectChange(key="check.bonus", mode="upgrade", value=5)],
    )

    # Sub-case A (raises): baseline +2, paired run adds upgrade(5), 5 > 2.
    baseline_a = ActiveEffect(
        id="effect:add2",
        name="Add 2",
        origin="test:add2",
        target_id="char:test",
        changes=[ActiveEffectChange(key="check.bonus", mode="add", value=2)],
    )
    random.seed(9001)
    baseline_a_result = resolve_check(_spec((baseline_a,)))
    random.seed(9001)
    with_upgrade_a_result = resolve_check(_spec((baseline_a, upgrade_effect)))

    assert with_upgrade_a_result.modifier - baseline_a_result.modifier == 3
    assert with_upgrade_a_result.roll_total - baseline_a_result.roll_total == 3

    # Sub-case B (never lowers): baseline +7, paired run adds the SAME
    # upgrade(5), 5 < 7 — the lower upgrade value must NOT pull it down.
    baseline_b = ActiveEffect(
        id="effect:add7",
        name="Add 7",
        origin="test:add7",
        target_id="char:test",
        changes=[ActiveEffectChange(key="check.bonus", mode="add", value=7)],
    )
    random.seed(1337)
    baseline_b_result = resolve_check(_spec((baseline_b,)))
    random.seed(1337)
    with_upgrade_b_result = resolve_check(_spec((baseline_b, upgrade_effect)))

    assert with_upgrade_b_result.modifier - baseline_b_result.modifier == 0
    assert with_upgrade_b_result.roll_total - baseline_b_result.roll_total == 0
