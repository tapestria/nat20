from pathlib import Path

from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState

PARTY = [
    {
        "name": "Brom",
        "build": {
            "species_slug": "human",
            "class_slug": "fighter",
            "level": 3,
            "ability_scores": {
                "str": 16,
                "dex": 14,
                "con": 14,
                "int": 10,
                "wis": 12,
                "cha": 8,
            },
            "equipment": ["chain-mail", "shield"],
        },
    }
]


def _start(client: TestClient, seed: int = 42) -> dict:
    resp = client.post(
        "/v1/combat", json={"party": PARTY, "monsters": ["goblin-warrior"], "seed": seed}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_combat_flow(client: TestClient) -> None:
    start = _start(client)
    cid = start["combat_id"]
    assert start["narration"]  # initiative/turn-open narration present
    assert start["events"]

    view = client.get(f"/v1/combat/{cid}").json()
    ids = [row["entity_id"] for row in view["order"]]
    assert "char:brom" in ids and any(i.startswith("mon:goblin-warrior") for i in ids)

    # Drive up to 20 turns: attack on Brom's turn, advance on the goblin's.
    for _ in range(20):
        view = client.get(f"/v1/combat/{cid}").json()
        if view["ended"]:
            break
        if view["current_actor"].startswith("char:"):
            r = client.post(
                f"/v1/combat/{cid}/intent",
                json={
                    "actor_id": "char:brom",
                    "intent_type": "attack",
                    "weapon_id": "longsword",
                    "target_id": next(i for i in ids if i.startswith("mon:")),
                },
            )
        else:
            r = client.post(f"/v1/combat/{cid}/advance-monster", json={})
        assert r.status_code == 200, r.text

    end = client.post(f"/v1/combat/{cid}/end", json={})
    assert end.status_code == 200
    assert end.json()["outcome"]["ended_reason"] in ("victory", "defeat_tpk", "forced")


def test_same_seed_same_narration(client: TestClient) -> None:
    a, b = _start(client, seed=7), _start(client, seed=7)
    assert a["narration"] == b["narration"]
    assert a["events"] == b["events"]


def test_wrong_turn_intent_is_409_unknown_combat_404(client: TestClient) -> None:
    start = _start(client, seed=1)
    cid = start["combat_id"]
    view = client.get(f"/v1/combat/{cid}").json()
    wrong = "mon:goblin-warrior-1" if view["current_actor"].startswith("char:") else "char:brom"
    r = client.post(f"/v1/combat/{cid}/intent", json={"actor_id": wrong, "intent_type": "pass"})
    assert r.status_code == 409
    assert client.get("/v1/combat/nope").status_code == 404


def test_combat_ids_never_reused_after_a_combat_ends(client: TestClient) -> None:
    # Regression: numbering a combat by how many are live collided once a
    # combat was removed — start A (c1), start B (c2), end A (drops A,
    # leaving just B), start C would then also mint "c2", silently
    # clobbering B's still-live session with C's.
    a = _start(client, seed=101)
    b = _start(client, seed=102)
    assert a["combat_id"] != b["combat_id"]

    end_a = client.post(f"/v1/combat/{a['combat_id']}/end", json={})
    assert end_a.status_code == 200

    c = _start(client, seed=103)

    ids = {a["combat_id"], b["combat_id"], c["combat_id"]}
    assert len(ids) == 3, f"expected 3 distinct combat ids, got {ids}"

    # B must still be reachable and functional — not overwritten by C.
    view_b = client.get(f"/v1/combat/{b['combat_id']}")
    assert view_b.status_code == 200
    b_ids = [row["entity_id"] for row in view_b.json()["order"]]
    assert "char:brom" in b_ids

    view_c = client.get(f"/v1/combat/{c['combat_id']}")
    assert view_c.status_code == 200


def test_view_exposes_the_grid_scene(client: TestClient) -> None:
    """The view carries the battlefield scene, not just per-combatant zones.

    A host that renders a map needs the grid's extent and terrain; without
    this block it can only guess the dimensions the bridge chose.
    """
    cid = _start(client)["combat_id"]

    grid = client.get(f"/v1/combat/{cid}").json()["grid"]

    assert (grid["width"], grid["height"]) == (12, 12)
    assert grid["cell_size_ft"] == 5
    assert grid["blocked_cells"] == []
    assert grid["difficult_terrain_cells"] == []
    assert grid["cover_cells"] == {}
    assert grid["wall_segments"] == []


def test_every_combatant_zone_is_inside_the_reported_grid(client: TestClient) -> None:
    """The zones and the grid block must describe the same battlefield."""
    cid = _start(client)["combat_id"]

    view = client.get(f"/v1/combat/{cid}").json()
    grid = view["grid"]

    for row in view["order"]:
        col, rownum = (int(part) for part in row["zone"].split(","))
        assert 0 <= col < grid["width"], row
        assert 0 <= rownum < grid["height"], row


def test_a_summon_joins_the_view_and_dodges_on_advance_monster(tmp_path: Path) -> None:
    """A Wizard 9 casts Summon Dragon: the Draconic Spirit shows in the view's
    order right after its caster (SRD 5.2: "it takes its turn immediately after
    yours"), and ``/advance-monster`` on its turn plays the uncommanded Dodge.

    The client is entered as a context manager, so every request shares one
    event loop as under a real server. Seed 42 puts the wizard first."""
    wizard = {
        "name": "Vex",
        "build": {
            "species_slug": "human",
            "class_slug": "wizard",
            "level": 9,
            "ability_scores": {"str": 8, "dex": 14, "con": 14, "int": 18, "wis": 12, "cha": 10},
        },
        "spells_known": ["summon-dragon"],
    }
    with TestClient(create_app(BridgeState(homebrew_path=tmp_path / "homebrew.json"))) as client:
        start = client.post(
            "/v1/combat", json={"party": [wizard], "monsters": ["goblin-warrior"], "seed": 42}
        )
        assert start.status_code == 200, start.text
        cid = start.json()["combat_id"]
        assert client.get(f"/v1/combat/{cid}").json()["current_actor"].startswith("char:vex")

        cast = client.post(
            f"/v1/combat/{cid}/intent",
            json={"actor_id": "char:vex", "intent_type": "cast_spell", "spell_id": "summon-dragon"},
        )
        assert cast.status_code == 200, cast.text
        [joined] = [e for e in cast.json()["events"] if e["type"] == "combatant_joined"]
        spirit = joined["entity_id"]
        assert spirit.startswith("summon:char:vex:")

        view = client.get(f"/v1/combat/{cid}").json()
        order = [(row["entity_id"], row["name"]) for row in view["order"]]
        assert order[:2] == [("char:vex", "Vex"), (spirit, "Draconic Spirit")]
        assert view["current_actor"].startswith(spirit)

        turn = client.post(f"/v1/combat/{cid}/advance-monster", json={})
        assert turn.status_code == 200, turn.text
        submitted = [e for e in turn.json()["events"] if e["type"] == "intent_submitted"]
        assert [(e["actor_id"], e["intent_type"]) for e in submitted] == [(spirit, "dodge")]
