"""Knocking out a creature instead of dropping it.

SRD 5.2 Rules Glossary, "Knocking Out a Creature":

    "When you would reduce a creature to 0 Hit Points with a melee attack, you
    can instead reduce the creature to 1 Hit Point. The creature then has the
    Unconscious condition and starts a Short Rest.

    The creature remains Unconscious until it regains any Hit Points or until
    someone uses an action to administer first aid to it, which requires a
    successful DC 10 Wisdom (Medicine) check."

SRD 5.2 Unconscious: "You have the Incapacitated and Prone conditions ...
When this condition ends, you remain Prone. ... Attack rolls against you have
Advantage. ... Any attack roll that hits you is a Critical Hit if the attacker
is within 5 feet of you."

A character's ``attack`` intent chooses it with ``PlayerIntent.knock_out``.
Every melee hit of that intent that would reduce a creature to 0 Hit Points
leaves it at 1 Hit Point instead, emits ``KnockedOut`` and applies
Unconscious. The creature is then out of the fight: no foe picks it, no host
may name it as a monster's target, and it counts with the dead when the
combat's end reason is derived. Any healing wakes it. A swing that cannot be
a melee attack is refused with ``knock_out_not_melee`` before anything is
spent. First aid and the Short Rest are a host's to adjudicate.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest
from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

from dnd5e_engine import CombatHandle, KnockOutRecord, end_combat, get_live
from dnd5e_engine.events import (
    AttackRolled,
    CombatantLeft,
    ConditionApplied,
    ConditionRemoved,
    DamageApplied,
    Death,
    DeathSaveRolled,
    HealingApplied,
    IntentSubmitted,
    KnockedOut,
    SaveRolled,
    Unconscious,
)
from dnd5e_engine.orchestrator import (
    IntentRejectedError,
    _current_actor,
    _LiveCombat,
    _select_monster_targets,
    advance_monster_turn,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.testing import rng_factory
from tests.c21_support import (
    act,
    anchor_effect,
    cleric,
    combatant,
    events,
    foe,
    monster_turn,
    pc,
    seat_summon,
    start,
)


class _D20Shows10(random.Random):
    """Every d20 shows 10, so no attack is a natural 20 and AC 1 is always
    hit; every other die draws as seeded."""

    def randint(self, a: int, b: int) -> int:
        return 10 if (a, b) == (1, 20) else super().randint(a, b)


class _D20Shows20(random.Random):
    def randint(self, a: int, b: int) -> int:
        return 20 if (a, b) == (1, 20) else super().randint(a, b)


def _scripted(party: list[Any], encounter: list[Any], *, seed: int = 1) -> Any:
    with rng_factory(_D20Shows10):
        return start(party, seed=seed, encounter=encounter)


def _frail(entity_id: str = "mon:foe", **fields: Any) -> Any:
    """A template-less foe at 1 Hit Point (of 1, so it never flees)."""
    return foe(entity_id=entity_id, **({"hp_current": 1, "hp_max": 1} | fields))


def _refused(handle: CombatHandle, actor_id: str, **intent: Any) -> str:
    with pytest.raises(IntentRejectedError) as excinfo:
        act(handle, actor_id, **intent)
    return excinfo.value.reason


def _assert_knocked_out(live: _LiveCombat, target_id: str, attacker_id: str) -> None:
    log = live.event_log
    [ko_at] = [i for i, e in enumerate(log) if isinstance(e, KnockedOut)]
    damage, knocked, condition = log[ko_at - 1], log[ko_at], log[ko_at + 1]
    assert isinstance(damage, DamageApplied)
    assert (damage.target_id, damage.knock_out) == (target_id, True)
    assert knocked == KnockedOut(target_id=target_id, attacker_id=attacker_id)
    assert condition == ConditionApplied(target_id=target_id, condition="unconscious")
    assert events(live, Death) == []
    assert live.tracked_hp[target_id] == 1
    assert combatant(live, target_id).hp_current == 1
    assert live.knocked_out_ids == {target_id}
    assert "unconscious" in {c.condition for c in combatant(live, target_id).conditions}


# ── A pulled blow ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("weapon_id", "foe_cell"),
    [
        ("longsword", cell_id(1, 0)),
        ("unarmed-strike", cell_id(1, 0)),
        ("dagger", cell_id(1, 0)),  # Thrown, but swung within reach
    ],
)
def test_a_melee_hit_that_would_drop_a_foe_knocks_it_out(weapon_id: str, foe_cell: str) -> None:
    handle, live = _scripted([pc()], [_frail(zone_id=foe_cell)])
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id=weapon_id,
        target_id="mon:foe",
        knock_out=True,
    )
    _assert_knocked_out(live, "mon:foe", "char:hero")
    assert get_live(handle).knocked_out_ids == {"mon:foe"}


def test_a_summons_commanded_rend_knocks_out() -> None:
    with rng_factory(_D20Shows10):
        handle, live = start(
            [pc()], seed=1, encounter=[_frail()], active_effects=[anchor_effect("char:hero")]
        )
    spirit = seat_summon(live, "char:hero", zone_id=cell_id(0, 1))
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == spirit
    act(
        handle,
        spirit,
        intent_type="attack",
        stat_block_action_id="rend",
        target_id="mon:foe",
        knock_out=True,
    )
    _assert_knocked_out(live, "mon:foe", spirit)


@pytest.mark.parametrize(
    ("weapon_id", "foe_cell"),
    [
        ("shortbow", cell_id(1, 0)),  # a ranged weapon, even at 5 feet
        ("dagger", cell_id(3, 0)),  # Thrown beyond its 5-foot reach
    ],
)
def test_a_swing_that_is_not_a_melee_attack_is_refused_with_nothing_spent(
    weapon_id: str, foe_cell: str
) -> None:
    handle, live = _scripted([pc()], [_frail(zone_id=foe_cell)])
    before = (len(live.event_log), live.rng.getstate(), combatant(live).model_dump())
    reason = _refused(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id=weapon_id,
        target_id="mon:foe",
        knock_out=True,
    )
    assert reason == "knock_out_not_melee"
    assert (len(live.event_log), live.rng.getstate(), combatant(live).model_dump()) == before
    assert events(live, IntentSubmitted) == []


def test_the_same_swing_without_the_choice_is_accepted() -> None:
    handle, live = _scripted([pc()], [_frail(zone_id=cell_id(3, 0))])
    act(handle, "char:hero", intent_type="attack", weapon_id="dagger", target_id="mon:foe")
    assert [d.target_id for d in events(live, Death)] == ["mon:foe"]


def test_a_hit_that_does_not_drop_the_target_only_carries_the_flag() -> None:
    logs = []
    for knock_out in (False, True):
        handle, live = start([pc()], seed=7)
        act(
            handle,
            "char:hero",
            intent_type="attack",
            weapon_id="longsword",
            target_id="mon:foe",
            knock_out=knock_out,
        )
        logs.append([e.model_dump() for e in live.event_log])
        assert live.knocked_out_ids == set()
    plain, pulled = logs
    damage = [i for i, e in enumerate(pulled) if e["type"] == "damage_applied"]
    assert damage
    for i in damage:
        assert (plain[i]["knock_out"], pulled[i]["knock_out"]) == (False, True)
        pulled[i]["knock_out"] = False
    assert pulled == plain


def test_a_cleave_follow_up_rides_the_choice() -> None:
    handle, live = _scripted(
        [pc()],
        [
            foe(entity_id="mon:a", zone_id=cell_id(0, 1)),
            _frail("mon:b", zone_id=cell_id(1, 1), initiative=2),
        ],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="greataxe",
        target_id="mon:a",
        knock_out=True,
    )
    by_target = {e.target_id: e for e in events(live, DamageApplied)}
    assert by_target["mon:b"].source_id == "mastery:cleave"
    assert all(e.knock_out for e in by_target.values())
    _assert_knocked_out(live, "mon:b", "char:hero")


def test_sneak_attack_rides_the_choice() -> None:
    """An ally within 5 feet of the target gives the rogue's dagger its Sneak
    Attack; the extra dice are part of the same pulled blow."""
    handle, live = _scripted(
        [
            pc(class_slug="rogue", character_level=1, dexterity=16),
            pc("char:ally", initiative=19, zone_id=cell_id(2, 0)),
        ],
        [_frail()],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="dagger",
        target_id="mon:foe",
        knock_out=True,
    )
    assert combatant(live).sneak_attack_spent_this_turn
    _assert_knocked_out(live, "mon:foe", "char:hero")


def test_an_opportunity_attack_never_pulls_its_blow() -> None:
    """The hero knocks out one foe; its ally then walks away from the hero and
    the hero's opportunity attack kills it."""
    handle, live = _scripted(
        [pc()],
        [_frail("mon:a"), _frail("mon:b", zone_id=cell_id(0, 1), initiative=10)],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:a",
        knock_out=True,
    )
    assert _current_actor(live).entity_id == "mon:b"
    act(handle, "mon:b", intent_type="move", target_zone_id=cell_id(0, 3))
    [aoo] = [e for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert (aoo.attacker_id, aoo.target_id) == ("char:hero", "mon:b")
    killing = [e for e in events(live, DamageApplied) if e.target_id == "mon:b"]
    assert [e.knock_out for e in killing] == [False]
    assert [d.target_id for d in events(live, Death)] == ["mon:b"]
    assert live.knocked_out_ids == {"mon:a"}


# ── Out of the fight ─────────────────────────────────────────────────────────


def test_a_knocked_out_character_is_out_of_the_foes_pool_and_only_passes() -> None:
    """The hero knocks out a party member with the lowest Hit Points. On its
    own turn it makes no death save and can only pass; the foe then attacks
    the hero, and the host may not name the knocked-out one."""
    handle, live = _scripted(
        [
            pc(),
            pc("char:weak", initiative=19, hp_current=1, hp_max=30, zone_id=cell_id(0, 1)),
        ],
        [foe()],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="char:weak",
        knock_out=True,
    )
    _assert_knocked_out(live, "char:weak", "char:hero")
    assert events(live, Unconscious) == []
    assert _current_actor(live).entity_id == "char:weak"
    assert events(live, DeathSaveRolled) == []
    reason = _refused(
        handle, "char:weak", intent_type="attack", weapon_id="longsword", target_id="mon:foe"
    )
    assert reason == "actor_incapacitated"
    act(handle, "char:weak", intent_type="pass")
    foe_now = _current_actor(live)
    assert foe_now.entity_id == "mon:foe"
    assert [c.entity_id for c in _select_monster_targets(live, foe_now)] == ["char:hero"]
    with pytest.raises(IntentRejectedError) as excinfo:
        asyncio.run(advance_monster_turn(handle, target_id="char:weak"))
    assert excinfo.value.reason == "target_invalid"
    monster_turn(handle)
    [foe_attack] = [e for e in events(live, AttackRolled) if e.attacker_id == "mon:foe"]
    assert foe_attack.target_id == "char:hero"


def test_with_every_foe_knocked_out_the_fight_is_won() -> None:
    """SRD 5.2 Experience Points: "XP is awarded for defeating the monster in
    combat or otherwise neutralizing it." A foe still knocked out when the
    fight ends is worth its XP as a dead one is."""
    handle, _ = _scripted(
        [pc(), pc("char:two", initiative=19, zone_id=cell_id(1, 1))],
        [
            _frail("mon:a", xp_value=100),
            _frail("mon:b", zone_id=cell_id(2, 1), initiative=2, xp_value=50),
        ],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:a",
        knock_out=True,
    )
    act(
        handle,
        "char:two",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:b",
        knock_out=True,
    )
    assert get_live(handle).knocked_out_ids == {"mon:a", "mon:b"}
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.ended_reason == "victory"
    assert outcome.deaths == []
    assert outcome.knock_outs == [
        KnockOutRecord(target_id="mon:a", target_kind="monster", attacker_id="char:hero"),
        KnockOutRecord(target_id="mon:b", target_kind="monster", attacker_id="char:two"),
    ]
    assert outcome.xp_awarded == {"char:hero": 75, "char:two": 75}


def test_a_knocked_out_party_counts_as_out_for_the_end_reason() -> None:
    handle, live = _scripted(
        [pc(), pc("char:weak", initiative=19, hp_current=1, zone_id=cell_id(0, 1))],
        [foe()],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="char:weak",
        knock_out=True,
    )
    live.dead_ids.add("char:hero")
    assert asyncio.run(end_combat(handle)).outcome.ended_reason == "defeat_tpk"


# ── Waking ───────────────────────────────────────────────────────────────────


def test_healing_wakes_a_knocked_out_creature_prone() -> None:
    handle, live = _scripted(
        [
            pc(),
            cleric(initiative=19, zone_id=cell_id(2, 0), spells_known=["cure-wounds"]),
        ],
        [_frail(hp_max=20)],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:foe",
        knock_out=True,
    )
    first = len(live.event_log)
    act(
        handle,
        "char:cleric",
        intent_type="cast_spell",
        spell_id="cure-wounds",
        target_id="mon:foe",
        slot_level=1,
    )
    after = live.event_log[first:]
    [heal_at] = [i for i, e in enumerate(after) if isinstance(e, HealingApplied)]
    assert after[heal_at + 1 : heal_at + 3] == [
        ConditionRemoved(target_id="mon:foe", condition="unconscious"),
        ConditionApplied(target_id="mon:foe", condition="prone"),
    ]
    assert live.knocked_out_ids == set()
    names = {c.condition for c in combatant(live, "mon:foe").conditions}
    assert "unconscious" not in names
    assert "prone" in names
    assert asyncio.run(end_combat(handle)).outcome.knock_outs == []


def test_regeneration_at_turn_start_wakes_a_knocked_out_troll() -> None:
    handle, live = _scripted([pc()], [foe(monster_template_slug="troll", hp_current=1, hp_max=94)])
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:foe",
        knock_out=True,
    )
    assert live.knocked_out_ids == {"mon:foe"}
    first = len(live.event_log)
    monster_turn(handle)
    after = live.event_log[first:]
    [heal_at] = [i for i, e in enumerate(after) if isinstance(e, HealingApplied)]
    assert after[heal_at + 1] == ConditionRemoved(target_id="mon:foe", condition="unconscious")
    assert live.knocked_out_ids == set()


# ── Hit again ────────────────────────────────────────────────────────────────


def test_a_hit_within_5_feet_is_a_critical_hit_that_kills_a_knocked_out_monster() -> None:
    handle, live = _scripted([pc(class_slug="fighter", character_level=5)], [_frail()])
    for knock_out in (True, False):
        act(
            handle,
            "char:hero",
            intent_type="attack",
            weapon_id="longsword",
            target_id="mon:foe",
            knock_out=knock_out,
        )
    first, second = events(live, AttackRolled)
    assert (first.natural, first.is_crit) == (10, False)
    assert (second.natural, second.is_crit) == (10, True)
    assert [(d.target_id, d.reason) for d in events(live, Death)] == [("mon:foe", "damage")]
    assert live.knocked_out_ids == set()
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.knock_outs == []
    assert [d.killer_id for d in outcome.deaths] == ["char:hero"]


def test_a_second_pulled_blow_knocks_it_out_again() -> None:
    handle, live = _scripted([pc(class_slug="fighter", character_level=5)], [_frail()])
    for _ in range(2):
        act(
            handle,
            "char:hero",
            intent_type="attack",
            weapon_id="longsword",
            target_id="mon:foe",
            knock_out=True,
        )
    assert [e.target_id for e in events(live, KnockedOut)] == ["mon:foe", "mon:foe"]
    assert events(live, Death) == []
    assert live.knocked_out_ids == {"mon:foe"}
    assert len(asyncio.run(end_combat(handle)).outcome.knock_outs) == 1


def test_a_knocked_out_character_hit_again_starts_dying() -> None:
    handle, live = _scripted(
        [
            pc(class_slug="fighter", character_level=5),
            pc("char:pal", initiative=19, hp_current=1, zone_id=cell_id(0, 1)),
        ],
        [foe()],
    )
    for knock_out in (True, False):
        act(
            handle,
            "char:hero",
            intent_type="attack",
            weapon_id="longsword",
            target_id="char:pal",
            knock_out=knock_out,
        )
    assert [e.is_crit for e in events(live, AttackRolled)] == [False, True]
    assert events(live, Unconscious) == [Unconscious(target_id="char:pal")]
    assert events(live, Death) == []
    assert live.tracked_hp["char:pal"] == 0
    assert live.knocked_out_ids == set()
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == "char:pal"
    assert [e.target_id for e in events(live, DeathSaveRolled)] == ["char:pal"]


# ── Never knocked out ────────────────────────────────────────────────────────


def test_a_summon_is_never_knocked_out() -> None:
    """The spirit's AC 19 takes a natural 20 to hit."""
    with rng_factory(_D20Shows20):
        handle, live = start([pc()], seed=1, active_effects=[anchor_effect("char:hero")])
    spirit = seat_summon(live, "char:hero", zone_id=cell_id(0, 1), hp=1)
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id=spirit,
        knock_out=True,
    )
    assert events(live, KnockedOut) == []
    [left] = events(live, CombatantLeft)
    assert (left.entity_id, left.reason) == (spirit, "zero_hp")
    assert live.knocked_out_ids == set()


def test_a_spell_attack_ignores_the_choice_and_kills() -> None:
    """Knocking out with a melee spell attack is out of scope: Shocking Grasp
    with ``knock_out=True`` is accepted and drops the foe as before."""
    handle, live = _scripted(
        [pc(class_slug="wizard", character_level=1, spells_known=["shocking-grasp"])],
        [_frail()],
    )
    act(
        handle,
        "char:hero",
        intent_type="cast_spell",
        spell_id="shocking-grasp",
        target_id="mon:foe",
        knock_out=True,
    )
    assert events(live, KnockedOut) == []
    assert [e.knock_out for e in events(live, DamageApplied)] == [False]
    assert [d.target_id for d in events(live, Death)] == ["mon:foe"]


def test_damage_to_a_creature_already_at_0_hp_is_not_a_knock_out() -> None:
    """Only a blow that "would reduce a creature to 0 Hit Points" can be
    pulled: a dying character takes its death save failure as before."""
    handle, live = _scripted(
        [pc(), pc("char:down", initiative=19, hp_current=0, zone_id=cell_id(0, 1))],
        [foe()],
    )
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="char:down",
        knock_out=True,
    )
    assert events(live, KnockedOut) == []
    assert live.knocked_out_ids == set()
    assert live.tracked_hp["char:down"] == 0
    assert combatant(live, "char:down").death_saves


def test_a_creature_immune_to_unconscious_drops_to_1_hp_and_fights_on() -> None:
    """SRD 5.2 Immunity: "If you have Immunity to a damage type or a
    condition, it doesn't affect you in any way." The pulled blow still
    reduces the creature "to 1 Hit Point" instead of 0, but the Unconscious
    condition that follows never lands, so it is not knocked out: no
    ``KnockedOut``, still a legal target, and it acts on its own turn."""
    handle, live = _scripted([pc()], [_frail(condition_immunities=["unconscious"])])
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:foe",
        knock_out=True,
    )
    [damage] = events(live, DamageApplied)
    assert damage.knock_out
    assert live.tracked_hp["mon:foe"] == 1
    assert combatant(live, "mon:foe").hp_current == 1
    assert events(live, KnockedOut) == []
    assert events(live, ConditionApplied) == []
    assert events(live, Death) == []
    assert live.knocked_out_ids == set()
    assert "unconscious" not in {c.condition for c in combatant(live, "mon:foe").conditions}
    monster_turn(handle)
    [foe_attack] = [e for e in events(live, AttackRolled) if e.attacker_id == "mon:foe"]
    assert foe_attack.target_id == "char:hero"
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.knock_outs == []
    assert outcome.deaths == []


def test_undead_fortitude_still_saves_a_summon_a_pulled_blow_cannot_knock_out() -> None:
    """SRD 5.2 Undead Fortitude: "If damage reduces the [monster] to 0 Hit
    Points, it makes a Constitution saving throw (DC 5 plus the damage taken)
    ... On a successful save, the [monster] drops to 1 Hit Point instead." A
    pulled blow skips that save only because it leaves the creature at 1 Hit
    Point. A summon "disappears when it drops to 0 Hit Points" whatever the
    attacker chose, so the blow does reduce it to 0 and the save is rolled."""
    with rng_factory(_D20Shows10):
        handle, live = start([pc()], seed=1, active_effects=[anchor_effect("char:hero")])
    spirit = seat_summon(live, "char:hero", zone_id=cell_id(0, 1), hp=1)
    body = combatant(live, spirit)
    body.ac = 1
    body.constitution = 40
    body.save_proficiencies = []
    body.trait_mechanics = [MonsterTraitMechanic.UNDEAD_FORTITUDE]
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="longsword",
        target_id=spirit,
        knock_out=True,
    )
    [save] = [e for e in events(live, SaveRolled) if e.target_id == spirit]
    assert (save.ability, save.succeeded) == ("con", True)
    assert events(live, KnockedOut) == []
    assert events(live, CombatantLeft) == []
    assert live.tracked_hp[spirit] == 1
