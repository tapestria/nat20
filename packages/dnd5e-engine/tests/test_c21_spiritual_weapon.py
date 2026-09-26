"""Spiritual Weapon (SRD 5.2), a caster-owned construct (C21): the cast places
the force and makes its immediate melee spell attack; a Bonus Action on a later
turn moves it and repeats the attack; it ends with its concentration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CombatHandle, get_live
from dnd5e_engine.activities.build_context import spell_attack_magnitudes
from dnd5e_engine.activities.conjuration import CONSTRUCTS, construct_attack_activity
from dnd5e_engine.events import (
    AttackFailed,
    AttackRolled,
    CastFailed,
    ConcentrationDropped,
    ConditionRemoved,
    DamageApplied,
    EffectExpired,
    SpellCast,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _get_live,
    _LiveCombat,
    _monster_cast_candidate,
    start_combat,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import GridScene, PartyMemberSpec
from dnd5e_engine.views import ConstructView
from tests.c21_support import act, cleric, combatant, events, foe, monster_turn, pc, start

LOADER = BundledAssetLoader()
SW = "spiritual-weapon"
FORCE_ID = "construct:char:cleric:spiritual-weapon"
ANCHOR = ("char:cleric", "effect:spiritual-weapon", "cast:spiritual-weapon:char:cleric")


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _classless_cleric(**fields: Any) -> PartyMemberSpec:
    """S03's caster: level 5 with no class, so no spellcasting ability."""
    base: dict[str, Any] = {"character_level": 5, "spells_known": [SW], "spell_slots": {2: 1}}
    return pc("char:cleric", **(base | fields))


def _cast(handle: CombatHandle, **intent: Any) -> None:
    act(handle, "char:cleric", intent_type="cast_spell", spell_id=SW, **intent)


def _repeat(handle: CombatHandle, **intent: Any) -> None:
    act(handle, "char:cleric", intent_type="attack", spell_id=SW, target_id="mon:foe", **intent)


def _hits(live: _LiveCombat) -> list[tuple[str, int, int, int]]:
    return [
        (e.attacker_id, e.natural, e.modifier, e.roll_total) for e in events(live, AttackRolled)
    ]


def _damage(live: _LiveCombat) -> list[tuple[str, int, str]]:
    return [(e.target_id, e.amount, e.damage_type) for e in events(live, DamageApplied)]


def _parked_force(seed: int) -> tuple[CombatHandle, _LiveCombat]:
    """An AC 30 WIS-16 cleric parks the force at 5,0 (25 ft from her, 20 ft
    from the foe at 1,0) with no target, so the cast attacks nothing; she
    passes and the foe's swing misses. It is her second turn."""
    handle, live = start([cleric(ac=30)], seed=seed)
    _cast(handle, target_zone_id=cell_id(5, 0))
    act(handle, "char:cleric", intent_type="pass")
    monster_turn(handle)
    assert live.current_actor_id == "char:cleric"
    assert not events(live, DamageApplied)
    return handle, live


def test_construct_attack_activity_is_a_flat_melee_spell_attack() -> None:
    """A level-4 slot: 1d8 + 2 (two levels above 2) = 3d8, plus the modifier;
    the part's own upcast scaling is zeroed so the dice are not added twice."""
    activity = construct_attack_activity(
        CONSTRUCTS[SW], slot_level=4, attack_bonus=6, damage_bonus=3
    )
    assert (activity.attack.flat, activity.attack.bonus) == (True, "6")
    assert (activity.attack.type.value, activity.attack.type.classification) == ("melee", "spell")
    [part] = activity.damage.parts
    assert (part.number, part.denomination, part.bonus, part.types) == (3, 8, "3", ["force"])
    assert part.scaling.number == 0
    assert activity.damage.include_base is False


@pytest.mark.parametrize(
    ("member", "ability", "magnitudes"),
    [
        ({"character_level": 5}, None, (3, 0)),
        ({"character_level": 5, "class_slug": "cleric", "wisdom": 16}, "wis", (6, 3)),
        ({"character_level": 5, "wisdom": 16, "attack_bonus": 9}, "wis", (9, 3)),
    ],
)
def test_spell_attack_magnitudes_follow_the_casters_own_spell_attack(
    member: dict[str, Any], ability: str | None, magnitudes: tuple[int, int]
) -> None:
    """A classless caster keeps the legacy fallbacks (PB 3 + 0; modifier 0); a
    WIS 16 caster gets PB 3 + 3 and +3; a pinned to-hit wins the to-hit."""
    _, live = start([pc(**member)], seed=1)
    assert spell_attack_magnitudes(combatant(live), ability) == magnitudes


def test_a_monster_spell_attack_uses_its_stat_block() -> None:
    """The Priest (WIS 16, PB 2): +5 to hit, +3 damage."""
    _, live = start(
        [pc()], seed=1, encounter=[foe(entity_id="mon:priest", monster_template_slug="priest")]
    )
    assert spell_attack_magnitudes(combatant(live, "mon:priest"), "wis") == (5, 3)


def test_the_classless_cleric_attacks_at_plus_3_for_1d8() -> None:
    """S03. The cast is a Bonus Action and draws nothing itself. Seed 9: the
    immediate attack rolls d20 15 + 3 (PB, no spellcasting ability) = 18 against
    AC 1, then 1d8 = 6 + 0 Force."""
    handle, live = start([_classless_cleric()], seed=9)
    _cast(handle, target_id="mon:foe")
    assert _hits(live) == [("char:cleric", 15, 3, 18)]
    assert _damage(live) == [("mon:foe", 6, "force")]
    assert live.current_actor_id == "char:cleric"
    assert combatant(live, "char:cleric").bonus_action_available is False


def test_a_wis_16_cleric_attacks_at_plus_6_for_1d8_plus_3() -> None:
    """SRD 5.2: "Force damage equal to 1d8 plus your spellcasting ability
    modifier." A Cleric 5 with WIS 16: PB 3 + WIS 3. Seed 9: 15 + 6 = 21;
    6 + 3 = 9."""
    handle, live = start([cleric()], seed=9)
    _cast(handle, target_id="mon:foe")
    assert _hits(live) == [("char:cleric", 15, 6, 21)]
    assert _damage(live) == [("mon:foe", 9, "force")]


def test_a_level_3_slot_adds_1d8() -> None:
    """SRD 5.2: "The damage increases by 1d8 for every slot level above 2."
    Seed 9: d8s 6 and 5, + 3 = 14 (2d8, not 3d8)."""
    handle, live = start([cleric(spell_slots={3: 1})], seed=9)
    _cast(handle, target_id="mon:foe", slot_level=3)
    assert _damage(live) == [("mon:foe", 14, "force")]


def test_a_running_bless_still_applies_to_the_immediate_attack() -> None:
    """The concentration hand-off runs after the resolution (the recorded D1
    timing edge): the cleric's own Bless still adds its d4 to the force's
    immediate attack, then ends. Seed 3: the foe's d20 8 misses AC 30; the
    attack rolls 19 + 6 and Bless's d4 2 = 27; 1d8 6 + 3 = 9 Force."""
    handle, live = start([cleric(ac=30)], seed=3)
    act(handle, "char:cleric", intent_type="cast_spell", spell_id="bless", target_id="char:cleric")
    monster_turn(handle)
    _cast(handle, target_id="mon:foe")
    assert _hits(live)[-1] == ("char:cleric", 19, 6, 27)
    assert _damage(live) == [("mon:foe", 9, "force")]
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:blessed", "concentration_drop")
    ]
    assert live.concentration_chain["char:cleric"] == [ANCHOR]


def test_the_force_waits_in_the_targets_space_and_is_no_combatant() -> None:
    """The default space is the named target's. The force has no initiative
    slot and no zone of its own; hosts read it through ``LiveCombatView``."""
    handle, live = start([cleric()], seed=9)
    _cast(handle, target_id="mon:foe")
    construct = live.constructs[FORCE_ID]
    assert (construct.owner_id, construct.cell, construct.slot_level) == (
        "char:cleric",
        cell_id(1, 0),
        2,
    )
    assert (construct.anchor, construct.cast_round) == (ANCHOR, 1)
    assert live.concentration_chain["char:cleric"] == [ANCHOR]
    assert [c.entity_id for c in live.initiative] == ["char:cleric", "mon:foe"]
    assert set(live.actor_zone) == {"char:cleric", "mon:foe"}
    assert get_live(handle).constructs == {
        FORCE_ID: ConstructView(
            construct_id=FORCE_ID,
            owner_id="char:cleric",
            spell_id=SW,
            zone_id=cell_id(1, 0),
            slot_level=2,
        )
    }


def test_a_cast_without_a_target_makes_a_force_and_no_attack() -> None:
    """With no target and no space named, the force appears in the caster's
    space and waits."""
    handle, live = start([cleric()], seed=9)
    _cast(handle)
    assert live.constructs[FORCE_ID].cell == cell_id(0, 0)
    assert not events(live, AttackRolled)


@pytest.mark.parametrize(
    ("zone", "target"),
    [
        (cell_id(40, 0), None),
        (cell_id(4, 4), "mon:foe"),
    ],
)
def test_a_force_that_cannot_be_placed_is_refused_before_spending(
    zone: str, target: str | None
) -> None:
    """A space off the map cannot be measured; a force 20 ft from its named
    target cannot make the immediate attack "within 5 feet of the force"."""
    handle, live = start([cleric()], seed=9)
    _cast(handle, target_zone_id=zone, target_id=target)
    assert [(e.spell_id, e.reason) for e in events(live, CastFailed)] == [(SW, "out_of_range")]
    assert live.spell_slots_by_entity["char:cleric"][2] == 2
    assert combatant(live, "char:cleric").bonus_action_available
    assert not live.constructs


def _wide_combat(seed: int, foe_col: int = 1) -> tuple[CombatHandle, _LiveCombat]:
    """A 20x2 grid: the cleric at 0,0, the foe at ``foe_col``,0."""
    result = asyncio.run(
        start_combat(
            session_id=f"c21a-wide-{seed}",
            party=[cleric()],
            encounter=[foe(zone_id=cell_id(foe_col, 0))],
            grid_scene=GridScene(width=20, height=2),
            rng_seed=seed,
        )
    )
    return result.handle, _get_live(result.handle)


@pytest.mark.parametrize(("col", "placed"), [(12, True), (13, False)])
def test_the_force_appears_within_the_spells_range(col: int, placed: bool) -> None:
    """Range 60 feet: 12 squares away is in range, 13 (65 ft) is not."""
    handle, live = _wide_combat(9)
    _cast(handle, target_zone_id=cell_id(col, 0))
    assert bool(live.constructs) is placed
    assert bool(events(live, CastFailed)) is not placed


def test_the_target_is_measured_from_the_force() -> None:
    """SRD 5.2: "The force appears within range in a space of your choice, and
    you can immediately make one melee spell attack against one creature within
    5 feet of the force." A force placed 60 feet away reaches a foe 65 feet
    away. Seed 9: d20 15 + 6 = 21; 1d8 6 + 3 = 9 Force."""
    handle, live = _wide_combat(9, foe_col=13)
    _cast(handle, target_id="mon:foe", target_zone_id=cell_id(12, 0))
    assert events(live, CastFailed) == []
    assert live.constructs[FORCE_ID].cell == cell_id(12, 0)
    assert _hits(live) == [("char:cleric", 15, 6, 21)]
    assert _damage(live) == [("mon:foe", 9, "force")]


def test_the_force_cannot_repeat_on_the_cast_turn() -> None:
    """SRD 5.2: "As a Bonus Action on your later turns". The cast made this
    turn's attack; the repeat is refused before anything is spent."""
    handle, live = start([cleric()], seed=9)
    _cast(handle, target_id="mon:foe")
    _repeat(handle)
    assert [e.reason for e in events(live, AttackFailed)] == ["action_unavailable"]
    assert combatant(live, "char:cleric").action_available
    assert len(events(live, AttackRolled)) == 1


@pytest.mark.parametrize("spell_id", ["fire-bolt", SW])
def test_an_attack_naming_no_live_force_ignores_its_spell_id(spell_id: str) -> None:
    """``spell_id`` on an ``attack`` names the force only while its caster owns
    one; otherwise the field is not read and the attack is an ordinary one: a
    Mace swing on the Attack action. Seed 9: d20 15 + 5 = 20; 1d6 5 + STR 2 = 7
    Bludgeoning."""
    handle, live = start([cleric(strength=14)], seed=9)
    act(
        handle,
        "char:cleric",
        intent_type="attack",
        target_id="mon:foe",
        weapon_id="mace",
        spell_id=spell_id,
    )
    assert events(live, AttackFailed) == []
    assert _hits(live) == [("char:cleric", 15, 5, 20)]
    assert _damage(live) == [("mon:foe", 7, "bludgeoning")]
    cleric_now = combatant(live, "char:cleric")
    assert (cleric_now.action_available, cleric_now.bonus_action_available) == (False, True)


def test_a_repeat_that_also_names_a_weapon_is_refused() -> None:
    """The repeat is the force's attack alone: one naming a weapon as well
    would add a free weapon swing to the Bonus Action. It is refused before
    anything is spent — the force stays put, the Action and the Bonus Action
    stay open — and the repeat alone still works."""
    handle, live = _parked_force(3)
    rolls = len(events(live, AttackRolled))
    _repeat(handle, target_zone_id=cell_id(1, 1), weapon_id="mace")
    assert [e.reason for e in events(live, AttackFailed)] == ["action_unavailable"]
    assert len(events(live, AttackRolled)) == rolls
    assert live.constructs[FORCE_ID].cell == cell_id(5, 0)
    cleric_now = combatant(live, "char:cleric")
    assert (cleric_now.action_available, cleric_now.bonus_action_available) == (True, True)
    _repeat(handle, target_zone_id=cell_id(1, 1))
    assert _damage(live) == [("mon:foe", 6, "force")]


@pytest.mark.parametrize(
    "zone",
    [
        None,  # the force stays at 5,0, 20 ft from the foe: out of its reach
        cell_id(0, 1),  # 25 ft from 5,0: more than the 20-ft move
        cell_id(40, 0),  # off the map
    ],
)
def test_a_repeat_out_of_move_or_reach_is_refused(zone: str | None) -> None:
    handle, live = _parked_force(3)
    _repeat(handle, target_zone_id=zone)
    assert [e.reason for e in events(live, AttackFailed)] == ["out_of_range"]
    assert combatant(live, "char:cleric").bonus_action_available
    assert live.constructs[FORCE_ID].cell == cell_id(5, 0)


def test_the_next_turn_repeat_moves_the_force_and_spends_the_bonus_action() -> None:
    """SRD 5.2: "move the force up to 20 feet and repeat the attack". From 5,0
    to 1,1 is 20 ft, 5 ft from the foe. Seed 3: the foe's d20 8 misses AC 30;
    the repeat rolls 19 + 6 = 25, then 1d8 3 + 3 = 6 Force. The turn stays
    open; a second repeat has no Bonus Action to spend."""
    handle, live = _parked_force(3)
    _repeat(handle, target_zone_id=cell_id(1, 1))
    assert _hits(live)[-1] == ("char:cleric", 19, 6, 25)
    assert _damage(live) == [("mon:foe", 6, "force")]
    assert live.constructs[FORCE_ID].cell == cell_id(1, 1)
    cleric_now = combatant(live, "char:cleric")
    assert (cleric_now.action_available, cleric_now.bonus_action_available) == (True, False)
    assert live.current_actor_id == "char:cleric"
    _repeat(handle)
    assert [e.reason for e in events(live, AttackFailed)] == ["no_action_economy"]


def test_a_repeat_against_an_unknown_target_is_refused() -> None:
    handle, live = _parked_force(3)
    act(handle, "char:cleric", intent_type="attack", spell_id=SW, target_id="mon:nobody")
    assert [e.reason for e in events(live, AttackFailed)] == ["target_invalid"]


def test_the_repeat_ends_the_owners_hide() -> None:
    """SRD 5.2 Hide: the condition ends "immediately after ... you make an
    attack roll"; the force's attack is the cleric's roll."""
    handle, live = _parked_force(3)
    live.hidden_entities.add("char:cleric")
    _repeat(handle, target_zone_id=cell_id(1, 1))
    assert "char:cleric" not in live.hidden_entities
    assert [(e.target_id, e.condition) for e in events(live, ConditionRemoved)] == [
        ("char:cleric", "invisible")
    ]


def test_failed_concentration_save_removes_the_force() -> None:
    """Seed 6: the immediate attack (19 + 6; 2 + 3 = 5); the foe hits AC 10
    with 16 for 1d4 = 3; the cleric's CON save rolls 2 against DC 10 and fails.
    The anchor expires and the force is gone."""
    handle, live = start([cleric()], seed=6)
    _cast(handle, target_id="mon:foe")
    act(handle, "char:cleric", intent_type="pass")
    monster_turn(handle)
    assert [e.effect_name for e in events(live, ConcentrationDropped)] == [
        "effect:spiritual-weapon"
    ]
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "concentration_drop")
    ]
    assert live.constructs == {}
    assert get_live(handle).constructs == {}


def test_recast_replaces_the_force() -> None:
    """A recast drops the old concentration first (ending its force), then
    seats one new force with its own immediate attack: one force, one chain
    entry. Seed 3: the foe's d20 8 misses AC 30 in between."""
    handle, live = start([cleric(ac=30, spell_slots={2: 2})], seed=3)
    _cast(handle, target_id="mon:foe")
    act(handle, "char:cleric", intent_type="pass")
    monster_turn(handle)
    _cast(handle, target_id="mon:foe", target_zone_id=cell_id(2, 0))
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "concentration_drop")
    ]
    assert list(live.constructs) == [FORCE_ID]
    assert (live.constructs[FORCE_ID].cell, live.constructs[FORCE_ID].cast_round) == (
        cell_id(2, 0),
        2,
    )
    assert live.concentration_chain["char:cleric"] == [ANCHOR]
    assert len([e for e in _hits(live) if e[0] == "char:cleric"]) == 2


def test_duration_expiry_removes_the_force() -> None:
    """The anchor carries the spell's 1-minute maximum (10 rounds); at its last
    round the concentration ends with ``duration`` and takes the force along."""
    handle, live = start([cleric()], seed=9)
    _cast(handle, target_id="mon:foe")
    assert live.concentration_rounds_remaining["char:cleric"] == 10
    live.concentration_rounds_remaining["char:cleric"] = 1
    act(handle, "char:cleric", intent_type="pass")
    assert [(e.effect_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:spiritual-weapon", "duration")
    ]
    assert live.constructs == {}


@pytest.mark.parametrize(
    ("seed", "rolls", "damage"),
    [
        (1, [(5, False), (19, True)], [(1, "bludgeoning"), (4, "radiant")]),
        (2, [(2, False), (3, False)], []),
        (9, [(15, True), (5, False)], [(5, "bludgeoning"), (6, "radiant")]),
    ],
)
def test_the_priest_opens_with_its_multiattack(
    seed: int, rolls: list[tuple[int, bool]], damage: list[tuple[int, str]]
) -> None:
    """SRD 5.2 Priest: "The priest makes two attacks, using Mace or Radiant
    Flame in any combination." Its bundled 1/Day Spellcasting entry points at
    Spiritual Weapon where the SRD's says Spirit Guardians (a data slip), and
    no monster casts a construct spell (BACKLOG), so its first turn is that
    Multiattack, pinned roll for roll."""
    handle, live = start(
        [pc(initiative=1, zone_id=cell_id(1, 0))],
        seed=seed,
        encounter=[
            foe(
                entity_id="mon:priest",
                name="Priest",
                initiative=20,
                zone_id=cell_id(0, 0),
                monster_template_slug="priest",
            )
        ],
    )
    monster_turn(handle)
    assert events(live, SpellCast) == []
    assert [(e.attacker_id, e.natural, e.is_hit) for e in events(live, AttackRolled)] == [
        ("mon:priest", *roll) for roll in rolls
    ]
    assert [(e.amount, e.damage_type) for e in events(live, DamageApplied)] == damage
    assert live.constructs == {}


def test_the_cultist_fanatics_spiritual_weapon_is_no_monster_cast() -> None:
    """The SRD 5.2 Cultist Fanatic has "Spiritual Weapon (2/Day)", but monster
    casts of a construct spell are deferred (BACKLOG): its entry is no cast
    candidate, so the AI never picks it."""
    _, live = start(
        [pc()],
        seed=1,
        encounter=[foe(entity_id="mon:fanatic", monster_template_slug="cultist-fanatic")],
    )
    monster = LOADER.get_monster("cultist-fanatic")
    assert monster is not None
    entry = next(a for a in monster.actions if a.slug == SW)
    assert _monster_cast_candidate(live, combatant(live, "mon:fanatic"), entry) is None


def test_a_readied_concentration_spell_stays_its_owners() -> None:
    """The force's immediate attack fires its target's readied Fog Cloud before
    the cast resolves, as every attack drains reactions: the Fog Cloud
    concentrates on the hero, and the cleric holds only its Spiritual Weapon.
    Seed 9: the Fog Cloud draws nothing; d20 15 + 6 misses AC 30."""
    hero = pc(spells_known=["fog-cloud"], spell_slots={1: 1}, ac=30, zone_id=cell_id(0, 1))
    handle, live = start([hero, cleric(initiative=19)], seed=9)
    act(
        handle,
        "char:hero",
        intent_type="ready",
        spell_id="fog-cloud",
        slot_level=1,
        reaction_trigger="hit_by_attack",
    )
    _cast(handle, target_id="char:hero")
    assert {e.spell_id for e in events(live, SpellCast)} == {"fog-cloud", SW}
    assert _hits(live) == [("char:cleric", 15, 6, 21)]
    assert live.concentration_chain["char:cleric"] == [ANCHOR]
    assert live.concentration_chain["char:hero"] == [
        ("char:hero", "effect:fog-cloud", "cast:fog-cloud:char:hero")
    ]
    assert combatant(live).concentration_effect_id == "effect:fog-cloud"
