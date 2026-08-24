from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from nat20_bridge.app import create_app
from nat20_bridge.state import BridgeState


def main() -> None:
    parser = argparse.ArgumentParser(prog="nat20-bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".nat20-bridge",
        help="where homebrew.json persists",
    )
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(BridgeState(homebrew_path=args.data_dir / "homebrew.json"))
    uvicorn.run(app, host=args.host, port=args.port)  # pragma: no cover
