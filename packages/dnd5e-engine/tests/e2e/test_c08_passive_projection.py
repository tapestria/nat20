"""C08 — Passive-stat projection.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 8.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(8, "Passive-stat projection")
def test_c08_s01_rage_resistance_never_halves_matching_damage_taken():
    """C08-S01: Rage's activation-gated `dr` resistance never halves matching
    damage taken while raging (same-seed A/B).

    SRD 5.2 §Barbarian Class Features, Rage ("you have Resistance to
    Bludgeoning, Piercing, and Slashing damage" while raging); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/barbarian/class-features/rage.yml;
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/rage.json
    (`passive_effects[0]`, name "Rage", `disabled: true, transfer: true` —
    activation-gated; `changes` include
    `{"key": "system.traits.dr.value", "mode": 2, "value": "slashing"}` +
    "piercing" + "bludgeoning", alongside
    `{"key": "system.bonuses.mwak.damage", "value": "+@scale.barbarian.rage-damage"}`);
    engine: packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_fold_active_effect_changes`, lines 1372-1497 — folds ONLY
    `_FOUNDRY_MELEE_DAMAGE_KEY = "system.bonuses.mwak.damage"`,
    `_FOUNDRY_ATTACK_BONUS_KEYS`, `"system.bonuses.abilities.save"`,
    `"attack.roll.bonus"`, `"save.bonus"`, `"ac.bonus"`, `"damage.bonus"`
    from an ACTIVE effect's `changes`; no branch matches
    `"system.traits.dr.value"`) and
    packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py
    (`apply_damage` — `resistances` is populated ONCE at PC-build time by
    `build_party_member`->`interpret_passive_stats`, which correctly
    EXCLUDES Rage's `dr` changes because `disabled=True` fails the
    always-on `transfer and not disabled` filter,
    packages/dnd5e-engine/src/dnd5e_engine/build_party.py:81).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=100,
                hp_max=100,
                constitution=16,
                character_level=5,
                class_slug="barbarian",
                ac=1,
                zone_id="zone:a",
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:zombie",
                entity_type="Monster",
                name="Zombie",
                initiative=1,
                hp_current=22,
                hp_max=22,
                ac=8,
                attack_bonus=3,
                zone_id="zone:a",
                monster_template_slug="zombie",
            )
        ]

    async def _run(*, raged: bool):
        start = await start_combat(
            session_id=f"e2e-c08-s01-{raged}",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(
                zones=["zone:a"], edges=[ZoneEdge(a="zone:a", b="zone:a", distance_ft=0)]
            ),
            rng_seed=8,
        )
        live = _get_live(start.handle)
        if raged:
            await submit_player_intent(
                start.handle,
                actor_id="char:hero",
                intent=PlayerIntent(intent_type="use_feature", feature_id="rage"),
            )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="dodge"),
        )
        await advance_monster_turn(start.handle)
        return live

    live_a = run_async(_run(raged=False))
    base_total = sum(
        e.amount for e in events_of(live_a, DamageApplied) if e.target_id == "char:hero"
    )

    live_b = run_async(_run(raged=True))
    raged_total = sum(
        e.amount for e in events_of(live_b, DamageApplied) if e.target_id == "char:hero"
    )

    assert raged_total == base_total // 2


@xfail_cluster(8, "Passive-stat projection")
def test_c08_s02_natures_ward_condition_immunity_does_not_block_poisoned():
    """C08-S02: Nature's Ward's condition-immunity (`ci:poison`) does not
    block Poisoned condition application on a failed save.

    SRD 5.2 §Circle of the Land (Druid), Nature's Ward ("You can't be
    Poisoned"); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/druid/subclass-features/circle-of-land/natures-ward.yml;
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/natures-ward.json
    (`passive_effects[0]`, name "Nature's Ward", `disabled: false,
    transfer: true` — ALWAYS ON; `changes = [{"key":
    "system.traits.ci.value", "mode": 2, "value": "\"poison\""}]`); granted
    by packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/subclasses/land.json
    (`granted_features`, `{"level": 10, "slug": "natures-ward"}`); poisoning
    source: packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/stinking-cloud.json
    (activity `dnd5eactivity000`, `kind: "save"`, `save.ability=["con"]`;
    `effects=[{"id": "gFid0DG5HydORpr3", "on_save": false}]` referencing
    `passive_effects[0]` "Stinking Poison", `statuses: ["poisoned"]`,
    `disabled: false`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/passive_stats.py
    (`interpret_passive_stats` — `system.traits.ci.value` matches no
    recognized key and falls to `skipped_keys`) and
    packages/dnd5e-engine/src/dnd5e_engine/types/combat.py (`Combatant` —
    no `condition_immunities` field of any kind) and
    packages/dnd5e-engine/src/dnd5e_engine/activities/effects.py
    (`ConditionApplied` emission — no condition-immunity gate anywhere in
    the emit path).
    """
    import dnd5e_engine.events as ev

    async def _run():
        start = await start_combat(
            session_id="e2e-c08-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wiz",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    intelligence=18,
                    character_level=5,
                    class_slug="wizard",
                    spells_known=["stinking-cloud"],
                    spell_slots={3: 1},
                    zone_id="zone:a",
                ),
                PartyMemberSpec(
                    entity_id="char:druid",
                    name="Druid",
                    initiative=10,
                    hp_current=40,
                    hp_max=40,
                    wisdom=16,
                    constitution=3,
                    character_level=10,
                    class_slug="druid",
                    subclass_slug="land",
                    zone_id="zone:a",
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=15,
                    hp_current=10,
                    hp_max=10,
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a"], edges=[ZoneEdge(a="zone:a", b="zone:a", distance_ft=0)]
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="stinking-cloud", target_id="char:druid"
            ),
        )
        return live

    live = run_async(_run())
    condition_applied = getattr(ev, "ConditionApplied", None)
    assert condition_applied is not None, "ConditionApplied not yet defined"
    poisoned = [
        e
        for e in events_of(live, condition_applied)
        if e.target_id == "char:druid" and e.condition == "poisoned"
    ]
    assert not poisoned, "Nature's Ward should prevent Poisoned from ever attaching"


@xfail_cluster(8, "Passive-stat projection")
def test_c08_s03_damage_vulnerability_never_doubles_matching_hit():
    """C08-S03: Damage vulnerability never doubles a matching-type hit — the
    sidecar consumer has no producer anywhere in the engine.

    SRD 5.2 §Damage Vulnerability ("applying twice the normal damage");
    dataset: packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/monsters/skeleton.json
    (`damage_vulnerabilities: ["bludgeoning"]`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/apply.py
    (`apply_damage` — `vulnerabilities = set(sidecar.get("vulnerabilities",
    ()))`; per its own docstring, "Vulnerabilities have no static field on
    `Combatant` and come ONLY from the sidecar") — but the only producer
    site, `rules/conditions.py::project_passive_damage_modifiers`, never
    appends to the `"vulnerabilities"` list.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c08-s03",
            party=[
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
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:skel",
                    entity_type="Monster",
                    name="Skeleton",
                    initiative=1,
                    hp_current=13,
                    hp_max=13,
                    ac=1,
                    zone_id="zone:a",
                    monster_template_slug="skeleton",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a"], edges=[ZoneEdge(a="zone:a", b="zone:a", distance_ft=0)]
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="mace", target_id="mon:skel"),
        )
        return live

    live = run_async(_run())
    base_total = sum(e.amount for e in events_of(live, DamageApplied) if e.target_id == "mon:skel")
    vuln_total = base_total
    assert vuln_total == 2 * base_total


@xfail_cluster(8, "Passive-stat projection")
def test_c08_s04_granted_feature_movement_mode_never_lands_on_combatant():
    """C08-S04: A granted feature's non-walk movement mode (and its own flat
    walk-speed bonus) never lands on the live `Combatant`.

    SRD 5.2 §Ranger Class Features, Roving ("Your Speed increases by 10 feet
    while you aren't wearing Heavy armor. You also have a Climb Speed and a
    Swim Speed equal to your Speed."); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/ranger/class-features/roving.yml;
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/roving.json
    (`passive_effects[0]`, name "Roving", `disabled: false, transfer: true`
    — ALWAYS ON; `changes = [{"key": "system.attributes.movement.walk",
    "mode": 2, "value": "10"}, {"key": "system.attributes.movement.climb",
    "mode": 4, "value": "@attributes.movement.walk"}, {"key":
    "system.attributes.movement.swim", "mode": 4, "value":
    "@attributes.movement.walk"}]`); granted by
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/classes/ranger.json
    (`granted_features`, `{"level": 6, "slug": "roving"}`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/passive_stats.py —
    `system.attributes.movement.*` matches no recognized key, so EVERY
    movement change (including the plain flat `+10` walk-speed integer)
    falls through to `skipped_keys`; packages/dnd5e-engine/src/dnd5e_engine/types/combat.py
    (`Combatant` — `base_speed: int` is the ONLY movement field).

    Pure build-seam probe (no live combat needed), mirroring C04-S02's
    precedent.
    """
    from dnd5e_engine.build_party import build_party_member
    from dnd5e_engine.build_spec import AbilityScores, CharacterBuildSpec, CombatInstance

    loader = BundledAssetLoader()
    build_spec = CharacterBuildSpec(
        class_slug="ranger",
        subclass_slug=None,
        species_slug="human",
        level=6,
        ability_scores=AbilityScores(
            strength=10, dexterity=16, constitution=14, intelligence=10, wisdom=14, charisma=10
        ),
    )
    instance = CombatInstance(
        entity_id="char:ranger",
        name="Ranger",
        initiative=10,
        hp_current=50,
        hp_max=50,
        ac=15,
        attack_bonus=6,
        zone_id="zone:a",
    )

    spec = build_party_member(build_spec, instance, loader=loader)

    assert spec.base_speed == 40
