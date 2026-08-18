.PHONY: check lint format format-check type test
check: lint format-check type test
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
