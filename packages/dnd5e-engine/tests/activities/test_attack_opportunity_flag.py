"""``ActivityResolutionContext.is_opportunity_attack`` (C24): the orchestrator
flags the resolution an opportunity attack runs, and ``resolve_attack``
stamps every ``AttackRolled`` it emits with it."""

from __future__ import annotations

import random

from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackDamageBlock,
    DamagePartBlock,
    RangeBlock,
)

from dnd5e_engine.activities.attack import resolve_attack
from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.types.combat import Combatant


def _activity() -> AttackActivity:
    return AttackActivity(
        name="Claw",
        range=RangeBlock(units="self", value=None),
        damage=AttackDamageBlock(
            parts=[DamagePartBlock(number=1, denomination=6, types=["slashing"])]
        ),
    )


def _combatants() -> tuple[Combatant, Combatant]:
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t", entity_type="Monster", name="T", initiative=1, hp_current=10, hp_max=10
    )
    return caster, target


def _rolled(**fields):
    caster, target = _combatants()
    out: list[AttackRolled] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=caster,
        targets=[target],
        event_emitter=lambda e: out.append(e) if isinstance(e, AttackRolled) else None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        **fields,
    )
    resolve_attack(_activity(), ctx)
    return out


def test_an_ordinary_attack_is_not_an_opportunity_attack() -> None:
    assert [e.is_opportunity_attack for e in _rolled()] == [False]


def test_an_opportunity_attack_context_stamps_its_attack_roll() -> None:
    assert [e.is_opportunity_attack for e in _rolled(is_opportunity_attack=True)] == [True]


def test_build_activity_context_passes_the_flag_through() -> None:
    caster, target = _combatants()
    common = dict(
        rng=random.Random(1),
        event_emitter=lambda e: None,
        slot_level=None,
        base_spell_level=None,
        spellcasting_ability=None,
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers={},
        save_modifiers={},
    )
    assert build_activity_context(caster, [target], **common).is_opportunity_attack is False
    flagged = build_activity_context(caster, [target], is_opportunity_attack=True, **common)
    assert flagged.is_opportunity_attack is True
