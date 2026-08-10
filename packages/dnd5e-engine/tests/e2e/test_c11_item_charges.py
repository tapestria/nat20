"""C11 — Item charge depletion + dawn recharge, against the real corpus.

New cluster (Piece B, Task 4). Model: ``test_c09_rest.py::
test_c09_s03_second_wind_has_no_per_rest_usage_cap`` (seeded ``start_combat``
+ scripted intents + event-log asserts, sync test wrapping an inner
``async def _run()`` via ``run_async``). Where c09-s03 pins the
``feature_use:<slug>`` per-rest cap, this pins the mirrored
``item_use:<slug>`` charge gate end-to-end against a real bundled item —
Pipes of Haunting, ``uses.max="3"``, single ``save`` activity whose sole
``itemUses`` consumption target costs 1 charge/use — loaded via the
autouse ``BundledAssetLoader`` in ``tests/e2e/conftest.py`` (no hand-built
item, no pre-seeded ``custom_counters``).

SRD 5.2 §Pipes of Haunting
(packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/equipment24/equipment/pipes-of-haunting.yml:
"These pipes have 3 charges and regain 1d3 expended charges daily at dawn.
You can take a Magic action to play them and expend 1 charge to create an
eerie, spellbinding tune. Each creature of your choice within 30 feet of you
must succeed on a DC 15 Wisdom saving throw or have the Frightened
condition..."); the same file's typed ``uses`` block is the depletion/
recharge contract this test exercises: ``max: '3'``, ``recovery: [{period:
dawn, type: formula, formula: 1d3}]``.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import CastFailed, SaveRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.rest import recover_item_uses
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import events_of, run_async, single_zone

ITEM_SLUG = "pipes-of-haunting"
COUNTER_KEY = f"item_use:{ITEM_SLUG}"


def _use_pipes_intent() -> PlayerIntent:
    return PlayerIntent(intent_type="use_item", item_id=ITEM_SLUG, target_id="mon:foe")


def test_c11_s01_pipes_of_haunting_charge_depletion_and_dawn_recharge():
    """C11-S01: a 3-charge item depletes its pool over successive uses, the
    4th use is rejected loudly, and a dawn rest recharges the pool per its
    own ``1d3`` formula — no pre-seeded counters, real corpus item.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c11-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    zone_id="zone:start",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=30,
                    hp_current=500,
                    hp_max=500,
                    zone_id="zone:start",
                )
            ],
            scene_zones=single_zone(),
            rng_seed=1,
        )
        live = _get_live(start.handle)

        # N=3 charges: 3 successive full-Action turns (Play Pipes ends the
        # turn) deplete the pool, each followed by a monster turn (mirrors
        # c09-s03's successive-turn loop for a full-Action, no-rest-between
        # resource). The 4th use finds an empty pool; a rejected use burns no
        # action economy (Task 3), so the turn stays with the hero and there
        # is no monster turn to advance past it.
        for _round in range(3):
            await submit_player_intent(
                start.handle, actor_id="char:hero", intent=_use_pipes_intent()
            )
            await advance_monster_turn(start.handle)
        await submit_player_intent(start.handle, actor_id="char:hero", intent=_use_pipes_intent())

        return live

    live = run_async(_run())

    # Exactly 3 uses resolved (the item's sole activity is a `save`; each
    # resolved use rolls the target's DC 15 Wisdom save).
    saves = [e for e in events_of(live, SaveRolled) if e.target_id == "mon:foe"]
    assert len(saves) == 3

    # The 4th is rejected loudly, charge pool exhausted.
    rejections = [
        e
        for e in events_of(live, CastFailed)
        if e.actor_id == "char:hero" and e.reason == "no_charges_remaining"
    ]
    assert len(rejections) == 1

    assert live.custom_counters_by_entity["char:hero"][COUNTER_KEY] == {"spent": 3}

    # Recharge leg (pure, out-of-combat companion — rest.py has no
    # resolvable in-combat seam, same non-existence class c09-s01/s02
    # document for Short/Long Rest): feed the live counters + the item's OWN
    # typed recovery rule into recover_item_uses at a "dawn" period.
    item = BundledAssetLoader().get_item(ITEM_SLUG)
    assert item is not None
    counters = live.custom_counters_by_entity["char:hero"]
    recovered = recover_item_uses(
        counters,
        "dawn",
        {ITEM_SLUG: item.uses.recovery},
        rng=random.Random(0),
    )

    # formula "1d3" recharge, deterministic under rng=random.Random(0): a
    # regain of 2 brings spent 3 -> 1. The seed is fixed, so this exact value
    # is the point — not just a sanity bound on the 1d3 range.
    assert recovered[ITEM_SLUG] == 1
