.PHONY: install test check

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest -v

check:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src
	uv run pytest -q --cov=nat20_bridge --cov-report=term-missing --cov-fail-under=85
	uv run bandit -r src/ -c pyproject.toml -q
