"""Live multiclass (SRD 5.2 Multiclassing): "When you gain a new level in a
class, you get its features for that level" — in combat too."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from pydantic import ValidationError

from dnd5e_engine import CharacterBuildSpec, CombatInstance, build_party_member, get_live
from dnd5e_engine.activities.scale import build_scale_values
from dnd5e_engine.events import HealingApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _granted_feature_slugs, _pc_condition_immunities
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, pc, start

LOADER = BundledAssetLoader()
FIGHTER_1_WIZARD_4 = {
    "class_slug": "fighter",
    "classes": {"fighter": 1, "wizard": 4},
    "character_level": 5,
}


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def test_classes_must_sum_to_character_level() -> None:
    with pytest.raises(ValidationError, match="does not equal the sum of classes"):
        pc(class_slug="fighter", classes={"fighter": 1, "wizard": 4}, character_level=4)


def test_class_slug_must_be_one_of_the_classes() -> None:
    with pytest.raises(ValidationError, match="is not one of classes"):
        pc(class_slug="rogue", classes={"fighter": 1, "wizard": 4}, character_level=5)


def test_build_party_member_forwards_the_classes() -> None:
    member = build_party_member(
        CharacterBuildSpec(species_slug="human", classes={"fighter": 1, "wizard": 4}),
        CombatInstance(entity_id="char:hero", name="Hero", zone_id=cell_id(0, 0)),
        loader=LOADER,
    )
    assert (member.classes, member.class_slug, member.character_level) == (
        {"fighter": 1, "wizard": 4},
        "fighter",
        5,
    )


def test_a_fighter_1_wizard_4_has_no_extra_attack_or_action_surge() -> None:
    """Extra Attack (Fighter 5) and Action Surge (Fighter 2) are out of reach
    at Fighter 1; the Wizard's level-1 feature is in."""
    handle, live = start([pc(**FIGHTER_1_WIZARD_4)], seed=1)
    slugs = _granted_feature_slugs(combatant(live))
    assert {"second-wind", "arcane-recovery"} <= slugs
    assert slugs.isdisjoint({"extra-attack", "action-surge"})
    assert get_live(handle).turn.attacks_remaining == 1


def test_second_wind_heals_by_the_fighter_level_not_the_character_level() -> None:
    """Second Wind: "regain Hit Points equal to 1d10 plus your Fighter level".
    Seed 3: d10 = 4, so 4 + 1 = 5 (reading Fighter 5 would give 9)."""
    handle, live = start([pc(hp_current=10, hp_max=40, **FIGHTER_1_WIZARD_4)], seed=3)
    act(handle, "char:hero", intent_type="use_feature", feature_id="second-wind")
    assert [e.amount for e in events(live, HealingApplied)] == [5]


def test_raw_spec_without_classes_keeps_the_single_class_projection() -> None:
    """A host that sends only class_slug + character_level keeps today's
    reading: one class at the total level, so a Fighter 5 has Extra Attack."""
    handle, _ = start([pc(class_slug="fighter", character_level=5)], seed=1)
    assert get_live(handle).turn.attacks_remaining == 2


def test_scale_values_read_each_class_at_its_own_level() -> None:
    split = build_scale_values(
        class_slug="monk",
        subclass_slug=None,
        species_slug=None,
        level=5,
        loader=LOADER,
        classes={"monk": 1, "fighter": 4},
    )
    assert (
        split["monk.die"],
        split["monk.focus"],
        split["fighter.second-wind"],
        split["fighter.action-surge"],
    ) == ("d6", 1, 3, 1)
    single = build_scale_values(
        class_slug="monk", subclass_slug=None, species_slug=None, level=5, loader=LOADER
    )
    assert (single["monk.die"], single["monk.focus"]) == ("d8", 5)


def test_subclass_features_follow_their_own_class_level() -> None:
    """Nature's Ward is a Circle of the Land feature at Druid level 10: a
    Druid 3 / Fighter 7 doesn't have it, a Druid 10 does."""
    split = pc(
        class_slug="druid",
        subclass_slug="land",
        classes={"druid": 3, "fighter": 7},
        character_level=10,
    )
    whole = pc(class_slug="druid", subclass_slug="land", character_level=10)
    assert _pc_condition_immunities(split) == []
    assert _pc_condition_immunities(whole) == ["poisoned"]
