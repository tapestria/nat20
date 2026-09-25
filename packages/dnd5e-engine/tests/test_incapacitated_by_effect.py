"""An Incapacitated condition an effect imposes ends what a directly applied one
ends. SRD 5.2 Incapacitated: "No Concentration. Your Concentration is broken."
Ending a Grapple: "The condition also ends if the grappler has the Incapacitated
condition". Rage: "it ends early if you don Heavy armor or have the
Incapacitated condition."

Each test paralyzes its subject with a real Hold Person from a Wizard 5 (spell
save DC 16); the subject's low Wisdom fails the save on the seed used.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import ConcentrationDropped, ConditionRemoved, EffectExpired
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _LiveCombat
from tests.c20_support import act, combatant, events, hold_person, pc, start, wizard


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _has(live: _LiveCombat, entity_id: str, condition: str) -> bool:
    return any(c.condition == condition for c in combatant(live, entity_id).conditions)


def test_hold_person_ends_the_rage_of_a_barbarian_below_15() -> None:
    barbarian = pc(
        class_slug="barbarian",
        character_level=3,
        strength=16,
        wisdom=6,
        creature_type="humanoid",
    )
    handle, live = start([barbarian, wizard()], seed=1)
    act(handle, "char:hero", intent_type="use_feature", feature_id="rage")
    act(handle, "char:hero", intent_type="pass")
    hold_person(handle, "char:hero")
    assert _has(live, "char:hero", "paralyzed")
    assert [e.reason for e in events(live, EffectExpired) if e.effect_id == "effect:rage"] == [
        "incapacitated"
    ]
    assert not any(e.id == "effect:rage" for e in live.active_effects["char:hero"])


def test_hold_person_breaks_the_concentration_of_the_caster_it_paralyzes() -> None:
    """The cleric's Bless ends on both of its targets."""
    cleric = pc(
        class_slug="cleric",
        character_level=3,
        wisdom=6,
        creature_type="humanoid",
        spell_slots={1: 3},
        spells_known=["bless"],
    )
    handle, live = start([cleric, wizard()], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="cast_spell",
        spell_id="bless",
        target_id="char:hero",
        target_ids=("char:hero", "char:wiz"),
        slot_level=1,
    )
    assert combatant(live).concentration_effect_id == "effect:blessed"
    hold_person(handle, "char:hero")
    assert _has(live, "char:hero", "paralyzed")
    assert [e.target_id for e in events(live, ConcentrationDropped)] == ["char:hero", "char:hero"]
    bless_ends = [
        (e.target_id, e.reason)
        for e in events(live, EffectExpired)
        if e.effect_id == "effect:blessed"
    ]
    assert sorted(bless_ends) == [
        ("char:hero", "concentration_drop"),
        ("char:wiz", "concentration_drop"),
    ]
    assert combatant(live).concentration_effect_id is None
    assert "char:hero" not in live.concentration_chain


def test_hold_person_on_a_grappler_releases_its_grapple() -> None:
    fighter = pc(
        class_slug="fighter",
        character_level=3,
        strength=20,
        wisdom=4,
        creature_type="humanoid",
    )
    handle, live = start([fighter, wizard()], seed=2)
    act(handle, "char:hero", intent_type="grapple", target_id="mon:foe")
    assert _has(live, "mon:foe", "grappled")
    hold_person(handle, "char:hero")
    assert _has(live, "char:hero", "paralyzed")
    assert [(e.target_id, e.condition) for e in events(live, ConditionRemoved)] == [
        ("mon:foe", "grappled")
    ]
    assert not _has(live, "mon:foe", "grappled")
