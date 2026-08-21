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
