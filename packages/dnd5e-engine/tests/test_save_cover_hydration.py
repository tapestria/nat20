"""C22-S03 — a cover tag on a target's own cell must reach its Dexterity
save even when the resolving activity carries a measured AoE template
(Acid Splash's SRD 5.2 5-ft-radius Sphere) and the point of origin
coincides with the single creature it affects.

``_target_cover_map`` / ``_aoe_cover_origin`` shift the cover point-of-origin
to the AoE's burst point for every templated cast (SRD 5.2 §Cover — "an area
of effect ... measure cover from the point of origin"), pinned for a genuine
multi-target burst by ``tests/test_c16_orchestrator.py::
test_aoe_cover_is_measured_from_the_point_of_origin_not_the_caster`` (a
2-target Fireball). When that burst point coincides with the ONE creature it
affects — Acid Splash resolving to a single foe — ``cover_between``'s line
walk (which always excludes its own origin endpoint) degenerates to a single
excluded point and would silently drop a tag sitting on that shared cell.
``_target_cover_map`` special-cases ``origin == target_zone`` to read the tag
directly off that cell (``GridTopology.cover_on_cell``) instead. This module
pins the OBSERVABLE BEHAVIOUR — the tag reaches the save, and Sacred Flame's
``ignore_cover`` strips it — not the internal mechanism, so it stays green
under any implementation that satisfies the same contract.

The companion single-victim-burst regression lives in
``test_fireball_resolving_to_one_target_ignores_a_caster_line_cover_tag``
below: a cover tag on an INTERIOR caster-to-target cell (not the target's own
cell) must NOT apply, because cover for an AoE is measured from the burst
point, never from the caster — even when the burst happens to hit only one
creature.
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


def test_cover_tag_on_the_targets_own_cell_reaches_a_templated_single_target_save():
    """Acid Splash (SRD 5.2 5-ft Sphere, resolving to exactly one foe) still
    picks up the half-cover tag on that foe's own cell: +2 on the Dex save."""
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


def test_fireball_resolving_to_one_target_ignores_a_caster_line_cover_tag():
    """A templated save spell that resolves to exactly ONE target still
    measures cover from the AoE's burst point, never the caster — even
    though the single-victim case is otherwise handled specially. A
    half-cover tag on an INTERIOR cell of the caster-to-target line (never on
    the target/origin cell itself) must contribute nothing: it doesn't lie on
    any line the burst point actually needs (the burst point IS the target's
    cell here), so the save keeps its bare (0) Dexterity modifier.
    """

    async def _inner() -> SaveRolled:
        start = await start_combat(
            session_id="save-cover-hydration-fireball-single-victim",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=60,
                    hp_max=60,
                    character_level=5,
                    class_slug="wizard",
                    spells_known=["fireball"],
                    spell_slots={3: 1},
                    zone_id=cell(0, 10),
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
                    ac=12,
                    dexterity=10,
                    zone_id=cell(10, 10),
                )
            ],
            scene_zones=None,
            # Tagged cell (5,10) sits on the caster(0,10)->target(10,10) line
            # but is NOT the burst point (the target's own cell, (10,10)).
            grid_scene=GridScene(width=21, height=21, cover_cells={cell(5, 10): "half"}),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(intent_type="cast_spell", spell_id="fireball", target_id="mon:foe"),
        )
        return next(e for e in events_of(live, SaveRolled) if e.target_id == "mon:foe")

    rolled = run_async(_inner())
    assert rolled.ability == "dex"
    assert rolled.modifier == 0
