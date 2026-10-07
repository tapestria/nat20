"""Magic Initiate's spells in combat: the chosen ability, the slotless cast.

SRD 5.2 Magic Initiate: "Intelligence, Wisdom, or Charisma is your
spellcasting ability for this feat's spells ... You always have that spell
prepared. You can cast it once without a spell slot, and you regain the
ability to cast it in that way when you finish a Long Rest. You can also cast
the spell using any spell slots you have."
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import AttackRolled, CastFailed, ReactionTriggered, SaveRolled, SpellCast
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.rest import recover_slotless_casts
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, events, foe, monster_turn, pc, start


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


_BOLT = {"spell_abilities": {"guiding-bolt": "wis"}, "slotless_casts": ("guiding-bolt",)}


def _cast(handle, spell: str, **intent: Any) -> None:
    act(
        handle, "char:hero", intent_type="cast_spell", spell_id=spell, target_id="mon:foe", **intent
    )


def _start(**hero: Any):
    return start([pc(**hero)], seed=1, encounter=[foe(ac=10, zone_id=cell_id(3, 0))])


def test_a_cantrip_is_cast_with_the_chosen_ability() -> None:
    # Sacred Flame's DC for a Fighter 1 (WIS 16): 8 + Proficiency Bonus 2 +
    # Wisdom 3. Without an ability of its own a Fighter casts at the flat 10.
    fighter = {"class_slug": "fighter", "wisdom": 16}
    handle, live = _start(spell_abilities={"sacred-flame": "wis"}, **fighter)
    _cast(handle, "sacred-flame")
    assert [e.dc for e in events(live, SaveRolled)] == [13]
    handle, live = _start(**fighter)
    _cast(handle, "sacred-flame")
    assert [e.dc for e in events(live, SaveRolled)] == [10]


def test_the_chosen_ability_replaces_the_classs_for_that_spell() -> None:
    # A Cleric (Wisdom) casts a Magic Initiate (Wizard) Fire Bolt with
    # Intelligence: +4 + Proficiency Bonus 2, where Wisdom 10 gives +2.
    cleric = {"class_slug": "cleric", "wisdom": 10, "intelligence": 18}
    handle, live = _start(spell_abilities={"fire-bolt": "int"}, **cleric)
    _cast(handle, "fire-bolt")
    assert [e.modifier for e in events(live, AttackRolled)] == [6]
    handle, live = _start(**cleric)
    _cast(handle, "fire-bolt")
    assert [e.modifier for e in events(live, AttackRolled)] == [2]


def test_the_slotless_cast_goes_first_then_a_slot() -> None:
    handle, live = _start(class_slug="cleric", spell_slots={1: 2}, **_BOLT)
    _cast(handle, "guiding-bolt")
    assert live.spell_slots_by_entity["char:hero"] == {1: 2}
    counters = live.custom_counters_by_entity["char:hero"]
    assert counters["slotless_cast:guiding-bolt"] == {"spent": 1}
    monster_turn(handle)
    _cast(handle, "guiding-bolt")
    assert live.spell_slots_by_entity["char:hero"] == {1: 1}
    assert counters["slotless_cast:guiding-bolt"] == {"spent": 1}
    assert [e.slot_level for e in events(live, SpellCast)] == [1, 1]


def test_an_upcast_spends_a_slot_and_keeps_the_slotless_cast() -> None:
    handle, live = _start(class_slug="cleric", character_level=3, spell_slots={1: 2, 2: 2}, **_BOLT)
    _cast(handle, "guiding-bolt", slot_level=2)
    assert live.spell_slots_by_entity["char:hero"] == {1: 2, 2: 1}
    assert "slotless_cast:guiding-bolt" not in live.custom_counters_by_entity.get("char:hero", {})


def test_a_tally_the_host_carries_in_is_honoured() -> None:
    # The slotless cast was spent in an earlier combat and no Long Rest followed.
    spent = {"custom_counters": {"slotless_cast:guiding-bolt": {"spent": 1}}}
    handle, live = _start(class_slug="fighter", **_BOLT, **spent)
    _cast(handle, "guiding-bolt")
    assert [e.reason for e in events(live, CastFailed)] == ["no_slot"]
    assert events(live, SpellCast) == []


def test_a_readied_shield_fires_through_its_slotless_cast() -> None:
    # A Fighter with Magic Initiate (Wizard)'s Shield and no spell slots.
    hero = {
        "class_slug": "fighter",
        "spell_abilities": {"shield": "int"},
        "slotless_casts": ("shield",),
    }
    handle, live = start([pc(**hero)], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="ready",
        spell_id="shield",
        reaction_trigger="hit_by_attack",
    )
    monster_turn(handle)
    assert [e.reaction_name for e in events(live, ReactionTriggered)] == ["shield"]
    assert [e.spell_id for e in events(live, SpellCast)] == ["shield"]
    assert live.custom_counters_by_entity["char:hero"]["slotless_cast:shield"] == {"spent": 1}


def test_a_long_rest_restores_a_slotless_cast_and_a_short_rest_does_not() -> None:
    counters = {
        "slotless_cast:guiding-bolt": {"spent": 1},
        "feature_use:second-wind": {"spent": 1},
    }
    assert recover_slotless_casts(counters, "lr") == {"guiding-bolt": 0}
    assert recover_slotless_casts(counters, "sr") == {"guiding-bolt": 1}
    assert counters["slotless_cast:guiding-bolt"] == {"spent": 1}  # pure
