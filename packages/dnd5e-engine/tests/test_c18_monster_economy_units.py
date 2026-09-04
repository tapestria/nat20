"""C18 — monster action economy, orchestrator-level units: limited-use state
hydration and the three turn-start mechanics (legendary-action reset,
recharge rolls, regeneration). Every rule quotes the SRD 5.2 sentence it
pins. Later C18 tasks append to this file."""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    advance_monster_turn,
    get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.events import HealingApplied, RechargeRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live
from dnd5e_engine.spatial import cell_id as cell


@pytest.fixture(autouse=True)
def _bundled_loader():
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _run(coro):
    return asyncio.run(coro)


def _events(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


def _hero(entity_id="char:hero", *, initiative=20, hp=40, ac=15, attack_bonus=6, col=0):
    return PartyMemberSpec(
        entity_id=entity_id,
        name=entity_id,
        initiative=initiative,
        hp_current=hp,
        hp_max=hp,
        ac=ac,
        attack_bonus=attack_bonus,
        zone_id=cell(col, 0),
    )


def _foe(slug, entity_id="mon:foe", *, initiative=5, hp, hp_max=None, ac=10, col=3):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id,
        initiative=initiative,
        hp_current=hp,
        hp_max=hp_max if hp_max is not None else hp,
        ac=ac,
        zone_id=cell(col, 0),
        monster_template_slug=slug,
    )


async def _start(party, encounter, *, seed=1, width=10, session="c18-units"):
    start = await start_combat(
        session_id=session,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=GridScene(width=width, height=10, cell_size_ft=5),
        rng_seed=seed,
    )
    return start.handle, _get_live(start.handle)


async def _pass(handle):
    await submit_player_intent(
        handle, actor_id="char:hero", intent=PlayerIntent(intent_type="pass")
    )


def test_regeneration_heals_at_own_turn_start_when_above_zero():
    """SRD 5.2 Regeneration: "regains [N] Hit Points at the start of each of its
    turns if it has at least 1 Hit Point." Troll heal activity: flat 10."""

    async def go():
        handle, live = await _start([_hero()], [_foe("troll", hp=40, hp_max=94, ac=15)], seed=2)
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    heals = [e for e in _events(live, HealingApplied) if e.target_id == "mon:foe"]
    assert heals
    assert heals[0].amount == 10
    assert live.tracked_hp["mon:foe"] == 50


def test_regeneration_is_capped_at_hp_max_and_silent_at_zero():
    async def go(hp):
        handle, live = await _start(
            [_hero()], [_foe("troll", hp=max(hp, 1), hp_max=94, ac=15)], seed=2
        )
        if hp == 0:
            live.tracked_hp["mon:foe"] = 0
            live.initiative[1].hp_current = 0
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    full = _run(go(94))
    assert not [e for e in _events(full, HealingApplied) if e.target_id == "mon:foe"]
    down = _run(go(0))  # "if it has at least 1 Hit Point"
    assert not _events(down, HealingApplied)


def test_recharge_roll_only_after_the_action_was_spent():
    """SRD 5.2 Recharge X–Y: rolled at the start of each of the monster's
    turns; Foundry parity — an unspent part is not rolled for."""

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        uses = live.monster_action_uses_by_entity["mon:foe"]["fire-breath"]
        assert uses.recharge_spent is False
        await advance_monster_turn(
            handle
        )  # turn 1 — Task 3 makes this the breath; here we force the state
        uses.recharge_spent = True
        await _pass(handle)
        await advance_monster_turn(handle)  # turn 2 — the roll happens here
        return handle, live

    handle, live = _run(go())
    rolled = _events(live, RechargeRolled)
    assert len(rolled) == 1
    ev = rolled[0]
    assert (ev.monster_id, ev.action_slug, ev.threshold) == ("mon:foe", "fire-breath", "6")
    assert 1 <= ev.roll <= 6
    assert ev.succeeded == (ev.roll >= 6)
    assert live.monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent is (
        not ev.succeeded
    )
    assert get_live(handle).monster_action_uses_by_entity["mon:foe"][
        "fire-breath"
    ].recharge_spent is (not ev.succeeded)


def test_legendary_pools_hydrate_from_the_template_and_reset_at_own_turn():
    async def go():
        handle, live = await _start(
            [_hero(initiative=25)],
            [_foe("adult-red-dragon", initiative=10, hp=256, ac=19)],
            seed=4,
        )
        dragon = live.initiative[1]
        assert (dragon.legendary_actions_max, dragon.legendary_actions_remaining) == (3, 3)
        assert dragon.legendary_resistances_max == dragon.legendary_resistances_remaining == 3
        assert get_live(handle).legendary_actions_by_entity == {"mon:foe": 3}
        dragon.legendary_actions_remaining = 1
        await _pass(handle)
        await advance_monster_turn(handle)
        return live

    live = _run(go())
    assert live.initiative[1].legendary_actions_remaining == 3


def test_template_damage_immunities_hydrate_unconditionally():
    async def go():
        _, live = await _start([_hero()], [_foe("zombie", hp=15, ac=8)])
        return live.initiative[1]

    z = _run(go())
    assert "poison" in z.damage_immunities  # verify the zombie's corpus immunities first
    assert z.physical_resistances_nonmagical_only is False
