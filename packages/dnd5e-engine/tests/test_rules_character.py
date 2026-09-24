"""Pure character-derivation rules (rules/character.py): one section per plan task."""

from __future__ import annotations

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import PassiveEffectChange

from dnd5e_engine.rules import character as rc
from dnd5e_engine.rules.skills import passive_perception, skill_proficiency_bonus

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


# ── Task 5 ──

_NAMES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


def test_apply_ability_increases_stops_at_20() -> None:
    assert rc.apply_ability_increases({"strength": 18}, {"strength": 2}, source="x") == {
        "strength": 20
    }
    with pytest.raises(ValueError, match="stop at 20"):
        rc.apply_ability_increases({"strength": 19}, {"strength": 2}, source="x")


def test_validate_increase_budget() -> None:
    allowed = {"strength", "dexterity", "constitution"}
    rc.validate_increase_budget(
        {"strength": 2, "constitution": 1}, allowed=allowed, points=3, cap=2, source="bg"
    )
    for bad, message in (
        ({"intelligence": 2, "strength": 1}, "not among"),
        ({"strength": 3}, "each increase"),
        ({"strength": 1, "dexterity": 1}, "exactly 3"),
    ):
        with pytest.raises(ValueError, match=message):
            rc.validate_increase_budget(bad, allowed=allowed, points=3, cap=2, source="bg")


def test_validate_ability_score_method() -> None:
    array = dict(zip(_NAMES, (15, 14, 13, 12, 10, 8), strict=True))
    rc.validate_ability_score_method(array, "standard_array")
    with pytest.raises(ValueError, match="standard_array"):
        rc.validate_ability_score_method({**array, "charisma": 9}, "standard_array")
    bought = dict(zip(_NAMES, (15, 15, 15, 8, 8, 8), strict=True))  # 9 + 9 + 9 = 27 points
    rc.validate_ability_score_method(bought, "point_buy")
    with pytest.raises(ValueError, match="point_buy"):
        rc.validate_ability_score_method({**bought, "intelligence": 9}, "point_buy")
    with pytest.raises(ValueError, match="point_buy"):
        rc.validate_ability_score_method({**bought, "strength": 16}, "point_buy")


def test_ability_score_improvement_lookup() -> None:
    fighter, monk = LOADER.get_class("fighter"), LOADER.get_class("monk")
    assert rc.ability_score_improvement(fighter, 6) is not None
    assert rc.ability_score_improvement(fighter, 5) is None
    assert rc.ability_score_improvement(monk, 20) is None  # Body and Mind is fixed, not a choice


# ── Task 6 ──


def test_skill_proficiency_bonus_shares() -> None:
    assert skill_proficiency_bonus(3, proficient=True) == 3
    assert skill_proficiency_bonus(3, proficient=True, expertise=True) == 6
    assert skill_proficiency_bonus(3, proficient=False, jack_of_all_trades=True) == 1
    assert skill_proficiency_bonus(3, proficient=True, jack_of_all_trades=True) == 3
    assert skill_proficiency_bonus(3, proficient=False, expertise=True) == 0


def test_passive_perception_keeps_its_positional_contract() -> None:
    assert passive_perception(15, True, 2) == 14  # SRD 5.2's own example
    assert passive_perception(12, True, 2, expertise=True) == 15
    assert passive_perception(12, False, 3, jack_of_all_trades=True) == 12


def test_foundry_weapon_ids_resolve_in_the_corpus() -> None:
    for foundry_id, slug in rc.FOUNDRY_WEAPON_ID_TO_SLUG.items():
        assert LOADER.get_weapon(slug) is not None, foundry_id
    for class_slug in LOADER.list_slugs("classes"):
        grants = rc.proficiency_grants([(LOADER.get_class(class_slug), 20, "primary")])
        for weapon in grants.weapons - {
            "simple_melee",
            "simple_ranged",
            "martial_melee",
            "martial_ranged",
        }:
            assert LOADER.get_weapon(weapon) is not None, (class_slug, weapon)


# ── Task 7 ──

_MODS = {
    "strength": 0,
    "dexterity": 4,
    "constitution": 3,
    "intelligence": 0,
    "wisdom": 2,
    "charisma": 1,
}


def _armor(slug: str):
    armor = LOADER.get_armor(slug)
    assert armor is not None
    return armor


def test_armor_class_formulas() -> None:
    kw = {"body_armor_bonus": 0, "shield_bonus": 0}
    assert rc.armor_class("default", _MODS, body_armor=None, **kw) == 14
    assert (
        rc.armor_class(
            "default", _MODS, body_armor=_armor("chain-mail"), body_armor_bonus=0, shield_bonus=2
        )
        == 18
    )
    assert rc.armor_class("default", _MODS, body_armor=_armor("scale-mail"), **kw) == 16
    assert (
        rc.armor_class(
            "default", _MODS, body_armor=_armor("leather-armor"), body_armor_bonus=1, shield_bonus=0
        )
        == 16
    )
    assert rc.armor_class("mage_armor", _MODS, body_armor=None, **kw) == 17
    assert rc.armor_class("unarmored_barbarian", _MODS, body_armor=None, **kw) == 17
    assert rc.armor_class("unarmored_monk", _MODS, body_armor=None, **kw) == 16
    assert rc.armor_class("unarmored_bard", _MODS, body_armor=None, **kw) == 15
    clumsy = {**_MODS, "dexterity": -1}
    assert (
        rc.armor_class("default", clumsy, body_armor=_armor("chain-mail"), **kw) == 16
    )  # heavy: DEX ignored
    assert (
        rc.armor_class("default", clumsy, body_armor=_armor("scale-mail"), **kw) == 13
    )  # medium: penalty applies


def test_ac_mode_eligibility() -> None:
    assert rc.ac_mode_eligible("default", wearing_armor=True, wielding_shield=True)
    assert rc.ac_mode_eligible("unarmored_barbarian", wearing_armor=False, wielding_shield=True)
    assert not rc.ac_mode_eligible("unarmored_barbarian", wearing_armor=True, wielding_shield=False)
    assert not rc.ac_mode_eligible("unarmored_monk", wearing_armor=False, wielding_shield=True)
    assert rc.ac_mode_eligible("mage_armor", wearing_armor=False, wielding_shield=True)


def test_armor_speed_penalty() -> None:
    assert rc.armor_speed_penalty(_armor("plate-armor"), 15) == 0
    assert rc.armor_speed_penalty(_armor("plate-armor"), 14) == 10
    assert rc.armor_speed_penalty(_armor("scale-mail"), 3) == 0
    assert rc.armor_speed_penalty(None, 3) == 0
