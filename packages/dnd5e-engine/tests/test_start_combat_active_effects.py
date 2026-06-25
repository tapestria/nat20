"""Phase 6 — start_combat seeds active_effects."""

from __future__ import annotations

import asyncio

from dnd5e_engine.specs import (
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



def test_start_combat_default_active_effects_empty():
    """No active_effects parameter ⇒ engine starts with empty registry."""
    from dnd5e_engine.orchestrator import _get_live, start_combat

    result = asyncio.run(start_combat(
        session_id="sess1",
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
    ))
    live = _get_live(result.handle)
    assert live.active_effects == {}



def test_start_combat_seeds_active_effects():
    """Non-empty active_effects ⇒ partitioned by target_id in registry."""
    from dnd5e_engine.orchestrator import _get_live, start_combat
    from dnd5e_engine.types.effects import (
        ActiveEffect,
        ActiveEffectChange,
        ActiveEffectDuration,
    )

    bless = ActiveEffect(
        id="effect:bless00000001",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=5),
        changes=[ActiveEffectChange(key="attack.roll.bonus", mode="add", value="1d4")],
        flags={"concentration": True},
    )
    result = asyncio.run(start_combat(
        session_id="sess2",
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
        active_effects=(bless,),
    ))
    live = _get_live(result.handle)
    assert "char:aaaaaaaaaaaa" in live.active_effects
    assert live.active_effects["char:aaaaaaaaaaaa"][0].id == "effect:bless00000001"



def test_start_combat_unions_statuses_into_combatant_conditions():
    """Effect.statuses are unioned into the target combatant's conditions."""
    from dnd5e_engine.orchestrator import _get_live, start_combat
    from dnd5e_engine.types.effects import ActiveEffect

    hold = ActiveEffect(
        id="effect:hold0000person",
        name="Hold Person",
        origin="cast:hold_person:1",
        target_id="char:aaaaaaaaaaaa",
        statuses={"paralyzed"},
    )
    result = asyncio.run(start_combat(
        session_id="sess3",
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
        active_effects=(hold,),
    ))
    live = _get_live(result.handle)
    pc = next(c for c in live.initiative if c.entity_id == "char:aaaaaaaaaaaa")
    condition_slugs = {ac.condition for ac in pc.conditions}
    assert "paralyzed" in condition_slugs
    # And the seeding tags the source_effect_id for later cleanup.
    para = next(ac for ac in pc.conditions if ac.condition == "paralyzed")
    assert para.source_effect_id == "effect:hold0000person"
    assert para.scope == "combat"



def test_start_combat_skips_effect_targeting_unknown_entity():
    """Effect for an entity not in this combat ⇒ stored in registry but no
    combatant mutation (no raise)."""
    from dnd5e_engine.orchestrator import _get_live, start_combat
    from dnd5e_engine.types.effects import ActiveEffect

    stray = ActiveEffect(
        id="effect:stray000ghost",
        name="Stray",
        origin="cast:stray:1",
        target_id="char:zzzzzzzzzzzz",
        statuses={"paralyzed"},
    )
    result = asyncio.run(start_combat(
        session_id="sess4",
        party=_party(),
        encounter=_encounter(),
        scene_zones=_topology(),
        rng_seed=1,
        active_effects=(stray,),
    ))
    live = _get_live(result.handle)
    # Registry still partitions by the (unknown) target_id.
    assert "char:zzzzzzzzzzzz" in live.active_effects
    # No combatant gained the paralyzed status.
    for c in live.initiative:
        assert all(ac.condition != "paralyzed" for ac in c.conditions)
