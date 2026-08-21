from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BridgeState(homebrew_path=tmp_path / "homebrew.json")))
