"""Regression — equipped enchantment ActiveEffectChanges reach engine sidecar.

Codex Phase 6 review iter-6 P1: equipped magic items (Cloak of Protection,
+1 Weapon) were synthesized as ActiveEffect instances and passed via
start_combat(active_effects=...), but the engine's own monster-turn
handlers read attack/save state from the legacy sidecar projections in
_build_hydration_payload() — projections that key on ieffect_passive_index
lookups, NOT on ActiveEffect.changes. So a PC's Cloak of Protection AC
bonus would work on player-dispatched attacks (host DispatchContext path)
but NOT when a monster's attack/save was resolved through the engine.

The fix folds int- and dice-formula `mode=add` changes into the same
sidecar surfaces the IR-index path populates (passive_save_bonus,
passive_to_hit_bonus, passive_ac_bonus, passive_damage_bonus). These
tests lock the projection.
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
            entity_id="char:hero",
            name="Hero",
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


def _project(live):
    """Run the hydration payload projection and return its dicts."""
    return _build_hydration_payload(live, caster=None)


def test_cloak_ac_bonus_folds_into_passive_ac_bonus():
    """Cloak of Protection's ac.bonus +1 lands on the target's sidecar."""

    async def _run():
        cloak = ActiveEffect(
            id="effect:cloak_of_protection",
            name="Cloak of Protection",
            origin="item:cloak:effect:cloak_of_protection",
            target_id="char:hero",
            duration=ActiveEffectDuration(),  # permanent while equipped
            changes=[ActiveEffectChange(key="ac.bonus", mode="add", value=1)],
        )
        return await start_combat(
            session_id="sess-ac",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(cloak,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    save_modifiers = payload["save_modifiers"]
    hero_entry = save_modifiers.get("char:hero", {})
    ac_bonus = hero_entry.get("passive_ac_bonus")
    # First fold writes the raw value; subsequent folds prepend a sign.
    assert ac_bonus == "1", (
        f"Cloak ac.bonus +1 must land on passive_ac_bonus; got {ac_bonus!r}"
    )


def test_cloak_save_bonus_folds_into_passive_save_bonus():
    """Cloak of Protection's save.bonus +1 lands on the target's save sidecar."""

    async def _run():
        cloak = ActiveEffect(
            id="effect:cloak_of_protection",
            name="Cloak of Protection",
            origin="item:cloak:effect:cloak_of_protection",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key="save.bonus", mode="add", value=1)],
        )
        return await start_combat(
            session_id="sess-save",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(cloak,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_save = payload["save_modifiers"].get("char:hero", {})
    assert hero_save.get("passive_save_bonus") == "1"


def test_per_ability_save_bonus_folds_into_passive_save_bonus():
    """save.wisdom.bonus +N also lands on passive_save_bonus."""

    async def _run():
        ring = ActiveEffect(
            id="effect:ring_mind_shield",
            name="Ring of Mind Shielding",
            origin="item:ring:effect:ring_mind_shield",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key="save.wisdom.bonus", mode="add", value=2)],
        )
        return await start_combat(
            session_id="sess-wisdom-save",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(ring,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_save = payload["save_modifiers"].get("char:hero", {})
    # iter-13 P2 fix: per-ability buckets (save.wisdom.bonus) no longer
    # flatten into the generic passive_save_bonus — they'd silently
    # leak onto every saving throw. The direct active_effects path
    # via apply_changes_to_check (saving_throw, resolve_check) honors
    # per-ability buckets correctly without the sidecar projection.
    assert hero_save.get("passive_save_bonus") is None


def test_weapon_tagged_effect_does_not_fold_attack_damage_into_sidecar():
    """A +1 Weapon tagged ``applicable_action_types=["attack"]`` must NOT
    fold attack/damage changes into the engine sidecar. The sidecar is
    action-type-agnostic; if we projected them, the engine's attack
    handler would silently buff spell attacks (Fire Bolt etc.) too.

    The host-side build_dispatch_context filter still applies the +1
    weapon bonus on player-dispatched attack actions; the trade-off is
    that monster-driven attack resolution (which goes through the
    engine sidecar) doesn't see the +1 weapon — acceptable since the
    monster isn't wielding the weapon, only the PC.
    """

    async def _run():
        sword = ActiveEffect(
            id="effect:weapon_plus_1",
            name="+1 Weapon",
            origin="item:sword:effect:weapon_plus_1",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            changes=[
                ActiveEffectChange(key="attack.roll.bonus", mode="add", value=1),
                ActiveEffectChange(key="damage.bonus", mode="add", value=1),
            ],
            flags={"applicable_action_types": ["attack"]},
        )
        return await start_combat(
            session_id="sess-sword",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(sword,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_dmg = payload["passive_damage_modifiers"].get("char:hero", {})
    # iter-14 P1: weapon-tagged effects route to the weapon-only sidecar
    # (passive_weapon_to_hit_bonus / passive_weapon_damage_bonus). The
    # broad surface remains None — the attack handler reads it ONLY for
    # action_type="attack", so spell attacks (Fire Bolt etc.) don't
    # inherit the +1 weapon bonus.
    assert hero_dmg.get("passive_to_hit_bonus") is None
    assert hero_dmg.get("passive_weapon_to_hit_bonus") == "1"
    assert hero_dmg.get("passive_damage_bonus") is None
    assert hero_dmg.get("passive_weapon_damage_bonus") == "1"


def test_untagged_attack_bonus_still_folds():
    """An ActiveEffect with no applicable_action_types tag (e.g. Bless)
    still folds attack.roll.bonus / damage.bonus into the sidecar."""

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:hero",
            target_id="char:hero",
            duration=ActiveEffectDuration(rounds=10),
            changes=[ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4")],
            flags={"concentration": True},  # no applicable_action_types
        )
        return await start_combat(
            session_id="sess-bless",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_dmg = payload["passive_damage_modifiers"].get("char:hero", {})
    assert hero_dmg.get("passive_to_hit_bonus") == "1d4"


def test_dice_formula_passes_through():
    """A dice-formula value ("1d4") flows through the projection verbatim;
    the attack handler's parser can fold the dice expression at roll time."""

    async def _run():
        burning_blade = ActiveEffect(
            id="effect:burning_blade",
            name="Burning Blade",
            origin="item:burning_blade:effect:burning_blade",
            target_id="char:hero",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key="damage.bonus", mode="add", value="1d4")],
        )
        return await start_combat(
            session_id="sess-formula",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(burning_blade,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_dmg = payload["passive_damage_modifiers"].get("char:hero", {})
    assert hero_dmg.get("passive_damage_bonus") == "1d4"


def test_advantage_flags_do_not_fold_into_passive_bonus():
    """override-mode flags (advantage / disadvantage) don't land on passive_*
    bonus surfaces — they need their own resolver path. This test pins that the
    fold is gated on mode=add only."""

    async def _run():
        bless_adv = ActiveEffect(
            id="effect:custom",
            name="Custom Adv",
            origin="cast:custom:char:hero",
            target_id="char:hero",
            changes=[
                ActiveEffectChange(
                    key="flags.advantage.saving_throw", mode="override", value=True
                )
            ],
        )
        return await start_combat(
            session_id="sess-adv",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless_adv,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    payload = _project(live)
    hero_save = payload["save_modifiers"].get("char:hero", {})
    assert hero_save.get("passive_save_bonus") is None
