#!/usr/bin/env python3
"""Fail closed when detect-secrets finds a credential-like value in source control."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_BASELINE = PROJECT_ROOT / ".secrets.baseline"
# MVP-R keeps governed datasets, local trust roots, and content-addressed run
# artifacts under an ignored local-only directory. They must never enter source
# control and their expected hashes/signatures are not source-code findings.
EXCLUDED_PATHS = (
    r"(^|/)(\.git|\.venv|\.pytest_cache|\.mypy_cache|\.ruff_cache|__pycache__)(/|$)"
    r"|^\.secrets\.baseline$"
    r"|^datasets/mvp-r-001/"
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fao-secret-scan-") as temporary_directory:
        scan_baseline = Path(temporary_directory) / "baseline.json"
        shutil.copyfile(SECRET_BASELINE, scan_baseline)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "detect_secrets",
                "scan",
                "--all-files",
                "--baseline",
                str(scan_baseline),
                "--force-use-all-plugins",
                "--exclude-files",
                EXCLUDED_PATHS,
            ],
            check=True,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        findings = json.loads(scan_baseline.read_text(encoding="utf-8")).get("results", {})
    unaudited_findings = {
        path: [finding for finding in path_findings if finding.get("is_secret") is not False]
        for path, path_findings in findings.items()
    }
    unaudited_findings = {path: path_findings for path, path_findings in unaudited_findings.items() if path_findings}
    if unaudited_findings:
        print("Secret scan failed; remove the value or replace it with a non-secret reference.", file=sys.stderr)
        for path in sorted(unaudited_findings):
            print(path, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
