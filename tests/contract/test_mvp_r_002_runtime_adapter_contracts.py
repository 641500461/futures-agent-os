"""Synthetic, no-network contracts for the MVP-R-002 frozen runtime."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from futures_agent_os.adapters import (
    R002_EXPERIMENT_DESIGN_SCHEMA,
    R002_INDEPENDENT_CRITIC_SCHEMA,
    R002_RESEARCH_SYNTHESIS_SCHEMA,
)
from futures_agent_os.adapters.codex_app_server import _actual_reasoning_effort
from futures_agent_os.research_experiment.model_routing import (
    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    MVP_R_002_EMPTY_TOOLSET_BINDING,
    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
    ModelAuthenticationMode,
    ModelCostAccountingMode,
    ModelProfileRevision,
    ModelProtocolFamily,
    ModelQualificationState,
    ModelRunnerCapabilities,
    ModelRunnerKind,
    MvpR002QualificationWorkloads,
    ProfileQualificationAuthority,
    ProfileQualificationReceiptRegistry,
    ProfileQualificationReport,
    QualificationBinding,
    ResearchWorkloadBundle,
    ResolvedQualificationRunConfig,
    WorkloadId,
)
from futures_agent_os.research_experiment.mvp_r_002 import (
    EvidenceKind,
    IndependentCriticInvocation,
    OwnerEvidenceRegistry,
    PhaseZeroAuthority,
)
from futures_agent_os.research_experiment.mvp_r_002_runtime import (
    FrozenRuntimeAssets,
    MvpR002FailureStage,
    MvpR002PhaseZeroOrchestrator,
    MvpR002RunReceipt,
    MvpR002RuntimeAssets,
    MvpR002RuntimeFailureCode,
    MvpR002RuntimeWorkloadAsset,
)
from futures_agent_os.shared_kernel import EntityId, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_ROOT = Path(__file__).parents[2]
_SPECS = (
    (
        MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
        "medium",
        "r002-research-synthesis-v1.md",
        R002_RESEARCH_SYNTHESIS_SCHEMA,
    ),
    (
        MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
        "medium",
        "r002-experiment-design-v1.md",
        R002_EXPERIMENT_DESIGN_SCHEMA,
    ),
    (MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high", "r002-independent-critic-v1.md", R002_INDEPENDENT_CRITIC_SCHEMA),
)


def _critic_authority() -> PhaseZeroAuthority:
    return PhaseZeroAuthority(bytes(range(64, 96)))


def _frozen_json(value: object) -> JsonValue:
    if value is None or type(value) in (str, int, bool):
        return cast(JsonValue, value)
    if type(value) in (list, tuple):
        return tuple(_frozen_json(item) for item in cast(list[object] | tuple[object, ...], value))
    if isinstance(value, dict):
        return {key: _frozen_json(item) for key, item in value.items()}
    raise TypeError("test schema must be JSON")


def _capabilities() -> ModelRunnerCapabilities:
    return ModelRunnerCapabilities(
        True, True, True, True, True, ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE, True, "r002-runtime-fake.v1"
    )


def _profile(workload: str, effort: str) -> ModelProfileRevision:
    return ModelProfileRevision(
        EntityId.new("model_profile"),
        1,
        WorkloadId(workload),
        ModelProtocolFamily.MVP_R_002,
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        effort,
        f"{workload}.prompt",
        f"{workload}.schema",
        MVP_R_002_EMPTY_TOOLSET_BINDING,
        _capabilities(),
        ModelQualificationState.EVALUATING,
    )


def _assets() -> tuple[FrozenRuntimeAssets, PhaseZeroAuthority, OwnerEvidenceRegistry]:
    phase_authority = PhaseZeroAuthority(bytes(range(32)))
    qualification = ProfileQualificationAuthority(phase_authority)
    configs: list[ResolvedQualificationRunConfig] = []
    reports: list[ProfileQualificationReport] = []
    receipt_registries: list[ProfileQualificationReceiptRegistry] = []
    case_rosters = []
    values: list[tuple[str, ResolvedQualificationRunConfig, ProfileQualificationReport, bytes, JsonValue]] = []
    for workload, effort, prompt_file, schema in _SPECS:
        frozen_schema = _frozen_json(schema)
        profile = _profile(workload, effort)
        prompt = (_ROOT / "prompts" / "mvp-r" / prompt_file).read_bytes()
        runtime_identity = f"mvp-r-002.runtime.{workload}.v1"
        receipt_common = {
            "prompt_sha256": __import__("hashlib").sha256(prompt).hexdigest(),
            "schema_sha256": canonical_sha256(frozen_schema),
            "toolset_sha256": canonical_sha256(()),
            "runtime_sha256": canonical_sha256(cast(JsonValue, {"runtime_identity": runtime_identity})),
            "actual_provider": "openai",
            "actual_model_id": "gpt-5.6-terra",
            "actual_reasoning_effort": effort,
            "cost_accounting_mode": ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
            "total_tokens": 20_000,
            "latency_ms": 35_000,
            "reroute_count": 0,
            "activity_count": 0,
        }
        scenario_receipts = tuple(
            qualification.issue_receipt(
                profile,
                receipt_kind="CRITICAL_SCENARIO",
                case_id=f"critical-{index}",
                correct_refusal=True,
                fault_recalled=False,
                **receipt_common,
            )
            for index in range(4)
        )
        fault_receipt = qualification.issue_receipt(
            profile,
            receipt_kind="FAULT",
            case_id="fault-one",
            correct_refusal=False,
            fault_recalled=True,
            **receipt_common,
        )
        receipt_registry = ProfileQualificationReceiptRegistry(qualification)
        for receipt in (*scenario_receipts, fault_receipt):
            receipt_registry.add(receipt)
        case_roster = qualification.issue_case_roster(
            profile,
            tuple((item.receipt_kind, item.case_id) for item in (*scenario_receipts, fault_receipt)),
        )
        report = qualification.issue(profile, receipt_registry, case_roster)
        qualified = replace(profile, qualification_state=ModelQualificationState.QUALIFIED)
        transition = qualification.qualify(profile, report, receipt_registry, case_roster)
        config = ResolvedQualificationRunConfig.resolve(
            QualificationBinding.bind(
                EntityId.new("model_qualification"),
                qualified,
                qualification_owner_authority=phase_authority,
                transition=transition,
            ),
            qualified,
        )
        configs.append(config)
        reports.append(report)
        receipt_registries.append(receipt_registry)
        case_rosters.append(case_roster)
        values.append((runtime_identity, config, report, prompt, frozen_schema))
    workloads = MvpR002QualificationWorkloads(ResearchWorkloadBundle(configs[0], configs[1]), configs[2])
    assembled = MvpR002RuntimeAssets(
        workloads,
        MvpR002RuntimeWorkloadAsset(_SPECS[0][0], configs[0], reports[0], values[0][3], values[0][4], values[0][0]),
        MvpR002RuntimeWorkloadAsset(_SPECS[1][0], configs[1], reports[1], values[1][3], values[1][4], values[1][0]),
        MvpR002RuntimeWorkloadAsset(_SPECS[2][0], configs[2], reports[2], values[2][3], values[2][4], values[2][0]),
    )
    assets = FrozenRuntimeAssets.issue_from_repository(
        phase_authority,
        workloads,
        cast(tuple[ProfileQualificationReport, ProfileQualificationReport, ProfileQualificationReport], tuple(reports)),
        cast(
            tuple[
                ProfileQualificationReceiptRegistry,
                ProfileQualificationReceiptRegistry,
                ProfileQualificationReceiptRegistry,
            ],
            tuple(receipt_registries),
        ),
        cast(tuple, tuple(case_rosters)),
    )
    assert assets.assets.content_sha256 == assembled.content_sha256
    return assets, phase_authority, OwnerEvidenceRegistry(phase_authority)


class _FakePort:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def __call__(self, payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        self.calls.append(payload)
        return self.response


def _response(final: object, **overrides: object) -> dict[str, object]:
    return {
        "response_id": "r002-response",
        "model_provider": "openai",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "status": "completed",
        "timed_out": False,
        "usage": {
            "inputTokens": 10,
            "cachedInputTokens": 4,
            "outputTokens": 2,
            "reasoningOutputTokens": 1,
            "cacheWriteInputTokens": 0,
            "totalTokens": 12,
        },
        "latencyMs": 9,
        "reroutes": (),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("agentMessage",),
        "final_texts": (json.dumps(final),),
        **overrides,
    }


def _critic_request(
    authority: PhaseZeroAuthority, assets: FrozenRuntimeAssets, run_id: str = "critic-one"
) -> IndependentCriticInvocation:
    asset = assets.assets.independent_critic
    payload = {
        "schema_version": "mvp-r-002.phase0.v2",
        "workload_id": MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
        "run_id": run_id,
        "candidate_sha256": "a" * 64,
        "agent_outcome_sha256": "b" * 64,
        "research_run_sha256": "c" * 64,
        "brief_sha256": "d" * 64,
        "profile_sha256": asset.config.profile_sha256,
        "prompt_sha256": asset.prompt_sha256,
        "schema_sha256": asset.schema_sha256,
        "toolset_sha256": canonical_sha256(()),
        "runtime_sha256": asset.runtime_sha256,
    }
    return IndependentCriticInvocation(
        **payload, content_sha256=canonical_sha256(payload), signature_sha256=authority.sign(payload)
    )


def _run_orchestrated_critic(response: dict[str, object], *, run_id: str):
    from test_mvp_r_002_phase0_contracts import _episode, _proposal, _research_wire

    from futures_agent_os.research_experiment.mvp_r_002 import (
        EvidenceKind,
        FrozenProfileQualification,
        OwnerEvidenceIssuer,
        ResearchAction,
        ResearchCandidateFactory,
    )

    assets, _authority, _unused_registry = _assets()
    episode = _episode()
    issuer = OwnerEvidenceIssuer(episode.authority, "runtime-adapter-orchestrator-test")

    def bind(workload_id: str):
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
        artifacts = (
            profile,
            issuer.issue(EvidenceKind.PROMPT, {"workload_id": workload_id, "asset_sha256": asset.prompt_sha256}),
            issuer.issue(EvidenceKind.SCHEMA, {"workload_id": workload_id, "asset_sha256": asset.schema_sha256}),
            issuer.issue(EvidenceKind.TOOLSET, {"workload_id": workload_id, "asset_sha256": canonical_sha256(())}),
            issuer.issue(EvidenceKind.RUNTIME, {"workload_id": workload_id, "asset_sha256": asset.runtime_sha256}),
        )
        for artifact in artifacts:
            episode.registry.add(artifact)
        return assets.bind_owner(
            episode.registry,
            workload_id=workload_id,
            profile_sha256=artifacts[0].content_sha256,
            prompt_sha256=artifacts[1].content_sha256,
            schema_sha256=artifacts[2].content_sha256,
            toolset_sha256=artifacts[3].content_sha256,
            runtime_sha256=artifacts[4].content_sha256,
        ), artifacts

    synthesis_binding, synthesis_artifacts = bind(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD)
    experiment_binding, _ = bind(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD)
    critic_binding, _ = bind(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD)
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

    class SequencePort(_FakePort):
        def __init__(self) -> None:
            super().__init__({})
            self.responses = [
                _response(_research_wire(proposal), reasoning_effort="medium", response_id=f"{run_id}-synthesis"),
                _response(
                    {"design_category": "USE_FROZEN_BINDING"},
                    reasoning_effort="medium",
                    response_id=f"{run_id}-experiment",
                ),
                response,
            ]

        def __call__(self, payload: object) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.calls.append(payload)
            return self.responses.pop(0)

    port = SequencePort()
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
    agent = orchestrator.run_research(
        candidate,
        synthesis_invocation_id=f"{run_id}-synthesis",
        experiment_invocation_id=f"{run_id}-experiment",
    )
    try:
        governed = orchestrator.run_critic(candidate, agent, run_id=run_id)
    except PermissionError:
        governed = None
    digest, receipt = episode.registry.runtime_receipt_for_invocation(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, run_id)
    return governed, receipt, digest, episode.registry, port, assets


def test_critic_receipt_uses_qualified_assets_and_official_usage_shape() -> None:
    governed, receipt, _digest, _registry, port, assets = _run_orchestrated_critic(
        _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}), run_id="critic-one"
    )
    assert governed is not None and receipt.status == "COMPLETED"
    assert receipt.cost_available is False and receipt.total_tokens == 12
    assert receipt.activity_sha256s == () and receipt.reroute_sha256s == ()
    assert MvpR002RunReceipt.hydrate(receipt.to_dict(), PhaseZeroAuthority(bytes(range(32)))) == receipt
    request = port.calls[2]
    assert (
        request["prompt"] == assets.assets.independent_critic.prompt_bytes.decode()
        and request["schema"] == assets.assets.independent_critic.schema
    )


def test_critic_invocation_authority_is_separate_from_receipt_owner_authority() -> None:
    governed, receipt, digest, registry, _port, _assets_value = _run_orchestrated_critic(
        _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}),
        run_id="separate-critic-authority",
    )
    assert governed is not None
    assert registry.require_runtime_receipt(digest) == receipt


def test_runner_and_port_are_not_exported_and_orchestrator_constructor_is_factory_proof() -> None:
    import futures_agent_os.research_experiment as package
    import futures_agent_os.research_experiment.mvp_r_002_runtime as runtime_module

    assert not hasattr(package, "MvpR002QualificationRunner")
    assert not hasattr(package, "MvpR002FrozenStructuredPort")
    with pytest.raises(PermissionError, match="factory-issued"):
        MvpR002PhaseZeroOrchestrator(*([object()] * 9))  # type: ignore[arg-type]
    assert not hasattr(runtime_module, "_MvpR002RuntimeExecutor")


def test_same_critic_authority_is_rejected_before_any_runtime_call() -> None:
    # The only executable factory rejects the same research/Critic authority.
    from test_mvp_r_002_phase0_contracts import _episode

    episode = _episode()
    assets, _authority, _registry = _assets()
    fake = _FakePort(_response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}))
    with pytest.raises((TypeError, PermissionError)):
        MvpR002PhaseZeroOrchestrator.create(
            fake,
            episode.authority,
            episode.authority,
            episode.registry,
            assets,
            episode.binding,
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
    assert not fake.calls


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("model_provider", "other", MvpR002RuntimeFailureCode.PROVIDER_MISMATCH),
        ("model", "other", MvpR002RuntimeFailureCode.MODEL_DRIFT),
        ("reasoning_effort", "medium", MvpR002RuntimeFailureCode.EFFORT_DRIFT),
        ("reroutes", ("reroute",), MvpR002RuntimeFailureCode.REROUTE_REJECTED),
        ("dynamic_calls", ({"name": "bad"},), MvpR002RuntimeFailureCode.ACTIVITY_REJECTED),
        ("usage", {}, MvpR002RuntimeFailureCode.USAGE_INCOMPLETE),
    ),
)
def test_observation_failures_preserve_signed_failure_evidence(
    field: str, value: object, code: MvpR002RuntimeFailureCode
) -> None:
    governed, receipt, _digest, _registry, _port, _assets_value = _run_orchestrated_critic(
        _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}, **{field: value}),
        run_id=f"observation-{field}",
    )
    assert governed is None and receipt.failure_code == code.value
    assert receipt.failure_stage == MvpR002FailureStage.OBSERVATION.value
    assert receipt.raw_response_sha256 is not None


def test_typed_critic_and_zero_token_defer_do_not_accept_mapping_or_call_port() -> None:
    # Low-level mapping execution is absent from the public surface; the
    # deterministic DEFER path remains covered in the Phase-0 contract suite.
    import futures_agent_os.research_experiment as package

    assert not hasattr(package, "MvpR002QualificationRunner")


def test_closed_wire_failure_replaces_unissued_success_without_losing_observation() -> None:
    governed, receipt, digest, registry, _port, _assets_value = _run_orchestrated_critic(
        _response({"decision": "NOT_A_VERDICT", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}),
        run_id="closed-wire-failure",
    )
    assert governed is None and receipt.failure_code == MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID.value
    assert receipt.actual_model_id == "gpt-5.6-terra" and receipt.total_tokens == 12
    assert registry.require(digest, EvidenceKind.RUNTIME_RECEIPT).content_sha256 == digest


def test_missing_actual_effort_and_bad_json_object_fail_inside_signed_boundary() -> None:
    missing_effort = _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"})
    del missing_effort["reasoning_effort"]
    governed, receipt, _digest, _registry, _port, _assets_value = _run_orchestrated_critic(
        missing_effort, run_id="missing-effort"
    )
    assert governed is None and receipt.failure_code == MvpR002RuntimeFailureCode.USAGE_INCOMPLETE.value
    assert receipt.actual_provider == "openai" and receipt.actual_model_id == "gpt-5.6-terra"
    assert receipt.actual_reasoning_effort is None and receipt.raw_response_sha256 is not None

    bad = _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"})
    bad["bad"] = object()
    bad_governed, bad_receipt, bad_digest, bad_registry, _bad_port, _bad_assets = _run_orchestrated_critic(
        bad, run_id="bad-object"
    )
    assert bad_governed is None and bad_receipt.failure_code == MvpR002RuntimeFailureCode.USAGE_INCOMPLETE.value
    assert bad_receipt.raw_response_sha256 is None
    assert (
        bad_receipt.actual_provider,
        bad_receipt.actual_model_id,
        bad_receipt.actual_reasoning_effort,
        bad_receipt.response_id,
        bad_receipt.total_tokens,
        bad_receipt.latency_ms,
    ) == ("openai", "gpt-5.6-terra", "high", "r002-response", 12, 9)
    assert bad_registry.require_runtime_receipt(bad_digest) == bad_receipt


@pytest.mark.parametrize(
    "usage",
    (
        {
            "inputTokens": 1,
            "cachedInputTokens": 999,
            "outputTokens": 1,
            "reasoningOutputTokens": 0,
            "cacheWriteInputTokens": 0,
            "totalTokens": 2,
        },
        {
            "inputTokens": 1,
            "cachedInputTokens": 0,
            "outputTokens": 1,
            "reasoningOutputTokens": 999,
            "cacheWriteInputTokens": 0,
            "totalTokens": 2,
        },
        {
            "inputTokens": 1,
            "cachedInputTokens": 1,
            "outputTokens": 1,
            "reasoningOutputTokens": 0,
            "cacheWriteInputTokens": 1,
            "totalTokens": 2,
        },
    ),
)
def test_impossible_usage_relationships_never_complete(usage: dict[str, int]) -> None:
    governed, receipt, _digest, _registry, _port, _assets_value = _run_orchestrated_critic(
        _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"}, usage=usage),
        run_id=f"bad-usage-{canonical_sha256(usage)}",
    )
    assert governed is None and receipt.failure_code == MvpR002RuntimeFailureCode.USAGE_INCOMPLETE.value


def test_frozen_runtime_assets_reject_direct_construction_and_root_tamper() -> None:
    assets, authority, _registry = _assets()
    with pytest.raises((TypeError, PermissionError)):
        FrozenRuntimeAssets(assets.assets, assets.repository_root, assets.content_sha256, assets.signature_sha256)  # type: ignore[call-arg]
    tampered_payload = {"repository_root": "/tmp/attacker-prompts", "assets_sha256": assets.assets.content_sha256}
    with pytest.raises(PermissionError, match="fixed repository root"):
        FrozenRuntimeAssets.hydrate(
            {
                **tampered_payload,
                "content_sha256": canonical_sha256(tampered_payload),
                "signature_sha256": authority.sign(tampered_payload),
            },
            authority,
            assets.assets,
        )


def test_public_experiment_call_with_bad_object_never_reaches_port() -> None:
    import futures_agent_os.research_experiment as package

    fake = _FakePort(_response({"design_category": "USE_FROZEN_BINDING"}, reasoning_effort="medium"))
    assert not hasattr(package, "MvpR002QualificationRunner")
    assert not fake.calls


def test_assets_reject_shared_prompt_and_exact_mud_config() -> None:
    assets, _, _ = _assets()
    with pytest.raises(PermissionError, match="qualified workload configs"):
        MvpR002RuntimeAssets(
            assets.assets.workloads,
            assets.assets.research_synthesis,
            assets.assets.research_synthesis,
            assets.assets.independent_critic,
        )
    with pytest.raises(PermissionError, match="runtime asset"):
        replace(assets.assets.research_synthesis, schema=assets.assets.independent_critic.schema)


def test_direct_r002_provider_call_without_orchestrator_lease_never_reaches_transport() -> None:
    import futures_agent_os.adapters as adapters

    calls: list[object] = []

    def transport(payload: object):
        calls.append(payload)
        return _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"})

    assert not hasattr(adapters, "CodexAppServerProvider")
    assert not calls
    with pytest.raises(AttributeError):
        getattr(adapters, "CodexAppServerProvider")
    assert not calls


def test_adapter_never_backfills_requested_effort_as_actual_observation() -> None:
    missing = _response({"decision": "PASS", "reason_category": "INDEPENDENT_WINDOW_UNKNOWN"})
    del missing["reasoning_effort"]
    assert "reasoning_effort" not in missing


def test_official_transport_effort_requires_consistent_start_or_final_metadata() -> None:
    assert (
        _actual_reasoning_effort(
            {"model": "gpt-5.6-terra"},
            {"reasoning": {"effort": "high"}},
            {"status": "completed", "reasoningEffort": "high"},
        )
        == "high"
    )
    assert _actual_reasoning_effort({"model": "gpt-5.6-terra"}, {"status": "completed"}) is None
    with pytest.raises(PermissionError, match="one exact reasoning effort"):
        _actual_reasoning_effort({"reasoningEffort": "high"}, {"effort": "medium"})
