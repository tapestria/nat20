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
from dnd5e_engine.events import DamageApplied, HealingApplied, IntentSubmitted, RechargeRolled
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
    turns; Foundry parity — an unspent part is not rolled for.

    C18 Task 3 note: turn 1 no longer needs a manual ``recharge_spent = True``
    flip — ``rank_monster_actions`` now ranks the available Fire Breath ahead
    of Claw, so the mephit spends it for real on turn 1 (see
    ``test_mephit_breathes_first_then_claw_or_breath_again_after_recharge``
    below for the full selection assertions). The tracked entry ends turn 2
    spent either way: on a successful roll, Fire Breath is available again
    and gets re-selected + re-spent the SAME turn; on a failed roll it just
    stays spent — either path is observed here, only the roll fields differ.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        uses = live.monster_action_uses_by_entity["mon:foe"]["fire-breath"]
        assert uses.recharge_spent is False
        await advance_monster_turn(handle)  # turn 1 — the mephit breathes, spending it
        assert uses.recharge_spent is True
        await _pass(handle)
        await advance_monster_turn(handle)  # turn 2 — the roll happens at turn start
        return handle, live

    handle, live = _run(go())
    rolled = _events(live, RechargeRolled)
    assert len(rolled) == 1
    ev = rolled[0]
    assert (ev.monster_id, ev.action_slug, ev.threshold) == ("mon:foe", "fire-breath", "6")
    assert 1 <= ev.roll <= 6
    assert ev.succeeded == (ev.roll >= 6)
    assert live.monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent is True
    assert (
        get_live(handle).monster_action_uses_by_entity["mon:foe"]["fire-breath"].recharge_spent
        is True
    )


def test_ranked_selection_opens_with_recharge_action_then_recharges_or_repeats():
    """C18 Task 3 (S01): ``rank_monster_actions`` now ranks an available
    recharge action ahead of the first-listed offensive action, so the
    mephit opens combat with Fire Breath instead of Claw. Turn 2 rolls to
    recharge at turn start (SRD 5.2 "at the start of each of the monster's
    turns, roll 1d6 ... if within the ... range, the monster regains the
    use"); observed once for seed 7: ``roll=6`` (>= the "6" threshold, i.e.
    success), so Fire Breath is available again and re-selected the SAME
    turn. Had it failed, turn 2's action would fall back to Claw — no fire
    damage in that slice of the log — which the final assertion checks
    either way rather than hard-coding the branch not taken.
    """

    async def go():
        handle, live = await _start(
            [_hero(initiative=1)], [_foe("magma-mephit", initiative=20, hp=18, ac=11)], seed=7
        )
        await advance_monster_turn(handle)  # turn 1
        turn1_log = list(live.event_log)
        await _pass(handle)
        pre_turn2 = len(live.event_log)
        await advance_monster_turn(handle)  # turn 2
        turn2_log = live.event_log[pre_turn2:]
        return turn1_log, turn2_log

    turn1_log, turn2_log = _run(go())

    def _fire_damage_at_hero(log):
        return [
            e
            for e in log
            if isinstance(e, DamageApplied)
            and e.target_id == "char:hero"
            and e.damage_type == "fire"
        ]

    assert _fire_damage_at_hero(turn1_log), "turn 1 should open with Fire Breath, not Claw"
    turn1_intents = [
        e for e in turn1_log if isinstance(e, IntentSubmitted) and e.actor_id == "mon:foe"
    ]
    assert [i.intent_type for i in turn1_intents] == ["attack"]

    turn2_rolls = [e for e in turn2_log if isinstance(e, RechargeRolled)]
    assert len(turn2_rolls) == 1
    ev = turn2_rolls[0]
    # Pinned from a live run at seed 7 (observed, not guessed).
    assert (ev.roll, ev.succeeded) == (6, True)
    if ev.succeeded:
        assert _fire_damage_at_hero(turn2_log), "recharge succeeded — Fire Breath fires again"
    else:
        assert not _fire_damage_at_hero(turn2_log), "recharge failed — turn 2 falls back to Claw"


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
