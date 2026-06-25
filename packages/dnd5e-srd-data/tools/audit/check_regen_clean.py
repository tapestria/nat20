"""Regen-clean gate with input-hash cache.

Re-running ``make regen`` on every ``make check`` adds ~90s of wall time to
the lib's gate. This script gates that work by hashing the inputs that
actually influence regen output (translator code, schema models, the
Foundry pinned content digest) and comparing against ``.cache/regen.stamp``.

On a cache hit, regen is skipped — the canonical/ tree is provably stable
because no input changed. On a miss, regen runs, canonical/ is diff-checked,
and the new stamp is written.

The stamp lives under ``.cache/`` which is gitignored — CI starts from a
fresh checkout (no stamp) and always pays the full regen cost. The fast
path is the developer loop, where regen is wasted work most of the time.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAMP_PATH = ROOT / ".cache" / "regen.stamp"
PINS_PATH = ROOT / "raw_sources" / "PINS.json"


def _input_paths() -> list[Path]:
    """Return the files whose content influences canonical/ output.

    Scope: any .py under tools/translators/ (foundry.py + every helper it
    imports, e.g. prose_cleanup.py — Codex round 3 flagged the prose helper
    being absent here as a stale-cache hole), tools/audit/cross_check.py
    (regen.py imports it for validation), tools/regen.py itself, and every
    .py under src/dnd5e_srd_data/schema/ (Pydantic models drive
    canonical-JSON shape). Anything else under tools/audit/ is read-only
    audit reporting that doesn't affect canonical/."""
    schema_dir = ROOT / "src" / "dnd5e_srd_data" / "schema"
    translators_dir = ROOT / "tools" / "translators"
    return [
        ROOT / "tools" / "regen.py",
        ROOT / "tools" / "audit" / "cross_check.py",
        *sorted(translators_dir.rglob("*.py")),
        *sorted(schema_dir.rglob("*.py")),
    ]


def _compute_stamp() -> str:
    """Hash translator + schema sources + pinned Foundry content digest."""
    h = hashlib.sha256()
    # The PINS.json foundry.content_digest already aggregates every byte of
    # raw_sources/foundry/{packs/_source,module}/** (see check_foundry_pin.py).
    # Reusing it here is both cheap and correct.
    if PINS_PATH.is_file():
        pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
        foundry_digest = (pins.get("foundry") or {}).get("content_digest", "")
    else:
        foundry_digest = ""
    h.update(f"foundry:{foundry_digest}\x00".encode())
    for path in _input_paths():
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        h.update(f"{rel}:{content_hash}\x00".encode())
    return h.hexdigest()


def _load_cached_stamp() -> str | None:
    if not STAMP_PATH.is_file():
        return None
    text = STAMP_PATH.read_text(encoding="utf-8").strip()
    return text or None


def _write_stamp(stamp: str) -> None:
    STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAMP_PATH.write_text(stamp + "\n", encoding="utf-8")


def _run_regen() -> int:
    env = {**os.environ, "PYTHONPATH": "."}
    proc = subprocess.run(
        ["uv", "run", "python", "tools/regen.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.stderr.write("[check-regen-clean] FAIL: regen errored\n")
    return proc.returncode


def _assert_canonical_clean() -> int:
    proc = subprocess.run(
        ["git", "diff", "--exit-code", "--", "src/dnd5e_srd_data/canonical/"],
        cwd=ROOT,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            "[check-regen-clean] FAIL: make regen drifted from committed "
            "canonical/. Translator non-determinism or pending regen commit. "
            "Run `make regen` and stage the diff.\n"
        )
    return proc.returncode


def main() -> int:
    current = _compute_stamp()
    cached = _load_cached_stamp()
    if cached == current:
        print(f"[check-regen-clean] cache HIT ({current[:16]}…) — skipping regen")
        return 0
    if cached is None:
        print("[check-regen-clean] no cache; running regen")
    else:
        print(
            f"[check-regen-clean] cache MISS (was {cached[:16]}…, "
            f"now {current[:16]}…); running regen"
        )
    rc = _run_regen()
    if rc != 0:
        return rc
    rc = _assert_canonical_clean()
    if rc != 0:
        return rc
    _write_stamp(current)
    print(f"[check-regen-clean] OK ({current[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
