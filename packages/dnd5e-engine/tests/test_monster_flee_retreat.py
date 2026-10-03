"""Unit tests for the grid flee planner (``_plan_flee_route``).

The planner picks the cell a fleeing monster can reach that is farthest from
its NEAREST threat (Chebyshev distance), breaking ties by the cheapest route
and then the lowest ``(column, row)``, and returns the route to it — or
``None`` when nothing reachable is farther than standing still. Exercised
directly against ``GridTopology`` so the selection logic is pinned
independent of the full turn machinery.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _plan_flee_route
from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import GridScene


def _plan(grid, start, threats, budget, *, enemies=None, occupied=()):
    return _plan_flee_route(
        grid,
        start,
        threats,
        budget,
        enemy_cells=threats if enemies is None else enemies,
        occupied_cells=[*threats, *occupied],
    )


def test_flee_runs_to_the_farthest_reachable_cell_along_its_cheapest_route() -> None:
    grid = GridTopology(GridScene(width=10, height=10))
    route = _plan(grid, cell_id(3, 0), [cell_id(0, 0)], 30)
    # Column 9 is the farthest any 6-step route reaches (45 ft from the
    # threat); 9,0 is the lowest (column, row) among the cells tied there.
    assert route == [cell_id(c, 0) for c in range(3, 10)]


def test_flee_returns_none_when_the_budget_reaches_nothing_farther() -> None:
    grid = GridTopology(GridScene(width=10, height=10))
    assert _plan(grid, cell_id(3, 0), [cell_id(0, 0)], 0) is None


def test_flee_returns_none_when_cornered() -> None:
    # The monster's pocket is 0,0 / 1,0 / 0,1, walled in by blocked cells,
    # with the threat on 1,1: no cell in it is farther than 0,0 already is.
    grid = GridTopology(
        GridScene(
            width=10,
            height=10,
            blocked_cells=[
                cell_id(2, 0),
                cell_id(2, 1),
                cell_id(2, 2),
                cell_id(0, 2),
                cell_id(1, 2),
            ],
        )
    )
    assert _plan(grid, cell_id(0, 0), [cell_id(1, 1)], 30) is None


def test_flee_scores_against_the_nearest_of_several_threats() -> None:
    # Threats on 0,4 and 9,4 flank the monster on 4,4. Every cell of row 9 is
    # 25 ft from the nearer threat — farther than any other reachable cell —
    # and 25 ft away; 0,9 has the lowest (column, row) among them.
    grid = GridTopology(GridScene(width=10, height=10))
    route = _plan(grid, cell_id(4, 4), [cell_id(0, 4), cell_id(9, 4)], 30)
    assert route is not None
    assert route[-1] == cell_id(0, 9)
    assert len(route) == 6


def test_flee_never_ends_on_an_occupied_cell() -> None:
    grid = GridTopology(GridScene(width=10, height=10))
    route = _plan(grid, cell_id(3, 0), [cell_id(0, 0)], 30, occupied=[cell_id(9, 0)])
    assert route is not None
    assert route[-1] == cell_id(9, 1)


def test_flee_never_walks_through_an_enemy() -> None:
    # A one-row corridor: the threat on 0,0 and a second enemy on 5,0. Only
    # by walking through 5,0 could the monster on 2,0 get farther away.
    grid = GridTopology(GridScene(width=10, height=1))
    threats = [cell_id(0, 0), cell_id(5, 0)]
    assert _plan(grid, cell_id(2, 0), threats, 30) is None
