.PHONY: check lint type test smoke
check: lint type test
lint:
	uv run ruff check .
type:
	uv run mypy src/
test:
	uv run pytest -q
smoke:
	bash scripts/smoke_clean_install.sh
