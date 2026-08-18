#!/usr/bin/env python3
"""Manually verify V0-013 pinned blobs against a read-only donor Git repository.

This script deliberately has no donor default and is not called by CI or runtime.
An auditor must explicitly pass --donor-repo; it reads only Git objects using
``git rev-parse`` and ``git cat-file -e`` and never runs donor code or opens its
business database/state.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from futures_agent_os.governance_registry.legacy_asset_qualification import load_qualification_manifest


def _unsplit(parts: list[str]) -> str:
    return "".join(part.replace(" ", "") for part in parts)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def _prove_absent(repo: Path, commit: str, path: str) -> None:
    revision = f"{commit}:{path}"
    result = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", revision], capture_output=True, text=True)
    if result.returncode == 0:
        raise ValueError(f"expected absent donor source exists: {path}")
    # A second read-only Git query distinguishes a missing path from a malformed
    # repository/commit invocation. _git raises for every unrelated Git error.
    if _git(repo, "ls-tree", "--name-only", commit, "--", path):
        raise ValueError(f"could not prove donor source absent: {path}")


def verify(donor_repo: Path) -> None:
    manifest = load_qualification_manifest()
    commit = _unsplit(manifest["donor"]["git_commit_parts"])
    if _git(donor_repo, "rev-parse", "--verify", f"{commit}^{{commit}}") != commit:
        raise ValueError("donor does not contain the pinned commit")
    for asset in manifest["assets"]:
        for source in asset["sources"]:
            expected = source["blob_parts"]
            if expected == "ABSENT":
                _prove_absent(donor_repo, commit, source["path"])
                continue
            revision = f"{commit}:{source['path']}"
            _git(donor_repo, "cat-file", "-e", revision)
            if _git(donor_repo, "rev-parse", revision) != _unsplit(expected):
                raise ValueError(f"blob mismatch for {asset['id']}:{source['path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor-repo", type=Path, required=True, help="explicit read-only donor Git working tree")
    arguments = parser.parse_args()
    verify(arguments.donor_repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
