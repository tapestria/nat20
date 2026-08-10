"""Item-charge spend gate — Piece B, Task 3.

A ``use_item`` intent against an item carrying a typed ``Item.uses`` pool
(charges, e.g. Pipes of Haunting: 3 charges, ``itemUses`` consumption on its
single ``save`` activity) must spend a ``item_use:<slug>`` sidecar counter on
the actor and reject once the pool is exhausted — mirroring the Cluster 9
``feature_use:<slug>`` gate. Items with NO ``uses`` pool (~280 of the corpus)
stay entirely ungated, proven here by the existing potion-of-healing path.

Fixture setup is lifted verbatim from
``test_orchestrator_pc_resolution_typed.py`` (``_party``/``_encounter``/
``_topology``/``_events_of``) — production-shape items always come from
``BundledAssetLoader().get_item(<slug>)``, never hand-built.
"""

from __future__ import annotations

import asyncio

import pytest
from dnd5e_srd_data import MemoryAssetLoader
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import CastFailed, SaveRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge

# Chosen via the scan in the task brief (Step 1): the non-cast charged item
# with the smallest deterministic pool.
#
#   uv run python - <<'EOF'
#   from dnd5e_srd_data.loader import BundledAssetLoader
#   ld = BundledAssetLoader()
#   for slug in ld.list_slugs("items"):
#       it = ld.get_item(slug)
#       if it is None or it.uses is None or not it.uses.max:
#           continue
#       kinds = {a.kind for a in it.activities
#                if any(t.type == "itemUses" for t in a.consumption.targets)}
#       if kinds and "cast" not in kinds:
#           print(slug, it.uses.max, sorted(kinds))
#   EOF
#
# ``pipes-of-haunting``: uses.max="3", a single ``save`` activity whose sole
# ``itemUses`` consumption target has value="1" (charge cost 1/use) — small,
# single-activity, deterministic (Wisdom save, no attack roll noise).
ITEM_SLUG = "pipes-of-haunting"
COUNTER_KEY = f"item_use:{ITEM_SLUG}"


def _topology() -> SceneTopology:
    return SceneTopology(
        zones=["zone:start"],
        edges=[ZoneEdge(a="zone:start", b="zone:start", distance_ft=0)],
    )


def _party(**pc_overrides: object) -> list[PartyMemberSpec]:
    base = dict(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=20,
        hp_max=20,
        attack_bonus=5,
        strength=16,
        dexterity=16,
        zone_id="zone:start",
    )
    base.update(pc_overrides)
    return [PartyMemberSpec(**base)]  # type: ignore[arg-type]


def _encounter() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            zone_id="zone:start",
        )
    ]


@pytest.fixture(autouse=True)
def _reset_lib_loader():
    yield
    set_lib_loader_for_tests(None)


def _events_of(live, kind):
    return [e for e in live.event_log if isinstance(e, kind)]


def _use_pipes_intent() -> PlayerIntent:
    return PlayerIntent(
        intent_type="use_item",
        item_id=ITEM_SLUG,
        target_id="mon:foe",
    )


def _load_pipes():
    item = BundledAssetLoader().get_item(ITEM_SLUG)
    assert item is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[item]))
    return item


def test_use_item_spends_a_charge():
    """A single use_item intent against a fresh (unseeded) charge pool spends
    exactly one charge (the item's per-activity ``itemUses`` cost)."""
    _load_pipes()

    async def _run():
        start = await start_combat(
            session_id="sess-pipes-spend",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_pipes_intent(),
        )
        return live

    live = asyncio.run(_run())
    assert live.custom_counters_by_entity["char:hero"][COUNTER_KEY] == {"spent": 1}
    assert _events_of(live, SaveRolled), "the save activity must still resolve"


def test_use_item_rejected_when_exhausted():
    """A charge pool seeded at its cap rejects the use_item intent with
    CastFailed(reason='no_charges_remaining'), resolves nothing, and does not
    burn the action — a follow-up attack still resolves this turn."""
    _load_pipes()

    async def _run():
        start = await start_combat(
            session_id="sess-pipes-exhausted",
            party=_party(custom_counters={COUNTER_KEY: {"spent": 3}}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_pipes_intent(),
        )
        # The action budget must not have been consumed by the rejected use:
        # a follow-up attack (no weapon fetched — attack resolves emptily,
        # but must not raise IntentRejectedError("no_action_economy")) still
        # goes through this same turn.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack",
                weapon_id="unarmed-strike",
                target_id="mon:foe",
            ),
        )
        return live

    live = asyncio.run(_run())
    failed = _events_of(live, CastFailed)
    assert len(failed) == 1
    assert failed[0].reason == "no_charges_remaining"
    assert not _events_of(live, SaveRolled), "a rejected use must not resolve its activity"
    assert live.custom_counters_by_entity["char:hero"][COUNTER_KEY] == {"spent": 3}


def test_use_item_without_pool_is_ungated():
    """``net`` (the existing ``test_use_item_resolves_item_activities`` fixture
    item) carries no ``uses`` pool — the use_item path stays entirely
    ungated: it resolves normally and writes no item_use: counter."""
    net = BundledAssetLoader().get_item("net")
    assert net is not None
    assert net.uses is None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[net]))

    async def _run():
        start = await start_combat(
            session_id="sess-net-ungated",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="use_item",
                item_id="net",
                target_id="mon:foe",
            ),
        )
        return live

    live = asyncio.run(_run())
    assert _events_of(live, SaveRolled), "net must still resolve its save activity"
    counters = live.custom_counters_by_entity.get("char:hero", {})
    assert "item_use:net" not in counters


def test_partial_seed_spend_accumulates():
    """Seeding at cap-1 lets exactly one more use through (reaching the cap),
    and a second use past the cap rejects."""
    _load_pipes()

    async def _run():
        start = await start_combat(
            session_id="sess-pipes-partial",
            party=_party(custom_counters={COUNTER_KEY: {"spent": 2}}),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        # ``pipes-of-haunting``'s save activity is a full Action — it ends the
        # actor's turn, so a second use this same combat needs a monster turn
        # in between (mirrors ``test_c09_s03_second_wind_has_no_per_rest_
        # usage_cap``'s successive-turn pattern).
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_pipes_intent(),
        )
        first_spent = live.custom_counters_by_entity["char:hero"][COUNTER_KEY]["spent"]
        await advance_monster_turn(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_pipes_intent(),
        )
        return live, first_spent

    live, first_spent = asyncio.run(_run())
    assert first_spent == 3
    failed = _events_of(live, CastFailed)
    assert len(failed) == 1
    assert failed[0].reason == "no_charges_remaining"
    assert live.custom_counters_by_entity["char:hero"][COUNTER_KEY] == {"spent": 3}
