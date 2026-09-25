"""Rage's lifetime. SRD 5.2 Rage: "The Rage lasts until the end of your next
turn, and it ends early if you don Heavy armor or have the Incapacitated
condition. If your Rage is still active on your next turn, you can extend the
Rage for another round by doing one of the following: Make an attack roll
against an enemy. Force an enemy to make a saving throw. Take a Bonus Action to
extend your Rage. Each time the Rage is extended, it lasts until the end of
your next turn."

No assertion here reads a die, so seed 1 serves every test.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import (
    AttackRolled,
    ConditionApplied,
    EffectApplied,
    EffectExpired,
    SaveRolled,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _emit
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import PartyMemberSpec
from dnd5e_engine.types.effects import ActiveEffect
from tests.c20_support import act, combatant, events, monster_turn, pc, start

RAGE = "effect:rage"
ALLY = "char:ally"


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _barbarian(**fields: Any) -> PartyMemberSpec:
    """A Barbarian 1: one attack per Attack action, two Rages."""
    return pc(class_slug="barbarian", strength=16, **fields)


def _raging(live) -> bool:
    return any(e.id == RAGE for e in live.active_effects.get("char:hero", []))


def _rage_ends(live) -> list[str]:
    return [e.reason for e in events(live, EffectExpired) if e.effect_id == RAGE]


def _rage_uses(live) -> dict[str, int] | None:
    return live.custom_counters_by_entity.get("char:hero", {}).get("feature_use:rage")


def _rage_then_next_turn(handle, *, with_ally: bool = False) -> None:
    """Turn 1: enter Rage (a Bonus Action) and pass. Everyone else then takes a
    turn (the adjacent foe swings its 1d4 at someone), so the barbarian is on
    its next turn."""
    act(handle, "char:hero", intent_type="use_feature", feature_id="rage")
    act(handle, "char:hero", intent_type="pass")
    if with_ally:
        act(handle, ALLY, intent_type="pass")
    monster_turn(handle)


def _swing(handle, target_id: str = "mon:foe") -> None:
    """A Mace (Sap; neither Light nor Cleave): a Barbarian 1's only attack ends
    its turn."""
    act(handle, "char:hero", intent_type="attack", weapon_id="mace", target_id=target_id)


def test_a_rage_entered_this_turn_lasts_through_its_end() -> None:
    handle, live = start([_barbarian()], seed=1)
    act(handle, "char:hero", intent_type="use_feature", feature_id="rage")
    act(handle, "char:hero", intent_type="pass")
    assert (_rage_ends(live), _raging(live)) == ([], True)


def test_an_unextended_rage_ends_at_the_end_of_the_next_turn() -> None:
    handle, live = start([_barbarian()], seed=1)
    _rage_then_next_turn(handle)
    assert _raging(live)
    act(handle, "char:hero", intent_type="pass")
    ended = [e for e in events(live, EffectExpired) if e.effect_id == RAGE]
    assert [(e.target_id, e.origin, e.reason) for e in ended] == [
        ("char:hero", "cast:rage:char:hero", "not_extended")
    ]
    assert not _raging(live)


@pytest.mark.parametrize(("target_id", "extended"), [("mon:foe", True), (ALLY, False)])
def test_only_an_attack_roll_against_an_enemy_extends_the_rage(
    target_id: str, extended: bool
) -> None:
    """ "Make an attack roll against an enemy" — hit or miss; an ally is no enemy."""
    ally = pc(ALLY, initiative=15, zone_id=cell_id(0, 1))
    handle, live = start([_barbarian(), ally], seed=1)
    _rage_then_next_turn(handle, with_ally=True)
    _swing(handle, target_id)
    assert _raging(live) is extended
    assert _rage_ends(live) == ([] if extended else ["not_extended"])


def test_each_extension_lasts_until_the_end_of_the_next_turn() -> None:
    handle, live = start([_barbarian()], seed=1)
    _rage_then_next_turn(handle)
    _swing(handle)
    monster_turn(handle)
    assert _raging(live)
    act(handle, "char:hero", intent_type="pass")
    assert (_rage_ends(live), _raging(live)) == (["not_extended"], False)


def test_forcing_an_enemy_to_save_extends_the_rage() -> None:
    """ "Force an enemy to make a saving throw": a Shove makes the foe save and
    ends the turn without any attack roll by the barbarian."""
    handle, live = start([_barbarian()], seed=1)
    _rage_then_next_turn(handle)
    act(handle, "char:hero", intent_type="shove", target_id="mon:foe")
    assert any(e.target_id == "mon:foe" for e in events(live, SaveRolled))
    assert not any(e.attacker_id == "char:hero" for e in events(live, AttackRolled))
    assert (_rage_ends(live), _raging(live)) == ([], True)


def test_a_bonus_action_extends_the_rage_without_spending_a_use() -> None:
    """ "Take a Bonus Action to extend your Rage": ``use_feature rage`` while
    raging spends the Bonus Action, no Rage use, and applies nothing new."""
    handle, live = start([_barbarian()], seed=1)
    _rage_then_next_turn(handle)
    act(handle, "char:hero", intent_type="use_feature", feature_id="rage")
    hero = combatant(live)
    assert (hero.bonus_action_available, hero.action_available) == (False, True)
    act(handle, "char:hero", intent_type="pass")
    assert (_rage_ends(live), _raging(live)) == ([], True)
    assert _rage_uses(live) == {"spent": 1}
    assert len([e for e in events(live, EffectApplied) if e.effect.id == RAGE]) == 1


@pytest.mark.parametrize(
    ("condition", "ends"),
    [("incapacitated", True), ("stunned", True), ("unconscious", True), ("prone", False)],
)
def test_the_incapacitated_condition_ends_the_rage_at_once(condition: str, ends: bool) -> None:
    """ "...it ends early if you ... have the Incapacitated condition." Stunned
    and Unconscious include it; Prone doesn't."""
    handle, live = start([_barbarian()], seed=1)
    act(handle, "char:hero", intent_type="use_feature", feature_id="rage")
    _emit(live, ConditionApplied(target_id="char:hero", condition=condition))
    assert _rage_ends(live) == (["incapacitated"] if ends else [])
    assert _raging(live) is not ends


@pytest.mark.parametrize(
    ("intent", "extended"),
    [
        ({"intent_type": "pass"}, False),
        ({"intent_type": "attack", "weapon_id": "mace", "target_id": "mon:foe"}, True),
    ],
    ids=["pass", "attack"],
)
def test_a_rage_carried_into_combat_must_be_extended_on_its_first_turn(
    intent: dict[str, str], extended: bool
) -> None:
    """A Rage a host seeds through ``start_combat(active_effects=...)`` wasn't
    entered this turn, so the barbarian's first turn has to extend it."""
    rage = ActiveEffect(id=RAGE, name="Rage", origin="cast:rage:char:hero", target_id="char:hero")
    handle, live = start([_barbarian()], seed=1, active_effects=[rage])
    act(handle, "char:hero", **intent)
    assert _raging(live) is extended
