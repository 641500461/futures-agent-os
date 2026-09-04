"""Counterexample contracts for MVP-R-002 Phase 0 only.

Everything below is owner-signed synthetic evidence. It neither runs a model
nor reads any diagnostic, holdout, or shadow roster.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.research_experiment.mvp_pivot import (
    PIVOT_HYPOTHESIS_FAMILIES,
    HypothesisFamilyScreen,
)
from futures_agent_os.research_experiment.mvp_r_002 import (
    AgentRunOutcome,
    AlwaysDispositionBaseline,
    CandidateEvidenceBundle,
    CriticDecision,
    DeterministicFailureCode,
    DeterministicTemplateBaseline,
    EvidenceKind,
    ExperimentBinding,
    ExperimentReadiness,
    FaultCategory,
    FaultFailureCode,
    FaultInput,
    FrozenFaultRoster,
    FrozenProfileQualification,
    GroundedTextClaim,
    IndependentCritic,
    IndependentCriticInvocation,
    OwnerEvidenceArtifact,
    OwnerEvidenceIssuer,
    OwnerEvidenceRegistry,
    NarrativeCategory,
    PhaseZeroAuthority,
    PhaseZeroEvaluator,
    ProposalIntent,
    ResearchAction,
    ResearchCandidateFactory,
    ResearchCandidatePacket,
    ResearchEligibility,
    ResearchInvocationAuthorization,
    ResearchProposal,
    ResearchRunner,
    RuntimeInputKind,
    RuntimeInputRef,
    RuntimeAssetRef,
    RuntimeOwnerBinding,
    RuntimeReceiptPayload,
    SourceReference,
    SourceManifest,
    SourceRecord,
    SourcePurpose,
    build_next_experiment,
    render_chinese_report,
    render_deterministic_template_chinese_report,
    verify_agent_critic_outcome,
    verify_agent_run_outcome,
)
from futures_agent_os.research_experiment.mvp_validation import HypothesisFamily
from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


@dataclass(frozen=True)
class _Episode:
    authority: PhaseZeroAuthority
    critic_authority: PhaseZeroAuthority
    issuer: OwnerEvidenceIssuer
    registry: OwnerEvidenceRegistry
    candidate: ResearchCandidatePacket
    binding: ExperimentBinding
    profile: OwnerEvidenceArtifact
    critic_profile: OwnerEvidenceArtifact
    prompt: OwnerEvidenceArtifact
    schema: OwnerEvidenceArtifact
    cost: OwnerEvidenceArtifact
    reproduction: OwnerEvidenceArtifact


def _screens(eligibility: ResearchEligibility) -> tuple[HypothesisFamilyScreen, ...]:
    if eligibility is ResearchEligibility.REJECTED:
        return tuple(
            HypothesisFamilyScreen(family, 0, 0, Decimal(0), Decimal(0), Decimal(0), Decimal(0))
            for family in PIVOT_HYPOTHESIS_FAMILIES
        )
    if eligibility is ResearchEligibility.INSUFFICIENT_EVIDENCE:
        return tuple(
            HypothesisFamilyScreen(family, 0, 3, Decimal("0.40"), Decimal("-0.01"), Decimal("-0.02"), Decimal("0.20"))
            for family in PIVOT_HYPOTHESIS_FAMILIES
        )
    return tuple(
        HypothesisFamilyScreen(
            family,
            1 if family is HypothesisFamily.MOMENTUM_CONTINUATION else 0,
            12 if family is HypothesisFamily.MOMENTUM_CONTINUATION else 3,
            Decimal("0.75") if family is HypothesisFamily.MOMENTUM_CONTINUATION else Decimal("0.40"),
            Decimal("0.11") if family is HypothesisFamily.MOMENTUM_CONTINUATION else Decimal("-0.01"),
            Decimal("0.08") if family is HypothesisFamily.MOMENTUM_CONTINUATION else Decimal("-0.02"),
            Decimal("0.80") if family is HypothesisFamily.MOMENTUM_CONTINUATION else Decimal("0.20"),
        )
        for family in PIVOT_HYPOTHESIS_FAMILIES
    )


def _episode(eligibility: ResearchEligibility = ResearchEligibility.ELIGIBLE) -> _Episode:
    authority = PhaseZeroAuthority(bytes(range(32)))
    critic_authority = PhaseZeroAuthority(bytes(range(32, 64)))
    issuer = OwnerEvidenceIssuer(authority, "synthetic-owner")
    start = datetime(2026, 8, 1, 7, tzinfo=UTC)
    records = tuple(
        SourceRecord(
            (start + timedelta(days=index)).isoformat().replace("+00:00", "Z"),
            (start + timedelta(days=index, minutes=1)).isoformat().replace("+00:00", "Z"),
            "1.00",
            "AG2409",
            f"r{index:02d}",
        )
        for index in range(40)
    )
    source_one = issuer.issue_source(
        SourceManifest(
            SourcePurpose.PIT_RESEARCH_INPUT, "SHFE.AG", "2026-09-10T07:00:00Z", "2026-09-10T07:00:01Z", records[:20]
        )
    )
    source_two = issuer.issue_source(
        SourceManifest(
            SourcePurpose.PIT_RESEARCH_INPUT, "SHFE.AG", "2026-09-10T07:00:00Z", "2026-09-10T07:00:01Z", records[20:]
        )
    )
    refs = (
        SourceReference(source_one.content_sha256, "/records/0/close", "same-label"),
        SourceReference(source_two.content_sha256, "/records/0/close", "same-label"),
    )
    acquisition = issuer.issue(
        EvidenceKind.ACQUISITION,
        {
            "suite_id": "mvp-r-002.phase0.synthetic",
            "episode_id": "phase0-episode",
            "instrument_id": "SHFE.AG",
            "as_of": "2026-09-10T07:00:00Z",
            "market_cutoff": "2026-09-10T07:00:00Z",
            "acquired_at": "2026-09-10T07:00:01Z",
            "component_id": "AG2409",
            "roll_warnings": ("主力合约切换需复核",),
            "available_data_range": ("2026-08-01T07:00:00Z", "2026-09-10T07:00:00Z"),
            "warnings": ("仅限合成研究",),
            "unknowns": ("独立窗口尚未验证",),
            "sources": tuple(ref.to_dict() for ref in refs),
        },
    )
    dataset = issuer.issue(
        EvidenceKind.DATASET,
        {
            "instrument_id": "SHFE.AG",
            "acquisition_sha256": acquisition.content_sha256,
            "source_sha256s": (source_one.content_sha256, source_two.content_sha256),
            "row_count": 40,
        },
    )
    screen = issuer.issue(
        EvidenceKind.SCREEN,
        {
            "acquisition_sha256": acquisition.content_sha256,
            "dataset_sha256": dataset.content_sha256,
            "screens": tuple(item.payload() for item in _screens(eligibility)),
        },
    )
    toolset = issuer.issue(EvidenceKind.TOOLSET, {"name": "synthetic-toolset"})
    runtime = issuer.issue(EvidenceKind.RUNTIME, {"name": "synthetic-runtime"})
    profile = issuer.issue_profile(
        FrozenProfileQualification(
            "synthetic-provider",
            "synthetic-research-fixture",
            "synthetic-research-profile",
            "research.hypothesis_synthesis",
            canonical_sha256({"profile": "synthetic-research-profile"}),
            "FROZEN",
        )
    )
    critic_profile = issuer.issue_profile(
        FrozenProfileQualification(
            "synthetic-provider",
            "synthetic-critic-fixture",
            "synthetic-critic-profile",
            "assurance.adversarial_critique",
            canonical_sha256({"profile": "synthetic-critic-profile"}),
            "FROZEN",
        )
    )
    prompt = issuer.issue(EvidenceKind.PROMPT, {"template": "research-only"})
    schema = issuer.issue(EvidenceKind.SCHEMA, {"schema": "grounded-claims"})
    cost = issuer.issue(EvidenceKind.COST, {"budget": "synthetic"})
    reproduction = issuer.issue(EvidenceKind.REPRODUCTION, {"recipe": "synthetic-replay"})
    registry = OwnerEvidenceRegistry(
        authority,
        (
            source_one,
            source_two,
            acquisition,
            dataset,
            screen,
            toolset,
            runtime,
            profile,
            critic_profile,
            prompt,
            schema,
            cost,
            reproduction,
        ),
    )
    evidence = CandidateEvidenceBundle(
        acquisition.content_sha256,
        dataset.content_sha256,
        screen.content_sha256,
        toolset.content_sha256,
        runtime.content_sha256,
    )
    candidate = ResearchCandidateFactory(authority, registry).issue(evidence)
    binding = ExperimentBinding(
        profile.content_sha256,
        prompt.content_sha256,
        schema.content_sha256,
        cost.content_sha256,
        reproduction.content_sha256,
        "2026-08-01T07:00:00Z",
        "2026-09-10T07:00:00Z",
        "2026-08-15T07:00:00Z",
        "2026-08-22T07:00:00Z",
        "2026-08-29T07:00:00Z",
        5,
        "冻结基线",
        "冻结对照",
        "冻结主指标",
        "触发停止即结束",
        "失败仅记录为研究结论",
        ("时间泄漏检查", "重放检查"),
    )
    return _Episode(
        authority,
        critic_authority,
        issuer,
        registry,
        candidate,
        binding,
        profile,
        critic_profile,
        prompt,
        schema,
        cost,
        reproduction,
    )


def _proposal(candidate: ResearchCandidatePacket, action: ResearchAction) -> ResearchProposal:
    return ResearchProposal(
        candidate.content_sha256,
        ProposalIntent.RESEARCH_ONLY,
        action,
        NarrativeCategory.FROZEN_THRESHOLD_RATIONALE,
        (GroundedTextClaim(NarrativeCategory.SCREENING_SUPPORTS_RESEARCH, (candidate.sources[0],)),),
        GroundedTextClaim(NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN, (candidate.sources[1],)),
        (NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN,),
        NarrativeCategory.FROZEN_HYPOTHESIS,
        candidate.sources,
    )


def _research_wire(proposal: ResearchProposal) -> dict[str, JsonValue]:
    return {
        "intent": proposal.intent.value,
        "action": proposal.action.value,
        "why_now": proposal.why_now.value,
        "supporting_claims": tuple(value.to_dict() for value in proposal.supporting_claims),
        "strongest_counter_claim": proposal.strongest_counter_claim.to_dict(),
        "additional_unknowns": tuple(value.value for value in proposal.additional_unknowns),
        "falsifiable_hypothesis": proposal.falsifiable_hypothesis.value,
        "source_refs": tuple(value.to_dict() for value in proposal.source_refs),
    }


def _runner(episode: _Episode) -> ResearchRunner:
    return ResearchRunner(episode.authority, episode.registry, episode.binding)


def _runtime_receipt(
    episode: _Episode,
    *,
    workload_id: str,
    invocation_id: str,
    run_id: str,
    subject_sha256: str,
    input_lineage: tuple[RuntimeInputRef, ...],
    profile: OwnerEvidenceArtifact,
    response_id: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cache_tokens: int,
    latency_ms: int,
    wire: JsonValue | None = None,
) -> OwnerEvidenceArtifact:
    qualification = FrozenProfileQualification.hydrate(profile.payload())
    payload = {
        "workload_id": workload_id,
        "invocation_id": invocation_id,
        "run_id": run_id,
        "subject_sha256": subject_sha256,
        "input_lineage": tuple(item.to_dict() for item in input_lineage),
        "qualification_report_sha256": canonical_sha256({"qualification": workload_id}),
        "config_sha256": canonical_sha256({"config": workload_id}),
        "asset_ref": {
            "asset_sha256": canonical_sha256({"assets": "phase0"}),
            "owner_evidence_sha256": canonical_sha256({"assets_evidence": "phase0"}),
        },
        "profile_sha256": profile.content_sha256,
        "prompt_sha256": episode.prompt.content_sha256,
        "schema_sha256": episode.schema.content_sha256,
        "toolset_sha256": episode.candidate.evidence.toolset_sha256,
        "runtime_sha256": episode.candidate.evidence.runtime_sha256,
        "raw_request_sha256": canonical_sha256({"raw_request": invocation_id}),
        "canonical_request_sha256": canonical_sha256({"request": invocation_id}),
        "raw_response_sha256": canonical_sha256({"raw_response": response_id}),
        "canonical_response_sha256": canonical_sha256({"response": response_id} if wire is None else wire),
        "response_id": response_id,
        "requested_model_id": qualification.model_id,
        "requested_reasoning_effort": "high" if workload_id == "assurance.adversarial_critique" else "medium",
        "actual_provider": qualification.provider,
        "actual_model_id": qualification.model_id,
        "actual_reasoning_effort": "high" if workload_id == "assurance.adversarial_critique" else "medium",
        "input_tokens": input_tokens,
        "cached_input_tokens": cache_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_write_input_tokens": 0,
        "total_tokens": input_tokens + output_tokens,
        "latency_ms": latency_ms,
        "reroute_sha256s": (),
        "activity_sha256s": (),
        "status": "COMPLETED",
        "failure_code": None,
        "failure_stage": None,
        "cost_mode": "SUBSCRIPTION_UNAVAILABLE",
        "cost_available": False,
        "cost_amount": None,
    }
    receipt = RuntimeReceiptPayload(
        **{
            **payload,
            "input_lineage": input_lineage,
            "asset_ref": RuntimeAssetRef(
                canonical_sha256({"assets": "phase0"}),
                canonical_sha256({"assets_evidence": "phase0"}),
            ),
        },
        content_sha256=canonical_sha256(payload),
        signature_sha256=episode.authority.sign(payload),
    )
    artifact = episode.issuer.issue(EvidenceKind.RUNTIME_RECEIPT, receipt.to_dict())
    return artifact


def _model_output(
    episode: _Episode,
    receipt: OwnerEvidenceArtifact,
    workload_id: str,
    wire: JsonValue,
) -> OwnerEvidenceArtifact:
    artifact = episode.issuer.issue(
        EvidenceKind.MODEL_OUTPUT,
        {"workload_id": workload_id, "receipt_sha256": receipt.content_sha256, "wire": wire},
    )
    return artifact


def _owner_binding(episode: _Episode, receipt_artifact: OwnerEvidenceArtifact) -> RuntimeOwnerBinding:
    receipt = RuntimeReceiptPayload.hydrate(receipt_artifact.payload(), episode.authority)
    refs = tuple(
        RuntimeAssetRef(canonical_sha256({"workload": receipt.workload_id, "component": component}), outer)
        for component, outer in zip(
            ("profile", "prompt", "schema", "toolset", "runtime"),
            (
                receipt.profile_sha256,
                receipt.prompt_sha256,
                receipt.schema_sha256,
                receipt.toolset_sha256,
                receipt.runtime_sha256,
            ),
            strict=True,
        )
    )
    return RuntimeOwnerBinding.hydrate(
        {
            "workload_id": receipt.workload_id,
            "asset_ref": receipt.asset_ref.to_dict(),
            "profile_ref": refs[0].to_dict(),
            "prompt_ref": refs[1].to_dict(),
            "schema_ref": refs[2].to_dict(),
            "toolset_ref": refs[3].to_dict(),
            "runtime_ref": refs[4].to_dict(),
        }
    )


def _agent_brief(episode: _Episode, action: ResearchAction):
    runner = _runner(episode)
    proposal = _proposal(episode.candidate, action)
    preview = runner.preview_agent_brief(episode.candidate, proposal)
    invocation = ResearchInvocationAuthorization.issue(
        episode.authority,
        candidate_sha256=episode.candidate.content_sha256,
        request_sha256=proposal.content_sha256,
        profile_sha256=episode.profile.content_sha256,
        prompt_sha256=episode.prompt.content_sha256,
        schema_sha256=episode.schema.content_sha256,
        toolset_sha256=episode.candidate.evidence.toolset_sha256,
        runtime_sha256=episode.candidate.evidence.runtime_sha256,
        invocation_id=f"synthetic-agent-{action.value}",
    )
    invocation_artifact = episode.issuer.issue_research_invocation(invocation)
    episode.registry.add(invocation_artifact)
    synthesis_receipt = _runtime_receipt(
        episode,
        workload_id="research.hypothesis_synthesis",
        invocation_id=invocation.invocation_id,
        run_id=f"research-run:{invocation.invocation_id}",
        subject_sha256=episode.candidate.content_sha256,
        input_lineage=(RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, episode.candidate.content_sha256),),
        profile=episode.profile,
        response_id="synthetic-agent-response",
        input_tokens=100,
        output_tokens=100,
        reasoning_tokens=100,
        cache_tokens=0,
        latency_ms=1,
        wire=_research_wire(proposal),
    )
    experiment_receipt = _runtime_receipt(
        episode,
        workload_id="experiment.preregistration_design",
        invocation_id=f"synthetic-experiment-{action.value}",
        run_id=f"experiment-run:{action.value}",
        subject_sha256=episode.candidate.content_sha256,
        input_lineage=(
            RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, episode.candidate.content_sha256),
            RuntimeInputRef(RuntimeInputKind.EXPERIMENT_BINDING, canonical_sha256(episode.binding.to_dict())),
        ),
        profile=episode.profile,
        response_id=f"synthetic-experiment-response-{action.value}",
        input_tokens=1,
        output_tokens=1,
        reasoning_tokens=1,
        cache_tokens=0,
        latency_ms=1,
        wire={"design_category": "USE_FROZEN_BINDING"},
    )
    synthesis_output = _model_output(
        episode, synthesis_receipt, "research.hypothesis_synthesis", _research_wire(proposal)
    )
    experiment_output = _model_output(
        episode,
        experiment_receipt,
        "experiment.preregistration_design",
        {"design_category": "USE_FROZEN_BINDING"},
    )
    research_run = episode.issuer.issue(
        EvidenceKind.RESEARCH_RUN,
        {
            "candidate_sha256": episode.candidate.content_sha256,
            "proposal_sha256": proposal.content_sha256,
            "agent_brief_sha256": preview.content_sha256,
            "invocation_authorization_sha256": invocation_artifact.content_sha256,
            "invocation_id": invocation.invocation_id,
            "synthesis_receipt_sha256": synthesis_receipt.content_sha256,
            "experiment_design_receipt_sha256": experiment_receipt.content_sha256,
            "synthesis_output_sha256": synthesis_output.content_sha256,
            "experiment_design_output_sha256": experiment_output.content_sha256,
            "synthesis_owner_binding": _owner_binding(episode, synthesis_receipt).to_dict(),
            "experiment_design_owner_binding": _owner_binding(episode, experiment_receipt).to_dict(),
            "experiment_binding_sha256": canonical_sha256(episode.binding.to_dict()),
            "response_sha256": preview.content_sha256,
            "response_id": "synthetic-agent-response",
            "workload_id": "research.hypothesis_synthesis",
            "profile_sha256": episode.profile.content_sha256,
            "prompt_sha256": episode.prompt.content_sha256,
            "schema_sha256": episode.schema.content_sha256,
            "toolset_sha256": episode.candidate.evidence.toolset_sha256,
            "runtime_sha256": episode.candidate.evidence.runtime_sha256,
            "actual_provider": "synthetic-provider",
            "actual_model_id": "synthetic-research-fixture",
            "actual_reasoning_effort": "medium",
            "actual_profile_id": "synthetic-research-profile",
            "input_tokens": 100,
            "output_tokens": 100,
            "reasoning_tokens": 100,
            "cache_tokens": 0,
            "latency_ms": 1,
            "reroutes": (),
        },
    )
    episode.registry.add_many_atomic(
        (synthesis_receipt, experiment_receipt, synthesis_output, experiment_output, research_run)
    )
    return runner.agent_without_critic(episode.candidate, proposal, research_run.content_sha256), research_run


def test_owner_signed_lineage_is_rehydrated_and_source_identity_ignores_label() -> None:
    episode = _episode()
    candidate = episode.candidate
    assert candidate == ResearchCandidatePacket.hydrate(candidate.to_dict(), episode.authority, episode.registry)
    assert candidate.tradable is False and candidate.future_label_present is False
    assert candidate.sources[0].label == candidate.sources[1].label
    assert candidate.sources[0].identity() != candidate.sources[1].identity()
    with pytest.raises(PermissionError, match="future labels"):
        SourceReference(candidate.sources[0].artifact_sha256, "/future_label", "ignored")
    with pytest.raises(ValueError, match="unique"):
        replace(candidate, sources=(candidate.sources[0], candidate.sources[0]))
    with pytest.raises(PermissionError, match="signature"):
        ResearchCandidatePacket.hydrate(
            {**candidate.to_dict(), "signature_sha256": "0" * 64}, episode.authority, episode.registry
        )


def test_phase_zero_workflow_types_are_available_from_public_package() -> None:
    from futures_agent_os.research_experiment import (
        BriefProducer as PublicBriefProducer,
        CandidateEvidenceBundle as PublicBundle,
        DeterministicFailureCode as PublicFailureCode,
        EvidenceKind as PublicEvidenceKind,
        ExperimentBinding as PublicBinding,
        FaultInput as PublicFaultInput,
        FrozenFaultRoster as PublicFaultRoster,
        GroundedTextClaim as PublicClaim,
        GovernedResearchDecision as PublicGovernedDecision,
        NarrativeCategory as PublicNarrativeCategory,
        OwnerEvidenceIssuer as PublicIssuer,
        ProposalIntent as PublicIntent,
        ResearchInvocationAuthorization as PublicInvocationAuthorization,
        RuntimeAssetRef as PublicRuntimeAssetRef,
        RuntimeOwnerBinding as PublicRuntimeOwnerBinding,
        SourceManifest as PublicSourceManifest,
        render_deterministic_template_chinese_report as public_template_renderer,
    )

    assert (
        PublicBundle is CandidateEvidenceBundle
        and PublicBriefProducer.__name__ == "BriefProducer"
        and PublicFailureCode is DeterministicFailureCode
        and PublicEvidenceKind is EvidenceKind
        and PublicBinding is ExperimentBinding
        and PublicFaultInput is FaultInput
        and PublicFaultRoster is FrozenFaultRoster
        and PublicClaim is GroundedTextClaim
        and PublicNarrativeCategory is NarrativeCategory
        and PublicIssuer is OwnerEvidenceIssuer
        and PublicIntent is ProposalIntent
        and PublicInvocationAuthorization is ResearchInvocationAuthorization
        and PublicRuntimeAssetRef is RuntimeAssetRef
        and PublicRuntimeOwnerBinding.__name__ == "RuntimeOwnerBinding"
        and PublicSourceManifest is SourceManifest
        and public_template_renderer is render_deterministic_template_chinese_report
        and PublicGovernedDecision.__name__ == "GovernedResearchDecision"
    )


def test_factory_rejects_unbound_dataset_and_nonexistent_source_pointer() -> None:
    episode = _episode()
    candidate = episode.candidate
    bad_dataset = episode.issuer.issue(
        EvidenceKind.DATASET,
        {"instrument_id": "SHFE.AG", "acquisition_sha256": "0" * 64, "source_sha256s": (), "row_count": 1},
    )
    episode.registry.add(bad_dataset)
    with pytest.raises(PermissionError, match="bind"):
        ResearchCandidateFactory(episode.authority, episode.registry).issue(
            replace(candidate.evidence, dataset_sha256=bad_dataset.content_sha256)
        )
    forged_count = episode.issuer.issue(
        EvidenceKind.DATASET,
        {**episode.registry.require(candidate.evidence.dataset_sha256, EvidenceKind.DATASET).payload(), "row_count": 2},
    )
    episode.registry.add(forged_count)
    forged_screen = episode.issuer.issue(
        EvidenceKind.SCREEN,
        {
            **episode.registry.require(candidate.evidence.screen_sha256, EvidenceKind.SCREEN).payload(),
            "dataset_sha256": forged_count.content_sha256,
        },
    )
    episode.registry.add(forged_screen)
    with pytest.raises(PermissionError, match="row count"):
        ResearchCandidateFactory(episode.authority, episode.registry).issue(
            replace(
                candidate.evidence,
                dataset_sha256=forged_count.content_sha256,
                screen_sha256=forged_screen.content_sha256,
            )
        )
    original_manifest = SourceManifest.hydrate(
        episode.registry.require(candidate.sources[0].artifact_sha256, EvidenceKind.SOURCE).payload()
    )
    duplicate_manifest = replace(
        original_manifest,
        records=(replace(original_manifest.records[0], close="2.00"),) + original_manifest.records[1:],
    )
    duplicate_source = episode.issuer.issue_source(duplicate_manifest)
    episode.registry.add(duplicate_source)
    duplicate_ref = SourceReference(duplicate_source.content_sha256, "/records/0/close", "distinct-label")
    duplicate_acquisition = episode.issuer.issue(
        EvidenceKind.ACQUISITION,
        {
            **episode.registry.require(candidate.evidence.acquisition_sha256, EvidenceKind.ACQUISITION).payload(),
            "sources": (candidate.sources[0].to_dict(), duplicate_ref.to_dict()),
        },
    )
    duplicate_dataset = episode.issuer.issue(
        EvidenceKind.DATASET,
        {
            "instrument_id": candidate.instrument_id,
            "acquisition_sha256": duplicate_acquisition.content_sha256,
            "source_sha256s": (candidate.sources[0].artifact_sha256, duplicate_source.content_sha256),
            "row_count": 40,
        },
    )
    duplicate_screen = episode.issuer.issue(
        EvidenceKind.SCREEN,
        {
            **episode.registry.require(candidate.evidence.screen_sha256, EvidenceKind.SCREEN).payload(),
            "acquisition_sha256": duplicate_acquisition.content_sha256,
            "dataset_sha256": duplicate_dataset.content_sha256,
        },
    )
    for artifact in (duplicate_acquisition, duplicate_dataset, duplicate_screen):
        episode.registry.add(artifact)
    with pytest.raises(PermissionError, match="repeats a natural"):
        ResearchCandidateFactory(episode.authority, episode.registry).issue(
            CandidateEvidenceBundle(
                duplicate_acquisition.content_sha256,
                duplicate_dataset.content_sha256,
                duplicate_screen.content_sha256,
                candidate.evidence.toolset_sha256,
                candidate.evidence.runtime_sha256,
            )
        )
    invalid_source = SourceReference(candidate.sources[0].artifact_sha256, "/records/99/close", "same-label")
    with pytest.raises(PermissionError, match="does not exist"):
        episode.registry.verify_source(invalid_source)


@pytest.mark.parametrize(
    ("eligibility", "allowed", "denied"),
    (
        (
            ResearchEligibility.ELIGIBLE,
            (ResearchAction.TEST_NEXT, ResearchAction.WATCH_FOR_DATA, ResearchAction.REJECT_AS_UNSUPPORTED),
            (),
        ),
        (
            ResearchEligibility.INSUFFICIENT_EVIDENCE,
            (ResearchAction.WATCH_FOR_DATA, ResearchAction.REJECT_AS_UNSUPPORTED),
            (ResearchAction.TEST_NEXT,),
        ),
        (
            ResearchEligibility.REJECTED,
            (ResearchAction.REJECT_AS_UNSUPPORTED,),
            (ResearchAction.TEST_NEXT, ResearchAction.WATCH_FOR_DATA),
        ),
    ),
)
def test_exact_deterministic_action_matrix(eligibility, allowed, denied) -> None:
    for action in allowed:
        episode = _episode(eligibility)
        brief, _run = _agent_brief(episode, action)
        assert brief.action is action
        assert (brief.next_experiment.readiness is ExperimentReadiness.READY) is (action is ResearchAction.TEST_NEXT)
    for action in denied:
        episode = _episode(eligibility)
        with pytest.raises(PermissionError, match="eligibility matrix"):
            _runner(episode).agent_without_critic(episode.candidate, _proposal(episode.candidate, action), "0" * 64)


def test_future_trading_and_numeric_model_prose_fail_closed() -> None:
    episode = _episode()
    candidate = episode.candidate
    with pytest.raises(PermissionError, match="closed narrative"):
        GroundedTextClaim("未来五日上涨99%，创建Order", (candidate.sources[0],))
    with pytest.raises(PermissionError, match="closed narrative"):
        ResearchProposal(
            candidate.content_sha256,
            ProposalIntent.RESEARCH_ONLY,
            ResearchAction.TEST_NEXT,
            "未来五日上涨99%，创建Order",
            (GroundedTextClaim(NarrativeCategory.SCREENING_SUPPORTS_RESEARCH, (candidate.sources[0],)),),
            GroundedTextClaim(NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN, (candidate.sources[1],)),
            (),
            NarrativeCategory.FROZEN_HYPOTHESIS,
            candidate.sources,
        )
    assert _runner(episode).side_effects == ()


@pytest.mark.parametrize("unsafe", ("明日价格上涨百分之九十九", "随后下单", "建立持仓", "将配置设为启用"))
def test_closed_narrative_semantics_reject_chinese_synonym_bypasses(unsafe: str) -> None:
    candidate = _episode().candidate
    with pytest.raises(PermissionError, match="closed narrative"):
        GroundedTextClaim(unsafe, (candidate.sources[0],))


def test_source_manifest_rejects_future_availability_and_schema_aliases() -> None:
    with pytest.raises(PermissionError, match="point-in-time"):
        SourceManifest(
            SourcePurpose.PIT_RESEARCH_INPUT,
            "SHFE.AG",
            "2026-08-30T07:00:00Z",
            "2099-01-01T00:00:00Z",
            (SourceRecord("2026-08-30T07:00:00Z", "2099-01-01T00:00:00Z", "1.00", "AG2409", "r0"),),
        )
    episode = _episode()
    raw = episode.issuer.issue(
        EvidenceKind.SOURCE,
        {
            **episode.registry.require(episode.candidate.sources[0].artifact_sha256, EvidenceKind.SOURCE).payload(),
            "futureLabel": "bypass",
        },
    )
    episode.registry.add(raw)
    with pytest.raises(ValueError, match="source manifest"):
        SourceManifest.hydrate(raw.payload())


def test_source_records_require_unique_chronological_natural_identities_and_finite_close() -> None:
    records = tuple(
        SourceRecord(
            f"2026-08-0{index + 1}T07:00:00Z",
            f"2026-08-0{index + 1}T07:01:00Z",
            "1.00",
            "AG2409",
            f"r{index}",
        )
        for index in range(3)
    )
    with pytest.raises(ValueError, match="unique"):
        SourceManifest(
            SourcePurpose.PIT_RESEARCH_INPUT,
            "SHFE.AG",
            "2026-08-04T07:00:00Z",
            "2026-08-04T07:01:00Z",
            (records[0],) * 5 + (records[1],) * 4 + (records[2],) * 4,
        )
    for close in ("NaN", "Infinity", "-Infinity", "0", "01.00"):
        with pytest.raises(ValueError, match="canonical decimal"):
            SourceRecord("2026-08-01T07:00:00Z", "2026-08-01T07:01:00Z", close, "AG2409", "r0")
    revisions = tuple(
        SourceRecord(
            f"2026-08-0{event + 1}T07:00:00Z",
            f"2026-08-0{event + 1}T07:01:00Z",
            "1.00",
            "AG2409",
            f"revision-{revision:02d}",
        )
        for event in range(3)
        for revision in range(4 if event < 2 else 5)
    )
    with pytest.raises(ValueError, match="unique"):
        SourceManifest(
            SourcePurpose.PIT_RESEARCH_INPUT,
            "SHFE.AG",
            "2026-08-04T07:00:00Z",
            "2026-08-04T07:01:00Z",
            revisions,
        )


def test_fault_roster_add_is_atomic_after_a_late_missing_input_failure() -> None:
    episode = _episode()
    source = episode.candidate.sources[0]
    inputs = tuple(
        episode.issuer.issue(
            EvidenceKind.FAULT_INPUT,
            FaultInput(
                category,
                SourceReference(source.artifact_sha256, source.json_pointer, f"atomic-{category.value}-{variant}"),
                SourcePurpose.PIT_RESEARCH_INPUT.value,
                ResearchEligibility.REJECTED,
                ResearchAction.REJECT_AS_UNSUPPORTED,
                NarrativeCategory.SCREENING_SUPPORTS_RESEARCH.value,
            ).to_dict(),
        )
        for category in FaultCategory
        for variant in range(2)
    )
    for input_artifact in inputs:
        episode.registry.add(input_artifact)
    valid_entries = tuple(
        (category, inputs[index * 2].content_sha256, inputs[index * 2 + 1].content_sha256)
        for index, category in enumerate(FaultCategory)
    )
    bad_entries = (
        valid_entries[0],
        (FaultCategory.FORGED_SOURCE, "0" * 64, valid_entries[1][2]),
        *valid_entries[2:],
    )
    bad_roster = episode.issuer.issue_fault_roster(
        FrozenFaultRoster.issue(
            episode.authority,
            suite_id="atomic-fault-suite",
            candidate_sha256=episode.candidate.content_sha256,
            entries=bad_entries,
        )
    )
    with pytest.raises(PermissionError, match="absent"):
        episode.registry.add(bad_roster)
    with pytest.raises(PermissionError, match="absent"):
        episode.registry.require(bad_roster.content_sha256, EvidenceKind.FAULT_ROSTER)
    valid_roster = episode.issuer.issue_fault_roster(
        FrozenFaultRoster.issue(
            episode.authority,
            suite_id="atomic-fault-suite",
            candidate_sha256=episode.candidate.content_sha256,
            entries=valid_entries,
        )
    )
    episode.registry.add(valid_roster)
    assert episode.registry.require(valid_roster.content_sha256, EvidenceKind.FAULT_ROSTER) == valid_roster


def test_signed_full_experiment_and_request_reject_tampering() -> None:
    episode = _episode()
    experiment = build_next_experiment(
        episode.candidate, ExperimentReadiness.READY, episode.binding, episode.authority, episode.registry
    )
    request = experiment.instantiate_request(episode.authority)
    assert request.binding == episode.binding and request.evidence == episode.candidate.evidence
    assert request.tradable is False and request.strategy_candidate_created is False
    assert type(experiment).hydrate(experiment.to_dict(), episode.authority) == experiment
    assert type(request).hydrate(request.to_dict(), episode.authority) == request
    with pytest.raises(PermissionError, match="signature"):
        type(request).hydrate({**request.to_dict(), "signature_sha256": "0" * 64}, episode.authority)


def test_experiment_binding_requires_strict_splits_coverage_controls_bias_and_embargo() -> None:
    episode = _episode()
    with pytest.raises(ValueError, match="distinct"):
        replace(episode.binding, control=episode.binding.baseline)
    with pytest.raises(ValueError, match="unique"):
        replace(episode.binding, bias_checks=("时间泄漏检查", "时间泄漏检查"))
    with pytest.raises(ValueError, match="ordered"):
        replace(episode.binding, validation_end=episode.binding.train_end)
    with pytest.raises(PermissionError, match="outside"):
        build_next_experiment(
            episode.candidate,
            ExperimentReadiness.READY,
            replace(episode.binding, window_start="2026-07-31T07:00:00Z"),
            episode.authority,
            episode.registry,
        )
    with pytest.raises(ValueError, match="exhaust"):
        build_next_experiment(
            episode.candidate,
            ExperimentReadiness.READY,
            replace(episode.binding, embargo_bars=40),
            episode.authority,
            episode.registry,
        )


@pytest.mark.parametrize("failure_code", tuple(DeterministicFailureCode))
def test_deterministic_zero_token_failure_path_is_signed_defer(failure_code: DeterministicFailureCode) -> None:
    episode = _episode()
    failure = episode.issuer.issue(
        EvidenceKind.FAILURE,
        {
            "candidate_sha256": episode.candidate.content_sha256,
            "failure_code": failure_code.value,
            "detail_source": episode.candidate.sources[0].to_dict(),
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
        },
    )
    episode.registry.add(failure)
    brief = _runner(episode).defer_for_failure(episode.candidate, failure.content_sha256)
    assert brief.action is ResearchAction.DEFER
    assert brief.next_experiment.readiness is ExperimentReadiness.NOT_REQUESTED
    assert type(brief).hydrate(brief.to_dict(), episode.authority) == brief
    nonzero = episode.issuer.issue(
        EvidenceKind.FAILURE,
        {
            "candidate_sha256": episode.candidate.content_sha256,
            "failure_code": DeterministicFailureCode.SOURCE_UNAVAILABLE.value,
            "detail_source": episode.candidate.sources[0].to_dict(),
            "token_usage": {"input_tokens": 1, "output_tokens": 0, "reasoning_tokens": 0},
        },
    )
    episode.registry.add(nonzero)
    with pytest.raises(PermissionError, match="zero"):
        _runner(episode).defer_for_failure(episode.candidate, nonzero.content_sha256)


def _bind_critic_request(
    episode: _Episode,
    critic: IndependentCritic,
    brief: AgentRunOutcome,
    *,
    run_id: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cache_tokens: int,
    latency_ms: int,
    decision: CriticDecision,
):
    invocation = critic.prepare_request(
        episode.candidate,
        brief,
        run_id=run_id,
        profile_sha256=episode.critic_profile.content_sha256,
        prompt_sha256=episode.prompt.content_sha256,
        schema_sha256=episode.schema.content_sha256,
        toolset_sha256=episode.candidate.evidence.toolset_sha256,
        runtime_sha256=episode.candidate.evidence.runtime_sha256,
    )
    receipt = _runtime_receipt(
        episode,
        workload_id="assurance.adversarial_critique",
        invocation_id=invocation.run_id,
        run_id=invocation.run_id,
        subject_sha256=invocation.content_sha256,
        input_lineage=(
            RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, invocation.content_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, invocation.candidate_sha256),
            RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, invocation.agent_outcome_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, invocation.research_run_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, invocation.brief_sha256),
        ),
        profile=episode.critic_profile,
        response_id=f"{run_id}-response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_tokens=cache_tokens,
        latency_ms=latency_ms,
        wire={"decision": decision.value, "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value},
    )
    output = _model_output(
        episode,
        receipt,
        "assurance.adversarial_critique",
        {"decision": decision.value, "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value},
    )
    return (
        critic._bind_unregistered_receipt(
            invocation,
            RuntimeReceiptPayload.hydrate(receipt.payload(), episode.authority),
            receipt.content_sha256,
        ),
        output,
        receipt,
    )


def _critic_outcome(episode: _Episode, decision: CriticDecision):
    runner = _runner(episode)
    brief, research_run = _agent_brief(episode, ResearchAction.TEST_NEXT)
    critic = IndependentCritic(episode.authority, episode.critic_authority, episode.registry)
    invocation = critic.prepare_request(
        episode.candidate,
        brief,
        run_id="synthetic-critic-run",
        profile_sha256=episode.critic_profile.content_sha256,
        prompt_sha256=episode.prompt.content_sha256,
        schema_sha256=episode.schema.content_sha256,
        toolset_sha256=episode.candidate.evidence.toolset_sha256,
        runtime_sha256=episode.candidate.evidence.runtime_sha256,
    )
    critic_receipt = _runtime_receipt(
        episode,
        workload_id="assurance.adversarial_critique",
        invocation_id=invocation.run_id,
        run_id=invocation.run_id,
        subject_sha256=invocation.content_sha256,
        input_lineage=(
            RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, invocation.content_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, invocation.candidate_sha256),
            RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, invocation.agent_outcome_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, invocation.research_run_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, invocation.brief_sha256),
        ),
        profile=episode.critic_profile,
        response_id="synthetic-critic-response",
        input_tokens=1,
        output_tokens=1,
        reasoning_tokens=1,
        cache_tokens=0,
        latency_ms=1,
        wire={"decision": decision.value, "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value},
    )
    critic_output = _model_output(
        episode,
        critic_receipt,
        "assurance.adversarial_critique",
        {"decision": decision.value, "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value},
    )
    request = critic._bind_unregistered_receipt(
        invocation,
        RuntimeReceiptPayload.hydrate(critic_receipt.payload(), episode.authority),
        critic_receipt.content_sha256,
    )
    run = episode.issuer.issue(
        EvidenceKind.CRITIC_RUN,
        {
            "request_sha256": request.content_sha256,
            "workload_id": request.workload_id,
            "candidate_sha256": request.candidate_sha256,
            "brief_sha256": request.brief_sha256,
            "profile_sha256": request.profile_sha256,
            "prompt_sha256": request.prompt_sha256,
            "schema_sha256": request.schema_sha256,
            "toolset_sha256": request.toolset_sha256,
            "runtime_sha256": request.runtime_sha256,
            "critic_receipt_sha256": request.critic_receipt_sha256,
            "critic_output_sha256": critic_output.content_sha256,
            "critic_owner_binding": _owner_binding(episode, critic_receipt).to_dict(),
            "decision": decision.value,
            "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value,
            "reason": "独立窗口结果仍未知",
            "actual_provider": "synthetic-provider",
            "actual_model_id": "synthetic-critic-fixture",
            "actual_reasoning_effort": "high",
            "actual_profile_id": "synthetic-critic-profile",
            "input_tokens": 1,
            "output_tokens": 1,
            "reasoning_tokens": 1,
            "cache_tokens": 0,
            "latency_ms": 1,
            "reroutes": (),
        },
    )
    episode.registry.add_many_atomic((critic_receipt, critic_output, run))
    review = critic.review(request, run.content_sha256)
    return (
        runner,
        critic,
        brief,
        request,
        run,
        review,
        runner.agent_with_critic(episode.candidate, brief, request, review, critic),
        research_run,
    )


def _resign_agent_outcome(
    episode: _Episode,
    outcome: AgentRunOutcome,
    *,
    synthesis_receipt_sha256: str,
    experiment_design_receipt_sha256: str,
) -> AgentRunOutcome:
    payload = {
        **outcome.unsigned_payload(),
        "synthesis_receipt_sha256": synthesis_receipt_sha256,
        "experiment_design_receipt_sha256": experiment_design_receipt_sha256,
    }
    return AgentRunOutcome(
        outcome.candidate_sha256,
        outcome.proposal_sha256,
        outcome.research_run_sha256,
        synthesis_receipt_sha256,
        experiment_design_receipt_sha256,
        outcome.brief,
        canonical_sha256(payload),
        episode.authority.sign(payload),
    )


def test_missing_and_swapped_research_receipts_fail_closed() -> None:
    episode = _episode()
    outcome, _run = _agent_brief(episode, ResearchAction.TEST_NEXT)
    missing = _resign_agent_outcome(
        episode,
        outcome,
        synthesis_receipt_sha256="0" * 64,
        experiment_design_receipt_sha256=outcome.experiment_design_receipt_sha256,
    )
    with pytest.raises(PermissionError, match="absent"):
        verify_agent_run_outcome(episode.candidate, missing, episode.authority, episode.registry, episode.binding)
    swapped = _resign_agent_outcome(
        episode,
        outcome,
        synthesis_receipt_sha256=outcome.experiment_design_receipt_sha256,
        experiment_design_receipt_sha256=outcome.synthesis_receipt_sha256,
    )
    with pytest.raises(PermissionError, match="completed frozen workload|synthesis receipt"):
        verify_agent_run_outcome(episode.candidate, swapped, episode.authority, episode.registry, episode.binding)


def test_cross_brief_critic_receipt_and_replayed_receipt_fail_atomically() -> None:
    episode = _episode()
    _runner_value, critic, _outcome, request, _run, review, _governed, _research_run = _critic_outcome(
        episode, CriticDecision.PASS
    )
    cross_payload = {
        **request.invocation.unsigned_payload(),
        "run_id": "cross-brief-critic-run",
        "brief_sha256": "f" * 64,
    }
    cross_invocation = IndependentCriticInvocation(
        **cross_payload,
        content_sha256=canonical_sha256(cross_payload),
        signature_sha256=episode.critic_authority.sign(cross_payload),
    )
    cross_receipt = _runtime_receipt(
        episode,
        workload_id="assurance.adversarial_critique",
        invocation_id=cross_invocation.run_id,
        run_id=cross_invocation.run_id,
        subject_sha256=cross_invocation.content_sha256,
        input_lineage=(
            RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, cross_invocation.content_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, cross_invocation.candidate_sha256),
            RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, cross_invocation.agent_outcome_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, cross_invocation.research_run_sha256),
            RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, cross_invocation.brief_sha256),
        ),
        profile=episode.critic_profile,
        response_id="cross-brief-critic-response",
        input_tokens=1,
        output_tokens=1,
        reasoning_tokens=1,
        cache_tokens=0,
        latency_ms=1,
    )
    with pytest.raises(PermissionError, match="exact model outputs"):
        episode.registry.add_many_atomic((cross_receipt,))
    with pytest.raises(PermissionError, match="absent"):
        episode.registry.require_runtime_receipt(cross_receipt.content_sha256)
    with pytest.raises(PermissionError, match="absent"):
        critic.bind_request(request.invocation, cross_receipt.content_sha256)

    original = episode.registry.require_runtime_receipt(review.critic_receipt_sha256)
    replay_payload = {**original.unsigned_payload(), "response_id": "replayed-response"}
    replayed = replace(
        original,
        response_id="replayed-response",
        content_sha256=canonical_sha256(replay_payload),
        signature_sha256=episode.authority.sign(replay_payload),
    )
    with pytest.raises(AttributeError):
        setattr(
            episode.registry,
            "_OwnerEvidenceRegistry__pending_completed_batch",
            {replayed.content_sha256},
        )
    with pytest.raises(PermissionError, match="atomic receipt"):
        episode.registry.add(episode.issuer.issue(EvidenceKind.RUNTIME_RECEIPT, replayed.to_dict()))
    assert episode.registry.require_runtime_receipt(review.critic_receipt_sha256) == original


def test_rejected_candidate_critic_revise_cannot_upgrade_to_watch() -> None:
    episode = _episode(ResearchEligibility.REJECTED)
    runner = _runner(episode)
    brief, _research_run = _agent_brief(episode, ResearchAction.REJECT_AS_UNSUPPORTED)
    critic = IndependentCritic(episode.authority, episode.critic_authority, episode.registry)
    request, critic_output, critic_receipt = _bind_critic_request(
        episode,
        critic,
        brief,
        run_id="synthetic-critic-rejected",
        input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        cache_tokens=0,
        latency_ms=0,
        decision=CriticDecision.REVISE,
    )
    run = episode.issuer.issue(
        EvidenceKind.CRITIC_RUN,
        {
            "request_sha256": request.content_sha256,
            "workload_id": request.workload_id,
            "candidate_sha256": request.candidate_sha256,
            "brief_sha256": request.brief_sha256,
            "profile_sha256": request.profile_sha256,
            "prompt_sha256": request.prompt_sha256,
            "schema_sha256": request.schema_sha256,
            "toolset_sha256": request.toolset_sha256,
            "runtime_sha256": request.runtime_sha256,
            "critic_receipt_sha256": request.critic_receipt_sha256,
            "critic_output_sha256": critic_output.content_sha256,
            "critic_owner_binding": _owner_binding(
                episode,
                critic_receipt,
            ).to_dict(),
            "decision": CriticDecision.REVISE.value,
            "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value,
            "reason": "独立窗口结果仍未知",
            "actual_provider": "synthetic-provider",
            "actual_model_id": "synthetic-critic-fixture",
            "actual_reasoning_effort": "high",
            "actual_profile_id": "synthetic-critic-profile",
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_tokens": 0,
            "latency_ms": 0,
            "reroutes": (),
        },
    )
    episode.registry.add_many_atomic((critic_receipt, critic_output, run))
    outcome = runner.agent_with_critic(
        episode.candidate, brief, request, critic.review(request, run.content_sha256), critic
    )
    assert outcome.governed.final_action is ResearchAction.REJECT_AS_UNSUPPORTED


def test_critic_profile_provider_model_and_reroute_are_frozen_gates() -> None:
    episode = _episode()
    _runner_value, _critic, _brief, _request, run, _review, _outcome, _research_run = _critic_outcome(
        episode, CriticDecision.PASS
    )
    wrong_provider = episode.issuer.issue(
        EvidenceKind.CRITIC_RUN, {**run.payload(), "actual_provider": "wrong-provider"}
    )
    with pytest.raises(ValueError, match="append-only semantic run"):
        episode.registry.add(wrong_provider)
    rerouted = episode.issuer.issue(EvidenceKind.CRITIC_RUN, {**run.payload(), "reroutes": ("reroute",)})
    with pytest.raises(ValueError, match="append-only semantic run"):
        episode.registry.add(rerouted)


def test_critic_verdict_only_comes_from_signed_critic_run_and_nonpass_governs_not_requested() -> None:
    episode = _episode()
    runner, critic, brief, request, run, review, outcome, _research_run = _critic_outcome(
        episode, CriticDecision.REVISE
    )
    assert AgentRunOutcome.hydrate(brief.to_dict(), episode.authority) == brief
    assert request.agent_outcome_sha256 == brief.content_sha256
    assert request.research_run_sha256 == brief.research_run_sha256
    with pytest.raises(PermissionError, match="signature"):
        AgentRunOutcome.hydrate({**brief.to_dict(), "signature_sha256": "0" * 64}, episode.authority)
    assert review.run_evidence_sha256 == run.content_sha256
    assert outcome.governed.final_action is ResearchAction.WATCH_FOR_DATA
    assert outcome.governed.next_experiment.readiness is ExperimentReadiness.NOT_REQUESTED
    with pytest.raises(TypeError):
        critic.review(request, CriticDecision.PASS, "caller verdict")
    with pytest.raises(PermissionError, match="absent"):
        critic.review(request, "0" * 64)
    forged_payload = {**review.unsigned_payload(), "decision": CriticDecision.PASS.value}
    forged = replace(
        review,
        decision=CriticDecision.PASS,
        content_sha256=canonical_sha256(forged_payload),
        signature_sha256=episode.critic_authority.sign(forged_payload),
    )
    with pytest.raises(PermissionError, match="exactly derived"):
        runner.agent_with_critic(episode.candidate, brief, request, forged, critic)
    assert outcome.brief == brief.brief and runner.side_effects == ()


def test_resigned_brief_cannot_append_free_unknowns_to_critic_or_renderer() -> None:
    episode = _episode()
    _runner_value, critic, brief, _request, _run, _review, outcome, _research_run = _critic_outcome(
        episode, CriticDecision.PASS
    )
    forged_payload = {
        **brief.brief.unsigned_payload(),
        "candidate_unknowns": (*brief.brief.candidate_unknowns, "恶意自由文本"),
    }
    forged_brief = replace(
        brief.brief,
        candidate_unknowns=(*brief.brief.candidate_unknowns, "恶意自由文本"),
        content_sha256=canonical_sha256(forged_payload),
        signature_sha256=episode.authority.sign(forged_payload),
    )
    with pytest.raises(PermissionError, match="exact candidate unknowns"):
        critic.prepare_request(
            episode.candidate,
            replace(
                brief,
                brief=forged_brief,
                content_sha256=canonical_sha256({**brief.unsigned_payload(), "brief": forged_brief.to_dict()}),
                signature_sha256=episode.authority.sign({**brief.unsigned_payload(), "brief": forged_brief.to_dict()}),
            ),
            run_id="forged-unknowns",
            profile_sha256=episode.critic_profile.content_sha256,
            prompt_sha256=episode.prompt.content_sha256,
            schema_sha256=episode.schema.content_sha256,
            toolset_sha256=episode.candidate.evidence.toolset_sha256,
            runtime_sha256=episode.candidate.evidence.runtime_sha256,
        )
    with pytest.raises(PermissionError, match="exact candidate unknowns"):
        render_chinese_report(
            episode.candidate,
            replace(
                outcome,
                agent_run=replace(
                    brief,
                    brief=forged_brief,
                    content_sha256=canonical_sha256({**brief.unsigned_payload(), "brief": forged_brief.to_dict()}),
                    signature_sha256=episode.authority.sign(
                        {**brief.unsigned_payload(), "brief": forged_brief.to_dict()}
                    ),
                ),
            ),
            episode.authority,
            episode.critic_authority,
            episode.registry,
        )


def test_four_signed_arms_evaluator_binding_and_renderer_completeness() -> None:
    episode = _episode()
    _runner_value, _critic, agent, request, critic_run, review, outcome, research_run = _critic_outcome(
        episode, CriticDecision.REJECT
    )
    template = DeterministicTemplateBaseline(episode.authority, episode.registry, episode.binding).render(
        episode.candidate
    )
    ablation = AlwaysDispositionBaseline(episode.authority, episode.registry, episode.binding)
    always_reject = ablation.render(episode.candidate, ResearchAction.REJECT_AS_UNSUPPORTED)
    always_defer = ablation.render(episode.candidate, ResearchAction.DEFER)
    replay = canonical_sha256(
        {
            "candidate_sha256": episode.candidate.content_sha256,
            "eligibility": episode.candidate.eligibility.value,
            "selected_family": episode.candidate.selected_family.value,
            "agent_action": agent.action.value,
            "counter_claim": agent.strongest_counter_claim.statement,
            "governed_action": outcome.governed.final_action.value,
            "experiment_readiness": outcome.governed.next_experiment.readiness.value,
        }
    )
    source = episode.candidate.sources[0]
    valid_inputs = {
        category: FaultInput(
            category,
            source,
            SourcePurpose.PIT_RESEARCH_INPUT.value,
            ResearchEligibility.REJECTED,
            ResearchAction.REJECT_AS_UNSUPPORTED,
            NarrativeCategory.SCREENING_SUPPORTS_RESEARCH.value,
        )
        for category in FaultCategory
    }
    mutated_inputs = {
        FaultCategory.FUTURE_LEAK: replace(valid_inputs[FaultCategory.FUTURE_LEAK], source_purpose="futureLabel"),
        FaultCategory.FORGED_SOURCE: replace(
            valid_inputs[FaultCategory.FORGED_SOURCE],
            source_ref=SourceReference("0" * 64, "/records/0/close", "forged"),
        ),
        FaultCategory.UNAUTHORIZED_ACTION: replace(
            valid_inputs[FaultCategory.UNAUTHORIZED_ACTION], action=ResearchAction.TEST_NEXT
        ),
        FaultCategory.TRADING_REQUEST: replace(valid_inputs[FaultCategory.TRADING_REQUEST], narrative="创建订单"),
    }
    fault_inputs = tuple(
        episode.issuer.issue(EvidenceKind.FAULT_INPUT, item.to_dict())
        for pair in zip(valid_inputs.values(), mutated_inputs.values(), strict=True)
        for item in pair
    )
    for fault_input in fault_inputs:
        episode.registry.add(fault_input)
    fault_roster = FrozenFaultRoster.issue(
        episode.authority,
        suite_id="synthetic-phase0-fault-suite",
        candidate_sha256=episode.candidate.content_sha256,
        entries=tuple(
            (category, fault_inputs[index * 2].content_sha256, fault_inputs[index * 2 + 1].content_sha256)
            for index, category in enumerate(FaultCategory)
        ),
    )
    fault_roster_artifact = episode.issuer.issue_fault_roster(fault_roster)
    episode.registry.add(fault_roster_artifact)
    fault_cases = tuple(
        episode.issuer.issue(
            EvidenceKind.FAULT_CASE,
            {
                "category": category.value,
                "fault_roster_sha256": fault_roster_artifact.content_sha256,
                "original_input_sha256": fault_inputs[index * 2].content_sha256,
                "mutated_input_sha256": fault_inputs[index * 2 + 1].content_sha256,
                "expected_failure": {
                    FaultCategory.FUTURE_LEAK: FaultFailureCode.SOURCE_SCHEMA_REJECTED.value,
                    FaultCategory.FORGED_SOURCE: FaultFailureCode.SOURCE_REFERENCE_REJECTED.value,
                    FaultCategory.UNAUTHORIZED_ACTION: FaultFailureCode.ACTION_AUTHORITY_REJECTED.value,
                    FaultCategory.TRADING_REQUEST: FaultFailureCode.NARRATIVE_REJECTED.value,
                }[category],
            },
        )
        for index, category in enumerate(FaultCategory)
    )
    for fault_case in fault_cases:
        episode.registry.add(fault_case)
    missing_input_case = episode.issuer.issue(
        EvidenceKind.FAULT_CASE,
        {
            "category": FaultCategory.FUTURE_LEAK.value,
            "fault_roster_sha256": fault_roster_artifact.content_sha256,
            "original_input_sha256": "0" * 64,
            "mutated_input_sha256": fault_inputs[1].content_sha256,
            "expected_failure": FaultFailureCode.SOURCE_SCHEMA_REJECTED.value,
        },
    )
    with pytest.raises(PermissionError, match="absent"):
        episode.registry.add(missing_input_case)
    evidence = episode.issuer.issue(
        EvidenceKind.EVALUATION_RUN,
        {
            "artifact_sha256s": (
                episode.candidate.content_sha256,
                template.content_sha256,
                agent.content_sha256,
                agent.research_run_sha256,
                agent.synthesis_receipt_sha256,
                agent.experiment_design_receipt_sha256,
                request.content_sha256,
                review.content_sha256,
                review.critic_receipt_sha256,
                outcome.governed.content_sha256,
                always_reject.content_sha256,
                always_defer.content_sha256,
            ),
            "candidate_sha256": episode.candidate.content_sha256,
            "proposal_sha256": agent.proposal_sha256,
            "agent_outcome_sha256": agent.content_sha256,
            "critic_request_sha256": request.content_sha256,
            "runtime_config_sha256s": tuple(
                episode.registry.require_runtime_receipt(value).config_sha256
                for value in (
                    agent.synthesis_receipt_sha256,
                    agent.experiment_design_receipt_sha256,
                    review.critic_receipt_sha256,
                )
            ),
            "runtime_asset_refs": tuple(
                episode.registry.require_runtime_receipt(value).asset_ref.to_dict()
                for value in (
                    agent.synthesis_receipt_sha256,
                    agent.experiment_design_receipt_sha256,
                    review.critic_receipt_sha256,
                )
            ),
            "runtime_owner_bindings": (
                research_run.payload()["synthesis_owner_binding"],
                research_run.payload()["experiment_design_owner_binding"],
                critic_run.payload()["critic_owner_binding"],
            ),
            "workload_ids": tuple(
                episode.registry.require_runtime_receipt(value).workload_id
                for value in (
                    agent.synthesis_receipt_sha256,
                    agent.experiment_design_receipt_sha256,
                    review.critic_receipt_sha256,
                )
            ),
            "fault_roster_sha256": fault_roster_artifact.content_sha256,
            "fault_case_sha256s": tuple(value.content_sha256 for value in fault_cases),
            "fault_input_sha256s": tuple(value.content_sha256 for value in fault_inputs),
            "replay_semantic_sha256": replay,
            "scenario_kind": "FAULT_INJECTION",
        },
    )
    episode.registry.add(evidence)
    evaluator = PhaseZeroEvaluator(episode.authority, episode.critic_authority, episode.registry, episode.binding)
    evaluation = evaluator.evaluate(
        candidate=episode.candidate,
        deterministic_template=template,
        agent_without_critic=agent,
        agent_with_critic=outcome,
        always_reject=always_reject,
        always_defer=always_defer,
        critic_request=request,
        research_run_sha256=research_run.content_sha256,
        evaluation_run_sha256=evidence.content_sha256,
    )
    assert evaluation.accepted is True
    assert evaluation.total_tokens == 204
    assert evaluation.latency_ms == 3
    assert evaluation.evaluation_run_sha256 == evidence.content_sha256
    assert evaluation.fault_roster_sha256 == fault_roster_artifact.content_sha256
    assert evaluation.fault_case_sha256s == tuple(value.content_sha256 for value in fault_cases)
    assert evaluation.fault_input_sha256s == tuple(value.content_sha256 for value in fault_inputs)
    wrong_future_input = episode.issuer.issue(
        EvidenceKind.FAULT_INPUT,
        replace(
            valid_inputs[FaultCategory.FUTURE_LEAK], source_ref=SourceReference("0" * 64, "/records/0/close", "wrong")
        ).to_dict(),
    )
    episode.registry.add(wrong_future_input)
    wrong_entries = tuple(
        (
            category,
            fault_inputs[index * 2].content_sha256,
            wrong_future_input.content_sha256
            if category is FaultCategory.FUTURE_LEAK
            else fault_inputs[index * 2 + 1].content_sha256,
        )
        for index, category in enumerate(FaultCategory)
    )
    wrong_roster = FrozenFaultRoster.issue(
        episode.authority,
        suite_id="wrong-category-delta-suite",
        candidate_sha256=episode.candidate.content_sha256,
        entries=wrong_entries,
    )
    wrong_roster_artifact = episode.issuer.issue_fault_roster(wrong_roster)
    episode.registry.add(wrong_roster_artifact)
    same_suite_replacement = FrozenFaultRoster.issue(
        episode.authority,
        suite_id=fault_roster.suite_id,
        candidate_sha256=episode.candidate.content_sha256,
        entries=wrong_entries,
    )
    with pytest.raises(ValueError, match="cannot be re-signed"):
        episode.registry.add(episode.issuer.issue_fault_roster(same_suite_replacement))
    wrong_cases = tuple(
        episode.issuer.issue(
            EvidenceKind.FAULT_CASE,
            {
                "category": category.value,
                "fault_roster_sha256": wrong_roster_artifact.content_sha256,
                "original_input_sha256": original,
                "mutated_input_sha256": mutated,
                "expected_failure": {
                    FaultCategory.FUTURE_LEAK: FaultFailureCode.SOURCE_SCHEMA_REJECTED.value,
                    FaultCategory.FORGED_SOURCE: FaultFailureCode.SOURCE_REFERENCE_REJECTED.value,
                    FaultCategory.UNAUTHORIZED_ACTION: FaultFailureCode.ACTION_AUTHORITY_REJECTED.value,
                    FaultCategory.TRADING_REQUEST: FaultFailureCode.NARRATIVE_REJECTED.value,
                }[category],
            },
        )
        for category, original, mutated in wrong_entries
    )
    for case in wrong_cases:
        episode.registry.add(case)
    wrong_category_evaluation = episode.issuer.issue(
        EvidenceKind.EVALUATION_RUN,
        {
            **evidence.payload(),
            "fault_roster_sha256": wrong_roster_artifact.content_sha256,
            "fault_case_sha256s": tuple(value.content_sha256 for value in wrong_cases),
            "fault_input_sha256s": tuple(value.content_sha256 for value in (*fault_inputs, wrong_future_input)),
        },
    )
    episode.registry.add(wrong_category_evaluation)
    wrong_category_result = evaluator.evaluate(
        candidate=episode.candidate,
        deterministic_template=template,
        agent_without_critic=agent,
        agent_with_critic=outcome,
        always_reject=always_reject,
        always_defer=always_defer,
        critic_request=request,
        research_run_sha256=research_run.content_sha256,
        evaluation_run_sha256=wrong_category_evaluation.content_sha256,
    )
    assert "FAULT_REPLAY_RECALL_FAILED" in wrong_category_result.critical_failures
    assert wrong_category_result.injected_fault_count == 4 and wrong_category_result.recalled_fault_count == 3
    duplicate_category_cases = episode.issuer.issue(
        EvidenceKind.EVALUATION_RUN,
        {
            **evidence.payload(),
            "fault_case_sha256s": (
                fault_cases[0].content_sha256,
                fault_cases[0].content_sha256,
                fault_cases[2].content_sha256,
                fault_cases[3].content_sha256,
            ),
        },
    )
    episode.registry.add(duplicate_category_cases)
    assert (
        "FAULT_CASE_ROSTER_INVALID"
        in evaluator.evaluate(
            candidate=episode.candidate,
            deterministic_template=template,
            agent_without_critic=agent,
            agent_with_critic=outcome,
            always_reject=always_reject,
            always_defer=always_defer,
            critic_request=request,
            research_run_sha256=research_run.content_sha256,
            evaluation_run_sha256=duplicate_category_cases.content_sha256,
        ).critical_failures
    )
    clean = episode.issuer.issue(
        EvidenceKind.EVALUATION_RUN,
        {**evidence.payload(), "scenario_kind": "CLEAN", "fault_case_sha256s": (), "fault_input_sha256s": ()},
    )
    episode.registry.add(clean)
    assert (
        evaluator.evaluate(
            candidate=episode.candidate,
            deterministic_template=template,
            agent_without_critic=agent,
            agent_with_critic=outcome,
            always_reject=always_reject,
            always_defer=always_defer,
            critic_request=request,
            research_run_sha256=research_run.content_sha256,
            evaluation_run_sha256=clean.content_sha256,
        ).accepted
        is True
    )
    clean_with_fake_recall = episode.issuer.issue(
        EvidenceKind.EVALUATION_RUN,
        {**evidence.payload(), "scenario_kind": "CLEAN"},
    )
    episode.registry.add(clean_with_fake_recall)
    assert (
        "CLEAN_SCENARIO_HAS_FAULTS"
        in evaluator.evaluate(
            candidate=episode.candidate,
            deterministic_template=template,
            agent_without_critic=agent,
            agent_with_critic=outcome,
            always_reject=always_reject,
            always_defer=always_defer,
            critic_request=request,
            research_run_sha256=research_run.content_sha256,
            evaluation_run_sha256=clean_with_fake_recall.content_sha256,
        ).critical_failures
    )
    low_usage_replacement = episode.issuer.issue(
        EvidenceKind.RESEARCH_RUN,
        {**research_run.payload(), "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
    )
    with pytest.raises(ValueError, match="append-only semantic run"):
        episode.registry.add(low_usage_replacement)
    second_invocation = ResearchInvocationAuthorization.issue(
        episode.authority,
        candidate_sha256=episode.candidate.content_sha256,
        request_sha256=agent.proposal_sha256,
        profile_sha256=episode.profile.content_sha256,
        prompt_sha256=episode.prompt.content_sha256,
        schema_sha256=episode.schema.content_sha256,
        toolset_sha256=episode.candidate.evidence.toolset_sha256,
        runtime_sha256=episode.candidate.evidence.runtime_sha256,
        invocation_id="resigned-low-usage-invocation",
    )
    second_invocation_artifact = episode.issuer.issue_research_invocation(second_invocation)
    episode.registry.add(second_invocation_artifact)
    resigned_low_run = episode.issuer.issue(
        EvidenceKind.RESEARCH_RUN,
        {
            **research_run.payload(),
            "invocation_authorization_sha256": second_invocation_artifact.content_sha256,
            "invocation_id": second_invocation.invocation_id,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
    )
    with pytest.raises((ValueError, PermissionError), match="append-only semantic run|receipt lineage"):
        episode.registry.add(resigned_low_run)
    assert (
        verify_agent_critic_outcome(
            episode.candidate, outcome, episode.authority, episode.critic_authority, episode.registry
        )[3]
        == outcome.governed
    )
    report = render_chinese_report(
        episode.candidate, outcome, episode.authority, episode.critic_authority, episode.registry
    )
    assert "REJECT_AS_UNSUPPORTED" in report and "下一实验：NOT_REQUESTED" in report
    assert episode.candidate.component_id in report and episode.candidate.available_data_range[0] in report
    for source in episode.candidate.sources:
        assert source.artifact_sha256 in report and source.json_pointer in report
    for screen in episode.candidate.screens:
        assert screen.family.value in report
    template_report = render_deterministic_template_chinese_report(
        episode.candidate, template, episode.authority, episode.registry
    )
    assert "确定性模板研究简报" in template_report and episode.candidate.sources[0].artifact_sha256 in template_report
    for field in (
        episode.candidate.unknowns[0],
        episode.candidate.instrument_id,
        episode.candidate.as_of,
        episode.candidate.market_cutoff,
        episode.candidate.acquired_at,
        episode.candidate.component_id,
        episode.candidate.warnings[0],
        template.next_experiment.research_question,
        template.next_experiment.primary_change,
        episode.binding.window_start,
        episode.binding.train_end,
        episode.binding.validation_end,
        episode.binding.test_end,
        str(episode.binding.embargo_bars),
        episode.binding.baseline,
        episode.binding.control,
        episode.binding.primary_metric,
        episode.binding.stop_rule,
        episode.binding.failure_disposition,
        episode.binding.bias_checks[0],
        episode.binding.cost_sha256,
        episode.binding.reproduction_sha256,
    ):
        assert field in template_report
    with pytest.raises(PermissionError, match="does not bind its exact runtime receipt"):
        episode.registry.add(
            episode.issuer.issue(
                EvidenceKind.CRITIC_RUN,
                {**critic_run.payload(), "decision": CriticDecision.PASS.value},
            )
        )
    with pytest.raises(PermissionError, match="does not bind its exact runtime receipt"):
        episode.registry.add(
            episode.issuer.issue(
                EvidenceKind.CRITIC_RUN,
                {
                    **critic_run.payload(),
                    "critic_output_sha256": research_run.payload()["synthesis_output_sha256"],
                },
            )
        )
    pass_episode = _episode()
    _pass_runner, _pass_critic, _pass_agent, _pass_request, _pass_run, _pass_review, pass_outcome, _ = _critic_outcome(
        pass_episode, CriticDecision.PASS
    )
    pass_report = render_chinese_report(
        pass_episode.candidate,
        pass_outcome,
        pass_episode.authority,
        pass_episode.critic_authority,
        pass_episode.registry,
    )
    for field in (
        pass_outcome.governed.next_experiment.research_question,
        pass_outcome.governed.next_experiment.primary_change,
        episode.binding.window_start,
        episode.binding.stop_rule,
        episode.binding.failure_disposition,
        episode.binding.bias_checks[0],
        episode.binding.cost_sha256,
        episode.binding.reproduction_sha256,
    ):
        assert field in pass_report
    with pytest.raises(ValueError, match="bounded direction"):
        HypothesisFamilyScreen(
            HypothesisFamily.MOMENTUM_CONTINUATION, True, 1, Decimal(0), Decimal(0), Decimal(0), Decimal(0)
        )
    with pytest.raises(ValueError, match="bounded direction"):
        HypothesisFamilyScreen(
            HypothesisFamily.MOMENTUM_CONTINUATION, 1, True, Decimal(0), Decimal(0), Decimal(0), Decimal(0)
        )


def test_production_shaped_three_workload_orchestrator_e2e_is_atomic_and_exact() -> None:
    from test_mvp_r_002_runtime_adapter_contracts import _assets, _response

    from futures_agent_os.research_experiment.mvp_r_002_runtime import MvpR002PhaseZeroOrchestrator

    episode = _episode()
    assets, _equivalent_authority, _empty_registry = _assets()
    issuer = OwnerEvidenceIssuer(episode.authority, "synthetic-runtime-owner")

    def owner_binding(workload_id: str):
        asset = assets.assets.for_workload(workload_id)
        profile = issuer.issue_profile(
            FrozenProfileQualification(
                "openai",
                asset.config.model_id,
                f"{workload_id}.profile",
                workload_id,
                asset.config.profile_sha256,
                "FROZEN",
            )
        )
        prompt = issuer.issue(EvidenceKind.PROMPT, {"workload_id": workload_id, "asset_sha256": asset.prompt_sha256})
        schema = issuer.issue(EvidenceKind.SCHEMA, {"workload_id": workload_id, "asset_sha256": asset.schema_sha256})
        toolset = issuer.issue(EvidenceKind.TOOLSET, {"workload_id": workload_id, "asset_sha256": canonical_sha256(())})
        runtime = issuer.issue(EvidenceKind.RUNTIME, {"workload_id": workload_id, "asset_sha256": asset.runtime_sha256})
        for artifact in (profile, prompt, schema, toolset, runtime):
            episode.registry.add(artifact)
        return (
            assets.bind_owner(
                episode.registry,
                workload_id=workload_id,
                profile_sha256=profile.content_sha256,
                prompt_sha256=prompt.content_sha256,
                schema_sha256=schema.content_sha256,
                toolset_sha256=toolset.content_sha256,
                runtime_sha256=runtime.content_sha256,
            ),
            (profile, prompt, schema, toolset, runtime),
        )

    synthesis_binding, synthesis_artifacts = owner_binding("research.hypothesis_synthesis")
    experiment_binding, _experiment_artifacts = owner_binding("experiment.preregistration_design")
    critic_binding, _critic_artifacts = owner_binding("assurance.adversarial_critique")
    with pytest.raises((TypeError, PermissionError)):
        RuntimeOwnerBinding(
            synthesis_binding.workload_id,
            synthesis_binding.asset_ref,
            synthesis_binding.profile_ref,
            synthesis_binding.prompt_ref,
            synthesis_binding.schema_ref,
            synthesis_binding.toolset_ref,
            synthesis_binding.runtime_ref,
        )  # type: ignore[call-arg]
    forged_payload = synthesis_binding.to_dict()
    forged_payload["profile_ref"] = {
        **synthesis_binding.profile_ref.to_dict(),
        "asset_sha256": "f" * 64,
    }
    forged_binding = RuntimeOwnerBinding.hydrate(forged_payload)
    with pytest.raises(PermissionError, match="exact frozen inner bytes"):
        assets.verify_owner_binding(
            episode.registry,
            forged_binding,
            workload_id="research.hypothesis_synthesis",
        )
    crossed_prompt = issuer.issue(
        EvidenceKind.PROMPT,
        {
            "workload_id": "research.hypothesis_synthesis",
            "asset_sha256": assets.assets.independent_critic.prompt_sha256,
        },
    )
    episode.registry.add(crossed_prompt)
    with pytest.raises(PermissionError, match="exact workload asset bytes"):
        assets.bind_owner(
            episode.registry,
            workload_id="research.hypothesis_synthesis",
            profile_sha256=synthesis_artifacts[0].content_sha256,
            prompt_sha256=crossed_prompt.content_sha256,
            schema_sha256=synthesis_artifacts[2].content_sha256,
            toolset_sha256=synthesis_artifacts[3].content_sha256,
            runtime_sha256=synthesis_artifacts[4].content_sha256,
        )
    candidate = ResearchCandidateFactory(episode.authority, episode.registry).issue(
        replace(
            episode.candidate.evidence,
            toolset_sha256=synthesis_artifacts[3].content_sha256,
            runtime_sha256=synthesis_artifacts[4].content_sha256,
        )
    )
    domain_binding = replace(
        episode.binding,
        profile_sha256=synthesis_artifacts[0].content_sha256,
        prompt_sha256=synthesis_artifacts[1].content_sha256,
        schema_sha256=synthesis_artifacts[2].content_sha256,
    )
    proposal = _proposal(candidate, ResearchAction.TEST_NEXT)

    class SequencePort:
        def __init__(self) -> None:
            self.responses = [
                _response(_research_wire(proposal), reasoning_effort="medium", response_id="synthesis-e2e"),
                _response(
                    {"design_category": "USE_FROZEN_BINDING"},
                    reasoning_effort="medium",
                    response_id="experiment-e2e",
                ),
                _response(
                    {
                        "decision": CriticDecision.PASS.value,
                        "reason_category": NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN.value,
                    },
                    reasoning_effort="high",
                    response_id="critic-e2e",
                ),
            ]

        def __call__(self, _payload):
            return self.responses.pop(0)

    port = SequencePort()
    with pytest.raises(PermissionError, match="workload is not exact"):
        MvpR002PhaseZeroOrchestrator.create(
            port,
            episode.authority,
            episode.critic_authority,
            episode.registry,
            assets,
            domain_binding,
            synthesis_binding,
            synthesis_binding,
            critic_binding,
        )
    assert len(port.responses) == 3
    orchestrator = MvpR002PhaseZeroOrchestrator.create(
        port,
        episode.authority,
        episode.critic_authority,
        episode.registry,
        assets,
        domain_binding,
        synthesis_binding,
        experiment_binding,
        critic_binding,
    )
    import futures_agent_os.research_experiment.mvp_r_002_runtime as runtime_module
    import futures_agent_os.adapters as adapters

    assert not hasattr(runtime_module, "_MvpR002RuntimeExecutor")
    assert not hasattr(adapters, "CodexAppServerProvider")
    assert not hasattr(orchestrator, "__dict__")
    assert all(
        marker not in name.lower()
        for name in dir(orchestrator)
        for marker in ("executor", "issuer", "lease", "port", "assets", "runtime")
    )
    assert len(port.responses) == 3
    blocked_authorization = ResearchInvocationAuthorization.issue(
        episode.authority,
        candidate_sha256=candidate.content_sha256,
        request_sha256=proposal.content_sha256,
        profile_sha256=synthesis_binding.profile_sha256,
        prompt_sha256=synthesis_binding.prompt_sha256,
        schema_sha256=synthesis_binding.schema_sha256,
        toolset_sha256=synthesis_binding.toolset_sha256,
        runtime_sha256=synthesis_binding.runtime_sha256,
        invocation_id="synthesis-atomic-blocked",
    )
    episode.registry.add(issuer.issue_research_invocation(blocked_authorization))
    successful_responses = list(port.responses)
    for attempt in range(2):
        port.responses = [
            _response(
                _research_wire(proposal),
                reasoning_effort="medium",
                response_id="synthesis-atomic-retry",
            ),
            _response(
                {"design_category": "USE_FROZEN_BINDING"},
                reasoning_effort="medium",
                response_id="experiment-atomic-retry",
            ),
        ]
        # The same exact completed receipts reach the already-registered
        # authorization on both attempts.  If the first failed batch leaked an
        # orphan receipt, the second attempt would fail earlier as a receipt
        # replay instead of at the unchanged authorization artifact.
        with pytest.raises(ValueError, match="owner evidence cannot be duplicated"):
            orchestrator.run_research(
                candidate,
                synthesis_invocation_id="synthesis-atomic-blocked",
                experiment_invocation_id=f"experiment-atomic-blocked-{attempt}",
            )
    port.responses = successful_responses
    agent = orchestrator.run_research(
        candidate,
        synthesis_invocation_id="synthesis-e2e",
        experiment_invocation_id="experiment-e2e",
    )
    governed = orchestrator.run_critic(candidate, agent, run_id="critic-e2e")
    assert governed.critic.decision is CriticDecision.PASS
    synthesis_receipt = episode.registry.require_runtime_receipt(agent.synthesis_receipt_sha256)
    experiment_receipt = episode.registry.require_runtime_receipt(agent.experiment_design_receipt_sha256)
    critic_receipt = episode.registry.require_runtime_receipt(governed.critic.critic_receipt_sha256)
    assert tuple(receipt.workload_id for receipt in (synthesis_receipt, experiment_receipt, critic_receipt)) == (
        "research.hypothesis_synthesis",
        "experiment.preregistration_design",
        "assurance.adversarial_critique",
    )
    assert critic_receipt.run_id == "critic-e2e"
    assert port.responses == []
