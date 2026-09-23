"""``CharacterBuildSpec.classes`` (spec §3 multiclass carrier) + loader-aware
``derive_multiclass_slots`` (C17-S03) + ``build_party_member`` slot fill."""

from __future__ import annotations

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CharacterBuildSpec, CombatInstance, build_party_member, make_build_spec
from dnd5e_engine.build_spec import derive_multiclass_pact_slots, derive_multiclass_slots
from dnd5e_engine.lib_loader import set_lib_loader_for_tests


@pytest.fixture(autouse=True)
def _loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def test_single_class_spec_projects_classes_dict():
    spec = CharacterBuildSpec(species_slug="human", class_slug="wizard", level=5)
    assert spec.classes == {"wizard": 5}
    assert spec.class_slug == "wizard"
    assert spec.level == 5


def test_classes_dict_projects_primary_class_and_total_level():
    spec = CharacterBuildSpec(species_slug="human", classes={"paladin": 2, "wizard": 3})
    assert spec.class_slug == "paladin"  # first key = primary class
    assert spec.level == 5  # total character level
    assert spec.classes == {"paladin": 2, "wizard": 3}


def test_classes_and_level_must_agree():
    with pytest.raises(ValueError):
        CharacterBuildSpec(species_slug="human", classes={"fighter": 3, "rogue": 2}, level=4)
    # consistent pair is fine (C19 fixtures pass both)
    spec = CharacterBuildSpec(species_slug="human", classes={"fighter": 3, "rogue": 2}, level=5)
    assert spec.level == 5


def test_classes_and_class_slug_must_agree():
    with pytest.raises(ValueError):
        CharacterBuildSpec(species_slug="human", class_slug="rogue", classes={"fighter": 1})


def test_neither_class_slug_nor_classes_rejected():
    with pytest.raises(ValueError):
        CharacterBuildSpec(species_slug="human")


def test_make_build_spec_accepts_classes():
    spec = make_build_spec(species_slug="human", classes={"paladin": 2, "wizard": 3})
    assert spec.level == 5
    assert spec.class_slug == "paladin"
    legacy = make_build_spec(species_slug="human", class_slug="wizard", level=3)
    assert legacy.classes == {"wizard": 3}


def test_derive_multiclass_slots_paladin2_wizard3():
    assert derive_multiclass_slots({"paladin": 2, "wizard": 3}) == {1: 4, 2: 3}


def test_derive_multiclass_slots_single_class_matches_single_table():
    assert derive_multiclass_slots({"wizard": 5}) == {1: 4, 2: 3, 3: 2}
    assert derive_multiclass_slots({"paladin": 1}) == {1: 2}
    assert derive_multiclass_slots({"fighter": 5}) == {}


def test_derive_multiclass_slots_unknown_class_rejected():
    with pytest.raises(ValueError):
        derive_multiclass_slots({"not-a-class": 3})


def test_derive_multiclass_pact_slots_counts_only_warlock_levels():
    assert derive_multiclass_pact_slots({"warlock": 5, "wizard": 2}) == {3: 2}
    assert derive_multiclass_pact_slots({"wizard": 5}) == {}


def test_build_party_member_fills_empty_slot_pools_from_classes():
    spec = make_build_spec(species_slug="human", classes={"warlock": 5, "wizard": 2})
    member = build_party_member(
        spec,
        CombatInstance(entity_id="char:x", name="X", hp_current=10, hp_max=10),
        loader=BundledAssetLoader(),
    )
    assert member.spell_slots == {1: 3}  # wizard 2 => caster level 2
    assert member.pact_slots == {3: 2}


def test_build_party_member_keeps_host_supplied_slots():
    """Spec rule: an explicit value always wins; derivation fills only what is unset."""
    spec = make_build_spec(species_slug="human", class_slug="wizard", level=5)
    member = build_party_member(
        spec,
        CombatInstance(entity_id="char:x", name="X", hp_current=10, hp_max=10, spell_slots={9: 1}),
        loader=BundledAssetLoader(),
    )
    assert member.spell_slots == {9: 1}
