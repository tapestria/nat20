from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from nat20_bridge.app import create_app
from nat20_bridge.state import DEFAULT_MAX_COMBATS, BridgeState


def _at_least_one(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


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
    parser.add_argument(
        "--max-combats",
        type=_at_least_one,
        default=DEFAULT_MAX_COMBATS,
        help="how many combats stay live; starting one more ends the least recently used",
    )
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    state = BridgeState(homebrew_path=args.data_dir / "homebrew.json", max_combats=args.max_combats)
    app = create_app(state)
    uvicorn.run(app, host=args.host, port=args.port)  # pragma: no cover
