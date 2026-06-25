.PHONY: install test check check-provenance check-regen-clean refresh-upstream regen

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest -v

# Public-repo gate: hermetic only (no raw_sources/foundry required).
# The canonical/ corpus is the shipped product; regenerating it from upstream
# is a maintainer flow (see check-provenance / refresh-upstream / regen).
check:
	uv run ruff check src tests tools
	uv run ruff format --check src tests tools
	uv run mypy src
	uv run pytest

# Maintainer-only: verifies canonical/ still matches pinned upstream sources.
# Requires `make refresh-upstream` first to populate raw_sources/foundry.
check-provenance:
	uv run python tools/audit/check_foundry_pin.py
	$(MAKE) check-regen-clean

# Regen-clean gate (PR A task A7): translator output MUST be deterministic.
# Re-runs regen + asserts canonical/ is clean, but skips when the inputs
# that influence regen output haven't changed (cached by stamp under
# .cache/regen.stamp). CI starts from a fresh checkout with no stamp and
# always pays the full cost; the developer loop gets sub-second checks on
# unrelated changes. See tools/audit/check_regen_clean.py.
check-regen-clean:
	@PYTHONPATH=. uv run python tools/audit/check_regen_clean.py

refresh-upstream:
	uv run python tools/refresh_upstream.py

# regen.py imports `tools.audit.*` which requires the project root on sys.path.
# pyproject's `pythonpath = [".", "src"]` only applies to pytest, so set it
# explicitly here.
regen:
	PYTHONPATH=. uv run python tools/regen.py
