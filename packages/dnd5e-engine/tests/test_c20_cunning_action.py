"""Cunning Action (SRD 5.2 Rogue 2): "On your turn, you can take one of the
following actions as a Bonus Action: Dash, Disengage, or Hide." The gate is the
feature at the Rogue's own level, not ``class_slug == "rogue"``. Hide charges no
budget at all (C14), so only Dash and Disengage are gated.

No die is drawn here; Speed is 30, so a Dash leaves 30 + 30 = 60 ft.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.events import DashTaken, IntentSubmitted
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import IntentRejectedError
from tests.c20_support import act, combatant, events, pc, start

ROGUE_2: dict[str, Any] = {"class_slug": "rogue", "character_level": 2}
FIGHTER_1_ROGUE_2: dict[str, Any] = {
    "class_slug": "fighter",
    "classes": {"fighter": 1, "rogue": 2},
    "character_level": 3,
}
ROGUE_1: dict[str, Any] = {"class_slug": "rogue", "character_level": 1}
ROGUE_1_FIGHTER_1: dict[str, Any] = {
    "class_slug": "rogue",
    "classes": {"rogue": 1, "fighter": 1},
    "character_level": 2,
}
FIGHTER_5: dict[str, Any] = {"class_slug": "fighter", "character_level": 5}


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _budgets(live) -> tuple[bool, bool, int, bool]:
    hero = combatant(live)
    return (
        hero.bonus_action_available,
        hero.action_available,
        hero.movement_remaining,
        hero.disengaging_this_turn,
    )


@pytest.mark.parametrize(
    "build", [ROGUE_2, FIGHTER_1_ROGUE_2], ids=["rogue-2", "fighter-1-rogue-2"]
)
def test_cunning_action_dashes_with_the_bonus_action(build: dict[str, Any]) -> None:
    """A Rogue 2 — or any build with two Rogue levels, whatever its
    ``class_slug`` — Dashes with the Bonus Action and keeps its Action."""
    handle, live = start([pc(**build)], seed=1)
    act(handle, "char:hero", intent_type="dash", use_bonus_action=True)
    [dash] = events(live, DashTaken)
    assert (dash.budget_consumed, dash.doubled_movement_remaining) == ("bonus_action", 60)
    assert _budgets(live) == (False, True, 60, False)


@pytest.mark.parametrize("intent_type", ["dash", "disengage"])
@pytest.mark.parametrize(
    "build",
    [ROGUE_1, ROGUE_1_FIGHTER_1, FIGHTER_5],
    ids=["rogue-1", "rogue-1-fighter-1", "fighter-5"],
)
def test_without_cunning_action_the_bonus_action_path_is_refused(
    build: dict[str, Any], intent_type: str
) -> None:
    """Cunning Action arrives at Rogue level 2: a Rogue 1 is refused even at
    character level 2, and a Fighter never has it. Nothing is spent."""
    handle, live = start([pc(**build)], seed=1)
    with pytest.raises(IntentRejectedError, match=r"no_action_economy: .*Cunning Action"):
        act(handle, "char:hero", intent_type=intent_type, use_bonus_action=True)
    assert _budgets(live) == (True, True, 30, False)


def test_cunning_action_disengages_with_the_bonus_action() -> None:
    """Disengage as the Bonus Action: the Action stays, and movement provokes
    no Opportunity Attacks for the rest of the turn."""
    handle, live = start([pc(**ROGUE_2)], seed=1)
    act(handle, "char:hero", intent_type="disengage", use_bonus_action=True)
    assert _budgets(live) == (False, True, 30, True)
    assert [e.intent_type for e in events(live, IntentSubmitted)] == ["disengage"]


def test_disengage_without_the_flag_still_spends_the_action() -> None:
    handle, live = start([pc(**ROGUE_2)], seed=1)
    act(handle, "char:hero", intent_type="disengage")
    assert _budgets(live) == (True, False, 30, True)


def test_only_one_bonus_action_per_turn() -> None:
    """ "You can take only one Bonus Action on your turn": a Cunning Action Dash
    leaves none for a Cunning Action Disengage."""
    handle, live = start([pc(**ROGUE_2)], seed=1)
    act(handle, "char:hero", intent_type="dash", use_bonus_action=True)
    with pytest.raises(IntentRejectedError, match="no Bonus Action remaining"):
        act(handle, "char:hero", intent_type="disengage", use_bonus_action=True)
    assert _budgets(live) == (False, True, 60, False)
