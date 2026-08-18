"""Immutable, point-in-time data-lake contracts and a local object-store adapter.

The adapter is deliberately small: PostgreSQL retains metadata ownership while
large bytes are content-addressed files.  It is suitable for local development
only and never fetches market data itself.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


class DatasetLayer(StrEnum):
    RAW = "raw"
    NORMALIZED_PIT = "normalized_pit"
    FEATURE_SNAPSHOT = "features"
    DATASET = "datasets"
    ARTIFACT = "artifacts"


class DataQualityLevel(StrEnum):
    Q0_INVALID = "Q0_INVALID"
    Q1_DEGRADED = "Q1_DEGRADED"
    Q2_RESEARCH = "Q2_RESEARCH"
    Q3_DECISION = "Q3_DECISION"
    Q4_EXECUTION = "Q4_EXECUTION"


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Traceability for an external fact or a deterministic derived product."""

    source_name: str
    source_uri: str
    acquired_at: RecordedAt
    source_published_at: RecordedAt | None = None
    source_revision: str | None = None

    def __post_init__(self) -> None:
        if not self.source_name.strip() or not self.source_uri.strip():
            raise ValueError("dataset provenance requires source_name and source_uri")
        if self.source_published_at and self.source_published_at.value > self.acquired_at.value:
            raise ValueError("source_published_at cannot be after acquired_at")


@dataclass(frozen=True, slots=True)
class LicenseTerms:
    license_name: str
    allowed_use: str
    retention_policy: str
    redistribution_policy: str
    environment_restriction: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in asdict(self).values()):
            raise ValueError("dataset license requires all use and restriction terms")


@dataclass(frozen=True, slots=True)
class TimeCoverage:
    start: RecordedAt
    end: RecordedAt

    def __post_init__(self) -> None:
        if self.end.value < self.start.value:
            raise ValueError("dataset coverage end cannot precede coverage start")


@dataclass(frozen=True, slots=True)
class QualityReport:
    level: DataQualityLevel
    summary: str
    checked_at: RecordedAt
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("quality report requires a summary")


@dataclass(frozen=True, slots=True)
class RevisionInfo:
    revision: int
    reason: str
    revised_at: RecordedAt
    supersedes_dataset_id: EntityId | None = None

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("dataset revision must be a positive integer")
        if not self.reason.strip():
            raise ValueError("dataset revision requires a reason")
        if self.revision == 1 and self.supersedes_dataset_id is not None:
            raise ValueError("initial dataset revision cannot supersede another dataset")
        if self.revision > 1 and self.supersedes_dataset_id is None:
            raise ValueError("revised dataset must declare supersedes_dataset_id")


@dataclass(frozen=True, slots=True)
class PointInTimeRecord:
    """A normalized observation whose availability is explicit and testable."""

    event_time: RecordedAt
    available_time: RecordedAt
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.available_time.value < self.event_time.value:
            raise ValueError("point-in-time available_time cannot precede event_time")
        if not self.values:
            raise ValueError("point-in-time record requires values")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def validate_as_of(self, as_of: RecordedAt) -> None:
        if self.available_time.value > as_of.value:
            raise ValueError("point-in-time record was not available at dataset as_of")


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Complete immutable descriptor for one content-addressed dataset object."""

    dataset_id: EntityId
    layer: DatasetLayer
    object_uri: str
    content_hash: str
    schema_name: str
    schema_version: SchemaVersion
    coverage: TimeCoverage
    instrument_universe: tuple[str, ...]
    provenance: SourceProvenance
    license: LicenseTerms
    as_of: RecordedAt
    ingested_at: RecordedAt
    quality: QualityReport
    revision: RevisionInfo
    generated_by: str | None = None
    upstream_manifest_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if not self.object_uri.strip() or not self.content_hash.startswith("sha256:"):
            raise ValueError("dataset manifest requires object_uri and canonical content_hash")
        digest = self.content_hash.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("dataset content_hash must be a lowercase sha256 digest")
        if not self.schema_name.strip() or not self.instrument_universe:
            raise ValueError("dataset manifest requires schema and instrument universe")
        if len(set(self.instrument_universe)) != len(self.instrument_universe):
            raise ValueError("dataset instrument universe must be unique")
        if self.as_of.value > self.ingested_at.value:
            raise ValueError("dataset as_of cannot be after ingestion")
        if self.coverage.end.value > self.as_of.value:
            raise ValueError("dataset coverage cannot extend beyond as_of")
        if (
            self.layer in {DatasetLayer.FEATURE_SNAPSHOT, DatasetLayer.DATASET, DatasetLayer.ARTIFACT}
            and not self.generated_by
        ):
            raise ValueError("derived datasets require generated_by provenance")
        if self.layer in {DatasetLayer.FEATURE_SNAPSHOT, DatasetLayer.DATASET} and not self.upstream_manifest_ids:
            raise ValueError("derived datasets require upstream manifests")

    def validate_point_in_time(self, records: tuple[PointInTimeRecord, ...]) -> None:
        if self.layer not in {DatasetLayer.NORMALIZED_PIT, DatasetLayer.FEATURE_SNAPSHOT, DatasetLayer.DATASET}:
            raise ValueError("point-in-time validation applies only to normalized or derived datasets")
        for record in records:
            record.validate_as_of(self.as_of)
            if not (self.coverage.start.value <= record.event_time.value <= self.coverage.end.value):
                raise ValueError("point-in-time record falls outside manifest coverage")


@dataclass(frozen=True, slots=True)
class StoredDataset:
    manifest: DatasetManifest
    content: bytes


class DatasetStore(Protocol):
    def put(self, dataset: StoredDataset) -> DatasetManifest: ...

    def get(self, dataset_id: EntityId) -> StoredDataset: ...


class ArtifactStore(DatasetStore, Protocol):
    """Store for experiment reports, curves, figures, and model outputs."""


def sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class LocalFileDataStore:
    """Append-only local store with separately immutable objects and manifests."""

    def __init__(self, root: Path, layer: DatasetLayer) -> None:
        self._root = root.resolve()
        self._layer = layer

    def put(self, dataset: StoredDataset) -> DatasetManifest:
        manifest = dataset.manifest
        if manifest.layer != self._layer:
            raise ValueError("dataset layer does not match this store")
        if sha256_digest(dataset.content) != manifest.content_hash:
            raise ValueError("dataset content does not match manifest content_hash")
        object_path = self._object_path(manifest.content_hash)
        manifest_path = self._manifest_path(manifest.dataset_id)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(object_path, dataset.content)
        manifest_bytes = _manifest_json(manifest)
        if manifest_path.exists():
            if manifest_path.read_bytes() != manifest_bytes:
                raise ValueError("immutable dataset_id already has a different manifest")
            return manifest
        try:
            self._write_once(manifest_path, manifest_bytes)
        except ValueError:
            # A concurrent writer can win between exists() and O_EXCL.  Its
            # manifest must still be identical for this operation to be safe.
            if manifest_path.read_bytes() != manifest_bytes:
                raise ValueError("immutable dataset_id already has a different manifest") from None
        return manifest

    def get(self, dataset_id: EntityId) -> StoredDataset:
        manifest_path = self._manifest_path(dataset_id)
        manifest = _manifest_from_json(manifest_path.read_bytes())
        if manifest.dataset_id != dataset_id or manifest.layer != self._layer:
            raise ValueError("stored dataset manifest does not match identity or store layer")
        object_path = self._object_path(manifest.content_hash)
        content = object_path.read_bytes()
        if sha256_digest(content) != manifest.content_hash:
            raise ValueError("stored dataset content hash verification failed")
        return StoredDataset(manifest=manifest, content=content)

    def _object_path(self, content_hash: str) -> Path:
        _validate_hash(content_hash)
        return self._root / "objects" / content_hash.removeprefix("sha256:")

    def _manifest_path(self, dataset_id: EntityId) -> Path:
        return self._root / "manifests" / self._layer.value / f"{dataset_id}.json"

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("immutable object path already contains different content") from None
            return
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)


class LocalFileArtifactStore(LocalFileDataStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root, DatasetLayer.ARTIFACT)


def _manifest_json(manifest: DatasetManifest) -> bytes:
    return json.dumps(_manifest_dict(manifest), sort_keys=True, separators=(",", ":")).encode()


def _manifest_dict(manifest: DatasetManifest) -> dict[str, object]:
    return {
        "dataset_id": str(manifest.dataset_id),
        "layer": manifest.layer.value,
        "object_uri": manifest.object_uri,
        "content_hash": manifest.content_hash,
        "schema_name": manifest.schema_name,
        "schema_version": str(manifest.schema_version),
        "coverage": {"start": _time(manifest.coverage.start), "end": _time(manifest.coverage.end)},
        "instrument_universe": list(manifest.instrument_universe),
        "provenance": {
            "source_name": manifest.provenance.source_name,
            "source_uri": manifest.provenance.source_uri,
            "acquired_at": _time(manifest.provenance.acquired_at),
            "source_published_at": _time(manifest.provenance.source_published_at)
            if manifest.provenance.source_published_at
            else None,
            "source_revision": manifest.provenance.source_revision,
        },
        "license": asdict(manifest.license),
        "as_of": _time(manifest.as_of),
        "ingested_at": _time(manifest.ingested_at),
        "quality": {
            "level": manifest.quality.level.value,
            "summary": manifest.quality.summary,
            "checked_at": _time(manifest.quality.checked_at),
            "issues": list(manifest.quality.issues),
        },
        "revision": {
            "revision": manifest.revision.revision,
            "reason": manifest.revision.reason,
            "revised_at": _time(manifest.revision.revised_at),
            "supersedes_dataset_id": str(manifest.revision.supersedes_dataset_id)
            if manifest.revision.supersedes_dataset_id
            else None,
        },
        "generated_by": manifest.generated_by,
        "upstream_manifest_ids": [str(value) for value in manifest.upstream_manifest_ids],
    }


def _manifest_from_json(content: bytes) -> DatasetManifest:
    data = json.loads(content)
    provenance = data["provenance"]
    revision = data["revision"]
    return DatasetManifest(
        dataset_id=EntityId.parse(data["dataset_id"]),
        layer=DatasetLayer(data["layer"]),
        object_uri=data["object_uri"],
        content_hash=data["content_hash"],
        schema_name=data["schema_name"],
        schema_version=SchemaVersion.parse(data["schema_version"]),
        coverage=TimeCoverage(_at(data["coverage"]["start"]), _at(data["coverage"]["end"])),
        instrument_universe=tuple(data["instrument_universe"]),
        provenance=SourceProvenance(
            provenance["source_name"],
            provenance["source_uri"],
            _at(provenance["acquired_at"]),
            _at(provenance["source_published_at"]) if provenance["source_published_at"] else None,
            provenance["source_revision"],
        ),
        license=LicenseTerms(**data["license"]),
        as_of=_at(data["as_of"]),
        ingested_at=_at(data["ingested_at"]),
        quality=QualityReport(
            DataQualityLevel(data["quality"]["level"]),
            data["quality"]["summary"],
            _at(data["quality"]["checked_at"]),
            tuple(data["quality"]["issues"]),
        ),
        revision=RevisionInfo(
            revision["revision"],
            revision["reason"],
            _at(revision["revised_at"]),
            EntityId.parse(revision["supersedes_dataset_id"]) if revision["supersedes_dataset_id"] else None,
        ),
        generated_by=data["generated_by"],
        upstream_manifest_ids=tuple(EntityId.parse(value) for value in data["upstream_manifest_ids"]),
    )


def _time(value: RecordedAt) -> str:
    return value.to_dict()["recorded_at"]


def _at(value: str) -> RecordedAt:
    return RecordedAt.parse(value)


def _validate_hash(content_hash: str) -> None:
    digest = content_hash.removeprefix("sha256:")
    if (
        not content_hash.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("content_hash must be a canonical sha256 digest")
