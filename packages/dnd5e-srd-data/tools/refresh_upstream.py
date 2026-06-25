"""Fetch pinned upstream snapshots into raw_sources/.

Reads raw_sources/PINS.json, shallow-clones each upstream at the pinned
commit. Idempotent — skips sources already at the right commit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw_sources"
PINS_PATH = RAW_DIR / "PINS.json"


def _current_sha(repo_dir: Path) -> str | None:
    if not (repo_dir / ".git").is_dir():
        return None
    try:
        out = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True)
        return out.strip()
    except subprocess.CalledProcessError:
        return None


def _fetch_pin(name: str, url: str, commit: str) -> None:
    target = RAW_DIR / name
    if _current_sha(target) == commit:
        print(f"[skip] {name} already at {commit}")
        return
    if target.exists():
        shutil.rmtree(target)
    print(f"[fetch] {name} @ {commit}")
    subprocess.check_call(
        ["git", "clone", "--quiet", url, str(target)],
    )
    subprocess.check_call(
        ["git", "-C", str(target), "checkout", "--quiet", commit],
    )


def main() -> int:
    pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    for name, meta in pins.items():
        _fetch_pin(name, meta["url"], meta["commit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
