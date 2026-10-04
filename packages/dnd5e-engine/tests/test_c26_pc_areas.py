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
from dnd5e_engine.events import AttackFailed, CastFailed, IntentSubmitted, SaveRolled
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
    """ORCHESTRATOR RULING (2026-10-04): SRD 5.2 §Making an Attack — an attack
    roll always targets one creature, so an ``attack`` intent never
    area-expands, even when the weapon's other activities carry a template of
    their own. Mace of Terror's Wave of Terror rides the same weapon as a
    separate, itemUses-gated use; a plain swing must not turn it loose on
    every enemy within 30 feet."""
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
    assert _saved(live) == ["mon:g1"]
    assert _areas(live) == []


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
    caster = wizard(spells_known=["confusion"], spell_slots={4: 1}, character_level=7)
    handle, live = start(
        [caster], seed=1, encounter=[_goblin("mon:a", 4, 0), _goblin("mon:b", 4, 1)]
    )
    with caplog.at_level(logging.WARNING, logger="dnd5e_engine.orchestrator"):
        act(
            handle,
            "char:wiz",
            intent_type="cast_spell",
            spell_id="confusion",
            target_id="mon:a",
            slot_level=4,
        )
    assert _saved(live) == ["mon:a"]
    assert _areas(live) == []
    assert "falling back to the named target" in caplog.text
