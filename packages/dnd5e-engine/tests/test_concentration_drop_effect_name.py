"""Task 9-A FIX 3 — ConcentrationDropped.effect_name representation consistency.

The whole effect lifecycle keys on the resolver-emitted effect *id*
(``effect:<name-slug>``): ``concentration_chain`` / ``conditions_by_effect`` use
``effect.id``, and ``_build_hydration_payload`` projects
``existing_concentration[caster]["effect_name"] = concentration_effect_id`` (the
id). ``_drop_concentration`` was the lone divergent site: it emitted
``ConcentrationDropped.effect_name`` as ``eff.name`` ("Bane") when the effect was
still in ``active_effects`` but as the id ("effect:bane") otherwise — two different
representations from one emit site, neither matching the id the rest of the
lifecycle consistently uses. This locks the id as the single representation.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.events import ConcentrationDropped
from dnd5e_engine.orchestrator import _drop_concentration, _get_live, start_combat
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration

_CASTER = "char:aaaaaaaaaaaa"
_TARGET = "mon:111111111111"


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id=_CASTER,
            name="Cleric",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id=_TARGET,
            entity_type="Monster",
            name="Goblin",
            initiative=10,
            hp_current=7,
            hp_max=7,
            zone_id="zone:start",
        ),
    ]


def test_concentration_dropped_effect_name_is_the_effect_id() -> None:
    """ConcentrationDropped.effect_name must carry the effect *id* (``effect:bane``),
    matching ``concentration_effect_id`` and the ``conditions_by_effect`` keys —
    not the human-readable ``ActiveEffect.name`` ("Bane")."""
    bane = ActiveEffect(
        id="effect:bane",
        name="Bane",
        origin=f"cast:bane:{_CASTER}",
        target_id=_TARGET,
        duration=ActiveEffectDuration(rounds=10),
        flags={"concentration": True},
    )
    result = asyncio.run(
        start_combat(
            session_id="sess-conc-drop-name",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:start"], edges=[]),
            rng_seed=1,
            active_effects=(bane,),
        )
    )
    live = _get_live(result.handle)
    # Sanity: the effect is live in active_effects (the branch that previously
    # produced eff.name) AND tracked on the chain.
    assert any(e.id == "effect:bane" for e in live.active_effects.get(_TARGET, []))

    before = len(live.event_log)
    _drop_concentration(live, _CASTER)
    emitted = [
        ev for ev in live.event_log[before:] if isinstance(ev, ConcentrationDropped)
    ]

    assert len(emitted) == 1
    assert emitted[0].target_id == _CASTER
    assert emitted[0].effect_name == "effect:bane", (
        "ConcentrationDropped.effect_name must be the effect id used throughout "
        f"the lifecycle, got {emitted[0].effect_name!r}"
    )
