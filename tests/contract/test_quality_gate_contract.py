"""The documented local gates and CI stages must remain the same commands."""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_quality_tools_and_locked_environment_are_declared() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    for dependency in ("ruff", "mypy", "hypothesis", "detect-secrets"):
        assert f'"{dependency}>=' in pyproject
        assert f'name = "{dependency}"' in lock
    assert 'requires-python = ">=3.14,<3.15"' in pyproject


def test_ci_uses_the_same_make_targets_as_local_quality_commands() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (PROJECT_ROOT / ".github/workflows/postgresql.yml").read_text(encoding="utf-8")
    targets = (
        "lock",
        "format",
        "lint",
        "type",
        "scan",
        "schema",
        "health",
        "test-unit",
        "test-property",
        "test-contract",
        "test-integration",
    )
    for target in targets:
        assert f"{target}:" in makefile
        assert f"make {target}" in workflow
    assert workflow.count("uv sync --locked") == 5


def test_ci_third_party_actions_are_pinned_to_commit_shas() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/postgresql.yml").read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in action_refs)
