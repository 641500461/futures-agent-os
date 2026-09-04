from __future__ import annotations

from dataclasses import replace

import pytest

from futures_agent_os.research_experiment.model_routing import (
    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    MVP_R_002_EMPTY_TOOLSET_BINDING,
    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
    ModelActivationBinding,
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
    QualificationBinding,
    ResearchWorkloadBundle,
    R002FrozenSuite,
    R002SuiteActivationAuthority,
    ResolvedQualificationRunConfig,
    WorkloadId,
)
from futures_agent_os.security import SecretReference
from futures_agent_os.shared_kernel import EntityId


def _capabilities() -> ModelRunnerCapabilities:
    return ModelRunnerCapabilities(
        True,
        True,
        True,
        True,
        True,
        ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
        True,
        "mvp-r-002.codex-capability-probe.v1",
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
        f"mvp-r-002.{workload.replace('.', '-')}.prompt.v1",
        f"mvp-r-002.{workload.replace('.', '-')}.schema.v1",
        MVP_R_002_EMPTY_TOOLSET_BINDING,
        _capabilities(),
        ModelQualificationState.EVALUATING,
    )


def _resolved(profile: ModelProfileRevision) -> ResolvedQualificationRunConfig:
    binding = QualificationBinding.bind(EntityId.new("model_qualification"), profile)
    return ResolvedQualificationRunConfig.resolve(binding, profile)


def _qualified(profile: ModelProfileRevision) -> ResolvedQualificationRunConfig:
    owner_authority = PhaseZeroAuthority(bytes(range(32)))
    authority = ProfileQualificationAuthority(owner_authority)
    receipts = _receipts(authority, profile)
    registry = ProfileQualificationReceiptRegistry(authority)
    for receipt in receipts:
        registry.add(receipt)
    roster = authority.issue_case_roster(profile, tuple((item.receipt_kind, item.case_id) for item in receipts))
    report = authority.issue(profile, registry, roster)
    qualified = replace(profile, qualification_state=ModelQualificationState.QUALIFIED)
    transition = authority.qualify(profile, report, registry, roster)
    return ResolvedQualificationRunConfig.resolve(
        QualificationBinding.bind(
            EntityId.new("model_qualification"),
            qualified,
            qualification_owner_authority=owner_authority,
            transition=transition,
        ),
        qualified,
    )


def _receipts(
    authority: ProfileQualificationAuthority,
    profile: ModelProfileRevision,
    *,
    recalled: bool = True,
):
    common = {
        "prompt_sha256": "a" * 64,
        "schema_sha256": "b" * 64,
        "toolset_sha256": "c" * 64,
        "runtime_sha256": "d" * 64,
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
        fault_recalled=recalled,
        **common,
    )
    return (*scenarios, fault)


def test_three_phase_zero_profiles_are_explicit_non_active_and_have_no_fallback() -> None:
    synthesis = _resolved(_profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"))
    experiment = _resolved(_profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium"))
    critic = _resolved(_profile(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high"))

    all_workloads = MvpR002QualificationWorkloads(ResearchWorkloadBundle(synthesis, experiment), critic)

    assert all_workloads.research.hypothesis_synthesis.activation_binding_id is None
    assert all_workloads.research.preregistration_design.activation_binding_id is None
    assert all_workloads.adversarial_critique.activation_binding_id is None
    assert all_workloads.adversarial_critique.reroute_allowed is False
    assert all_workloads.adversarial_critique.fallback_profile_id is None


def test_qualification_resolution_rejects_active_fallback_reroute_and_profile_drift() -> None:
    profile = _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium")
    binding = QualificationBinding.bind(EntityId.new("model_qualification"), profile)
    resolved = ResolvedQualificationRunConfig.resolve(binding, profile)

    with pytest.raises(PermissionError, match="activate"):
        replace(binding, activation_binding_id=EntityId.new("model_activation"))
    with pytest.raises(PermissionError, match="fallback"):
        replace(binding, fallback_profile_id=EntityId.new("model_profile"))
    with pytest.raises(PermissionError, match="factory-issued"):
        replace(resolved, activation_binding_id=EntityId.new("model_activation"))
    with pytest.raises(PermissionError, match="factory-issued"):
        replace(resolved, reroute_allowed=True)
    with pytest.raises(PermissionError, match="factory-issued"):
        ResolvedQualificationRunConfig(
            resolved.workload_id,
            resolved.protocol_family,
            resolved.qualification_binding_id,
            None,
            resolved.profile_id,
            resolved.profile_revision,
            resolved.profile_sha256,
            resolved.qualification_report_sha256,
            resolved.provider,
            resolved.runner_kind,
            resolved.authentication_mode,
            resolved.model_id,
            resolved.reasoning_effort,
            resolved.prompt_binding,
            resolved.output_schema_binding,
            resolved.toolset_binding,
            resolved.capabilities,
            resolved.credential_ref,
        )
    with pytest.raises(PermissionError, match="exact model profile"):
        ResolvedQualificationRunConfig.resolve(binding, _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"))

    # Existing activation remains a separate, qualified-only path.
    with pytest.raises(PermissionError, match="qualified"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), profile)


def test_bundle_rejects_wrong_effort_toolset_and_shared_profile_identity() -> None:
    synthesis = _resolved(_profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"))
    experiment = _resolved(_profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium"))

    with pytest.raises(PermissionError, match="qualification policy"):
        ResearchWorkloadBundle(synthesis, _resolved(_profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "high")))
    r001_synthesis = _resolved(
        replace(
            _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"),
            protocol_family=ModelProtocolFamily.MVP_R_001,
        )
    )
    r001_experiment = _resolved(
        replace(
            _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium"),
            protocol_family=ModelProtocolFamily.MVP_R_001,
        )
    )
    r001_critic = _resolved(
        replace(
            _profile(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high"),
            protocol_family=ModelProtocolFamily.MVP_R_001,
        )
    )
    with pytest.raises(PermissionError, match="qualification policy"):
        ResearchWorkloadBundle(r001_synthesis, r001_experiment)
    with pytest.raises(PermissionError, match="qualification policy"):
        MvpR002QualificationWorkloads(ResearchWorkloadBundle(synthesis, experiment), r001_critic)
    bad_toolset_profile = _profile(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high")
    bad_toolset_profile = replace(bad_toolset_profile, toolset_binding="mvp-r-002.nonempty-toolset.v1")
    with pytest.raises(PermissionError, match="qualification policy"):
        MvpR002QualificationWorkloads(
            ResearchWorkloadBundle(synthesis, experiment),
            _resolved(bad_toolset_profile),
        )
    with pytest.raises(ValueError, match="separate profile"):
        same_profile = _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium")
        same_profile = replace(same_profile, profile_id=synthesis.profile_id)
        ResearchWorkloadBundle(synthesis, _resolved(same_profile))
    shared_prompt_schema = _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium")
    shared_prompt_schema = replace(
        shared_prompt_schema,
        prompt_binding=synthesis.prompt_binding,
        output_schema_binding=synthesis.output_schema_binding,
    )
    with pytest.raises(ValueError, match="separate prompt and schema"):
        ResearchWorkloadBundle(synthesis, _resolved(shared_prompt_schema))
    missing_serial_capability = _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium")
    missing_serial_capability = replace(
        missing_serial_capability,
        capabilities=replace(missing_serial_capability.capabilities, serial_function_tools=False),
    )
    with pytest.raises(PermissionError, match="qualification policy"):
        ResearchWorkloadBundle(synthesis, _resolved(missing_serial_capability))
    api_key_auth = _profile(MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium")
    api_key_auth = replace(
        api_key_auth,
        authentication_mode=ModelAuthenticationMode.PROVIDER_CREDENTIAL,
        credential_ref=SecretReference.parse("secret://vault/mvp-r-002#api-key"),
    )
    with pytest.raises(PermissionError, match="qualification policy"):
        ResearchWorkloadBundle(synthesis, _resolved(api_key_auth))


def test_self_reported_qualified_profile_cannot_bind_or_activate_without_signed_transition() -> None:
    evaluating = _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium")
    self_reported = replace(evaluating, qualification_state=ModelQualificationState.QUALIFIED)

    with pytest.raises(PermissionError, match="authority-verified"):
        QualificationBinding.bind(EntityId.new("model_qualification"), self_reported)
    with pytest.raises(PermissionError, match="FROZEN suite"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), self_reported)


def test_r002_activation_cannot_hide_behind_toolset_or_caller_frozen_string() -> None:
    evaluating = replace(
        _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"),
        toolset_binding="attacker.nonempty-toolset.v1",
    )
    qualified = replace(evaluating, qualification_state=ModelQualificationState.QUALIFIED)
    with pytest.raises(PermissionError, match="FROZEN suite"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), qualified)
    with pytest.raises((TypeError, PermissionError)):
        ModelActivationBinding(
            EntityId.new("model_activation"),
            qualified.workload_id,
            qualified.profile_id,
            qualified.revision,
            qualified.content_sha256,
        )  # type: ignore[call-arg]


def test_signed_protocol_family_is_the_only_r002_classifier_and_r001_remains_compatible() -> None:
    r002_named_r001 = replace(
        _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"),
        protocol_family=ModelProtocolFamily.MVP_R_001,
        qualification_state=ModelQualificationState.QUALIFIED,
    )
    activated = ModelActivationBinding.activate(EntityId.new("model_activation"), r002_named_r001)
    assert activated.profile_sha256 == r002_named_r001.content_sha256

    legacy_named_r002 = replace(
        r002_named_r001,
        protocol_family=ModelProtocolFamily.MVP_R_002,
        prompt_binding="legacy.prompt.v1",
        output_schema_binding="legacy.schema.v1",
        toolset_binding="legacy.toolset.v1",
    )
    with pytest.raises(PermissionError, match="FROZEN suite"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), legacy_named_r002)

    fake = R002SuiteActivationAuthority("attacker.suite", bytes(range(32)))
    with pytest.raises(TypeError):
        fake.issue(  # type: ignore[call-arg]
            suite_state="FROZEN",
            suite_sha256="a" * 64,
            profile=legacy_named_r002,
            transition=object(),
        )
    with pytest.raises((TypeError, PermissionError)):
        R002FrozenSuite(
            "attacker.suite",
            "FROZEN",
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            "a" * 64,
            "b" * 64,
        )  # type: ignore[call-arg]


def test_bad_qualification_gate_cannot_produce_a_transition() -> None:
    profile = _profile(MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD, "high")
    authority = ProfileQualificationAuthority(PhaseZeroAuthority(bytes(range(32))))
    receipts = _receipts(authority, profile, recalled=False)
    registry = ProfileQualificationReceiptRegistry(authority, tuple(item.to_dict() for item in receipts))
    roster = authority.issue_case_roster(profile, tuple((item.receipt_kind, item.case_id) for item in receipts))
    with pytest.raises(PermissionError, match="fixed MVP-R-002 gate"):
        authority.issue(profile, registry, roster)


def test_qualification_report_is_rederived_from_a_strict_trusted_receipt_roster() -> None:
    profile = _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium")
    authority = ProfileQualificationAuthority(PhaseZeroAuthority(bytes(range(32))))
    receipts = _receipts(authority, profile)
    registry = ProfileQualificationReceiptRegistry(authority)
    for receipt in receipts:
        registry.add(receipt)
    with pytest.raises(ValueError, match="append-only"):
        registry.add(receipts[0])
    roster = authority.issue_case_roster(profile, tuple((item.receipt_kind, item.case_id) for item in receipts))
    assert authority.issue(profile, registry, roster).critical_scenario_count == 4
    attacker = ProfileQualificationAuthority(PhaseZeroAuthority(bytes(range(1, 33))))
    with pytest.raises(PermissionError, match="trusted root"):
        attacker.issue(profile, registry, roster)
    attacker_receipts = _receipts(attacker, profile)
    attacker_registry = ProfileQualificationReceiptRegistry(attacker)
    for receipt in attacker_receipts:
        attacker_registry.add(receipt)
    attacker_roster = attacker.issue_case_roster(
        profile, tuple((receipt.receipt_kind, receipt.case_id) for receipt in attacker_receipts)
    )
    attacker_report = attacker.issue(profile, attacker_registry, attacker_roster)
    with pytest.raises(PermissionError, match="qualification report"):
        authority.verify(attacker_report, profile, attacker_registry, attacker_roster)

    changed = authority.issue_receipt(
        profile,
        receipt_kind=receipts[0].receipt_kind,
        case_id=receipts[0].case_id,
        prompt_sha256=receipts[0].prompt_sha256,
        schema_sha256=receipts[0].schema_sha256,
        toolset_sha256=receipts[0].toolset_sha256,
        runtime_sha256=receipts[0].runtime_sha256,
        actual_provider=receipts[0].actual_provider,
        actual_model_id=receipts[0].actual_model_id,
        actual_reasoning_effort=receipts[0].actual_reasoning_effort,
        cost_accounting_mode=receipts[0].cost_accounting_mode,
        correct_refusal=receipts[0].correct_refusal,
        fault_recalled=receipts[0].fault_recalled,
        total_tokens=receipts[0].total_tokens - 1,
        latency_ms=receipts[0].latency_ms,
        reroute_count=receipts[0].reroute_count,
        activity_count=receipts[0].activity_count,
    )
    with pytest.raises(ValueError, match="append-only"):
        registry.add(changed)

    nonexistent_roster = authority.issue_case_roster(
        profile,
        (("CRITICAL_SCENARIO", "missing-case"), *roster.cases[1:]),
    )
    with pytest.raises(PermissionError, match="absent"):
        authority.issue(profile, registry, nonexistent_roster)

    extra = authority.issue_receipt(
        profile,
        receipt_kind="FAULT",
        case_id="fault-extra",
        prompt_sha256=receipts[-1].prompt_sha256,
        schema_sha256=receipts[-1].schema_sha256,
        toolset_sha256=receipts[-1].toolset_sha256,
        runtime_sha256=receipts[-1].runtime_sha256,
        actual_provider=receipts[-1].actual_provider,
        actual_model_id=receipts[-1].actual_model_id,
        actual_reasoning_effort=receipts[-1].actual_reasoning_effort,
        cost_accounting_mode=receipts[-1].cost_accounting_mode,
        correct_refusal=False,
        fault_recalled=True,
        total_tokens=receipts[-1].total_tokens,
        latency_ms=receipts[-1].latency_ms,
        reroute_count=0,
        activity_count=0,
    )
    registry.add(extra)
    with pytest.raises(PermissionError, match="exactly match"):
        authority.issue(profile, registry, roster)

    assert type(roster).hydrate(roster.to_dict(), authority, profile) == roster
    with pytest.raises(ValueError, match="fields are not exact"):
        type(roster).hydrate(roster.to_dict() | {"extra": "forbidden"}, authority, profile)


def test_qualification_authority_cannot_choose_identity_or_independent_key() -> None:
    import futures_agent_os.research_experiment as package

    assert not hasattr(package, "ProfileQualificationAuthority")
    with pytest.raises(TypeError):
        ProfileQualificationAuthority("attacker.qualification", bytes(range(32)))  # type: ignore[call-arg]
    authority = ProfileQualificationAuthority(PhaseZeroAuthority(bytes(range(32))))
    assert authority.authority_id == "mvp-r-002.profile-qualification"


def test_qualified_factory_result_is_usable_only_with_the_signed_transition() -> None:
    profile = _profile(MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium")
    resolved = _qualified(profile)

    assert resolved.qualification_report_sha256 is not None
