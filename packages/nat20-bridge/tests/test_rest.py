from fastapi.testclient import TestClient


def test_short_rest_heals_and_clamps(client: TestClient) -> None:
    resp = client.post(
        "/v1/rest/short",
        json={
            "hit_die_size": 8,
            "dice_remaining": 3,
            "dice_total": 5,
            "dice_to_spend": 2,
            "con_modifier": 2,
            "hp_current": 10,
            "hp_max": 25,
            "seed": 42,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dice_spent"] == 2
    assert body["dice_remaining"] == 1
    assert body["hp_current"] > 10
    assert body["hp_current"] <= 25
    assert body["seed"] == 42


def test_short_rest_clamps_hp_to_max(client: TestClient) -> None:
    resp = client.post(
        "/v1/rest/short",
        json={
            "hit_die_size": 12,
            "dice_remaining": 5,
            "dice_total": 5,
            "dice_to_spend": 5,
            "con_modifier": 10,
            "hp_current": 20,
            "hp_max": 25,
            "seed": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hp_current"] == 25


def test_short_rest_deterministic_by_seed(client: TestClient) -> None:
    payload = {
        "hit_die_size": 8,
        "dice_remaining": 3,
        "dice_total": 5,
        "dice_to_spend": 2,
        "con_modifier": 2,
        "hp_current": 10,
        "hp_max": 25,
        "seed": 55,
    }
    a = client.post("/v1/rest/short", json=payload).json()
    b = client.post("/v1/rest/short", json=payload).json()
    assert a["healed"] == b["healed"]


def test_short_rest_overspend_is_422(client: TestClient) -> None:
    resp = client.post(
        "/v1/rest/short",
        json={
            "hit_die_size": 8,
            "dice_remaining": 1,
            "dice_total": 5,
            "dice_to_spend": 2,
            "con_modifier": 2,
            "hp_current": 10,
            "hp_max": 25,
        },
    )
    assert resp.status_code == 422


def test_long_rest_full_recovery(client: TestClient) -> None:
    resp = client.post(
        "/v1/rest/long",
        json={
            "hit_die_size": 8,
            "dice_remaining": 1,
            "dice_total": 5,
            "hp_current": 3,
            "hp_max": 25,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hp_current"] == 25
    assert body["dice_remaining"] == 5
    assert isinstance(body["seed"], int)
