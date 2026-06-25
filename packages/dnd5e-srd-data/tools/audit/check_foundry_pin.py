"""Enforce that ``raw_sources/foundry/`` has not drifted from the SHA pinned
in ``raw_sources/PINS.json``.

Bumping the Foundry SHA requires regen + reviewed diff + updated digest. This
script computes a content digest over the files the translator + audit tooling
actually depend on (pack YAML inputs + data-class .mjs references) and asserts
it matches the digest committed to ``PINS.json.foundry.content_digest``.

Wired into ``make check`` so any tampering / accidental local edit fails loud.

Digest scope (intentionally narrow — full repo is 482MB / 6,388 files, and
gating on every PNG icon adds CI runtime for no marginal review value):

- ``raw_sources/foundry/packs/_source/**`` — every file. These are the
  translator's inputs; any edit must trigger explicit review.
- ``raw_sources/foundry/module/**/*.mjs`` — only the JS/MJS source. The
  per-kind activity data classes are this gate's primary review surface.

Algorithm: sort all matched paths (relative to the foundry root), then
``sha256`` over the concatenation of each path bytes + a NUL byte + the
file's content SHA256 hex digest + a NUL byte. The composite hex digest is
written to ``PINS.json.foundry.content_digest``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS_PATH = ROOT / "raw_sources" / "PINS.json"
FOUNDRY_ROOT = ROOT / "raw_sources" / "foundry"


def _iter_gated_paths() -> list[Path]:
    """Return the sorted list of files in the digest scope."""
    paths: list[Path] = []
    pack_root = FOUNDRY_ROOT / "packs" / "_source"
    if pack_root.is_dir():
        paths.extend(p for p in pack_root.rglob("*") if p.is_file())
    module_root = FOUNDRY_ROOT / "module"
    if module_root.is_dir():
        paths.extend(p for p in module_root.rglob("*.mjs") if p.is_file())
    return sorted(paths)


def compute_digest() -> str:
    composite = hashlib.sha256()
    for path in _iter_gated_paths():
        rel = path.relative_to(FOUNDRY_ROOT).as_posix().encode("utf-8")
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        composite.update(rel)
        composite.update(b"\x00")
        composite.update(content_digest)
        composite.update(b"\x00")
    return composite.hexdigest()


def _load_pinned_digest() -> str | None:
    if not PINS_PATH.is_file():
        return None
    pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    foundry = pins.get("foundry") or {}
    value = foundry.get("content_digest")
    return str(value) if value else None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Compute the digest and write it to PINS.json (use after an intentional SHA bump).",
    )
    args = parser.parse_args()

    digest = compute_digest()
    if args.write:
        pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
        pins.setdefault("foundry", {})["content_digest"] = digest
        PINS_PATH.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[check_foundry_pin] wrote content_digest={digest}")
        return 0

    pinned = _load_pinned_digest()
    if pinned is None:
        print(
            "[check_foundry_pin] FAIL: PINS.json has no foundry.content_digest. "
            "Run `python tools/audit/check_foundry_pin.py --write` after "
            "confirming raw_sources/foundry/ is at the intended SHA.",
            file=sys.stderr,
        )
        return 1
    if digest != pinned:
        print(
            "[check_foundry_pin] FAIL: raw_sources/foundry/ has drifted from "
            "the pinned content.\n"
            f"  pinned:   {pinned}\n"
            f"  computed: {digest}\n"
            "If this drift is intentional (Foundry SHA bump), update the "
            "commit field in PINS.json and re-run with --write. Otherwise, "
            "restore the foundry sources from the pinned commit.",
            file=sys.stderr,
        )
        return 1
    print(f"[check_foundry_pin] OK ({digest[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
