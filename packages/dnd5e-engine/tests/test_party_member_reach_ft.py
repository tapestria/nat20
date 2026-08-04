"""C02-S03 — ``PartyMemberSpec.reach_ft`` threads an equipped reach weapon's
reach onto the live ``Combatant``.

``Combatant.melee_reach_ft: int = 5`` already exists, but ``PartyMemberSpec``
had no ``reach_ft`` field to source it from, and ``orchestrator._build_pc_combatants``
never threaded any such value in — a glaive-wielding PC's ``Combatant`` always
read the hardcoded default. Focused unit test on the spec-default +
threading seam; the full start_combat -> get_live path is covered end to
end by ``tests/e2e/test_c02_small_mechanics.py::test_c02_s03_...``.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _build_pc_combatants
from dnd5e_engine.specs import PartyMemberSpec


def _pc(**overrides) -> PartyMemberSpec:
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=10,
        hp_current=20,
        hp_max=20,
        zone_id="zone:a",
    )
    base.update(overrides)
    return PartyMemberSpec(**base)


def test_reach_ft_defaults_to_five_mirroring_melee_reach_ft_default():
    assert _pc().reach_ft == 5


def test_reach_ft_threads_into_combatant_melee_reach_ft():
    combatants: list = []
    _build_pc_combatants(
        [_pc(reach_ft=10)],
        combatants,
        actor_zone={},
        tracked_hp={},
        spell_slots_by_entity={},
        spells_known_by_entity={},
        custom_counters_by_entity={},
    )
    assert combatants[0].melee_reach_ft == 10


def test_reach_ft_default_still_yields_five_on_combatant():
    combatants: list = []
    _build_pc_combatants(
        [_pc()],
        combatants,
        actor_zone={},
        tracked_hp={},
        spell_slots_by_entity={},
        spells_known_by_entity={},
        custom_counters_by_entity={},
    )
    assert combatants[0].melee_reach_ft == 5
