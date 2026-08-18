"""Versioned persistence and artifact contracts must remain mechanically compatible."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from futures_agent_os.reference_market_data import DatasetLayer, DatasetManifest
from futures_agent_os.shared_kernel import SchemaVersion


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = PROJECT_ROOT / "migrations" / "versions"


def test_alembic_revisions_are_linear_and_reversible() -> None:
    revisions: dict[str, str | None] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments: dict[str, str | None] = {}
        for node in tree.body:
            target = (
                node.targets[0]
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                else node.target
                if isinstance(node, ast.AnnAssign)
                else None
            )
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                assignments[target.id] = ast.literal_eval(node.value)
        function_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert set(assignments) == {"revision", "down_revision"}, path
        assert {"upgrade", "downgrade"} <= function_names, path
        revision = assignments["revision"]
        assert isinstance(revision, str) and re.fullmatch(r"\d{4}_.+", revision), path
        assert revision not in revisions, path
        down_revision = assignments["down_revision"]
        assert down_revision is None or isinstance(down_revision, str), path
        revisions[revision] = down_revision

    assert revisions
    roots = [revision for revision, parent in revisions.items() if parent is None]
    assert len(roots) == 1
    heads = set(revisions) - {parent for parent in revisions.values() if parent is not None}
    assert len(heads) == 1
    for revision, parent in revisions.items():
        assert parent is None or parent in revisions, revision


def test_artifact_contract_keeps_a_versioned_schema_and_artifact_layer() -> None:
    annotations = DatasetManifest.__annotations__
    assert "schema_name" in annotations
    assert "schema_version" in annotations
    assert SchemaVersion(1, 0).major == 1
    assert DatasetLayer.ARTIFACT.value == "artifacts"
