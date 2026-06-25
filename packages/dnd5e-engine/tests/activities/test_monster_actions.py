"""Tests for typed monster-action selection + multiattack fan-out (cutover task 3).

Exercised against the REAL canonical owlbear + goblin-boss via BundledAssetLoader.
Both monsters' multiattack descriptions reference sub-attacks only by Foundry
``[[/item .<id>]]`` tokens with no rendered label, so neither can take the precise
name-join path — both resolve via the logged fallback (repeat first attack sibling).
"""

from __future__ import annotations

import logging

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackDamageBlock,
    DamagePartBlock,
    RangeBlock,
    SaveActivity,
)
from dnd5e_srd_data.schema.monster import MonsterAction, MonsterActionKind

from dnd5e_engine.activities.monster_actions import (
    expand_action_to_activities,
    select_typed_monster_action,
)


def test_owlbear_multiattack_fans_out_to_two_attacks() -> None:
    owlbear = BundledAssetLoader().get_monster("owlbear")
    assert owlbear is not None
    action = select_typed_monster_action(owlbear)
    assert action is not None
    assert action.slug == "multiattack"
    activities = expand_action_to_activities(owlbear, action)
    assert len(activities) == 2
    assert all(isinstance(a, AttackActivity) for a in activities)


def test_goblin_boss_multiattack_count_two() -> None:
    gb = BundledAssetLoader().get_monster("goblin-boss")
    assert gb is not None
    action = select_typed_monster_action(gb)
    assert action is not None
    activities = expand_action_to_activities(gb, action)
    assert len(activities) == 2


def test_non_multiattack_action_returns_its_activities_verbatim() -> None:
    owlbear = BundledAssetLoader().get_monster("owlbear")
    assert owlbear is not None
    rend = next(a for a in owlbear.actions if a.slug == "rend")
    activities = expand_action_to_activities(owlbear, rend)
    assert activities == rend.activities
    assert all(isinstance(a, (AttackActivity, SaveActivity)) for a in activities)


def _claw_attack() -> MonsterAction:
    return MonsterAction(
        slug="claw",
        name="Claw",
        kind=MonsterActionKind.ACTION,
        description="Melee Weapon Attack. Claw.",
        activities=[
            AttackActivity(
                name="Claw",
                range=RangeBlock(units="self", value=None),
                damage=AttackDamageBlock(
                    parts=[DamagePartBlock(number=2, denomination=6, types=["slashing"])]
                ),
            )
        ],
    )


def test_precise_multiattack_repeats_matched_sibling_per_prose_count() -> None:
    """A label-joined multiattack expands the matched sibling ``count`` times.

    The precise path (rendered ``[[/item]]{label}`` joins onto a sibling name)
    previously emitted each matched sibling ONCE, dropping the prose count —
    "makes TWO claw attacks" yielded a single claw. The matched sibling must
    repeat ``count`` times, like the fallback's ``* count``.
    """
    base = BundledAssetLoader().get_monster("owlbear")
    assert base is not None
    claw = _claw_attack()
    multiattack = MonsterAction(
        slug="multiattack",
        name="Multiattack",
        kind=MonsterActionKind.ACTION,
        # Rendered label "Claw" joins onto the claw sibling; count word "two".
        description="The creature makes two [[/item .abc123]]{Claw} attacks.",
        activities=[],
    )
    monster = base.model_copy(update={"actions": [multiattack, claw]})

    activities = expand_action_to_activities(monster, multiattack)

    assert len(activities) == 2, "the matched claw sibling must repeat per the prose count"
    assert all(isinstance(a, AttackActivity) and a.name == "Claw" for a in activities)


def test_multiattack_with_no_attack_sibling_logs_and_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A multiattack whose siblings carry no attack/save activity cannot resolve.
    base = BundledAssetLoader().get_monster("owlbear")
    assert base is not None
    multiattack = MonsterAction(
        slug="multiattack",
        name="Multiattack",
        kind=MonsterActionKind.ACTION,
        description="The creature makes two attacks.",
        activities=[],
    )
    monster = base.model_copy(update={"actions": [multiattack]})
    with caplog.at_level(logging.WARNING):
        activities = expand_action_to_activities(monster, multiattack)
    assert activities == []
    assert "multiattack_join_unresolved" in caplog.text
