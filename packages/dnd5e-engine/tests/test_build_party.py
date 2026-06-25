import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import CombatInstance, make_build_spec
from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology
from dnd5e_engine.types.combat import Combatant

_LOADER = BundledAssetLoader()  # real lib data; barbarian/dwarf/berserker exist
_INST = CombatInstance(
    entity_id="char:1",
    name="Korg",
    hp_current=45,
    hp_max=45,
    ac=15,
    attack_bonus=7,
    initiative=12,
    zone_id="zone:a",
)


def test_make_build_spec_normalizes_short_keys():
    bs = make_build_spec(
        species_slug="dwarf", class_slug="barbarian", level=5, ability_scores={"str": 16, "con": 14}
    )
    assert bs.ability_scores.strength == 16
    assert bs.ability_scores.constitution == 14
    assert bs.ability_scores.dexterity == 10  # unspecified default 10
    assert bs.level == 5
    assert bs.subclass_slug is None
    assert bs.equipment == ()
    assert bs.selected_choices == ()


def test_make_build_spec_normalizes_long_keys():
    # the backend cache stores long-form keys — the boundary must accept them
    bs = make_build_spec(
        species_slug="elf", class_slug="rogue", ability_scores={"dexterity": 17, "intelligence": 13}
    )
    assert bs.ability_scores.dexterity == 17
    assert bs.ability_scores.intelligence == 13


def test_make_build_spec_rejects_unknown_ability_key():
    with pytest.raises((ValueError, KeyError)):
        make_build_spec(species_slug="dwarf", class_slug="barbarian", ability_scores={"luck": 20})


def test_combat_instance_carries_identity():
    ci = CombatInstance(
        entity_id="char:1",
        name="Korg",
        hp_current=45,
        hp_max=45,
        ac=15,
        attack_bonus=7,
        initiative=12,
        zone_id="zone:a",
    )
    assert ci.entity_id == "char:1"
    assert ci.name == "Korg"
    assert ci.hp_max == 45


def test_specs_carry_all_six_abilities_and_subclass():
    p = PartyMemberSpec(
        entity_id="char:1",
        name="Korg",
        initiative=10,
        hp_current=45,
        hp_max=45,
        ac=15,
        attack_bonus=7,
        zone_id="z",
        strength=16,
        dexterity=14,
        constitution=14,
        class_slug="barbarian",
        subclass_slug="berserker",
        character_level=5,
    )
    assert p.strength == 16
    assert p.constitution == 14
    assert p.subclass_slug == "berserker"
    c = Combatant(
        entity_id="char:1",
        entity_type="Character",
        name="Korg",
        initiative=10,
        hp_current=45,
        strength=16,
        constitution=14,
        subclass_slug="berserker",
    )
    assert c.strength == 16
    assert c.constitution == 14
    assert c.subclass_slug == "berserker"


def test_start_combat_copies_abilities_and_subclass_to_combatant():
    async def _run():
        party = [
            PartyMemberSpec(
                entity_id="char:korg",
                name="Korg",
                initiative=15,
                hp_current=45,
                hp_max=45,
                ac=15,
                attack_bonus=7,
                zone_id="zone:start",
                strength=16,
                dexterity=14,
                constitution=14,
                intelligence=8,
                wisdom=12,
                charisma=10,
                class_slug="barbarian",
                subclass_slug="berserker",
                character_level=5,
            )
        ]
        encounter = [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=10,
                hp_current=11,
                hp_max=11,
                zone_id="zone:start",
            )
        ]
        return await start_combat(
            session_id="sess-copy",
            party=party,
            encounter=encounter,
            scene_zones=SceneTopology(zones=["zone:start"], edges=[]),
            rng_seed=1,
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    korg = next(c for c in live.initiative if c.entity_id == "char:korg")
    assert korg.strength == 16
    assert korg.constitution == 14
    assert korg.intelligence == 8
    assert korg.wisdom == 12
    assert korg.charisma == 10
    assert korg.subclass_slug == "berserker"


def test_combatant_and_spec_carry_senses():
    from dnd5e_engine.activities.passive_stats import CombatantSenses

    spec = PartyMemberSpec(
        entity_id="char:1",
        name="Korg",
        initiative=10,
        hp_current=45,
        hp_max=45,
        ac=15,
        zone_id="zone:a",
        senses=CombatantSenses(darkvision=120),
    )
    assert spec.senses.darkvision == 120
    c = Combatant(
        entity_id="char:1",
        entity_type="Character",
        name="Korg",
        initiative=10,
        hp_current=45,
        senses=CombatantSenses(darkvision=120),
    )
    assert c.senses.darkvision == 120
    # default is an empty CombatantSenses, not None
    bare = Combatant(
        entity_id="char:2", entity_type="Character", name="Bob", initiative=5, hp_current=10
    )
    assert bare.senses.darkvision is None


def test_start_combat_copies_senses_and_resistances_to_combatant():
    from dnd5e_engine.activities.passive_stats import CombatantSenses

    async def _run():
        party = [
            PartyMemberSpec(
                entity_id="char:dwarf",
                name="Thrain",
                initiative=15,
                hp_current=30,
                hp_max=30,
                ac=16,
                attack_bonus=5,
                zone_id="zone:start",
                damage_resistances=["poison"],
                senses=CombatantSenses(darkvision=120),
            )
        ]
        encounter = [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=10,
                hp_current=11,
                hp_max=11,
                zone_id="zone:start",
            )
        ]
        return await start_combat(
            session_id="sess-senses",
            party=party,
            encounter=encounter,
            scene_zones=SceneTopology(zones=["zone:start"], edges=[]),
            rng_seed=1,
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    thrain = next(c for c in live.initiative if c.entity_id == "char:dwarf")
    assert thrain.senses.darkvision == 120
    assert "poison" in thrain.damage_resistances


def test_build_party_member_produces_complete_spec():
    bs = make_build_spec(
        species_slug="dwarf",
        class_slug="barbarian",
        level=5,
        ability_scores={"strength": 16, "constitution": 14, "dexterity": 12},
    )
    spec = build_party_member(bs, _INST, loader=_LOADER)
    assert spec.entity_id == "char:1"  # identity from instance
    assert spec.name == "Korg"
    assert spec.class_slug == "barbarian"
    assert spec.character_level == 5
    assert spec.strength == 16
    assert spec.constitution == 14
    assert spec.dexterity == 12
    assert spec.base_speed == _LOADER.get_species("dwarf").movement.walk  # real value
    assert spec.hp_max == 45
    assert spec.ac == 15
    assert spec.attack_bonus == 7
    assert spec.subclass_slug is None


def test_build_party_member_carries_equipment_through_seam():
    bs = make_build_spec(
        species_slug="dwarf",
        class_slug="barbarian",
        equipment=("longsword", "shield"),
    )
    spec = build_party_member(bs, _INST, loader=_LOADER)
    assert spec.equipment == ("longsword", "shield")


def test_build_party_member_validates_subclass_ownership():
    # berserker belongs to barbarian — ok
    ok = build_party_member(
        make_build_spec(
            species_slug="dwarf", class_slug="barbarian", subclass_slug="berserker", level=5
        ),
        _INST,
        loader=_LOADER,
    )
    assert ok.subclass_slug == "berserker"
    # a subclass that doesn't belong to the class -> ValueError
    with pytest.raises(ValueError):
        build_party_member(
            make_build_spec(species_slug="dwarf", class_slug="wizard", subclass_slug="berserker"),
            _INST,
            loader=_LOADER,
        )


def test_build_party_member_rejects_unknown_class_or_species():
    with pytest.raises(ValueError):
        build_party_member(
            make_build_spec(species_slug="dwarf", class_slug="nope"), _INST, loader=_LOADER
        )
    with pytest.raises(ValueError):
        build_party_member(
            make_build_spec(species_slug="nope", class_slug="barbarian"), _INST, loader=_LOADER
        )
