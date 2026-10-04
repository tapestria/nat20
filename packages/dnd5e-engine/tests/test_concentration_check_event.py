"""F2c — the concentration-on-damage check emits ``ConcentrationCheck``.

SRD 5.2 §Concentration: *"If you take damage, you must succeed on a
Constitution saving throw to maintain Concentration. The DC equals 10 or half
the damage taken, whichever number is higher."*

The check is the roll's only event: no generic ``SaveRolled(ability="con")``
accompanies it. Its d20 goes through the shared ``roll_d20_test`` primitive, so
the event carries the ``natural`` / ``modifier`` breakdown.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, cast

import pytest

from dnd5e_engine.events import ConcentrationCheck, SaveRolled
from dnd5e_engine.orchestrator import _LiveCombat
from dnd5e_engine.types.combat import Combatant


def _caster() -> Combatant:
    return Combatant(
        entity_id="char:a",
        entity_type="Character",
        name="A",
        initiative=10,
        hp_current=40,
        hp_max=40,
        character_level=5,
        constitution=18,
        save_proficiencies=["con"],
    )


def _fake_live() -> _LiveCombat:
    return _LiveCombat(
        handle_id="h",
        session_id="s",
        initiative=[],
        party_ids=set(),
        encounter_ids=set(),
        topology=cast(Any, None),
        rng=cast(Any, None),
        event_queue=asyncio.Queue(),
        scene_location_id="loc:test",
    )


def _damage(amount: int, *, concentrating: bool = True) -> _LiveCombat:
    from dnd5e_engine import orchestrator as orch

    live = _fake_live()
    caster = _caster()
    live.initiative = [caster]
    live.rng = random.Random(20260826)
    live.tracked_hp = {caster.entity_id: 40}
    if concentrating:
        live.concentration_chain = {caster.entity_id: [("mon:x", "eff:1", "spell:hold-person")]}
    orch._emit_apply_damage(
        live,
        orch.DamageApplied(
            target_id=caster.entity_id,
            amount=amount,
            damage_type="fire",
            source_id="mon:x",
            is_overkill=False,
        ),
    )
    return live


def _events(live: _LiveCombat, kind: type) -> list[Any]:
    return [e for e in live.event_log if isinstance(e, kind)]


@pytest.mark.parametrize(
    ("amount", "expected_dc"),
    [(1, 10), (18, 10), (20, 10), (30, 15), (41, 20)],
)
def test_concentration_check_dc_is_ten_or_half_the_damage(amount: int, expected_dc: int) -> None:
    checks = _events(_damage(amount), ConcentrationCheck)

    assert len(checks) == 1
    assert checks[0].dc == expected_dc == max(10, amount // 2)
    assert checks[0].target_id == "char:a"


def test_concentration_check_is_the_rolls_only_event() -> None:
    live = _damage(24)

    assert len(_events(live, ConcentrationCheck)) == 1
    assert _events(live, SaveRolled) == []


def test_concentration_check_carries_its_roll_breakdown() -> None:
    """F2c — the check reports the kept natural and the flat modifier
    (CON 18 + proficiency at level 5 = +4 + 3)."""
    check = _events(_damage(24), ConcentrationCheck)[0]

    assert check.natural is not None
    assert 1 <= check.natural <= 20
    assert check.modifier == 7
    assert check.roll_total == check.natural + check.modifier
    assert check.advantage == "normal"
    assert check.sources == []


def test_no_concentration_means_no_check_event() -> None:
    live = _damage(24, concentrating=False)

    assert _events(live, ConcentrationCheck) == []
    assert _events(live, SaveRolled) == []


def test_concentration_check_draws_exactly_one_d20() -> None:
    """The primitive is called with no advantage source, so the seeded stream
    is byte-identical to the pre-F2c single ``randint(1, 20)`` draw."""
    from dnd5e_engine import orchestrator as orch

    live = _fake_live()
    caster = _caster()
    live.initiative = [caster]
    live.rng = random.Random(4242)
    live.tracked_hp = {caster.entity_id: 40}
    live.concentration_chain = {caster.entity_id: [("mon:x", "eff:1", "spell:hold-person")]}

    reference = random.Random(4242)
    expected_natural = reference.randint(1, 20)
    expected_next = reference.randint(1, 20)

    orch._emit_apply_damage(
        live,
        orch.DamageApplied(
            target_id=caster.entity_id,
            amount=24,
            damage_type="fire",
            source_id="mon:x",
            is_overkill=False,
        ),
    )

    assert _events(live, ConcentrationCheck)[0].natural == expected_natural
    assert live.rng.randint(1, 20) == expected_next


# SRD 5.2 §Concentration: "The DC equals 10 or half the damage taken (round
# down), whichever number is higher, up to a maximum DC of 30." The cap is
# 2024/SRD-5.2-specific (Foundry: actor.mjs getConcentrationDC clamps to
# [10, 30] only in "modern" rules).
def test_concentration_dc_clamps_at_srd_maximum_30() -> None:
    live = _damage(90)
    checks = [e for e in live.event_log if isinstance(e, ConcentrationCheck)]
    assert len(checks) == 1
    assert checks[0].dc == 30  # raw amount // 2 == 45, must clamp


def test_concentration_dc_floor_and_midband_unchanged() -> None:
    assert next(e for e in _damage(8).event_log if isinstance(e, ConcentrationCheck)).dc == 10
    assert next(e for e in _damage(44).event_log if isinstance(e, ConcentrationCheck)).dc == 22
    assert next(e for e in _damage(60).event_log if isinstance(e, ConcentrationCheck)).dc == 30
