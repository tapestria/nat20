"""Regression — start_combat(active_effects=...) seeds lifecycle indexes.

Codex Phase 6 review iter-3 P2: the seeding block only populated
``live.active_effects`` and ``combatant.conditions``. The runtime
concentration-drop and end-of-turn repeat-save logic reads from
``concentration_chain`` and ``conditions_by_effect`` (populated by
``_record_effect_lifecycle_links`` from runtime EffectApplied events),
so a seeded concentration effect (Bless / Hold Person) would never
trigger concentration cleanup and would never fire its repeat save.
This test locks the fix that seeding also populates those indexes.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.orchestrator import _get_live, start_combat
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
            entity_id="char:caster",
            name="Cleric",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
        PartyMemberSpec(
            entity_id="char:fighter",
            name="Fighter",
            initiative=12,
            hp_current=25,
            hp_max=25,
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


def test_seeded_concentration_effect_enters_concentration_chain():
    """Bless seeded via active_effects → concentration_chain[caster] has entry.

    Without this, the caster taking damage would not trigger a concentration
    save and Bless would persist indefinitely past damage events.
    """

    async def _run():
        bless = ActiveEffect(
            id="effect:bless",
            name="Bless",
            origin="cast:bless:char:caster",
            target_id="char:fighter",
            duration=ActiveEffectDuration(rounds=10),
            changes=[
                ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4"),
            ],
            flags={"concentration": True},
        )
        return await start_combat(
            session_id="sess-seed-conc",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    assert "char:caster" in live.concentration_chain
    chain = live.concentration_chain["char:caster"]
    assert any(
        identity == ("char:fighter", "effect:bless", "cast:bless:char:caster") for identity in chain
    )


def test_seeded_effect_with_statuses_enters_conditions_by_effect():
    """Hold Person seeded → conditions_by_effect attributes paralyzed to it.

    Without this, when Hold Person expires (concentration breaks, duration
    ticks), the paralyzed condition would not be cleared because the
    cascade can't find which condition belongs to which effect.
    """

    async def _run():
        hold = ActiveEffect(
            id="effect:hold_person",
            name="Hold Person",
            origin="cast:hold_person:char:caster",
            target_id="mon:foe",
            duration=ActiveEffectDuration(rounds=10),
            statuses={"paralyzed"},
            flags={"concentration": True},
        )
        return await start_combat(
            session_id="sess-seed-status",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(hold,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    key = ("mon:foe", "effect:hold_person", "cast:hold_person:char:caster")
    assert key in live.conditions_by_effect
    assert "paralyzed" in live.conditions_by_effect[key]


def test_seeded_item_enchantment_does_not_enter_concentration_chain():
    """Item-origin effects ("item:...") aren't concentration-managed.

    Equipped magic items (+1 weapon, Cloak of Protection) get synthesized
    via _project_party_equipped_enchantments with origin "item:..." — they
    have no caster, persist while equipped, and must not appear in any
    PC's concentration_chain.
    """

    async def _run():
        sword = ActiveEffect(
            id="effect:weapon_plus_1",
            name="+1 Weapon",
            origin="item:sword_id:effect:weapon_plus_1",
            target_id="char:fighter",
            changes=[
                ActiveEffectChange(key="attack.roll.bonus", mode="add", value=1),
            ],
        )
        return await start_combat(
            session_id="sess-seed-item",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(sword,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    # Nothing in concentration_chain at all (no concentration flag, no
    # cast origin).
    assert live.concentration_chain == {}


def test_seeded_effect_without_concentration_skips_chain():
    """A non-concentration spell effect (Mage Armor-style) stays out of the chain."""

    async def _run():
        mage_armor = ActiveEffect(
            id="effect:mage_armor",
            name="Mage Armor",
            origin="cast:mage_armor:char:caster",
            target_id="char:fighter",
            duration=ActiveEffectDuration(seconds=28800),  # 8 hours
            changes=[ActiveEffectChange(key="ac.bonus", mode="add", value=3)],
            # No "concentration" flag.
        )
        return await start_combat(
            session_id="sess-seed-no-conc",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(mage_armor,),
        )

    result = asyncio.run(_run())
    live = _get_live(result.handle)
    assert live.concentration_chain == {}
