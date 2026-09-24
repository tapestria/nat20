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
