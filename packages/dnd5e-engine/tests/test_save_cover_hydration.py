"""C22-S03 — the orchestrator's PC cast-spell path must hydrate
``ActivityResolutionContext.target_cover`` from the CASTER's own cell for a
single-target save cast, even when the resolving activity happens to carry a
measured template (Acid Splash's Foundry data models its "one or two
creatures within 5 ft of each other" targeting as a 5-ft sphere).

``_target_cover_map`` / ``_aoe_cover_origin`` correctly shift the cover
point-of-origin to the AoE's burst point for a genuine multi-target broadcast
(pinned by ``tests/test_c16_orchestrator.py::
test_aoe_cover_is_measured_from_the_point_of_origin_not_the_caster``, a
2-target Fireball). But when the template resolves to exactly ONE target —
Acid Splash cast at a single foe — that burst point degenerates to the
target's own cell: ``cover_between(cell, cell)`` walks a single point and
excludes it (the ORIGIN cell never counts), so a cover tag sitting on that
one cell is silently dropped and the SRD +2 never reaches the roll. The fix
is scoped to the "genuinely more than one resolved target" broadcast case;
this test pins the single-target degenerate case landing on the ordinary
caster-to-target cover reading instead.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import SaveRolled
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, run_async


def _cast_and_get_save(spell_slug: str) -> SaveRolled:
    async def _inner() -> SaveRolled:
        start = await start_combat(
            session_id=f"save-cover-hydration-{spell_slug}",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    spells_known=["sacred-flame", "acid-splash"],
                    character_level=1,
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=20,
                    hp_max=20,
                    ac=12,
                    dexterity=10,
                    zone_id=cell(5, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, cover_cells={cell(5, 0): "half"}),
            rng_seed=13,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(intent_type="cast_spell", spell_id=spell_slug, target_id="mon:foe"),
        )
        return next(e for e in events_of(live, SaveRolled) if e.target_id == "mon:foe")

    return run_async(_inner())


def test_single_target_templated_save_cast_reads_cover_from_the_caster():
    """Acid Splash (sphere template, but exactly one foe on the grid) still
    picks up the target's own half-cover tag: +2 on the Dexterity save."""
    rolled = _cast_and_get_save("acid-splash")
    assert rolled.ability == "dex"
    assert rolled.modifier == 2


def test_sacred_flame_ignore_cover_strips_the_same_bonus():
    """Same geometry, but Sacred Flame's ``ignore_cover`` carve-out zeroes the
    bonus that Acid Splash keeps — the two spells must diverge by exactly the
    cover amount."""
    rolled = _cast_and_get_save("sacred-flame")
    assert rolled.ability == "dex"
    assert rolled.modifier == 0
