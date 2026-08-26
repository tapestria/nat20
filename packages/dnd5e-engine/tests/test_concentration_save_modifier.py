"""F1c — real ability + proficiency modifiers on every saving-throw path.

SRD 5.2 §Saving Throws: a save is ``d20 + ability modifier + proficiency
bonus (if proficient in that save)``. Before F1c the orchestrator projected
DEX only, so every other ability saved at a flat +0.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from dnd5e_engine.events import SaveRolled
from dnd5e_engine.orchestrator import _LiveCombat, _project_target_modifiers
from dnd5e_engine.types.combat import Combatant


def _pc(**kw: Any) -> Combatant:
    base: dict[str, Any] = dict(
        entity_id="char:a",
        entity_type="Character",
        name="A",
        initiative=10,
        hp_current=10,
        hp_max=10,
        character_level=5,
    )
    return Combatant(**{**base, **kw})


def _fake_live() -> _LiveCombat:
    """Minimal ``_LiveCombat`` with no active effects — the projection under
    test reads only ``live.active_effects``."""
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


def test_con_save_projection_includes_all_abilities() -> None:
    c = _pc(constitution=18, wisdom=12, save_proficiencies=["con"], character_level=5)
    entry, _ = _project_target_modifiers(c, _fake_live(), {})
    assert entry["saves"] == {"str": 0, "dex": 0, "con": 7, "int": 0, "wis": 1, "cha": 0}


def test_projection_uses_monster_proficiency_override() -> None:
    m = Combatant(
        entity_id="mon:x",
        entity_type="Monster",
        name="X",
        initiative=1,
        hp_current=5,
        hp_max=5,
        dexterity=14,
        wisdom=16,
        proficiency_bonus_override=4,
        save_proficiencies=["wis"],
    )
    entry, _ = _project_target_modifiers(m, _fake_live(), {})
    assert entry["saves"]["wis"] == 3 + 4
    assert entry["saves"]["dex"] == 2


def test_concentration_save_applies_con_modifier() -> None:
    """Same-seed A/B: a CON 18, CON-save-proficient L5 caster's concentration
    check rolls +7 above an otherwise identical CON 10, non-proficient one."""
    from dnd5e_engine import orchestrator as orch

    def _roll(constitution: int, proficient: bool) -> int:
        import random

        live = _fake_live()
        caster = _pc(
            constitution=constitution,
            save_proficiencies=["con"] if proficient else [],
        )
        live.initiative = [caster]
        live.rng = random.Random(20260826)
        live.tracked_hp = {caster.entity_id: 40}
        live.concentration_chain = {caster.entity_id: [("mon:x", "eff:1", "spell:hold-person")]}
        orch._emit_apply_damage(
            live,
            orch.DamageApplied(
                target_id=caster.entity_id,
                amount=10,
                damage_type="fire",
                source_id="mon:x",
                is_overkill=False,
            ),
        )
        rolled = [e for e in live.event_log if isinstance(e, SaveRolled)]
        assert len(rolled) == 1
        return rolled[0].roll_total

    assert _roll(18, True) - _roll(10, False) == 7
