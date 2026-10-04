"""C25 — the grid is the only spatial backend, and a concentration check emits
one event.

``start_combat`` takes a required ``GridScene``; the zone graph and its
``scene_zones`` keyword are gone. A template the engine can't map onto the grid
still resolves, against its named target.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from dnd5e_engine.events import ConcentrationCheck, MoveFailed, SaveRolled
from dnd5e_engine.orchestrator import _extends_rage, start_combat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import GridScene
from dnd5e_engine.testing import registry
from tests.c20_support import act, combatant, events, foe, pc, start, wizard


def _open(**kwargs: object) -> None:
    asyncio.run(
        start_combat(session_id="c25", party=[pc()], encounter=[foe()], rng_seed=1, **kwargs)
    )


def test_the_removed_scene_zones_keyword_is_a_type_error() -> None:
    before = set(registry)
    with pytest.raises(TypeError, match="scene_zones"):
        _open(scene_zones=None, grid_scene=GridScene(width=10, height=10))
    assert set(registry) == before


def test_start_combat_requires_a_grid_scene() -> None:
    before = set(registry)
    with pytest.raises(TypeError, match="grid_scene"):
        _open()
    assert set(registry) == before


def test_a_none_grid_scene_is_refused_before_any_state_exists() -> None:
    before = set(registry)
    with pytest.raises(ValueError, match="grid_scene is required"):
        _open(grid_scene=None)
    assert set(registry) == before


def test_a_zone_name_destination_is_unreachable_on_the_grid() -> None:
    """A host still naming zones: nothing moves and nothing is spent."""
    handle, live = start([pc()], seed=1)
    budget = combatant(live).movement_remaining
    act(handle, "char:hero", intent_type="move", target_zone_id="zone:b")
    assert [e.reason for e in events(live, MoveFailed)] == ["unreachable"]
    assert live.actor_zone["char:hero"] == cell_id(0, 0)
    assert combatant(live).movement_remaining == budget


def test_an_unmappable_area_targets_the_named_target_only(caplog: pytest.LogCaptureFixture) -> None:
    """Confusion's sphere size is a formula the engine can't map, so the cast
    falls back to its named target — never its neighbour, never the caster."""
    caster = wizard(spells_known=["confusion"], spell_slots={4: 1}, character_level=7)
    near = foe(entity_id="mon:a", name="A", zone_id=cell_id(4, 0))
    neighbour = foe(entity_id="mon:b", name="B", zone_id=cell_id(4, 1))
    handle, live = start([caster], seed=1, encounter=[near, neighbour])
    with caplog.at_level(logging.WARNING, logger="dnd5e_engine.orchestrator"):
        act(
            handle,
            "char:wiz",
            intent_type="cast_spell",
            spell_id="confusion",
            target_id="mon:a",
            slot_level=4,
        )
    assert [e.target_id for e in events(live, SaveRolled)] == ["mon:a"]
    assert "falling back to the named target" in caplog.text


def test_an_enemy_concentration_check_does_not_extend_rage() -> None:
    """SRD 5.2 Rage: "Force an enemy to make a saving throw." The attack or save
    that dealt the damage already extends Rage; the concentration check the
    damage triggers does not count again."""
    _handle, live = start([pc("char:barb")], seed=1)
    check = ConcentrationCheck(target_id="mon:foe", dc=10, roll_total=3, succeeded=False)
    save = SaveRolled(target_id="mon:foe", ability="con", dc=10, roll_total=3, succeeded=False)
    assert not _extends_rage(live, "char:barb", check)
    assert _extends_rage(live, "char:barb", save)
