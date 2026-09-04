"""Read-only checks that R-003/R-004 Evidence was not rewritten."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

PREDECESSOR_HASH_SCHEMA = "mvp-r-005.predecessor-hash-manifest.v1"
PRE_V2_BYTE_STABILITY = "NOT_PROVEN"
PROTECTED_ROOTS = (
    "evidence/mvp-r-003",
    "evidence/mvp-r-004",
    "datasets/mvp-r-001/runs/mvp-r-005-discovery",
    "datasets/mvp-r-001/runs/mvp-r-005-correction-v2",
    "datasets/mvp-r-001/runs/mvp-r-005-correction-v3",
)
PROTECTED_FILES = (
    "evidence/mvp-r-005/authorization-2026-09-02.json",
    "evidence/mvp-r-005/roster.json",
    "evidence/mvp-r-005/scorecard.json",
    "evidence/mvp-r-005/wp-discovery.json",
    "evidence/mvp-r-005/reviewer-rejection-2026-09-02.json",
)
PROTECTED_TREES = (
    "evidence/mvp-r-005/correction-v2",
    "evidence/mvp-r-005/correction-v3",
    "evidence/mvp-r-005/correction-v4",
)


def predecessor_evidence_status(root: Path) -> dict[str, object]:
    r003 = json.loads((root / "evidence/mvp-r-003/discovery/scorecard.json").read_text(encoding="utf-8"))
    r004 = json.loads((root / "evidence/mvp-r-004/discovery/scorecard.json").read_text(encoding="utf-8"))
    blind = json.loads((root / "evidence/mvp-r-004/discovery/user-blind-eval.json").read_text(encoding="utf-8"))
    pivot = json.loads((root / "evidence/mvp-r-004/product-pivot-2026-09-02.json").read_text(encoding="utf-8"))
    r003_decision = r003["gate"]["decision"]
    r004_decision = r004["gate"]["decision"]
    blind_decision = blind["gate"]["decision"]
    if r003_decision != "STOP/PIVOT":
        raise RuntimeError("R-003 v1 scorecard must remain STOP/PIVOT")
    if r004_decision != "DISCOVERY_PASS":
        raise RuntimeError("R-004 discovery scorecard must remain DISCOVERY_PASS")
    if blind_decision != "USER_VALUE_FAIL":
        raise RuntimeError("R-004 user-blind eval must remain USER_VALUE_FAIL")
    if pivot.get("confirmed_pivot") != "SINGLE_RESEARCH_AGENT_PLUS_DETERMINISTIC_EXPERIMENT_LOOP":
        raise RuntimeError("R-004 product pivot direction must remain single-agent loop")
    if blind.get("independent_real_user_validation") is not False:
        raise RuntimeError("R-004 assisted blind eval must not be recorded as independent real user validation")
    return {
        "r003_v1_decision": r003_decision,
        "r004_discovery_decision": r004_decision,
        "r004_user_blind_eval": blind_decision,
        "r004_independent_real_user_validation": False,
        "r004_product_pivot": pivot["confirmed_pivot"],
        "pre_v2_byte_stability": PRE_V2_BYTE_STABILITY,
    }


def list_protected_predecessor_paths(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for relative in PROTECTED_FILES:
        path = root / relative
        if path.is_file():
            paths.append(relative)
    for relative in (*PROTECTED_ROOTS, *PROTECTED_TREES):
        directory = root / relative
        if not directory.exists():
            continue
        for file_path in sorted(directory.rglob("*")):
            if file_path.is_file():
                paths.append(file_path.relative_to(root).as_posix())
    return tuple(sorted(set(paths)))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_predecessor_hash_manifest(root: Path) -> dict[str, JsonValue]:
    files: tuple[dict[str, JsonValue], ...] = tuple(
        {"path": relative, "sha256": sha256_file(root / relative), "size": (root / relative).stat().st_size}
        for relative in list_protected_predecessor_paths(root)
    )
    hashed: dict[str, JsonValue] = {
        "schema_version": PREDECESSOR_HASH_SCHEMA,
        "files": files,
        "file_count": len(files),
    }
    payload: dict[str, JsonValue] = {
        **hashed,
        "pre_v2_byte_stability": PRE_V2_BYTE_STABILITY,
        "content_sha256": canonical_sha256(hashed),
    }
    return payload


def write_predecessor_hash_manifest(path: Path, manifest: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_text(manifest), encoding="utf-8")


def load_predecessor_hash_manifest(path: Path) -> dict[str, JsonValue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError("predecessor hash manifest must be an object")
    return payload


def file_hash_map(manifest: Mapping[str, object]) -> dict[str, str]:
    files = manifest.get("files")
    if not isinstance(files, (tuple, list)):
        raise ValueError("predecessor hash manifest files must be a sequence")
    mapping: dict[str, str] = {}
    for item in files:
        if type(item) is not dict:
            raise ValueError("predecessor hash manifest entries must be objects")
        path = item.get("path")
        digest = item.get("sha256")
        if type(path) is not str or type(digest) is not str:
            raise ValueError("predecessor hash manifest entries require path and sha256")
        mapping[path] = digest
    return mapping


def predecessor_hashes_match(baseline: Mapping[str, object], current: Mapping[str, object]) -> bool:
    return file_hash_map(baseline) == file_hash_map(current)
