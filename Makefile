# Aggregate developer entrypoint for the nat20 workspace.
# CI runs each package's `make check` in its own job (.github/workflows/ci.yml);
# this target mirrors the full gate locally. Run `uv sync --all-packages --extra dev`
# once first so both packages' dev tools (ruff/mypy/pytest-cov/bandit) are present.
.PHONY: check check-engine check-srd-data examples smoke format

check: check-srd-data check-engine examples

check-srd-data:
	$(MAKE) -C packages/dnd5e-srd-data check

check-engine:
	$(MAKE) -C packages/dnd5e-engine check

# Runnable examples double as an integration smoke over the public API.
examples:
	uv run python examples/grid_combat.py
	uv run python examples/skill_check.py
	uv run python examples/build_party_member.py

# Clean-venv install smoke: builds both wheels, installs with no path deps,
# runs grid combat through the published surface. Slow; CI runs it standalone.
smoke:
	$(MAKE) -C packages/dnd5e-engine smoke

# Auto-apply formatting across both packages.
format:
	$(MAKE) -C packages/dnd5e-engine format
	cd packages/dnd5e-srd-data && uv run ruff format src tests tools
