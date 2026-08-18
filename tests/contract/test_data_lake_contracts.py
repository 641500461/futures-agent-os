from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.reference_market_data import (
    DataQualityLevel, DatasetLayer, DatasetManifest, LicenseTerms, LocalFileArtifactStore,
    LocalFileDataStore, PointInTimeRecord, QualityReport, RevisionInfo, SourceProvenance,
    StoredDataset, TimeCoverage, sha256_digest,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(minutes: int) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 18, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _manifest(layer: DatasetLayer = DatasetLayer.RAW, *, content: bytes = b"raw-response") -> DatasetManifest:
    return DatasetManifest(
        dataset_id=EntityId.new("dataset"), layer=layer, object_uri="local://example/object",
        content_hash=sha256_digest(content), schema_name="market.observation", schema_version=SchemaVersion(1, 0),
        coverage=TimeCoverage(_at(1), _at(2)), instrument_universe=("SHFE.AG2609",),
        provenance=SourceProvenance("synthetic-exchange", "synthetic://exchange/ag", _at(3), _at(2), "source-r1"),
        license=LicenseTerms("test-license", "research", "30d", "no redistribution", "development only"),
        as_of=_at(4), ingested_at=_at(5), quality=QualityReport(DataQualityLevel.Q2_RESEARCH, "complete", _at(5)),
        revision=RevisionInfo(1, "initial ingest", _at(5)),
        generated_by="unit-test" if layer in {DatasetLayer.FEATURE_SNAPSHOT, DatasetLayer.DATASET, DatasetLayer.ARTIFACT} else None,
        upstream_manifest_ids=(EntityId.new("dataset"),) if layer in {DatasetLayer.FEATURE_SNAPSHOT, DatasetLayer.DATASET} else (),
    )


def test_manifest_requires_complete_provenance_license_quality_and_revision() -> None:
    manifest = _manifest()
    assert manifest.provenance.source_revision == "source-r1"
    assert manifest.quality.level is DataQualityLevel.Q2_RESEARCH
    with pytest.raises(ValueError, match="license"):
        replace(manifest, license=LicenseTerms("test", "", "30d", "no", "dev"))
    with pytest.raises(ValueError, match="supersedes"):
        replace(manifest, revision=RevisionInfo(2, "correction", _at(6)))
    with pytest.raises(ValueError, match="derived"):
        replace(_manifest(DatasetLayer.FEATURE_SNAPSHOT), upstream_manifest_ids=())


def test_local_store_is_content_addressed_immutable_and_verifies_hash(tmp_path) -> None:
    content = b"raw-response"
    manifest = _manifest(content=content)
    store = LocalFileDataStore(tmp_path, DatasetLayer.RAW)
    stored = StoredDataset(manifest, content)
    assert store.put(stored) == manifest
    assert store.get(manifest.dataset_id) == stored
    with pytest.raises(ValueError, match="content_hash"):
        store.put(StoredDataset(manifest, b"changed"))
    object_path = tmp_path / "objects" / manifest.content_hash.removeprefix("sha256:")
    object_path.chmod(0o644)  # Simulate tampering outside the immutable-store boundary.
    object_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash verification"):
        store.get(manifest.dataset_id)


def test_same_content_can_have_distinct_immutable_manifests_and_revisions(tmp_path) -> None:
    content = b"same-source-response"
    original = _manifest(content=content)
    corrected = replace(
        _manifest(content=content),
        revision=RevisionInfo(2, "quality correction", _at(6), original.dataset_id),
        quality=QualityReport(DataQualityLevel.Q3_DECISION, "validated correction", _at(6)),
    )
    store = LocalFileDataStore(tmp_path, DatasetLayer.RAW)

    store.put(StoredDataset(original, content))
    store.put(StoredDataset(corrected, content))

    assert store.get(original.dataset_id).manifest == original
    assert store.get(corrected.dataset_id).manifest == corrected
    assert len(list((tmp_path / "objects").iterdir())) == 1
    assert corrected.revision.supersedes_dataset_id == original.dataset_id


def test_manifest_identity_conflict_cannot_overwrite_an_existing_dataset_id(tmp_path) -> None:
    content = b"raw-response"
    original = _manifest(content=content)
    conflicting = replace(original, quality=QualityReport(DataQualityLevel.Q1_DEGRADED, "late gap", _at(6)))
    store = LocalFileDataStore(tmp_path, DatasetLayer.RAW)

    store.put(StoredDataset(original, content))
    with pytest.raises(ValueError, match="dataset_id"):
        store.put(StoredDataset(conflicting, content))
    assert store.get(original.dataset_id).manifest == original


def test_pit_records_cannot_leak_future_availability_or_coverage() -> None:
    manifest = _manifest(DatasetLayer.NORMALIZED_PIT)
    valid = PointInTimeRecord(_at(2), _at(3), {"close": "100"})
    manifest.validate_point_in_time((valid,))
    with pytest.raises(TypeError):
        valid.values["close"] = "101"
    with pytest.raises(ValueError, match="not available"):
        manifest.validate_point_in_time((PointInTimeRecord(_at(2), _at(6), {"close": "100"}),))
    with pytest.raises(ValueError, match="coverage"):
        manifest.validate_point_in_time((PointInTimeRecord(_at(0), _at(1), {"close": "100"}),))


def test_artifacts_use_the_same_immutable_manifest_contract(tmp_path) -> None:
    content = b"report"
    manifest = _manifest(DatasetLayer.ARTIFACT, content=content)
    store = LocalFileArtifactStore(tmp_path)
    assert store.put(StoredDataset(manifest, content)).layer is DatasetLayer.ARTIFACT
    assert store.get(manifest.dataset_id).content == content
