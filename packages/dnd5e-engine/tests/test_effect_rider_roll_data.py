"""Roll-data tokens in an effect rider's change values.

An activity's effect rider is a ``PassiveEffect`` whose change values may carry
Foundry roll-data tokens. Foundry evaluates such a value against the roll data
of the actor the effect is applied to, so ``@attributes.movement.walk`` is the
walking Speed of the creature that receives the effect:

* SRD 5.2 Potion of Flying: "When you drink this potion, you gain a Fly Speed
  equal to your Speed for 1 hour and can hover."
* SRD 5.2 Freedom of Movement: "you have a Swim Speed equal to your Speed"
  (Oil of Slipperiness's "Cover Creature" casts it on the creature it covers).
* SRD 5.2 Spider Climb: "you gain a Climb Speed equal to its Speed".

A rider is applied after the intent is accepted and its cost is paid, so every
token a canonical rider carries must resolve; the corpus guard below pins that.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterator
from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema import Feature, Item, Spell
from dnd5e_srd_data.schema.common import AppliedEffectRef, PassiveEffect

from dnd5e_engine.activities.conjuration import CONJURATION_ALLOWLIST
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.events import CastFailed, EffectApplied
from dnd5e_engine.types.combat import Combatant
from tests.c20_support import act, combatant, events, foe, pc, start, wizard

_SRD = BundledAssetLoader()
_HERO = "char:hero"
_FOE = "mon:foe"
_FLY = "system.attributes.movement.fly"
_SWIM = "system.attributes.movement.swim"
_CLIMB = "system.attributes.movement.climb"
_OIL_COVER_CREATURE = "dgp4czAiBiwgDJ2X"


def _changes(effect: EffectApplied) -> dict[str, tuple[str, Any]]:
    return {ch.key: (ch.mode, ch.value) for ch in effect.effect.changes}


# ── seeded end-to-end ───────────────────────────────────────────────────────


def test_drinking_a_potion_of_flying_grants_a_fly_speed_equal_to_the_drinkers_speed() -> None:
    handle, live = start([pc(base_speed=35)], seed=1, encounter=[foe(base_speed=40)])
    act(handle, _HERO, intent_type="use_item", item_id="potion-of-flying", target_id=_HERO)

    [applied] = events(live, EffectApplied)
    assert applied.effect.name == "Flyer"
    assert applied.effect.target_id == _HERO
    changes = _changes(applied)
    assert changes[_FLY] == ("upgrade", "35")
    assert changes["system.attributes.movement.hover"] == ("override", "true")
    assert [e.name for e in live.active_effects[_HERO]] == ["Flyer"]

    # SRD 5.2 potions are a Bonus Action to drink; the one-use potion is spent.
    hero = combatant(live)
    assert hero.bonus_action_available is False
    assert hero.action_available is True
    act(handle, _HERO, intent_type="use_item", item_id="potion-of-flying", target_id=_HERO)
    assert [f.reason for f in events(live, CastFailed)] == ["no_charges_remaining"]
    assert len(events(live, EffectApplied)) == 1


def test_oil_of_slipperiness_gives_the_covered_creature_its_own_speed_to_swim() -> None:
    """The covered creature's Speed (40), not the user's (30), owns the value."""
    handle, live = start([pc()], seed=1, encounter=[foe(base_speed=40)])
    act(
        handle,
        _HERO,
        intent_type="use_item",
        item_id="oil-of-slipperiness",
        activity_id=_OIL_COVER_CREATURE,
        target_id=_FOE,
    )
    [applied] = events(live, EffectApplied)
    assert applied.effect.target_id == _FOE
    assert _changes(applied)[_SWIM] == ("upgrade", "40")


def test_spider_climb_gives_its_target_a_climb_speed_equal_to_the_targets_speed() -> None:
    handle, live = start(
        [pc(base_speed=25), wizard(spells_known=["spider-climb"], initiative=25)], seed=1
    )
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="spider-climb",
        target_id=_HERO,
        slot_level=2,
    )
    [applied] = events(live, EffectApplied)
    assert applied.effect.target_id == _HERO
    assert _changes(applied)[_CLIMB] == ("upgrade", "25")


# ── corpus guard ────────────────────────────────────────────────────────────


_SCALE_TOKEN = re.compile(r"@scale\.([A-Za-z0-9_.-]+)")
_CLASS_LEVELS_TOKEN = re.compile(r"@classes\.([a-z0-9-]+)\.levels")


def _guard_ctx(target: Combatant, rider: PassiveEffect) -> ActivityResolutionContext:
    """The orchestrator fills the level-scaled carriers per caster, so every
    carrier key the rider names answers here: the guard checks only that the
    resolver knows each token's shape."""
    values = " ".join(str(ch.value) for ch in rider.changes)
    return ActivityResolutionContext(
        rng=random.Random(1),
        caster=target,
        targets=[target],
        event_emitter=lambda e: None,
        caster_abilities={a: 10 for a in ("str", "dex", "con", "int", "wis", "cha")},
        caster_proficiency_bonus=2,
        spellcasting_ability="int",
        scale_values={key: 1 for key in _SCALE_TOKEN.findall(values)},
        class_levels={cls: 1 for cls in _CLASS_LEVELS_TOKEN.findall(values)},
        source_passive_effects=[rider],
    )


def _applied_riders() -> Iterator[tuple[str, Any, AppliedEffectRef, PassiveEffect]]:
    """Every ``(owner slug, activity, ref, rider)`` a canonical item, spell or
    feature activity applies. An ``enchant`` activity applies its riders only
    for an allowlisted conjuration source; every other one is a narrative no-op
    (its riders are description embeds, never applied)."""
    entries: list[Item | Spell | Feature | None] = [
        *(_SRD.get_item(slug) for slug in _SRD.list_slugs("items")),
        *(_SRD.get_spell(slug) for slug in _SRD.list_slugs("spells")),
        *(_SRD.get_feature(slug) for slug in _SRD.list_slugs("features")),
    ]
    for entry in entries:
        assert entry is not None
        by_id = {pe.id: pe for pe in entry.passive_effects}
        for activity in entry.activities:
            if activity.kind == "enchant" and CONJURATION_ALLOWLIST.get(entry.slug) != "enchant":
                continue
            for ref in getattr(activity, "effects", ()):
                if ref.id in by_id:
                    yield entry.slug, activity, ref, by_id[ref.id]


_TOKEN = re.compile(r"@[A-Za-z]")


def test_every_canonical_rider_change_value_resolves() -> None:
    target = Combatant(
        entity_id="char:guard",
        entity_type="Character",
        name="Guard",
        initiative=10,
        hp_current=10,
        base_speed=30,
    )
    failures: list[str] = []
    checked = 0
    for slug, activity, ref, pe in _applied_riders():
        if not any(isinstance(ch.value, str) and _TOKEN.search(ch.value) for ch in pe.changes):
            continue
        checked += 1
        try:
            apply_activity_effects(
                activity,
                _guard_ctx(target, pe),
                target,
                save_succeeded=None,
                cast_level=ref.level.min or 0,
            )
        except ValueError as exc:
            failures.append(f"{slug} / {pe.name}: {exc}")
    assert checked > 0
    assert failures == []
