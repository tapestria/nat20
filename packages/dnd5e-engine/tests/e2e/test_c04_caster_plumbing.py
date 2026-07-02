"""C04 — Caster plumbing (spellcasting ability, scales, bonuses).

Transcribed from specs/e2e-scenario-catalog.md, Cluster 4.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.activities.scale import build_scale_values, resolve_scale_value
from dnd5e_engine.events import DamageApplied, SaveRolled
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(4, "Caster plumbing")
def test_c04_s01_cleric_spell_save_dc_uses_real_wis_formula():
    """C04-S01: A cleric's spell save DC is computed from the real WIS-based
    spellcasting formula, not a hardcoded flat approximation.

    SRD 5.2 §Spellcasting, Spell Save DC ("Spell save DC = 8 + your
    Proficiency Bonus + your spellcasting ability modifier"); foundry/canonical:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/classes/cleric.json
    (`spellcasting: {ability: "wis", progression: "full"}`),
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/sacred-flame.json
    (activity `dTJW1b6fCd5TyMEa`, `save.dc.calculation="spellcasting"`);
    engine: packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_resolve_intent_activities` — `spellcasting_ability = "int"` hardcoded
    for every `cast_spell` intent regardless of caster class) and
    packages/dnd5e-engine/src/dnd5e_engine/activities/build_context.py
    (`_caster_mod`/`_save_dc` — `save_dc_override` unconditionally set for
    every non-feature cast, short-circuiting
    packages/dnd5e-engine/src/dnd5e_engine/activities/save.py::resolve_save_dc's
    otherwise-correct `8 + ctx.caster_proficiency_bonus +
    ctx.ability_mod(ctx.spellcasting_ability)` branch before it ever runs).
    """

    async def _run(wisdom: int):
        start = await start_combat(
            session_id="e2e-c04-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    class_slug="cleric",
                    character_level=5,
                    attack_bonus=5,
                    wisdom=wisdom,
                    spells_known=["sacred-flame"],
                    zone_id="zone:a",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    dexterity=10,
                    ac=15,
                    hp_current=50,
                    hp_max=50,
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="sacred-flame", target_id="mon:foe"
            ),
        )
        return live

    live_high_wis = run_async(_run(20))
    dc_high_wis = next(
        e.dc for e in events_of(live_high_wis, SaveRolled) if e.target_id == "mon:foe"
    )

    live_low_wis = run_async(_run(10))
    dc_low_wis = next(e.dc for e in events_of(live_low_wis, SaveRolled) if e.target_id == "mon:foe")

    assert dc_high_wis - dc_low_wis == 5
    assert dc_high_wis == 16
    assert dc_low_wis == 11


@xfail_cluster(4, "Caster plumbing")
def test_c04_s02_feature_owned_scale_id_resolves_against_granting_feature():
    """C04-S02: Feature-owned `@scale` ids (Channel Divinity's Divine Spark
    die count) resolve against the granting feature's own advancement table.

    SRD 5.2 §Channel Divinity (Cleric) ("Roll 1d8 and add your Wisdom
    modifier... You roll an additional d8 when you reach Cleric levels 7
    (2d8), 13 (3d8), and 18 (4d8)"); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/classes24/cleric/class-features/channel-divinity.yml
    (ScaleValue advancement `{"2":{value:1},"7":{value:2},"13":{value:3},"18":{value:4}}`);
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/features/channel-divinity-cleric.json
    carries the same formula string but no top-level `advancement` key at
    all (`packages/dnd5e-srd-data/src/dnd5e_srd_data/schema/feature.py::Feature`
    has no `advancement` field); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/scale.py
    (`_owner_doc` — class / subclass / species only, no `get_feature`
    fallback; `build_scale_values` — same three-slug walk, never a caster's
    granted FEATURE slugs).

    Pure resolver-level probe (no live combat needed), mirroring
    packages/dnd5e-engine/tests/test_scale_resolver.py, which already
    documents this exact token in its "UNRESOLVED set" docstring and locks
    it as `None` at lines 121-123. This scenario deliberately targets the
    internal `activities/scale.py` seam the task brief names directly —
    there is no public-spec path to a feature-owned `@scale` id today
    because reaching Channel Divinity's activities at all is independently
    blocked by the C07-S03 multi-activity gap.
    """
    loader = BundledAssetLoader()

    resolved = resolve_scale_value("channel-divinity-cleric", "spark", level=13, loader=loader)
    assert resolved == 3

    scale_values = build_scale_values(
        class_slug="cleric",
        subclass_slug=None,
        species_slug=None,
        level=13,
        loader=loader,
    )
    assert scale_values.get("channel-divinity-cleric.spark") == 3


@xfail_cluster(4, "Caster plumbing")
def test_c04_s03_rwak_damage_bucket_reaches_ranged_swing_damage():
    """C04-S03: A `system.bonuses.rwak.damage` active-effect bucket reaches
    a ranged weapon swing's damage (ranged analog of Rage's `mwak` fold).

    SRD 5.2 §Making an Attack / §Magic Items (a feature/item that grants a
    ranged-weapon-attack damage bonus applies it to a ranged swing's
    damage, symmetrically with a melee-only bonus such as Rage's); engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_fold_active_effect_changes` — `_FOUNDRY_MELEE_DAMAGE_KEY =
    "system.bonuses.mwak.damage"` is the ONLY damage-category bucket
    folded; the `elif` chain has no branch for
    `"system.bonuses.rwak.damage"`); sibling melee-only invariant already
    locked by
    packages/dnd5e-engine/tests/test_rage_second_wind_e2e.py::test_rage_bonus_is_melee_only_not_ranged,
    which never exercises the `rwak` bucket itself.
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
                dexterity=18,
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
            session_id="e2e-c04-s03",
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
            intent=PlayerIntent(intent_type="attack", weapon_id="shortbow", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run(()))
    base_total = sum(e.amount for e in events_of(live_a, DamageApplied) if e.target_id == "mon:foe")

    rwak_buff = ActiveEffect(
        id="effect:rwak_buff",
        name="rwak_buff",
        origin="test:rwak_buff",
        target_id="char:hero",
        changes=[ActiveEffectChange(key="system.bonuses.rwak.damage", mode="add", value=2)],
    )
    live_b = run_async(_run((rwak_buff,)))
    buffed_total = sum(
        e.amount for e in events_of(live_b, DamageApplied) if e.target_id == "mon:foe"
    )

    assert buffed_total == base_total + 2
