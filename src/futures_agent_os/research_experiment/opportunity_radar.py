"""Deterministic, research-only OBSERVE opportunity radar contracts.

This module deliberately stops at research candidates: it has no TradePlan,
Order, account, ledger, or strategy-promotion capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


class ScanResult(StrEnum):
    CANDIDATES = "OPPORTUNITY_CANDIDATE"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"


class TimeHorizon(StrEnum):
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    POSITION = "POSITION"


@dataclass(frozen=True, slots=True)
class ScanPolicy:
    policy_id: str
    revision: str
    cadence_seconds: int
    cooldown_seconds: int = 0

    def __post_init__(self) -> None:
        if (
            not self.policy_id.strip()
            or not self.revision.strip()
            or type(self.cadence_seconds) is not int
            or self.cadence_seconds <= 0
        ):
            raise ValueError("scan policy requires positive cadence and revision")
        if type(self.cooldown_seconds) is not int or self.cooldown_seconds < 0:
            raise ValueError("cooldown must be non-negative")


@dataclass(frozen=True, slots=True)
class UniversePolicy:
    policy_id: str
    revision: str
    instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.revision.strip() or not self.instruments:
            raise ValueError("universe policy is incomplete")
        if any(not x.strip() for x in self.instruments) or len(set(self.instruments)) != len(self.instruments):
            raise ValueError("universe instruments must be unique")


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    ref: str
    content_sha256: str
    summary: str

    def __post_init__(self) -> None:
        if not self.ref.strip() or not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) or not self.summary.strip():
            raise ValueError("evidence requires ref, SHA-256 and summary")


@dataclass(frozen=True, slots=True)
class OpportunityCandidate:
    candidate_id: EntityId
    instrument: str
    horizon: TimeHorizon
    dedupe_key: str
    supporting_evidence: tuple[ResearchEvidence, ...]
    opposing_evidence: tuple[ResearchEvidence, ...]
    hypothesis: str
    cooldown_until: RecordedAt | None = None

    def __post_init__(self) -> None:
        if (
            self.candidate_id.namespace != "opportunity_candidate"
            or not self.instrument.strip()
            or not self.dedupe_key.strip()
            or not self.hypothesis.strip()
        ):
            raise ValueError("invalid opportunity candidate")
        if not self.supporting_evidence or not self.opposing_evidence:
            raise ValueError("candidate requires both supporting and opposing evidence")
        refs = [e.ref for e in self.supporting_evidence + self.opposing_evidence]
        if len(set(refs)) != len(refs):
            raise ValueError("candidate evidence refs must be unique")

    def to_dict(self) -> dict[str, JsonValue]:
        def evidence_dict(e: ResearchEvidence) -> dict[str, str]:
            return {"ref": e.ref, "content_sha256": e.content_sha256, "summary": e.summary}

        return {
            "candidate_id": str(self.candidate_id),
            "instrument": self.instrument,
            "horizon": self.horizon.value,
            "dedupe_key": self.dedupe_key,
            "supporting_evidence": tuple(evidence_dict(e) for e in self.supporting_evidence),
            "opposing_evidence": tuple(evidence_dict(e) for e in self.opposing_evidence),
            "hypothesis": self.hypothesis,
            "cooldown_until": self.cooldown_until.to_dict()["recorded_at"] if self.cooldown_until else None,
        }


@dataclass(frozen=True, slots=True)
class OpportunityScan:
    scan_id: EntityId
    schema_version: SchemaVersion
    scan_policy: ScanPolicy
    universe_policy: UniversePolicy
    as_of: RecordedAt
    data_revision: str
    feature_revision: str
    budget: int
    result: ScanResult
    candidates: tuple[OpportunityCandidate, ...] = ()
    event_ref: EntityId | None = None
    missed: bool = False
    rerun_of: EntityId | None = None

    def __post_init__(self) -> None:
        if (
            self.scan_id.namespace != "opportunity_scan"
            or not self.data_revision.strip()
            or not self.feature_revision.strip()
            or type(self.budget) is not int
            or self.budget <= 0
        ):
            raise ValueError("scan metadata or budget invalid")
        if self.event_ref is not None and self.event_ref.namespace != "market_event":
            raise ValueError("event ref must be a market event")
        if self.rerun_of is not None and self.rerun_of.namespace != "opportunity_scan":
            raise ValueError("rerun ref must be an opportunity scan")
        if self.missed and (self.candidates or self.result is not ScanResult.NO_OPPORTUNITY):
            raise ValueError("a missed scan cannot claim evaluated candidates")
        if self.result is ScanResult.NO_OPPORTUNITY and self.candidates:
            raise ValueError("NO_OPPORTUNITY scan cannot contain candidates")
        if self.result is ScanResult.CANDIDATES and not self.candidates:
            raise ValueError("candidate result requires candidates")
        instruments = set(self.universe_policy.instruments)
        if any(c.instrument not in instruments for c in self.candidates):
            raise ValueError("candidate is outside the frozen universe")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "scan_id": str(self.scan_id),
                "schema_version": str(self.schema_version),
                "scan_policy": self.scan_policy.__dict__
                if hasattr(self.scan_policy, "__dict__")
                else {
                    "policy_id": self.scan_policy.policy_id,
                    "revision": self.scan_policy.revision,
                    "cadence_seconds": self.scan_policy.cadence_seconds,
                    "cooldown_seconds": self.scan_policy.cooldown_seconds,
                },
                "universe_policy": {
                    "policy_id": self.universe_policy.policy_id,
                    "revision": self.universe_policy.revision,
                    "instruments": self.universe_policy.instruments,
                },
                "as_of": self.as_of.to_dict()["recorded_at"],
                "data_revision": self.data_revision,
                "feature_revision": self.feature_revision,
                "budget": self.budget,
                "result": self.result.value,
                "candidates": tuple(c.to_dict() for c in self.candidates),
                "event_ref": str(self.event_ref) if self.event_ref else None,
                "missed": self.missed,
                "rerun_of": str(self.rerun_of) if self.rerun_of else None,
            }
        )


class OpportunityRadar:
    """Small in-process reference implementation for scan dedupe/recovery."""

    def __init__(self) -> None:
        self._scans: dict[EntityId, OpportunityScan] = {}
        self._keys: set[tuple[str, str, str]] = set()

    def scan(
        self,
        *,
        scan_policy: ScanPolicy,
        universe_policy: UniversePolicy,
        as_of: RecordedAt,
        data_revision: str,
        feature_revision: str,
        budget: int,
        candidates: tuple[OpportunityCandidate, ...] = (),
        event_ref: EntityId | None = None,
        missed: bool = False,
        rerun_of: EntityId | None = None,
    ) -> OpportunityScan:
        result = ScanResult.CANDIDATES if candidates else ScanResult.NO_OPPORTUNITY
        filtered: list[OpportunityCandidate] = []
        for candidate in candidates:
            key = (candidate.instrument, candidate.dedupe_key, feature_revision)
            if key in self._keys and not missed:
                continue
            if candidate.cooldown_until and as_of.value < candidate.cooldown_until.value:
                continue
            filtered.append(candidate)
            self._keys.add(key)
        result = ScanResult.CANDIDATES if filtered else ScanResult.NO_OPPORTUNITY
        record = OpportunityScan(
            EntityId.new("opportunity_scan"),
            SchemaVersion(1, 0),
            scan_policy,
            universe_policy,
            as_of,
            data_revision,
            feature_revision,
            budget,
            result,
            tuple(filtered),
            event_ref,
            missed,
            rerun_of,
        )
        self._scans[record.scan_id] = record
        return record

    def rerun_missed(self, scan_id: EntityId, as_of: RecordedAt) -> OpportunityScan:
        original = self._scans[scan_id]
        if not original.missed:
            raise ValueError("only missed scans can be rerun")
        return self.scan(
            scan_policy=original.scan_policy,
            universe_policy=original.universe_policy,
            as_of=as_of,
            data_revision=original.data_revision,
            feature_revision=original.feature_revision,
            budget=original.budget,
            missed=False,
            rerun_of=scan_id,
        )

    def get(self, scan_id: EntityId) -> OpportunityScan:
        return self._scans[scan_id]


__all__ = [
    "ScanPolicy",
    "UniversePolicy",
    "ResearchEvidence",
    "OpportunityCandidate",
    "OpportunityScan",
    "OpportunityRadar",
    "ScanResult",
    "TimeHorizon",
]
