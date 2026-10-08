"""Savage Attacker and Grappler in the attack resolver.

SRD 5.2 Savage Attacker: "Once per turn when you hit a target with a weapon,
you can roll the weapon's damage dice twice and use either roll against the
target." Grappler: "You have Advantage on attack rolls against a creature
Grappled by you." These pin the resolver halves against scripted dice;
``orchestrator.py`` projects the per-turn use and who grapples whom.
"""

from __future__ import annotations

import random
from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled, CombatEvent, DamageApplied
from dnd5e_engine.types.combat import Combatant

LOADER = BundledAssetLoader()


class _Scripted(random.Random):
    """Hands out the scripted faces in order: each d20, then each damage die.
    Running out means the resolver drew a die the test did not expect."""

    def __init__(self, faces: list[int]) -> None:
        super().__init__(0)
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        face = self.faces.pop(0)
        assert a <= face <= b, (face, a, b)
        return face


def _hero(**fields: Any) -> Combatant:
    base: dict[str, Any] = {
        "entity_id": "char:hero",
        "entity_type": "Character",
        "name": "Hero",
        "initiative": 20,
        "hp_current": 30,
        "hp_max": 30,
        "strength": 16,
        "feats": ("savage-attacker",),
    }
    return Combatant(**(base | fields))


def _foe(entity_id: str = "mon:foe") -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
    )


def _swing(
    weapon_slug: str, faces: list[int], *, hero: Combatant | None = None, **context: Any
) -> tuple[list[CombatEvent], ActivityResolutionContext, _Scripted]:
    """Resolve one attack with ``weapon_slug`` against ``mon:foe`` on ``faces``."""
    weapon = LOADER.get_weapon(weapon_slug)
    assert weapon is not None
    caster = hero or _hero()
    activity = next(a for a in weapon.activities if a.kind == "attack")
    events: list[CombatEvent] = []
    rng = _Scripted(faces)
    ctx = ActivityResolutionContext(
        rng=rng,
        caster=caster,
        targets=[_foe()],
        event_emitter=events.append,
        caster_abilities={
            "str": caster.strength,
            "dex": caster.dexterity,
            "con": 10,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        caster_proficiency_bonus=2,
        **context,
    )
    resolve_activity(activity, ctx, weapon=weapon)
    return events, ctx, rng


def _damage(events: list[CombatEvent]) -> list[int]:
    return [e.amount for e in events if isinstance(e, DamageApplied)]


def test_savage_attacker_keeps_the_higher_of_two_weapon_rolls() -> None:
    # Greatsword 2d6 + STR 3: a d20 of 15 hits AC 1; rolls 2+1 and 6+5.
    events, ctx, rng = _swing("greatsword", [15, 2, 1, 6, 5])
    assert _damage(events) == [11 + 3]
    assert ctx.savage_attacker_spent == {"char:hero": True}
    assert rng.faces == []
    # The first roll is kept when the second is lower; the modifier is added once.
    events, _, _ = _swing("greatsword", [15, 6, 5, 2, 1])
    assert _damage(events) == [11 + 3]


def test_without_the_feat_the_weapon_rolls_once() -> None:
    events, ctx, rng = _swing("greatsword", [15, 2, 1], hero=_hero(feats=()))
    assert _damage(events) == [3 + 3]
    assert ctx.savage_attacker_spent == {}
    assert rng.faces == []


def test_savage_attacker_used_this_turn_rolls_once() -> None:
    events, ctx, rng = _swing("greatsword", [15, 2, 1], savage_attacker_spent={"char:hero": True})
    assert _damage(events) == [3 + 3]
    assert ctx.savage_attacker_spent == {"char:hero": True}
    assert rng.faces == []


def test_savage_attacker_rerolls_critical_dice_and_the_great_weapon_fighting_floor() -> None:
    # A natural 20 doubles the dice (4d6), on both rolls; Great Weapon Fighting
    # treats each 1 or 2 as a 3 on both: 3+3+3+3 = 12, then 6+6+6+6 = 24.
    hero = _hero(fighting_styles=("great-weapon-fighting",))
    events, _, rng = _swing("greatsword", [20, 1, 1, 2, 2, 6, 6, 6, 6], hero=hero)
    assert _damage(events) == [24 + 3]
    assert rng.faces == []


def test_savage_attacker_skips_an_unarmed_strike() -> None:
    # A Monk's Unarmed Strike rolls its Martial Arts die (1d8) once: an
    # Unarmed Strike is not a weapon.
    events, ctx, rng = _swing(
        "unarmed-strike",
        [15, 4],
        martial_arts=True,
        scale_values={"monk.die": "d8"},
    )
    assert _damage(events) == [4 + 3]
    assert ctx.savage_attacker_spent == {}
    assert rng.faces == []


def test_a_cleave_hit_in_the_same_attack_rolls_once() -> None:
    # Greataxe 1d12: the main hit rolls 1 and 12 and keeps 12 (+3); the Cleave
    # chain (d20 15) rolls its 1d12 once (5, no modifier).
    second = _foe("mon:second")
    events, ctx, rng = _swing(
        "greataxe",
        [15, 1, 12, 15, 5],
        cleave_available=True,
        cleave_candidate=second,
    )
    assert _damage(events) == [12 + 3, 5]
    assert ctx.savage_attacker_spent == {"char:hero": True}
    assert rng.faces == []


def test_a_grappler_attacks_the_creature_it_grapples_with_advantage() -> None:
    hero = _hero(feats=("grappler",))
    events, _, _ = _swing(
        "longsword", [4, 15, 5], hero=hero, target_grappled_by_attacker={"mon:foe": True}
    )
    [swing] = [e for e in events if isinstance(e, AttackRolled)]
    assert (swing.advantage, swing.advantage_sources, swing.natural) == (
        "advantage",
        ["trait"],
        15,
    )


def test_grappling_without_the_feat_or_the_feat_without_a_grapple_gives_nothing() -> None:
    for hero, grappled in ((_hero(feats=()), True), (_hero(feats=("grappler",)), False)):
        events, _, _ = _swing(
            "longsword",
            [15, 5],
            hero=hero,
            target_grappled_by_attacker={"mon:foe": grappled},
        )
        [swing] = [e for e in events if isinstance(e, AttackRolled)]
        assert (swing.advantage, swing.advantage_sources) == ("normal", [])
