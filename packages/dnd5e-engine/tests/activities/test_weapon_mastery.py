"""Behavioral tests for SRD-2024 weapon mastery (``activities/mastery.py``).

Only the two masteries that fully resolve inside a single attack are
implemented; the other six are deliberately deferred. The rules pinned here:

- **graze** fires on a MISS and deals flat governing-ability-modifier damage
  of the weapon's damage type — no dice, nothing at all when the modifier is
  zero or negative. It routes through ``apply_damage`` so the target's
  resistances still apply.
- **topple** fires on a HIT: a Constitution save vs ``8 + proficiency +
  governing-ability mod``, knocking the target prone on a failure.
  ``SaveRolled`` must be emitted *before* any ``ConditionApplied`` — a topple
  that applies prone without first reporting the save is a bug.
- Each mastery fires on exactly one of hit/miss, never both.
- A deferred mastery applies no mechanic but must not be silent: it logs one
  INFO marker so the gap stays visible.
"""

from __future__ import annotations

import logging
import random
from datetime import date
from typing import Any

import pytest
from dnd5e_srd_data.schema.common import (
    DamagePart,
    Provenance,
    Range,
    RangeUnits,
    ReviewState,
)
from dnd5e_srd_data.schema.item import Weapon

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.mastery import apply_mastery_on_hit, apply_mastery_on_miss
from dnd5e_engine.events import ConditionApplied, DamageApplied, SaveRolled
from dnd5e_engine.types.combat import Combatant

ABILITIES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 6, 3),
        ingest_version="v1",
        srd_version=frozenset({"5.2"}),
    )


def _weapon(
    mastery: str | None = None,
    *,
    damage_type: str = "slashing",
    damage_parts: list[DamagePart] | None = None,
) -> Weapon:
    return Weapon(
        slug="battleaxe",
        name="Battleaxe",
        description="A blade.",
        weight=4.0,
        cost_gp=10.0,
        rarity="common",
        provenance=_provenance(),
        review=ReviewState(),
        weapon_category="martial_melee",
        damage_parts=(
            damage_parts
            if damage_parts is not None
            else [DamagePart(dice="1d8", damage_type=damage_type)]
        ),
        range=Range(kind="melee", value=5, units=RangeUnits.FEET),
        mastery=mastery,
    )


def _target(entity_id: str = "mon:foe", **kwargs: Any) -> Combatant:
    defaults: dict[str, Any] = dict(
        entity_id=entity_id,
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=50,
        hp_max=50,
        ac=13,
    )
    defaults.update(kwargs)
    return Combatant(**defaults)


def _ctx(
    *,
    abilities: dict[str, int] | None = None,
    proficiency: int = 2,
    forced_save_d20: int | None = 10,
    **context_kwargs: Any,
) -> tuple[ActivityResolutionContext, list[Any]]:
    events: list[Any] = []
    variables: dict[str, Any] = {}
    if forced_save_d20 is not None:
        variables["force_save_d20"] = forced_save_d20
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=Combatant(
            entity_id="char:hero",
            entity_type="Character",
            name="Hero",
            initiative=10,
            hp_current=20,
            hp_max=20,
        ),
        targets=[],
        event_emitter=events.append,
        caster_abilities=abilities or dict(ABILITIES),
        caster_proficiency_bonus=proficiency,
        variables=variables,
        **context_kwargs,
    )
    return ctx, events


# ---------------------------------------------------------------------------
# No mastery / wrong trigger
# ---------------------------------------------------------------------------


def test_weapon_without_mastery_is_a_no_op_on_hit() -> None:
    ctx, events = _ctx()

    apply_mastery_on_hit(_weapon(None), ctx, _target(), "str")

    assert events == []


def test_weapon_without_mastery_is_a_no_op_on_miss() -> None:
    ctx, events = _ctx()

    apply_mastery_on_miss(_weapon(None), ctx, _target(), "str")

    assert events == []


def test_absent_weapon_is_a_no_op() -> None:
    ctx, events = _ctx()

    apply_mastery_on_hit(None, ctx, _target(), "str")
    apply_mastery_on_miss(None, ctx, _target(), "str")

    assert events == []


def test_graze_does_not_fire_on_a_hit() -> None:
    """Graze is a miss rider — firing it on a hit would double-dip damage."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_hit(_weapon("graze"), ctx, _target(), "str")

    assert events == []


def test_topple_does_not_fire_on_a_miss() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("topple"), ctx, _target(), "str")

    assert events == []


# ---------------------------------------------------------------------------
# graze
# ---------------------------------------------------------------------------


def test_graze_deals_flat_ability_modifier_damage_on_a_miss() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(), "str")

    damage = [e for e in events if isinstance(e, DamageApplied)]
    assert len(damage) == 1
    assert damage[0].amount == 4  # STR 18 -> +4, no dice
    assert damage[0].damage_type == "slashing"


def test_graze_uses_the_weapons_damage_type() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "dex": 16})

    apply_mastery_on_miss(_weapon("graze", damage_type="piercing"), ctx, _target(), "dex")

    damage = [e for e in events if isinstance(e, DamageApplied)]
    assert damage[0].damage_type == "piercing"
    assert damage[0].amount == 3


def test_graze_deals_nothing_when_the_modifier_is_zero() -> None:
    ctx, events = _ctx()  # every ability at 10 -> +0

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(), "str")

    assert events == []


def test_graze_deals_nothing_when_the_modifier_is_negative() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 6})

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(), "str")

    assert events == []


def test_graze_without_a_governing_ability_is_a_no_op() -> None:
    """A flat attack carries no ability to graze with."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(), None)

    assert events == []


def test_graze_on_a_weapon_without_damage_parts_is_skipped() -> None:
    """Ill-formed data must not raise mid-attack."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("graze", damage_parts=[]), ctx, _target(), "str")

    assert events == []


def test_graze_damage_respects_target_resistance() -> None:
    """Routing through apply_damage is what makes resistance apply; a direct
    HP write would ignore it."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(damage_resistances=["slashing"]), "str")

    damage = [e for e in events if isinstance(e, DamageApplied)]
    assert damage[0].amount == 2  # 4 halved


def test_graze_damage_is_zeroed_by_target_immunity() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    apply_mastery_on_miss(_weapon("graze"), ctx, _target(damage_immunities=["slashing"]), "str")

    damage = [e for e in events if isinstance(e, DamageApplied)]
    assert damage[0].amount == 0


# ---------------------------------------------------------------------------
# topple
# ---------------------------------------------------------------------------


def test_topple_dc_is_eight_plus_proficiency_plus_ability_mod() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, proficiency=3)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    saves = [e for e in events if isinstance(e, SaveRolled)]
    assert len(saves) == 1
    assert saves[0].dc == 15  # 8 + 3 + 4
    assert saves[0].ability == "con"
    assert saves[0].target_id == "mon:foe"


def test_topple_dc_without_a_governing_ability_contributes_zero() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, proficiency=2)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), None)

    saves = [e for e in events if isinstance(e, SaveRolled)]
    assert saves[0].dc == 10


def test_topple_knocks_the_target_prone_on_a_failed_save() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, forced_save_d20=1)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    conditions = [e for e in events if isinstance(e, ConditionApplied)]
    assert len(conditions) == 1
    assert conditions[0].condition == "prone"
    assert conditions[0].target_id == "mon:foe"


def test_topple_applies_nothing_on_a_successful_save() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, forced_save_d20=20)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    assert [e for e in events if isinstance(e, SaveRolled)]
    assert not [e for e in events if isinstance(e, ConditionApplied)]


def test_topple_emits_the_save_before_the_condition() -> None:
    """Ordering is load-bearing: a prone condition with no preceding SaveRolled
    reads as an unresolved effect to any consumer of the event stream."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, forced_save_d20=1)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    kinds = [type(e) for e in events]
    assert kinds.index(SaveRolled) < kinds.index(ConditionApplied)


def test_topple_save_reports_its_outcome() -> None:
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, proficiency=2, forced_save_d20=20)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    save = next(e for e in events if isinstance(e, SaveRolled))
    assert save.succeeded is True
    assert save.roll_total >= 20


# ---------------------------------------------------------------------------
# Deferred masteries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mastery", ["sap", "vex", "slow", "push", "nick", "cleave"])
def test_deferred_masteries_apply_no_mechanic_but_log_the_gap(
    mastery: str, caplog: pytest.LogCaptureFixture
) -> None:
    """These six are lingering / multi-target / movement effects that cannot
    resolve inside one attack. They must be inert — but visibly so."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18})

    with caplog.at_level(logging.INFO, logger="dnd5e_engine.activities.mastery"):
        apply_mastery_on_hit(_weapon(mastery), ctx, _target(), "str")
        apply_mastery_on_miss(_weapon(mastery), ctx, _target(), "str")

    assert events == []
    assert caplog.text.count(f"mastery_deferred mastery={mastery}") == 2


def test_topple_save_carries_its_roll_breakdown() -> None:
    """F2c — every ``SaveRolled`` emitted by the engine now reports the kept
    natural, the flat modifier and the advantage sources that applied."""
    ctx, events = _ctx(abilities={**ABILITIES, "str": 18}, forced_save_d20=13)

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    save = next(e for e in events if isinstance(e, SaveRolled))
    assert save.natural == 13
    assert save.modifier == 0  # no per-target save sidecar in this context
    assert save.roll_total == 13
    assert save.advantage == "normal"
    assert save.sources == []


def test_topple_save_reports_target_side_advantage() -> None:
    """F2c round 2 — ``SaveRolled.advantage`` mirrors ``AttackRolled.advantage``:
    a target with SRD condition-derived advantage on the topple Con save keeps
    the higher of two dice and the event says so."""
    ctx, events = _ctx(
        abilities={**ABILITIES, "str": 18},
        forced_save_d20=None,
        passive_save_adv={"mon:foe": ["CON"]},
    )
    rolls = random.Random(1)
    expected = max(rolls.randint(1, 20), rolls.randint(1, 20))

    apply_mastery_on_hit(_weapon("topple"), ctx, _target(), "str")

    save = next(e for e in events if isinstance(e, SaveRolled))
    assert save.natural == expected
    assert save.advantage == "advantage"
    assert save.sources == ["condition:target"]
