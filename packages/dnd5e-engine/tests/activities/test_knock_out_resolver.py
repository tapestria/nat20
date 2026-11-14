"""Knocking out a creature, resolver side: which damage carries the choice.

SRD 5.2 Rules Glossary, "Knocking Out a Creature":

    "When you would reduce a creature to 0 Hit Points with a melee attack, you
    can instead reduce the creature to 1 Hit Point. The creature then has the
    Unconscious condition and starts a Short Rest.

    The creature remains Unconscious until it regains any Hit Points or until
    someone uses an action to administer first aid to it, which requires a
    successful DC 10 Wisdom (Medicine) check."

The resolver only marks the damage: ``ActivityResolutionContext.knock_out``
says the attacker chose to pull its blows, and ``resolve_attack`` stamps
``DamageApplied.knock_out`` on the damage of a *melee* attack (a melee attack
activity whose weapon is not a ranged weapon and not a Thrown weapon thrown
beyond its reach). Everything that is part of that attack's damage carries it:
the base weapon dice, Sneak Attack, a Cleave follow-up swing and a Graze on a
miss. A save-based rider is not an attack and never does. The Unconscious
fold itself is the orchestrator's.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackBlock,
    AttackDamageBlock,
    AttackTypeBlock,
    DamagePartBlock,
    RangeBlock,
)
from dnd5e_srd_data.schema.item import Weapon
from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.mastery import apply_mastery_on_miss
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import DamageApplied, SaveRolled
from dnd5e_engine.types.combat import Combatant

_LOADER = BundledAssetLoader()


def _weapon(slug: str) -> Weapon:
    weapon = _LOADER.get_weapon(slug)
    assert weapon is not None
    return weapon


def _attack_of(weapon: Weapon) -> AttackActivity:
    return next(a for a in weapon.activities if isinstance(a, AttackActivity))


def _attacker() -> Combatant:
    return Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
        strength=16,
        dexterity=16,
    )


def _foe(entity_id: str = "mon:bandit", *, hp: int = 2) -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Monster",
        name="Bandit",
        initiative=1,
        hp_current=hp,
        hp_max=11,
        ac=5,
    )


def _ctx(
    targets: list[Combatant],
    events: list[Any],
    *,
    distance_ft: int = 5,
    knock_out: bool | None = None,
    seed: int = 7,
    **extra: Any,
) -> ActivityResolutionContext:
    ctx = build_activity_context(
        _attacker(),
        targets,
        rng=random.Random(seed),
        event_emitter=events.append,
        slot_level=None,
        base_spell_level=None,
        spellcasting_ability=None,
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers={},
        save_modifiers={},
        target_distance_ft={t.entity_id: distance_ft for t in targets},
        **extra,
    )
    ctx.variables["force_d20"] = 15
    if knock_out is None:
        return ctx
    return replace(ctx, knock_out=knock_out)


def _damage(events: list[Any]) -> list[DamageApplied]:
    return [e for e in events if isinstance(e, DamageApplied)]


def _swing(
    slug: str, *, distance_ft: int = 5, knock_out: bool | None = True, **extra: Any
) -> list[Any]:
    weapon = _weapon(slug)
    events: list[Any] = []
    ctx = _ctx([_foe()], events, distance_ft=distance_ft, knock_out=knock_out, **extra)
    resolve_activity(_attack_of(weapon), ctx, weapon=weapon)
    return events


# ── the context flag ─────────────────────────────────────────────────────────


def test_the_context_flag_defaults_off() -> None:
    assert _ctx([_foe()], []).knock_out is False


# ── melee attacks carry it ───────────────────────────────────────────────────


def test_a_melee_weapon_hit_stamps_every_damage_event() -> None:
    damage = _damage(_swing("longsword"))
    assert damage
    assert all(e.knock_out for e in damage)


def test_a_thrown_dagger_within_reach_is_a_melee_attack() -> None:
    damage = _damage(_swing("dagger", distance_ft=5))
    assert damage
    assert all(e.knock_out for e in damage)


def test_a_natural_melee_attack_stamps_its_damage() -> None:
    """A stat-block melee attack (no weapon item), as a commanded summon
    makes, is a melee attack."""
    activity = AttackActivity(
        name="Rend",
        range=RangeBlock(units="ft", value="5"),
        attack=AttackBlock(type=AttackTypeBlock(value="melee", classification="weapon")),
        damage=AttackDamageBlock(
            parts=[DamagePartBlock(number=1, denomination=6, bonus="4", types=["piercing"])]
        ),
    )
    events: list[Any] = []
    resolve_activity(activity, _ctx([_foe()], events, knock_out=True))
    damage = _damage(events)
    assert damage
    assert all(e.knock_out for e in damage)


# ── ranged attacks never do ──────────────────────────────────────────────────


def test_a_ranged_weapon_hit_never_stamps() -> None:
    damage = _damage(_swing("shortbow", distance_ft=30))
    assert damage
    assert not any(e.knock_out for e in damage)


def test_a_ranged_weapon_at_point_blank_still_never_stamps() -> None:
    damage = _damage(_swing("shortbow", distance_ft=5))
    assert damage
    assert not any(e.knock_out for e in damage)


def test_a_dagger_thrown_beyond_reach_never_stamps() -> None:
    damage = _damage(_swing("dagger", distance_ft=20))
    assert damage
    assert not any(e.knock_out for e in damage)


# ── the default leaves the damage as it was ──────────────────────────────────


def test_the_default_leaves_damage_unchanged() -> None:
    """Without the choice the damage is what it was before the flag existed:
    the same dumps as an explicit ``knock_out=False`` and as a pulled blow
    that cannot apply (a ranged attack), and the same dice drawn."""
    default = [e.model_dump() for e in _damage(_swing("shortbow", knock_out=None))]
    off = [e.model_dump() for e in _damage(_swing("shortbow", knock_out=False))]
    pulled_ranged = [e.model_dump() for e in _damage(_swing("shortbow", knock_out=True))]
    assert default == off == pulled_ranged
    assert all(d["knock_out"] is False for d in default)


def test_the_choice_draws_no_extra_dice() -> None:
    def state(knock_out: bool | None) -> object:
        weapon = _weapon("longsword")
        ctx = _ctx([_foe()], [], knock_out=knock_out)
        resolve_activity(_attack_of(weapon), ctx, weapon=weapon)
        return ctx.rng.getstate()

    assert state(None) == state(True)


def test_a_pulled_melee_blow_differs_only_in_the_flag() -> None:
    pulled = [e.model_dump() for e in _damage(_swing("longsword", knock_out=True))]
    plain = [e.model_dump() for e in _damage(_swing("longsword", knock_out=None))]
    assert [{**d, "knock_out": False} for d in pulled] == plain


# ── the rest of the same attack ──────────────────────────────────────────────


def test_sneak_attack_dice_ride_the_pulled_blow() -> None:
    plain = _damage(_swing("dagger", knock_out=None, scale_values={}))
    with_sneak = _damage(
        _swing(
            "dagger",
            scale_values={"rogue.sneak-attack": "3d6"},
            sneak_attack_ally_adjacent={"mon:bandit": True},
        )
    )
    assert sum(e.amount for e in with_sneak) > sum(e.amount for e in plain)
    assert all(e.knock_out for e in with_sneak)


def test_a_cleave_follow_up_rides_the_pulled_blow() -> None:
    weapon = _weapon("greataxe")
    assert weapon.mastery == "cleave"
    second = _foe("mon:second")
    events: list[Any] = []
    ctx = _ctx(
        [_foe()],
        events,
        knock_out=True,
        cleave_available=True,
        cleave_candidate=second,
        seed=1,
    )
    ctx.target_distance_ft["mon:second"] = 5
    resolve_activity(_attack_of(weapon), ctx, weapon=weapon)
    cleave = [e for e in _damage(events) if e.source_id == "mastery:cleave"]
    assert cleave, "seed 1 lands the follow-up swing"
    assert all(e.knock_out for e in _damage(events))


def test_a_graze_on_a_miss_rides_the_pulled_blow() -> None:
    weapon = _weapon("glaive")
    assert weapon.mastery == "graze"
    events: list[Any] = []
    ctx = _ctx([_foe()], events, knock_out=True)
    ctx.variables["force_d20"] = 1  # a natural 1 always misses
    resolve_activity(_attack_of(weapon), ctx, weapon=weapon)
    damage = _damage(events)
    assert [e.source_id for e in damage] == ["mastery:graze"]
    assert damage[0].knock_out is True


def test_a_graze_called_without_the_choice_stays_unmarked() -> None:
    target = _foe()
    events: list[Any] = []
    apply_mastery_on_miss(_weapon("glaive"), _ctx([target], events, knock_out=True), target, "str")
    assert [e.knock_out for e in _damage(events)] == [False]


def test_a_save_rider_never_carries_it() -> None:
    """A Saving Throw is not an attack: a save activity's damage resolved
    under a pulled-blow context stays unmarked."""
    spell = _LOADER.get_spell("thunderwave")
    assert spell is not None
    save = next(a for a in spell.activities if a.kind == "save")
    events: list[Any] = []
    resolve_activity(save, _ctx([_foe(hp=40)], events, knock_out=True))
    damage = _damage(events)
    assert damage
    assert not any(e.knock_out for e in damage)


# ── apply_damage ─────────────────────────────────────────────────────────────


def test_apply_damage_stamps_the_keyword_on_every_type() -> None:
    events: list[Any] = []
    target = _foe(hp=20)
    ctx = _ctx([target], events)
    apply_damage(target, {"slashing": 3, "fire": 2}, ctx, knock_out=True)
    assert [(e.damage_type, e.knock_out) for e in _damage(events)] == [
        ("slashing", True),
        ("fire", True),
    ]


def test_a_pulled_blow_leaves_no_undead_fortitude_save() -> None:
    """Undead Fortitude: "If damage reduces the [monster] to 0 Hit Points, it
    makes a Constitution saving throw". A pulled blow reduces it to 1 Hit Point
    instead, so no save is rolled and no die is drawn."""
    zombie = Combatant(
        entity_id="mon:zombie",
        entity_type="Monster",
        name="Zombie",
        initiative=1,
        hp_current=3,
        hp_max=22,
        constitution=16,
        trait_mechanics=[MonsterTraitMechanic.UNDEAD_FORTITUDE],
    )
    events: list[Any] = []
    ctx = _ctx([zombie], events)
    before = ctx.rng.getstate()
    apply_damage(zombie, {"bludgeoning": 5}, ctx, knock_out=True)
    assert not [e for e in events if isinstance(e, SaveRolled)]
    assert ctx.rng.getstate() == before
    assert [e.knock_out for e in _damage(events)] == [True]
