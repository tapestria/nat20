"""C02 — Small mechanics.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 2.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.check import CheckSpec, resolve_check
from dnd5e_engine.events import ActorMoved, DamageApplied
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(2, "Small mechanics")
def test_c02_s01_weapon_tagged_damage_bonus_reaches_swing_damage():
    """C02-S01: A weapon-tagged `damage.bonus` active effect reaches the
    swing's damage, not just its to-hit.

    SRD 5.2 §Making an Attack / §Magic Items (a magic weapon's bonus applies
    to attack AND damage rolls made with it); engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_fold_active_effect_changes` — folds a weapon-tagged `damage.bonus`
    change into the `passive_weapon_damage_bonus` sidecar key) and
    packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py
    (`_build_activity_context` reads `passive_to_hit_bonus` →
    `passive_attack_bonus` and `passive_melee_damage_bonus` →
    `ActivityResolutionContext.passive_melee_damage_bonus`, but never reads
    the weapon-only `passive_weapon_to_hit_bonus` / `passive_weapon_damage_bonus`
    keys).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                attack_bonus=5,
                strength=16,
                zone_id="zone:a",
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                ac=1,
                hp_current=500,
                hp_max=500,
                zone_id="zone:a",
            )
        ]

    async def _run(active_effects):
        start = await start_combat(
            session_id="e2e-c02-s01",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=11,
            active_effects=active_effects,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longsword", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run(()))
    base_total = sum(e.amount for e in events_of(live_a, DamageApplied) if e.target_id == "mon:foe")

    plus3_weapon = ActiveEffect(
        id="effect:plus3_weapon",
        name="+3 Weapon",
        origin="test:plus3_weapon",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="damage.bonus", mode="add", value=3)],
        flags={"applicable_action_types": ["attack"]},
    )
    live_b = run_async(_run((plus3_weapon,)))
    buffed_total = sum(
        e.amount for e in events_of(live_b, DamageApplied) if e.target_id == "mon:foe"
    )

    assert buffed_total == base_total + 3


def test_c02_s02_expertise_doubles_proficiency_bonus_on_skill_check():
    """C02-S02: Expertise doubles proficiency bonus on a proficient skill check.

    SRD 5.2 §Skills, Expertise (a class feature that doubles the proficiency
    bonus for a chosen proficient skill/tool); engine:
    packages/dnd5e-engine/src/dnd5e_engine/check.py (`CheckSpec.expertise_skills`),
    packages/dnd5e-engine/src/dnd5e_engine/rules/skills.py
    (`skill_check(expertise=...)`).

    Already implemented and verified working today — plain regression, no
    xfail marker per the catalog's flag for this entry.
    """
    import random

    base_spec = CheckSpec(
        kind="skill",
        skill="stealth",
        ability_scores={"dexterity": 14},
        proficient_skills=("stealth",),
        proficient_saves=(),
        proficiency_bonus=3,
        expertise_skills=(),
    )
    expert_spec = CheckSpec(
        kind="skill",
        skill="stealth",
        ability_scores={"dexterity": 14},
        proficient_skills=("stealth",),
        proficient_saves=(),
        proficiency_bonus=3,
        expertise_skills=("stealth",),
    )

    random.seed(1234)
    base = resolve_check(base_spec)
    random.seed(1234)
    expert = resolve_check(expert_spec)

    assert expert.modifier - base.modifier == base_spec.proficiency_bonus
    assert expert.roll_total - base.roll_total == base_spec.proficiency_bonus


@xfail_cluster(2, "Small mechanics")
def test_c02_s03_reach_ft_threads_onto_live_combatant():
    """C02-S03: `PartyMemberSpec.reach_ft` threads an equipped reach weapon's
    reach onto the live `Combatant`.

    SRD 5.2 Weapons table, Glaive (properties Heavy, Reach, Two-Handed —
    Reach adds 5 ft to a melee weapon's normal reach); engine:
    packages/dnd5e-engine/src/dnd5e_engine/types/combat.py
    (`Combatant.melee_reach_ft: int = 5`),
    packages/dnd5e-engine/src/dnd5e_engine/specs.py
    (`PartyMemberSpec` — no `reach_ft` field today); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/equipment24/weapons/martial-melee/glaive.yml.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c02-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    equipment=("glaive",),
                    reach_ft=10,  # type: ignore[call-arg]
                    zone_id="zone:a",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=10,
                    hp_max=10,
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = run_async(_run())
    hero = next(c for c in live.initiative if c.entity_id == "char:hero")
    assert hero.melee_reach_ft == 10


@xfail_cluster(2, "Small mechanics")
def test_c02_s04_monster_can_dash_to_double_movement_budget():
    """C02-S04: A monster can Dash to double its movement budget within one
    `advance_monster_turn`.

    SRD 5.2 §Actions in Combat, Dash ("you gain extra movement for the
    current turn equal to your Speed"); engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_handle_dash` — reachable only from `submit_player_intent`'s
    `intent.intent_type == "dash"` branch; `advance_monster_turn`'s gambit
    movement loop, same file, never calls it).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c02-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=1,
                    ac=15,
                    hp_current=20,
                    hp_max=20,
                    zone_id="zone:pc",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:goblin",
                    entity_type="Monster",
                    name="Goblin",
                    initiative=20,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    monster_template_slug="goblin-warrior",
                    base_speed=30,
                    zone_id="zone:foe",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:foe", "zone:pc"],
                edges=[ZoneEdge(a="zone:foe", b="zone:pc", distance_ft=35)],
            ),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    moves = [e for e in events_of(live, ActorMoved) if e.actor_id == "mon:goblin"]
    total_distance = sum(e.distance_ft for e in moves)
    assert total_distance == 35
    assert total_distance > 30
    assert total_distance <= 60
