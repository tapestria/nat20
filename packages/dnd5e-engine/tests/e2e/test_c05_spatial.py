"""C05 — Spatial (walls, LoS, cover, AoE, terrain).

Transcribed from specs/e2e-scenario-catalog.md, Cluster 5.
"""

from __future__ import annotations

from dnd5e_srd_data import MemoryAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import ActorMoved, AttackFailed, AttackRolled, DamageApplied, MoveFailed
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import events_of, run_async, xfail_cluster
from tests.test_orchestrator_gating_typed import _ranged_weapon


@xfail_cluster(5, "Spatial")
def test_c05_s01_wall_segment_blocks_line_of_sight_gating_ranged_attack():
    """C05-S01: A wall segment between attacker and target blocks line of
    sight, gating an in-range ranged attack.

    SRD 5.2 §Areas of Effect ("If all straight lines extending from the
    point of origin to a location in the area of effect are blocked, that
    location isn't included in the area of effect. To block a line, an
    obstruction must provide Total Cover." —
    packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-references.yml,
    journal page `On6Sg3vUokAkXBB5`, "Area of Effect"); engine:
    packages/dnd5e-engine/src/dnd5e_engine/spatial.py
    (`GridTopology.has_line_of_sight` — v1 always returns `True`),
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_in_range_with_los`, line ~433 — `within_range(a, b, range_ft) and
    has_line_of_sight(a, b)`; the false-LoS gate is already proven wired by
    `test_false_line_of_sight_gates_pc_attack` in
    packages/dnd5e-engine/tests/test_orchestrator_grid_combat.py — only the
    geometry backing `has_line_of_sight` is missing).
    """
    set_lib_loader_for_tests(
        MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
    )

    async def _run():
        start = await start_combat(
            session_id="e2e-c05-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    zone_id=cell_id(0, 0),
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
                    zone_id=cell_id(4, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(
                width=10,
                height=10,
                wall_segments=[{"x1": 2, "y1": 0, "x2": 2, "y2": 10}],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[0].actor_id == "char:hero"
    assert failed[0].target_id == "mon:foe"
    assert failed[0].reason == "out_of_range"
    assert not events_of(live, AttackRolled)
    assert not events_of(live, DamageApplied)


@xfail_cluster(5, "Spatial")
def test_c05_s02_half_cover_adds_plus2_ac_flips_hit_to_miss_same_seed():
    """C05-S02: Half cover adds +2 to a target's effective AC for a ranged
    attack (same-seed A/B: the identical natural roll hits base AC but
    misses AC+2).

    SRD 5.2 §Cover
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-references.yml,
    journal page `hv0J61IAfofuhy3Q`, "Half Cover": *"A target with half
    cover has a +2 bonus to AC and Dexterity saving throws."*; Foundry
    system parity: `config.mjs:3590` `DND5E.cover = {0: "None", .5:
    "CoverHalf", .75: "CoverThreeQuarters", 1: "CoverTotal"}`,
    `config.mjs:3818-3835` status effects
    `coverHalf`/`coverThreeQuarters`/`coverTotal`); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py
    (`_resolve_hit_outcome`, line ~284 — `total >= target_ac`, no cover
    term anywhere in `attack.py` or `spatial.py`).
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
                zone_id=cell_id(0, 0),
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=50,
                hp_max=50,
                ac=10,
                zone_id=cell_id(2, 0),
            )
        ]

    async def _run(grid_scene):
        set_lib_loader_for_tests(
            MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
        )
        start = await start_combat(
            session_id="e2e-c05-s02",
            party=_party(),
            encounter=_encounter(),
            scene_zones=None,
            grid_scene=grid_scene,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live_a = run_async(_run(GridScene(width=10, height=10)))
    rolled_a = next(e for e in events_of(live_a, AttackRolled) if e.target_id == "mon:foe")

    live_b = run_async(_run(GridScene(width=10, height=10, cover_cells={cell_id(1, 0): "half"})))
    rolled_b = next(e for e in events_of(live_b, AttackRolled) if e.target_id == "mon:foe")

    assert rolled_a.roll_total == 10
    assert rolled_b.roll_total == 10
    assert rolled_a.is_hit is True
    assert rolled_b.is_hit is False


@xfail_cluster(5, "Spatial")
def test_c05_s03_total_cover_makes_target_untargetable():
    """C05-S03: Total cover makes a target untargetable, rejecting an
    otherwise in-range ranged attack.

    SRD 5.2 §Cover
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-references.yml,
    journal page `BKUAxXuPEzxiEOeL`, "Total Cover": *"A target with total
    cover can't be targeted directly."*); engine: same gap as C05-S02 —
    packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py has no
    cover consumer at all, and
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_in_range_with_los
    (line ~433) has only two conjuncts (`within_range`,
    `has_line_of_sight`) — no cover-derived third conjunct exists.
    """
    set_lib_loader_for_tests(
        MemoryAssetLoader(items=[_ranged_weapon(slug="longbow", normal=30, long=120)])
    )

    async def _run():
        start = await start_combat(
            session_id="e2e-c05-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    zone_id=cell_id(0, 0),
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
                    ac=12,
                    zone_id=cell_id(3, 0),
                )
            ],
            scene_zones=None,
            grid_scene=GridScene(
                width=10,
                height=10,
                cover_cells={cell_id(1, 0): "total"},
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", weapon_id="longbow", target_id="mon:foe"),
        )
        return live

    live = run_async(_run())
    failed = events_of(live, AttackFailed)
    assert failed
    assert failed[0].actor_id == "char:hero"
    assert failed[0].target_id == "mon:foe"
    assert failed[0].reason == "out_of_range"
    assert not events_of(live, AttackRolled)
    assert not events_of(live, DamageApplied)


@xfail_cluster(5, "Spatial")
def test_c05_s04_cells_in_template_sphere_returns_81_cell_chebyshev_set():
    """C05-S04: `cells_in_template` returns the exact 81-cell set for a
    20 ft sphere on a 5 ft grid.

    SRD 5.2 §Areas of Effect, Sphere
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-references.yml,
    journal page `npdEWb2egUPnB5Fa`, "Sphere": *"A Sphere is an area of
    effect that extends in straight lines from a point of origin outward
    in all directions... A Sphere's point of origin is included in the
    Sphere's area of effect."*); real SRD grounding for the 20 ft radius:
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/fireball.json
    (`target.template = {type: "sphere", size: "20", units: "ft"}`);
    Foundry parity: `config.mjs:2794-2805`,
    `DND5E.areaTargetTypes.circle = {template: "circle", sizes:
    ["radius"]}`. Engine: packages/dnd5e-engine/src/dnd5e_engine/spatial.py
    — no `cells_in_template` anywhere in the module; `GridTopology`'s
    public surface is `is_adjacent`/`edge_distance`/`within_range`/
    `has_line_of_sight`/`is_valid_cell`/`shortest_path` only.

    Geometric convention: **Chebyshev** cell distance (maintainer
    decision, 2026-07-02), consistent with the SRD 5.2 grid rules and
    `GridTopology`'s existing metric for `within_range`/`is_adjacent`/
    `shortest_path`. Pure geometry probe — no live combat needed.
    """
    topo = GridTopology(GridScene(width=21, height=21, cell_size_ft=5))
    cells_in_template = getattr(topo, "cells_in_template", None)
    assert cells_in_template is not None, "cells_in_template not yet defined"

    cells = cells_in_template(origin="10,10", shape="sphere", size_ft=20)

    assert len(cells) == 81
    assert "10,10" in cells  # origin — SRD 5.2's "point of origin is included"
    assert "14,10" in cells  # dx=4, dy=0 — 4 squares, IN
    assert "14,14" in cells  # dx=4, dy=4 — Chebyshev 4, IN
    assert "15,10" not in cells  # dx=5 — OUT
    assert "15,15" not in cells  # dx=5, dy=5 — OUT


@xfail_cluster(5, "Spatial")
def test_c05_s05_difficult_terrain_doubles_movement_cost_refusing_move():
    """C05-S05: Difficult terrain doubles the movement cost of entering a
    cell, refusing a move a normal-terrain budget would afford (same-seed
    A/B).

    SRD 5.2 §Difficult Terrain
    (packages/dnd5e-srd-data/raw_sources/foundry/packs/_source/content24/appendices/appendix-d-rule-references.yml,
    journal page `hFW5BR2yHHwwgurD`: *"Every foot of movement in Difficult
    Terrain costs 1 extra foot, even if multiple things in a space count
    as Difficult Terrain."*); engine:
    packages/dnd5e-engine/src/dnd5e_engine/spatial.py
    (`GridTopology.edge_distance` — always returns the flat
    `cell_size_ft`, no terrain-cost term),
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py
    (`_handle_move`, line ~2626 — `distance_ft =
    live.topology.edge_distance(current_zone, target_zone_id)`; `if
    current.movement_remaining < distance_ft: MoveFailed(reason=
    "insufficient_movement")` — the `"insufficient_movement"` literal
    already exists on `MoveFailed.reason`, so no new event schema is
    needed, only a correct cost feeding it).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                base_speed=5,
                zone_id=cell_id(0, 0),
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:foe",
                entity_type="Monster",
                name="Foe",
                initiative=1,
                hp_current=50,
                hp_max=50,
                zone_id=cell_id(9, 9),
            )
        ]

    async def _run(grid_scene):
        set_lib_loader_for_tests(MemoryAssetLoader())
        start = await start_combat(
            session_id="e2e-c05-s05",
            party=_party(),
            encounter=_encounter(),
            scene_zones=None,
            grid_scene=grid_scene,
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id=cell_id(1, 0)),
        )
        return live

    live_a = run_async(_run(GridScene(width=10, height=10)))
    moved_a = events_of(live_a, ActorMoved)
    assert moved_a
    assert moved_a[-1].from_zone == "0,0"
    assert moved_a[-1].to_zone == "1,0"
    assert moved_a[-1].distance_ft == 5
    assert live_a.actor_zone["char:hero"] == "1,0"
    hero_a = next(c for c in live_a.initiative if c.entity_id == "char:hero")
    assert hero_a.movement_remaining == 0

    live_b = run_async(
        _run(GridScene(width=10, height=10, difficult_terrain_cells=[cell_id(1, 0)]))
    )
    failed_b = events_of(live_b, MoveFailed)
    assert failed_b
    assert failed_b[0].actor_id == "char:hero"
    assert failed_b[0].reason == "insufficient_movement"
    assert not events_of(live_b, ActorMoved)
    assert live_b.actor_zone["char:hero"] == "0,0"
    hero_b = next(c for c in live_b.initiative if c.entity_id == "char:hero")
    assert hero_b.movement_remaining == 5
