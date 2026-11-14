"""The monster AI's closing walk honours occupancy.

SRD 5.2 Moving Around Other Creatures: "During your move, you can pass
through the space of an ally, a creature that has the Incapacitated condition
(see "Rules Glossary"), a Tiny creature, or a creature that is two sizes
larger or smaller than you." and "You can't willingly end a move in a space
occupied by another creature."

The engine applies a simpler rule, the same one a ``move`` intent follows
(``_handle_move``): an ally's space may be passed through, and every other
creature's space blocks the walk. No walk ends on an occupied cell. A walk
that meets no creature goes the same way it always did.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any

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
    entity_id: str,
    at: str,
    *,
    initiative: int = 2,
    slug: str = "goblin-warrior",
    **fields: Any,
) -> EncounterMemberSpec:
    """A real corpus monster; the walker acts first (initiative 20)."""
    base: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": "Monster",
        "name": entity_id.removeprefix("mon:").title(),
        "initiative": initiative,
        "hp_current": 20,
        "hp_max": 20,
        "ac": 15,
        "monster_template_slug": slug,
        "zone_id": at,
    }
    return EncounterMemberSpec(**(base | fields))


def _walker(at: str, slug: str = "goblin-warrior", **fields: Any) -> EncounterMemberSpec:
    return _goblin("mon:walker", at, initiative=20, slug=slug, **fields)


class _MaxRandom(random.Random):
    """Every ``randint(a, b)`` draw returns ``b``: each d20 is a natural 20."""

    def randint(self, a: int, b: int) -> int:
        del a
        return b


def _turn(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    scene: GridScene,
    *,
    seed: int = 1,
    prepare: Callable[[_LiveCombat], None] | None = None,
) -> _LiveCombat:
    """Start the fight, let ``prepare`` adjust it, then run the walker's turn."""

    async def _run() -> _LiveCombat:
        start = await start_combat(
            session_id=f"closing-walk-{seed}",
            party=party,
            encounter=encounter,
            grid_scene=scene,
            rng_seed=seed,
        )
        live = _get_live(start.handle)
        if prepare is not None:
            prepare(live)
        await advance_monster_turn(start.handle)
        return live

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

    # No free cell touches the target, so the walker spends its movement on
    # the route in and stops on its last free cell, two cells short.
    assert _steps(live) == [
        (cell_id(0, 5), cell_id(1, 4), 5),
        (cell_id(1, 4), cell_id(2, 3), 5),
        (cell_id(2, 3), cell_id(3, 3), 5),
    ]
    assert _no_shared_cell(live)
    assert _intent(live) == "pass"
    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert _walker_swings(live) == []


def test_a_foe_never_walks_through_an_enemy_it_is_not_targeting() -> None:
    # A one-row corridor: the foe goes for the wounded far character and the
    # near one stands in the way.
    live = _turn(
        [_pc("char:near", cell_id(2, 0)), _pc("char:far", cell_id(5, 0), hp=5)],
        [_walker(cell_id(0, 0))],
        GridScene(width=8, height=1),
    )

    # No route reaches the far character, so the walker stays where it is.
    assert _steps(live) == []
    assert live.actor_zone["mon:walker"] == cell_id(0, 0)
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


def test_an_unobstructed_walk_goes_round_the_wall_and_attacks() -> None:
    # No creature stands on or beside the route, so it is the fewest-cells
    # route of the walk that ignores occupancy. The cell beside the target
    # costs exactly the walker's 30 ft, so no Dash is needed and it attacks.
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
    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert _intent(live) == "attack"
    assert {e.target_id for e in _walker_swings(live)} == {"char:hero"}


def test_a_walk_that_ends_in_reach_without_a_dash_attacks() -> None:
    # The target's own cell is 35 ft away, but the cell beside it is 30 ft.
    live = _turn(
        [_pc("char:hero", cell_id(7, 0))],
        [_walker(cell_id(0, 0))],
        GridScene(width=20, height=1),
    )

    assert live.actor_zone["mon:walker"] == cell_id(6, 0)
    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert _intent(live) == "attack"


def test_a_walk_that_needs_a_dash_to_reach_takes_it() -> None:
    # The cell beside the target is 60 ft away: within one Dash.
    live = _turn(
        [_pc("char:hero", cell_id(13, 0))],
        [_walker(cell_id(0, 0))],
        GridScene(width=20, height=1),
    )

    [dash] = [e for e in live.event_log if isinstance(e, DashTaken)]
    assert dash.doubled_movement_remaining == 60
    assert live.actor_zone["mon:walker"] == cell_id(12, 0)
    assert _intent(live) == "dash"


def test_a_cheaper_free_cell_beats_an_expensive_route_through_difficult_terrain() -> None:
    # Row 0 is difficult terrain from column 1: the fewest-cells route costs
    # 60 ft to reach the target's side, the row below costs 30 ft.
    scene = GridScene(
        width=12,
        height=2,
        difficult_terrain_cells=[cell_id(c, 0) for c in range(1, 12)],
    )
    live = _turn([_pc("char:hero", cell_id(7, 0))], [_walker(cell_id(0, 0))], scene)

    assert live.actor_zone["mon:walker"] == cell_id(6, 1)
    assert sum(ft for _from, _to, ft in _steps(live)) == 30
    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert _intent(live) == "attack"


def test_with_its_action_spent_a_walker_cannot_dash_to_a_free_cell() -> None:
    # The free cell beside the target (8,1) needs a Dash; the Action is gone,
    # so the walker walks the route in and stops on its last free cell.
    def spend_action(live: _LiveCombat) -> None:
        for idx, c in enumerate(live.initiative):
            if c.entity_id == "mon:walker":
                live.initiative[idx] = c.model_copy(update={"action_available": False})

    live = _turn(
        [_pc("char:hero", cell_id(8, 0))],
        [
            _walker(cell_id(1, 0)),
            _goblin("mon:ally", cell_id(7, 0)),
            _goblin("mon:other", cell_id(7, 1)),
        ],
        GridScene(width=10, height=2),
        prepare=spend_action,
    )

    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert live.actor_zone["mon:walker"] == cell_id(6, 0)
    assert _no_shared_cell(live)
    assert _intent(live) == "pass"


def test_a_walker_with_speed_zero_stays_put() -> None:
    live = _turn(
        [_pc("char:hero", cell_id(5, 0))],
        [_walker(cell_id(0, 0), base_speed=0)],
        GridScene(width=8, height=1),
    )

    assert _steps(live) == []
    assert live.actor_zone["mon:walker"] == cell_id(0, 0)
    assert not [e for e in live.event_log if isinstance(e, DashTaken)]
    assert _intent(live) == "pass"


def test_an_opportunity_attack_can_leave_the_walker_on_its_allys_cell() -> None:
    # The walker (Speed 10) passes through its ally on 1,0; stepping on to
    # 2,0 leaves the guard's reach, and the guard's club (Slow mastery)
    # takes the walker's Speed to 0 while it still stands on the ally's cell.
    # It did not choose to end there; the walk simply stops.
    guard = PartyMemberSpec(
        entity_id="char:guard",
        name="Guard",
        initiative=1,
        hp_current=30,
        hp_max=30,
        ac=12,
        zone_id=cell_id(0, 1),
        equipment=("club",),
        opportunity_attack_weapon_id="club",
    )

    def natural_twenties(live: _LiveCombat) -> None:
        live.rng = _MaxRandom()

    live = _turn(
        [guard, _pc("char:hero", cell_id(3, 0), hp=5)],
        [_walker(cell_id(0, 0), base_speed=10), _goblin("mon:ally", cell_id(1, 0))],
        GridScene(width=4, height=2),
        prepare=natural_twenties,
    )

    opportunity = [
        e for e in live.event_log if isinstance(e, AttackRolled) and e.is_opportunity_attack
    ]
    assert [(e.attacker_id, e.target_id, e.is_hit) for e in opportunity] == [
        ("char:guard", "mon:walker", True)
    ]
    assert _steps(live) == [(cell_id(0, 0), cell_id(1, 0), 5)]
    assert live.actor_zone["mon:walker"] == live.actor_zone["mon:ally"] == cell_id(1, 0)
    assert _intent(live) == "pass"
