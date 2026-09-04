"""Deterministic, research-only evaluation contracts for V1-012."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
import re
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _digest(v: JsonValue) -> str:
    return canonical_sha256(v)


def _check(v: str, field: str) -> None:
    if not _SHA256.fullmatch(v):
        raise ValueError(f"{field} requires lowercase SHA-256")


class EvaluationDimension(StrEnum):
    TOOL_SELECTION = "tool_selection"
    CITATION_CORRECTNESS = "citation_correctness"
    NUMERIC_GROUNDING = "numeric_grounding"
    COUNTER_EVIDENCE = "counter_evidence"
    DECISION_DISCIPLINE = "decision_discipline"
    REPLAY_CONSISTENCY = "replay_consistency"


class ResearchOutcome(StrEnum):
    NO_TRADE = "NO_TRADE"
    DEFER = "DEFER"
    OPPORTUNITY = "OPPORTUNITY"


_DIMENSIONS = tuple(EvaluationDimension)


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    ref: str
    content_sha256: str
    available_at: RecordedAt

    def __post_init__(self):
        if not self.ref.strip():
            raise ValueError("evidence ref required")
        _check(self.content_sha256, "evidence")

    def to_dict(self):
        return {
            "ref": self.ref,
            "content_sha256": self.content_sha256,
            "available_at": self.available_at.to_dict()["recorded_at"],
        }


@dataclass(frozen=True, slots=True)
class NumericGrounding:
    metric: str
    value: str
    unit: str
    source_ref: str

    def __post_init__(self):
        if any(not x.strip() for x in (self.metric, self.value, self.unit, self.source_ref)):
            raise ValueError("numeric grounding incomplete")

    def to_dict(self):
        return {"metric": self.metric, "value": self.value, "unit": self.unit, "source_ref": self.source_ref}


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    prompt: str
    required_tools: tuple[str, ...]
    evidence: tuple[EvidenceBinding, ...]
    expected_outcome: ResearchOutcome
    expected_evidence_sha256: str
    numeric_groundings: tuple[NumericGrounding, ...] = ()
    counter_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.case_id.strip() or not self.prompt.strip() or not self.required_tools:
            raise ValueError("evaluation case incomplete")
        if len(set(self.required_tools)) != len(self.required_tools) or len({x.ref for x in self.evidence}) != len(
            self.evidence
        ):
            raise ValueError("case refs must be unique")
        if type(self.expected_outcome) is not ResearchOutcome:
            raise TypeError("typed outcome required")
        _check(self.expected_evidence_sha256, "case replay")
        known = {x.ref for x in self.evidence}
        if (
            any(x.source_ref not in known for x in self.numeric_groundings)
            or not set(self.counter_evidence_refs) <= known
        ):
            raise ValueError("grounding must reference frozen evidence")

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "prompt": self.prompt,
            "required_tools": self.required_tools,
            "evidence": tuple(x.to_dict() for x in self.evidence),
            "expected_outcome": self.expected_outcome.value,
            "expected_evidence_sha256": self.expected_evidence_sha256,
            "numeric_groundings": tuple(x.to_dict() for x in self.numeric_groundings),
            "counter_evidence_refs": self.counter_evidence_refs,
        }


@dataclass(frozen=True, slots=True)
class ResearchEvaluationSuite:
    suite_id: EntityId
    version: str
    dataset_revision: str
    rubric_revision: str
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self):
        if self.suite_id.namespace != "evaluation_suite" or not all(
            x.strip() for x in (self.version, self.dataset_revision, self.rubric_revision)
        ):
            raise ValueError("suite metadata incomplete")
        if not self.cases or len({x.case_id for x in self.cases}) != len(self.cases):
            raise ValueError("suite cases must be unique")

    def to_dict(self):
        return {
            "suite_id": str(self.suite_id),
            "version": self.version,
            "dataset_revision": self.dataset_revision,
            "rubric_revision": self.rubric_revision,
            "cases": tuple(x.to_dict() for x in self.cases),
            "frozen": True,
        }

    @property
    def content_sha256(self):
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    outcome: ResearchOutcome
    scores: tuple[tuple[EvaluationDimension, int], ...]
    replay_sha256: str

    def __post_init__(self):
        if type(self.outcome) is not ResearchOutcome or tuple(k for k, _ in self.scores) != _DIMENSIONS:
            raise ValueError("complete ordered scores required")
        if any(type(v) is not int or v not in (0, 1) for _, v in self.scores):
            raise ValueError("scores must be binary")
        _check(self.replay_sha256, "replay")

    def score(self, d):
        return dict(self.scores)[d]

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "outcome": self.outcome.value,
            "scores": {k.value: v for k, v in self.scores},
            "replay_sha256": self.replay_sha256,
        }


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    suite_sha256: str
    model_revision: str
    prompt_revision: str
    toolset_revision: str
    case_scores: tuple[CaseScore, ...]

    def __post_init__(self):
        _check(self.suite_sha256, "suite")
        if (
            not all(x.strip() for x in (self.model_revision, self.prompt_revision, self.toolset_revision))
            or not self.case_scores
            or len({x.case_id for x in self.case_scores}) != len(self.case_scores)
        ):
            raise ValueError("run metadata/cases incomplete")

    def aggregate(self):
        return tuple((d, sum(x.score(d) for x in self.case_scores)) for d in _DIMENSIONS)

    def to_dict(self):
        return {
            "suite_sha256": self.suite_sha256,
            "model_revision": self.model_revision,
            "prompt_revision": self.prompt_revision,
            "toolset_revision": self.toolset_revision,
            "case_scores": tuple(x.to_dict() for x in self.case_scores),
        }

    @property
    def content_sha256(self):
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ComparableReport:
    baseline_run_sha256: str
    candidate_run_sha256: str
    suite_sha256: str
    deltas: tuple[tuple[EvaluationDimension, int], ...]
    replay_equal: bool

    def to_dict(self):
        return {
            "baseline_run_sha256": self.baseline_run_sha256,
            "candidate_run_sha256": self.candidate_run_sha256,
            "suite_sha256": self.suite_sha256,
            "deltas": {k.value: v for k, v in self.deltas},
            "replay_equal": self.replay_equal,
        }

    @property
    def content_sha256(self):
        return _digest(self.to_dict())


class EvaluationManager:
    def __init__(self):
        self._suites = {}

    def freeze(self, suite):
        if suite.content_sha256 in self._suites:
            raise ValueError("suite already frozen")
        self._suites[suite.content_sha256] = suite
        return suite

    def score_case(
        self,
        case,
        *,
        selected_tools,
        cited_evidence,
        numeric_groundings,
        counter_evidence_refs,
        outcome,
        evidence_payload,
    ):
        replay = _digest(evidence_payload)
        evidence_ok = tuple(x.to_dict() for x in cited_evidence) == tuple(x.to_dict() for x in case.evidence)
        vals = (
            int(selected_tools == case.required_tools),
            int(evidence_ok),
            int(numeric_groundings == case.numeric_groundings and evidence_ok),
            int(counter_evidence_refs == case.counter_evidence_refs and evidence_ok),
            int(outcome is case.expected_outcome),
            int(replay == case.expected_evidence_sha256),
        )
        return CaseScore(case.case_id, outcome, tuple(zip(_DIMENSIONS, vals, strict=True)), replay)

    def report(self, baseline, candidate):
        if baseline.suite_sha256 != candidate.suite_sha256 or baseline.suite_sha256 not in self._suites:
            raise ValueError("comparison requires one frozen suite")
        expected = tuple(x.case_id for x in self._suites[baseline.suite_sha256].cases)
        if (
            tuple(x.case_id for x in baseline.case_scores) != expected
            or tuple(x.case_id for x in candidate.case_scores) != expected
        ):
            raise ValueError("runs must cover frozen cases in order")
        a, b = dict(baseline.aggregate()), dict(candidate.aggregate())
        return ComparableReport(
            baseline.content_sha256,
            candidate.content_sha256,
            baseline.suite_sha256,
            tuple((d, b[d] - a[d]) for d in _DIMENSIONS),
            tuple(x.replay_sha256 for x in baseline.case_scores)
            == tuple(x.replay_sha256 for x in candidate.case_scores),
        )


__all__ = [
    "CaseScore",
    "ComparableReport",
    "EvaluationCase",
    "EvaluationDimension",
    "EvaluationManager",
    "EvaluationRun",
    "EvidenceBinding",
    "NumericGrounding",
    "ResearchEvaluationSuite",
    "ResearchOutcome",
]
