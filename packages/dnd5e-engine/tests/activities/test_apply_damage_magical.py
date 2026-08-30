"""C22-S04 — magical B/P/S damage overcomes resistance to *nonmagical* B/P/S."""

from __future__ import annotations

import random

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.types.combat import Combatant


def _run(
    *,
    magical: bool,
    resistances: list[str],
    nonmagical_only: bool = True,
    damage_type: str = "piercing",
):
    events: list[DamageApplied] = []
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t",
        entity_type="Monster",
        name="T",
        initiative=1,
        hp_current=50,
        hp_max=50,
        damage_resistances=resistances,
        physical_resistances_nonmagical_only=nonmagical_only,
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=caster,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
    )
    apply_damage(target, {damage_type: 10}, ctx, magical=magical)
    return events[0].amount


def test_nonmagical_piercing_is_halved_by_piercing_resistance():
    assert _run(magical=False, resistances=["piercing"]) == 5


def test_magical_piercing_bypasses_nonmagical_piercing_resistance():
    assert _run(magical=True, resistances=["piercing"]) == 10


def test_unconditional_resistance_still_halves_magical_damage():
    assert _run(magical=True, resistances=["piercing"], nonmagical_only=False) == 5


def test_magical_flag_never_bypasses_non_physical_or_all_resistance():
    assert _run(magical=True, resistances=["fire"], damage_type="fire") == 5
    assert _run(magical=True, resistances=["all"]) == 5


def test_default_call_is_nonmagical():
    events: list[DamageApplied] = []
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t",
        entity_type="Monster",
        name="T",
        initiative=1,
        hp_current=50,
        hp_max=50,
        damage_resistances=["slashing"],
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=caster,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
    )
    apply_damage(target, {"slashing": 9}, ctx)
    assert events[0].amount == 4
