"""Phase 6 — concentration / repeat-save linkage uses (target_id, id, origin).

Locks the Task 8 rekey. Two casters / two Bless effects had silently
merged into one concentration record under the prior effect_name-keyed
model; this test asserts the new tuple-keyed linkage keeps them
distinct.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    PartyMemberSpec,
    SceneTopology,
)
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration


def _party() -> list[PartyMemberSpec]:
    # Two PCs so we can model two casters.
    return [
        PartyMemberSpec(
            entity_id="char:aaaaaaaaaaaa",
            name="Hero A",
            initiative=15,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
        PartyMemberSpec(
            entity_id="char:bbbbbbbbbbbb",
            name="Hero B",
            initiative=12,
            hp_current=20,
            hp_max=20,
            zone_id="zone:start",
        ),
    ]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:111111111111",
            entity_type="Monster",
            name="Bandit",
            initiative=10,
            hp_current=11,
            hp_max=11,
            zone_id="zone:start",
        ),
    ]


def _topology() -> SceneTopology:
    return SceneTopology(zones=["zone:start"], edges=[])


def test_two_blesses_track_independent_identity():
    """Two Bless effects with different origins on different targets must be
    kept distinct in _LiveCombat.active_effects under (target_id, id, origin)
    identity."""

    bless_a = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=10),
        flags={"concentration": True},
    )
    bless_b = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:2",
        target_id="char:bbbbbbbbbbbb",
        duration=ActiveEffectDuration(rounds=10),
        flags={"concentration": True},
    )

    result = asyncio.run(
        start_combat(
            session_id="sess-two-bless",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless_a, bless_b),
        )
    )
    live = _get_live(result.handle)

    assert "char:aaaaaaaaaaaa" in live.active_effects
    assert "char:bbbbbbbbbbbb" in live.active_effects
    a_bless = live.active_effects["char:aaaaaaaaaaaa"]
    b_bless = live.active_effects["char:bbbbbbbbbbbb"]
    assert len(a_bless) == 1
    assert len(b_bless) == 1
    assert a_bless[0].origin == "cast:bless:1"
    assert b_bless[0].origin == "cast:bless:2"


def test_same_target_two_origins_no_merge():
    """One target, two Bless instances (same id, different origin) coexist
    under the identity-tuple model — the prior effect_name-keyed linkage
    would have collapsed them into one."""

    bless_a = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:1",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=10),
    )
    bless_b = ActiveEffect(
        id="effect:bless",
        name="Bless",
        origin="cast:bless:2",
        target_id="char:aaaaaaaaaaaa",
        duration=ActiveEffectDuration(rounds=10),
    )

    result = asyncio.run(
        start_combat(
            session_id="sess-same-target",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
            active_effects=(bless_a, bless_b),
        )
    )
    live = _get_live(result.handle)

    a_effects = live.active_effects["char:aaaaaaaaaaaa"]
    assert len(a_effects) == 2
    assert {e.origin for e in a_effects} == {"cast:bless:1", "cast:bless:2"}


def test_dedupe_by_identity_drops_exact_duplicates():
    """Direct unit on rules.effects.dedupe_by_identity (Task 4)."""
    from dnd5e_engine.rules.effects import dedupe_by_identity

    a = ActiveEffect(id="effect:bless", name="Bless", origin="cast:bless:1", target_id="t1")
    a_dupe = ActiveEffect(id="effect:bless", name="Bless", origin="cast:bless:1", target_id="t1")
    b = ActiveEffect(id="effect:bless", name="Bless", origin="cast:bless:2", target_id="t1")

    out = dedupe_by_identity([a, a_dupe, b])
    assert len(out) == 2
    assert out[0].origin == "cast:bless:1"
    assert out[1].origin == "cast:bless:2"
