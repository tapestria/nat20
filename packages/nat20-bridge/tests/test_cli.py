from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nat20_bridge import cli
from nat20_bridge.state import BridgeState


def test_main_builds_app_and_creates_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "nat20-bridge-data"
    captured: dict[str, Any] = {}

    def fake_run(app: Any, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["nat20-bridge", "--host", "0.0.0.0", "--port", "9999", "--data-dir", str(data_dir)],
    )

    cli.main()

    assert data_dir.is_dir()
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9999
    assert captured["app"] is not None


def test_main_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, host, port: captured.update(host=host, port=port)
    )
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("sys.argv", ["nat20-bridge"])

    cli.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8020
    assert (tmp_path / ".nat20-bridge").is_dir()


def test_max_combats_reaches_the_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    states: list[BridgeState] = []

    def fake_create_app(state: BridgeState) -> object:
        states.append(state)
        return object()

    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port: None)
    monkeypatch.setattr(
        "sys.argv", ["nat20-bridge", "--data-dir", str(tmp_path), "--max-combats", "3"]
    )
    cli.main()
    assert [s.max_combats for s in states] == [3]


def test_max_combats_below_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["nat20-bridge", "--data-dir", str(tmp_path), "--max-combats", "0"]
    )
    with pytest.raises(SystemExit):
        cli.main()
    assert "must be at least 1" in capsys.readouterr().err
