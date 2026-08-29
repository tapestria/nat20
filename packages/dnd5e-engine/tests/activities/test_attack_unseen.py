"""C16b — the ``unseen`` AdvantageSource in ``activities/attack.py`` (SRD 5.2
"Unseen Attackers and Targets"), fed from the two visibility maps."""

from __future__ import annotations

import random
from typing import Any

from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackDamageBlock,
    DamagePartBlock,
    RangeBlock,
)

from dnd5e_engine.activities.attack import resolve_attack
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.types.combat import Combatant


def _activity() -> AttackActivity:
    # Same construction ``tests/activities/test_monster_actions.py::_claw_attack`` uses.
    return AttackActivity(
        name="Claw",
        range=RangeBlock(units="self", value=None),
        damage=AttackDamageBlock(
            parts=[DamagePartBlock(number=1, denomination=6, types=["slashing"])]
        ),
    )


def _ctx(**maps: Any) -> tuple[ActivityResolutionContext, list[AttackRolled]]:
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t", entity_type="Monster", name="T", initiative=1, hp_current=10, hp_max=10
    )
    out: list[AttackRolled] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=caster,
        targets=[target],
        event_emitter=lambda e: out.append(e) if isinstance(e, AttackRolled) else None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        **maps,
    )
    return ctx, out


def test_default_maps_roll_normal() -> None:
    ctx, out = _ctx()
    resolve_attack(_activity(), ctx)
    assert out[0].advantage == "normal"
    assert out[0].sources == []


def test_attacker_cannot_see_target_is_disadvantage() -> None:
    ctx, out = _ctx(target_unseen={"t": True})
    resolve_attack(_activity(), ctx)
    assert out[0].advantage == "disadvantage"
    assert "unseen" in out[0].sources


def test_target_cannot_see_attacker_is_advantage() -> None:
    ctx, out = _ctx(attacker_unseen_by={"t": True})
    resolve_attack(_activity(), ctx)
    assert out[0].advantage == "advantage"
    assert "unseen" in out[0].sources


def test_mutually_unseen_cancels_to_normal() -> None:
    ctx, out = _ctx(target_unseen={"t": True}, attacker_unseen_by={"t": True})
    resolve_attack(_activity(), ctx)
    assert out[0].advantage == "normal"
    assert "unseen" in out[0].sources
