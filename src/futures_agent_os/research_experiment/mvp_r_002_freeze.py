"""Phase-0-only freeze authorities for MVP-R-002.

These contracts describe what a later freeze must prove.  They intentionally
cannot issue a suite, roster, episode, label reveal, or ACTIVE binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.research_experiment.model_routing import (
    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
    MvpR002QualificationWorkloads,
    ProfileQualificationReport,
    ResolvedQualificationRunConfig,
)
from futures_agent_os.security import SecretReference
from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class FreezePlanState(StrEnum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"


def _digest(value: str, label: str) -> None:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ValueError(f"{label} must be a canonical SHA-256 digest")


def _name(value: str, label: str) -> None:
    if type(value) is not str or not _NAME.fullmatch(value):
        raise ValueError(f"{label} must be canonical")


def _digests(values: tuple[str, ...], label: str) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} cannot contain duplicates")
    for value in values:
        _digest(value, label)


@dataclass(frozen=True, slots=True)
class DatasetFreezeSpec:
    state: FreezePlanState
    authority_id: str
    provider_contract_sha256s: tuple[str, ...]
    dataset_manifest_sha256s: tuple[str, ...]
    prior_episode_exclusion_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.state) is not FreezePlanState:
            raise TypeError("dataset freeze state must be closed")
        _name(self.authority_id, "dataset authority")
        _digests(self.provider_contract_sha256s, "provider contracts")
        _digests(self.dataset_manifest_sha256s, "dataset manifests")
        if self.prior_episode_exclusion_sha256 is not None:
            _digest(self.prior_episode_exclusion_sha256, "prior episode exclusion")
        if self.state is FreezePlanState.PLANNED and not self.provider_contract_sha256s:
            raise ValueError("planned dataset freeze requires provider contracts")

    @property
    def exact_inputs_present(self) -> bool:
        return bool(
            self.provider_contract_sha256s
            and self.dataset_manifest_sha256s
            and self.prior_episode_exclusion_sha256 is not None
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "state": self.state.value,
                "authority_id": self.authority_id,
                "provider_contract_sha256s": self.provider_contract_sha256s,
                "dataset_manifest_sha256s": self.dataset_manifest_sha256s,
                "prior_episode_exclusion_sha256": self.prior_episode_exclusion_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class SuiteFreezeSpec:
    state: FreezePlanState
    authority_id: str
    qualification_workloads: MvpR002QualificationWorkloads | None
    prompt_sha256s: tuple[str, ...]
    schema_sha256s: tuple[str, ...]
    runtime_sha256s: tuple[str, ...]
    template_sha256: str | None
    evaluator_sha256: str | None
    workload_bindings: tuple["WorkloadFreezeBinding", ...] = ()

    def __post_init__(self) -> None:
        if type(self.state) is not FreezePlanState:
            raise TypeError("suite freeze state must be closed")
        _name(self.authority_id, "suite authority")
        if (
            self.qualification_workloads is not None
            and type(self.qualification_workloads) is not MvpR002QualificationWorkloads
        ):
            raise TypeError("suite freeze requires exact qualification workloads")
        _digests(self.prompt_sha256s, "prompts")
        _digests(self.schema_sha256s, "schemas")
        _digests(self.runtime_sha256s, "runtimes")
        if self.template_sha256 is not None:
            _digest(self.template_sha256, "template")
        if self.evaluator_sha256 is not None:
            _digest(self.evaluator_sha256, "evaluator")
        if type(self.workload_bindings) is not tuple or any(
            type(binding) is not WorkloadFreezeBinding for binding in self.workload_bindings
        ):
            raise TypeError("suite freeze requires exact workload bindings")
        if self.workload_bindings and tuple(binding.workload_id for binding in self.workload_bindings) != (
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
            MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
            MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
        ):
            raise ValueError("suite freeze requires the complete ordered workload mapping")
        if self.workload_bindings and any(
            binding.qualification_report is not None for binding in self.workload_bindings
        ):
            reports = tuple(binding.qualification_report for binding in self.workload_bindings)
            if any(report is None for report in reports) or (
                self.prompt_sha256s != tuple(report.prompt_sha256 for report in reports if report is not None)
                or self.schema_sha256s != tuple(report.schema_sha256 for report in reports if report is not None)
                or self.runtime_sha256s != tuple(report.runtime_sha256 for report in reports if report is not None)
            ):
                raise PermissionError("suite freeze hashes do not match its workload qualification reports")

    @property
    def exact_inputs_present(self) -> bool:
        return bool(
            self.qualification_workloads is not None
            and len(self.workload_bindings) == 3
            and len(self.prompt_sha256s) == 3
            and len(self.schema_sha256s) == 3
            and len(self.runtime_sha256s) == 3
            and self.template_sha256 is not None
            and self.evaluator_sha256 is not None
            and all(binding.exact_inputs_present for binding in self.workload_bindings)
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "state": self.state.value,
                "authority_id": self.authority_id,
                "qualification_workloads_sha256": (
                    self.qualification_workloads.content_sha256 if self.qualification_workloads is not None else None
                ),
                "prompt_sha256s": self.prompt_sha256s,
                "schema_sha256s": self.schema_sha256s,
                "runtime_sha256s": self.runtime_sha256s,
                "template_sha256": self.template_sha256,
                "evaluator_sha256": self.evaluator_sha256,
                "workload_bindings": tuple(binding.payload() for binding in self.workload_bindings),
            }
        )


@dataclass(frozen=True, slots=True)
class WorkloadFreezeBinding:
    workload_id: str
    config: ResolvedQualificationRunConfig
    qualification_report: ProfileQualificationReport | None

    def __post_init__(self) -> None:
        _name(self.workload_id, "workload")
        if type(self.config) is not ResolvedQualificationRunConfig:
            raise TypeError("workload freeze binding requires an exact qualification config")
        if str(self.config.workload_id) != self.workload_id:
            raise PermissionError("workload freeze binding crossed workload identities")
        if self.qualification_report is not None and type(self.qualification_report) is not ProfileQualificationReport:
            raise TypeError("workload freeze binding requires an exact qualification report")

    @property
    def exact_inputs_present(self) -> bool:
        return bool(
            self.qualification_report is not None
            and self.config.qualification_report_sha256 == self.qualification_report.content_sha256
            and self.qualification_report.workload_id == self.config.workload_id
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "workload_id": self.workload_id,
            "config_sha256": self.config.content_sha256,
            "qualification_report_sha256": (
                self.qualification_report.content_sha256 if self.qualification_report is not None else None
            ),
            "prompt_sha256": self.qualification_report.prompt_sha256 if self.qualification_report is not None else None,
            "schema_sha256": self.qualification_report.schema_sha256 if self.qualification_report is not None else None,
            "toolset_sha256": self.qualification_report.toolset_sha256
            if self.qualification_report is not None
            else None,
            "runtime_sha256": self.qualification_report.runtime_sha256
            if self.qualification_report is not None
            else None,
        }


@dataclass(frozen=True, slots=True)
class RosterAuthorityDescriptor:
    state: FreezePlanState
    authority_id: str
    selection_key_ref: SecretReference
    stratification_policy: str
    diagnostic_count: int
    holdout_count: int
    candidate_pool_commitment_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.state) is not FreezePlanState:
            raise TypeError("roster authority state must be closed")
        _name(self.authority_id, "roster authority")
        if type(self.selection_key_ref) is not SecretReference:
            raise TypeError("roster authority requires an HMAC secret reference, never key material")
        _name(self.stratification_policy, "roster stratification policy")
        if (type(self.diagnostic_count) is not int or self.diagnostic_count != 30) or (
            type(self.holdout_count) is not int or self.holdout_count != 50
        ):
            raise ValueError("MVP-R-002 roster authority requires the fixed 30/50 counts")
        if self.candidate_pool_commitment_sha256 is not None:
            _digest(self.candidate_pool_commitment_sha256, "candidate pool commitment")

    @property
    def exact_inputs_present(self) -> bool:
        return self.candidate_pool_commitment_sha256 is not None

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "state": self.state.value,
                "authority_id": self.authority_id,
                "selection_key_ref": self.selection_key_ref.uri,
                "stratification_policy": self.stratification_policy,
                "diagnostic_count": self.diagnostic_count,
                "holdout_count": self.holdout_count,
                "candidate_pool_commitment_sha256": self.candidate_pool_commitment_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class ShadowRandomizationCommitment:
    state: FreezePlanState
    authority_id: str
    randomization_key_ref: SecretReference
    task_count: int
    selection_commitment_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.state) is not FreezePlanState:
            raise TypeError("shadow commitment state must be closed")
        _name(self.authority_id, "shadow authority")
        if type(self.randomization_key_ref) is not SecretReference:
            raise TypeError("shadow randomization requires a secret reference, never key material")
        if type(self.task_count) is not int or self.task_count != 10:
            raise ValueError("MVP-R-002 shadow commitment requires exactly ten tasks")
        if self.selection_commitment_sha256 is not None:
            _digest(self.selection_commitment_sha256, "shadow selection commitment")

    @property
    def exact_inputs_present(self) -> bool:
        return self.selection_commitment_sha256 is not None

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "state": self.state.value,
                "authority_id": self.authority_id,
                "randomization_key_ref": self.randomization_key_ref.uri,
                "task_count": self.task_count,
                "selection_commitment_sha256": self.selection_commitment_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class PhaseZeroFreezePlan:
    """A non-mutating checklist, deliberately incapable of a real freeze."""

    state: FreezePlanState
    dataset: DatasetFreezeSpec
    suite: SuiteFreezeSpec
    roster: RosterAuthorityDescriptor
    shadow: ShadowRandomizationCommitment

    def __post_init__(self) -> None:
        if type(self.state) is not FreezePlanState:
            raise TypeError("phase-zero freeze plan state must be closed")
        if any(
            type(value) is not expected
            for value, expected in (
                (self.dataset, DatasetFreezeSpec),
                (self.suite, SuiteFreezeSpec),
                (self.roster, RosterAuthorityDescriptor),
                (self.shadow, ShadowRandomizationCommitment),
            )
        ):
            raise TypeError("phase-zero freeze plan requires exact typed authorities")
        if any(value.state is not self.state for value in (self.dataset, self.suite, self.roster, self.shadow)):
            raise ValueError("phase-zero freeze plan authorities must share one state")

    @property
    def exact_inputs_present(self) -> bool:
        return bool(
            self.dataset.exact_inputs_present
            and self.suite.exact_inputs_present
            and self.roster.exact_inputs_present
            and self.shadow.exact_inputs_present
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "state": self.state.value,
                "dataset": self.dataset.content_sha256,
                "suite": self.suite.content_sha256,
                "roster": self.roster.content_sha256,
                "shadow": self.shadow.content_sha256,
            }
        )

    def require_exact_inputs(self) -> None:
        if self.state is not FreezePlanState.PLANNED or not self.exact_inputs_present:
            raise PermissionError("Phase-0 freeze plan lacks exact frozen inputs")

    def freeze(self) -> None:
        raise PermissionError("Phase 0 is AUTHORIZED_NOT_FROZEN and cannot freeze a suite")

    def materialize_roster(self) -> None:
        raise PermissionError("Phase 0 cannot materialize a diagnostic or holdout roster")

    def issue_episode(self) -> None:
        raise PermissionError("Phase 0 cannot issue an evaluation episode")

    def reveal_label(self) -> None:
        raise PermissionError("Phase 0 cannot reveal a label")

    def activate(self) -> None:
        raise PermissionError("Phase 0 cannot create an ACTIVE model binding")


__all__ = [
    "DatasetFreezeSpec",
    "FreezePlanState",
    "PhaseZeroFreezePlan",
    "RosterAuthorityDescriptor",
    "ShadowRandomizationCommitment",
    "SuiteFreezeSpec",
    "WorkloadFreezeBinding",
]
