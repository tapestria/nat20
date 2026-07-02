"""C09 — Rest & recovery.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 9.

These entries presume a not-yet-existing ``dnd5e_engine.rest`` module — the
import lives inside each test body so today's ``ImportError`` is caught by
the strict xfail marker.
"""

from __future__ import annotations

import random

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import HealingApplied
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(9, "Rest & recovery")
def test_c09_s01_short_rest_hit_dice_healing():
    """C09-S01: Short Rest has no resolvable seam at all — SRD hit-dice
    healing (`1dHD + CON`, floored at 1 per die) cannot be exercised
    anywhere in the public API.

    SRD 5.2 §Short Rest
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/rules-glossary.yml,
    journal page wVuNbEADtC16ejAi: "Spend Hit Point Dice. You can spend one
    or more of your Hit Point Dice to regain Hit Points. For each Hit Point
    Die you spend in this way, roll the die and add your Constitution
    modifier to it. You regain Hit Points equal to the total (minimum of 1
    Hit Point)."); Foundry parity for the per-die floor:
    packages/dnd5e-srd-data/raw_sources/foundry/module/documents/actor/actor.mjs::rollHitDie
    (line ~1966: `max(1, 1${denomination} + @abilities.con.mod)` — the 2024
    "modern" ruleset floors EACH die's individual roll+CON at 1); hit-die
    size dataset source:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/classes/fighter.json
    (`hit_die: "d10"`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/types/intent.py
    (`ActionType.SHORT_REST = "short_rest"`) versus
    packages/dnd5e-engine/src/dnd5e_engine/events.py (`IntentType` — the
    ACTUAL closed set `PlayerIntent.intent_type` accepts; `"short_rest"` is
    not a member); no `hit_dice`/`hit_die` remaining-pool field exists
    anywhere on `Combatant` or `PartyMemberSpec`.
    """
    from dnd5e_engine.rest import HitDicePool, resolve_short_rest

    pool = HitDicePool(hit_die_size=10, dice_remaining=5, dice_total=5)
    outcome = resolve_short_rest(pool, dice_to_spend=3, con_modifier=2, rng=random.Random(7))

    assert outcome.dice_remaining == 2
    assert 9 <= outcome.healed <= 36
    assert len(outcome.rolls) == 3


@xfail_cluster(9, "Rest & recovery")
def test_c09_s02_long_rest_full_hp_and_hit_dice_recovery():
    """C09-S02: Long Rest has no seam at all — SRD 2024 full recovery (ALL
    HP + ALL Hit Dice), not the stale 2014 half-Hit-Dice rule.

    SRD 5.2 §Long Rest
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/rules-glossary.yml,
    journal page NGmwolHLA5ppbIZY: "Regain All HP. You regain all lost Hit
    Points and all spent Hit Point Dice. If your Hit Point maximum was
    reduced, it returns to normal.") — edition-warning finding: the 2014
    sibling text in this same repo's raw sources
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/rules/appendix-e-rules.yml,
    journal page 6cLtjbHn4KV2R7G9, "Long Rest") instead reads a HALF-only
    recovery rule ("up to a number of dice equal to half of the character's
    total number of them (minimum of one die)"); this repo pins SRD 5.2 =
    the 2024 ruleset (`content24/`) — full recovery, not half. Engine: same
    non-existence as C09-S01 — `ActionType` (`types/intent.py`) has no
    `LONG_REST` member, and `IntentType` (`events.py`) has neither.
    """
    from dnd5e_engine.rest import HitDicePool, resolve_long_rest

    pool = HitDicePool(hit_die_size=10, dice_remaining=1, dice_total=5)
    outcome = resolve_long_rest(pool, hp_current=10, hp_max=50)

    assert outcome.hp_current == 50
    assert outcome.dice_remaining == outcome.pool.dice_total == 5


@xfail_cluster(9, "Rest & recovery")
def test_c09_s03_second_wind_has_no_per_rest_usage_cap():
    """C09-S03: Second Wind has no per-rest usage cap — it fires unlimited
    times per combat with nothing to recharge.

    SRD 5.2 §Fighter Class Features, Second Wind ("you can use a Bonus
    Action to regain...", a limited-use feature that recharges on a Short
    or Long Rest); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/fighter/class-features/second-wind.yml
    (top-level `uses: {max: "@scale.fighter.second-wind", spent: 0,
    recovery: [{period: "lr", type: "recoverAll"}, {period: "sr", type:
    "formula", formula: "1"}]}` — a capped, rest-recharged resource) versus
    canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/second-wind.json
    (no top-level `"uses"` key at all;
    packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/feature.py::Feature
    has no `uses` field); engine: exhaustive grep for `"consumption"` /
    `"itemUses"` across
    packages/dnd5e-engine/src/dnd5e_engine/activities/*.py returns ZERO
    hits — no per-feature-use tracking of any kind in the live-combat
    resolver.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c09-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=1,
                    hp_max=100,
                    constitution=14,
                    character_level=5,
                    class_slug="fighter",
                    zone_id="zone:a",
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
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a"], edges=[ZoneEdge(a="zone:a", b="zone:a", distance_ft=0)]
            ),
            rng_seed=3,
        )
        live = _get_live(start.handle)

        # Round 1.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="use_feature", feature_id="second-wind"),
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dodge")
        )
        await advance_monster_turn(start.handle)

        # Round 2 — no rest occurred in between; the second invocation should
        # be rejected.
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="use_feature", feature_id="second-wind"),
        )
        await submit_player_intent(
            start.handle, actor_id="char:hero", intent=PlayerIntent(intent_type="dodge")
        )
        await advance_monster_turn(start.handle)

        return live

    live = run_async(_run())
    heals = [e for e in events_of(live, HealingApplied) if e.target_id == "char:hero"]
    assert len(heals) == 1
