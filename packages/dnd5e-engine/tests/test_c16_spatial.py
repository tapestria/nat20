"""C16 — pure GridTopology geometry units (obstruction model, legal steps,
cube/cylinder templates, push path, can_see). Every rule quotes the SRD 5.2
card in specs/rule-cards/c16-spatial-vision.md."""

from __future__ import annotations

from dnd5e_engine.spatial import GridTopology
from dnd5e_engine.specs import GridScene


def _grid(**kw) -> GridTopology:
    kw.setdefault("width", 10)
    kw.setdefault("height", 10)
    return GridTopology(GridScene(**kw))


# ── Task 1: obstruction model ────────────────────────────────────────────


def test_cover_between_blocked_cell_is_total_cover():
    g = _grid(blocked_cells=["2,0"])
    assert g.cover_between("0,0", "4,0") == "total"


def test_cover_between_occupied_cell_grants_half_cover():
    g = _grid()
    assert g.cover_between("0,0", "2,0") == "none"
    assert g.cover_between("0,0", "2,0", occupied_cells={"1,0"}) == "half"


def test_cover_between_occupied_endpoints_never_count():
    g = _grid()
    # attacker's and target's own cells are always "occupied" — never cover.
    assert g.cover_between("0,0", "2,0", occupied_cells={"0,0", "2,0"}) == "none"


def test_cover_between_target_own_cover_cell_counts_but_origin_does_not():
    # SRD 5.2 §Cover, Half: "an object that covers at least half of the
    # target" — an obstacle IN the target's own space shields it; one in the
    # attacker's space does not. Shared ruling with C22 Task 6 (C22-S03 tags
    # the target's own cell). Re-pins
    # tests/test_grid_topology.py::test_cover_between_ignores_cover_on_the_endpoints_themselves
    # to this rule (rename it ``..._ignores_cover_on_the_origin_cell``).
    g = _grid(cover_cells={"2,0": "half", "0,0": "three_quarters"})
    assert g.cover_between("0,0", "2,0") == "half"
    assert g.cover_between("2,0", "0,0") == "three_quarters"


def test_cover_between_highest_degree_wins_over_creature_half():
    g = _grid(cover_cells={"1,0": "three_quarters"})
    assert g.cover_between("0,0", "3,0", occupied_cells={"2,0"}) == "three_quarters"


def test_cover_between_accepts_any_collection_and_default_is_unchanged():
    g = _grid(cover_cells={"1,0": "half"})
    assert g.cover_between("0,0", "2,0") == "half"
    assert g.cover_between("0,0", "2,0", ["1,0"]) == "half"
    assert g.cover_between("0,0", "2,0", ()) == "half"
