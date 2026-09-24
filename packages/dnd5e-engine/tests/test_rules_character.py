"""Pure character-derivation rules (rules/character.py): one section per plan task."""

from __future__ import annotations

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import PassiveEffectChange

from dnd5e_engine.rules import character as rc

LOADER = BundledAssetLoader()


# ── Task 3 ──


def test_extra_attack_count_takes_the_highest_tier_never_the_sum() -> None:
    assert rc.extra_attack_count([]) == 0
    assert rc.extra_attack_count(["extra-attack"]) == 1
    assert rc.extra_attack_count(["extra-attack", "two-extra-attacks"]) == 2
    assert rc.extra_attack_count(["extra-attack", "two-extra-attacks", "three-extra-attacks"]) == 3


def test_leveled_feature_slugs_uses_each_sources_own_level() -> None:
    slugs = rc.leveled_feature_slugs(
        [(LOADER.get_class("fighter"), 1), (LOADER.get_class("wizard"), 4), (None, 9)]
    )
    assert "second-wind" in slugs
    assert "arcane-recovery" in slugs
    assert "extra-attack" not in slugs
    assert "action-surge" not in slugs


def test_granted_feature_slugs_keeps_its_single_level_contract() -> None:
    fighter = LOADER.get_class("fighter")
    assert rc.granted_feature_slugs([fighter, None], level=5) == rc.leveled_feature_slugs(
        [(fighter, 5)]
    )


def test_subclass_gate_level_is_3_for_every_srd_class() -> None:
    for slug in LOADER.list_slugs("classes"):
        cls = LOADER.get_class(slug)
        assert cls is not None
        assert rc.subclass_gate_level(cls) == 3, slug


# ── Task 4 ──


def test_fixed_hit_points_match_the_srd_table() -> None:
    assert [rc.fixed_hit_points(d) for d in (6, 8, 10, 12)] == [4, 5, 6, 7]
    assert rc.hit_die_size("d10") == 10


def test_hit_points_max_single_class_fixed() -> None:
    assert rc.hit_points_max({"fighter": 1}, {"fighter": 10}, 2) == 12
    assert rc.hit_points_max({"fighter": 5}, {"fighter": 10}, 2) == 44


def test_only_the_first_class_takes_the_die_maximum() -> None:
    dice = {"fighter": 10, "rogue": 8}
    assert rc.hit_points_max({"fighter": 3, "rogue": 2}, dice, 2) == 42
    assert rc.hit_points_max({"rogue": 2, "fighter": 3}, dice, 2) == 10 + 7 + 3 * 8


def test_each_level_gains_at_least_one_hit_point() -> None:
    assert rc.hit_points_max({"wizard": 2}, {"wizard": 6}, -4) == (6 - 4) + 1


def test_recorded_rolls_replace_the_fixed_value() -> None:
    assert (
        rc.hit_points_max({"fighter": 3}, {"fighter": 10}, 1, rolls={"fighter": [1, 10]})
        == 11 + 2 + 11
    )
    assert (
        rc.hit_points_max(
            {"fighter": 1, "wizard": 1}, {"fighter": 10, "wizard": 6}, 0, rolls={"wizard": [3]}
        )
        == 13
    )


@pytest.mark.parametrize(
    ("rolls", "message"),
    [
        ({"fighter": [5]}, "needs 2 roll"),
        ({"fighter": [5, 11]}, "outside 1-10"),
        ({"fighter": [5, 5], "wizard": [3]}, "not in classes"),
    ],
)
def test_recorded_rolls_are_validated(rolls: dict[str, list[int]], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        rc.hit_points_max({"fighter": 3}, {"fighter": 10}, 0, rolls=rolls)


def test_hit_point_bonus_per_level_and_class_level_reference() -> None:
    per_level = PassiveEffectChange(key="system.attributes.hp.bonuses.level", mode=2, value="1")
    overall = PassiveEffectChange(
        key="system.attributes.hp.bonuses.overall", mode=2, value="@classes.sorcerer.levels"
    )
    symbolic = PassiveEffectChange(
        key="system.attributes.hp.bonuses.overall", mode=2, value="@abilities.con.mod"
    )
    assert rc.hit_point_bonus([per_level], total_level=5, classes={"fighter": 5}) == 5
    assert rc.hit_point_bonus([overall], total_level=4, classes={"sorcerer": 3, "wizard": 1}) == 3
    assert rc.hit_point_bonus([symbolic], total_level=1, classes={}) == 0


def test_hit_dice_pool_groups_by_die_size() -> None:
    assert rc.hit_dice_pool({"fighter": 5, "paladin": 5}, {"fighter": 10, "paladin": 10}) == {
        10: 10
    }
    assert rc.hit_dice_pool({"cleric": 5, "paladin": 5}, {"cleric": 8, "paladin": 10}) == {
        8: 5,
        10: 5,
    }
