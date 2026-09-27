from importlib.metadata import version

from fastapi.testclient import TestClient


def test_health_reports_versions(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"bridge", "engine", "data"}
    assert body == {
        "bridge": version("nat20-bridge"),
        "engine": version("dnd5e-engine"),
        "data": version("dnd5e-srd-data"),
    }
