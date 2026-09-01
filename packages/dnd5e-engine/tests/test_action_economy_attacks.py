"""C14 Task 1 — Extra Attack counter and turn-keeping main-hand attacks.

SRD 5.2 (Fighter, Extra Attack): "You can attack twice, instead of once,
whenever you take the Attack action on your turn." The multiclass
non-stacking rule means the single highest-count qualifying feature sets
the cap (counts never sum): ``extra-attack`` -> 2, ``two-extra-attacks``
-> 3, ``three-extra-attacks`` -> 4.

``_attacks_per_action`` is the pure-ish lookup (reads the lib loader via
``_granted_feature_slugs``); the orchestrator-level behavior (turn-keeping
attack intents, the ``no_action_economy`` reject, back-compat for
1-attack actors) is exercised end-to-end via ``submit_player_intent``.
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent, get_live
from dnd5e_engine.events import AttackFailed, AttackRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _attacks_per_action,
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant
from tests.e2e.harness import cell, grid_scene


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _combatant(**overrides: object) -> Combatant:
    base = dict(
        entity_id="char:pc",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=20,
        hp_max=20,
    )
    base.update(overrides)
    return Combatant(**base)  # type: ignore[arg-type]


class TestAttacksPerAction:
    def test_fighter_level_5_gets_two_attacks(self):
        c = _combatant(class_slug="fighter", character_level=5)
        assert _attacks_per_action(c) == 2

    def test_fighter_level_4_gets_one_attack(self):
        c = _combatant(class_slug="fighter", character_level=4)
        assert _attacks_per_action(c) == 1

    def test_no_class_slug_gets_one_attack(self):
        c = _combatant(class_slug=None, character_level=20)
        assert _attacks_per_action(c) == 1

    def test_fighter_level_11_gets_three_attacks_never_five(self):
        """Multiclass non-stacking: level 11 Fighter grants BOTH
        ``extra-attack`` (2) and ``two-extra-attacks`` (3); the highest
        tier wins — the counts are never summed to 2 + 3 = 5."""
        c = _combatant(class_slug="fighter", character_level=11)
        assert _attacks_per_action(c) == 3


def _fighter_party(*, character_level: int = 5) -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:ftr",
            name="Fighter",
            initiative=20,
            hp_current=40,
            hp_max=40,
            strength=16,
            attack_bonus=7,
            character_level=character_level,
            class_slug="fighter",
            zone_id=cell(0, 0),
        )
    ]


def _dummy_encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:dummy",
            entity_type="Monster",
            name="Dummy",
            initiative=1,
            hp_current=500,
            hp_max=500,
            ac=1,
            zone_id=cell(1, 0),
        )
    ]


async def _start_fighter_combat(session_id: str, *, character_level: int = 5):
    return await start_combat(
        session_id=session_id,
        party=_fighter_party(character_level=character_level),
        encounter=_dummy_encounter(),
        scene_zones=None,
        grid_scene=grid_scene(),
        rng_seed=21,
    )


def _attack_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:dummy")


def test_extra_attack_view_shows_two_at_turn_start():
    async def _run():
        start = await _start_fighter_combat("sess-t1-view-start")
        return get_live(start.handle)

    view = asyncio.run(_run())
    assert view.turn.attacks_remaining == 2


def test_extra_attack_view_decrements_after_one_swing():
    async def _run():
        start = await _start_fighter_combat("sess-t1-view-decrement")
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return get_live(start.handle)

    view = asyncio.run(_run())
    assert view.turn.attacks_remaining == 1


def test_third_attack_is_rejected_and_actor_keeps_the_turn():
    async def _run():
        start = await _start_fighter_combat("sess-t1-third-swing")
        for _ in range(2):
            await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        # third swing this Action — budget is exhausted (2/2 spent).
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return _get_live(start.handle)

    live = asyncio.run(_run())
    swings = [
        e for e in live.event_log if isinstance(e, AttackRolled) and e.attacker_id == "char:ftr"
    ]
    assert len(swings) == 2
    rejections = [
        e
        for e in live.event_log
        if isinstance(e, AttackFailed)
        and e.actor_id == "char:ftr"
        and e.reason == "no_action_economy"
    ]
    assert len(rejections) == 1
    # the fighter still holds initiative — no TurnEnded fired for them.
    assert live.current_actor_id == "char:ftr"


def test_one_attack_actor_ends_turn_on_first_swing_back_compat():
    """A 1-attack actor (no Extra Attack) swinging a non-Light weapon must
    still end the turn on the first attack — the back-compat bar for C14."""

    async def _run():
        start = await _start_fighter_combat("sess-t1-back-compat", character_level=4)
        await submit_player_intent(start.handle, actor_id="char:ftr", intent=_attack_intent())
        return _get_live(start.handle)

    live = asyncio.run(_run())
    assert live.current_actor_id != "char:ftr"
