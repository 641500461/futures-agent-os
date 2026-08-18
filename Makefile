.PHONY: install health test check

install:
	uv sync --locked

health:
	uv run futures-agent-os health

test:
	uv run pytest

check: test health

