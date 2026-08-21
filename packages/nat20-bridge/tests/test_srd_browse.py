from fastapi.testclient import TestClient


def test_browse_spells_matches_substring_on_slug(client: TestClient) -> None:
    resp = client.get("/v1/srd/spells", params={"q": "fire"})
    assert resp.status_code == 200
    assert "fireball" in resp.json()["slugs"]


def test_browse_spells_no_query_returns_all(client: TestClient) -> None:
    resp = client.get("/v1/srd/spells")
    assert resp.status_code == 200
    assert "fireball" in resp.json()["slugs"]


def test_browse_unknown_category_404(client: TestClient) -> None:
    resp = client.get("/v1/srd/not-a-category")
    assert resp.status_code == 404


def test_get_entry_fireball(client: TestClient) -> None:
    resp = client.get("/v1/srd/spells/fireball")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Fireball"


def test_get_entry_unknown_slug_404(client: TestClient) -> None:
    resp = client.get("/v1/srd/spells/no-such-spell")
    assert resp.status_code == 404


def test_get_entry_unknown_category_404(client: TestClient) -> None:
    resp = client.get("/v1/srd/not-a-category/fireball")
    assert resp.status_code == 404


def test_forge_item_then_lookup_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/v1/forge/item",
        json={"name": "Frost Brand", "base": "longsword", "bonus": 1, "extra_damage": "1d6:cold"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "hb-frost-brand"
    assert body["summary"] == "Frost Brand (hb-frost-brand): longsword base, +1, +1d6 cold"

    lookup = client.get("/v1/srd/items/hb-frost-brand")
    assert lookup.status_code == 200
    assert lookup.json()["name"] == "Frost Brand"


def test_forge_item_unknown_base_422(client: TestClient) -> None:
    resp = client.post("/v1/forge/item", json={"name": "X", "base": "no-such-base"})
    assert resp.status_code == 422


def test_homebrew_import_invalid_422(client: TestClient) -> None:
    resp = client.post("/v1/homebrew/items", json={"slug": "hb-junk", "item_kind": "weapon"})
    assert resp.status_code == 422
    assert "validation error" in resp.json()["detail"].lower()


def test_homebrew_import_list_and_delete(client: TestClient) -> None:
    base_resp = client.get("/v1/srd/items/longsword")
    assert base_resp.status_code == 200
    raw = base_resp.json()
    raw["slug"] = "hb-my-sword"
    raw["name"] = "My Sword"

    add_resp = client.post("/v1/homebrew/items", json=raw)
    assert add_resp.status_code == 200
    assert add_resp.json() == {"slug": "hb-my-sword"}

    list_resp = client.get("/v1/homebrew")
    assert list_resp.status_code == 200
    assert list_resp.json()["entries"]["hb-my-sword"] == "items"

    lookup = client.get("/v1/srd/items/hb-my-sword")
    assert lookup.status_code == 200
    assert lookup.json()["name"] == "My Sword"

    del_resp = client.delete("/v1/homebrew/hb-my-sword")
    assert del_resp.status_code == 204

    del_again = client.delete("/v1/homebrew/hb-my-sword")
    assert del_again.status_code == 404

    lookup_after = client.get("/v1/srd/items/hb-my-sword")
    assert lookup_after.status_code == 404
