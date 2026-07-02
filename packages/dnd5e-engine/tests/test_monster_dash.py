"""C02-S04 — a monster can Dash to double its movement budget within one
``advance_monster_turn``.

``_handle_dash`` was reachable only from ``submit_player_intent``'s
``intent.intent_type == "dash"`` branch; ``advance_monster_turn``'s gambit
movement loop never called it, so a monster whose target was farther than
one un-doubled move (but within a doubled Dash move) simply gave up and
recorded ``IntentSubmitted(intent_type="pass")`` with zero movement.

Focused unit tests on the two new pure decision helpers
(``_path_total_distance`` / ``_monster_dash_movement_budget``) — backend-
agnostic, per the ``SpatialTopology`` Protocol, so exercised here against
the simpler ``GridTopology`` backend. The full start_combat ->
advance_monster_turn path (zone-graph backend) is covered end to end by
``tests/e2e/test_c02_small_mechanics.py::test_c02_s04_...``.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _monster_dash_movement_budget, _path_total_distance
from dnd5e_engine.spatial import GridTopology
from dnd5e_engine.specs import GridScene


def test_path_total_distance_sums_edges_on_grid_topology():
    topology = GridTopology(GridScene(width=5, height=5, cell_size_ft=5))
    path = topology.shortest_path("0,0", "0,2")
    assert _path_total_distance(topology, path) == 10  # 2 steps * 5ft


def test_path_total_distance_zero_for_single_cell_path():
    topology = GridTopology(GridScene(width=5, height=5, cell_size_ft=5))
    assert _path_total_distance(topology, ["0,0"]) == 0


def test_path_total_distance_none_when_a_step_is_missing():
    topology = GridTopology(GridScene(width=5, height=5, cell_size_ft=5))
    # Non-adjacent hop: edge_distance returns None for it.
    assert _path_total_distance(topology, ["0,0", "4,4"]) is None


def test_monster_dash_not_needed_when_already_affordable():
    assert _monster_dash_movement_budget(20, movement_remaining=30, base_speed=30) is None


def test_monster_dash_doubles_budget_when_it_closes_the_gap():
    # Mirrors C02-S04: 35ft needed, 30ft budget, 30ft base_speed -> dash to 60.
    assert _monster_dash_movement_budget(35, movement_remaining=30, base_speed=30) == 60


def test_monster_dash_gives_up_when_even_a_dash_falls_short():
    assert _monster_dash_movement_budget(65, movement_remaining=30, base_speed=30) is None


def test_monster_dash_none_when_path_distance_unresolved():
    assert _monster_dash_movement_budget(None, movement_remaining=30, base_speed=30) is None
