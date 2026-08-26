"""Catalog 1.5 diagnostic composition and replayable Research Critic gate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Mapping, Sequence
from typing import ClassVar, TypeAlias, cast

from futures_agent_os.reference_market_data import MarketSnapshot
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .critique import (
    CritiqueCategory,
    CritiqueStatus,
    DiagnosticMeasurement,
    ResearchArtifactIdentity,
    ResearchArtifactKind,
)
from .research_hypothesis import EvidenceSynthesis, ExperimentRequest, FalsifiableHypothesis
from .validation_tools import (
    TOOL_SCHEMA_VERSION,
    ResearchArtifactRef,
    DeterministicResearchTools,
    ResearchToolName,
    ResearchToolResult,
    ToolFailureCode,
    ValidationConfig,
    ValidationRunRequest,
    semantic_entity_id,
)


V1_010_POLICY_ID = EntityId.parse("research_critic_policy_019034dd-0000-7000-8000-000000000010")
V1_010_REQUIRED_TOOLS = (
    ResearchToolName.MARKET_QUERY,
    ResearchToolName.HISTORICAL_QUERY,
    ResearchToolName.FEATURE_QUERY,
    ResearchToolName.CONTRACT_QUERY,
    ResearchToolName.MEMORY_SEARCH,
    ResearchToolName.EXPERIMENT_SEARCH,
    ResearchToolName.L0_SIGNAL_TEST,
    ResearchToolName.L1_BAR_BACKTEST,
    ResearchToolName.WALK_FORWARD,
    ResearchToolName.COST_STRESS,
    ResearchToolName.COUNTERFACTUAL,
)


@dataclass(frozen=True, slots=True)
class V1_010CritiquePolicy:
    policy_id: EntityId = V1_010_POLICY_ID
    version: int = 1
    schema_version: SchemaVersion = TOOL_SCHEMA_VERSION
    max_iterations: int = 1

    def __post_init__(self) -> None:
        if (self.policy_id, self.version, self.schema_version, self.max_iterations) != (
            V1_010_POLICY_ID,
            1,
            TOOL_SCHEMA_VERSION,
            1,
        ):
            raise ValueError("V1-010 research Critic policy is pinned")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "policy_id": str(self.policy_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "max_iterations": self.max_iterations,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticEvidenceV1_010:
    diagnostic_id: EntityId
    category: CritiqueCategory
    policy_id: EntityId
    schema_version: SchemaVersion
    as_of: RecordedAt
    evaluated_at: RecordedAt
    market_snapshot_ref: ResearchArtifactRef
    run_id: EntityId
    config_sha256: str
    research_sources: tuple[ResearchArtifactIdentity, ...]
    tool_results: tuple[ResearchToolResult, ...]
    measurement: DiagnosticMeasurement
    warnings: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.diagnostic_id) is not EntityId
            or self.diagnostic_id.namespace != "critique_diagnostic"
            or self.policy_id != V1_010_POLICY_ID
            or self.schema_version != TOOL_SCHEMA_VERSION
        ):
            raise ValueError("V1-010 diagnostic requires a versioned diagnostic identity")
        if (
            type(self.category) is not CritiqueCategory
            or type(self.as_of) is not RecordedAt
            or type(self.evaluated_at) is not RecordedAt
            or type(self.market_snapshot_ref) is not ResearchArtifactRef
        ):
            raise TypeError("V1-010 diagnostic requires exact category, time, and snapshot ref")
        if self.market_snapshot_ref.artifact_kind != "market_snapshot" or self.market_snapshot_ref.as_of != self.as_of:
            raise ValueError("diagnostic must bind the exact snapshot as_of")
        if not self.as_of.value <= self.evaluated_at.value < self.market_snapshot_ref.valid_until.value:
            raise ValueError("diagnostic evaluated_at must be inside its frozen PIT lifetime")
        if (
            type(self.run_id) is not EntityId
            or self.run_id.namespace != "research_validation_run"
            or type(self.tool_results) is not tuple
            or not self.tool_results
            or any(type(result) is not ResearchToolResult for result in self.tool_results)
        ):
            raise ValueError("diagnostic requires an exact validation run")
        for result in self.tool_results:
            result.__post_init__()
        if any(result.run_id != self.run_id or result.as_of != self.as_of for result in self.tool_results):
            raise ValueError("diagnostic tool lineage cannot cross run or as_of")
        if any(result.valid_until.value <= self.evaluated_at.value for result in self.tool_results):
            raise ValueError("diagnostic cannot consume expired tool results")
        if any(result.config.content_sha256 != self.config_sha256 for result in self.tool_results):
            raise ValueError("diagnostic tool lineage cannot cross frozen configuration")
        expected_sources = tuple(ResearchArtifactKind)
        if (
            type(self.research_sources) is not tuple
            or any(type(source) is not ResearchArtifactIdentity for source in self.research_sources)
            or tuple(source.artifact_kind for source in self.research_sources) != expected_sources
        ):
            raise ValueError("diagnostic requires exact hypothesis, synthesis, and request lineage")
        if any(source.as_of != self.as_of for source in self.research_sources):
            raise ValueError("diagnostic research lineage cannot cross as_of")
        if (
            type(self.warnings) is not tuple
            or any(type(value) is not str or not value.strip() for value in self.warnings)
            or tuple(sorted(set(self.warnings))) != self.warnings
        ):
            raise ValueError("diagnostic warnings must be canonical")
        expected = _diagnostic_measurement(self.category, self.tool_results)
        if self.measurement is not expected:
            raise ValueError("diagnostic measurement must be derived from tool failure codes")
        _digest(self.config_sha256)
        _digest(self.content_sha256)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("diagnostic hash does not match immutable lineage")
        if self.diagnostic_id != semantic_entity_id("critique_diagnostic", self.payload()):
            raise ValueError("diagnostic logical identity must derive from immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "policy_id": str(self.policy_id),
            "schema_version": str(self.schema_version),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "evaluated_at": self.evaluated_at.to_dict()["recorded_at"],
            "market_snapshot_ref": self.market_snapshot_ref.to_dict(),
            "run_id": str(self.run_id),
            "config_sha256": self.config_sha256,
            "research_sources": tuple(source.to_dict() for source in self.research_sources),
            "tool_result_hashes": tuple(result.content_sha256 for result in self.tool_results),
            "measurement": self.measurement.value,
            "warnings": self.warnings,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "diagnostic_id": str(self.diagnostic_id),
            **self.payload(),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def hydrate(
        cls,
        value: Mapping[str, object],
        research_sources: tuple[ResearchArtifactIdentity, ...],
        tool_results: tuple[ResearchToolResult, ...],
    ) -> DiagnosticEvidenceV1_010:
        expected = {
            "diagnostic_id",
            "category",
            "policy_id",
            "schema_version",
            "as_of",
            "evaluated_at",
            "market_snapshot_ref",
            "run_id",
            "config_sha256",
            "research_sources",
            "tool_result_hashes",
            "measurement",
            "warnings",
            "content_sha256",
        }
        if set(value) != expected:
            raise ValueError("diagnostic hydration fields are not exact")
        hashes = tuple(str(item) for item in cast("Sequence[object]", value["tool_result_hashes"]))
        if hashes != tuple(result.content_sha256 for result in tool_results):
            raise ValueError("diagnostic hydration tool result lineage mismatch")
        serialized_sources = tuple(
            cast("Mapping[str, object]", item) for item in cast("Sequence[object]", value["research_sources"])
        )
        if serialized_sources != tuple(source.to_dict() for source in research_sources):
            raise ValueError("diagnostic hydration research lineage mismatch")
        category = CritiqueCategory(str(value["category"]))
        diagnostic = cls(
            EntityId.parse(str(value["diagnostic_id"])),
            category,
            EntityId.parse(str(value["policy_id"])),
            SchemaVersion.parse(str(value["schema_version"])),
            RecordedAt.parse(str(value["as_of"])),
            RecordedAt.parse(str(value["evaluated_at"])),
            ResearchArtifactRef.hydrate(cast("Mapping[str, object]", value["market_snapshot_ref"])),
            EntityId.parse(str(value["run_id"])),
            str(value["config_sha256"]),
            research_sources,
            tool_results,
            DiagnosticMeasurement(str(value["measurement"])),
            tuple(str(item) for item in cast("Sequence[object]", value["warnings"])),
            str(value["content_sha256"]),
        )
        return diagnostic


@dataclass(frozen=True, slots=True)
class _TypedDiagnostic:
    evidence: DiagnosticEvidenceV1_010
    CATEGORY: ClassVar[CritiqueCategory]

    def __post_init__(self) -> None:
        if type(self.evidence) is not DiagnosticEvidenceV1_010 or self.evidence.category is not self.CATEGORY:
            raise ValueError("typed diagnostic category does not match its evidence")


class CounterEvidenceDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.COUNTER_EVIDENCE


class DataLeakageDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.DATA_LEAKAGE


class CostCoverageDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.COST_COVERAGE


class SampleApplicabilityDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.SAMPLE_APPLICABILITY


class ConcentrationDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.CONCENTRATION


class ParameterStabilityDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.PARAMETER_STABILITY


class HistoricalFailureDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.HISTORICAL_FAILURE


class ConclusionStrengthDiagnostic(_TypedDiagnostic):
    CATEGORY = CritiqueCategory.CONCLUSION_STRENGTH


TypedDiagnostic: TypeAlias = (
    CounterEvidenceDiagnostic
    | DataLeakageDiagnostic
    | CostCoverageDiagnostic
    | SampleApplicabilityDiagnostic
    | ConcentrationDiagnostic
    | ParameterStabilityDiagnostic
    | HistoricalFailureDiagnostic
    | ConclusionStrengthDiagnostic
)

_TYPE_BY_CATEGORY: dict[CritiqueCategory, type[_TypedDiagnostic]] = {
    value.CATEGORY: value
    for value in (
        CounterEvidenceDiagnostic,
        DataLeakageDiagnostic,
        CostCoverageDiagnostic,
        SampleApplicabilityDiagnostic,
        ConcentrationDiagnostic,
        ParameterStabilityDiagnostic,
        HistoricalFailureDiagnostic,
        ConclusionStrengthDiagnostic,
    )
}

_TOOLS_BY_CATEGORY = {
    CritiqueCategory.COUNTER_EVIDENCE: (ResearchToolName.COUNTERFACTUAL,),
    CritiqueCategory.DATA_LEAKAGE: (ResearchToolName.MARKET_QUERY, ResearchToolName.HISTORICAL_QUERY),
    CritiqueCategory.COST_COVERAGE: (ResearchToolName.COST_STRESS,),
    CritiqueCategory.SAMPLE_APPLICABILITY: (ResearchToolName.WALK_FORWARD,),
    CritiqueCategory.CONCENTRATION: (ResearchToolName.L1_BAR_BACKTEST,),
    CritiqueCategory.PARAMETER_STABILITY: (ResearchToolName.WALK_FORWARD, ResearchToolName.COUNTERFACTUAL),
    CritiqueCategory.HISTORICAL_FAILURE: (ResearchToolName.EXPERIMENT_SEARCH,),
    CritiqueCategory.CONCLUSION_STRENGTH: V1_010_REQUIRED_TOOLS,
}


@dataclass(frozen=True, slots=True)
class ResearchCritiqueV1_010:
    critique_id: EntityId
    policy: V1_010CritiquePolicy
    market_snapshot_ref: ResearchArtifactRef
    run_id: EntityId
    config: ValidationConfig
    hypothesis_snapshot: FalsifiableHypothesis
    evidence_synthesis_snapshot: EvidenceSynthesis
    experiment_request_snapshot: ExperimentRequest
    diagnostics: tuple[TypedDiagnostic, ...]
    evaluated_at: RecordedAt
    expires_at: RecordedAt
    status: CritiqueStatus
    required_validations: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.critique_id) is not EntityId
            or self.critique_id.namespace != "critique"
            or type(self.policy) is not V1_010CritiquePolicy
        ):
            raise ValueError("research critique requires V1-010 identity and policy")
        if (
            type(self.market_snapshot_ref) is not ResearchArtifactRef
            or type(self.run_id) is not EntityId
            or self.run_id.namespace != "research_validation_run"
            or type(self.config) is not ValidationConfig
            or type(self.hypothesis_snapshot) is not FalsifiableHypothesis
            or type(self.evidence_synthesis_snapshot) is not EvidenceSynthesis
            or type(self.experiment_request_snapshot) is not ExperimentRequest
            or type(self.diagnostics) is not tuple
            or type(self.evaluated_at) is not RecordedAt
            or type(self.expires_at) is not RecordedAt
            or type(self.status) is not CritiqueStatus
            or type(self.required_validations) is not tuple
        ):
            raise TypeError("research critique requires exact immutable V1-010 values")
        if any(type(item) not in tuple(_TYPE_BY_CATEGORY.values()) for item in self.diagnostics):
            raise TypeError("research critique diagnostics must use exact category-specific types")
        for item in self.diagnostics:
            item.__post_init__()
        if (
            self.evidence_synthesis_snapshot.hypothesis != self.hypothesis_snapshot
            or self.experiment_request_snapshot.hypothesis != self.hypothesis_snapshot
        ):
            raise ValueError("research critique must retain exact nested hypothesis lineage")
        if len(self.diagnostics) != len(CritiqueCategory) or tuple(item.CATEGORY for item in self.diagnostics) != tuple(
            sorted(CritiqueCategory, key=lambda value: value.value)
        ):
            raise ValueError("research critique requires all eight typed diagnostics in canonical order")
        if any(
            item.evidence.market_snapshot_ref != self.market_snapshot_ref
            or item.evidence.run_id != self.run_id
            or item.evidence.config_sha256 != self.config.content_sha256
            or item.evidence.evaluated_at != self.evaluated_at
            for item in self.diagnostics
        ):
            raise ValueError("research critique diagnostics must share exact snapshot/run/config lineage")
        exact_sources = _research_identities(
            self.hypothesis_snapshot,
            self.evidence_synthesis_snapshot,
            self.experiment_request_snapshot,
        )
        if any(item.evidence.research_sources != exact_sources for item in self.diagnostics):
            raise ValueError("research critique diagnostics must exactly match retained research source identities")
        failures = tuple(
            item for item in self.diagnostics if item.evidence.measurement is not DiagnosticMeasurement.WITHIN_THRESHOLD
        )
        expected_status = CritiqueStatus.DEFER if failures else CritiqueStatus.PASS
        expected_validations = tuple(f"DIAGNOSTIC_FAILED:{item.CATEGORY.value}" for item in failures)
        if self.status is not expected_status or self.required_validations != expected_validations:
            raise ValueError("research critique conclusion must be deterministically derived")
        if (
            self.evaluated_at.value < self.market_snapshot_ref.as_of.value
            or not self.evaluated_at.value < self.expires_at.value
            or self.expires_at.value
            > min(
                self.market_snapshot_ref.valid_until.value,
                self.hypothesis_snapshot.valid_until.value,
                self.evidence_synthesis_snapshot.valid_until.value,
                self.experiment_request_snapshot.valid_until.value,
            )
        ):
            raise ValueError("research critique requires a valid PIT lifetime")
        _digest(self.content_sha256)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("research critique hash does not match immutable content")
        if self.critique_id != semantic_entity_id("critique", self.payload()):
            raise ValueError("research critique logical identity must derive from immutable content")

    def payload(self) -> dict[str, JsonValue]:
        exact_sources = _research_identities(
            self.hypothesis_snapshot,
            self.evidence_synthesis_snapshot,
            self.experiment_request_snapshot,
        )
        return {
            "policy": self.policy.to_dict(),
            "market_snapshot_ref": self.market_snapshot_ref.to_dict(),
            "run_id": str(self.run_id),
            "config": self.config.payload(),
            "config_sha256": self.config.content_sha256,
            "research_sources": tuple(source.to_dict() for source in exact_sources),
            "diagnostic_hashes": tuple(item.evidence.content_sha256 for item in self.diagnostics),
            "evaluated_at": self.evaluated_at.to_dict()["recorded_at"],
            "expires_at": self.expires_at.to_dict()["recorded_at"],
            "status": self.status.value,
            "required_validations": self.required_validations,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "critique_id": str(self.critique_id),
            **self.payload(),
            "config": self.config.to_dict(),
            "diagnostics": tuple(item.evidence.to_dict() for item in self.diagnostics),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def hydrate(
        cls,
        value: Mapping[str, object],
        hypothesis: FalsifiableHypothesis,
        evidence_synthesis: EvidenceSynthesis,
        experiment_request: ExperimentRequest,
        results: tuple[ResearchToolResult, ...],
    ) -> ResearchCritiqueV1_010:
        expected = {
            "critique_id",
            "policy",
            "market_snapshot_ref",
            "run_id",
            "config",
            "config_sha256",
            "research_sources",
            "diagnostic_hashes",
            "diagnostics",
            "evaluated_at",
            "expires_at",
            "status",
            "required_validations",
            "content_sha256",
        }
        if set(value) != expected:
            raise ValueError("critique hydration fields are not exact")
        policy_value = cast("Mapping[str, object]", value["policy"])
        policy = V1_010CritiquePolicy()
        if policy_value != policy.to_dict():
            raise ValueError("critique hydration policy mismatch")
        sources = _research_identities(hypothesis, evidence_synthesis, experiment_request)
        serialized_sources = tuple(
            cast("Mapping[str, object]", item) for item in cast("Sequence[object]", value["research_sources"])
        )
        if serialized_sources != tuple(source.to_dict() for source in sources):
            raise ValueError("critique hydration research lineage mismatch")
        by_tool = {result.tool: result for result in results}
        if set(by_tool) != set(V1_010_REQUIRED_TOOLS) or len(by_tool) != len(results):
            raise ValueError("critique hydration requires the exact validation suite")
        diagnostics: list[TypedDiagnostic] = []
        for raw in cast("Sequence[object]", value["diagnostics"]):
            raw_value = cast("Mapping[str, object]", raw)
            category = CritiqueCategory(str(raw_value["category"]))
            category_results = tuple(by_tool[tool] for tool in _TOOLS_BY_CATEGORY[category])
            evidence = DiagnosticEvidenceV1_010.hydrate(raw_value, sources, category_results)
            diagnostics.append(cast("TypedDiagnostic", _TYPE_BY_CATEGORY[category](evidence)))
        typed = tuple(diagnostics)
        if tuple(str(item) for item in cast("Sequence[object]", value["diagnostic_hashes"])) != tuple(
            item.evidence.content_sha256 for item in typed
        ):
            raise ValueError("critique hydration diagnostic lineage mismatch")
        config = ValidationConfig.hydrate(cast("Mapping[str, object]", value["config"]))
        if config.content_sha256 != str(value["config_sha256"]):
            raise ValueError("critique hydration config hash mismatch")
        return cls(
            EntityId.parse(str(value["critique_id"])),
            policy,
            ResearchArtifactRef.hydrate(cast("Mapping[str, object]", value["market_snapshot_ref"])),
            EntityId.parse(str(value["run_id"])),
            config,
            hypothesis,
            evidence_synthesis,
            experiment_request,
            typed,
            RecordedAt.parse(str(value["evaluated_at"])),
            RecordedAt.parse(str(value["expires_at"])),
            CritiqueStatus(str(value["status"])),
            tuple(str(item) for item in cast("Sequence[object]", value["required_validations"])),
            str(value["content_sha256"]),
        )


class V1_010DiagnosticProducer:
    """Produce the eight immutable diagnostic artifacts before Critic dispatch."""

    def __init__(self, tools: DeterministicResearchTools) -> None:
        if type(tools) is not DeterministicResearchTools:
            raise TypeError("diagnostic producer requires the trusted deterministic tools port")
        self._tools = tools

    def produce(
        self,
        snapshot: MarketSnapshot,
        request: ValidationRunRequest,
        results: tuple[ResearchToolResult, ...],
        hypothesis: FalsifiableHypothesis,
        evidence_synthesis: EvidenceSynthesis,
        experiment_request: ExperimentRequest,
        evaluated_at: RecordedAt,
    ) -> tuple[TypedDiagnostic, ...]:
        if (
            type(snapshot) is not MarketSnapshot
            or type(request) is not ValidationRunRequest
            or any(type(result) is not ResearchToolResult for result in results)
        ):
            raise TypeError("V1-010 diagnostic production requires exact snapshot and tool results")
        snapshot.__post_init__()
        request.__post_init__()
        self._tools.verify_results(results)
        replayed = self._tools.run_snapshot_suite(snapshot, request)
        if results != replayed:
            raise ValueError("diagnostic producer rejects untrusted or non-deterministic tool results")
        for result in results:
            result.__post_init__()
        by_tool = {result.tool: result for result in results}
        if len(by_tool) != len(results) or tuple(sorted(by_tool, key=lambda value: value.value)) != tuple(
            sorted(V1_010_REQUIRED_TOOLS, key=lambda value: value.value)
        ):
            raise ValueError("V1-010 composition requires exactly the pinned validation suite")
        run_ids = {result.run_id for result in results}
        configs = {result.config for result in results}
        snapshot_ref = request.snapshot_ref
        if (
            snapshot_ref.artifact_id != snapshot.snapshot_id
            or snapshot_ref.content_sha256 != snapshot.expected_content_sha256
            or snapshot_ref.as_of != snapshot.as_of
            or snapshot_ref.schema_version != snapshot.schema_version
            or run_ids != {request.run_id}
            or configs != {request.config}
            or any(result.request_sha256 != request.content_sha256 for result in results)
            or any(result.valid_until.value <= evaluated_at.value for result in results)
        ):
            raise ValueError("validation suite must bind one exact snapshot/run/config")
        if evidence_synthesis.hypothesis != hypothesis or experiment_request.hypothesis != hypothesis:
            raise ValueError("Critic research sources must bind the exact hypothesis")
        if (
            hypothesis.content_sha256 != canonical_sha256(hypothesis.payload())
            or evidence_synthesis.content_sha256 != canonical_sha256(evidence_synthesis.payload())
            or experiment_request.content_sha256 != canonical_sha256(experiment_request.payload())
        ):
            raise ValueError("Critic research source hash does not match its immutable snapshot")
        sources = _research_identities(hypothesis, evidence_synthesis, experiment_request)
        if any(source.as_of != snapshot.as_of for source in sources):
            raise ValueError("snapshot and research artifacts must share exact as_of")
        if (
            request.query_scope.hypothesis_sha256 != hypothesis.content_sha256
            or request.query_scope.market not in hypothesis.applicable_markets
            or evaluated_at.value >= min(source.valid_until.value for source in sources)
        ):
            raise ValueError("diagnostics require exact hypothesis market scope and PIT lifetime")
        run_id = next(iter(run_ids))
        config = next(iter(configs))
        diagnostics: list[TypedDiagnostic] = []
        suite_has_failure = any(result.failure_code is not ToolFailureCode.NONE for result in results)
        for category in sorted(CritiqueCategory, key=lambda value: value.value):
            category_results = tuple(by_tool[tool] for tool in _TOOLS_BY_CATEGORY[category])
            measurement = _diagnostic_measurement(category, category_results)
            if category is CritiqueCategory.CONCLUSION_STRENGTH and suite_has_failure:
                measurement = DiagnosticMeasurement.THRESHOLD_BREACH
            warnings = tuple(sorted({warning for result in category_results for warning in result.warnings}))
            if measurement is DiagnosticMeasurement.THRESHOLD_BREACH:
                warnings = tuple(sorted((*warnings, "deterministic diagnostic threshold breached")))
            payload: dict[str, JsonValue] = {
                "category": category.value,
                "policy_id": str(V1_010_POLICY_ID),
                "schema_version": str(TOOL_SCHEMA_VERSION),
                "as_of": snapshot.as_of.to_dict()["recorded_at"],
                "evaluated_at": evaluated_at.to_dict()["recorded_at"],
                "market_snapshot_ref": snapshot_ref.to_dict(),
                "run_id": str(run_id),
                "config_sha256": config.content_sha256,
                "research_sources": tuple(source.to_dict() for source in sources),
                "tool_result_hashes": tuple(result.content_sha256 for result in category_results),
                "measurement": measurement.value,
                "warnings": warnings,
            }
            evidence = DiagnosticEvidenceV1_010(
                semantic_entity_id("critique_diagnostic", payload),
                category,
                V1_010_POLICY_ID,
                TOOL_SCHEMA_VERSION,
                snapshot.as_of,
                evaluated_at,
                snapshot_ref,
                run_id,
                config.content_sha256,
                sources,
                category_results,
                measurement,
                warnings,
                canonical_sha256(payload),
            )
            diagnostics.append(cast("TypedDiagnostic", _TYPE_BY_CATEGORY[category](evidence)))
        return tuple(diagnostics)


class V1_010CritiqueComposer:
    """Validate already-produced diagnostics and deterministically adjudicate them."""

    def compose(
        self,
        snapshot: MarketSnapshot,
        request: ValidationRunRequest,
        hypothesis: FalsifiableHypothesis,
        evidence_synthesis: EvidenceSynthesis,
        experiment_request: ExperimentRequest,
        diagnostics: tuple[TypedDiagnostic, ...],
        evaluated_at: RecordedAt,
        expires_at: RecordedAt,
    ) -> ResearchCritiqueV1_010:
        if (
            type(snapshot) is not MarketSnapshot
            or type(request) is not ValidationRunRequest
            or type(diagnostics) is not tuple
            or any(type(item) not in tuple(_TYPE_BY_CATEGORY.values()) for item in diagnostics)
        ):
            raise TypeError("V1-010 composition requires frozen diagnostics")
        snapshot.__post_init__()
        request.__post_init__()
        for item in diagnostics:
            item.__post_init__()
            item.evidence.__post_init__()
        typed = diagnostics
        if len(typed) != len(CritiqueCategory) or tuple(item.CATEGORY for item in typed) != tuple(
            sorted(CritiqueCategory, key=lambda value: value.value)
        ):
            raise ValueError("Critic requires all eight upstream diagnostics in canonical order")
        snapshot_ref = request.snapshot_ref
        sources = _research_identities(hypothesis, evidence_synthesis, experiment_request)
        if (
            evidence_synthesis.hypothesis != hypothesis
            or experiment_request.hypothesis != hypothesis
            or snapshot_ref.artifact_id != snapshot.snapshot_id
            or snapshot_ref.content_sha256 != snapshot.expected_content_sha256
            or snapshot_ref.schema_version != snapshot.schema_version
            or snapshot_ref.as_of != snapshot.as_of
            or request.query_scope.instrument_key != snapshot.rule_resolution.rule.instrument.reference_id
            or request.query_scope.market != snapshot.rule_resolution.rule.instrument.variety.code
            or request.query_scope.hypothesis_sha256 != hypothesis.content_sha256
            or request.query_scope.market not in hypothesis.applicable_markets
            or any(
                item.evidence.market_snapshot_ref != snapshot_ref
                or item.evidence.run_id != request.run_id
                or item.evidence.config_sha256 != request.config.content_sha256
                or item.evidence.research_sources != sources
                or item.evidence.evaluated_at != evaluated_at
                for item in typed
            )
            or expires_at.value > min(source.valid_until.value for source in sources)
            or expires_at.value > snapshot_ref.valid_until.value
        ):
            raise ValueError("Critic diagnostics do not bind the exact frozen lineage")
        run_id = request.run_id
        config = request.config
        failures = tuple(
            item for item in typed if item.evidence.measurement is not DiagnosticMeasurement.WITHIN_THRESHOLD
        )
        status = CritiqueStatus.DEFER if failures else CritiqueStatus.PASS
        validations = tuple(f"DIAGNOSTIC_FAILED:{item.CATEGORY.value}" for item in failures)
        policy = V1_010CritiquePolicy()
        payload: dict[str, JsonValue] = {
            "policy": policy.to_dict(),
            "market_snapshot_ref": snapshot_ref.to_dict(),
            "run_id": str(run_id),
            "config": config.payload(),
            "config_sha256": config.content_sha256,
            "research_sources": tuple(source.to_dict() for source in sources),
            "diagnostic_hashes": tuple(item.evidence.content_sha256 for item in typed),
            "evaluated_at": evaluated_at.to_dict()["recorded_at"],
            "expires_at": expires_at.to_dict()["recorded_at"],
            "status": status.value,
            "required_validations": validations,
        }
        return ResearchCritiqueV1_010(
            semantic_entity_id("critique", payload),
            policy,
            snapshot_ref,
            run_id,
            config,
            hypothesis,
            evidence_synthesis,
            experiment_request,
            typed,
            evaluated_at,
            expires_at,
            status,
            validations,
            canonical_sha256(payload),
        )


class V1_010CriticWorker:
    """Synchronous schedulable Catalog 1.5 worker port.

    The orchestrator supplies a hydrated run request and immutable source
    snapshots. This boundary performs no model or tool invocation itself.
    """

    def run(
        self,
        snapshot: MarketSnapshot,
        request: ValidationRunRequest,
        hypothesis: FalsifiableHypothesis,
        evidence_synthesis: EvidenceSynthesis,
        experiment_request: ExperimentRequest,
        diagnostics: tuple[TypedDiagnostic, ...],
        evaluated_at: RecordedAt,
        expires_at: RecordedAt,
    ) -> ResearchCritiqueV1_010:
        return V1_010CritiqueComposer().compose(
            snapshot,
            request,
            hypothesis,
            evidence_synthesis,
            experiment_request,
            diagnostics,
            evaluated_at,
            expires_at,
        )


def _research_identities(
    hypothesis: FalsifiableHypothesis, synthesis: EvidenceSynthesis, request: ExperimentRequest
) -> tuple[ResearchArtifactIdentity, ...]:
    return (
        ResearchArtifactIdentity(
            hypothesis.hypothesis_id,
            ResearchArtifactKind.HYPOTHESIS,
            hypothesis.schema_version,
            hypothesis.content_sha256,
            hypothesis.as_of,
            hypothesis.valid_until,
        ),
        ResearchArtifactIdentity(
            synthesis.synthesis_id,
            ResearchArtifactKind.EVIDENCE_SYNTHESIS,
            synthesis.schema_version,
            synthesis.content_sha256,
            synthesis.as_of,
            synthesis.valid_until,
        ),
        ResearchArtifactIdentity(
            request.request_id,
            ResearchArtifactKind.EXPERIMENT_REQUEST,
            request.schema_version,
            request.content_sha256,
            request.as_of,
            request.valid_until,
        ),
    )


def _diagnostic_measurement(
    category: CritiqueCategory, results: tuple[ResearchToolResult, ...]
) -> DiagnosticMeasurement:
    """Apply the closed V1-010 thresholds to measured tool outputs."""
    if any(result.failure_code is not ToolFailureCode.NONE for result in results):
        return DiagnosticMeasurement.THRESHOLD_BREACH
    metrics = {result.tool: dict(result.metrics) for result in results}
    config = results[0].config
    passes = True
    if category is CritiqueCategory.COUNTER_EVIDENCE:
        values = metrics[ResearchToolName.COUNTERFACTUAL]
        passes = (
            values.get("changed_variable") == "signal_direction"
            and values.get("fixed_config_sha256") == config.content_sha256
            and Decimal(values["baseline_net_mean"]) > Decimal(values["counterfactual_net_mean"])
        )
    elif category is CritiqueCategory.DATA_LEAKAGE:
        passes = all(
            int(metrics[tool]["future_observation_count"]) == 0
            for tool in (ResearchToolName.MARKET_QUERY, ResearchToolName.HISTORICAL_QUERY)
        )
    elif category is CritiqueCategory.COST_COVERAGE:
        passes = Decimal(metrics[ResearchToolName.COST_STRESS]["worst_net_mean"]) >= 0
    elif category is CritiqueCategory.SAMPLE_APPLICABILITY:
        values = metrics[ResearchToolName.WALK_FORWARD]
        passes = int(values["fold_count"]) >= 1 and values["tuning_count"] == "0"
    elif category is CritiqueCategory.CONCENTRATION:
        passes = (
            Decimal(metrics[ResearchToolName.L1_BAR_BACKTEST]["max_abs_contribution_ratio"])
            <= config.maximum_contribution_ratio
        )
    elif category is CritiqueCategory.PARAMETER_STABILITY:
        values = metrics[ResearchToolName.WALK_FORWARD]
        passes = (
            int(values["fold_count"]) >= 2
            and Decimal(values["positive_fold_ratio"]) >= config.minimum_fold_positive_ratio
        )
    elif category is CritiqueCategory.HISTORICAL_FAILURE:
        values = metrics[ResearchToolName.EXPERIMENT_SEARCH]
        passes = int(values["match_count"]) >= 1 and int(values["failed_count"]) == 0
    elif category is CritiqueCategory.CONCLUSION_STRENGTH:
        l0 = metrics[ResearchToolName.L0_SIGNAL_TEST]
        passes = (
            int(metrics[ResearchToolName.FEATURE_QUERY]["injected_feature_count"]) >= 1
            and Decimal(l0["signal_coverage"]) >= config.minimum_signal_coverage
            and Decimal(l0["accuracy"]) >= config.minimum_signal_accuracy
            and int(metrics[ResearchToolName.L1_BAR_BACKTEST]["signal_count"]) >= 1
        )
    return DiagnosticMeasurement.WITHIN_THRESHOLD if passes else DiagnosticMeasurement.THRESHOLD_BREACH


def _digest(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("content digest requires lowercase SHA-256")
