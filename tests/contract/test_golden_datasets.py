import hashlib
import json
import shutil
from pathlib import Path

import pytest

from futures_agent_os.reference_market_data.golden_datasets import (
    REQUIRED_CASES,
    UNIVERSE,
    golden_events,
    repository_dataset_root,
    validate_golden_dataset,
    write_golden_dataset,
)


def test_committed_v0_012_golden_dataset_is_reproducible_and_valid() -> None:
    validate_golden_dataset(repository_dataset_root())


def test_generator_reproduces_all_committed_golden_assets(tmp_path) -> None:
    write_golden_dataset(tmp_path)
    validate_golden_dataset(tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_bytes())["cases"]
    assert {case["variety"] for case in cases} == set(UNIVERSE)
    assert REQUIRED_CASES <= {case["case_id"] for case in cases}


def test_fixed_release_oracle_locks_version_identity_revision_and_bundle_digests() -> None:
    root = repository_dataset_root()
    oracle = json.loads((Path(__file__).parent / "fixtures" / "v0_012_release_oracle.json").read_bytes())
    event_manifest = json.loads((root / "golden_market_events.manifest.json").read_bytes())
    bundle = json.loads((root / "golden_bundle.manifest.json").read_bytes())

    assert event_manifest["dataset_id"] == oracle["dataset"]["id"]
    assert event_manifest["provenance"]["source_revision"] == oracle["dataset"]["version"]
    assert event_manifest["revision"]["revision"] == oracle["dataset"]["revision"]
    assert event_manifest["revision"]["supersedes_dataset_id"] is oracle["dataset"]["supersedes_dataset_id"]
    assert bundle["bundle_id"] == oracle["bundle"]["id"]
    assert bundle["bundle_version"] == oracle["bundle"]["version"]
    assert bundle["revision"]["revision"] == oracle["bundle"]["revision"]
    assert bundle["revision"]["supersedes_bundle_id"] is oracle["bundle"]["supersedes_bundle_id"]
    digests = {name: "".join(parts) for name, parts in oracle["digest_parts"].items()}
    for name, expected_digest in digests.items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        assert actual == expected_digest
    assert bundle["members"]["events"]["content_hash"] == f"sha256:{digests['golden_market_events.jsonl']}"
    assert bundle["members"]["events_manifest"]["content_hash"] == (
        f"sha256:{digests['golden_market_events.manifest.json']}"
    )
    assert bundle["members"]["catalog"]["content_hash"] == f"sha256:{digests['cases.json']}"


def test_catalog_has_one_non_empty_fixture_scoped_reason_and_disposition_per_variety() -> None:
    cases = json.loads((repository_dataset_root() / "cases.json").read_bytes())["cases"]

    assert len(cases) == len(UNIVERSE)
    assert {case["variety"] for case in cases} == set(UNIVERSE)
    assert len({case["case_id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["product_reason"].strip()
        assert "synthetic" in case["product_reason"].lower()
        assert case["expected_disposition"].strip()


def test_out_of_order_case_is_arrival_ordered_but_event_time_disordered() -> None:
    assert [event["available_time"] for event in golden_events()] == sorted(
        event["available_time"] for event in golden_events()
    )
    records = [event for event in golden_events() if event["case_id"] == "out_of_order"]
    assert [record["available_time"] for record in records] == sorted(record["available_time"] for record in records)
    assert [record["event_time"] for record in records] != sorted(record["event_time"] for record in records)
    assert [record["sequence"] for record in records] == sorted(
        (record["sequence"] for record in records), reverse=True
    )


@pytest.mark.parametrize(
    "asset",
    ("golden_market_events.jsonl", "golden_market_events.manifest.json", "cases.json", "golden_bundle.manifest.json"),
)
def test_committed_golden_assets_fail_closed_when_tampered(tmp_path, asset: str) -> None:
    copied = tmp_path / "v0-012"
    shutil.copytree(repository_dataset_root(), copied)
    target = copied / asset
    target.write_bytes(target.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="not reproducible"):
        validate_golden_dataset(copied)


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    (
        ("quality", "summary", "tampered quality"),
        ("license", "allowed_use", "tampered license"),
        (None, "schema_name", "tampered.schema"),
        ("provenance", "source_uri", "synthetic://tampered"),
    ),
)
def test_manifest_only_semantic_drift_fails_closed(tmp_path, section: str | None, field: str, replacement: str) -> None:
    copied = tmp_path / "v0-012"
    shutil.copytree(repository_dataset_root(), copied)
    target = copied / "golden_market_events.manifest.json"
    manifest = json.loads(target.read_bytes())
    (manifest[section] if section else manifest)[field] = replacement
    target.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    with pytest.raises(ValueError, match="not reproducible"):
        validate_golden_dataset(copied)
