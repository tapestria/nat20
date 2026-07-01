"""Regression — Codex Phase 6 review iter-13 fixes.

P2: per-ability save buckets (save.wisdom.bonus, save.dexterity.bonus)
must NOT flatten into the action-agnostic passive_save_bonus sidecar.
Otherwise effect/save.py would apply a Wisdom-only buff to every save.

P2: seeding a concentration effect via start_combat must also set the
caster Combatant's concentration_effect_id so _build_hydration_payload
derives existing_concentration correctly.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.orchestrator import _build_hydration_payload, _get_live, start_combat
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import (
    ActiveEffect,
    ActiveEffectChange,
    ActiveEffectDuration,
)


def _party():
    return [
        PartyMemberSpec(
            entity_id="char:cleric",
            name="Cleric",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter():
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _topology():
    return SceneTopology(zones=["zone:start"], edges=[])


def test_per_ability_save_bucket_stays_out_of_passive_save_bonus():
    """A Ring of Mind Shielding-style effect (save.wisdom.bonus only)
    must NOT route its bonus to the generic passive_save_bonus sidecar."""

    async def _run():
        ring = ActiveEffect(
            id="effect:mind_shield",
            name="Mind Shield",
            origin="item:ring:effect:mind_shield",
            target_id="char:cleric",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key="save.wisdom.bonus", mode="add", value=2)],
        )
        return await start_combat(
            session_id="sess-per-ability-save",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(ring,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _build_hydration_payload(live, caster=None)
    save_modifiers = payload["save_modifiers"].get("char:cleric", {})
    # Per-ability bucket no longer leaks into the generic sidecar.
    assert save_modifiers.get("passive_save_bonus") is None


def test_generic_save_bucket_still_flows_through():
    """save.bonus (Cloak of Protection style) still flows into the sidecar."""

    async def _run():
        cloak = ActiveEffect(
            id="effect:cloak",
            name="Cloak of Protection",
            origin="item:cloak:effect:cloak",
            target_id="char:cleric",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key="save.bonus", mode="add", value=1)],
        )
        return await start_combat(
            session_id="sess-generic-save",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(cloak,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _build_hydration_payload(live, caster=None)
    save_modifiers = payload["save_modifiers"].get("char:cleric", {})
    assert save_modifiers.get("passive_save_bonus") == "1"


def test_seeded_concentration_sets_caster_concentration_effect_id():
    """A seeded concentration effect cast by the cleric writes
    cleric.concentration_effect_id so the next concentration spell
    correctly drops the seeded one."""

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:cleric",
            target_id="char:cleric",
            duration=ActiveEffectDuration(rounds=10),
            flags={"concentration": True},
        )
        return await start_combat(
            session_id="sess-seed-conc-effect-id",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    cleric = next(c for c in live.initiative if c.entity_id == "char:cleric")
    assert cleric.concentration_effect_id == "effect:bless", (
        "seeded concentration effect must populate caster.concentration_effect_id "
        "so _build_hydration_payload sees existing_concentration"
    )


def test_seeded_concentration_existing_concentration_in_hydration():
    """The hydration payload reflects the seeded concentration."""

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:cleric",
            target_id="char:cleric",
            duration=ActiveEffectDuration(rounds=10),
            flags={"concentration": True},
        )
        return await start_combat(
            session_id="sess-hydration-conc",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    cleric = next(c for c in live.initiative if c.entity_id == "char:cleric")
    payload = _build_hydration_payload(live, caster=cleric)
    existing = payload.get("existing_concentration") or {}
    assert "char:cleric" in existing, (
        "_build_hydration_payload must report the cleric as concentrating on the seeded Bless"
    )


def test_non_caster_origin_does_not_set_concentration_effect_id():
    """An item-origin effect (no caster) doesn't write
    concentration_effect_id even if flags.concentration=True (defensive)."""

    async def _run():
        item_eff = ActiveEffect(
            id="effect:weird_item",
            name="Weird Item",
            origin="item:weird:effect:weird_item",
            target_id="char:cleric",
            duration=ActiveEffectDuration(),
            flags={"concentration": True},  # weird but defensive
        )
        return await start_combat(
            session_id="sess-item-conc-defensive",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(item_eff,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    cleric = next(c for c in live.initiative if c.entity_id == "char:cleric")
    assert cleric.concentration_effect_id is None
