from __future__ import annotations

from dataclasses import replace

import pytest

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
    PhaseZeroAuthority,
    ProfileQualificationAuthority,
    ProfileQualificationReceiptRegistry,
    ProfileQualificationReport,
    QualificationBinding,
    ResearchWorkloadBundle,
    ResolvedQualificationRunConfig,
    WorkloadId,
)
from futures_agent_os.research_experiment.mvp_r_002_freeze import (
    DatasetFreezeSpec,
    FreezePlanState,
    PhaseZeroFreezePlan,
    RosterAuthorityDescriptor,
    ShadowRandomizationCommitment,
    SuiteFreezeSpec,
    WorkloadFreezeBinding,
)
from futures_agent_os.security import SecretReference
from futures_agent_os.shared_kernel import EntityId


def _digest(character: str) -> str:
    return character * 64


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
        f"mvp-r-002.{workload.replace('.', '-')}.prompt.v1",
        f"mvp-r-002.{workload.replace('.', '-')}.schema.v1",
        MVP_R_002_EMPTY_TOOLSET_BINDING,
        ModelRunnerCapabilities(
            True,
            True,
            True,
            True,
            True,
            ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
            True,
            "mvp-r-002.codex-capability-probe.v1",
        ),
        ModelQualificationState.EVALUATING,
    )


def _resolved(profile: ModelProfileRevision) -> ResolvedQualificationRunConfig:
    return ResolvedQualificationRunConfig.resolve(
        QualificationBinding.bind(EntityId.new("model_qualification"), profile), profile
    )


def _qualified(
    profile: ModelProfileRevision, digests: tuple[str, str, str, str, str, str]
) -> tuple[ResolvedQualificationRunConfig, ProfileQualificationReport]:
    owner_authority = PhaseZeroAuthority(bytes(range(32)))
    authority = ProfileQualificationAuthority(owner_authority)
    common = {
        "prompt_sha256": _digest(digests[0]),
        "schema_sha256": _digest(digests[1]),
        "toolset_sha256": _digest(digests[2]),
        "runtime_sha256": _digest(digests[3]),
        "actual_provider": "openai",
        "actual_model_id": "gpt-5.6-terra",
        "actual_reasoning_effort": profile.reasoning_effort,
        "cost_accounting_mode": ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
        "total_tokens": 20_000,
        "latency_ms": 35_000,
        "reroute_count": 0,
        "activity_count": 0,
    }
    scenarios = tuple(
        authority.issue_receipt(
            profile,
            receipt_kind="CRITICAL_SCENARIO",
            case_id=f"critical-{index}",
            correct_refusal=True,
            fault_recalled=False,
            **common,
        )
        for index in range(4)
    )
    fault = authority.issue_receipt(
        profile,
        receipt_kind="FAULT",
        case_id="fault-one",
        correct_refusal=False,
        fault_recalled=True,
        **common,
    )
    receipt_registry = ProfileQualificationReceiptRegistry(authority)
    for receipt in (*scenarios, fault):
        receipt_registry.add(receipt)
    case_roster = authority.issue_case_roster(
        profile, tuple((item.receipt_kind, item.case_id) for item in (*scenarios, fault))
    )
    report = authority.issue(profile, receipt_registry, case_roster)
    qualified = replace(profile, qualification_state=ModelQualificationState.QUALIFIED)
    transition = authority.qualify(profile, report, receipt_registry, case_roster)
    config = ResolvedQualificationRunConfig.resolve(
        QualificationBinding.bind(
            EntityId.new("model_qualification"),
            qualified,
            qualification_owner_authority=owner_authority,
            transition=transition,
        ),
        qualified,
    )
    return config, report


def _workloads(*, qualified: bool) -> tuple[MvpR002QualificationWorkloads, tuple[WorkloadFreezeBinding, ...]]:
    profiles = (
        _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"),
        _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium"),
        _profile(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high"),
    )
    if not qualified:
        configs = tuple(_resolved(profile) for profile in profiles)
        reports = (None, None, None)
    else:
        qualified_items = tuple(
            _qualified(profile, digests)
            for profile, digests in zip(
                profiles,
                (("a", "d", "1", "4", "7", "0"), ("b", "e", "2", "5", "8", "1"), ("c", "f", "3", "6", "9", "2")),
            )
        )
        configs = tuple(item[0] for item in qualified_items)
        reports = tuple(item[1] for item in qualified_items)
    workloads = MvpR002QualificationWorkloads(ResearchWorkloadBundle(configs[0], configs[1]), configs[2])
    return workloads, tuple(
        WorkloadFreezeBinding(str(config.workload_id), config, report) for config, report in zip(configs, reports)
    )


def _plan(state: FreezePlanState, *, complete: bool, qualified: bool | None = None) -> PhaseZeroFreezePlan:
    qualification_complete = complete if qualified is None else qualified
    workloads, bindings = _workloads(qualified=qualification_complete)
    reports = tuple(binding.qualification_report for binding in bindings)
    return PhaseZeroFreezePlan(
        state,
        DatasetFreezeSpec(
            state,
            "mvp-r-002.dataset-freeze",
            (_digest("a"),) if complete else (),
            (_digest("b"),) if complete else (),
            _digest("c") if complete else None,
        ),
        SuiteFreezeSpec(
            state,
            "mvp-r-002.suite-freeze",
            workloads,
            tuple(report.prompt_sha256 for report in reports if report is not None) if complete else (),
            tuple(report.schema_sha256 for report in reports if report is not None) if complete else (),
            tuple(report.runtime_sha256 for report in reports if report is not None) if complete else (),
            _digest("7") if complete else None,
            _digest("8") if complete else None,
            bindings if qualification_complete else (),
        ),
        RosterAuthorityDescriptor(
            state,
            "mvp-r-002.roster-authority",
            SecretReference.parse("secret://governance/mvp-r-002?version=1#roster_hmac"),
            "instrument-market-state.v1",
            30,
            50,
            _digest("9") if complete else None,
        ),
        ShadowRandomizationCommitment(
            state,
            "mvp-r-002.shadow-authority",
            SecretReference.parse("secret://governance/mvp-r-002?version=1#shadow_hmac"),
            10,
            _digest("0") if complete else None,
        ),
    )


def test_phase_zero_draft_cannot_claim_exact_inputs_or_freeze_anything() -> None:
    plan = _plan(FreezePlanState.DRAFT, complete=False)

    assert plan.exact_inputs_present is False
    with pytest.raises(PermissionError, match="lacks exact"):
        plan.require_exact_inputs()
    for forbidden in (plan.freeze, plan.materialize_roster, plan.issue_episode, plan.reveal_label, plan.activate):
        with pytest.raises(PermissionError):
            forbidden()
    with pytest.raises(ValueError):
        FreezePlanState("FROZEN")


def test_phase_zero_plan_accepts_typed_commitments_but_still_cannot_freeze_or_materialize() -> None:
    plan = _plan(FreezePlanState.PLANNED, complete=True)

    assert plan.exact_inputs_present is True
    plan.require_exact_inputs()
    with pytest.raises(PermissionError, match="AUTHORIZED_NOT_FROZEN"):
        plan.freeze()
    with pytest.raises(PermissionError, match="roster"):
        plan.materialize_roster()


def test_evaluating_profiles_cannot_satisfy_exact_freeze_inputs() -> None:
    plan = _plan(FreezePlanState.PLANNED, complete=True, qualified=False)

    assert plan.suite.qualification_workloads is not None
    assert plan.exact_inputs_present is False
    with pytest.raises(PermissionError, match="lacks exact"):
        plan.require_exact_inputs()


def test_secret_uri_policy_and_fixed_counts_are_part_of_the_plan_identity() -> None:
    plan = _plan(FreezePlanState.PLANNED, complete=True)
    alternate_roster = RosterAuthorityDescriptor(
        FreezePlanState.PLANNED,
        "mvp-r-002.roster-authority",
        SecretReference.parse("secret://governance/mvp-r-002?version=2#roster_hmac"),
        "instrument-market-state.v2",
        30,
        50,
        _digest("9"),
    )
    changed = PhaseZeroFreezePlan(
        plan.state,
        plan.dataset,
        plan.suite,
        alternate_roster,
        plan.shadow,
    )

    assert changed.content_sha256 != plan.content_sha256
    with pytest.raises(ValueError, match="30/50"):
        RosterAuthorityDescriptor(
            FreezePlanState.PLANNED,
            "mvp-r-002.roster-authority",
            SecretReference.parse("secret://governance/mvp-r-002?version=1#roster_hmac"),
            "instrument-market-state.v1",
            29,
            50,
            _digest("9"),
        )


def test_hmac_authorities_accept_only_secret_references_not_key_bytes() -> None:
    with pytest.raises(TypeError, match="secret reference"):
        RosterAuthorityDescriptor(
            FreezePlanState.DRAFT,
            "mvp-r-002.roster-authority",
            b"not-a-reference",  # type: ignore[arg-type]
            "instrument-market-state.v1",
            30,
            50,
            None,
        )
