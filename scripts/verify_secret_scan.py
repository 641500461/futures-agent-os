#!/usr/bin/env python3
"""Fail closed when detect-secrets finds a credential-like value in source control."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PATHS = r"(^|/)(\.git|\.venv|\.pytest_cache|\.mypy_cache|\.ruff_cache|__pycache__)(/|$)"


def main() -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "detect_secrets", "scan", "--all-files", "--exclude-files", EXCLUDED_PATHS],
        check=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    findings = json.loads(completed.stdout).get("results", {})
    if findings:
        print("Secret scan failed; remove the value or replace it with a non-secret reference.", file=sys.stderr)
        for path in sorted(findings):
            print(path, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
