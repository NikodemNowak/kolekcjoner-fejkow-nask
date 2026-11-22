.PHONY: setup lint check app

setup:
	uv sync

lint:
	uv run ruff check --fix . && uv run ruff format .

check:
	uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q

app:
	uv run fakecollector app
