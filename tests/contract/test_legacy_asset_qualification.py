import json
import importlib.util
import subprocess
from pathlib import Path

import pytest

from futures_agent_os.governance_registry.legacy_asset_qualification import (
    load_qualification_manifest,
    validate_qualification_manifest,
)


def _forge_blob(manifest) -> None:
    manifest["assets"][0]["sources"][0]["blob_parts"][0] = "0 0 0 0 0 0 0 0 0 0"


def _provenance_script_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_v0_013_donor_provenance.py"
    spec = importlib.util.spec_from_file_location("v0_013_provenance_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _temporary_git_repo(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    (tmp_path / "present.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "present.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return tmp_path, commit


def test_v0_013_manifest_is_complete_and_does_not_access_the_donor() -> None:
    manifest = load_qualification_manifest()
    validate_qualification_manifest(manifest)
    assert len(manifest["assets"]) == 34
    assert manifest["summary"].get("qualified", 0) == 0
    assert all(asset["qualification_status"] != "QUALIFIED" for asset in manifest["assets"])
    assert all(
        "/Users/qiu/futures_workflow" not in source["path"]
        for asset in manifest["assets"]
        for source in asset["sources"]
    )


def test_v0_013_manifest_rejects_missing_gate_or_unsupported_qualification(tmp_path) -> None:
    manifest = load_qualification_manifest()
    manifest["assets"][0]["gates"].pop("security_scan")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="mandatory gate"):
        validate_qualification_manifest(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda manifest: manifest["assets"][0].update(id="forged_asset"), "baseline"),
        (lambda manifest: manifest["assets"][0].update(reuse_level="R4_REJECT"), "baseline"),
        (lambda manifest: manifest["assets"][0]["sources"][0].update(path="forged.py"), "baseline"),
        (_forge_blob, "digest"),
        (lambda manifest: manifest["assets"][25]["gates"]["security_scan"].update(status="PASS"), "digest"),
    ),
)
def test_v0_013_manifest_rejects_forged_baseline_fields(mutation, error: str) -> None:
    manifest = load_qualification_manifest()
    mutation(manifest)
    with pytest.raises(ValueError, match=error):
        validate_qualification_manifest(manifest)


def test_v0_013_unverified_license_prohibits_qualification() -> None:
    manifest = load_qualification_manifest()
    asset = manifest["assets"][0]
    asset["qualification_status"] = "QUALIFIED"
    for gate in asset["gates"].values():
        gate["status"] = "PASS"
    manifest["summary"] = {"candidate": 19, "deferred": 3, "evidence_only": 9, "rejected": 2, "qualified": 1}
    with pytest.raises(ValueError, match="unverified donor license"):
        validate_qualification_manifest(manifest)


def test_manual_provenance_verifier_proves_absent_sources_without_the_donor(tmp_path, monkeypatch) -> None:
    repo, commit = _temporary_git_repo(tmp_path)
    module = _provenance_script_module()
    manifest = {
        "donor": {"git_commit_parts": list(commit)},
        "assets": [{"id": "missing", "sources": [{"path": "missing.py", "blob_parts": "ABSENT"}]}],
    }
    monkeypatch.setattr(module, "load_qualification_manifest", lambda: manifest)
    module.verify(repo)

    manifest["assets"][0]["sources"][0]["path"] = "present.py"
    with pytest.raises(ValueError, match="expected absent donor source exists"):
        module.verify(repo)
