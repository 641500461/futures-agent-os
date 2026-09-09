"""Point-in-time external research evidence, never business authority."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from datetime import datetime
from futures_agent_os.shared_kernel import canonical_sha256


class EvidenceFormat(StrEnum):
    STRUCTURED = "STRUCTURED"
    UNSTRUCTURED = "UNSTRUCTURED"


@dataclass(frozen=True, slots=True)
class ExternalEvidence:
    evidence_id: str
    source: str
    license: str
    published_at: datetime
    valid_at: datetime
    quality: str
    format: EvidenceFormat
    content_digest: str

    def __post_init__(self):
        if any(
            type(x) is not str or not x.strip()
            for x in (self.evidence_id, self.source, self.license, self.quality, self.content_digest)
        ):
            raise ValueError("external evidence requires source, license, quality and digest")
        if self.published_at.tzinfo is None or self.valid_at.tzinfo is None or self.valid_at < self.published_at:
            raise ValueError("evidence times must be timezone-aware and ordered")
        if type(self.format) is not EvidenceFormat:
            raise TypeError("evidence format must be typed")

    @property
    def content_sha256(self):
        return canonical_sha256(
            {
                "id": self.evidence_id,
                "source": self.source,
                "license": self.license,
                "published": self.published_at.isoformat(),
                "valid": self.valid_at.isoformat(),
                "quality": self.quality,
                "format": self.format.value,
                "content": self.content_digest,
            }
        )

    @property
    def can_be_business_instruction(self) -> bool:
        return False


class EvidenceCatalog:
    def __init__(self):
        self._records = {}

    def add(self, evidence: ExternalEvidence) -> str:
        self._records[evidence.content_sha256] = evidence
        return evidence.content_sha256

    def at(self, when: datetime) -> tuple[ExternalEvidence, ...]:
        return tuple(sorted((e for e in self._records.values() if e.valid_at <= when), key=lambda e: e.content_sha256))


__all__ = ["EvidenceCatalog", "EvidenceFormat", "ExternalEvidence"]
