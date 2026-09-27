"""Summon Dragon (SRD 5.2) seats a Draconic Spirit in the initiative order (C21).

"It manifests in an unoccupied space that you can see within range and uses
the Draconic Spirit stat block." "In combat, the creature shares your
Initiative count, but it takes its turn immediately after yours." "Use the
spell slot's level for the spell's level in the stat block." The cast is
refused before anything is spent when no legal space exists; the seat draws
nothing and announces the creature with ``CombatantJoined``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CombatHandle, get_live
from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.events import (
    CastFailed,
    CastFailedReason,
    CombatantJoined,
    CombatantLeft,
    ConcentrationDropped,
    ConditionApplied,
    DamageApplied,
    SpellCast,
    TurnEnded,
    TurnStarted,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _emit, _get_live, _LiveCombat, start_combat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    SceneTopology,
    WallSegment,
    ZoneEdge,
)
from dnd5e_engine.views import SummonView
from tests.c21_support import (
    act,
    combatant,
    events,
    foe,
    joined,
    monster_turn,
    pc,
    roster,
    start,
    summoner,
    wizard,
)

SD = "summon-dragon"
SUMMONER = "char:summoner"
SPIRIT = "summon:char:summoner:draconic-spirit:1"
ANCHOR = (SUMMONER, "effect:summon-dragon", "cast:summon-dragon:char:summoner")


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _cast(handle: CombatHandle, caster: str = SUMMONER, **intent: Any) -> None:
    act(handle, caster, intent_type="cast_spell", spell_id=SD, **intent)


def _start_on(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    *,
    seed: int = 1,
    **topology: Any,
) -> tuple[CombatHandle, _LiveCombat]:
    """``start`` on a topology of the test's own (``grid_scene=`` / ``scene_zones=``)."""
    result = asyncio.run(
        start_combat(
            session_id=f"c21b-{seed}", party=party, encounter=encounter, rng_seed=seed, **topology
        )
    )
    return result.handle, _get_live(result.handle)


def _s01_druid(**fields: Any) -> PartyMemberSpec:
    """S01's caster: a classless level-9 character (Summon Dragon is a Wizard
    spell; the scenario sets no class) with one level-5 slot."""
    base: dict[str, Any] = {
        "character_level": 9,
        "spells_known": [SD],
        "spell_slots": {5: 1},
        "hp_current": 60,
        "hp_max": 60,
    }
    return pc("char:druid", **(base | fields))


def test_summon_dragon_seats_a_draconic_spirit_at_the_spells_numbers() -> None:
    """S01's combat: the caster at 0,0, the foe at 2,0. The spirit takes the
    first free cell of the scan, 1,0, at the caster's count, with AC 14 + 5 and
    HP 50 + 0 at a level-5 slot."""
    handle, live = start(
        [_s01_druid()],
        seed=7,
        encounter=[foe(zone_id=cell_id(2, 0), initiative=5, ac=15, hp_current=100, hp_max=100)],
    )
    _cast(handle, "char:druid", target_id="mon:foe")
    assert joined(live, "char:druid") == [
        CombatantJoined(
            entity_id="summon:char:druid:draconic-spirit:1",
            name="Draconic Spirit",
            stat_block_slug="draconic-spirit",
            origin_caster_id="char:druid",
            spell_id=SD,
            initiative_count=20,
            after_entity_id="char:druid",
            zone_id=cell_id(1, 0),
            hp_max=50,
            ac=19,
        )
    ]
    assert roster(live) == ["char:druid", "summon:char:druid:draconic-spirit:1", "mon:foe"]


def test_the_summon_takes_its_turn_immediately_after_its_caster() -> None:
    """``char:zed`` shares the summoner's count and Dexterity and follows it on
    the entity-id tie-break. The spirit (DEX 14) is seated in the slot right
    after its caster, never re-sorted ahead of it or behind ``char:zed``; its
    turn opens the moment the caster's ends."""
    handle, live = start(
        [summoner(), pc("char:zed", zone_id=cell_id(0, 1))],
        seed=1,
        encounter=[foe(zone_id=cell_id(5, 5))],
    )
    assert roster(live) == [SUMMONER, "char:zed", "mon:foe"]
    _cast(handle)
    assert roster(live) == [SUMMONER, SPIRIT, "char:zed", "mon:foe"]
    spirit = live.initiative[1]
    assert (spirit.initiative, spirit.dexterity) == (20, 14)
    boundary = [e for e in live.event_log if isinstance(e, (TurnEnded, TurnStarted))]
    assert boundary[-2:] == [TurnEnded(actor_id=SUMMONER), TurnStarted(actor_id=SPIRIT)]
    assert live.current_actor_id == SPIRIT


@pytest.mark.parametrize("level", [5, 6, 7, 8, 9])
def test_summon_dragon_numbers_at_every_slot_level(level: int) -> None:
    """SRD 5.2 Draconic Spirit at slot level L: "AC 14 + the spell's level";
    "HP 50 + 10 for each spell level above 5"; Rend's "Bonus equals your spell
    attack modifier" (the Wizard 9's +8) and "+ the spell's level" damage; "PB
    equals your Proficiency Bonus" (4); "a number of Rend attacks equal to half
    the spell's level (round down)"."""
    handle, live = start([summoner(spell_slots={level: 1})], seed=1)
    _cast(handle, slot_level=level)
    [event] = joined(live, SUMMONER)
    spirit = combatant(live, SPIRIT)
    assert (event.ac, event.hp_max) == (14 + level, 50 + 10 * (level - 5))
    assert (spirit.ac, spirit.hp_current, spirit.hp_max) == (event.ac, event.hp_max, event.hp_max)
    summon = live.summons[SPIRIT]
    assert summon.slot_level == level
    assert summon.magnitudes.attack_bonus == 8
    assert summon.magnitudes.proficiency_bonus == 4
    assert summon.magnitudes.attack_damage_bonus == level
    assert summon.attacks_per_action == level // 2


def test_the_summon_is_a_draconic_spirit_combatant() -> None:
    """A Monster acting from the Draconic Spirit stat block at its summoner's
    numbers, on neither side set: its allegiance is its owner's."""
    handle, live = start([summoner()], seed=1)
    _cast(handle)
    spirit = combatant(live, SPIRIT)
    assert (spirit.entity_type, spirit.name, spirit.creature_type) == (
        "Monster",
        "Draconic Spirit",
        "dragon",
    )
    scores = (
        spirit.strength,
        spirit.dexterity,
        spirit.constitution,
        spirit.intelligence,
        spirit.wisdom,
        spirit.charisma,
    )
    assert scores == (19, 14, 17, 10, 14, 14)
    assert spirit.damage_resistances == ["acid", "cold", "fire", "lightning", "poison"]
    assert spirit.condition_immunities == ["charmed", "frightened", "poisoned"]
    assert (spirit.base_speed, spirit.movement_remaining) == (30, 30)
    assert (spirit.movement_modes.fly, spirit.movement_modes.swim) == (60, 30)
    assert (spirit.senses.blindsight, spirit.senses.darkvision) == (30, 60)
    assert (spirit.proficiency_bonus_override, spirit.attack_bonus) == (4, 8)
    assert live.monster_slug_by_entity[SPIRIT] == "draconic-spirit"
    assert live.monster_action_uses_by_entity[SPIRIT] == {}
    # The default foe holds 1,0, so the scan's next cell.
    assert (live.actor_zone[SPIRIT], live.tracked_hp[SPIRIT]) == (cell_id(0, 1), 50)
    assert SPIRIT not in live.party_ids | live.encounter_ids


# ── Placement ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("occupants", "cell"),
    [
        ([], cell_id(1, 0)),  # S01's layout: the foe stands at 2,0
        ([cell_id(1, 0)], cell_id(0, 1)),  # S02's layout: the breaker holds 1,0
        ([cell_id(1, 0), cell_id(0, 1)], cell_id(1, 1)),
    ],
)
def test_the_default_space_is_the_first_free_cell_of_the_scan(
    occupants: list[str], cell: str
) -> None:
    """Nearest the caster first, then by row, then by column."""
    encounter = [foe(zone_id=cell_id(2, 0))] + [
        foe(entity_id=f"mon:block{i}", zone_id=zone) for i, zone in enumerate(occupants)
    ]
    handle, live = start([summoner()], seed=1, encounter=encounter)
    _cast(handle, target_id="mon:foe")
    assert [e.zone_id for e in joined(live, SUMMONER)] == [cell]
    assert live.actor_zone[SPIRIT] == cell


def test_an_explicit_free_space_is_used() -> None:
    handle, live = start([summoner()], seed=1)
    _cast(handle, target_zone_id=cell_id(3, 4))
    assert live.actor_zone[SPIRIT] == cell_id(3, 4)


_WALLED = GridScene(width=10, height=10, wall_segments=[WallSegment(x1=2, y1=0, x2=2, y2=10)])


@pytest.mark.parametrize(
    ("scene", "target_zone_id", "reason"),
    [
        (GridScene(width=10, height=10), cell_id(1, 0), "target_invalid"),  # the foe's space
        (GridScene(width=10, height=10), cell_id(10, 0), "target_invalid"),  # off the map
        (
            GridScene(width=10, height=10, blocked_cells=[cell_id(3, 0)]),
            cell_id(3, 0),
            "target_invalid",
        ),
        (GridScene(width=15, height=1), cell_id(13, 0), "out_of_range"),  # 65 ft
        (_WALLED, cell_id(3, 3), "out_of_range"),  # behind the wall
        (GridScene(width=2, height=1), None, "out_of_range"),  # no free cell at all
        (GridScene(width=10, height=10), "1, 1", "target_invalid"),  # not the grid's own id
        (GridScene(width=10, height=10), " 1,1", "target_invalid"),
        (GridScene(width=10, height=10), "01,1", "target_invalid"),
    ],
    ids=[
        "occupied",
        "off-map",
        "blocked",
        "beyond-60-ft",
        "out-of-sight",
        "no-free-cell",
        "spaced-id",
        "padded-id",
        "zero-led-id",
    ],
)
def test_no_legal_space_refuses_the_cast_before_anything_is_spent(
    scene: GridScene, target_zone_id: str | None, reason: CastFailedReason
) -> None:
    handle, live = _start_on([summoner()], [foe()], grid_scene=scene)
    _cast(handle, target_zone_id=target_zone_id)
    assert events(live, CastFailed) == [CastFailed(actor_id=SUMMONER, spell_id=SD, reason=reason)]
    assert not events(live, SpellCast)
    assert not events(live, CombatantJoined)
    assert live.spell_slots_by_entity[SUMMONER] == {1: 1, 5: 2}
    assert combatant(live, SUMMONER).action_available
    assert live.current_actor_id == SUMMONER
    assert roster(live) == [SUMMONER, "mon:foe"]
    assert live.concentration_chain.get(SUMMONER, []) == []


@pytest.mark.parametrize(("target_zone_id", "zone"), [(None, "near"), ("far", "far")])
def test_a_zone_graph_seats_the_summon_in_a_zone(target_zone_id: str | None, zone: str) -> None:
    """Zones are not exclusive: with no ``target_zone_id`` the creature
    manifests in the caster's own zone; a named zone within range is used."""
    scene = SceneTopology(
        zones=["near", "far"], edges=[ZoneEdge(a="near", b="far", distance_ft=30)]
    )
    handle, live = _start_on([summoner(zone_id="near")], [foe(zone_id="far")], scene_zones=scene)
    _cast(handle, target_zone_id=target_zone_id)
    assert [e.zone_id for e in joined(live, SUMMONER)] == [zone]


def test_ready_summon_dragon_is_refused() -> None:
    """A readied cast resolves from the reaction queue, which carries no space."""
    handle, live = start([summoner()], seed=1)
    act(
        handle,
        SUMMONER,
        intent_type="ready",
        spell_id=SD,
        slot_level=5,
        reaction_trigger="hit_by_attack",
    )
    assert events(live, CastFailed) == [
        CastFailed(actor_id=SUMMONER, spell_id=SD, reason="target_invalid")
    ]
    assert live.pending_reactions == []
    assert combatant(live, SUMMONER).action_available


@pytest.mark.parametrize("target_zone_id", [None, cell_id(0, 1)])
def test_a_blinded_caster_sees_no_space(target_zone_id: str | None) -> None:
    """SRD 5.2 Blinded: "You can't see" — so no space is one "that you can
    see", and the cast is refused before anything is spent."""
    handle, live = start([summoner()], seed=1)
    _emit(live, ConditionApplied(target_id=SUMMONER, condition="blinded"))
    _cast(handle, target_zone_id=target_zone_id)
    assert events(live, CastFailed) == [
        CastFailed(actor_id=SUMMONER, spell_id=SD, reason="out_of_range")
    ]
    assert not events(live, CombatantJoined)
    assert live.spell_slots_by_entity[SUMMONER] == {1: 1, 5: 2}
    assert combatant(live, SUMMONER).action_available


def test_a_blinded_caster_sees_no_zone_either() -> None:
    """On a zone graph the default space is the caster's own zone, which a
    Blinded caster can't see either."""
    scene = SceneTopology(
        zones=["near", "far"], edges=[ZoneEdge(a="near", b="far", distance_ft=30)]
    )
    handle, live = _start_on([summoner(zone_id="near")], [foe(zone_id="far")], scene_zones=scene)
    _emit(live, ConditionApplied(target_id=SUMMONER, condition="blinded"))
    _cast(handle)
    assert events(live, CastFailed) == [
        CastFailed(actor_id=SUMMONER, spell_id=SD, reason="out_of_range")
    ]
    assert not events(live, CombatantJoined)


@pytest.mark.parametrize(
    ("target_zone_id", "seated"), [(cell_id(0, 2), True), (cell_id(0, 3), False)]
)
def test_blindsight_sees_a_space_while_blinded(target_zone_id: str, seated: bool) -> None:
    """SRD 5.2 Blindsight: "you can see anything that isn't behind Total Cover
    even if you have the Blinded condition" — within its 10 feet."""
    handle, live = start([summoner(senses=CombatantSenses(blindsight=10))], seed=1)
    _emit(live, ConditionApplied(target_id=SUMMONER, condition="blinded"))
    _cast(handle, target_zone_id=target_zone_id)
    assert [e.zone_id for e in joined(live, SUMMONER)] == ([target_zone_id] if seated else [])


def test_a_blinded_caster_with_only_truesight_places_no_summon() -> None:
    """SRD 5.2 Blinded: "You can't see", and Truesight is sight ("your vision
    pierces through" Darkness and Invisibility): a Blinded caster whose only
    special sense is Truesight sees no space, and the cast is refused before
    anything is spent."""
    handle, live = start([summoner(senses=CombatantSenses(truesight=120))], seed=1)
    _emit(live, ConditionApplied(target_id=SUMMONER, condition="blinded"))
    _cast(handle)
    assert events(live, CastFailed) == [
        CastFailed(actor_id=SUMMONER, spell_id=SD, reason="out_of_range")
    ]
    assert not events(live, CombatantJoined)
    assert live.spell_slots_by_entity[SUMMONER] == {1: 1, 5: 2}


def test_polymorph_refuses_the_spirit_which_has_no_challenge_rating() -> None:
    """SRD 5.2 Draconic Spirit: "CR None". Polymorph's form needs "a Challenge
    Rating equal to or less than the target's (or the target's level if it
    doesn't have a Challenge Rating)"; the spirit has neither, so even a CR 0
    Cat is refused before anything is spent."""
    handle, live = start(
        [summoner(), wizard(initiative=15, zone_id=cell_id(0, 2))],
        seed=1,
        encounter=[foe(zone_id=cell_id(8, 8))],
    )
    _cast(handle)
    monster_turn(handle)  # the spirit's Dodge
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="polymorph",
        target_id=SPIRIT,
        form_id="cat",
    )
    assert events(live, CastFailed) == [
        CastFailed(actor_id="char:wiz", spell_id="polymorph", reason="invalid_form")
    ]
    assert live.spell_slots_by_entity["char:wiz"] == {2: 2, 4: 1}
    assert combatant(live, "char:wiz").action_available
    assert SPIRIT not in live.transforms


# ── The anchor, recasts and ids ──────────────────────────────────────────────


def test_the_cast_anchors_and_the_summon_records_it() -> None:
    handle, live = start([summoner()], seed=1)
    _cast(handle)
    assert live.concentration_chain[SUMMONER] == [ANCHOR]
    assert combatant(live, SUMMONER).concentration_effect_id == "effect:summon-dragon"
    assert live.summons[SPIRIT].anchor == ANCHOR
    assert get_live(handle).summons == {
        SPIRIT: SummonView(
            entity_id=SPIRIT,
            owner_id=SUMMONER,
            spell_id=SD,
            stat_block_slug="draconic-spirit",
            slot_level=5,
        )
    }


def _far_foe() -> EncounterMemberSpec:
    """A template-less foe at 9,9 whose first turn is a Dash toward the
    summoner, to 1,1: no attack, and nothing drawn."""
    return foe(zone_id=cell_id(9, 9))


def test_recasting_summon_dragon_replaces_the_summon() -> None:
    """SRD 5.2: "You lose Concentration on an effect the moment you start
    casting a spell that requires Concentration." The recast's anchor drops
    the first cast's concentration, which dismisses the first spirit, before
    the second joins. The first spirit still stood at 1,0 when the second
    cast was checked, so the second takes 0,1."""
    handle, live = start([summoner()], seed=1, encounter=[_far_foe()])
    _cast(handle)
    act(handle, SPIRIT, intent_type="pass")
    monster_turn(handle)
    assert live.current_actor_id == SUMMONER
    first = len(live.event_log)
    _cast(handle)
    second = "summon:char:summoner:draconic-spirit:2"
    stream = [
        (type(e).__name__, getattr(e, "entity_id", None))
        for e in live.event_log[first:]
        if isinstance(e, (ConcentrationDropped, CombatantLeft, CombatantJoined))
    ]
    assert stream == [
        ("ConcentrationDropped", None),
        ("CombatantLeft", SPIRIT),
        ("CombatantJoined", second),
    ]
    assert [e.reason for e in events(live, CombatantLeft)] == ["concentration_drop"]
    assert roster(live) == [SUMMONER, second, "mon:foe"]
    assert list(live.summons) == [second]
    assert live.actor_zone[second] == cell_id(0, 1)
    assert live.concentration_chain[SUMMONER] == [ANCHOR]
    assert live.current_actor_id == second


def test_resummoning_after_zero_hp_gets_a_fresh_id() -> None:
    """A spirit that dropped to 0 Hit Points leaves its caster concentrating
    (the SRD is silent); the recast ends that concentration, anchors anew and
    seats a spirit with the next id, never the first one's."""
    handle, live = start([summoner()], seed=1, encounter=[_far_foe()])
    _cast(handle)
    act(handle, SPIRIT, intent_type="pass")
    _emit(
        live, DamageApplied(target_id=SPIRIT, amount=50, damage_type="piercing", is_overkill=False)
    )
    assert [(e.entity_id, e.reason) for e in events(live, CombatantLeft)] == [(SPIRIT, "zero_hp")]
    assert live.concentration_chain[SUMMONER] == [ANCHOR]
    monster_turn(handle)
    _cast(handle)
    second = "summon:char:summoner:draconic-spirit:2"
    assert [e.entity_id for e in joined(live, SUMMONER)] == [SPIRIT, second]
    assert len(events(live, CombatantLeft)) == 1
    assert roster(live) == [SUMMONER, second, "mon:foe"]
    assert live.actor_zone[second] == cell_id(1, 0)
    assert live.concentration_chain[SUMMONER] == [ANCHOR]
    assert live.summon_counts == {SUMMONER: 2}


def test_the_cast_draws_nothing() -> None:
    handle, live = start([summoner()], seed=1)
    state = live.rng.getstate()
    _cast(handle)
    assert live.rng.getstate() == state
    assert len(joined(live, SUMMONER)) == 1
