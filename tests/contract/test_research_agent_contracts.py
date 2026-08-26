"""Acceptance contracts for the V1-007 read-only Research Agent."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from futures_agent_os.agent_orchestration import (
    CATALOG_VERSION,
    AgentRoleId,
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    ResearchAgent,
    ResearchAgentResult,
    ResearchTaskSources,
    TriggerSource,
    definition_for,
)
from futures_agent_os.research_experiment import (
    EvidenceGap,
    ExperimentRequest,
    ExperimentRequestSpec,
    FalsifiableHypothesisSpec,
    HypothesisLifecycle,
    HypothesisProposalSource,
    MarketStateAssessmentRef,
    ResearchSynthesisComposer,
    ResearchSynthesisInput,
    ResearchSynthesis,
)
from futures_agent_os.shared_kernel import (
    EntityId,
    RecordedAt,
    TraceContext,
    canonical_sha256,
)


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 24, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _assessment_ref() -> MarketStateAssessmentRef:
    return MarketStateAssessmentRef(
        EntityId.new("market_state_assessment"),
        CATALOG_VERSION,
        _at(3),
        _at(30),
        "c" * 64,
    )


def _source(ref: MarketStateAssessmentRef) -> ArtifactRef:
    return ArtifactRef(
        ref.assessment_id,
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        ref.schema_version,
        "sha256:" + ref.content_sha256,
        ref.as_of,
        ref.as_of,
    )


def _input() -> ResearchSynthesisInput:
    return ResearchSynthesisInput(
        "When the support-backed TREND state persists for the stated window, the next-window return differs from its regime-matched control.",
        ("CU",),
        "The next-window return relative to a regime-matched control.",
        "The prespecified out-of-sample confidence interval includes the regime-matched control effect.",
        ("historical_data", "feature_observation"),
        HypothesisProposalSource.MARKET_STATE_ASSESSMENT,
        ("Whether costs erase the observed difference",),
        ("The supplied assessment has support-backed market-state evidence",),
        ("Counter-evidence may indicate a regime transition",),
        ("Submit the bounded experiment request for deterministic scheduling",),
        (EvidenceGap("cost_coverage", "No point-in-time cost series is in the market-state lineage."),),
        "Regime-matched control window.",
        "2025-01-01 to 2025-12-31, with a held-out terminal window.",
        "Prespecified L0 directional comparison.",
        ("effect_size", "confidence_interval"),
        ("Retain and report supporting and refuting outcomes.",),
        "Stop after the prespecified out-of-sample window and report both supporting and refuting outcomes.",
        ("selection_bias", "cost_omission"),
    )


def _synthesis(
    ref: MarketStateAssessmentRef,
    hypothesis_spec: FalsifiableHypothesisSpec | None = None,
    request_spec: ExperimentRequestSpec | None = None,
):  # type: ignore[no-untyped-def]
    return ResearchSynthesisComposer().compose(
        hypothesis_spec or FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, CATALOG_VERSION),
        request_spec or ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, CATALOG_VERSION),
        ref,
        _input(),
        _at(25),
    )


def _task(source: ArtifactRef) -> AgentTaskEnvelope:
    correlation_id = EntityId.new("correlation")
    return AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        AgentRoleId.RESEARCH.value,
        CATALOG_VERSION,
        "turn the market-state assessment into a falsifiable research request",
        "return hypothesis, uncertainty synthesis, and an experiment request",
        (TriggerSource.MARKET,),
        (source,),
        (),
        ("historical_query",),
        definition_for(AgentRoleId.RESEARCH.value).budget,
        (ArtifactKind.HYPOTHESIS, ArtifactKind.EVIDENCE_SYNTHESIS, ArtifactKind.EXPERIMENT_REQUEST),
        source.as_of,
        _at(30),
    )


class _PayloadProxy:
    """A duck port with a self-consistent forged hash for adapter hardening tests."""

    def __init__(self, source: object, payload: dict[str, Any], **overrides: object) -> None:
        self._source = source
        self._payload = payload
        self.content_sha256 = canonical_sha256(payload)
        self.__dict__.update(overrides)

    def __getattr__(self, name: str) -> object:
        return getattr(self._source, name)

    def payload(self) -> dict[str, Any]:
        return self._payload


def _forged_port(synthesis: object, layer: str, key: str, value: object) -> _PayloadProxy:
    hypothesis = synthesis.hypothesis  # type: ignore[attr-defined]
    hypothesis_payload = dict(hypothesis.payload())
    if layer == "hypothesis":
        if key in {"spec", "spec_payload_version"}:
            hypothesis_payload["spec"] = {**hypothesis_payload["spec"], "version": value}
        else:
            hypothesis_payload[key] = value
    hypothesis_overrides: dict[str, object] = {}
    if layer == "hypothesis" and key == "lifecycle":
        hypothesis_overrides["lifecycle"] = SimpleNamespace(value=value)
    if layer == "hypothesis" and key in {"spec", "spec_port_version"}:
        hypothesis_overrides["spec"] = SimpleNamespace(
            spec_id=hypothesis.spec.spec_id, version=value, schema_version=hypothesis.schema_version
        )
    forged_hypothesis = _PayloadProxy(
        hypothesis,
        hypothesis_payload,
        **hypothesis_overrides,
    )

    evidence = synthesis.evidence_synthesis  # type: ignore[attr-defined]
    evidence_payload = {**evidence.payload(), "hypothesis_content_sha256": forged_hypothesis.content_sha256}
    if layer == "evidence":
        evidence_payload[key] = value
    forged_evidence = _PayloadProxy(evidence, evidence_payload, hypothesis=forged_hypothesis)

    request = synthesis.experiment_request  # type: ignore[attr-defined]
    request_payload = {**request.payload(), "hypothesis_content_sha256": forged_hypothesis.content_sha256}
    if layer == "request":
        if key in {"spec", "spec_payload_version"}:
            request_payload["spec"] = {**request_payload["spec"], "version": value}
        else:
            request_payload[key] = value
    request_overrides: dict[str, object] = {"hypothesis": forged_hypothesis}
    if layer == "request" and key == "data_requirements":
        request_overrides["data_requirements"] = value
    if layer == "request" and key in {"spec", "spec_port_version"}:
        request_overrides["spec"] = SimpleNamespace(
            spec_id=request.spec.spec_id, version=value, schema_version=request.schema_version
        )
    forged_request = _PayloadProxy(request, request_payload, **request_overrides)

    synthesis_payload = {
        "hypothesis": {"content_sha256": forged_hypothesis.content_sha256},
        "evidence_synthesis": {"content_sha256": forged_evidence.content_sha256},
        "experiment_request": {"content_sha256": forged_request.content_sha256},
    }
    if layer == "synthesis":
        synthesis_payload[key] = value
    return _PayloadProxy(
        synthesis,
        synthesis_payload,
        hypothesis=forged_hypothesis,
        evidence_synthesis=forged_evidence,
        experiment_request=forged_request,
    )


def test_research_synthesis_is_falsifiable_content_addressed_and_explicit_about_gaps() -> None:
    source = _assessment_ref()
    hypothesis_spec = FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, CATALOG_VERSION)
    request_spec = ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, CATALOG_VERSION)
    first = _synthesis(source, hypothesis_spec, request_spec)
    second = _synthesis(source, hypothesis_spec, request_spec)

    assert first.hypothesis.content_sha256 == second.hypothesis.content_sha256
    assert first.evidence_synthesis.content_sha256 == second.evidence_synthesis.content_sha256
    assert first.experiment_request.content_sha256 == second.experiment_request.content_sha256
    assert first.hypothesis.falsification_criterion
    assert first.hypothesis.lifecycle is HypothesisLifecycle.DRAFT
    assert first.hypothesis.applicable_markets == ("CU",)
    assert first.hypothesis.observable_outcome
    assert first.hypothesis.required_data == ("feature_observation", "historical_data")
    assert first.hypothesis.proposal_source is HypothesisProposalSource.MARKET_STATE_ASSESSMENT
    assert (
        first.evidence_synthesis.knowns and first.evidence_synthesis.conflicts and first.evidence_synthesis.next_steps
    )
    assert first.evidence_synthesis.unknowns == ("Whether costs erase the observed difference",)
    assert first.evidence_synthesis.evidence_gaps[0].code == "cost_coverage"
    assert first.experiment_request.stop_condition
    assert first.experiment_request.data_requirements == first.hypothesis.required_data
    assert first.experiment_request.control and first.experiment_request.evaluation_window
    assert first.experiment_request.method and first.experiment_request.metrics
    assert first.experiment_request.expected_diagnostics and first.experiment_request.potential_biases
    assert first.experiment_request.hypothesis_content_sha256 == first.hypothesis.content_sha256
    assert {state.value for state in HypothesisLifecycle} == {
        "DRAFT",
        "READY_FOR_TEST",
        "TESTING",
        "SUPPORTED",
        "PARTIAL",
        "REJECTED",
        "STALE",
    }

    alternate_spec_hypothesis = _synthesis(source)
    alternate_spec_request = _synthesis(source)
    assert alternate_spec_hypothesis.hypothesis.content_sha256 != alternate_spec_request.hypothesis.content_sha256
    assert (
        alternate_spec_hypothesis.experiment_request.content_sha256
        != alternate_spec_request.experiment_request.content_sha256
    )
    assert (
        _synthesis(
            replace(source, assessment_id=EntityId.new("market_state_assessment")), hypothesis_spec, request_spec
        ).hypothesis.content_sha256
        != first.hypothesis.content_sha256
    )

    with pytest.raises(ValueError, match="complete"):
        replace(_input(), falsification_criterion="")


def test_research_agent_packages_only_exact_market_state_lineage_and_non_authoritative_outputs() -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    task = _task(source)
    synthesis = _synthesis(assessment_ref)
    result = ResearchAgent().package(task, ResearchTaskSources((source,)), synthesis, EntityId.new("agent_run"))

    assert tuple(item.ref.artifact_kind for item in result.artifacts) == (
        ArtifactKind.HYPOTHESIS,
        ArtifactKind.EVIDENCE_SYNTHESIS,
        ArtifactKind.EXPERIMENT_REQUEST,
    )
    assert all(item.source_refs == (source,) for item in result.artifacts)
    assert all(item.claims and item.claims[0].evidence_refs == (source,) for item in result.artifacts)
    assert result.unknowns == synthesis.evidence_synthesis.unknowns
    assert tuple((item.code, item.description) for item in result.evidence_gaps) == tuple(
        (item.code, item.description) for item in synthesis.evidence_synthesis.evidence_gaps
    )

    with pytest.raises(ValueError, match="exact immutable source"):
        ResearchAgent().package(
            replace(task, input_artifacts=(replace(source, content_hash="sha256:" + "d" * 64),)),
            ResearchTaskSources((replace(source, content_hash="sha256:" + "d" * 64),)),
            synthesis,
            EntityId.new("agent_run"),
        )
    with pytest.raises(ValueError, match="required outputs"):
        ResearchAgent().package(
            replace(task, required_outputs=(ArtifactKind.HYPOTHESIS,)),
            ResearchTaskSources((source,)),
            synthesis,
            EntityId.new("agent_run"),
        )


@pytest.mark.parametrize(
    ("layer", "key", "value"),
    (
        ("hypothesis", "strategy_candidate", "OPEN"),
        ("evidence", "order", "BUY"),
        ("request", "approval", "GRANTED"),
        ("synthesis", "promotion", "APPROVED"),
    ),
)
def test_research_agent_rejects_hash_recomputed_duck_ports_with_extra_authority_fields(
    layer: str, key: str, value: str
) -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    task = _task(source)
    forged = _forged_port(_synthesis(assessment_ref), layer, key, value)

    with pytest.raises(ValueError, match="payload keys are not exact"):
        ResearchAgent().package(task, ResearchTaskSources((source,)), forged, EntityId.new("agent_run"))


def test_research_agent_rejects_ready_for_test_before_experiment_manager_owns_transition() -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    forged = _forged_port(_synthesis(assessment_ref), "hypothesis", "lifecycle", "READY_FOR_TEST")

    with pytest.raises(ValueError, match="fields are invalid"):
        ResearchAgent().package(_task(source), ResearchTaskSources((source,)), forged, EntityId.new("agent_run"))


def test_research_synthesis_preserves_explicit_empty_uncertainty_and_bias_fields() -> None:
    assessment_ref = _assessment_ref()
    values = replace(_input(), knowns=(), unknowns=(), conflicts=(), evidence_gaps=(), potential_biases=())
    synthesis = ResearchSynthesisComposer().compose(
        FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, CATALOG_VERSION),
        ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, CATALOG_VERSION),
        assessment_ref,
        values,
        _at(25),
    )
    source = _source(assessment_ref)
    result = ResearchAgent().package(
        _task(source), ResearchTaskSources((source,)), synthesis, EntityId.new("agent_run")
    )

    assert synthesis.evidence_synthesis.knowns == ()
    assert synthesis.evidence_synthesis.unknowns == ()
    assert synthesis.evidence_synthesis.conflicts == ()
    assert synthesis.evidence_synthesis.evidence_gaps == ()
    assert synthesis.experiment_request.potential_biases == ()
    assert synthesis.evidence_synthesis.payload()["unknowns"] == ()
    assert synthesis.evidence_synthesis.payload()["evidence_gaps"] == ()
    assert synthesis.experiment_request.payload()["potential_biases"] == ()
    assert result.unknowns == result.evidence_gaps == ()


def test_research_input_freezes_caller_owned_collections_before_composition() -> None:
    caller_knowns = ["support-backed state"]
    caller_data = ["historical_data", "feature_observation"]
    values = replace(_input(), knowns=caller_knowns, required_data=caller_data)  # type: ignore[arg-type]
    caller_knowns.clear()
    caller_data.clear()

    assert values.knowns == ("support-backed state",)
    assert values.required_data == ("feature_observation", "historical_data")


def test_research_agent_rejects_hash_recomputed_true_spec_version_and_unrelated_data() -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    task = _task(source)
    with pytest.raises(ValueError, match="lineage or lifetime"):
        ResearchAgent().package(
            task,
            ResearchTaskSources((source,)),
            _forged_port(_synthesis(assessment_ref), "hypothesis", "spec", True),
            EntityId.new("agent_run"),
        )
    with pytest.raises(ValueError, match="fields are invalid"):
        ResearchAgent().package(
            task,
            ResearchTaskSources((source,)),
            _forged_port(
                _synthesis(assessment_ref),
                "request",
                "data_requirements",
                ("feature_observation", "historical_data", "unrelated_future_dataset"),
            ),
            EntityId.new("agent_run"),
        )


@pytest.mark.parametrize(
    ("layer", "key", "expected"),
    (
        ("hypothesis", "spec_payload_version", "hypothesis payload does not match"),
        ("hypothesis", "spec_port_version", "lineage or lifetime"),
        ("hypothesis", "spec", "lineage or lifetime"),
        ("request", "spec_payload_version", "experiment request payload does not match"),
        ("request", "spec_port_version", "lineage or lifetime"),
        ("request", "spec", "lineage or lifetime"),
    ),
)
def test_research_agent_rejects_all_payload_and_port_bool_spec_version_variants(
    layer: str, key: str, expected: str
) -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    with pytest.raises(ValueError, match=expected):
        ResearchAgent().package(
            _task(source),
            ResearchTaskSources((source,)),
            _forged_port(_synthesis(assessment_ref), layer, key, True),
            EntityId.new("agent_run"),
        )


def test_domain_rejects_rehashed_experiment_request_data_mismatch_before_adapter() -> None:
    synthesis = _synthesis(_assessment_ref())
    request = synthesis.experiment_request
    mismatched_data = (*request.data_requirements, "unrelated_future_dataset")
    request_payload = {**request.payload(), "data_requirements": mismatched_data}
    with pytest.raises(ValueError, match="data requirements"):
        replace(
            request,
            data_requirements=mismatched_data,
            content_sha256=canonical_sha256(request_payload),
        )

    bypassed = object.__new__(ExperimentRequest)
    for field in fields(ExperimentRequest):
        object.__setattr__(
            bypassed,
            field.name,
            canonical_sha256(request_payload)
            if field.name == "content_sha256"
            else mismatched_data
            if field.name == "data_requirements"
            else getattr(request, field.name),
        )
    synthesis_payload = {
        "hypothesis": {"content_sha256": synthesis.hypothesis.content_sha256},
        "evidence_synthesis": {"content_sha256": synthesis.evidence_synthesis.content_sha256},
        "experiment_request": {"content_sha256": bypassed.content_sha256},
    }
    with pytest.raises(ValueError, match="data requirements"):
        ResearchSynthesis(
            EntityId.new("research_synthesis"),
            synthesis.hypothesis,
            synthesis.evidence_synthesis,
            bypassed,
            canonical_sha256(synthesis_payload),
        )


def test_research_agent_rejects_mutable_duck_collections_after_payload_hash_validation() -> None:
    assessment_ref = _assessment_ref()
    synthesis = _synthesis(assessment_ref)
    mutable_evidence = _PayloadProxy(
        synthesis.evidence_synthesis,
        dict(synthesis.evidence_synthesis.payload()),
        unknowns=list(synthesis.evidence_synthesis.unknowns),
    )
    mutable_synthesis = _PayloadProxy(
        synthesis,
        dict(synthesis.payload()),
        evidence_synthesis=mutable_evidence,
    )
    source = _source(assessment_ref)

    with pytest.raises(TypeError, match="immutable tuples"):
        ResearchAgent().package(
            _task(source), ResearchTaskSources((source,)), mutable_synthesis, EntityId.new("agent_run")
        )


def test_research_agent_result_detaches_caller_owned_collections_and_checks_provenance() -> None:
    assessment_ref = _assessment_ref()
    source = _source(assessment_ref)
    result = ResearchAgent().package(
        _task(source), ResearchTaskSources((source,)), _synthesis(assessment_ref), EntityId.new("agent_run")
    )
    caller_artifacts = list(result.artifacts)
    caller_unknowns = list(result.unknowns)
    caller_gaps = list(result.evidence_gaps)
    detached = ResearchAgentResult(caller_artifacts, caller_unknowns, caller_gaps, result.expires_at)
    caller_artifacts.clear()
    caller_unknowns.clear()
    caller_gaps.clear()

    assert isinstance(detached.artifacts, tuple)
    assert isinstance(detached.unknowns, tuple)
    assert isinstance(detached.evidence_gaps, tuple)
    assert detached.artifacts and detached.unknowns and detached.evidence_gaps
    with pytest.raises(ValueError, match="provenance"):
        ResearchAgentResult(
            (replace(result.artifacts[0], producer_role_id=AgentRoleId.MARKET_REGIME.value), *result.artifacts[1:]),
            result.unknowns,
            result.evidence_gaps,
            result.expires_at,
        )
    with pytest.raises(ValueError, match="provenance"):
        ResearchAgentResult(
            (replace(result.artifacts[0], expires_at=_at(29)), *result.artifacts[1:]),
            result.unknowns,
            result.evidence_gaps,
            result.expires_at,
        )


def test_research_role_cannot_receive_trade_approval_promotion_or_ledger_capabilities() -> None:
    research = definition_for(AgentRoleId.RESEARCH.value)
    forbidden_tools = {
        "submit_trade_plan",
        "request_plan_approval",
        "submit_improvement_proposal",
        "request_activation",
    }
    forbidden_outputs = {
        ArtifactKind.TRADE_PLAN_DRAFT,
        ArtifactKind.STRATEGY_CANDIDATE,
    }

    assert not forbidden_tools.intersection(research.declared_tools)
    assert not forbidden_outputs.intersection(research.output_kinds)
    assert ArtifactKind.EXPERIMENT_REQUEST in research.output_kinds
    assert research.input_kinds == (ArtifactKind.MARKET_STATE_ASSESSMENT,)

    source = _source(_assessment_ref())
    task = _task(source)
    with pytest.raises(ValueError, match="tool"):
        from futures_agent_os.agent_orchestration import validate_task_envelope

        validate_task_envelope(replace(task, allowed_tools=("submit_trade_plan",)))
    with pytest.raises(ValueError, match="input artifact"):
        validate_task_envelope(replace(task, input_artifacts=(replace(source, artifact_kind=ArtifactKind.REFLECTION),)))

    root = Path(__file__).resolve().parents[2] / "src" / "futures_agent_os"
    source_text = (root / "agent_orchestration" / "research_agent.py").read_text(encoding="utf-8")
    for forbidden in (
        "futures_agent_os.decision",
        "futures_agent_os.portfolio_risk",
        "futures_agent_os.execution_simulation",
        "futures_agent_os.accounting_settlement",
        "TradePlan",
        "RiskDecision",
        "Order",
        "LedgerEntry",
    ):
        assert forbidden not in source_text


def test_research_synthesis_fails_closed_for_forged_or_expired_market_state_reference() -> None:
    reference = _assessment_ref()
    synthesis = _synthesis(reference)
    forged_payload = {**synthesis.payload(), "hypothesis": {"content_sha256": "0" * 64}}
    with pytest.raises(ValueError, match="content_sha256"):
        replace(synthesis, content_sha256=canonical_sha256(forged_payload))
    with pytest.raises(ValueError, match="lifetime"):
        ResearchSynthesisComposer().compose(
            FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, CATALOG_VERSION),
            ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, CATALOG_VERSION),
            replace(reference, valid_until=_at(24)),
            _input(),
            _at(25),
        )
