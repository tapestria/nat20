"""F2b — the LIVE attack path honours advantage/disadvantage.

Before F2b ``activities/attack.py`` hard-coded ``mode = "normal"`` and
``rules/conditions.py::conditions_grant_advantage_on_attack`` was dead code.
These tests pin the four properties that change:

* an attacker ``flags.advantage.attack`` effect → ``advantage`` mode, source
  ``"flag"``, and exactly TWO d20 draws consumed from the seeded stream;
* a Blinded TARGET → ``advantage`` from ``"condition:target"`` with no effect;
* a Restrained attacker vs a Paralyzed target → the two sources CANCEL to
  ``normal`` (SRD §Advantage and Disadvantage) while both stay recorded;
* NO source at all → exactly ONE draw, i.e. the pre-F2b seeded stream is
  byte-identical (the draw discipline the D1 re-pin rests on).

Each expectation is checked against a mirror ``random.Random(seed)`` rather
than a hard-coded number, so the assertions describe the DRAW COUNT and the
keep rule, not a magic value.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange

_SEED = 9


def _attacker(*conditions: str) -> Combatant:
    return Combatant(
        entity_id="char:rogue",
        entity_type="Character",
        name="Rogue",
        initiative=10,
        hp_current=20,
        hp_max=20,
        conditions=[
            ActiveCondition(condition=c, source_entity_id="spell:0123456789ab", scope="combat")
            for c in conditions
        ],
    )


def _foe(*conditions: str) -> Combatant:
    return Combatant(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
        conditions=[
            ActiveCondition(condition=c, source_entity_id="spell:0123456789ab", scope="combat")
            for c in conditions
        ],
    )


def _flag_effect(key: str) -> ActiveEffect:
    return ActiveEffect(
        id=f"effect:{key}",
        name=key,
        origin="test",
        target_id="char:rogue",
        changes=[ActiveEffectChange(key=key, mode="override", value=True)],
    )


def _dagger_attack():
    weapon = BundledAssetLoader().get_weapon("dagger")
    assert weapon is not None
    activity = next(a for a in weapon.activities if a.kind == "attack")
    return weapon, activity


def _swing(
    *,
    attacker: Combatant,
    target: Combatant,
    active_effects: tuple[ActiveEffect, ...] = (),
) -> AttackRolled:
    """Resolve one dagger swing and return the emitted ``AttackRolled``."""
    weapon, activity = _dagger_attack()
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(_SEED),
        caster=attacker,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 10, "dex": 18, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=3,
        caster_level=5,
        active_effects=active_effects,
        attacker_conditions=[c.condition for c in attacker.conditions],
        target_conditions={target.entity_id: [c.condition for c in target.conditions]},
    )
    resolve_activity(activity, ctx, weapon=weapon)
    rolled = [e for e in events if isinstance(e, AttackRolled)]
    assert len(rolled) == 1
    return rolled[0]


# ── (a) attacker flag → advantage, two draws ─────────────────────────────────


def test_attacker_advantage_flag_rolls_with_advantage_and_consumes_two_draws():
    event = _swing(
        attacker=_attacker(),
        target=_foe(),
        active_effects=(_flag_effect("flags.advantage.attack"),),
    )
    mirror = random.Random(_SEED)
    first, second = mirror.randint(1, 20), mirror.randint(1, 20)

    assert event.advantage == "advantage"
    assert event.sources == ["flag"]
    assert event.natural == max(first, second)


def test_attacker_disadvantage_flag_keeps_the_lower_of_two_draws():
    event = _swing(
        attacker=_attacker(),
        target=_foe(),
        active_effects=(_flag_effect("flags.disadvantage.attack"),),
    )
    mirror = random.Random(_SEED)
    first, second = mirror.randint(1, 20), mirror.randint(1, 20)

    assert event.advantage == "disadvantage"
    assert event.sources == ["flag"]
    assert event.natural == min(first, second)


# ── (b) blinded target → advantage from condition:target ─────────────────────


def test_blinded_target_grants_advantage_from_a_condition_source():
    event = _swing(attacker=_attacker(), target=_foe("blinded"))
    mirror = random.Random(_SEED)
    first, second = mirror.randint(1, 20), mirror.randint(1, 20)

    assert event.advantage == "advantage"
    assert event.sources == ["condition:target"]
    assert event.natural == max(first, second)


def test_restrained_attacker_alone_imposes_disadvantage():
    event = _swing(attacker=_attacker("restrained"), target=_foe())
    mirror = random.Random(_SEED)
    first, second = mirror.randint(1, 20), mirror.randint(1, 20)

    assert event.advantage == "disadvantage"
    assert event.sources == ["condition:attacker"]
    assert event.natural == min(first, second)


# ── (c) both sides → cancel to normal ────────────────────────────────────────


def test_restrained_attacker_versus_paralyzed_target_cancels_to_normal():
    event = _swing(attacker=_attacker("restrained"), target=_foe("paralyzed"))
    mirror = random.Random(_SEED)

    assert event.advantage == "normal"
    # Both sources stay recorded even though they cancel — the provenance is
    # the point of the typed source list.
    assert sorted(event.sources) == ["condition:attacker", "condition:target"]
    # Cancelled ⇒ a NORMAL roll ⇒ exactly one draw.
    assert event.natural == mirror.randint(1, 20)


# ── (d) no sources → one draw, stream unchanged ──────────────────────────────


def test_no_advantage_source_consumes_exactly_one_draw():
    event = _swing(attacker=_attacker(), target=_foe())
    mirror = random.Random(_SEED)

    assert event.advantage == "normal"
    assert event.sources == []
    assert event.natural == mirror.randint(1, 20)


def test_modifier_and_natural_reconstruct_the_roll_total():
    event = _swing(attacker=_attacker(), target=_foe())
    assert event.modifier is not None
    assert event.natural is not None
    assert event.roll_total == event.natural + event.modifier
