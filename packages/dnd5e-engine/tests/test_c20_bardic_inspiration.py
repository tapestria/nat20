"""Bardic Inspiration (SRD 5.2): a die banked on another creature, rolled after
that creature's attack roll fails."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackFailed, AttackRolled, CastFailed, DamageApplied, EffectExpired
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.effects import ActiveEffect
from tests.c20_support import act, combatant, events, foe, monster_turn, pc, start

_REDEEM = "feature_grant:bardic-inspiration"


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _table(seed: int, *, bard_level: int = 3, **start_kwargs: Any):
    """S08's table: a Bard (CHA 16, initiative 20) at 0,0; an ally with a pinned
    +3 to hit and STR 10 (initiative 15) at 1,0; an AC 14 foe at 2,0."""
    return start(
        [
            pc("char:bard", class_slug="bard", character_level=bard_level, charisma=16),
            pc("char:ally", initiative=15, attack_bonus=3, zone_id=cell_id(1, 0)),
        ],
        seed=seed,
        encounter=[foe(ac=14, zone_id=cell_id(2, 0))],
        **start_kwargs,
    )


def _inspire(handle, target: str | None = "char:ally", bard: str = "char:bard") -> None:
    act(handle, bard, intent_type="use_feature", feature_id="bardic-inspiration", target_id=target)


def _inspired_ally(seed: int, **table_kwargs: Any):
    """The bard inspires the ally and passes: the ally's turn, holding a die."""
    handle, live = _table(seed, **table_kwargs)
    _inspire(handle)
    act(handle, "char:bard", intent_type="pass")
    return handle, live


def _ally_attack(handle, *, redeem: bool = True) -> None:
    act(
        handle,
        "char:ally",
        intent_type="attack",
        weapon_id="longsword",
        target_id="mon:foe",
        redeem_granted_die=_REDEEM if redeem else None,
    )


def _held_dice(live) -> list[str]:
    return [e.origin for e in live.active_effects.get("char:ally", []) if e.id == "effect:inspired"]


def _ally_failures(live) -> list[str]:
    return [e.reason for e in events(live, AttackFailed) if e.actor_id == "char:ally"]


def test_inspire_banks_one_die_on_another_creature() -> None:
    """ "As a Bonus Action, you can inspire another creature ... That creature
    gains one of your Bardic Inspiration dice." The die is the "Inspired"
    effect on the ally; the bard's turn goes on."""
    handle, live = _table(8)
    _inspire(handle)
    bard = combatant(live, "char:bard")
    assert _held_dice(live) == ["cast:inspired:char:bard"]
    assert (bard.bonus_action_available, bard.action_available) == (False, True)
    assert live.current_actor_id == "char:bard"
    assert (
        live.custom_counters_by_entity["char:bard"]["feature_use:bardic-inspiration"]["spent"] == 1
    )


def test_a_failed_attack_roll_adds_the_die() -> None:
    """ "Once within the next hour when the creature fails a D20 Test, the
    creature can roll the Bardic Inspiration die and add the number rolled to
    the d20, potentially turning the failure into a success. A Bardic
    Inspiration die is expended when it's rolled." Seed 8: d20 8 + 3 = 11
    misses AC 14; the Bard 3's d6 is the next draw, 3 → 14 hits; the Longsword's
    d8 7 follows. ``natural`` and ``modifier`` leave the die out."""
    handle, live = _inspired_ally(8)
    _ally_attack(handle)
    [attack] = events(live, AttackRolled)
    assert (attack.natural, attack.modifier, attack.roll_total, attack.is_hit) == (8, 3, 14, True)
    assert [e.amount for e in events(live, DamageApplied)] == [7]
    assert [(e.effect_id, e.target_id, e.reason) for e in events(live, EffectExpired)] == [
        ("effect:inspired", "char:ally", "expended")
    ]
    assert _held_dice(live) == []


def test_the_die_grows_with_the_bards_level() -> None:
    """A Bard 5's Bardic Inspiration die is a d8. Seed 8: 11 misses; d8 6 → 17."""
    handle, live = _inspired_ally(8, bard_level=5)
    _ally_attack(handle)
    [attack] = events(live, AttackRolled)
    assert (attack.roll_total, attack.is_hit) == (17, True)


@pytest.mark.parametrize("redeem", [True, False])
def test_a_hit_keeps_the_die(redeem: bool) -> None:
    """Only a failed roll uses the die. Seed 7: d20 11 + 3 = 14 hits AC 14, so
    nothing is rolled: the die stays banked and the Longsword's d8 (3) is the
    same draw with or without the request."""
    handle, live = _inspired_ally(7)
    _ally_attack(handle, redeem=redeem)
    [attack] = events(live, AttackRolled)
    assert (attack.roll_total, attack.is_hit) == (14, True)
    assert [e.amount for e in events(live, DamageApplied)] == [3]
    assert events(live, EffectExpired) == []
    assert _held_dice(live) == ["cast:inspired:char:bard"]


def test_a_natural_one_keeps_the_die() -> None:
    """ "If you roll a 1 on the d20 ... the attack misses regardless of any
    modifiers or the target's AC": the die could not turn it, so it is not
    rolled. Seed 31: d20 1."""
    handle, live = _inspired_ally(31)
    _ally_attack(handle)
    [attack] = events(live, AttackRolled)
    assert (attack.natural, attack.roll_total, attack.is_hit) == (1, 4, False)
    assert _held_dice(live) == ["cast:inspired:char:bard"]


_STRAY = ActiveEffect(
    id="effect:inspired", name="Inspired", origin="cast:inspired:char:gone", target_id="char:ally"
)


@pytest.mark.parametrize("seeded", [(), (_STRAY,)])
def test_redeeming_without_a_die_is_refused(seeded: tuple[ActiveEffect, ...]) -> None:
    """No die to roll — none banked, or one whose bard is not in this combat (its
    size is unknown) — refuses the attack before it spends anything."""
    handle, live = _table(8, active_effects=seeded)
    act(handle, "char:bard", intent_type="pass")
    _ally_attack(handle)
    assert _ally_failures(live) == ["no_granted_die"]
    assert events(live, AttackRolled) == []
    assert combatant(live, "char:ally").action_available
    assert live.current_actor_id == "char:ally"


def test_a_die_is_redeemed_once() -> None:
    """Once rolled, the die is gone: the ally's next redeem has nothing to roll."""
    handle, live = _inspired_ally(8)
    _ally_attack(handle)
    monster_turn(handle)
    act(handle, "char:bard", intent_type="pass")
    _ally_attack(handle)
    assert _ally_failures(live) == ["no_granted_die"]


@pytest.mark.parametrize("target", [None, "char:bard", "char:nobody"])
def test_inspire_needs_another_creature_in_the_combat(target: str | None) -> None:
    """ "...you can inspire another creature": no target, the bard itself or a
    creature not in this combat is refused before the use or the Bonus Action
    is spent."""
    handle, live = _table(8)
    _inspire(handle, target)
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert combatant(live, "char:bard").bonus_action_available
    assert "feature_use:bardic-inspiration" not in live.custom_counters_by_entity.get(
        "char:bard", {}
    )


def test_a_creature_holds_one_die_at_a_time() -> None:
    """ "A creature can have only one Bardic Inspiration die at a time." A second
    bard cannot inspire the ally while it holds the first bard's die."""
    handle, live = start(
        [
            pc("char:bard", class_slug="bard", character_level=3, charisma=16),
            pc(
                "char:bard2",
                class_slug="bard",
                character_level=3,
                charisma=16,
                initiative=18,
                zone_id=cell_id(0, 1),
            ),
            pc("char:ally", initiative=15, attack_bonus=3, zone_id=cell_id(1, 0)),
        ],
        seed=8,
        encounter=[foe(ac=14, zone_id=cell_id(2, 0))],
    )
    _inspire(handle)
    act(handle, "char:bard", intent_type="pass")
    _inspire(handle, bard="char:bard2")
    assert [e.reason for e in events(live, CastFailed)] == ["target_invalid"]
    assert combatant(live, "char:bard2").bonus_action_available
    assert _held_dice(live) == ["cast:inspired:char:bard"]


def test_the_die_is_drawn_after_the_bless_die() -> None:
    """The die follows the d20 and the Bless-style sidecar in the seeded stream,
    so a same-seed A/B stays aligned. Seed 13: d20 9 + 3 + Bless d4 3 = 15
    misses AC 16; the d6 is 6 → 21. (Drawn before the d4 it would be 3.)"""
    weapon = BundledAssetLoader().get_weapon("dagger")
    assert weapon is not None
    activity = next(a for a in weapon.activities if a.kind == "attack")
    ally = Combatant(
        entity_id="char:ally", entity_type="Character", name="Ally", initiative=15, hp_current=15
    )
    target = Combatant(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=16,
    )
    emitted: list[Any] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(13),
        caster=ally,
        targets=[target],
        event_emitter=emitted.append,
        caster_abilities=dict.fromkeys(("str", "dex", "con", "int", "wis", "cha"), 10),
        attack_bonus_override=3,
        passive_attack_bonus={"char:ally": "1d4"},
        granted_die="1d6",
    )
    resolve_activity(activity, ctx, weapon=weapon)
    [attack] = [e for e in emitted if isinstance(e, AttackRolled)]
    assert (attack.natural, attack.modifier, attack.roll_total, attack.is_hit) == (9, 3, 21, True)
    assert ctx.granted_die_rolls == [6]
