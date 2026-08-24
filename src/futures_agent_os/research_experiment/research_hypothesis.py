"""Immutable V1 research artifacts for falsifiable, non-authoritative inquiry.

The Research & Experiment context owns these records.  They intentionally
describe what would disprove an idea and what evidence is missing; they do not
encode a strategy, an approval, or any execution instruction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_GAP_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


class HypothesisLifecycle(StrEnum):
    """Research-owned lifecycle; neither state is a strategy qualification."""

    # Created by this task: statement and falsifier are recorded, but no
    # experiment has been scheduled or executed.
    DRAFT = "DRAFT"
    # Reserved for a later deterministic Experiment Manager after it accepts a
    # complete request; this remains research-only and non-executing.
    READY_FOR_TEST = "READY_FOR_TEST"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    STALE = "STALE"


class HypothesisProposalSource(StrEnum):
    MARKET_STATE_ASSESSMENT = "MARKET_STATE_ASSESSMENT"


def _sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} requires a lowercase content_sha256")


@dataclass(frozen=True, slots=True)
class MarketStateAssessmentRef:
    """The immutable Market Intelligence input consumed by research."""

    assessment_id: EntityId
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.assessment_id, EntityId) or self.assessment_id.namespace != "market_state_assessment":
            raise ValueError("market-state reference requires a market_state_assessment id")
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.as_of, RecordedAt):
            raise TypeError("market-state reference requires schema version and as_of")
        if not isinstance(self.valid_until, RecordedAt) or self.valid_until.value <= self.as_of.value:
            raise ValueError("market-state reference requires a valid lifetime")
        _sha256(self.content_sha256, "market-state reference")

    def to_dict(self) -> dict[str, str]:
        return {
            "assessment_id": str(self.assessment_id),
            "content_sha256": self.content_sha256,
            "schema_version": str(self.schema_version),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
        }


@dataclass(frozen=True, slots=True)
class FalsifiableHypothesisSpec:
    spec_id: EntityId
    version: int
    schema_version: SchemaVersion

    def __post_init__(self) -> None:
        if not isinstance(self.spec_id, EntityId) or self.spec_id.namespace != "hypothesis_spec":
            raise ValueError("hypothesis spec requires a hypothesis_spec id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("hypothesis spec version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("hypothesis spec requires SchemaVersion")

    def to_dict(self) -> dict[str, str | int]:
        return {"spec_id": str(self.spec_id), "version": self.version, "schema_version": str(self.schema_version)}


@dataclass(frozen=True, slots=True)
class ExperimentRequestSpec:
    spec_id: EntityId
    version: int
    schema_version: SchemaVersion

    def __post_init__(self) -> None:
        if not isinstance(self.spec_id, EntityId) or self.spec_id.namespace != "experiment_request_spec":
            raise ValueError("experiment request spec requires an experiment_request_spec id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("experiment request spec version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("experiment request spec requires SchemaVersion")

    def to_dict(self) -> dict[str, str | int]:
        return {"spec_id": str(self.spec_id), "version": self.version, "schema_version": str(self.schema_version)}


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    code: str
    description: str

    def __post_init__(self) -> None:
        if not _GAP_CODE.fullmatch(self.code) or not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("evidence gap requires a canonical code and non-empty description")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "description": self.description}


@dataclass(frozen=True, slots=True)
class ResearchSynthesisInput:
    statement: str
    applicable_markets: tuple[str, ...]
    observable_outcome: str
    falsification_criterion: str
    required_data: tuple[str, ...]
    proposal_source: HypothesisProposalSource
    unknowns: tuple[str, ...]
    knowns: tuple[str, ...]
    conflicts: tuple[str, ...]
    next_steps: tuple[str, ...]
    evidence_gaps: tuple[EvidenceGap, ...]
    experiment_control: str
    evaluation_window: str
    experiment_method: str
    experiment_metrics: tuple[str, ...]
    expected_diagnostics: tuple[str, ...]
    stop_condition: str
    potential_biases: tuple[str, ...]

    def __post_init__(self) -> None:
        unknowns = tuple(sorted(set(self.unknowns)))
        knowns = tuple(sorted(set(self.knowns)))
        conflicts = tuple(sorted(set(self.conflicts)))
        next_steps = tuple(sorted(set(self.next_steps)))
        applicable_markets = tuple(sorted(set(self.applicable_markets)))
        required_data = tuple(sorted(set(self.required_data)))
        metrics = tuple(sorted(set(self.experiment_metrics)))
        diagnostics = tuple(sorted(set(self.expected_diagnostics)))
        biases = tuple(sorted(set(self.potential_biases)))
        gaps = tuple(sorted(set(self.evidence_gaps), key=lambda item: (item.code, item.description)))
        text = (
            self.statement,
            self.observable_outcome,
            self.falsification_criterion,
            self.experiment_control,
            self.evaluation_window,
            self.experiment_method,
            self.stop_condition,
        )
        if any(not isinstance(value, str) or not value.strip() for value in text):
            raise ValueError("research synthesis input requires complete hypothesis and experiment fields")
        required_collections = (
            applicable_markets,
            required_data,
            next_steps,
            metrics,
            diagnostics,
        )
        if any(
            not values or any(not isinstance(value, str) or not value.strip() for value in values)
            for values in required_collections
        ) or any(
            any(not isinstance(value, str) or not value.strip() for value in values)
            for values in (knowns, unknowns, conflicts, biases)
        ):
            raise ValueError("research synthesis input requires complete structured collections")
        if not isinstance(self.proposal_source, HypothesisProposalSource):
            raise TypeError("research synthesis input requires a typed proposal source")
        if any(not isinstance(value, EvidenceGap) for value in gaps):
            raise ValueError("research synthesis input evidence gaps must be typed")
        object.__setattr__(self, "applicable_markets", applicable_markets)
        object.__setattr__(self, "required_data", required_data)
        object.__setattr__(self, "unknowns", unknowns)
        object.__setattr__(self, "knowns", knowns)
        object.__setattr__(self, "conflicts", conflicts)
        object.__setattr__(self, "next_steps", next_steps)
        object.__setattr__(self, "experiment_metrics", metrics)
        object.__setattr__(self, "expected_diagnostics", diagnostics)
        object.__setattr__(self, "potential_biases", biases)
        object.__setattr__(self, "evidence_gaps", gaps)


@dataclass(frozen=True, slots=True)
class FalsifiableHypothesis:
    hypothesis_id: EntityId
    spec: FalsifiableHypothesisSpec
    market_state_assessment: MarketStateAssessmentRef
    as_of: RecordedAt
    valid_until: RecordedAt
    lifecycle: HypothesisLifecycle
    statement: str
    applicable_markets: tuple[str, ...]
    observable_outcome: str
    falsification_criterion: str
    required_data: tuple[str, ...]
    proposal_source: HypothesisProposalSource
    content_sha256: str

    @property
    def schema_version(self) -> SchemaVersion:
        return self.spec.schema_version

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, EntityId) or self.hypothesis_id.namespace != "hypothesis":
            raise ValueError("hypothesis requires a hypothesis id")
        if not isinstance(self.spec, FalsifiableHypothesisSpec) or not isinstance(
            self.market_state_assessment, MarketStateAssessmentRef
        ):
            raise TypeError("hypothesis requires typed spec and market-state reference")
        if self.as_of != self.market_state_assessment.as_of or self.valid_until.value <= self.as_of.value:
            raise ValueError("hypothesis lifetime must follow its market-state reference")
        if self.valid_until.value > self.market_state_assessment.valid_until.value:
            raise ValueError("hypothesis cannot outlive its market-state reference")
        values = (self.statement, self.observable_outcome, self.falsification_criterion)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("hypothesis requires statement, observable outcome, and falsification criterion")
        markets = tuple(sorted(set(self.applicable_markets)))
        required_data = tuple(sorted(set(self.required_data)))
        if any(
            not values or any(not isinstance(value, str) or not value.strip() for value in values)
            for values in (markets, required_data)
        ):
            raise ValueError("hypothesis requires applicable markets and required data")
        if not isinstance(self.lifecycle, HypothesisLifecycle) or not isinstance(
            self.proposal_source, HypothesisProposalSource
        ):
            raise TypeError("hypothesis requires explicit lifecycle and proposal source")
        _sha256(self.content_sha256, "hypothesis")
        object.__setattr__(self, "applicable_markets", markets)
        object.__setattr__(self, "required_data", required_data)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("hypothesis content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "spec": self.spec.to_dict(),
            "market_state_assessment": self.market_state_assessment.to_dict(),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
            "lifecycle": self.lifecycle.value,
            "statement": self.statement,
            "applicable_markets": self.applicable_markets,
            "observable_outcome": self.observable_outcome,
            "falsification_criterion": self.falsification_criterion,
            "required_data": self.required_data,
            "proposal_source": self.proposal_source.value,
        }


@dataclass(frozen=True, slots=True)
class EvidenceSynthesis:
    synthesis_id: EntityId
    hypothesis: FalsifiableHypothesis
    as_of: RecordedAt
    valid_until: RecordedAt
    knowns: tuple[str, ...]
    unknowns: tuple[str, ...]
    conflicts: tuple[str, ...]
    next_steps: tuple[str, ...]
    evidence_gaps: tuple[EvidenceGap, ...]
    content_sha256: str

    @property
    def schema_version(self) -> SchemaVersion:
        return self.hypothesis.schema_version

    def __post_init__(self) -> None:
        knowns = tuple(sorted(set(self.knowns)))
        unknowns = tuple(sorted(set(self.unknowns)))
        conflicts = tuple(sorted(set(self.conflicts)))
        next_steps = tuple(sorted(set(self.next_steps)))
        gaps = tuple(sorted(set(self.evidence_gaps), key=lambda item: (item.code, item.description)))
        if not isinstance(self.synthesis_id, EntityId) or self.synthesis_id.namespace != "evidence_synthesis":
            raise ValueError("evidence synthesis requires an evidence_synthesis id")
        if not isinstance(self.hypothesis, FalsifiableHypothesis):
            raise TypeError("evidence synthesis requires a typed hypothesis")
        if self.as_of != self.hypothesis.as_of or self.valid_until != self.hypothesis.valid_until:
            raise ValueError("evidence synthesis must share the hypothesis lifetime")
        if not next_steps or any(not isinstance(value, str) or not value.strip() for value in next_steps):
            raise ValueError("evidence synthesis requires explicit next steps")
        if any(
            any(not isinstance(value, str) or not value.strip() for value in values)
            for values in (knowns, unknowns, conflicts)
        ):
            raise ValueError("evidence synthesis text collections are invalid")
        if any(not isinstance(value, EvidenceGap) for value in gaps):
            raise ValueError("evidence synthesis evidence gaps must be typed")
        _sha256(self.content_sha256, "evidence synthesis")
        object.__setattr__(self, "knowns", knowns)
        object.__setattr__(self, "unknowns", unknowns)
        object.__setattr__(self, "conflicts", conflicts)
        object.__setattr__(self, "next_steps", next_steps)
        object.__setattr__(self, "evidence_gaps", gaps)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("evidence synthesis content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "hypothesis_content_sha256": self.hypothesis.content_sha256,
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
            "knowns": self.knowns,
            "unknowns": self.unknowns,
            "conflicts": self.conflicts,
            "next_steps": self.next_steps,
            "evidence_gaps": tuple(item.to_dict() for item in self.evidence_gaps),
        }


@dataclass(frozen=True, slots=True)
class ExperimentRequest:
    request_id: EntityId
    spec: ExperimentRequestSpec
    hypothesis: FalsifiableHypothesis
    as_of: RecordedAt
    valid_until: RecordedAt
    data_requirements: tuple[str, ...]
    control: str
    evaluation_window: str
    method: str
    metrics: tuple[str, ...]
    expected_diagnostics: tuple[str, ...]
    stop_condition: str
    potential_biases: tuple[str, ...]
    content_sha256: str

    @property
    def hypothesis_content_sha256(self) -> str:
        return self.hypothesis.content_sha256

    @property
    def schema_version(self) -> SchemaVersion:
        return self.spec.schema_version

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, EntityId) or self.request_id.namespace != "experiment_request":
            raise ValueError("experiment request requires an experiment_request id")
        if not isinstance(self.spec, ExperimentRequestSpec) or not isinstance(self.hypothesis, FalsifiableHypothesis):
            raise TypeError("experiment request requires typed spec and hypothesis")
        if self.spec.schema_version != self.hypothesis.schema_version:
            raise ValueError("experiment request and hypothesis schema versions must match")
        if self.as_of != self.hypothesis.as_of or self.valid_until != self.hypothesis.valid_until:
            raise ValueError("experiment request must share the hypothesis lifetime")
        text = (self.control, self.evaluation_window, self.method, self.stop_condition)
        collections = (
            tuple(sorted(set(self.data_requirements))),
            tuple(sorted(set(self.metrics))),
            tuple(sorted(set(self.expected_diagnostics))),
            tuple(sorted(set(self.potential_biases))),
        )
        if (
            any(not isinstance(value, str) or not value.strip() for value in text)
            or any(
                not values or any(not isinstance(value, str) or not value.strip() for value in values)
                for values in collections[:3]
            )
            or any(not isinstance(value, str) or not value.strip() for value in collections[3])
        ):
            raise ValueError("experiment request requires complete research-plan fields")
        if collections[0] != self.hypothesis.required_data:
            raise ValueError("experiment request data requirements must exactly match hypothesis required data")
        _sha256(self.content_sha256, "experiment request")
        object.__setattr__(self, "data_requirements", collections[0])
        object.__setattr__(self, "metrics", collections[1])
        object.__setattr__(self, "expected_diagnostics", collections[2])
        object.__setattr__(self, "potential_biases", collections[3])
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("experiment request content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "spec": self.spec.to_dict(),
            "hypothesis_content_sha256": self.hypothesis.content_sha256,
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
            "data_requirements": self.data_requirements,
            "control": self.control,
            "evaluation_window": self.evaluation_window,
            "method": self.method,
            "metrics": self.metrics,
            "expected_diagnostics": self.expected_diagnostics,
            "stop_condition": self.stop_condition,
            "potential_biases": self.potential_biases,
        }


@dataclass(frozen=True, slots=True)
class ResearchSynthesis:
    synthesis_id: EntityId
    hypothesis: FalsifiableHypothesis
    evidence_synthesis: EvidenceSynthesis
    experiment_request: ExperimentRequest
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.synthesis_id, EntityId) or self.synthesis_id.namespace != "research_synthesis":
            raise ValueError("research synthesis requires a research_synthesis id")
        if (
            not isinstance(self.hypothesis, FalsifiableHypothesis)
            or not isinstance(self.evidence_synthesis, EvidenceSynthesis)
            or not isinstance(self.experiment_request, ExperimentRequest)
        ):
            raise TypeError("research synthesis requires typed research artifacts")
        if (
            self.evidence_synthesis.hypothesis != self.hypothesis
            or self.experiment_request.hypothesis != self.hypothesis
        ):
            raise ValueError("research synthesis artifacts must bind the exact hypothesis")
        if self.experiment_request.data_requirements != self.hypothesis.required_data:
            raise ValueError(
                "research synthesis experiment request data requirements must match hypothesis required data"
            )
        _sha256(self.content_sha256, "research synthesis")
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("research synthesis content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "hypothesis": {"content_sha256": self.hypothesis.content_sha256},
            "evidence_synthesis": {"content_sha256": self.evidence_synthesis.content_sha256},
            "experiment_request": {"content_sha256": self.experiment_request.content_sha256},
        }


class ResearchSynthesisComposer:
    """Pure assembly of versioned research artifacts from one PIT market state."""

    def compose(
        self,
        hypothesis_spec: FalsifiableHypothesisSpec,
        experiment_request_spec: ExperimentRequestSpec,
        market_state_assessment: MarketStateAssessmentRef,
        values: ResearchSynthesisInput,
        valid_until: RecordedAt,
    ) -> ResearchSynthesis:
        if not isinstance(hypothesis_spec, FalsifiableHypothesisSpec) or not isinstance(
            experiment_request_spec, ExperimentRequestSpec
        ):
            raise TypeError("research synthesis composer requires typed artifact specs")
        if hypothesis_spec.schema_version != experiment_request_spec.schema_version:
            raise ValueError("research artifact specs must use one schema version")
        if not isinstance(market_state_assessment, MarketStateAssessmentRef) or not isinstance(
            values, ResearchSynthesisInput
        ):
            raise TypeError("research synthesis composer requires immutable market-state input and research values")
        if (
            not isinstance(valid_until, RecordedAt)
            or not market_state_assessment.as_of.value < valid_until.value <= market_state_assessment.valid_until.value
        ):
            raise ValueError("research synthesis lifetime must be inside the market-state lifetime")
        hypothesis_payload: dict[str, JsonValue] = {
            "spec": hypothesis_spec.to_dict(),
            "market_state_assessment": market_state_assessment.to_dict(),
            "as_of": market_state_assessment.as_of.to_dict()["recorded_at"],
            "valid_until": valid_until.to_dict()["recorded_at"],
            "lifecycle": HypothesisLifecycle.DRAFT.value,
            "statement": values.statement,
            "applicable_markets": values.applicable_markets,
            "observable_outcome": values.observable_outcome,
            "falsification_criterion": values.falsification_criterion,
            "required_data": values.required_data,
            "proposal_source": values.proposal_source.value,
        }
        hypothesis = FalsifiableHypothesis(
            EntityId.new("hypothesis"),
            hypothesis_spec,
            market_state_assessment,
            market_state_assessment.as_of,
            valid_until,
            HypothesisLifecycle.DRAFT,
            values.statement,
            values.applicable_markets,
            values.observable_outcome,
            values.falsification_criterion,
            values.required_data,
            values.proposal_source,
            canonical_sha256(hypothesis_payload),
        )
        evidence_payload: dict[str, JsonValue] = {
            "hypothesis_content_sha256": hypothesis.content_sha256,
            "as_of": hypothesis.as_of.to_dict()["recorded_at"],
            "valid_until": hypothesis.valid_until.to_dict()["recorded_at"],
            "knowns": values.knowns,
            "unknowns": values.unknowns,
            "conflicts": values.conflicts,
            "next_steps": values.next_steps,
            "evidence_gaps": tuple(item.to_dict() for item in values.evidence_gaps),
        }
        evidence_synthesis = EvidenceSynthesis(
            EntityId.new("evidence_synthesis"),
            hypothesis,
            hypothesis.as_of,
            hypothesis.valid_until,
            values.knowns,
            values.unknowns,
            values.conflicts,
            values.next_steps,
            values.evidence_gaps,
            canonical_sha256(evidence_payload),
        )
        request_payload: dict[str, JsonValue] = {
            "spec": experiment_request_spec.to_dict(),
            "hypothesis_content_sha256": hypothesis.content_sha256,
            "as_of": hypothesis.as_of.to_dict()["recorded_at"],
            "valid_until": hypothesis.valid_until.to_dict()["recorded_at"],
            "data_requirements": values.required_data,
            "control": values.experiment_control,
            "evaluation_window": values.evaluation_window,
            "method": values.experiment_method,
            "metrics": values.experiment_metrics,
            "expected_diagnostics": values.expected_diagnostics,
            "stop_condition": values.stop_condition,
            "potential_biases": values.potential_biases,
        }
        experiment_request = ExperimentRequest(
            EntityId.new("experiment_request"),
            experiment_request_spec,
            hypothesis,
            hypothesis.as_of,
            hypothesis.valid_until,
            values.required_data,
            values.experiment_control,
            values.evaluation_window,
            values.experiment_method,
            values.experiment_metrics,
            values.expected_diagnostics,
            values.stop_condition,
            values.potential_biases,
            canonical_sha256(request_payload),
        )
        synthesis_payload: dict[str, JsonValue] = {
            "hypothesis": {"content_sha256": hypothesis.content_sha256},
            "evidence_synthesis": {"content_sha256": evidence_synthesis.content_sha256},
            "experiment_request": {"content_sha256": experiment_request.content_sha256},
        }
        return ResearchSynthesis(
            EntityId.new("research_synthesis"),
            hypothesis,
            evidence_synthesis,
            experiment_request,
            canonical_sha256(synthesis_payload),
        )
