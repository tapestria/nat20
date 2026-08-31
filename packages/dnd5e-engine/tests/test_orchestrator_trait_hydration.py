"""C22 — ``monster_template_slug`` hydrates ``Combatant.trait_mechanics``."""

from __future__ import annotations

import asyncio

from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec


def _start(slug: str | None):
    async def _run():
        start = await start_combat(
            session_id=f"trait-hydration-{slug}",
            party=[
                PartyMemberSpec(
                    entity_id="char:a",
                    name="A",
                    initiative=20,
                    hp_current=10,
                    hp_max=10,
                    zone_id=cell_id(0, 0),
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
                    zone_id=cell_id(1, 0),
                    monster_template_slug=slug,
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=5, height=5),
            rng_seed=1,
        )
        return _get_live(start.handle)

    return asyncio.run(_run())


def test_pit_fiend_hydrates_magic_and_legendary_resistance():
    live = _start("pit-fiend")
    foe = next(c for c in live.initiative if c.entity_id == "mon:foe")
    assert MonsterTraitMechanic.MAGIC_RESISTANCE in foe.trait_mechanics
    assert MonsterTraitMechanic.LEGENDARY_RESISTANCE in foe.trait_mechanics


def test_ogre_and_templateless_foes_have_no_traits():
    assert _start("ogre").initiative[-1].trait_mechanics == []
    assert _start(None).initiative[-1].trait_mechanics == []
