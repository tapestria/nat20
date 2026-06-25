"""Phase 6 — EndCombatResult.final_active_effects + carried_conditions removal."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd5e_engine.outcome import CombatOutcome
from dnd5e_engine.results import EndCombatResult


def test_carried_conditions_field_removed():
    # Pydantic with extra='forbid' rejects the dropped field.
    with pytest.raises(ValidationError):
        CombatOutcome(  # type: ignore[call-arg]
            handle_id="h",
            ended_reason="forced",
            carried_conditions=[],
        )


def test_end_combat_result_has_final_active_effects_field():
    from dnd5e_engine.types.effects import (
        ActiveEffect,
        ActiveEffectChange,
        ActiveEffectDuration,
    )

    bless = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:hero",
        duration=ActiveEffectDuration(rounds=7),
        changes=[ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4")],
    )

    # Implementer reads results.py to fit the constructor shape; pass
    # final_active_effects=(bless,) however the existing constructor
    # supports it (dataclass init or model_validate).
    er = EndCombatResult(
        handle_id="h",
        outcome=CombatOutcome(handle_id="h", ended_reason="forced"),
        events=[],
        final_active_effects=(bless,),
    )
    assert er.final_active_effects == (bless,)


import asyncio  # noqa: E402

from dnd5e_engine.specs import (  # noqa: E402
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)


def _party() -> list[PartyMemberSpec]:
    return [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Aria",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:entrance",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:bbbbbbbbbbbb",
            entity_type="Monster",
            name="Goblin",
            initiative=12,
            hp_current=7,
            hp_max=7,
            zone_id="zone:entrance",
        ),
    ]


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:entrance", "zone:back"],
        edges=[ZoneEdge(a="zone:entrance", b="zone:back", distance_ft=30)],
    )


def test_end_combat_returns_surviving_effects(monkeypatch):
    """Start combat with Bless (rounds=5), end_combat immediately:
    final_active_effects contains the seeded effect."""
    import dnd5e_engine.rules.dice as dice_mod
    from dnd5e_engine.orchestrator import end_combat, start_combat
    from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration

    monkeypatch.setattr(dice_mod.random, "randint", lambda a, b: 10)

    bless = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=5),
    )

    async def _run():
        start = await start_combat(
            session_id="sess",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )
        return await end_combat(start.handle)

    end = asyncio.run(_run())
    assert any(eff.id == "effect:bless" for eff in end.final_active_effects)
