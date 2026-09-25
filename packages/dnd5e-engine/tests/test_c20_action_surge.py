"""Action Surge (SRD 5.2 Fighter 2): one additional action, never the Magic action."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import get_live
from dnd5e_engine.events import AttackFailed, AttackRolled, CastFailed, DamageApplied
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import IntentRejectedError
from tests.c20_support import act, combatant, events, monster_turn, pc, start


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _fighter(level: int = 2):
    """A Fighter with STR 16 and a pinned +5 to hit against the AC 1 foe. Seed 6
    draws d20 19, d8 2, d20 16, d8 5, d20 2, d8 1, d20 5, d8 8: every Longsword
    swing hits for its d8 + 3."""
    return start(
        [pc(class_slug="fighter", character_level=level, strength=16, attack_bonus=5)], seed=6
    )


def _surge(handle) -> None:
    act(handle, "char:hero", intent_type="use_feature", feature_id="action-surge")


def _swing(handle) -> None:
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")


def _surges_spent(live) -> int:
    return live.custom_counters_by_entity["char:hero"]["feature_use:action-surge"]["spent"]


def test_action_surge_costs_no_action_and_keeps_the_turn() -> None:
    """SRD 5.2 Action Surge: "On your turn, you can take one additional action".
    Its activation is ``special``: part of the turn, not an action of its own."""
    handle, live = _fighter()
    _surge(handle)
    hero = combatant(live)
    assert (hero.action_available, hero.extra_actions_remaining) == (True, 1)
    assert hero.action_surge_used_this_turn
    assert live.current_actor_id == "char:hero"
    assert _surges_spent(live) == 1
    assert get_live(handle).turn.extra_actions_remaining == 1


def test_surge_then_two_attack_actions() -> None:
    """A Fighter 2 makes one attack per Attack action; the extra action takes a
    second one. Seed 6: 2 + 3 = 5, then 5 + 3 = 8; the turn ends with nothing left."""
    handle, live = _fighter()
    _surge(handle)
    _swing(handle)
    assert live.current_actor_id == "char:hero"
    _swing(handle)
    assert [e.amount for e in events(live, DamageApplied)] == [5, 8]
    assert live.current_actor_id == "mon:foe"


def test_extra_attack_gets_fresh_swings_on_the_surge_action() -> None:
    """A Fighter 5 spends its Attack action's two swings, surges and takes a
    second Attack action with two fresh swings. Seed 6: d8 2, 5, 1, 8 → 5, 8,
    4, 11 (d20 2 and 5 still hit AC 1); a fifth swing has nothing to pay for it."""
    handle, live = _fighter(5)
    _swing(handle)
    _swing(handle)
    _surge(handle)
    _swing(handle)
    assert combatant(live).attacks_remaining == 1
    _swing(handle)
    _swing(handle)
    assert [e.amount for e in events(live, DamageApplied)] == [5, 8, 4, 11]
    assert [e.reason for e in events(live, AttackFailed)] == ["no_action_economy"]


def test_surge_then_dodge_keeps_the_turn_for_the_extra_action() -> None:
    """Dodge on the base Action would end the turn; with the surge's action left
    it doesn't, and that action then takes the Attack action (seed 6: 5)."""
    handle, live = _fighter()
    _surge(handle)
    act(handle, "char:hero", intent_type="dodge")
    hero = combatant(live)
    assert (hero.dodging, hero.action_available, hero.extra_actions_remaining) == (True, False, 1)
    assert live.current_actor_id == "char:hero"
    _swing(handle)
    assert [e.amount for e in events(live, DamageApplied)] == [5]
    assert live.current_actor_id == "mon:foe"


def test_the_surge_action_cannot_be_a_magic_action() -> None:
    """ "...one additional action, except the Magic action." Glossary, Magic
    action: "you cast a spell that has a casting time of an action or use a
    feature or magic item that requires a Magic action to be activated." With
    the base Action spent, a cast gets ``CastFailed`` and a wand use
    ``IntentRejectedError`` — nothing spent, turn kept — and the extra action
    still takes the Attack action."""
    handle, live = _fighter()
    _surge(handle)
    _swing(handle)
    act(handle, "char:hero", intent_type="cast_spell", spell_id="fire-bolt", target_id="mon:foe")
    with pytest.raises(IntentRejectedError) as rejected:
        act(
            handle,
            "char:hero",
            intent_type="use_item",
            item_id="wand-of-magic-missiles",
            target_id="mon:foe",
        )
    assert rejected.value.reason == "no_action_economy"
    assert [e.reason for e in events(live, CastFailed)] == ["no_action_economy"]
    assert combatant(live).extra_actions_remaining == 1
    _swing(handle)
    assert len(events(live, AttackRolled)) == 2
    assert live.current_actor_id == "mon:foe"


def test_an_unused_surge_lapses_at_the_next_turn() -> None:
    """``pass`` ends the turn even with the extra action unspent; it lapses at
    the fighter's next turn start."""
    handle, live = _fighter()
    _surge(handle)
    _swing(handle)
    act(handle, "char:hero", intent_type="pass")
    assert live.current_actor_id == "mon:foe"
    monster_turn(handle)
    hero = combatant(live)
    assert live.current_actor_id == "char:hero"
    assert (hero.extra_actions_remaining, hero.action_surge_used_this_turn) == (0, False)
    assert get_live(handle).turn.extra_actions_remaining == 0


def test_dash_and_disengage_can_take_the_surge_action() -> None:
    """Any action but the Magic action: Dash on the base Action, Disengage on
    the extra one; a third action has nothing to pay for it."""
    handle, live = _fighter()
    _surge(handle)
    act(handle, "char:hero", intent_type="dash")
    act(handle, "char:hero", intent_type="disengage")
    hero = combatant(live)
    assert (hero.movement_remaining, hero.disengaging_this_turn, hero.extra_actions_remaining) == (
        60,
        True,
        0,
    )
    with pytest.raises(IntentRejectedError):
        act(handle, "char:hero", intent_type="dash")


def test_one_surge_per_turn_from_level_17() -> None:
    """ "Starting at level 17, you can use it twice before a rest but only once
    on a turn." The second surge that turn is refused before its use is spent;
    the next turn it works."""
    handle, live = _fighter(17)
    _surge(handle)
    _surge(handle)
    assert [e.reason for e in events(live, CastFailed)] == ["no_action_economy"]
    assert (combatant(live).extra_actions_remaining, _surges_spent(live)) == (1, 1)
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    _surge(handle)
    assert (combatant(live).extra_actions_remaining, _surges_spent(live)) == (1, 2)
