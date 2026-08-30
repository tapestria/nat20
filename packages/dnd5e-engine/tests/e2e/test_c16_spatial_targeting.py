"""C16 — Spatial targeting & geometry (grid-only) + C16b Vision & light.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 16
(specs/catalog-v2/c16.md). Grid-only throughout — ``GridScene`` +
``GridTopology``, cell ids ``"col,row"`` (``dnd5e_engine.spatial.cell_id``).
Setups mirror ``tests/e2e/test_c05_spatial.py``'s idioms (single-cell
``zone_id``s, same-seed A/B via a ``_run(grid_scene)`` closure).
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackFailed,
    AttackRolled,
    DamageApplied,
    MoveFailed,
    SaveRolled,
)
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def test_c16_s01_fireball_sphere_hits_every_creature_within_radius():
    """C16-S01: SRD 5.2 §Areas of Effect, Sphere — "A Sphere is an area of
    effect that extends in straight lines from a point of origin outward
    in all directions... A Sphere's point of origin is included in the
    Sphere's area of effect."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id npdEWb2egUPnB5Fa, heading "Sphere"); fireball's 20 ft radius:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/fireball.json
    (``target.template = {type: "sphere", size: "20", units: "ft"}``).
    ``orchestrator._expand_aoe_target_list`` walks
    ``GridTopology.cells_in_template("sphere", 20)`` from the point of
    origin and keeps every alive combatant standing in a resulting cell
    with line of effect, so the geometrically-in-radius but unnamed
    ``mon:near2`` takes damage alongside the named target. Before C16 the
    expansion was zone-EQUALITY filtering on the named target and
    ``mon:near2`` was never hit.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c16-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    intelligence=16,
                    character_level=5,
                    class_slug="wizard",
                    spells_known=["fireball"],
                    spell_slots={3: 1},
                    zone_id=cell(10, 10),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:near1",
                    entity_type="Monster",
                    name="Near1",
                    initiative=10,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(14, 10),
                ),
                EncounterMemberSpec(
                    entity_id="mon:near2",
                    entity_type="Monster",
                    name="Near2",
                    initiative=9,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(14, 14),
                ),
                EncounterMemberSpec(
                    entity_id="mon:far",
                    entity_type="Monster",
                    name="Far",
                    initiative=8,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(15, 15),
                ),
            ],
            scene_zones=None,
            grid_scene=grid_scene(width=21, height=21, cell_size_ft=5),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="fireball", target_id="mon:near1"
            ),
        )
        return live

    live = run_async(_run())
    near1_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:near1"]
    near2_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:near2"]
    far_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:far"]

    assert near1_dmg
    assert near1_dmg[0].damage_type == "fire"
    assert 8 <= near1_dmg[0].amount <= 48
    assert near2_dmg, "mon:near2 is geometrically inside the 20ft sphere too"
    assert 8 <= near2_dmg[0].amount <= 48
    assert not far_dmg


def test_c16_s02_burning_hands_cone_fires_from_casters_own_cell():
    """C16-S02: SRD 5.2 §Areas of Effect, Cone — "A Cone is an area of
    effect that extends in straight lines from a point of origin in a
    direction its creator chooses."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id DqqAOr5JnX71OCOw, heading "Cone"). Burning Hands' 15 ft cone:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/burning-hands.json
    (``target.template = {type: "cone", size: "15", units: "ft"}``,
    ``range.units = "self"``).

    ``mon:front`` (2 cells "ahead", inside the 3-cell forward cone) takes
    ``DamageApplied(damage_type="fire")`` (bounded ``[3, 18]``, 3d6) and
    ``mon:behind`` (2 cells "behind") takes none.
    ``_expand_aoe_target_list`` (orchestrator.py) now walks
    ``GridTopology.cells_in_template("cone", 15, direction=(1, 0))`` from
    the caster's own cell (origin excluded per SRD) and keeps every alive
    combatant standing in a resulting cell, so ``mon:behind`` is excluded
    by geometry rather than by not being the named target. See
    ``tests/test_c16_orchestrator.py::test_cone_hits_an_unnamed_creature_inside_the_cone``
    for the companion unit that pins the "unnamed but in-cone" half.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c16-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    character_level=3,
                    class_slug="wizard",
                    spells_known=["burning-hands"],
                    spell_slots={1: 1},
                    zone_id=cell(5, 5),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:front",
                    entity_type="Monster",
                    name="Front",
                    initiative=10,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(7, 5),
                ),
                EncounterMemberSpec(
                    entity_id="mon:behind",
                    entity_type="Monster",
                    name="Behind",
                    initiative=9,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(3, 5),
                ),
            ],
            scene_zones=None,
            grid_scene=grid_scene(width=11, height=11),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="burning-hands",
                target_id="mon:front",
                direction=(1, 0),
            ),
        )
        return live

    live = run_async(_run())
    front_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:front"]
    behind_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:behind"]

    assert front_dmg
    assert front_dmg[0].damage_type == "fire"
    assert 3 <= front_dmg[0].amount <= 18
    assert not behind_dmg


def test_c16_s03_lightning_bolt_line_hits_every_cell_along_its_length():
    """C16-S03: SRD 5.2 §Areas of Effect, Line — "A Line is an area of
    effect that extends from a point of origin in a straight path along
    its length and covers an area defined by its width."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id 6DOoBgg7okm9gBc6, heading "Line"). Lightning Bolt's 100 ft line:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/lightning-bolt.json.
    ``_expand_aoe_target_list`` enumerates the line's cells from the
    caster's own point of origin, so every creature standing on the
    bolt's path is hit — both the named target and ``mon:near``, which
    sits between the caster and it — while a creature off the path
    (``mon:offline``) takes none. Before C16 the zone-equality expansion
    degenerated the bolt to a single terminal-point hit.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c16-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:sorc",
                    name="Sorcerer",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    character_level=5,
                    class_slug="sorcerer",
                    spells_known=["lightning-bolt"],
                    spell_slots={3: 1},
                    zone_id=cell(0, 2),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:near",
                    entity_type="Monster",
                    name="Near",
                    initiative=11,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(2, 2),
                ),
                EncounterMemberSpec(
                    entity_id="mon:mid",
                    entity_type="Monster",
                    name="Mid",
                    initiative=10,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(5, 2),
                ),
                EncounterMemberSpec(
                    entity_id="mon:offline",
                    entity_type="Monster",
                    name="Offline",
                    initiative=9,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(5, 4),
                ),
            ],
            scene_zones=None,
            grid_scene=grid_scene(width=25, height=5, cell_size_ft=5),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:sorc",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="lightning-bolt", target_id="mon:mid"
            ),
        )
        return live

    live = run_async(_run())
    mid_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:mid"]
    near_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:near"]
    offline_dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:offline"]

    assert mid_dmg
    assert mid_dmg[0].damage_type == "lightning"
    assert 8 <= mid_dmg[0].amount <= 48
    assert near_dmg, "mon:near sits on the bolt's own path and must also be hit"
    assert not offline_dmg


def test_c16_s04_creature_standing_between_attacker_and_target_grants_half_cover():
    """C16-S04: SRD 5.2 §Cover — "A target with half cover has a +2 bonus
    to AC and Dexterity saving throws." Offered By: "Another creature or
    an object that covers at least half of the target."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id hv0J61IAfofuhy3Q, heading "Half Cover"; table text
    packs/_source/content24/chapter-1/combat.yml, id 12ZJOcieI7vPpryj,
    heading "Cover"). ``spatial.py::cover_between`` only consults
    ``GridScene.cover_cells`` (host-authored) — it never inspects live
    combatant occupancy, so an interposed creature grants zero cover
    today (same-seed A/B: identical roll, identical hit).
    """
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests
    from tests.test_orchestrator_gating_typed import _ranged_weapon

    def _party():
        return [
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

    def _foe():
        return EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=50,
            hp_max=50,
            ac=10,
            zone_id=cell(2, 0),
        )

    async def _run(encounter):
        set_lib_loader_for_tests(
            MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
        )
        start = await start_combat(
            session_id="e2e-c16-s04",
            party=_party(),
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run([_foe()]))
    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:foe")

    blocker = EncounterMemberSpec(
        entity_id="mon:blocker",
        entity_type="Monster",
        name="Blocker",
        initiative=2,
        hp_current=50,
        hp_max=50,
        ac=10,
        zone_id=cell(1, 0),
    )
    live_b = run_async(_run([_foe(), blocker]))
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:foe")

    assert rolled_a.roll_total == rolled_b.roll_total
    assert rolled_a.is_hit is True
    assert rolled_b.is_hit is False


def test_c16_s05_blocked_cell_blocks_los_and_wall_blocks_corner_cutting():
    """C16-S05: SRD 5.2 §Areas of Effect / Point of Origin — "To block a
    line, an obstruction must provide Total Cover."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml,
    id 8HxbRceQQUAhyWRt). §Playing on a Grid, "Corners" — "Diagonal
    movement can't cross the corner of a wall, a large tree, or another
    terrain feature that fills its space."
    (packs/_source/content24/chapter-1/combat.yml, id E9fzdKGx4UxrtOG7).
    ``has_line_of_sight`` walks ``wall_segments`` only, never
    ``blocked_cells``; ``_neighbors`` offers all 8 directions
    unconditionally with no corner-cutting guard.
    """
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests
    from tests.test_orchestrator_gating_typed import _ranged_weapon

    # Part A — a blocked cell (no wall) should block line of sight.
    async def _run_a():
        set_lib_loader_for_tests(
            MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
        )
        start = await start_combat(
            session_id="e2e-c16-s05-a",
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
                    ac=15,
                    zone_id=cell(4, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(width=10, height=10, blocked_cells=[cell(2, 0)]),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run_a())
    attack_failed_a = events_of(live_a, AttackFailed)
    assert attack_failed_a, "blocked cell should block LoS and reject the ranged attack"
    assert attack_failed_a[0].reason == "out_of_range"
    assert not events_of(live_a, AttackRolled)

    # Part B — a diagonal step that would cut a wall's corner is rejected.
    async def _run_b():
        set_lib_loader_for_tests(MemoryAssetLoader())
        start = await start_combat(
            session_id="e2e-c16-s05-b",
            party=[
                PartyMemberSpec(
                    entity_id="char:mover",
                    name="Mover",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
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
                    zone_id=cell(4, 4),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(
                width=5,
                height=5,
                blocked_cells=[cell(1, 0)],
                wall_segments=[{"x1": 1, "y1": 0, "x2": 1, "y2": 1}],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:mover",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell(1, 1)),
        )
        return live

    live_b = run_async(_run_b())
    move_failed_b = events_of(live_b, MoveFailed)
    assert move_failed_b, "diagonal step cutting the wall's corner should be rejected"
    assert not events_of(live_b, ActorMoved)
    assert live_b.actor_zone["char:mover"] == cell(0, 0)


def test_c16_s06_multicell_move_succeeds_with_terrain_cost_or_fails_unreachable_or_occupied():
    """C16-S06: SRD 5.2 §Movement and Position, "Playing on a Grid" —
    "It costs 1 square of movement to enter an unoccupied square that's
    adjacent to your space." (packs/_source/content24/chapter-1/combat.yml,
    id E9fzdKGx4UxrtOG7), combined with §Difficult Terrain's doubled
    entry cost (id hFW5BR2yHHwwgurD) and §Moving Around Other Creatures —
    "You can't willingly end a move in a space occupied by another
    creature." (id 9ZWCknaXCOdhyOrX). ``_handle_move`` only accepts a
    SINGLE adjacent-cell hop today — any non-adjacent ``target_zone_id``
    (including a perfectly legal 3-square straight line) rejects with
    ``MoveFailed(reason="not_adjacent")``; ``"unreachable"`` does not
    exist on ``MoveFailed.reason`` yet, and occupied-cell entry is
    unchecked entirely.
    """
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests

    def _hero():
        return PartyMemberSpec(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            base_speed=30,
            zone_id=cell(0, 0),
        )

    def _occupant():
        return EncounterMemberSpec(
            entity_id="mon:occupant",
            entity_type="Monster",
            name="Occupant",
            initiative=1,
            hp_current=10,
            hp_max=10,
            ac=10,
            zone_id=cell(4, 0),
        )

    async def _run(grid_scene_obj, encounter, target_zone_id):
        set_lib_loader_for_tests(MemoryAssetLoader())
        start = await start_combat(
            session_id="e2e-c16-s06",
            party=[_hero()],
            encounter=encounter,
            scene_zones=None,
            grid_scene=grid_scene_obj,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=target_zone_id),
        )
        return live

    # Run A — succeeds with a difficult-terrain leg, single intent to (3,0).
    live_a = run_async(
        _run(
            GridScene(width=10, height=10, difficult_terrain_cells=[cell(2, 0)]),
            [_occupant()],
            cell(3, 0),
        )
    )
    moved_a = events_of(live_a, ActorMoved)
    assert moved_a
    assert moved_a[-1].to_zone == cell(3, 0)
    assert moved_a[-1].distance_ft == 20
    hero_a = next(c for c in live_a.initiative if c.entity_id == "char:hero")
    assert hero_a.movement_remaining == 10
    assert not events_of(live_a, MoveFailed)

    # Run B — unreachable (boxed in on all sides; the occupant sits outside
    # the box and plays no part). ``start_combat`` requires a non-empty
    # encounter, so the occupant is carried along as inert scenery.
    boxed = GridScene(
        width=10,
        height=10,
        wall_segments=[
            {"x1": -2, "y1": -2, "x2": 3, "y2": -2},
            {"x1": -2, "y1": 3, "x2": 3, "y2": 3},
            {"x1": -2, "y1": -2, "x2": -2, "y2": 3},
            {"x1": 3, "y1": -2, "x2": 3, "y2": 3},
        ],
    )
    live_b = run_async(_run(boxed, [_occupant()], cell(9, 9)))
    failed_b = events_of(live_b, MoveFailed)
    assert failed_b
    assert failed_b[0].reason == "unreachable"
    assert live_b.actor_zone["char:hero"] == cell(0, 0)

    # Run C — occupied destination (mon:occupant's own cell).
    live_c = run_async(_run(GridScene(width=10, height=10), [_occupant()], cell(4, 0)))
    failed_c = events_of(live_c, MoveFailed)
    assert failed_c
    assert live_c.actor_zone["char:hero"] == cell(0, 0)
    assert live_c.actor_zone["mon:occupant"] == cell(4, 0)


def test_c16_s07_thunderwave_pushes_failed_save_target_10ft_away():
    """C16-S07: SRD 5.2 §Spell Descriptions, Thunderwave — "On a failed
    save, a creature takes 2d8 Thunder damage and is pushed 10 feet away
    from you." (packs/_source/spells24/1st-level/thunderwave.yml,
    phbsplThunderwav). Authored against a886f77, where no push/forced-movement
    primitive existed anywhere in ``orchestrator.py`` and ``events.py`` had no
    ``CombatantMoved`` event, so the save/damage resolved but the target never
    moved. C16 ships both (``orchestrator.push_combatant`` +
    ``events.CombatantMoved``); this scenario now passes unchanged.

    Seed choice: rng_seed=1 — verified on main a886f77: 2d8 drawn first,
    then the Constitution d20 = 9 vs DC 10 (INT 10 wizard, +0 CON foe) →
    failed save. Seed 7 (the catalog placeholder) rolls 13 and succeeds.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c16-s07",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    character_level=3,
                    class_slug="wizard",
                    spells_known=["thunderwave"],
                    spell_slots={1: 1},
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
                    ac=10,
                    dexterity=8,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="thunderwave", target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    saves = [e for e in events_of(live, SaveRolled) if e.target_id == "mon:foe"]
    assert saves
    assert saves[0].ability == "con"
    assert saves[0].succeeded is False

    dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
    assert dmg
    assert dmg[0].damage_type == "thunder"
    assert 2 <= dmg[0].amount <= 16

    # API delta (C16): CombatantMoved(forced=True) did not exist on a886f77 —
    # looked up dynamically so the AttributeError itself drove the xfail. C16
    # added it; the dynamic lookup is kept so the scenario body is untouched.
    from dnd5e_engine import events as events_module

    combatant_moved_cls = events_module.CombatantMoved
    pushes = [
        e for e in live.event_log if isinstance(e, combatant_moved_cls) and e.actor_id == "mon:foe"
    ]
    assert pushes
    assert pushes[0].forced is True
    assert pushes[0].to_zone == cell(3, 0)


def test_c16_s08_target_in_darkness_without_darkvision_grants_attack_disadvantage():
    """C16-S08 (C16b): SRD 5.2 §Vision and Light — "A Heavily Obscured
    area—such as an area with Darkness... is opaque. You have the
    Blinded condition when trying to see something there."
    (packs/_source/content24/chapter-1/exploration.yml, "Vision and
    Light"), combined with "an attack roll against a target you can't
    see is made at Disadvantage" (Unseen Attackers and Targets).
    ``GridScene`` (specs.py) carries ``lighting`` / ``default_lighting``
    / ``obscurement_cells``, and ``GridTopology.can_see`` reads them
    together with the viewer's senses; ``_target_visibility_maps``
    (orchestrator.py) threads the result into the attack resolver as the
    ``unseen`` advantage source. The lit run therefore resolves on a
    single d20 and the dark run at Disadvantage. Before C16b the scene
    had geometry fields only and both runs resolved identically.
    """
    from dnd5e_srd_data import MemoryAssetLoader

    from dnd5e_engine.lib_loader import set_lib_loader_for_tests
    from tests.test_orchestrator_gating_typed import _ranged_weapon

    def _hero_kwargs() -> dict:
        return dict(
            entity_id="char:hero",
            name="Hero",
            initiative=20,
            hp_current=20,
            hp_max=20,
            attack_bonus=5,
            zone_id=cell(0, 0),
        )

    def _foe():
        return EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=50,
            hp_max=50,
            ac=10,
            zone_id=cell(4, 0),
        )

    async def _run(grid_kwargs: dict):
        set_lib_loader_for_tests(
            MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
        )
        start = await start_combat(
            session_id="e2e-c16-s08",
            party=[PartyMemberSpec(**_hero_kwargs())],
            encounter=[_foe()],
            scene_zones=None,
            # API delta (C16b): GridScene.lighting is not a field today —
            # building the kwargs dict and unpacking it fails inside the
            # function body (extra="forbid"), not at collection time.
            grid_scene=GridScene(**grid_kwargs),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run(dict(width=10, height=10)))
    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:foe")

    dark_kwargs = dict(width=10, height=10, lighting={cell(4, 0): "dark"})
    live_b = run_async(_run(dark_kwargs))
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:foe")

    assert rolled_a.advantage == "normal"
    assert rolled_b.advantage == "disadvantage"
