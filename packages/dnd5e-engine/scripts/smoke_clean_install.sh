#!/usr/bin/env bash
# Clean-room install smoke for dnd5e-engine.
# Builds both wheels, installs them into a fresh venv with NO editable path deps,
# and runs a real grid combat through the public API. Exits non-zero on failure.
set -euo pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$(cd "$ENGINE_DIR/../dnd5e-srd-data" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> building wheels"
( cd "$DATA_DIR" && uv build --wheel -o "$WORK/dist" )
( cd "$ENGINE_DIR" && uv build --wheel -o "$WORK/dist" )

echo "==> fresh venv at $WORK/venv"
python -m venv "$WORK/venv"
# shellcheck disable=SC1091
source "$WORK/venv/bin/activate"
python -m pip install --quiet --upgrade pip

echo "==> installing built wheels (no path deps)"
# --find-links lets pip resolve the engine wheel's dnd5e-srd-data dependency from
# the locally-built data wheel (the package is unpublished); third-party deps
# (pydantic, d20) come from PyPI, which requires network.
python -m pip install --quiet --find-links "$WORK/dist" \
  "$WORK"/dist/dnd5e_srd_data-*.whl "$WORK"/dist/dnd5e_engine-*.whl

echo "==> running clean-room grid-combat smoke"
python "$ENGINE_DIR/scripts/_smoke_grid_combat.py"

echo "==> SMOKE PASSED"
