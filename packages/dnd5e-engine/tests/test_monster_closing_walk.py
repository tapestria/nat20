"""The monster AI's closing walk honours occupancy.

SRD 5.2 Moving Around Other Creatures: "You can't willingly end a move in a
space occupied by another creature." An enemy's space blocks movement and an
ally's may be passed through, the same rule a ``move`` intent already follows
(``_handle_move``). A walk that meets no creature is unchanged.
"""

from __future__ import annotations

import asyncio

from dnd5e_engine.events import ActorMoved, AttackRolled, DashTaken, IntentSubmitted
from dnd5e_engine.orchestrator import _get_live, _LiveCombat, advance_monster_turn, start_combat
from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec, WallSegment


def _pc(entity_id: str, at: str, *, hp: int = 30) -> PartyMemberSpec:
    return PartyMemberSpec(
        entity_id=entity_id,
        name=entity_id.removeprefix("char:").title(),
        initiative=1,
        hp_current=hp,
        hp_max=30,
        ac=12,
        zone_id=at,
    )


def _goblin(
    entity_id: str, at: str, *, initiative: int = 2, slug: str = "goblin-warrior"
) -> EncounterMemberSpec:
    """A real corpus monster; the walker acts first (initiative 20)."""
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name=entity_id.removeprefix("mon:").title(),
        initiative=initiative,
        hp_current=20,
        hp_max=20,
        ac=15,
        monster_template_slug=slug,
        zone_id=at,
    )


def _walker(at: str, slug: str = "goblin-warrior") -> EncounterMemberSpec:
    return _goblin("mon:walker", at, initiative=20, slug=slug)


def _turn(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    scene: GridScene,
    *,
    seed: int = 1,
) -> _LiveCombat:
    async def _run() -> _LiveCombat:
        start = await start_combat(
            session_id=f"closing-walk-{seed}",
            party=party,
            encounter=encounter,
            grid_scene=scene,
            rng_seed=seed,
        )
        await advance_monster_turn(start.handle)
        return _get_live(start.handle)

    return asyncio.run(_run())


def _steps(live: _LiveCombat) -> list[tuple[str, str, int]]:
    return [
        (e.from_zone, e.to_zone, e.distance_ft)
        for e in live.event_log
        if isinstance(e, ActorMoved) and e.actor_id == "mon:walker"
    ]


def _intent(live: _LiveCombat) -> str:
    [intent] = [
        e.intent_type
        for e in live.event_log
        if isinstance(e, IntentSubmitted) and e.actor_id == "mon:walker"
    ]
    return intent


def _walker_swings(live: _LiveCombat) -> list[AttackRolled]:
    return [
        e for e in live.event_log if isinstance(e, AttackRolled) and e.attacker_id == "mon:walker"
    ]


def _no_shared_cell(live: _LiveCombat) -> bool:
    cells = list(live.actor_zone.values())
    return len(cells) == len(set(cells))


def test_a_foe_behind_its_ally_ends_on_a_free_cell_in_reach_and_attacks() -> None:
    live = _turn(
        [_pc("char:hero", cell_id(5, 0))],
        [_walker(cell_id(1, 0)), _goblin("mon:ally", cell_id(4, 0))],
        GridScene(width=8, height=2),
    )

    assert live.actor_zone["mon:walker"] == cell_id(4, 1)
    assert _no_shared_cell(live)
    assert _intent(live) == "attack"
    assert [e.target_id for e in _walker_swings(live)] == ["char:hero"]


def test_a_foe_may_pass_through_an_ally_but_not_end_on_one() -> None:
    live = _turn(
        [_pc("char:hero", cell_id(4, 0))],
        [
            _walker(cell_id(0, 0)),
            _goblin("mon:passed", cell_id(1, 0)),
            _goblin("mon:beside", cell_id(3, 0)),
        ],
        GridScene(width=8, height=2),
    )

    assert _steps(live) == [
        (cell_id(0, 0), cell_id(1, 0), 5),
        (cell_id(1, 0), cell_id(2, 0), 5),
        (cell_id(2, 0), cell_id(3, 1), 5),
    ]
    assert _no_shared_cell(live)
    assert _intent(live) == "attack"


def test_a_ringed_target_leaves_the_foe_on_the_nearest_free_cell() -> None:
    ring = [
        _goblin(f"mon:ring{i}", cell_id(5 + dc, 5 + dr))
        for i, (dc, dr) in enumerate(
            (dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0)
        )
    ]
    live = _turn(
        [_pc("char:hero", cell_id(5, 5))],
        [_walker(cell_id(0, 5)), *ring],
        GridScene(width=10, height=10),
    )

    grid = GridTopology(GridScene(width=10, height=10))
    assert grid.distance_ft(live.actor_zone["mon:walker"], cell_id(5, 5)) == 10
    assert _no_shared_cell(live)
    assert _intent(live) in {"pass", "dash"}
    assert _walker_swings(live) == []


def test_a_foe_never_walks_through_an_enemy_it_is_not_targeting() -> None:
    # A one-row corridor: the foe goes for the wounded far character and the
    # near one stands in the way.
    live = _turn(
        [_pc("char:near", cell_id(2, 0)), _pc("char:far", cell_id(5, 0), hp=5)],
        [_walker(cell_id(0, 0))],
        GridScene(width=8, height=1),
    )

    assert cell_id(2, 0) not in {to for _from, to, _ft in _steps(live)}
    assert live.actor_zone["mon:walker"] in {cell_id(0, 0), cell_id(1, 0)}
    assert _intent(live) == "pass"
    assert _walker_swings(live) == []


def test_a_ranged_foe_whose_first_sight_line_cell_is_taken_finds_another() -> None:
    # The wall hides the character from the scout; the first cell with a
    # line of sight on the shortest route (2,3) holds the scout's ally.
    scene = GridScene(width=10, height=10, wall_segments=[WallSegment(x1=3, y1=0, x2=3, y2=3)])
    live = _turn(
        [_pc("char:hero", cell_id(0, 0))],
        [_walker(cell_id(5, 0), slug="scout"), _goblin("mon:ally", cell_id(2, 3))],
        scene,
    )

    end = live.actor_zone["mon:walker"]
    grid = GridTopology(scene)
    assert end != cell_id(2, 3)
    assert grid.has_line_of_sight(end, cell_id(0, 0))
    assert _no_shared_cell(live)
    assert _intent(live) == "attack"
    assert {e.target_id for e in _walker_swings(live)} == {"char:hero"}


def test_a_free_cell_only_a_dash_reaches_takes_the_dash() -> None:
    # The route's last cell before the target (7,0) holds an ally; the
    # nearest free cell in reach (8,1) is 35 ft away, beyond 30 ft of Speed.
    live = _turn(
        [_pc("char:hero", cell_id(8, 0))],
        [
            _walker(cell_id(1, 0)),
            _goblin("mon:ally", cell_id(7, 0)),
            _goblin("mon:other", cell_id(7, 1)),
        ],
        GridScene(width=10, height=2),
    )

    [dash] = [e for e in live.event_log if isinstance(e, DashTaken)]
    assert dash.doubled_movement_remaining == 60
    assert live.actor_zone["mon:walker"] == cell_id(8, 1)
    assert _no_shared_cell(live)
    assert _intent(live) == "dash"


def test_an_unobstructed_walk_keeps_its_cells() -> None:
    # Frozen from the walk before occupancy was honoured: no creature stands
    # on or beside the route, so the route is the same cell for cell.
    live = _turn(
        [_pc("char:hero", cell_id(1, 2))],
        [_walker(cell_id(6, 6))],
        GridScene(width=10, height=10, wall_segments=[WallSegment(x1=4, y1=2, x2=4, y2=6)]),
        seed=3,
    )

    assert _steps(live) == [
        ("6,6", "5,5", 5),
        ("5,5", "4,6", 5),
        ("4,6", "3,6", 5),
        ("3,6", "2,5", 5),
        ("2,5", "1,4", 5),
        ("1,4", "0,3", 5),
    ]
    assert _intent(live) == "dash"
