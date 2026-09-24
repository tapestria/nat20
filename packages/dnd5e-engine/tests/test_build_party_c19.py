"""build_party_member = derive_sheet + an explicit-wins merge (C19 R3/R9)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CombatInstance, build_party_member, make_build_spec, start_combat
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec

LOADER = BundledAssetLoader()


@pytest.fixture(autouse=True)
def _bundled_loader():
    set_lib_loader_for_tests(LOADER)
    yield
    set_lib_loader_for_tests(None)


def _member(build: dict[str, Any] | None = None, **instance: Any) -> PartyMemberSpec:
    spec = make_build_spec(
        **{"species_slug": "human", "class_slug": "fighter", "level": 1, **(build or {})}
    )
    fields: dict[str, Any] = {
        "entity_id": "char:hero",
        "name": "Hero",
        "zone_id": cell_id(0, 0),
        **instance,
    }
    return build_party_member(spec, CombatInstance(**fields), loader=LOADER)


def test_unset_instance_values_are_derived() -> None:
    member = _member({"ability_scores": {"constitution": 14}, "equipment": ("chain-mail",)})
    assert (member.hp_max, member.hp_current, member.ac, member.base_speed) == (12, 12, 16, 20)


def test_explicit_instance_values_always_win() -> None:
    member = _member(
        {"equipment": ("chain-mail",)},
        hp_max=30,
        hp_current=7,
        ac=10,
        attack_bonus=5,
        base_speed=35,
    )
    assert (
        member.hp_max,
        member.hp_current,
        member.ac,
        member.attack_bonus,
        member.base_speed,
    ) == (30, 7, 10, 5, 35)
    assert "attack_bonus" in member.model_fields_set


def test_unset_attack_bonus_stays_unset_so_the_engine_computes_it() -> None:
    assert "attack_bonus" not in _member().model_fields_set


def test_hp_current_defaults_to_the_resolved_maximum() -> None:
    assert _member(hp_max=20).hp_current == 20


def test_proficiencies_reach_the_party_spec() -> None:
    member = _member(
        {
            "class_slug": "rogue",
            "background_slug": "criminal",
            "selected_choices": ("skill:perception", "expertise:perception"),
        }
    )
    assert member.save_proficiencies == ("dex", "int")
    assert set(member.skill_proficiencies) == {"perception", "sleight_of_hand", "stealth"}
    assert member.skill_expertise == ("perception",)
    assert {"rapier", "simple_melee"} <= set(member.weapon_proficiencies)
    assert "weapon_proficiencies" in member.model_fields_set


def test_choice_tokens_change_the_scores_the_spec_carries() -> None:
    member = _member(
        {
            "level": 4,
            "ability_scores": {"strength": 16},
            "selected_choices": ("asi:fighter:4:strength+2",),
        }
    )
    assert member.strength == 18


def test_invalid_builds_raise_value_error() -> None:
    with pytest.raises(ValueError, match="needs fighter level 3"):
        _member({"level": 2, "subclass_slug": "champion"})


def test_multiclass_passive_projection_is_per_class() -> None:
    # Fast Movement is Barbarian level 5; a Barbarian 1 / Fighter 4 must not get it.
    member = _member({"class_slug": None, "classes": {"barbarian": 1, "fighter": 4}, "level": None})
    assert member.base_speed == 30


def test_live_combat_reads_the_derived_sheet() -> None:
    spec = make_build_spec(
        species_slug="human",
        class_slug="fighter",
        level=5,
        ability_scores={"strength": 16, "constitution": 14},
        equipment=("chain-mail", "shield"),
    )
    member = build_party_member(
        spec,
        CombatInstance(entity_id="char:hero", name="Hero", zone_id=cell_id(0, 0), initiative=20),
        loader=LOADER,
    )
    foe = EncounterMemberSpec(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=5,
        hp_max=5,
        ac=10,
        zone_id=cell_id(1, 0),
    )

    async def _go():
        start = await start_combat(
            session_id="c19-live",
            party=[member],
            encounter=[foe],
            scene_zones=None,
            grid_scene=GridScene(width=5, height=5),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = asyncio.run(_go())
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert (hero.hp_max, hero.ac) == (44, 18)
    assert sorted(hero.save_proficiencies) == ["con", "str"]
    assert hero.attack_bonus is None  # engine-computed per weapon (C15 sentinel)
    assert hero.weapon_proficiencies is not None
    assert "martial_melee" in hero.weapon_proficiencies
