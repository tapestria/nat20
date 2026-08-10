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


def _first_consuming_activity_cost(item) -> int:
    """Mirrors ``_activity_item_use_cost``'s positive-literal rule, iterating
    activities in declaration order — the expected "one invocation" cost when
    no ``activity_id`` is supplied."""
    for activity in item.activities:
        cost = 0
        for target in activity.consumption.targets:
            if target.type != "itemUses":
                continue
            try:
                value = int(str(target.value).strip())
            except ValueError:
                continue
            if value > 0:
                cost += value
        if cost > 0:
            return cost
    return 0


def test_multi_activity_item_usable_at_full_pool():
    """``staff-of-frost`` (cap 10) has 4 consuming cast activities whose
    itemUses costs SUM to 14 > 10 — under the old summing cost model this item
    was rejected even at a full, unspent pool (the same defect class as
    ``staff-of-the-magi``, cap 50 cost 56 — swapped in here because
    ``staff-of-the-magi``'s Retributive Strike activity hits an unrelated,
    pre-existing formula-resolution gap (``@item.uses.value`` token) once the
    charge gate stops rejecting it before resolution; out of scope for this
    charge-cost fix). A plain use_item (no activity_id) must resolve exactly
    the FIRST consuming activity's cost, not the sum of all of them."""
    item = BundledAssetLoader().get_item("staff-of-frost")
    assert item is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[item]))
    expected_cost = _first_consuming_activity_cost(item)
    assert 0 < expected_cost < 10

    async def _run():
        start = await start_combat(
            session_id="sess-staff-full-pool",
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
                item_id="staff-of-frost",
                target_id="mon:foe",
            ),
        )
        return live

    live = asyncio.run(_run())
    assert not _events_of(live, CastFailed), "a full 10-charge pool must never reject"
    counter_key = "item_use:staff-of-frost"
    assert live.custom_counters_by_entity["char:hero"][counter_key] == {"spent": expected_cost}


def test_symbolic_and_negative_targets_ignored():
    """``ball-bearings`` (cap 1) has a spend activity with target value ``1``
    and a recover activity with target value ``-1``. The old summing model
    summed these to 0 and bypassed the gate entirely — a positive-literal-only
    cost model must charge exactly 1 and gate the second use."""
    item = BundledAssetLoader().get_item("ball-bearings")
    assert item is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[item]))

    async def _run():
        start = await start_combat(
            session_id="sess-ball-bearings",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        intent = PlayerIntent(
            intent_type="use_item",
            item_id="ball-bearings",
            target_id="mon:foe",
        )
        await submit_player_intent(start.handle, actor_id="char:hero", intent=intent)
        first_spent = live.custom_counters_by_entity["char:hero"]["item_use:ball-bearings"]["spent"]
        await advance_monster_turn(start.handle)
        await submit_player_intent(start.handle, actor_id="char:hero", intent=intent)
        return live, first_spent

    live, first_spent = asyncio.run(_run())
    assert first_spent == 1
    failed = _events_of(live, CastFailed)
    assert len(failed) == 1
    assert failed[0].reason == "no_charges_remaining"
    assert live.custom_counters_by_entity["char:hero"]["item_use:ball-bearings"] == {"spent": 1}


def test_activity_id_selects_invocation_and_cost():
    """``cube-of-force`` (cap 10) has multiple consuming cast activities with
    distinct costs. Selecting one by ``activity_id`` must charge exactly that
    activity's cost, not the first-in-order activity's."""
    item = BundledAssetLoader().get_item("cube-of-force")
    assert item is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[item]))

    consuming = []
    for activity in item.activities:
        cost = 0
        for target in activity.consumption.targets:
            if target.type == "itemUses":
                cost += int(str(target.value).strip())
        if cost > 0:
            consuming.append((activity.id, cost))
    assert len(consuming) >= 2
    # Pick an activity that is NOT the first consuming one, so the assertion
    # actually distinguishes activity-id selection from "first activity"
    # fallback behavior.
    target_activity_id, target_cost = next(
        (aid, cost) for aid, cost in consuming[1:] if cost != consuming[0][1]
    )

    async def _run():
        start = await start_combat(
            session_id="sess-cube-of-force",
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
                item_id="cube-of-force",
                activity_id=target_activity_id,
                target_id="mon:foe",
            ),
        )
        return live

    live = asyncio.run(_run())
    counter_key = "item_use:cube-of-force"
    assert live.custom_counters_by_entity["char:hero"][counter_key] == {"spent": target_cost}


def test_eval_consumption_max_grammar():
    from dnd5e_engine.orchestrator import _eval_consumption_max

    assert _eval_consumption_max("", remaining=5, cap=7) is None
    assert _eval_consumption_max("3", remaining=5, cap=7) == 3
    assert _eval_consumption_max("@item.uses.value", remaining=5, cap=7) == 5
    assert _eval_consumption_max("@item.uses.max", remaining=5, cap=7) == 7
    assert _eval_consumption_max("min(@item.uses.value,3)", remaining=5, cap=7) == 3
    assert _eval_consumption_max("min(@item.uses.value,3)", remaining=2, cap=7) == 2
    assert _eval_consumption_max("min(5, @item.uses.value)", remaining=3, cap=7) == 3
    assert _eval_consumption_max("@scale.rogue.sneak", remaining=5, cap=7) is None


# wand-of-lightning-bolts: uses.max="7", single ``cast`` activity, itemUses
# base cost "1", ``consumption.scaling`` allowed with max="min(@item.uses.
# value,3)" — a real-corpus item whose scaling ceiling is tighter than its
# raw remaining-charges bound at a fresh pool (min(7,3) == 3).
WAND_SLUG = "wand-of-lightning-bolts"
WAND_COUNTER_KEY = f"item_use:{WAND_SLUG}"


def _load_wand():
    item = BundledAssetLoader().get_item(WAND_SLUG)
    assert item is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[item]))
    return item


def _use_wand_intent(charges_to_spend: int) -> PlayerIntent:
    return PlayerIntent(
        intent_type="use_item",
        item_id=WAND_SLUG,
        target_id="mon:foe",
        charges_to_spend=charges_to_spend,
    )


def test_charges_to_spend_over_scaling_max_rejected():
    """The wand's scaling ceiling at a fresh pool is min(@item.uses.value=7,
    3) == 3 — a request of 4 exceeds it and must reject with
    CastFailed(reason="invalid_charge_spend"), leaving the charge counter
    untouched and the action budget intact."""
    _load_wand()

    async def _run():
        start = await start_combat(
            session_id="sess-wand-over-scaling-max",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_wand_intent(4),
        )
        # The action budget must not have been consumed by the rejected use:
        # a follow-up attack still goes through this same turn.
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
    assert failed[0].reason == "invalid_charge_spend"
    counters = live.custom_counters_by_entity.get("char:hero", {})
    assert WAND_COUNTER_KEY not in counters


def test_charges_to_spend_spends_that_many():
    """A within-bounds charges_to_spend=3 (base cost 1 <= 3 <= ceiling 3)
    spends exactly that many charges."""
    _load_wand()

    async def _run():
        start = await start_combat(
            session_id="sess-wand-spends-requested",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_topology(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=_use_wand_intent(3),
        )
        return live

    live = asyncio.run(_run())
    assert not _events_of(live, CastFailed)
    assert live.custom_counters_by_entity["char:hero"][WAND_COUNTER_KEY] == {"spent": 3}


def test_charges_to_spend_on_unscalable_item_rejected():
    """``pipes-of-haunting``'s single ``save`` activity has
    ``consumption.scaling.allowed == False`` — any charges_to_spend request
    against it must reject with CastFailed(reason="invalid_charge_spend")."""
    _load_pipes()

    async def _run():
        start = await start_combat(
            session_id="sess-pipes-unscalable",
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
                item_id=ITEM_SLUG,
                target_id="mon:foe",
                charges_to_spend=2,
            ),
        )
        return live

    live = asyncio.run(_run())
    failed = _events_of(live, CastFailed)
    assert len(failed) == 1
    assert failed[0].reason == "invalid_charge_spend"
    counters = live.custom_counters_by_entity.get("char:hero", {})
    assert COUNTER_KEY not in counters


def test_charges_to_spend_on_pool_less_item_rejected():
    """``net`` carries no ``uses`` pool at all — there is nothing to scale, so
    a charges_to_spend request against it must reject with
    CastFailed(reason="invalid_charge_spend") rather than silently falling
    through the (pool-less) ungated path."""
    net = BundledAssetLoader().get_item("net")
    assert net is not None
    assert net.uses is None
    set_lib_loader_for_tests(MemoryAssetLoader(items=[net]))

    async def _run():
        start = await start_combat(
            session_id="sess-net-pool-less-scaling",
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
                charges_to_spend=2,
            ),
        )
        return live

    live = asyncio.run(_run())
    failed = _events_of(live, CastFailed)
    assert len(failed) == 1
    assert failed[0].reason == "invalid_charge_spend"
