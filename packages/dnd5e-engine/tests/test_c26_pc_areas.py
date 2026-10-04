"""Areas of effect for every intent kind, and the creatures an area spares.

SRD 5.2: "Each creature of your choice in a 5-foot-radius Sphere" (Sleep);
"If a spell targets a creature of your choice, you can choose yourself";
"You alter time around up to six creatures of your choice in a 40-foot Cube"
(Slow); a Cone, Cube or Line extends "in a direction its creator chooses".
"""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    AttackFailed,
    AttackRolled,
    CastFailed,
    HealingApplied,
    IntentSubmitted,
    SaveRolled,
)
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, foe, pc, start, wizard


def _goblin(entity_id: str, col: int, row: int, initiative: int = 1):
    return foe(
        entity_id=entity_id,
        name=entity_id.removeprefix("mon:"),
        monster_template_slug="goblin-warrior",
        initiative=initiative,
        hp_current=30,
        hp_max=30,
        zone_id=cell_id(col, row),
    )


def _saved(live) -> list[str]:
    return [e.target_id for e in events(live, SaveRolled)]


def _areas(live) -> list:
    return [e for e in live.event_log if e.type == "area_targeted"]


def _slow_caster(**fields):
    return wizard(
        zone_id=cell_id(0, 0),
        character_level=5,
        spell_slots={3: 1},
        spells_known=["slow"],
        **fields,
    )


def test_excluded_target_ids_defaults_to_none_and_refuses_blank_or_repeated_ids() -> None:
    assert PlayerIntent(intent_type="cast_spell", spell_id="sleep").excluded_target_ids is None
    assert PlayerIntent(intent_type="cast_spell", excluded_target_ids=()).excluded_target_ids == ()
    for bad in [("",), ("char:a", "char:a")]:
        with pytest.raises(ValidationError, match="excluded_target_ids"):
            PlayerIntent(intent_type="cast_spell", spell_id="sleep", excluded_target_ids=bad)


def test_excluding_a_creature_not_in_the_combat_spends_nothing() -> None:
    handle, live = start(
        [wizard(zone_id=cell_id(5, 6), spells_known=["sleep"], spell_slots={1: 1})],
        seed=1,
        encounter=[_goblin("mon:g1", 5, 5)],
    )
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="sleep",
        target_id="mon:g1",
        slot_level=1,
        excluded_target_ids=("char:nobody",),
    )
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert events(live, IntentSubmitted) == []
    assert live.spell_slots_by_entity["char:wiz"][1] == 1


def test_an_exclusion_on_a_weapon_attack_is_refused() -> None:
    handle, live = start([pc(equipment=("dagger",))], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="dagger",
        target_id="mon:foe",
        excluded_target_ids=(),
    )
    assert [(e.target_id, e.reason) for e in events(live, AttackFailed)] == [
        ("mon:foe", "target_invalid")
    ]
    assert combatant(live).action_available is True


def test_a_mace_of_terror_swing_attacks_only_its_target() -> None:
    """SRD 5.2 §Making an Attack — an attack roll always targets one
    creature, so an ``attack`` intent never area-expands, even when the
    weapon's other activities carry a template of their own. Mace of
    Terror's Wave of Terror rides the same weapon as a separate,
    itemUses-gated use; a plain swing must not turn it loose on every enemy
    within 30 feet."""
    handle, live = start(
        [pc(equipment=("mace-of-terror",))],
        seed=1,
        encounter=[_goblin("mon:g1", 1, 0), _goblin("mon:g2", 5, 0), _goblin("mon:g3", 0, 5)],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="mace-of-terror",
        target_id="mon:g1",
    )
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:g1"]
    # Not pinned to ``["mon:g1"]``: whether the swing also forces a Wave of
    # Terror save from its own target is a separate, known quirk (the save
    # activity still resolves against the attack's single-target list). What
    # this test pins is that it never reaches mon:g2 or mon:g3.
    assert set(_saved(live)) <= {"mon:g1"}
    assert _areas(live) == []


def test_javelin_of_lightning_use_item_without_an_activity_id_attacks_only_its_target() -> None:
    """Javelin of Lightning's thrown attack and its Lightning Bolt are
    alternative activities on the same item (Foundry activities are
    alternatives, never a batch): a ``use_item`` call that names neither
    resolves both, and an attack roll among them means the whole call stays
    single-target rather than spreading the Lightning Bolt's 120-foot line
    over whoever else is in it."""
    handle, live = start(
        [pc(equipment=("javelin-of-lightning",))],
        seed=1,
        encounter=[_goblin("mon:g1", 1, 0), _goblin("mon:g2", 5, 0), _goblin("mon:g3", 9, 0)],
    )
    act(
        handle,
        "char:hero",
        intent_type="use_item",
        item_id="javelin-of-lightning",
        target_id="mon:g1",
    )
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:g1"]
    assert set(_saved(live)) <= {"mon:g1"}
    assert _areas(live) == []


def test_horn_of_blasting_without_an_activity_id_resolves_no_area() -> None:
    """Horn of Blasting's blast, its object-damage rider, its
    explosion-chance roll and its misfire damage are four alternative
    activities, not a batch: a ``use_item`` call that names none of them is
    itself ambiguous and must not treat any one of them — the blast
    included — as if it alone fired over an area."""
    handle, live = start(
        [pc(equipment=("horn-of-blasting",))],
        seed=1,
        encounter=[_goblin("mon:g1", 1, 0), _goblin("mon:g2", 2, 0)],
    )
    act(
        handle,
        "char:hero",
        intent_type="use_item",
        item_id="horn-of-blasting",
        target_id="mon:g1",
    )
    assert "mon:g2" not in set(_saved(live))
    assert _areas(live) == []


def test_horn_of_blasting_with_the_blast_chosen_resolves_its_cone() -> None:
    """The same call, with the blast's own activity picked explicitly, is no
    longer ambiguous and still gets its area."""
    handle, live = start(
        [pc(equipment=("horn-of-blasting",))],
        seed=1,
        encounter=[_goblin("mon:g1", 1, 0), _goblin("mon:g2", 2, 0)],
    )
    act(
        handle,
        "char:hero",
        intent_type="use_item",
        item_id="horn-of-blasting",
        activity_id="FMTcQOb5MZKBohdN",
        direction=(1, 0),
    )
    [area] = _areas(live)
    assert (area.shape, area.size_ft, area.direction) == ("cone", 30, (1, 0))
    assert set(area.affected_ids) == {"mon:g1", "mon:g2"}


def test_the_pipes_spare_the_bards_allies_unless_it_opts_everyone_in() -> None:
    def play(**intent):
        handle, live = start(
            [
                pc("char:bard", zone_id=cell_id(5, 5)),
                pc("char:ally", zone_id=cell_id(6, 6), initiative=10),
            ],
            seed=1,
            encounter=[_goblin("mon:g1", 5, 8)],
        )
        act(
            handle,
            "char:bard",
            intent_type="use_item",
            item_id="pipes-of-haunting",
            target_id="mon:g1",
            **intent,
        )
        return live

    assert _saved(play()) == ["mon:g1"]
    assert sorted(_saved(play(excluded_target_ids=()))) == ["char:ally", "mon:g1"]


def test_slow_names_up_to_six_creatures_wherever_they_stand() -> None:
    goblins = [_goblin(f"mon:g{i}", i, 0) for i in range(1, 3)] + [_goblin("mon:far", 9, 9)]
    handle, live = start([_slow_caster()], seed=1, encounter=goblins)
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="slow",
        slot_level=3,
        target_ids=("mon:g2", "mon:far"),
    )
    assert _saved(live) == ["mon:g2", "mon:far"]
    assert _areas(live) == []


@pytest.mark.parametrize(
    "named",
    [
        tuple(f"mon:g{i}" for i in range(1, 8)),
        ("mon:g1", "mon:g1"),
        ("mon:g1", "mon:ghost"),
    ],
)
def test_slow_refuses_more_than_six_a_repeat_or_a_stranger(named: tuple[str, ...]) -> None:
    goblins = [_goblin(f"mon:g{i}", i, 0) for i in range(1, 8)]
    handle, live = start([_slow_caster()], seed=1, encounter=goblins)
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="slow",
        slot_level=3,
        direction=(1, 0),
        target_ids=named,
    )
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert live.spell_slots_by_entity["char:wiz"][3] == 1
    assert _saved(live) == []


def test_an_unaimed_breath_weapon_is_refused_before_its_use_is_spent() -> None:
    handle, live = start(
        [pc("char:drake", species_slug="dragonborn", character_level=5, constitution=14)],
        seed=1,
    )
    act(
        handle,
        "char:drake",
        intent_type="use_feature",
        feature_id="breath-weapon",
        activity_id="dxCRYmNSSGp6L2yh",
    )
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert live.custom_counters_by_entity.get("char:drake", {}) == {}
    assert combatant(live, "char:drake").action_available is True


def test_a_wall_template_affects_only_its_named_target(caplog: pytest.LogCaptureFixture) -> None:
    """Wall of Fire's ``wall`` template is one the engine can't place, so the
    cast falls back to its named target — never its neighbour."""
    caster = wizard(spells_known=["wall-of-fire"], spell_slots={4: 1}, character_level=7)
    handle, live = start(
        [caster], seed=1, encounter=[_goblin("mon:a", 4, 0), _goblin("mon:b", 4, 1)]
    )
    with caplog.at_level(logging.WARNING, logger="dnd5e_engine.orchestrator"):
        act(
            handle,
            "char:wiz",
            intent_type="cast_spell",
            spell_id="wall-of-fire",
            target_id="mon:a",
            slot_level=4,
        )
    # Both of its save activities resolve on the named target.
    assert set(_saved(live)) == {"mon:a"}
    assert _areas(live) == []
    assert "falling back to the named target" in caplog.text


def test_mass_cure_wounds_heals_the_casters_side_by_default() -> None:
    """SRD 5.2 Mass Cure Wounds: "Choose up to six creatures in a 30-foot-
    radius Sphere." Healing an area is help, not harm, so the default by
    harm is the caster's own side — never the goblin standing in range."""
    caster = wizard(
        "char:wiz",
        class_slug="cleric",
        wisdom=18,
        spells_known=["mass-cure-wounds"],
        spell_slots={5: 1},
        zone_id=cell_id(5, 5),
        hp_current=10,
    )
    ally = pc("char:ally", zone_id=cell_id(6, 6), initiative=10, hp_current=5)
    handle, live = start([caster, ally], seed=1, encounter=[_goblin("mon:g1", 5, 7)])
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="mass-cure-wounds",
        target_id="char:ally",
        slot_level=5,
    )
    [area] = _areas(live)
    assert area.affected_ids == ["char:wiz", "char:ally"]
    assert area.excluded_ids == ["mon:g1"]
    assert {e.target_id for e in events(live, HealingApplied)} == {"char:wiz", "char:ally"}
    order = [e.type for e in live.event_log if e.type in ("area_targeted", "healing_applied")]
    assert order.index("area_targeted") < order.index("healing_applied")


def test_a_refused_item_area_keeps_its_charge() -> None:
    """An exclusion naming a creature not in the combat is refused by
    ``_area_target_failure`` before anything is spent — the Pipes' charge
    included."""
    handle, live = start(
        [pc("char:bard", equipment=("pipes-of-haunting",), zone_id=cell_id(5, 5))],
        seed=1,
        encounter=[_goblin("mon:g1", 5, 7)],
    )
    act(
        handle,
        "char:bard",
        intent_type="use_item",
        item_id="pipes-of-haunting",
        target_id="mon:g1",
        excluded_target_ids=("char:nobody",),
    )
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert live.custom_counters_by_entity.get("char:bard", {}) == {}
    assert events(live, IntentSubmitted) == []
    assert combatant(live, "char:bard").action_available is True
