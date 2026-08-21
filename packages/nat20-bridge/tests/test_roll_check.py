from fastapi.testclient import TestClient


def test_roll_deterministic_by_seed(client: TestClient) -> None:
    a = client.post("/v1/roll", json={"dice": "2d6+3", "seed": 42}).json()
    b = client.post("/v1/roll", json={"dice": "2d6+3", "seed": 42}).json()
    assert a["total"] == b["total"]
    assert 5 <= a["total"] <= 15
    assert a["dice"] == "2d6+3"
    assert a["seed"] == 42


def test_roll_without_seed_generates_one(client: TestClient) -> None:
    resp = client.post("/v1/roll", json={"dice": "1d4"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["seed"], int)
    assert 1 <= body["total"] <= 4


def test_roll_invalid_dice_expression_is_422(client: TestClient) -> None:
    resp = client.post("/v1/roll", json={"dice": "not-a-dice-expr"})
    assert resp.status_code == 422
    assert "not-a-dice-expr" in resp.json()["detail"]


def test_check_route(client: TestClient) -> None:
    resp = client.post(
        "/v1/check",
        json={
            "kind": "skill",
            "ability": "dex",
            "skill": "stealth",
            "dc": 10,
            "ability_scores": {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "proficient_skills": ["stealth"],
            "proficient_saves": [],
            "proficiency_bonus": 2,
            "seed": 7,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] in (True, False)
    assert "summary" in body
    assert body["seed"] == 7
    assert body["ability"] == "dexterity"
    assert body["skill"] == "stealth"
    assert body["is_proficient"] is True


def test_check_route_deterministic_by_seed(client: TestClient) -> None:
    payload = {
        "kind": "skill",
        "ability": "dex",
        "skill": "stealth",
        "dc": 10,
        "ability_scores": {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "proficient_skills": ["stealth"],
        "proficient_saves": [],
        "proficiency_bonus": 2,
        "seed": 99,
    }
    a = client.post("/v1/check", json=payload).json()
    b = client.post("/v1/check", json=payload).json()
    assert a["roll_total"] == b["roll_total"]
    assert a["natural_roll"] == b["natural_roll"]


def test_check_route_saving_throw(client: TestClient) -> None:
    resp = client.post(
        "/v1/check",
        json={
            "kind": "saving_throw",
            "ability": "con",
            "dc": 12,
            "ability_scores": {"str": 10, "dex": 10, "con": 14, "int": 10, "wis": 10, "cha": 10},
            "proficient_skills": [],
            "proficient_saves": ["con"],
            "proficiency_bonus": 2,
            "seed": 3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ability"] == "constitution"
    assert body["is_proficient"] is True


def test_check_route_ability_check_no_dc(client: TestClient) -> None:
    resp = client.post(
        "/v1/check",
        json={
            "kind": "ability",
            "ability": "str",
            "ability_scores": {"str": 12, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "proficient_skills": [],
            "proficient_saves": [],
            "proficiency_bonus": 2,
            "seed": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dc"] is None
    assert body["success"] is None
