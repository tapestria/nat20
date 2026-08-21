from fastapi.testclient import TestClient

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
    # Regression: an earlier `cid = f"c{len(state.combats) + 1}"` scheme
    # collided once a combat was removed from the registry — start A (c1),
    # start B (c2), end A (drops A from `combats`, leaving just B), start C
    # would then also mint "c2", silently clobbering B's still-live
    # combats/events_log/names/seeds/collectors entries with C's.
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
