"""The deaths of a running combat, read from the live view.

SRD 5.2 Monster death: a monster dies the instant it drops to 0 Hit Points;
SRD 5.2 Death Saving Throws: "On your third failure, you die." Every death
the engine records is a ``DeathRecord``; ``get_live(handle).deaths`` lists
them in order while the fight runs, and ``CombatOutcome.deaths`` holds the
same list at its end.

``DeathRecord.killer_id`` is the creature that dealt the killing damage,
whoever's turn it is: an opportunity attack's reactor, a legendary action's
monster, a commanded summon, the caster whose spell's construct struck. It is
``None`` for a death nobody dealt (failed death saves) and for a creature
that killed itself.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from dnd5e_engine import DeathRecord, PlayerIntent, end_combat, get_live
from dnd5e_engine.events import AttackRolled, Death, DeathSaveRolled
from dnd5e_engine.orchestrator import (
    _current_actor,
    _hellish_rebuke_target_invalid,
    advance_monster_turn,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.testing import rng_factory
from tests.c21_support import act, cleric, combatant, events, foe, monster_turn, pc, start


class _D20Shows(random.Random):
    """Every d20 shows ``face``; every other die draws as seeded."""

    face = 10

    def randint(self, a: int, b: int) -> int:
        return self.face if (a, b) == (1, 20) else super().randint(a, b)


class _D20Shows20(_D20Shows):
    face = 20


class _D20Shows1(_D20Shows):
    face = 1


def _record(target_id: str, kind: str, reason: str, killer_id: str | None) -> DeathRecord:
    return DeathRecord(
        target_id=target_id,
        target_kind=kind,  # type: ignore[arg-type]
        location_id="loc:unknown",
        reason=reason,  # type: ignore[arg-type]
        killer_id=killer_id,
    )


def _frail(entity_id: str, **fields: Any) -> Any:
    return foe(entity_id=entity_id, **({"hp_current": 1, "hp_max": 1} | fields))


def test_a_death_mid_fight_is_in_the_view_before_the_fight_ends() -> None:
    with rng_factory(_D20Shows):
        handle, _ = start([pc()], seed=1, encounter=[_frail("mon:foe")])
    assert get_live(handle).deaths == []
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    view = get_live(handle)
    assert not view.ended
    assert view.deaths == [_record("mon:foe", "monster", "damage", "char:hero")]


def test_the_views_list_is_a_copy() -> None:
    with rng_factory(_D20Shows):
        handle, _ = start([pc()], seed=1, encounter=[_frail("mon:foe")])
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    get_live(handle).deaths.clear()
    assert len(get_live(handle).deaths) == 1
    get_live(handle).deaths[0].killer_id = "char:someone-else"
    assert get_live(handle).deaths[0].killer_id == "char:hero"


def test_the_outcome_holds_the_last_views_deaths() -> None:
    with rng_factory(_D20Shows):
        handle, _ = start(
            [pc()], seed=1, encounter=[_frail("mon:a"), _frail("mon:b", initiative=2)]
        )
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:a")
    last = get_live(handle).deaths
    outcome = asyncio.run(end_combat(handle)).outcome
    assert outcome.deaths == last
    assert get_live(handle).deaths == last


def test_the_outcomes_deaths_are_copies() -> None:
    with rng_factory(_D20Shows):
        handle, _ = start([pc()], seed=1, encounter=[_frail("mon:foe")])
    act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    outcome = asyncio.run(end_combat(handle)).outcome
    outcome.deaths[0].killer_id = "char:someone-else"
    outcome.deaths.clear()
    expected = [_record("mon:foe", "monster", "damage", "char:hero")]
    assert get_live(handle).deaths == expected
    final = get_live(handle).final_outcome
    assert final is not None
    assert final.deaths == expected
    final.deaths.clear()
    assert asyncio.run(end_combat(handle)).outcome.deaths == expected


def test_an_opportunity_attack_kill_names_the_reactor() -> None:
    """The foe walks away from the hero on its own turn and the hero's
    opportunity attack kills it."""
    with rng_factory(_D20Shows):
        handle, live = start(
            [pc(initiative=1)], seed=1, encounter=[_frail("mon:foe", initiative=20)]
        )
    assert _current_actor(live).entity_id == "mon:foe"
    act(handle, "mon:foe", intent_type="move", target_zone_id=cell_id(3, 0))
    [aoo] = [e for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert aoo.attacker_id == "char:hero"
    assert get_live(handle).deaths == [_record("mon:foe", "monster", "damage", "char:hero")]


def test_an_opportunity_attack_massive_damage_kill_of_a_character_names_the_reactor() -> None:
    """A 1-Hit-Point character walks away from a foe on its own turn; the
    foe's opportunity attack drops it with damage left over that equals its
    Hit Point maximum (SRD 5.2 Massive Damage)."""
    with rng_factory(_D20Shows20):
        handle, live = start([pc(hp_current=1, hp_max=1)], seed=1, encounter=[foe()])
    act(handle, "char:hero", intent_type="move", target_zone_id=cell_id(0, 3))
    [aoo] = [e for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert aoo.attacker_id == "mon:foe"
    assert get_live(handle).deaths == [_record("char:hero", "character", "instant_kill", "mon:foe")]


def test_hellish_rebuke_answers_the_opportunity_attacker_that_damaged_it() -> None:
    """SRD 5.2 Hellish Rebuke: "Reaction, which you take in response to taking
    damage from a creature ... The creature that damaged you is momentarily
    surrounded by green flames." The hero walks away from one foe on its own
    turn and that foe's opportunity attack hits it: the foe is the creature
    that damaged it, the bystander is not."""
    with rng_factory(_D20Shows20):
        handle, live = start(
            [pc(hp_current=30, hp_max=30)],
            seed=1,
            encounter=[foe(), foe(entity_id="mon:bystander", zone_id=cell_id(9, 9))],
        )
    act(handle, "char:hero", intent_type="move", target_zone_id=cell_id(0, 3))
    [aoo] = [e for e in events(live, AttackRolled) if e.is_opportunity_attack]
    assert (aoo.attacker_id, aoo.is_hit) == ("mon:foe", True)
    hero = combatant(live, "char:hero")
    assert hero.last_damaged_by == "mon:foe"

    def rebuke(target_id: str) -> PlayerIntent:
        return PlayerIntent(
            intent_type="cast_spell", spell_id="hellish-rebuke", target_id=target_id
        )

    assert not _hellish_rebuke_target_invalid(hero, rebuke("mon:foe"))
    assert _hellish_rebuke_target_invalid(hero, rebuke("mon:bystander"))


def test_a_legendary_action_kill_names_the_legendary_creature() -> None:
    """After the hero's turn, the first ally's turn has begun; the dragon's
    legendary action kills the second ally."""
    with rng_factory(_D20Shows20):
        handle, live = start(
            [pc(initiative=25, hp_current=60, hp_max=60)],
            seed=4,
            encounter=[
                foe(
                    entity_id="mon:dragon",
                    monster_template_slug="adult-brass-dragon",
                    hp_current=256,
                    hp_max=256,
                    initiative=10,
                    zone_id=cell_id(3, 0),
                ),
                _frail(
                    "npc:first",
                    entity_type="NPC",
                    side="party",
                    initiative=20,
                    zone_id=cell_id(0, 2),
                ),
                _frail(
                    "npc:second",
                    entity_type="NPC",
                    side="party",
                    initiative=15,
                    zone_id=cell_id(2, 0),
                ),
            ],
        )
    act(handle, "char:hero", intent_type="pass")
    assert _current_actor(live).entity_id == "npc:first"
    asyncio.run(advance_monster_turn(handle, legendary=True, target_id="npc:second"))
    assert [d.target_id for d in events(live, Death)] == ["npc:second"]
    assert get_live(handle).deaths == [_record("npc:second", "npc", "damage", "mon:dragon")]


def test_a_spell_constructs_kill_names_its_caster() -> None:
    """Spiritual Weapon's force is no creature: its attack is the caster's."""
    with rng_factory(_D20Shows):
        handle, _ = start(
            [cleric(spells_known=["spiritual-weapon"], spell_slots={2: 1})],
            seed=1,
            encounter=[_frail("mon:foe")],
        )
    act(
        handle,
        "char:cleric",
        intent_type="cast_spell",
        spell_id="spiritual-weapon",
        target_id="mon:foe",
        slot_level=2,
    )
    assert get_live(handle).deaths == [_record("mon:foe", "monster", "damage", "char:cleric")]


def test_a_creature_that_kills_itself_names_nobody() -> None:
    """A 1-Hit-Point wizard's Fireball, aimed at the foe beside it, catches
    the wizard in its own radius, which dies of Massive Damage; the foe dies
    too, credited to the wizard."""
    with rng_factory(_D20Shows1):
        handle, _ = start(
            [
                pc(
                    "char:wiz",
                    class_slug="wizard",
                    character_level=5,
                    hp_current=1,
                    hp_max=1,
                    spells_known=["fireball"],
                    spell_slots={3: 1},
                )
            ],
            seed=1,
            encounter=[_frail("mon:foe")],
        )
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="fireball",
        target_id="mon:foe",
        slot_level=3,
    )
    assert sorted(get_live(handle).deaths, key=lambda d: d.target_id) == [
        _record("char:wiz", "character", "instant_kill", None),
        _record("mon:foe", "monster", "damage", "char:wiz"),
    ]


def test_a_death_by_failed_death_saves_names_nobody() -> None:
    with rng_factory(_D20Shows1):
        handle, live = start([pc(hp_current=0)], seed=1, encounter=[foe(zone_id=cell_id(5, 5))])
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    assert len(events(live, DeathSaveRolled)) == 2
    assert get_live(handle).deaths == [_record("char:hero", "character", "death_saves", None)]
