"""Alert, Savage Attacker and Grappler in combat.

SRD 5.2 Alert: "When you roll Initiative, you can add your Proficiency Bonus to
the roll." Savage Attacker: "Once per turn when you hit a target with a weapon,
you can roll the weapon's damage dice twice and use either roll against the
target." Grappler: "You have Advantage on attack rolls against a creature
Grappled by you."
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.spatial import cell_id
from tests.c20_support import act, combatant, events, foe, pc, start


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


_FIGHTER = {"class_slug": "fighter", "character_level": 5, "strength": 16}


def test_a_characters_feats_reach_its_combatant() -> None:
    _, live = start([pc(feats=("alert", "savage-attacker"))], seed=1)
    assert combatant(live).feats == ("alert", "savage-attacker")
    assert combatant(live, "mon:foe").feats == ()


def test_alert_adds_to_a_surprised_characters_disadvantaged_roll() -> None:
    # SRD 5.2 Surprise: "Disadvantage on its Initiative roll". Alert still adds
    # the Proficiency Bonus (+2 at level 1) to the roll it keeps.
    def rolled(feats: tuple[str, ...]) -> int:
        hero = pc(initiative=None, is_surprised=True, dexterity=12, feats=feats)
        _, live = start([hero], seed=1, encounter=[foe(initiative=None)])
        return combatant(live).initiative

    assert (rolled(()), rolled(("alert",))) == (6, 8)


def _greatsword_damage(seed: int, *, feats: tuple[str, ...], used: bool = False) -> int:
    """A Fighter 5 (STR 16) hits the AC 1 foe with a greatsword once; ``used``
    marks Savage Attacker as already used this turn."""
    handle, live = start([pc(feats=feats, **_FIGHTER)], seed=seed)
    if used:
        live.initiative[0] = combatant(live).model_copy(
            update={"savage_attacker_spent_this_turn": True}
        )
    act(handle, "char:hero", intent_type="attack", weapon_id="greatsword", target_id="mon:foe")
    return sum(e.amount for e in events(live, DamageApplied))


def test_savage_attacker_already_used_this_turn_rolls_once() -> None:
    for seed in range(1, 6):
        plain = _greatsword_damage(seed, feats=())
        assert _greatsword_damage(seed, feats=("savage-attacker",), used=True) == plain


def test_savage_attacker_works_again_on_an_opportunity_attack() -> None:
    # SRD 5.2 "Once per turn": the foe's turn is a new turn, so the hero's
    # opportunity attack with its greatsword uses the feat again.
    hero = pc(feats=("savage-attacker",), equipment=("greatsword",), **_FIGHTER)
    handle, live = start([hero], seed=1)
    act(handle, "char:hero", intent_type="attack", weapon_id="greatsword", target_id="mon:foe")
    assert combatant(live).savage_attacker_spent_this_turn is True
    act(handle, "char:hero", intent_type="pass")
    assert combatant(live).savage_attacker_spent_this_turn is False
    act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    [reaction] = [e for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert reaction.is_hit
    assert combatant(live).savage_attacker_spent_this_turn is True


def test_a_grappler_gets_nothing_against_a_creature_another_grapples() -> None:
    # "a creature Grappled by you": the ally's grapple (the foe fails its DC 14
    # save on a 5) gives the Grappler no Advantage.
    ally = pc("char:ally", initiative=25, strength=18, zone_id=cell_id(1, 1))
    hero = pc(feats=("grappler",), class_slug="fighter", character_level=5, strength=18)
    handle, live = start([ally, hero], seed=1)
    act(handle, "char:ally", intent_type="grapple", target_id="mon:foe")
    assert "grappled" in {ac.condition for ac in combatant(live, "mon:foe").conditions}
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    [swing] = [e for e in events(live, AttackRolled) if e.attacker_id == "char:hero"]
    assert (swing.advantage, swing.advantage_sources) == ("normal", [])
