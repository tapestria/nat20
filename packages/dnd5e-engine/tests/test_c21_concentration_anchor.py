"""SRD 5.2 §Concentration for every concentration spell: "You lose
Concentration on an effect the moment you start casting a spell that requires
Concentration or activate another effect that requires Concentration." A
concentration spell whose resolution applies no concentration effect of its
own (a summon, a construct, a save every target passed) anchors it on its
caster, and C13 governs the anchor like any other concentration effect."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import ActiveEffect
from dnd5e_engine.events import (
    ConcentrationDropped,
    EffectApplied,
    EffectExpired,
    SaveRolled,
    SpellCast,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _ANCHOR_FLAG, _anchor_identity
from dnd5e_engine.spatial import cell_id
from tests.c21_support import (
    act,
    cleric,
    combatant,
    events,
    foe,
    monster_turn,
    pc,
    start,
    wizard,
)

CLERIC = "char:cleric"
SW_ANCHOR = ("char:cleric", "effect:spiritual-weapon", "cast:spiritual-weapon:char:cleric")
# An Incapacitated foe skips its turns without a draw, so the cleric's rounds
# pass without an attack on it.
HELD_FOE = ActiveEffect(
    id="effect:held",
    name="Held",
    origin="test:held",
    target_id="mon:foe",
    statuses={"incapacitated"},
)


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _spiritual_weapon(handle) -> None:
    """Cast with no target: the anchor is the whole outcome (a force placed
    without a creature to attack makes no attack roll)."""
    act(handle, CLERIC, intent_type="cast_spell", spell_id="spiritual-weapon")


def _anchors(live) -> list[ActiveEffect]:
    return [e.effect for e in events(live, EffectApplied) if e.effect.flags.get(_ANCHOR_FLAG)]


def test_the_anchor_identity_is_the_caster_held_chain_entry() -> None:
    assert _anchor_identity("spiritual-weapon", CLERIC) == SW_ANCHOR


def test_spiritual_weapon_anchors_its_concentration() -> None:
    """Spiritual Weapon's only activity is a ``summon``, so nothing it resolves
    concentrates; the anchor does. A Bonus Action: the cleric's turn stays
    open. The anchor's own effect has no changes, statuses or duration, and a
    PC's anchored cast counts into ``expended_resources`` like any
    concentration effect."""
    handle, live = start([cleric()], seed=3)
    _spiritual_weapon(handle)
    [anchor] = _anchors(live)
    assert (anchor.target_id, anchor.id, anchor.origin) == SW_ANCHOR
    assert anchor.name == "Spiritual Weapon"
    assert anchor.flags == {"concentration": True, _ANCHOR_FLAG: True}
    assert (anchor.changes, anchor.statuses) == ([], set())
    assert anchor.duration.rounds is None
    assert live.concentration_chain[CLERIC] == [SW_ANCHOR]
    assert live.concentration_rounds_remaining[CLERIC] == 10  # 1 minute
    assert combatant(live, CLERIC).concentration_effect_id == "effect:spiritual-weapon"
    assert live.expended_resources[CLERIC] == {"Spiritual Weapon": 1}
    assert live.initiative[live.current_turn_index].entity_id == CLERIC


def test_the_anchor_draws_nothing() -> None:
    """Seeded determinism: the anchored cast leaves the RNG where it was."""
    handle, live = start([cleric()], seed=3)
    state = live.rng.getstate()
    _spiritual_weapon(handle)
    assert live.rng.getstate() == state


def test_spiritual_weapon_ends_bless() -> None:
    """The cleric blesses itself (an Action, which ends its turn), then casts
    Spiritual Weapon next round: Bless's concentration ends."""
    handle, live = start([cleric()], seed=3, active_effects=[HELD_FOE])
    act(handle, CLERIC, intent_type="cast_spell", spell_id="bless", target_id=CLERIC)
    assert live.concentration_chain[CLERIC] == [
        (CLERIC, "effect:blessed", "cast:blessed:char:cleric")
    ]
    monster_turn(handle)
    _spiritual_weapon(handle)
    assert [(e.target_id, e.effect_name) for e in events(live, ConcentrationDropped)] == [
        (CLERIC, "effect:blessed")
    ]
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:blessed", "concentration_drop")
    ]
    assert live.concentration_chain[CLERIC] == [SW_ANCHOR]
    assert combatant(live, CLERIC).concentration_effect_id == "effect:spiritual-weapon"


def test_a_hit_on_the_anchored_caster_draws_the_con_save_and_a_failure_ends_it() -> None:
    """SRD 5.2: "If you take damage, you must succeed on a Constitution saving
    throw to maintain Concentration. The DC equals 10 or half the damage taken
    (round down), whichever number is higher". Seed 9: the cast and the pass
    draw nothing; the foe's d20 15 hits AC 10 for 1d4 = 3; the cleric's CON
    save is a 9 against DC 10, a failure."""
    handle, live = start([cleric()], seed=9)
    _spiritual_weapon(handle)
    act(handle, CLERIC, intent_type="pass")
    monster_turn(handle)
    [save] = events(live, SaveRolled)
    assert (save.target_id, save.ability, save.roll_total, save.dc, save.succeeded) == (
        CLERIC,
        "con",
        9,
        10,
        False,
    )
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "concentration_drop")
    ]
    assert CLERIC not in live.concentration_chain
    assert combatant(live, CLERIC).concentration_effect_id is None


def test_the_drop_intent_ends_the_anchor() -> None:
    handle, live = start([cleric()], seed=3)
    _spiritual_weapon(handle)
    act(handle, CLERIC, intent_type="drop_concentration")
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "concentration_drop")
    ]
    assert CLERIC not in live.concentration_chain


@pytest.mark.parametrize(
    ("seed", "saved", "chain"),
    [
        # d20 20 + WIS 0 against the Wizard 9's DC 16: every target saves.
        (5, True, [("char:wiz", "effect:hold-person", "cast:hold-person:char:wiz")]),
        # d20 5: the foe is Paralyzed and the spell concentrates through its
        # own effect — no anchor.
        (1, False, [("mon:foe", "effect:paralyzed", "cast:paralyzed:char:wiz")]),
    ],
)
def test_hold_person_is_anchored_only_when_every_target_saves(
    seed: int, saved: bool, chain: list[tuple[str, str, str]]
) -> None:
    handle, live = start([wizard()], seed=seed)
    act(handle, "char:wiz", intent_type="cast_spell", spell_id="hold-person", target_id="mon:foe")
    [save] = events(live, SaveRolled)
    assert save.succeeded is saved
    assert live.concentration_chain["char:wiz"] == chain
    assert bool(_anchors(live)) is saved


def test_a_non_concentration_spell_is_not_anchored() -> None:
    handle, live = start([cleric(spells_known=["healing-word"])], seed=3)
    act(handle, CLERIC, intent_type="cast_spell", spell_id="healing-word", target_id=CLERIC)
    assert [e.spell_id for e in events(live, SpellCast)] == ["healing-word"]
    assert not _anchors(live)
    assert CLERIC not in live.concentration_chain


def test_recasting_the_same_spell_restarts_its_concentration() -> None:
    """A recast ends the running Spiritual Weapon ("concentration_drop") before
    the new anchor: one chain entry, one live anchor, the 1-minute counter
    back at 10 (it stood at 9 after the first cast's turn)."""
    handle, live = start([cleric()], seed=3, active_effects=[HELD_FOE])
    _spiritual_weapon(handle)
    act(handle, CLERIC, intent_type="pass")
    assert live.concentration_rounds_remaining[CLERIC] == 9
    monster_turn(handle)
    _spiritual_weapon(handle)
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "concentration_drop")
    ]
    assert live.concentration_chain[CLERIC] == [SW_ANCHOR]
    assert [e.id for e in live.active_effects[CLERIC]] == ["effect:spiritual-weapon"]
    assert live.concentration_rounds_remaining[CLERIC] == 10


def test_the_one_minute_duration_expires_the_anchor() -> None:
    """1 minute is 10 rounds; the cast turn's own end counts as the first."""
    handle, live = start([cleric()], seed=3, active_effects=[HELD_FOE])
    _spiritual_weapon(handle)
    for _ in range(9):
        act(handle, CLERIC, intent_type="pass")
        monster_turn(handle)
    assert not events(live, EffectExpired)
    act(handle, CLERIC, intent_type="pass")
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "duration")
    ]
    assert CLERIC not in live.concentration_chain


@pytest.mark.parametrize(("seed", "anchored"), [(5, True), (1, False)])
def test_a_monster_cast_is_anchored_when_its_target_saves(seed: int, anchored: bool) -> None:
    """The Dryad's first turn casts Entangle (1/day; STR save DC 14). Seed 5:
    the hero's d20 20 saves, so nothing concentrates but the anchor. Seed 1:
    a 5 fails, and the Restrained effect concentrates on its own. The
    monster site keeps its uncapped duration."""
    dryad = foe(
        entity_id="mon:dryad",
        name="Dryad",
        monster_template_slug="dryad",
        initiative=25,
        zone_id=cell_id(2, 0),
    )
    handle, live = start([pc()], seed=seed, encounter=[dryad])
    monster_turn(handle)
    assert [(e.actor_id, e.spell_id) for e in events(live, SpellCast)] == [
        ("mon:dryad", "entangle")
    ]
    anchor = ("mon:dryad", "effect:entangle", "cast:entangle:mon:dryad")
    assert (live.concentration_chain["mon:dryad"] == [anchor]) is anchored
    assert bool(_anchors(live)) is anchored
    assert "mon:dryad" not in live.concentration_rounds_remaining


def test_a_readied_concentration_spell_now_concentrates() -> None:
    """A readied Fog Cloud fires on the foe's attack as a self-cast; the
    readied site now runs the same fold, so the spell concentrates (1 hour:
    600 rounds). Seed 1: the cast draws nothing; the foe's d20 5 misses AC 25."""
    hero = pc(spells_known=["fog-cloud"], spell_slots={1: 1}, ac=25)
    handle, live = start([hero], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="ready",
        spell_id="fog-cloud",
        slot_level=1,
        reaction_trigger="hit_by_attack",
    )
    monster_turn(handle)
    assert [e.spell_id for e in events(live, SpellCast)] == ["fog-cloud"]
    assert live.concentration_chain["char:hero"] == [
        ("char:hero", "effect:fog-cloud", "cast:fog-cloud:char:hero")
    ]
    assert live.concentration_rounds_remaining["char:hero"] == 600
    assert combatant(live, "char:hero").concentration_effect_id == "effect:fog-cloud"
