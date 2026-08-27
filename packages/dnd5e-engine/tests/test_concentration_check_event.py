"""F2c — the concentration-on-damage check emits ``ConcentrationCheck``.

SRD 5.2 §Concentration: *"If you take damage, you must succeed on a
Constitution saving throw to maintain Concentration. The DC equals 10 or half
the damage taken, whichever number is higher."*

Before F2c the orchestrator emitted a bare ``SaveRolled(ability="con")`` and
``ConcentrationCheck`` was an unconstructed event type; a host could only tell a
concentration save from any other CON save by convention. The specific event is
now emitted ALONGSIDE the generic one for one release (removed in v0.7), and the
d20 goes through the shared ``roll_d20_test`` primitive, so ``SaveRolled`` also
carries its ``natural`` / ``modifier`` breakdown.
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


def test_concentration_check_mirrors_the_save_it_duplicates() -> None:
    """TRANSITIONAL: both events are emitted for one release (v0.7 drops the
    ``SaveRolled``), so they must agree on total and outcome."""
    live = _damage(24)
    saves = _events(live, SaveRolled)
    checks = _events(live, ConcentrationCheck)

    assert len(saves) == len(checks) == 1
    assert saves[0].ability == "con"
    assert (saves[0].roll_total, saves[0].succeeded) == (
        checks[0].roll_total,
        checks[0].succeeded,
    )
    assert saves[0].dc == checks[0].dc
    # The SaveRolled is emitted FIRST — hosts that already listen for it keep
    # their ordering; the new event follows.
    assert live.event_log.index(saves[0]) < live.event_log.index(checks[0])


def test_concentration_save_carries_its_roll_breakdown() -> None:
    """F2c — the save now reports the kept natural and the flat modifier
    (CON 18 + proficiency at level 5 = +4 + 3)."""
    save = _events(_damage(24), SaveRolled)[0]

    assert save.natural is not None
    assert 1 <= save.natural <= 20
    assert save.modifier == 7
    assert save.roll_total == save.natural + save.modifier
    assert save.sources == []


def test_concentration_check_carries_the_same_roll_breakdown() -> None:
    """The breakdown rides the SPECIFIC event too, so it survives the v0.7
    removal of the duplicate ``SaveRolled``."""
    live = _damage(24)
    save = _events(live, SaveRolled)[0]
    check = _events(live, ConcentrationCheck)[0]

    assert check.natural == save.natural
    assert check.modifier == 7
    assert check.roll_total == check.natural + check.modifier
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

    assert _events(live, SaveRolled)[0].natural == expected_natural
    assert live.rng.randint(1, 20) == expected_next
