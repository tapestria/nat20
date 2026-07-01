.PHONY: check lint format format-check type test coverage security smoke
check: lint format-check type coverage security
lint:
	uv run ruff check .
format:
	uv run ruff format .
format-check:
	uv run ruff format --check .
type:
	uv run mypy src/
test:
	uv run pytest -q
# Baseline-and-ratchet coverage gate (75% observed today; floor set 2pts under).
coverage:
	uv run pytest -q --cov=dnd5e_engine --cov-report=term-missing --cov-fail-under=73
security:
	uv run bandit -r src/ -c pyproject.toml -q
smoke:
	bash scripts/smoke_clean_install.sh
