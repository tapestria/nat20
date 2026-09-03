"""C17 — spell slots & rests, orchestrator-level units: the second Pact Magic
pool, the reaction drain gates (slot availability, Counterspell range), upcast
target-count expansion (Magic Missile darts), the SpellCast event and the
in-combat ritual rejection. Every rule quotes the SRD 5.2 sentence it pins."""

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
from dnd5e_engine.events import CastFailed, DamageApplied, ReactionTriggered
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


def _caster(
    entity_id="char:caster",
    *,
    spells,
    spell_slots=None,
    pact_slots=None,
    col=0,
    initiative=20,
    intelligence=16,
    **kw,
):
    return PartyMemberSpec(
        entity_id=entity_id,
        name=entity_id,
        initiative=initiative,
        hp_current=30,
        hp_max=30,
        intelligence=intelligence,
        class_slug="wizard",
        character_level=5,
        spells_known=list(spells),
        spell_slots=dict(spell_slots or {}),
        pact_slots=dict(pact_slots or {}),
        zone_id=cell(col, 0),
        **kw,
    )


def _foe(entity_id="mon:foe", *, col=3, hp=100, ac=1):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id,
        initiative=1,
        hp_current=hp,
        hp_max=hp,
        ac=ac,
        zone_id=cell(col, 0),
    )


async def _start(party, encounter, *, seed=1, width=10, session="c17"):
    start = await start_combat(
        session_id=session,
        party=party,
        encounter=encounter,
        scene_zones=None,
        grid_scene=GridScene(width=width, height=10, cell_size_ft=5),
        rng_seed=seed,
    )
    return start.handle, _get_live(start.handle)


# ── Task 3: two pools ────────────────────────────────────────────────────────


def test_pact_slots_reach_live_state_and_view():
    handle, live = _run(_start([_caster(spells=["magic-missile"], pact_slots={1: 2})], [_foe()]))
    assert live.pact_slots_by_entity["char:caster"] == {1: 2}
    assert get_live(handle).pact_slots_by_entity["char:caster"] == {1: 2}


def test_cast_draws_from_pact_pool_when_spellcasting_pool_lacks_the_level():
    """SRD Multiclassing Pact Magic: either pool casts either prepared spell (R3)."""

    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], spell_slots={2: 1}, pact_slots={1: 2})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert not _events(live, CastFailed)
    assert live.pact_slots_by_entity["char:caster"] == {1: 1}
    assert live.spell_slots_by_entity["char:caster"] == {2: 1}


def test_spellcasting_pool_is_consumed_before_pact_pool():
    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], spell_slots={1: 1}, pact_slots={1: 1})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert live.spell_slots_by_entity["char:caster"] == {1: 0}
    assert live.pact_slots_by_entity["char:caster"] == {1: 1}


def test_no_slot_in_either_pool_rejects_with_no_slot():
    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], pact_slots={1: 0})], [_foe()]
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=1,
            ),
        )
        return live

    live = _run(_go())
    assert [e.reason for e in _events(live, CastFailed)] == ["no_slot"]
    assert not _events(live, DamageApplied)


# ── Task 4: drain gates ──────────────────────────────────────────────────────


def _counterspell_pair(*, reactor_slots, enemy_col, seed=9):
    async def _go():
        handle, live = await _start(
            [
                _caster(
                    "char:reactor",
                    spells=["counterspell"],
                    spell_slots=reactor_slots,
                    intelligence=18,
                    initiative=20,
                ),
                _caster(
                    "char:enemy_caster",
                    spells=["fireball"],
                    spell_slots={3: 1},
                    col=enemy_col,
                    initiative=15,
                ),
            ],
            [_foe(col=enemy_col + 1, ac=10, hp=50)],
            seed=seed,
            width=30,
        )
        await submit_player_intent(
            handle,
            actor_id="char:reactor",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
        await submit_player_intent(
            handle,
            actor_id="char:enemy_caster",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="fireball", slot_level=3, target_id="mon:foe"
            ),
        )
        return live

    return _run(_go())


def test_counterspell_with_empty_pool_does_not_fire_and_keeps_reaction():
    """SRD §Spell Slots: "you expend a slot of that spell's level or higher" — no slot,
    no cast. The armed reaction is skipped, not popped (R4)."""
    live = _counterspell_pair(reactor_slots={3: 0}, enemy_col=1)
    assert not _events(live, ReactionTriggered)
    assert not [e for e in _events(live, CastFailed) if e.reason == "countered"]
    reactor = next(c for c in live.initiative if c.entity_id == "char:reactor")
    assert reactor.reaction_available is True
    assert [pr.owner_id for pr in live.pending_reactions] == ["char:reactor"]


def test_counterspell_out_of_60ft_range_does_not_fire():
    """Counterspell: range 60 ft, "when you see a creature within range casting"."""
    live = _counterspell_pair(reactor_slots={3: 1}, enemy_col=18)  # 90 ft
    assert not _events(live, ReactionTriggered)
    assert live.spell_slots_by_entity["char:reactor"] == {3: 1}


def test_counterspell_in_range_with_slot_still_fires():
    live = _counterspell_pair(reactor_slots={3: 1}, enemy_col=1)
    assert [e.reaction_name for e in _events(live, ReactionTriggered)] == ["counterspell"]
    assert live.spell_slots_by_entity["char:reactor"] == {3: 0}


def test_counterspell_draws_from_pact_pool():
    live = _counterspell_pair(reactor_slots={}, enemy_col=1)
    assert not _events(live, ReactionTriggered)  # sanity: no pool at all

    # now with a pact pool only
    async def _go():
        handle, live = await _start(
            [
                _caster(
                    "char:reactor", spells=["counterspell"], pact_slots={3: 1}, intelligence=18
                ),
                _caster(
                    "char:enemy_caster",
                    spells=["fireball"],
                    spell_slots={3: 1},
                    col=1,
                    initiative=15,
                ),
            ],
            [_foe(col=2, ac=10, hp=50)],
            seed=9,
            width=30,
        )
        await submit_player_intent(
            handle,
            actor_id="char:reactor",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
        await submit_player_intent(
            handle,
            actor_id="char:enemy_caster",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="fireball", slot_level=3, target_id="mon:foe"
            ),
        )
        return live

    live2 = _run(_go())
    assert _events(live2, ReactionTriggered)
    assert live2.pact_slots_by_entity["char:reactor"] == {3: 0}


def test_readied_shield_with_empty_pool_does_not_fire():
    """BACKLOG "No-slot readied reactions fire for free" — Shield half."""

    async def _go(spell_slots):
        handle, live = await _start(
            [_caster("char:target", spells=["shield"], spell_slots=spell_slots, initiative=20)],
            [
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="mon:foe",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=10,
                    attack_bonus=10,
                    damage_dice="1d6",
                    damage_type="slashing",
                    zone_id=cell(1, 0),
                )
            ],
        )
        await submit_player_intent(
            handle,
            actor_id="char:target",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="shield",
                slot_level=1,
                reaction_trigger="hit_by_attack",
            ),
        )
        await advance_monster_turn(handle)
        return live

    live_empty = _run(_go({1: 0}))
    assert not [e for e in _events(live_empty, ReactionTriggered) if e.reaction_name == "shield"]

    live_full = _run(_go({1: 1}))
    assert [e.reaction_name for e in _events(live_full, ReactionTriggered)] == ["shield"]


# ── Task 5: darts ────────────────────────────────────────────────────────────


def _cast_mm(*, slot_level, target_id="mon:foe", target_ids=None, extra_foes=()):
    async def _go():
        handle, live = await _start(
            [_caster(spells=["magic-missile"], spell_slots={1: 1, 3: 1})],
            [_foe(), *extra_foes],
        )
        await submit_player_intent(
            handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id=target_id,
                target_ids=target_ids,
                slot_level=slot_level,
            ),
        )
        return live

    return _run(_go())


def test_magic_missile_base_level_fires_three_darts_sharing_one_roll():
    """SRD: "You create three glowing darts" — one DamageApplied per dart, same amount (R5)."""
    live = _cast_mm(slot_level=1)
    darts = [e for e in _events(live, DamageApplied) if e.target_id == "mon:foe"]
    assert len(darts) == 3
    assert len({d.amount for d in darts}) == 1
    assert all(2 <= d.amount <= 5 and d.damage_type == "force" for d in darts)


def test_magic_missile_slot_3_fires_five_darts_and_hp_drops_by_their_sum():
    live = _cast_mm(slot_level=3)
    darts = [e for e in _events(live, DamageApplied) if e.target_id == "mon:foe"]
    assert len(darts) == 5
    assert live.tracked_hp["mon:foe"] == 100 - sum(d.amount for d in darts)


def test_magic_missile_target_ids_spread_darts_across_creatures():
    live = _cast_mm(
        slot_level=1,
        target_id=None,
        target_ids=("mon:foe", "mon:foe", "mon:foe2"),
        extra_foes=(_foe("mon:foe2", col=4),),
    )
    by_target = {}
    for e in _events(live, DamageApplied):
        by_target[e.target_id] = by_target.get(e.target_id, 0) + 1
    assert by_target == {"mon:foe": 2, "mon:foe2": 1}


def test_magic_missile_too_many_target_ids_is_target_invalid():
    live = _cast_mm(slot_level=1, target_id=None, target_ids=("mon:foe",) * 4)
    assert [e.reason for e in _events(live, CastFailed)] == ["target_invalid"]
    assert not _events(live, DamageApplied)
    assert live.spell_slots_by_entity["char:caster"][1] == 1  # rejected before the slot gate


def test_dart_count_adds_no_rng_draws():
    """Determinism: the 5-dart cast and a 1-target single-dart-shaped cast consume the
    same number of draws — compare the rng state after each."""
    live_a = _cast_mm(slot_level=1)
    live_b = _cast_mm(slot_level=3)
    assert live_a.rng.getstate() == live_b.rng.getstate()
