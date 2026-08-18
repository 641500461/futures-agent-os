import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
FORBIDDEN_TOP_LEVEL_IMPORTS = {"futures_workflow"}


def test_source_has_no_legacy_runtime_imports() -> None:
    violations: list[str] = []

    for source_file in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            for name in names:
                if name in FORBIDDEN_TOP_LEVEL_IMPORTS:
                    violations.append(f"{source_file.relative_to(PROJECT_ROOT)} imports {name}")

    assert violations == []

