"""derive_sheet against the bundled SRD 5.2 corpus: one section per plan task."""

from __future__ import annotations

from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.build_spec import CharacterBuildSpec, DerivedSheet, derive_sheet

LOADER = BundledAssetLoader()


def _sheet(**fields: Any) -> DerivedSheet:
    fields.setdefault("species_slug", "human")
    return derive_sheet(CharacterBuildSpec(**fields), loader=LOADER)


# ── Task 3 ──


def test_subclass_below_its_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="needs fighter level 3"):
        _sheet(classes={"fighter": 2}, subclass_slug="champion")


def test_subclass_gate_reads_the_owning_class_level_not_the_total() -> None:
    with pytest.raises(ValueError, match="needs fighter level 3"):
        _sheet(classes={"fighter": 2, "rogue": 3}, subclass_slug="champion")
    assert _sheet(classes={"fighter": 2, "rogue": 3}, subclass_slug="thief").proficiency_bonus == 3


def test_subclass_of_a_class_not_taken_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a subclass"):
        _sheet(classes={"wizard": 3}, subclass_slug="champion")


def test_level3_build_without_a_subclass_is_allowed() -> None:
    assert _sheet(classes={"fighter": 5}).proficiency_bonus == 3


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"classes": {"nope": 1}}, "unknown class"),
        ({"classes": {"fighter": 1}, "species_slug": "nope"}, "unknown species"),
        ({"classes": {"fighter": 3}, "subclass_slug": "nope"}, "unknown subclass"),
    ],
)
def test_unknown_slugs_are_rejected(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _sheet(**fields)


def test_proficiency_bonus_follows_total_level() -> None:
    assert _sheet(classes={"fighter": 3, "rogue": 2}).proficiency_bonus == 3
    assert _sheet(classes={"wizard": 4}).proficiency_bonus == 2
    assert _sheet(classes={"wizard": 17}).proficiency_bonus == 6


def test_multiclass_features_follow_each_class_level() -> None:
    sheet = _sheet(classes={"fighter": 1, "wizard": 4})
    assert "second-wind" in sheet.features
    assert "arcane-recovery" in sheet.features
    assert "extra-attack" not in sheet.features
    assert sheet.extra_attack_count == 0


def test_extra_attack_tiers_and_non_stacking() -> None:
    assert _sheet(classes={"fighter": 5}).extra_attack_count == 1
    assert _sheet(classes={"fighter": 11}).extra_attack_count == 2
    assert _sheet(classes={"fighter": 20}).extra_attack_count == 3
    assert _sheet(classes={"fighter": 5, "barbarian": 5}).extra_attack_count == 1
    assert _sheet(classes={"fighter": 11, "paladin": 5}).extra_attack_count == 2


def test_species_speed_senses_and_resistances_match_the_passive_projection() -> None:
    sheet = _sheet(species_slug="dwarf", classes={"barbarian": 5})
    assert sheet.base_speed == 40  # walk 30 + Fast Movement +10 at barbarian 5
    assert sheet.senses.darkvision == 120
    assert "poison" in sheet.damage_resistances


def test_ability_modifiers_are_keyed_by_long_name() -> None:
    sheet = _sheet(classes={"fighter": 1}, ability_scores={"strength": 16, "dexterity": 9})
    assert sheet.ability_scores.strength == 16
    assert sheet.ability_modifiers["strength"] == 3
    assert sheet.ability_modifiers["dexterity"] == -1


def test_spell_slots_come_from_the_multiclass_tables() -> None:
    sheet = _sheet(classes={"warlock": 5, "wizard": 2})
    assert sheet.spell_slots == {1: 3}
    assert sheet.pact_slots == {3: 2}


def test_make_build_spec_takes_the_new_fields() -> None:
    from dnd5e_engine.build_spec import make_build_spec

    spec = make_build_spec(
        species_slug="human",
        class_slug="barbarian",
        background_slug="soldier",
        hp_mode="rolled",
        hp_rolls={"barbarian": (7,)},
        ac_calc_mode="unarmored_barbarian",
        attuned_items=(),
        ability_score_method="point_buy",
        level=2,
    )
    assert (spec.background_slug, spec.hp_mode, spec.hp_rolls) == (
        "soldier",
        "rolled",
        {"barbarian": (7,)},
    )
    assert (spec.ac_calc_mode, spec.ability_score_method) == ("unarmored_barbarian", "point_buy")


# ── Task 4 ──


def test_class_order_decides_the_level1_maximum() -> None:
    fighter_first = _sheet(classes={"fighter": 1, "rogue": 1}, ability_scores={"constitution": 14})
    rogue_first = _sheet(classes={"rogue": 1, "fighter": 1}, ability_scores={"constitution": 14})
    assert (fighter_first.hp_max, rogue_first.hp_max) == (12 + 7, 10 + 8)


def test_dwarven_toughness_adds_one_hit_point_per_level() -> None:
    dwarf = _sheet(
        species_slug="dwarf", classes={"fighter": 5}, ability_scores={"constitution": 14}
    )
    assert dwarf.hp_max == 44 + 5


def test_draconic_resilience_adds_the_sorcerer_level() -> None:
    assert _sheet(classes={"sorcerer": 3}, subclass_slug="draconic").hp_max == 6 + 4 + 4 + 3


def test_rolled_mode_uses_the_recorded_rolls() -> None:
    sheet = _sheet(
        classes={"fighter": 3},
        ability_scores={"constitution": 12},
        hp_mode="rolled",
        hp_rolls={"fighter": (1, 10)},
    )
    assert sheet.hp_max == 11 + 2 + 11


def test_rolls_without_rolled_mode_are_a_contradiction() -> None:
    with pytest.raises(ValueError, match="hp_mode"):
        _sheet(classes={"fighter": 2}, hp_rolls={"fighter": (4,)})


def test_rolled_mode_without_rolls_is_rejected() -> None:
    with pytest.raises(ValueError, match="needs 1 roll"):
        _sheet(classes={"fighter": 2}, hp_mode="rolled")


def test_hit_dice_pool_on_the_sheet() -> None:
    assert _sheet(classes={"fighter": 3, "rogue": 2}).hit_dice == {10: 3, 8: 2}


# ── Task 5 ──


def test_asi_raises_the_score_and_its_modifier() -> None:
    sheet = _sheet(
        classes={"fighter": 4},
        ability_scores={"strength": 16},
        selected_choices=("asi:fighter:4:strength+2",),
    )
    assert (sheet.ability_scores.strength, sheet.ability_modifiers["strength"]) == (18, 4)


def test_scores_without_choice_tokens_are_used_verbatim() -> None:
    sheet = _sheet(
        classes={"fighter": 8},
        background_slug="soldier",
        ability_scores={"strength": 20, "constitution": 16},
    )
    assert (sheet.ability_scores.strength, sheet.ability_scores.constitution) == (20, 16)


def test_background_adjustment_stays_within_its_options() -> None:
    sheet = _sheet(
        classes={"fighter": 1},
        background_slug="soldier",
        ability_scores={"strength": 15, "constitution": 14},
        selected_choices=("background:strength+2,constitution+1",),
    )
    assert (sheet.ability_scores.strength, sheet.ability_scores.constitution) == (17, 15)
    with pytest.raises(ValueError, match="not among"):
        _sheet(
            classes={"fighter": 1},
            background_slug="soldier",
            selected_choices=("background:intelligence+2,strength+1",),
        )
    with pytest.raises(ValueError, match="background_slug"):
        _sheet(classes={"fighter": 1}, selected_choices=("background:strength+2,constitution+1",))
    with pytest.raises(ValueError, match="unknown background"):
        _sheet(classes={"fighter": 1}, background_slug="nope")


@pytest.mark.parametrize(
    ("classes", "token", "message"),
    [
        (
            {"fighter": 5},
            "asi:fighter:5:strength+2",
            "no Ability Score Improvement at fighter level 5",
        ),
        ({"fighter": 3}, "asi:fighter:4:strength+2", "needs fighter level 4"),
        ({"fighter": 4}, "asi:rogue:4:strength+2", "not one of"),
        ({"monk": 20}, "asi:monk:20:dexterity+2", "no Ability Score Improvement at monk level 20"),
        ({"fighter": 4}, "asi:fighter:4:strength+1", "exactly 2"),
    ],
)
def test_asi_slots_are_validated(classes: dict[str, int], token: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _sheet(classes=classes, selected_choices=(token,))


def test_an_asi_slot_is_used_once() -> None:
    with pytest.raises(ValueError, match="already used"):
        _sheet(
            classes={"fighter": 4},
            selected_choices=("asi:fighter:4:strength+2", "feat:fighter:4:grappler"),
        )


def test_multiclass_asi_on_the_second_class() -> None:
    sheet = _sheet(
        classes={"fighter": 1, "rogue": 4},
        ability_scores={"dexterity": 16},
        selected_choices=("asi:rogue:4:dex+2",),
    )
    assert sheet.ability_scores.dexterity == 18


def test_increases_apply_in_order_and_stop_at_20() -> None:
    with pytest.raises(ValueError, match="stop at 20"):
        _sheet(
            classes={"fighter": 6},
            ability_scores={"strength": 18},
            selected_choices=("asi:fighter:4:strength+2", "asi:fighter:6:strength+2"),
        )


def test_a_con_increase_raises_hit_points_for_every_level() -> None:
    base = _sheet(classes={"fighter": 8}, ability_scores={"constitution": 17}).hp_max
    raised = _sheet(
        classes={"fighter": 8},
        ability_scores={"constitution": 17},
        selected_choices=("asi:fighter:4:constitution+1,strength+1",),
    ).hp_max
    assert raised - base == 8  # SRD "Adjust Ability Modifiers": +1 per level attained


def test_feats_at_asi_levels_check_prerequisites() -> None:
    assert _sheet(classes={"fighter": 4}, selected_choices=("feat:fighter:4:grappler",)).feats == (
        "grappler",
    )
    with pytest.raises(ValueError, match="character level 19"):
        _sheet(classes={"fighter": 4}, selected_choices=("feat:fighter:4:boon-of-combat-prowess",))
    assert (
        "boon-of-combat-prowess"
        in _sheet(
            classes={"fighter": 19}, selected_choices=("feat:fighter:19:boon-of-combat-prowess",)
        ).feats
    )
    with pytest.raises(ValueError, match="unknown feat"):
        _sheet(classes={"fighter": 4}, selected_choices=("feat:fighter:4:nope",))
    assert (
        "archery"
        in _sheet(classes={"fighter": 4}, selected_choices=("feat:fighter:4:archery",)).feats
    )
    with pytest.raises(ValueError, match="fighting-style"):
        _sheet(classes={"rogue": 4}, selected_choices=("feat:rogue:4:archery",))


def test_feature_choice_picks_join_features_or_feats() -> None:
    assert _sheet(classes={"fighter": 1}, selected_choices=("defense",)).feats == ("defense",)
    assert (
        "divine-order-protector"
        in _sheet(classes={"cleric": 1}, selected_choices=("divine-order-protector",)).features
    )
    warlock = _sheet(
        classes={"warlock": 2}, selected_choices=("agonizing-blast", "armor-of-shadows")
    )
    assert {"agonizing-blast", "armor-of-shadows"} <= set(warlock.features)
    assert (
        "skilled" in _sheet(classes={"wizard": 1}, selected_choices=("skilled",)).feats
    )  # Human Versatile


def test_a_pick_outside_every_reached_pool_is_rejected() -> None:
    with pytest.raises(ValueError, match="not an option"):
        _sheet(classes={"wizard": 1}, selected_choices=("defense",))
    with pytest.raises(ValueError, match="not an option"):
        _sheet(
            classes={"paladin": 1}, selected_choices=("defense",)
        )  # the Paladin's style opens at 2
    assert _sheet(classes={"paladin": 2}, selected_choices=("defense",)).feats == ("defense",)


def test_ability_score_method_checks_the_scores_before_any_increase() -> None:
    array = {
        "strength": 15,
        "dexterity": 14,
        "constitution": 13,
        "intelligence": 12,
        "wisdom": 10,
        "charisma": 8,
    }
    sheet = _sheet(
        classes={"fighter": 4},
        ability_scores=array,
        ability_score_method="standard_array",
        selected_choices=("asi:fighter:4:strength+2",),
    )
    assert sheet.ability_scores.strength == 17
    with pytest.raises(ValueError, match="point_buy"):
        _sheet(
            classes={"fighter": 1},
            ability_scores={"strength": 17},
            ability_score_method="point_buy",
        )


# ── Task 6 ──


def test_save_proficiencies_come_from_the_initial_class_only() -> None:
    assert _sheet(classes={"fighter": 1}).save_proficiencies == frozenset({"str", "con"})
    assert _sheet(classes={"fighter": 1, "rogue": 1}).save_proficiencies == frozenset(
        {"str", "con"}
    )
    assert _sheet(classes={"rogue": 1, "fighter": 1}).save_proficiencies == frozenset(
        {"dex", "int"}
    )
    assert _sheet(classes={"rogue": 15}).save_proficiencies == frozenset(
        {"dex", "int", "wis", "cha"}
    )


def test_weapon_proficiencies_resolve_to_categories_and_slugs() -> None:
    martial = {"martial_melee", "martial_ranged"}
    simple = {"simple_melee", "simple_ranged"}
    assert _sheet(classes={"fighter": 1}).weapon_proficiencies == frozenset(simple | martial)
    assert _sheet(classes={"rogue": 1}).weapon_proficiencies == frozenset(
        simple | {"hand-crossbow", "rapier", "scimitar", "shortsword", "whip"}
    )
    assert _sheet(classes={"wizard": 1}).weapon_proficiencies == frozenset(simple)
    assert martial <= _sheet(classes={"wizard": 1, "fighter": 1}).weapon_proficiencies
    assert (
        martial
        <= _sheet(
            classes={"cleric": 1}, selected_choices=("divine-order-protector",)
        ).weapon_proficiencies
    )


def test_armor_training_follows_primary_and_multiclass_grants() -> None:
    assert _sheet(classes={"fighter": 1}).armor_training == frozenset(
        {"light", "medium", "heavy", "shield"}
    )
    assert _sheet(classes={"wizard": 1}).armor_training == frozenset()
    assert _sheet(classes={"wizard": 1, "fighter": 1}).armor_training == frozenset(
        {"light", "medium", "shield"}
    )
    assert (
        "heavy"
        in _sheet(
            classes={"cleric": 1}, selected_choices=("divine-order-protector",)
        ).armor_training
    )


def test_skill_proficiencies_join_background_and_picks() -> None:
    sheet = _sheet(
        classes={"fighter": 1},
        background_slug="soldier",
        selected_choices=("skill:perception", "skill:acrobatics"),
    )
    assert sheet.skill_proficiencies == frozenset(
        {"athletics", "intimidation", "perception", "acrobatics"}
    )


def test_expertise_needs_the_proficiency() -> None:
    rogue = _sheet(
        classes={"rogue": 1},
        background_slug="criminal",
        selected_choices=("expertise:stealth", "expertise:sleight_of_hand"),
    )
    assert rogue.skill_expertise == frozenset({"stealth", "sleight_of_hand"})
    with pytest.raises(ValueError, match="Expertise in arcana needs proficiency"):
        _sheet(classes={"rogue": 1}, selected_choices=("expertise:arcana",))


def test_passive_perception_folds_proficiency_expertise_and_jack_of_all_trades() -> None:
    assert (
        _sheet(
            classes={"fighter": 1},
            ability_scores={"wisdom": 15},
            selected_choices=("skill:perception",),
        ).passive_perception
        == 14
    )
    assert _sheet(classes={"fighter": 1}, ability_scores={"wisdom": 15}).passive_perception == 12
    rogue = _sheet(
        classes={"rogue": 1},
        ability_scores={"wisdom": 12},
        selected_choices=("skill:perception", "expertise:perception"),
    )
    assert rogue.passive_perception == 10 + 1 + 4
    bard = _sheet(classes={"bard": 2}, ability_scores={"wisdom": 12})
    assert (bard.jack_of_all_trades, bard.passive_perception) == (True, 10 + 1 + 1)
    assert _sheet(classes={"bard": 1}).jack_of_all_trades is False


def test_reliable_talent_flag_arrives_at_rogue_7() -> None:
    assert _sheet(classes={"rogue": 7}).reliable_talent is True
    assert _sheet(classes={"rogue": 6}).reliable_talent is False
