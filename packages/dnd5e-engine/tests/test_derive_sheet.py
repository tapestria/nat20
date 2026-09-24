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
    # Grappler's prose requirement ("Strength or Dexterity 13+") is not parsed
    # (out of scope), but this build must still be one that legally qualifies.
    assert _sheet(
        classes={"fighter": 4},
        ability_scores={"strength": 13},
        selected_choices=("feat:fighter:4:grappler",),
    ).feats == ("grappler",)
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


def test_feat_token_rejects_ability_score_improvement() -> None:
    with pytest.raises(ValueError, match="asi:"):
        _sheet(
            classes={"fighter": 4},
            selected_choices=("feat:fighter:4:ability-score-improvement",),
        )


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


def test_disciplined_survivor_grants_all_six_saves_at_monk_14() -> None:
    # SRD 5.2 Disciplined Survivor: "Your physical and mental discipline
    # grant you proficiency in all saving throws."
    assert _sheet(classes={"monk": 14}).save_proficiencies == frozenset(
        {"str", "dex", "con", "int", "wis", "cha"}
    )
    assert _sheet(classes={"monk": 13}).save_proficiencies == frozenset({"str", "dex"})


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


# ── Task 7 ──


def test_unarmored_defense_is_derived_when_the_mode_is_unset() -> None:
    barbarian = _sheet(
        classes={"barbarian": 1}, ability_scores={"dexterity": 14, "constitution": 16}
    )
    assert (barbarian.ac, barbarian.ac_calc_mode) == (15, "unarmored_barbarian")
    monk = _sheet(classes={"monk": 1}, ability_scores={"dexterity": 16, "wisdom": 16})
    assert (monk.ac, monk.ac_calc_mode) == (16, "unarmored_monk")


def test_armor_or_a_monk_shield_switches_the_derived_mode_back_to_default() -> None:
    abilities = {"dexterity": 14, "constitution": 16}
    armored = _sheet(classes={"barbarian": 1}, ability_scores=abilities, equipment=("chain-mail",))
    assert (armored.ac, armored.ac_calc_mode) == (16, "default")
    shielded = _sheet(classes={"barbarian": 1}, ability_scores=abilities, equipment=("shield",))
    assert (shielded.ac, shielded.ac_calc_mode) == (17, "unarmored_barbarian")
    monk = _sheet(
        classes={"monk": 1}, ability_scores={"dexterity": 16, "wisdom": 16}, equipment=("shield",)
    )
    assert (monk.ac, monk.ac_calc_mode) == (
        10 + 3,
        "default",
    )  # untrained Shield adds nothing either


def test_a_shield_without_training_adds_nothing() -> None:
    assert (
        _sheet(classes={"wizard": 1}, ability_scores={"dexterity": 14}, equipment=("shield",)).ac
        == 12
    )
    assert (
        _sheet(classes={"fighter": 1}, ability_scores={"dexterity": 14}, equipment=("shield",)).ac
        == 14
    )


def test_draconic_resilience_offers_dex_plus_cha() -> None:
    sheet = _sheet(
        classes={"sorcerer": 3},
        subclass_slug="draconic",
        ability_scores={"dexterity": 14, "charisma": 16},
    )
    assert (sheet.ac, sheet.ac_calc_mode) == (15, "unarmored_bard")


def test_an_explicit_mode_wins_but_must_be_wearable() -> None:
    wizard = _sheet(
        classes={"wizard": 1}, ability_scores={"dexterity": 16}, ac_calc_mode="mage_armor"
    )
    assert (wizard.ac, wizard.ac_calc_mode) == (16, "mage_armor")
    barbarian = _sheet(
        classes={"barbarian": 1},
        ability_scores={"dexterity": 14, "constitution": 16},
        ac_calc_mode="default",
    )
    assert (barbarian.ac, barbarian.ac_calc_mode) == (12, "default")
    with pytest.raises(ValueError, match="unarmored_barbarian"):
        _sheet(
            classes={"barbarian": 1}, equipment=("chain-mail",), ac_calc_mode="unarmored_barbarian"
        )


def test_one_suit_of_armor_and_one_shield() -> None:
    with pytest.raises(ValueError, match="more than one suit of armor"):
        _sheet(classes={"fighter": 1}, equipment=("chain-mail", "leather-armor"))
    with pytest.raises(ValueError, match="more than one Shield"):
        _sheet(classes={"fighter": 1}, equipment=("shield", "sentinel-shield"))


def test_magic_armor_bonus_needs_attunement_when_the_item_requires_it() -> None:
    loose = _sheet(
        classes={"fighter": 1}, ability_scores={"dexterity": 14}, equipment=("dragon-scale-mail",)
    )
    bonded = _sheet(
        classes={"fighter": 1},
        ability_scores={"dexterity": 14},
        equipment=("dragon-scale-mail",),
        attuned_items=("dragon-scale-mail",),
    )
    assert (loose.ac, bonded.ac) == (16, 17)
    glamoured = _sheet(
        classes={"fighter": 1},
        ability_scores={"dexterity": 14},
        equipment=("glamoured-studded-leather",),
    )
    assert glamoured.ac == 15


def test_stealth_disadvantage_follows_the_worn_armor() -> None:
    assert _sheet(classes={"fighter": 1}, equipment=("chain-mail",)).stealth_disadvantage is True
    assert (
        _sheet(classes={"fighter": 1}, equipment=("leather-armor",)).stealth_disadvantage is False
    )
    assert _sheet(classes={"fighter": 1}).stealth_disadvantage is False


def test_the_strength_requirement_reads_the_final_strength() -> None:
    plate = {
        "classes": {"fighter": 4},
        "ability_scores": {"strength": 14},
        "equipment": ("plate-armor",),
    }
    assert _sheet(**plate).base_speed == 20
    assert (
        _sheet(**plate, selected_choices=("asi:fighter:4:strength+1,constitution+1",)).base_speed
        == 30
    )


@pytest.mark.parametrize(
    ("equipment", "attuned", "message"),
    [
        (("ring-of-protection",) * 1, ("ring-of-protection", "ring-of-protection"), "repeats"),
        ((), ("ring-of-protection",), "not in equipment"),
        (("longsword",), ("longsword",), "does not require attunement"),
        (("nope",), ("nope",), "unknown item"),
    ],
)
def test_attunement_rules(
    equipment: tuple[str, ...], attuned: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _sheet(classes={"wizard": 1}, equipment=equipment, attuned_items=attuned)


def test_three_attuned_items_are_fine_and_their_effects_stay_out_of_ac() -> None:
    items = ("ring-of-protection", "cloak-of-protection", "amulet-of-health")
    assert _sheet(classes={"wizard": 5}, equipment=items, attuned_items=items).ac == 10


def test_thief_use_magic_device_raises_the_attunement_limit_to_four() -> None:
    # SRD 5.2 Use Magic Device (Thief, rogue level 13): "You can attune to
    # up to four magic items at once."
    items = ("ring-of-protection", "cloak-of-protection", "amulet-of-health", "boots-of-speed")
    thief = _sheet(
        classes={"rogue": 13}, subclass_slug="thief", equipment=items, attuned_items=items
    )
    assert len(thief.weapon_proficiencies) > 0  # sanity: a full sheet derives
    with pytest.raises(ValueError, match="no more than 4"):
        _sheet(
            classes={"rogue": 13},
            subclass_slug="thief",
            equipment=(*items, "bracers-of-defense"),
            attuned_items=(*items, "bracers-of-defense"),
        )


def test_the_attunement_limit_is_three_without_use_magic_device() -> None:
    items = ("ring-of-protection", "cloak-of-protection", "amulet-of-health", "boots-of-speed")
    with pytest.raises(ValueError, match="no more than 3"):
        _sheet(classes={"wizard": 5}, equipment=items, attuned_items=items)


def test_unknown_non_armor_equipment_is_carried_not_rejected() -> None:
    assert _sheet(classes={"fighter": 1}, equipment=("homebrew-trinket",)).ac == 10
