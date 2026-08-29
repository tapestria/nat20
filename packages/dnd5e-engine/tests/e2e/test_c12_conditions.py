"""C12 — Conditions enforced.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 12
(specs/catalog-v2/c12.md). All setups use ``GridScene`` + cell-id
positions (``dnd5e_engine.spatial.cell_id``), never ``SceneTopology``/
zones, seeding conditions via ``ActiveEffect(statuses={...})`` at
``start_combat`` time.
"""

from __future__ import annotations

import pytest

from dnd5e_engine import ActiveEffect, PlayerIntent
from dnd5e_engine.events import (
    AttackRolled,
    ConditionApplied,
    MoveFailed,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


def test_c12_s01_incapacitated_blocks_attack_intent():
    """C12-S01: SRD 5.2 Conditions, Incapacitated — "You can't take any
    action, Bonus Action, or Reaction."
    (packs/_source/content24/appendices/rules-glossary.yml:1291).
    ``_validate_intent_preconditions`` reads no conditions today, so the
    attack silently resolves instead of being rejected.
    """
    from dnd5e_engine.orchestrator import IntentRejectedError

    async def _run():
        start = await start_combat(
            session_id="e2e-c12-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=1,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            active_effects=[
                ActiveEffect(
                    id="effect:incap",
                    name="Incap",
                    origin="test:incap",
                    target_id="char:hero",
                    statuses={"incapacitated"},
                )
            ],
            rng_seed=1,
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )

    with pytest.raises(IntentRejectedError) as exc_info:
        run_async(_run())
    assert exc_info.value.reason == "actor_incapacitated"


def test_c12_s02_paralyzed_target_grants_advantage_and_auto_crit_within_5ft():
    """C12-S02: SRD 5.2 Conditions, Paralyzed — attack rolls against you
    have Advantage, and any hit within 5 ft is an automatic Critical Hit
    (packs/_source/content24/appendices/rules-glossary.yml:1376).
    ``conditions_grant_advantage_on_attack`` reads Paralyzed but is unwired
    dead code, and ``_resolve_hit_outcome`` never forces a crit.
    """

    def _fight(paralyzed: bool):
        party = [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                attack_bonus=5,
                zone_id=cell(0, 0),
            )
        ]
        foe = EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            ac=1,
            zone_id=cell(1, 0),
        )
        active_effects = (
            [
                ActiveEffect(
                    id="effect:para",
                    name="Para",
                    origin="test:para",
                    target_id="mon:foe",
                    statuses={"paralyzed"},
                )
            ]
            if paralyzed
            else []
        )

        async def _run():
            start = await start_combat(
                session_id="e2e-c12-s02",
                party=party,
                encounter=[foe],
                scene_zones=None,
                grid_scene=grid_scene(),
                active_effects=active_effects,
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
            return live

        live = run_async(_run())
        return next(e for e in events_of(live, AttackRolled) if e.target_id == "mon:foe")

    base = _fight(False)
    para = _fight(True)

    assert para.advantage == "advantage"
    if para.is_hit:
        assert para.is_crit is True
    # Sanity: the un-conditioned control shouldn't itself be advantaged.
    assert base.advantage == "normal"


def test_c12_s03_prone_target_melee_advantage_ranged_disadvantage():
    """C12-S03: SRD 5.2 Conditions, Prone — attack rolls against a Prone
    target have Advantage within 5 ft and Disadvantage otherwise
    (packs/_source/content24/appendices/rules-glossary.yml:1543).
    ``conditions_grant_advantage_on_attack`` never checks Prone and is
    distance-blind.
    """

    def _fight(prone: bool):
        party = [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                attack_bonus=5,
                zone_id=cell(0, 0),
            )
        ]
        melee = EncounterMemberSpec(
            entity_id="mon:melee",
            entity_type="Monster",
            name="MeleeFoe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            ac=1,
            zone_id=cell(1, 0),
        )
        ranged = EncounterMemberSpec(
            entity_id="mon:ranged",
            entity_type="Monster",
            name="RangedFoe",
            initiative=1,
            hp_current=200,
            hp_max=200,
            ac=1,
            zone_id=cell(6, 0),
        )

        def _effects(target_id: str):
            if not prone:
                return []
            return [
                ActiveEffect(
                    id=f"effect:prone_{target_id}",
                    name="Prone",
                    origin="test:prone",
                    target_id=target_id,
                    statuses={"prone"},
                )
            ]

        async def _melee_run():
            start = await start_combat(
                session_id="e2e-c12-s03-melee",
                party=party,
                encounter=[melee],
                scene_zones=None,
                grid_scene=grid_scene(),
                active_effects=_effects("mon:melee"),
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:melee"
                ),
            )
            return live

        async def _ranged_run():
            start = await start_combat(
                session_id="e2e-c12-s03-ranged",
                party=party,
                encounter=[ranged],
                scene_zones=None,
                grid_scene=grid_scene(),
                active_effects=_effects("mon:ranged"),
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="shortbow", target_id="mon:ranged"
                ),
            )
            return live

        melee_live = run_async(_melee_run())
        ranged_live = run_async(_ranged_run())
        melee_event = next(
            e for e in events_of(melee_live, AttackRolled) if e.target_id == "mon:melee"
        )
        ranged_event = next(
            e for e in events_of(ranged_live, AttackRolled) if e.target_id == "mon:ranged"
        )
        return melee_event, ranged_event

    base_melee, base_ranged = _fight(False)
    prone_melee, prone_ranged = _fight(True)

    assert prone_melee.advantage == "advantage"
    assert prone_ranged.advantage == "disadvantage"
    assert base_melee.advantage == "normal"
    assert base_ranged.advantage == "normal"


def test_c12_s04_grappled_actor_has_speed_zero():
    """C12-S04: SRD 5.2 Conditions, Grappled — "Your Speed is 0 and can't
    increase." (packs/_source/content24/appendices/rules-glossary.yml:1251).
    ``_handle_move`` never reads ``conditions``/``movement_remaining``
    gating for Grappled, so a normally-legal 5 ft move still succeeds.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c12-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    base_speed=30,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    zone_id=cell(5, 5),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            active_effects=[
                ActiveEffect(
                    id="effect:grap",
                    name="Grap",
                    origin="test:grap",
                    target_id="char:hero",
                    statuses={"grappled"},
                )
            ],
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 0)),
        )
        return live

    live = run_async(_run())
    failed = events_of(live, MoveFailed)
    assert failed
    assert failed[0].actor_id == "char:hero"
    assert failed[0].reason == "speed_zero"


def test_c12_s05_exhaustion_applies_d20_and_speed_penalties():
    """C12-S05: SRD 5.2 Conditions, Exhaustion — D20 Tests are reduced by
    2 x Exhaustion level and Speed is reduced by 5 ft x Exhaustion level
    (packs/_source/content24/appendices/rules-glossary.yml:1169).
    ``ActiveCondition.exhaustion_level`` is carried but read nowhere in the
    projection functions.
    """

    def _run(exhausted: bool):
        active_effects = (
            [
                ActiveEffect(
                    id="effect:exh",
                    name="Exh",
                    origin="test:exh",
                    target_id="char:hero",
                    statuses={"exhaustion"},
                )
            ]
            if exhausted
            else []
        )

        async def _inner():
            start = await start_combat(
                session_id="e2e-c12-s05",
                party=[
                    PartyMemberSpec(
                        entity_id="char:hero",
                        name="Hero",
                        initiative=20,
                        hp_current=20,
                        hp_max=20,
                        attack_bonus=5,
                        base_speed=30,
                        zone_id=cell(0, 0),
                    )
                ],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=200,
                        hp_max=200,
                        ac=1,
                        zone_id=cell(1, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                active_effects=active_effects,
                rng_seed=1,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(
                    intent_type="attack", weapon_id="longsword", target_id="mon:foe"
                ),
            )
            hero = next(c for c in live.initiative if c.entity_id == "char:hero")
            return live, hero

        return run_async(_inner())

    base_live, base_hero = _run(False)
    exh_live, exh_hero = _run(True)

    base_roll = next(e for e in events_of(base_live, AttackRolled) if e.target_id == "mon:foe")
    exh_roll = next(e for e in events_of(exh_live, AttackRolled) if e.target_id == "mon:foe")

    assert exh_roll.roll_total == base_roll.roll_total - 2
    assert exh_hero.movement_remaining == base_hero.movement_remaining - 5


@xfail_cluster(12, "conditions enforced")
def test_c12_s06_dropping_to_zero_hp_applies_unconscious():
    """C12-S06: SRD 5.2 Damage and Healing, Dropping to 0 Hit Points —
    "If you reach 0 Hit Points and don't die instantly, you have the
    Unconscious condition..." (packs/_source/content24/chapter-1/
    damage-and-healing.yml:358). ``apply_damage`` computes ``is_overkill``
    but never checks ``hp_current`` reaching 0 to trigger a ``condition_
    applied`` event.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c12-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:attacker",
                    name="Attacker",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=99,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:victim",
                    name="Victim",
                    initiative=1,
                    hp_current=1,
                    hp_max=20,
                    ac=1,
                    zone_id=cell(1, 0),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=5,
                    hp_current=20,
                    hp_max=20,
                    ac=99,
                    zone_id=cell(5, 5),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:attacker",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="longsword", target_id="char:victim"
            ),
        )
        return live

    live = run_async(_run())
    unconscious = [
        e
        for e in events_of(live, ConditionApplied)
        if e.target_id == "char:victim" and e.condition == "unconscious"
    ]
    assert unconscious
