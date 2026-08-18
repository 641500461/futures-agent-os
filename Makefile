.PHONY: install health lock format lint type scan schema test test-unit test-property test-contract test-integration check

install:
	uv sync --locked

health:
	uv run futures-agent-os health

test:
	uv run pytest

lock:
	uv lock --check

format:
	uv run ruff format --check .

lint:
	uv run ruff check .

type:
	uv run mypy

scan:
	uv run python scripts/verify_secret_scan.py

schema:
	uv run pytest tests/contract/test_schema_compatibility.py

test-unit:
	uv run pytest tests/unit

test-property:
	uv run pytest tests/property

test-contract:
	uv run pytest tests/contract

test-integration:
	uv run pytest tests/integration

check: lock format lint type scan schema test-unit test-property test-contract health
