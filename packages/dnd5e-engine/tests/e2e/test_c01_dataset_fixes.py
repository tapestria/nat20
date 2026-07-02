"""C01 — Dataset fixes: typeless damage parts in canonical spells.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 1.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import DamageApplied
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(1, "Dataset fixes")
def test_c01_s01_call_lightning_repeat_bolt_applies_lightning_damage(caplog):
    """C01-S01: Call Lightning's repeat-bolt activity applies lightning-typed damage.

    SRD 5.2 §Spell Descriptions (Call Lightning: "taking 3d10 Lightning damage
    on a failed save... you can take a Magic action to call down lightning in
    that way again"); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/spells24/3rd-level/call-lightning.yml
    (activity `dnd5eactivity200`, `type: damage`, `damage.parts[0].types: []`);
    canonical packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/call-lightning.json
    (same activity, same empty `types`).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c01-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:druid",
                    name="Druid",
                    initiative=20,
                    hp_current=40,
                    hp_max=40,
                    spells_known=["call-lightning"],
                    spell_slots={3: 1},
                    character_level=5,
                    zone_id="zone:druid",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=1,
                    hp_current=200,
                    hp_max=200,
                    zone_id="zone:foe",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:druid", "zone:foe"],
                edges=[ZoneEdge(a="zone:druid", b="zone:foe", distance_ft=30)],
            ),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:druid",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="call-lightning", target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    assert not any("damage_part_untyped" in r.message for r in caplog.records)
    lightning_hits = [
        e
        for e in events_of(live, DamageApplied)
        if e.target_id == "mon:foe" and e.damage_type == "lightning"
    ]
    assert len(lightning_hits) == 2
    amounts = sorted(e.amount for e in lightning_hits)
    initial_bolt, repeat_bolt = amounts
    assert 3 <= initial_bolt <= 30
    assert 4 <= repeat_bolt <= 40


@xfail_cluster(1, "Dataset fixes")
def test_c01_s02_freezing_sphere_damage_parts_apply_cold_damage(caplog):
    """C01-S02: Freezing Sphere's damage parts apply cold-typed damage.

    SRD 5.2 §Spell Descriptions (Freezing Sphere: "taking 10d6 Cold damage on
    failed save or half as much damage on a successful one"); foundry:
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/spells24/6th-level/freezing-sphere.yml
    (activities `adCBWrctRmLQmb8M` "Cast and Fire" and `NKBsnjBBIgsaOPaY`
    "Throw Held Globe", both `damage.parts[0].types: []`); canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/freezing-sphere.json
    (same two activities, same empty `types`).
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c01-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=60,
                    hp_max=60,
                    spells_known=["freezing-sphere"],
                    spell_slots={6: 1},
                    character_level=11,
                    zone_id="zone:wiz",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=1,
                    hp_current=200,
                    hp_max=200,
                    zone_id="zone:foe",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:wiz", "zone:foe"],
                edges=[ZoneEdge(a="zone:wiz", b="zone:foe", distance_ft=30)],
            ),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="freezing-sphere", target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    assert not any("damage_part_untyped" in r.message for r in caplog.records)
    cold_hits = [
        e
        for e in events_of(live, DamageApplied)
        if e.target_id == "mon:foe" and e.damage_type == "cold"
    ]
    assert cold_hits
    assert all(10 <= e.amount <= 60 for e in cold_hits)
