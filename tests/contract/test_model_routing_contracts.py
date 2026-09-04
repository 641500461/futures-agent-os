from __future__ import annotations

import pytest

from futures_agent_os.research_experiment.model_routing import (
    ModelActivationBinding,
    ModelAuthenticationMode,
    ModelCostAccountingMode,
    ModelProfileRevision,
    ModelProtocolFamily,
    ModelQualificationState,
    ModelRunnerCapabilities,
    ModelRunnerKind,
    ResolvedRunConfig,
    WorkloadId,
    mvp_r_runner_gaps,
)
from futures_agent_os.security import SecretReference
from futures_agent_os.shared_kernel import EntityId


def _responses_capabilities() -> ModelRunnerCapabilities:
    return ModelRunnerCapabilities(
        True,
        True,
        True,
        True,
        True,
        ModelCostAccountingMode.EXACT_MUD,
        True,
        "mvp-r.responses.v1",
    )


def _profile(*, state: ModelQualificationState) -> ModelProfileRevision:
    return ModelProfileRevision(
        EntityId.new("model_profile"),
        1,
        WorkloadId("research.hypothesis_synthesis"),
        ModelProtocolFamily.MVP_R_001,
        "openai",
        ModelRunnerKind.OPENAI_RESPONSES,
        ModelAuthenticationMode.PLATFORM_CREDENTIAL,
        "gpt-5.6-terra",
        "medium",
        "mvp-r.prompt.v1",
        "mvp-r.conclusion.v1",
        "mvp-r.serial-research.v1",
        _responses_capabilities(),
        state,
        SecretReference.parse("secret://openai/projects/fao?version=1#api_key"),
    )


def test_workload_is_stable_and_profile_activation_freezes_exact_revision() -> None:
    profile = _profile(state=ModelQualificationState.QUALIFIED)
    binding = ModelActivationBinding.activate(EntityId.new("model_activation"), profile)
    resolved = ResolvedRunConfig.resolve(binding, profile)

    assert str(resolved.workload_id) == "research.hypothesis_synthesis"
    assert resolved.profile_sha256 == profile.content_sha256
    assert resolved.model_id == "gpt-5.6-terra"
    assert resolved.reasoning_effort == "medium"


def test_unqualified_or_drifted_profile_cannot_be_resolved() -> None:
    draft = _profile(state=ModelQualificationState.DRAFT)
    with pytest.raises(PermissionError, match="qualified"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), draft)

    qualified = _profile(state=ModelQualificationState.QUALIFIED)
    binding = ModelActivationBinding.activate(EntityId.new("model_activation"), qualified)
    replacement = _profile(state=ModelQualificationState.QUALIFIED)
    with pytest.raises(PermissionError, match="exact model profile"):
        ResolvedRunConfig.resolve(binding, replacement)


def test_chatgpt_session_profile_never_pretends_to_have_an_api_secret() -> None:
    observed = ModelRunnerCapabilities(
        False,
        False,
        False,
        False,
        True,
        ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
        True,
        "mvp-r.codex-probe.v1",
    )
    profile = ModelProfileRevision(
        EntityId.new("model_profile"),
        1,
        WorkloadId("research.hypothesis_synthesis"),
        ModelProtocolFamily.MVP_R_001,
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "medium",
        "mvp-r.prompt.v1",
        "mvp-r.conclusion.v1",
        "mvp-r.serial-research.v1",
        observed,
        ModelQualificationState.EVALUATING,
    )

    assert profile.credential_ref is None
    assert mvp_r_runner_gaps(observed) == (
        "structured_output",
        "serial_function_tools",
        "frozen_tool_surface",
        "actual_model_id",
    )
    with pytest.raises(PermissionError, match="qualified"):
        ModelActivationBinding.activate(EntityId.new("model_activation"), profile)


def test_api_auth_requires_secret_reference_and_workload_is_canonical() -> None:
    with pytest.raises(ValueError, match="dotted"):
        WorkloadId("research")
    profile = _profile(state=ModelQualificationState.EVALUATING)
    with pytest.raises(ValueError, match="secret reference"):
        ModelProfileRevision(
            profile.profile_id,
            profile.revision,
            profile.workload_id,
            profile.protocol_family,
            profile.provider,
            profile.runner_kind,
            profile.authentication_mode,
            profile.model_id,
            profile.reasoning_effort,
            profile.prompt_binding,
            profile.output_schema_binding,
            profile.toolset_binding,
            profile.capabilities,
            profile.qualification_state,
        )
