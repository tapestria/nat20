"""Wheel-packaging gate.

Builds the wheel via ``python -m build`` and asserts that canonical/ JSON
ships *inside* the package tree (``dnd5e_srd_data/canonical/...``). The
previous shared-data declaration installed canonical/ at site-packages root,
which broke importlib.resources lookups — codex iter-4 P1.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_includes_canonical_inside_package_tree(tmp_path: Path) -> None:
    """Building the wheel via uv produces a .whl with canonical JSONs at
    ``dnd5e_srd_data/canonical/items/*.json`` — INSIDE the package — so
    importlib.resources can read them post-install."""
    # Use uv build into a scratch dist dir so the test is hermetic.
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"uv build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    # Must ship canonical INSIDE the package (importlib.resources lookup root).
    assert any(
        n.startswith("dnd5e_srd_data/canonical/items/") and n.endswith(".json") for n in names
    ), "canonical/items JSON missing from wheel under dnd5e_srd_data/canonical/items/"
    assert any(
        n.startswith("dnd5e_srd_data/canonical/monsters/") and n.endswith(".json") for n in names
    ), "canonical/monsters JSON missing from wheel under dnd5e_srd_data/canonical/monsters/"
    # And explicitly NOT at site-packages root (the old broken shared-data
    # layout would put `canonical/items/longsword.json` at the top level).
    assert not any(n.startswith("canonical/") for n in names), (
        "wheel contains top-level canonical/ entries — shared-data regression"
    )
