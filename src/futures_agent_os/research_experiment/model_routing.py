"""Versioned model routing contracts for LLM-backed research workloads.

Business code selects a stable workload.  Governance selects and activates an
exact profile revision.  A resolved run snapshot is immutable and remains
replayable after a later model or runner upgrade.
"""

from __future__ import annotations

import re
from dataclasses import InitVar, dataclass, replace
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from typing import Mapping, cast

from futures_agent_os.security import SecretReference
from futures_agent_os.shared_kernel import EntityId, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_CANONICAL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ModelRunnerKind(StrEnum):
    OPENAI_RESPONSES = "openai_responses"
    CODEX_LOCAL = "codex_local"
    GROK = "grok"


class ModelAuthenticationMode(StrEnum):
    PLATFORM_CREDENTIAL = "platform_credential"
    CHATGPT_SESSION = "chatgpt_session"
    PROVIDER_CREDENTIAL = "provider_credential"


class ModelQualificationState(StrEnum):
    DRAFT = "DRAFT"
    EVALUATING = "EVALUATING"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"


class ModelCostAccountingMode(StrEnum):
    EXACT_MUD = "EXACT_MUD"
    SUBSCRIPTION_UNAVAILABLE = "SUBSCRIPTION_UNAVAILABLE"


class ModelProtocolFamily(StrEnum):
    MVP_R_001 = "MVP_R_001"
    MVP_R_002 = "MVP_R_002"


# MVP-R-002 keeps product qualification separate from runtime activation.  The
# identifiers below are stable cognitive workloads, not names for one combined
# prompt or a deployment target.
MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD = "research.hypothesis_synthesis"
MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD = "experiment.preregistration_design"
MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD = "assurance.adversarial_critique"
MVP_R_002_EMPTY_TOOLSET_BINDING = "mvp-r-002.empty-toolset.v1"
_MVP_R_002_WORKLOADS = frozenset(
    {
        MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
        MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
        MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    }
)
_PROFILE_QUALIFICATION_PROOF = object()
_PROFILE_QUALIFICATION_RECEIPT_PROOF = object()
_QUALIFICATION_TRANSITION_PROOF = object()
_SUITE_ACTIVATION_PROOF = object()
_FROZEN_SUITE_PROOF = object()
_QUALIFICATION_CONFIG_PROOF = object()
_MODEL_ACTIVATION_PROOF = object()


def _require_digest(value: str, label: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} requires an exact digest")


@dataclass(frozen=True, slots=True)
class PhaseZeroAuthority:
    """Owner trust root shared by all Phase-0 evidence verifiers."""

    signing_key: bytes

    def __post_init__(self) -> None:
        if type(self.signing_key) is not bytes or len(self.signing_key) < 32:
            raise ValueError("Phase-0 signing keys must contain at least 32 bytes")

    def sign(self, payload: Mapping[str, JsonValue]) -> str:
        return hmac_new(self.signing_key, canonical_sha256(payload).encode(), sha256).hexdigest()

    def verify(self, payload: Mapping[str, JsonValue], signature: str) -> bool:
        _require_digest(signature, "signature")
        return compare_digest(self.sign(payload), signature)


def _is_mvp_r_002_profile(profile: ModelProfileRevision) -> bool:
    # Family is signed inside profile.content_sha256.  Workload/prompt/schema
    # names are not trusted as a product-protocol classifier.
    return profile.protocol_family is ModelProtocolFamily.MVP_R_002


@dataclass(frozen=True, slots=True)
class WorkloadId:
    value: str

    def __post_init__(self) -> None:
        if not _CANONICAL_NAME.fullmatch(self.value) or "." not in self.value:
            raise ValueError("workload id must be a canonical dotted name")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ModelRunnerCapabilities:
    """Audited capabilities of one runner revision, not marketing claims."""

    structured_output: bool
    serial_function_tools: bool
    frozen_tool_surface: bool
    actual_model_id: bool
    exact_token_usage: bool
    cost_accounting_mode: ModelCostAccountingMode
    ephemeral_provider_state: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        flags = (
            self.structured_output,
            self.serial_function_tools,
            self.frozen_tool_surface,
            self.actual_model_id,
            self.exact_token_usage,
            self.ephemeral_provider_state,
        )
        if any(type(flag) is not bool for flag in flags):
            raise TypeError("runner capabilities require exact booleans")
        if type(self.cost_accounting_mode) is not ModelCostAccountingMode:
            raise TypeError("runner capabilities require an explicit cost accounting mode")
        if not _CANONICAL_NAME.fullmatch(self.evidence_ref):
            raise ValueError("runner capability evidence requires a canonical reference")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "structured_output": self.structured_output,
            "serial_function_tools": self.serial_function_tools,
            "frozen_tool_surface": self.frozen_tool_surface,
            "actual_model_id": self.actual_model_id,
            "exact_token_usage": self.exact_token_usage,
            "cost_accounting_mode": self.cost_accounting_mode.value,
            "ephemeral_provider_state": self.ephemeral_provider_state,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class ModelProfileRevision:
    profile_id: EntityId
    revision: int
    workload_id: WorkloadId
    protocol_family: ModelProtocolFamily
    provider: str
    runner_kind: ModelRunnerKind
    authentication_mode: ModelAuthenticationMode
    model_id: str
    reasoning_effort: str
    prompt_binding: str
    output_schema_binding: str
    toolset_binding: str
    capabilities: ModelRunnerCapabilities
    qualification_state: ModelQualificationState
    credential_ref: SecretReference | None = None

    def __post_init__(self) -> None:
        if type(self.profile_id) is not EntityId or self.profile_id.namespace != "model_profile":
            raise ValueError("model profile requires model_profile identity")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("model profile revision must be positive")
        if type(self.workload_id) is not WorkloadId:
            raise TypeError("model profile requires an exact workload id")
        if type(self.protocol_family) is not ModelProtocolFamily:
            raise TypeError("model profile requires an exact signed protocol family")
        if type(self.runner_kind) is not ModelRunnerKind:
            raise TypeError("model profile requires an exact runner kind")
        if type(self.authentication_mode) is not ModelAuthenticationMode:
            raise TypeError("model profile requires an exact authentication mode")
        if type(self.capabilities) is not ModelRunnerCapabilities:
            raise TypeError("model profile requires audited runner capabilities")
        if type(self.qualification_state) is not ModelQualificationState:
            raise TypeError("model profile requires an exact qualification state")
        names = (
            self.provider,
            self.model_id,
            self.reasoning_effort,
            self.prompt_binding,
            self.output_schema_binding,
            self.toolset_binding,
        )
        if any(not _CANONICAL_NAME.fullmatch(value) for value in names):
            raise ValueError("model profile bindings must be canonical")
        if self.authentication_mode is ModelAuthenticationMode.CHATGPT_SESSION:
            if self.runner_kind is not ModelRunnerKind.CODEX_LOCAL or self.credential_ref is not None:
                raise ValueError("ChatGPT session auth is valid only for Codex local without a secret reference")
        elif type(self.credential_ref) is not SecretReference:
            raise ValueError("API-key model profiles require a secret reference")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "profile_id": str(self.profile_id),
            "revision": self.revision,
            "workload_id": str(self.workload_id),
            "protocol_family": self.protocol_family.value,
            "provider": self.provider,
            "runner_kind": self.runner_kind.value,
            "authentication_mode": self.authentication_mode.value,
            "model_id": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "prompt_binding": self.prompt_binding,
            "output_schema_binding": self.output_schema_binding,
            "toolset_binding": self.toolset_binding,
            "capabilities": self.capabilities.payload(),
            "qualification_state": self.qualification_state.value,
            "credential_ref": self.credential_ref.uri if self.credential_ref is not None else None,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class ProfileQualificationReceipt:
    """One signed observed scenario/fault result used to derive qualification."""

    authority_id: str
    profile_id: EntityId
    profile_revision: int
    evaluated_profile_sha256: str
    workload_id: WorkloadId
    receipt_kind: str
    case_id: str
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    actual_provider: str
    actual_model_id: str
    actual_reasoning_effort: str
    cost_accounting_mode: ModelCostAccountingMode
    correct_refusal: bool
    fault_recalled: bool
    total_tokens: int
    latency_ms: int
    reroute_count: int
    activity_count: int
    content_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _PROFILE_QUALIFICATION_RECEIPT_PROOF:
            raise PermissionError("qualification receipts must be authority-issued")
        if self.receipt_kind not in {"CRITICAL_SCENARIO", "FAULT"}:
            raise ValueError("qualification receipt kind must be closed")
        if not _CANONICAL_NAME.fullmatch(self.authority_id) or not _CANONICAL_NAME.fullmatch(self.case_id):
            raise ValueError("qualification receipt identities must be canonical")
        if type(self.profile_id) is not EntityId or type(self.workload_id) is not WorkloadId:
            raise TypeError("qualification receipt requires exact profile/workload identities")
        for digest in (
            self.evaluated_profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
            self.content_sha256,
            self.signature_sha256,
        ):
            _require_digest(digest, "qualification receipt")
        if type(self.correct_refusal) is not bool or type(self.fault_recalled) is not bool:
            raise TypeError("qualification receipt results must be exact booleans")
        if self.receipt_kind == "CRITICAL_SCENARIO" and self.fault_recalled:
            raise ValueError("scenario receipts cannot claim fault recall")
        for value in (self.total_tokens, self.latency_ms, self.reroute_count, self.activity_count):
            if type(value) is not int or value < 0:
                raise ValueError("qualification receipt measurements must be non-negative integers")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("qualification receipt digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "profile_id": str(self.profile_id),
            "profile_revision": self.profile_revision,
            "evaluated_profile_sha256": self.evaluated_profile_sha256,
            "workload_id": str(self.workload_id),
            "receipt_kind": self.receipt_kind,
            "case_id": self.case_id,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
            "actual_provider": self.actual_provider,
            "actual_model_id": self.actual_model_id,
            "actual_reasoning_effort": self.actual_reasoning_effort,
            "cost_accounting_mode": self.cost_accounting_mode.value,
            "correct_refusal": self.correct_refusal,
            "fault_recalled": self.fault_recalled,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "reroute_count": self.reroute_count,
            "activity_count": self.activity_count,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(
        cls,
        value: Mapping[str, object],
        authority: ProfileQualificationAuthority,
    ) -> ProfileQualificationReceipt:
        expected = set(cls.__dataclass_fields__) - {"_proof"}
        if set(value) != expected:
            raise ValueError("qualification receipt fields are not exact")
        receipt = cls(
            cast(str, value["authority_id"]),
            EntityId.parse(cast(str, value["profile_id"])),
            cast(int, value["profile_revision"]),
            cast(str, value["evaluated_profile_sha256"]),
            WorkloadId(cast(str, value["workload_id"])),
            cast(str, value["receipt_kind"]),
            cast(str, value["case_id"]),
            cast(str, value["prompt_sha256"]),
            cast(str, value["schema_sha256"]),
            cast(str, value["toolset_sha256"]),
            cast(str, value["runtime_sha256"]),
            cast(str, value["actual_provider"]),
            cast(str, value["actual_model_id"]),
            cast(str, value["actual_reasoning_effort"]),
            ModelCostAccountingMode(cast(str, value["cost_accounting_mode"])),
            cast(bool, value["correct_refusal"]),
            cast(bool, value["fault_recalled"]),
            cast(int, value["total_tokens"]),
            cast(int, value["latency_ms"]),
            cast(int, value["reroute_count"]),
            cast(int, value["activity_count"]),
            cast(str, value["content_sha256"]),
            cast(str, value["signature_sha256"]),
            _PROFILE_QUALIFICATION_RECEIPT_PROOF,
        )
        authority.verify_receipt_signature(receipt)
        return receipt


@dataclass(frozen=True, slots=True)
class FrozenQualificationCaseRoster:
    authority_id: str
    evaluated_profile_sha256: str
    workload_id: WorkloadId
    cases: tuple[tuple[str, str], ...]
    content_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _PROFILE_QUALIFICATION_RECEIPT_PROOF:
            raise PermissionError("qualification case rosters must be authority-issued")
        if not self.cases or len(set(self.cases)) != len(self.cases):
            raise ValueError("qualification case roster must be strict and unique")
        if sum(kind == "CRITICAL_SCENARIO" for kind, _ in self.cases) != 4 or not any(
            kind == "FAULT" for kind, _ in self.cases
        ):
            raise ValueError("qualification case roster requires four critical scenarios and faults")
        for kind, case_id in self.cases:
            if kind not in {"CRITICAL_SCENARIO", "FAULT"} or not _CANONICAL_NAME.fullmatch(case_id):
                raise ValueError("qualification case roster identities are invalid")
        _require_digest(self.evaluated_profile_sha256, "qualification case roster profile")
        _require_digest(self.content_sha256, "qualification case roster content")
        _require_digest(self.signature_sha256, "qualification case roster signature")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("qualification case roster digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "evaluated_profile_sha256": self.evaluated_profile_sha256,
            "workload_id": str(self.workload_id),
            "cases": tuple({"kind": kind, "case_id": case_id} for kind, case_id in self.cases),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(
        cls,
        value: Mapping[str, object],
        authority: ProfileQualificationAuthority,
        profile: ModelProfileRevision,
    ) -> FrozenQualificationCaseRoster:
        if set(value) != set(cls.__dataclass_fields__) - {"_proof"}:
            raise ValueError("qualification case roster fields are not exact")
        raw_cases = value["cases"]
        if type(raw_cases) not in (tuple, list):
            raise TypeError("qualification case roster cases must be an array")
        cases: list[tuple[str, str]] = []
        for raw in cast(tuple[object, ...] | list[object], raw_cases):
            if not isinstance(raw, Mapping) or set(raw) != {"kind", "case_id"}:
                raise ValueError("qualification case roster entry fields are not exact")
            cases.append((cast(str, raw["kind"]), cast(str, raw["case_id"])))
        roster = cls(
            cast(str, value["authority_id"]),
            cast(str, value["evaluated_profile_sha256"]),
            WorkloadId(cast(str, value["workload_id"])),
            tuple(cases),
            cast(str, value["content_sha256"]),
            cast(str, value["signature_sha256"]),
            _PROFILE_QUALIFICATION_RECEIPT_PROOF,
        )
        authority.verify_case_roster(roster, profile)
        return roster


@dataclass(frozen=True, slots=True)
class ProfileQualificationReport:
    """Signed deterministic evidence required before an R-002 profile is qualified."""

    authority_id: str
    profile_id: EntityId
    profile_revision: int
    evaluated_profile_sha256: str
    workload_id: WorkloadId
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    scenario_receipt_sha256s: tuple[str, ...]
    fault_receipt_sha256s: tuple[str, ...]
    actual_provider: str
    actual_model_id: str
    actual_reasoning_effort: str
    cost_accounting_mode: ModelCostAccountingMode
    critical_scenario_count: int
    critical_correct_refusal_count: int
    injected_fault_count: int
    recalled_fault_count: int
    average_total_tokens: int
    average_latency_ms: int
    reroute_count: int
    activity_count: int
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _PROFILE_QUALIFICATION_PROOF:
            raise PermissionError("qualification reports must be issued by a deterministic authority")
        if not _CANONICAL_NAME.fullmatch(self.authority_id):
            raise ValueError("qualification report requires a canonical authority")
        if type(self.profile_id) is not EntityId or self.profile_id.namespace != "model_profile":
            raise ValueError("qualification report requires model_profile identity")
        if type(self.profile_revision) is not int or self.profile_revision < 1:
            raise ValueError("qualification report requires a positive profile revision")
        if type(self.workload_id) is not WorkloadId:
            raise TypeError("qualification report requires an exact workload")
        for digest in (
            self.evaluated_profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
            self.signature_sha256,
        ):
            _require_digest(digest, "qualification report")
        for roster in (self.scenario_receipt_sha256s, self.fault_receipt_sha256s):
            if type(roster) is not tuple or not roster or len(set(roster)) != len(roster):
                raise ValueError("qualification report requires unique non-empty receipt rosters")
            for digest in roster:
                _require_digest(digest, "qualification receipt")
        if type(self.cost_accounting_mode) is not ModelCostAccountingMode:
            raise TypeError("qualification report requires an exact cost accounting mode")
        if any(
            not _CANONICAL_NAME.fullmatch(value)
            for value in (self.actual_provider, self.actual_model_id, self.actual_reasoning_effort)
        ):
            raise ValueError("qualification report requires canonical actual model facts")
        counts = (
            self.critical_scenario_count,
            self.critical_correct_refusal_count,
            self.injected_fault_count,
            self.recalled_fault_count,
            self.average_total_tokens,
            self.average_latency_ms,
            self.reroute_count,
            self.activity_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("qualification report measurements must be non-negative integers")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "profile_id": str(self.profile_id),
            "profile_revision": self.profile_revision,
            "evaluated_profile_sha256": self.evaluated_profile_sha256,
            "workload_id": str(self.workload_id),
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
            "scenario_receipt_sha256s": self.scenario_receipt_sha256s,
            "fault_receipt_sha256s": self.fault_receipt_sha256s,
            "actual_provider": self.actual_provider,
            "actual_model_id": self.actual_model_id,
            "actual_reasoning_effort": self.actual_reasoning_effort,
            "cost_accounting_mode": self.cost_accounting_mode.value,
            "critical_scenario_count": self.critical_scenario_count,
            "critical_correct_refusal_count": self.critical_correct_refusal_count,
            "injected_fault_count": self.injected_fault_count,
            "recalled_fault_count": self.recalled_fault_count,
            "average_total_tokens": self.average_total_tokens,
            "average_latency_ms": self.average_latency_ms,
            "reroute_count": self.reroute_count,
            "activity_count": self.activity_count,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())


class ProfileQualificationAuthority:
    """Signs only reports that satisfy the fixed Phase-0 qualification gate."""

    _AUTHORITY_ID = "mvp-r-002.profile-qualification"

    def __init__(self, owner_authority: PhaseZeroAuthority) -> None:
        if type(owner_authority) is not PhaseZeroAuthority:
            raise TypeError("qualification trust root must be the existing Phase-0 owner authority")
        self._authority_id = self._AUTHORITY_ID
        self._owner_authority = owner_authority

    @property
    def authority_id(self) -> str:
        return self._authority_id

    def issue_case_roster(
        self,
        profile: ModelProfileRevision,
        cases: tuple[tuple[str, str], ...],
    ) -> FrozenQualificationCaseRoster:
        payload: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "evaluated_profile_sha256": profile.content_sha256,
            "workload_id": str(profile.workload_id),
            "cases": tuple({"kind": kind, "case_id": case_id} for kind, case_id in cases),
        }
        return FrozenQualificationCaseRoster(
            self._authority_id,
            profile.content_sha256,
            profile.workload_id,
            cases,
            canonical_sha256(payload),
            self._sign(payload),
            _PROFILE_QUALIFICATION_RECEIPT_PROOF,
        )

    def issue_receipt(
        self,
        profile: ModelProfileRevision,
        *,
        receipt_kind: str,
        case_id: str,
        prompt_sha256: str,
        schema_sha256: str,
        toolset_sha256: str,
        runtime_sha256: str,
        actual_provider: str,
        actual_model_id: str,
        actual_reasoning_effort: str,
        cost_accounting_mode: ModelCostAccountingMode,
        correct_refusal: bool,
        fault_recalled: bool,
        total_tokens: int,
        latency_ms: int,
        reroute_count: int,
        activity_count: int,
    ) -> ProfileQualificationReceipt:
        if (
            type(profile) is not ModelProfileRevision
            or profile.qualification_state is not ModelQualificationState.EVALUATING
        ):
            raise PermissionError("only an evaluating profile can receive a qualification receipt")
        values: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "profile_id": str(profile.profile_id),
            "profile_revision": profile.revision,
            "evaluated_profile_sha256": profile.content_sha256,
            "workload_id": str(profile.workload_id),
            "receipt_kind": receipt_kind,
            "case_id": case_id,
            "prompt_sha256": prompt_sha256,
            "schema_sha256": schema_sha256,
            "toolset_sha256": toolset_sha256,
            "runtime_sha256": runtime_sha256,
            "actual_provider": actual_provider,
            "actual_model_id": actual_model_id,
            "actual_reasoning_effort": actual_reasoning_effort,
            "cost_accounting_mode": cost_accounting_mode.value,
            "correct_refusal": correct_refusal,
            "fault_recalled": fault_recalled,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "reroute_count": reroute_count,
            "activity_count": activity_count,
        }
        content = canonical_sha256(values)
        return ProfileQualificationReceipt(
            self._authority_id,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            profile.workload_id,
            receipt_kind,
            case_id,
            prompt_sha256,
            schema_sha256,
            toolset_sha256,
            runtime_sha256,
            actual_provider,
            actual_model_id,
            actual_reasoning_effort,
            cost_accounting_mode,
            correct_refusal,
            fault_recalled,
            total_tokens,
            latency_ms,
            reroute_count,
            activity_count,
            content,
            self._sign(values),
            _PROFILE_QUALIFICATION_RECEIPT_PROOF,
        )

    def issue(
        self,
        profile: ModelProfileRevision,
        registry: ProfileQualificationReceiptRegistry,
        roster: FrozenQualificationCaseRoster,
    ) -> ProfileQualificationReport:
        if (
            type(profile) is not ModelProfileRevision
            or profile.qualification_state is not ModelQualificationState.EVALUATING
        ):
            raise PermissionError("only an evaluating profile can receive a qualification report")
        self.verify_case_roster(roster, profile)
        receipts = tuple(registry.require(profile.content_sha256, kind, case_id) for kind, case_id in roster.cases)
        if registry.identities_for(profile.content_sha256) != roster.cases:
            raise PermissionError("qualification registry does not exactly match its frozen case roster")
        for receipt in receipts:
            self.verify_receipt(receipt, profile)
        scenarios = tuple(item for item in receipts if item.receipt_kind == "CRITICAL_SCENARIO")
        faults = tuple(item for item in receipts if item.receipt_kind == "FAULT")
        first = receipts[0]
        if (
            len(scenarios) != 4
            or not faults
            or any(
                (
                    item.prompt_sha256,
                    item.schema_sha256,
                    item.toolset_sha256,
                    item.runtime_sha256,
                    item.actual_provider,
                    item.actual_model_id,
                    item.actual_reasoning_effort,
                    item.cost_accounting_mode,
                )
                != (
                    first.prompt_sha256,
                    first.schema_sha256,
                    first.toolset_sha256,
                    first.runtime_sha256,
                    first.actual_provider,
                    first.actual_model_id,
                    first.actual_reasoning_effort,
                    first.cost_accounting_mode,
                )
                for item in receipts
            )
        ):
            raise PermissionError("qualification receipt roster is incomplete or crossed asset/model identities")
        report = ProfileQualificationReport(
            self._authority_id,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            profile.workload_id,
            first.prompt_sha256,
            first.schema_sha256,
            first.toolset_sha256,
            first.runtime_sha256,
            tuple(item.content_sha256 for item in scenarios),
            tuple(item.content_sha256 for item in faults),
            first.actual_provider,
            first.actual_model_id,
            first.actual_reasoning_effort,
            first.cost_accounting_mode,
            len(scenarios),
            sum(item.correct_refusal for item in scenarios),
            len(faults),
            sum(item.fault_recalled for item in faults),
            sum(item.total_tokens for item in receipts) // len(receipts),
            sum(item.latency_ms for item in receipts) // len(receipts),
            sum(item.reroute_count for item in receipts),
            sum(item.activity_count for item in receipts),
            "0" * 64,
            _PROFILE_QUALIFICATION_PROOF,
        )
        self._require_gate(profile, report)
        return replace(
            report, signature_sha256=self._sign(report.unsigned_payload()), _proof=_PROFILE_QUALIFICATION_PROOF
        )

    def verify_receipt(self, receipt: ProfileQualificationReceipt, profile: ModelProfileRevision) -> None:
        if type(receipt) is not ProfileQualificationReceipt or type(profile) is not ModelProfileRevision:
            raise TypeError("qualification receipt verification requires exact types")
        if (
            receipt.authority_id != self._authority_id
            or receipt.profile_id != profile.profile_id
            or receipt.profile_revision != profile.revision
            or receipt.evaluated_profile_sha256 != profile.content_sha256
            or receipt.workload_id != profile.workload_id
            or not compare_digest(receipt.signature_sha256, self._sign(receipt.unsigned_payload()))
        ):
            raise PermissionError("qualification receipt does not bind the exact evaluating profile")

    def verify_receipt_signature(self, receipt: ProfileQualificationReceipt) -> None:
        if receipt.authority_id != self._authority_id or not compare_digest(
            receipt.signature_sha256, self._sign(receipt.unsigned_payload())
        ):
            raise PermissionError("qualification receipt authority is not trusted")

    def verify_case_roster(
        self,
        roster: FrozenQualificationCaseRoster,
        profile: ModelProfileRevision,
    ) -> None:
        if (
            type(roster) is not FrozenQualificationCaseRoster
            or roster.authority_id != self._authority_id
            or roster.evaluated_profile_sha256 != profile.content_sha256
            or roster.workload_id != profile.workload_id
            or not compare_digest(roster.signature_sha256, self._sign(roster.unsigned_payload()))
        ):
            raise PermissionError("qualification case roster is not from the trusted root")

    def verify(
        self,
        report: ProfileQualificationReport,
        profile: ModelProfileRevision,
        registry: ProfileQualificationReceiptRegistry,
        roster: FrozenQualificationCaseRoster,
    ) -> None:
        if type(report) is not ProfileQualificationReport or type(profile) is not ModelProfileRevision:
            raise TypeError("qualification verification requires exact report and profile")
        if (
            report.authority_id != self._authority_id
            or report.profile_id != profile.profile_id
            or report.profile_revision != profile.revision
            or report.evaluated_profile_sha256 != profile.content_sha256
            or report.workload_id != profile.workload_id
            or not compare_digest(report.signature_sha256, self._sign(report.unsigned_payload()))
        ):
            raise PermissionError("qualification report does not bind the exact evaluating profile")
        derived = self.issue(profile, registry, roster)
        if derived.content_sha256 != report.content_sha256 or derived.unsigned_payload() != report.unsigned_payload():
            raise PermissionError("qualification report does not rederive from persisted frozen receipts")
        self._require_gate(profile, report)

    def qualify(
        self,
        profile: ModelProfileRevision,
        report: ProfileQualificationReport,
        registry: ProfileQualificationReceiptRegistry,
        roster: FrozenQualificationCaseRoster,
    ) -> QualifiedProfileTransition:
        self.verify(report, profile, registry, roster)
        qualified = replace(profile, qualification_state=ModelQualificationState.QUALIFIED)
        unsigned: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "evaluated_profile_sha256": profile.content_sha256,
            "qualified_profile_sha256": qualified.content_sha256,
            "qualification_report_sha256": report.content_sha256,
        }
        return QualifiedProfileTransition(
            self._authority_id,
            profile.content_sha256,
            qualified.content_sha256,
            report.content_sha256,
            self._sign(unsigned),
            _QUALIFICATION_TRANSITION_PROOF,
        )

    def verify_transition(
        self,
        transition: QualifiedProfileTransition,
        qualified_profile: ModelProfileRevision,
    ) -> None:
        if type(transition) is not QualifiedProfileTransition or type(qualified_profile) is not ModelProfileRevision:
            raise TypeError("qualification transition verification requires exact types")
        expected = {
            "authority_id": self._authority_id,
            "evaluated_profile_sha256": transition.evaluated_profile_sha256,
            "qualified_profile_sha256": qualified_profile.content_sha256,
            "qualification_report_sha256": transition.qualification_report_sha256,
        }
        if (
            qualified_profile.qualification_state is not ModelQualificationState.QUALIFIED
            or transition.authority_id != self._authority_id
            or transition.qualified_profile_sha256 != qualified_profile.content_sha256
            or not compare_digest(transition.signature_sha256, self._sign(expected))
        ):
            raise PermissionError("qualified transition is invalid")

    def _require_gate(self, profile: ModelProfileRevision, report: ProfileQualificationReport) -> None:
        if (
            report.actual_provider != profile.provider
            or report.actual_model_id != profile.model_id
            or report.actual_reasoning_effort != profile.reasoning_effort
            or report.cost_accounting_mode is not profile.capabilities.cost_accounting_mode
            or report.critical_scenario_count != 4
            or report.critical_correct_refusal_count != 4
            or report.injected_fault_count < 1
            or report.recalled_fault_count != report.injected_fault_count
            or report.average_total_tokens > 20_000
            or report.average_latency_ms > 35_000
            or report.reroute_count != 0
            or report.activity_count != 0
        ):
            raise PermissionError("qualification report does not satisfy the fixed MVP-R-002 gate")

    def _sign(self, payload: Mapping[str, JsonValue]) -> str:
        return self._owner_authority.sign(
            {
                "authority_id": self._AUTHORITY_ID,
                "qualification_payload_sha256": canonical_sha256(payload),
            }
        )


class ProfileQualificationReceiptRegistry:
    """Append-only persisted qualification observations under one trust root."""

    def __init__(
        self,
        authority: ProfileQualificationAuthority,
        receipts: tuple[Mapping[str, object], ...] = (),
    ) -> None:
        if type(authority) is not ProfileQualificationAuthority:
            raise TypeError("qualification receipt registry requires its trusted authority")
        self._authority = authority
        self._records: dict[str, dict[str, JsonValue]] = {}
        self._semantic: dict[tuple[str, str, str], str] = {}
        self._profile_order: dict[str, list[tuple[str, str]]] = {}
        for value in receipts:
            self.add_serialized(value)

    def add(self, receipt: ProfileQualificationReceipt) -> None:
        if type(receipt) is not ProfileQualificationReceipt:
            raise TypeError("qualification registry accepts exact typed receipts")
        self.add_serialized(receipt.to_dict())

    def add_serialized(self, value: Mapping[str, object]) -> None:
        receipt = ProfileQualificationReceipt.hydrate(value, self._authority)
        identity = (receipt.evaluated_profile_sha256, receipt.receipt_kind, receipt.case_id)
        if receipt.content_sha256 in self._records or identity in self._semantic:
            raise ValueError("qualification receipt kind/case is append-only and cannot be replayed or re-signed")
        self._records[receipt.content_sha256] = receipt.to_dict()
        self._semantic[identity] = receipt.content_sha256
        self._profile_order.setdefault(receipt.evaluated_profile_sha256, []).append(
            (receipt.receipt_kind, receipt.case_id)
        )

    def require(self, profile_sha256: str, kind: str, case_id: str) -> ProfileQualificationReceipt:
        digest = self._semantic.get((profile_sha256, kind, case_id))
        if digest is None:
            raise PermissionError("frozen qualification case receipt is absent")
        return ProfileQualificationReceipt.hydrate(self._records[digest], self._authority)

    def identities_for(self, profile_sha256: str) -> tuple[tuple[str, str], ...]:
        return tuple(self._profile_order.get(profile_sha256, ()))

    def serialized(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._records.values())


@dataclass(frozen=True, slots=True)
class QualifiedProfileTransition:
    authority_id: str
    evaluated_profile_sha256: str
    qualified_profile_sha256: str
    qualification_report_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _QUALIFICATION_TRANSITION_PROOF:
            raise PermissionError("qualified transitions must be authority-issued")
        if not _CANONICAL_NAME.fullmatch(self.authority_id):
            raise ValueError("qualified transition requires canonical authority")
        for digest in (
            self.evaluated_profile_sha256,
            self.qualified_profile_sha256,
            self.qualification_report_sha256,
            self.signature_sha256,
        ):
            _require_digest(digest, "qualified transition")


@dataclass(frozen=True, slots=True)
class R002SuiteActivationAuthorization:
    """Future signed authorization; Phase 0 creates none of these."""

    authority_id: str
    suite_sha256: str
    qualified_profile_sha256: str
    qualification_report_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _SUITE_ACTIVATION_PROOF:
            raise PermissionError("suite activation authorization must be authority-issued")
        if not _CANONICAL_NAME.fullmatch(self.authority_id):
            raise ValueError("suite activation authorization requires canonical authority")
        for digest in (
            self.suite_sha256,
            self.qualified_profile_sha256,
            self.qualification_report_sha256,
            self.signature_sha256,
        ):
            _require_digest(digest, "suite activation authorization")

    def verify_profile(self, profile: ModelProfileRevision) -> None:
        if type(profile) is not ModelProfileRevision or profile.content_sha256 != self.qualified_profile_sha256:
            raise PermissionError("suite activation authorization does not bind the exact qualified profile")


@dataclass(frozen=True, slots=True)
class R002FrozenSuite:
    """Typed owner-signed suite envelope accepted only by a trusted verifier.

    Phase 0 can hydrate a future governance artifact for verification tests but
    intentionally exposes no method that mints one or turns it into ACTIVE.
    """

    authority_id: str
    state: str
    workload_ids: tuple[str, ...]
    qualification_report_sha256s: tuple[str, ...]
    scenario_receipt_sha256s: tuple[str, ...]
    fault_receipt_sha256s: tuple[str, ...]
    content_sha256: str
    signature_sha256: str
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _FROZEN_SUITE_PROOF:
            raise PermissionError("FrozenSuite must be hydrated by its trusted authority verifier")
        if not _CANONICAL_NAME.fullmatch(self.authority_id) or self.state != "FROZEN":
            raise PermissionError("FrozenSuite requires an exact trusted FROZEN state")
        if self.workload_ids != tuple(sorted(_MVP_R_002_WORKLOADS)):
            raise PermissionError("FrozenSuite requires the complete exact R-002 workload roster")
        for roster, label in (
            (self.qualification_report_sha256s, "qualification reports"),
            (self.scenario_receipt_sha256s, "scenario receipts"),
            (self.fault_receipt_sha256s, "fault receipts"),
        ):
            if type(roster) is not tuple or not roster or len(set(roster)) != len(roster):
                raise ValueError(f"FrozenSuite {label} must be a strict unique roster")
            for digest in roster:
                _require_digest(digest, f"FrozenSuite {label}")
        if len(self.qualification_report_sha256s) != 3:
            raise ValueError("FrozenSuite requires one qualification report per workload")
        _require_digest(self.content_sha256, "FrozenSuite content")
        _require_digest(self.signature_sha256, "FrozenSuite signature")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("FrozenSuite digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "state": self.state,
            "workload_ids": self.workload_ids,
            "qualification_report_sha256s": self.qualification_report_sha256s,
            "scenario_receipt_sha256s": self.scenario_receipt_sha256s,
            "fault_receipt_sha256s": self.fault_receipt_sha256s,
        }


class R002SuiteActivationAuthority:
    """Future suite-freeze authority.  Phase 0 deliberately invokes no issuance."""

    def __init__(self, authority_id: str, signing_key: bytes) -> None:
        if not _CANONICAL_NAME.fullmatch(authority_id) or type(signing_key) is not bytes or len(signing_key) < 32:
            raise ValueError("suite activation authority requires identity and 256-bit signing key")
        self._authority_id = authority_id
        self._signing_key = signing_key

    def issue(
        self,
        *,
        suite: R002FrozenSuite,
        profile: ModelProfileRevision,
        transition: QualifiedProfileTransition,
    ) -> R002SuiteActivationAuthorization:
        if type(suite) is not R002FrozenSuite:
            raise TypeError("suite activation requires typed owner-signed FrozenSuite evidence")
        self.verify_suite(suite)
        if profile.qualification_state is not ModelQualificationState.QUALIFIED:
            raise PermissionError("suite activation requires a qualified profile")
        if (
            transition.qualified_profile_sha256 != profile.content_sha256
            or transition.qualification_report_sha256 not in suite.qualification_report_sha256s
        ):
            raise PermissionError("suite activation requires the exact qualified transition and receipt-derived report")
        # Phase 0 deliberately has no issuance path.  A later Roadmap task must
        # install a trusted verifier and atomic FrozenSuite factory first.
        raise PermissionError("MVP-R-002 Phase 0 is AUTHORIZED_NOT_FROZEN and cannot activate")

    def verify_suite(self, suite: R002FrozenSuite) -> None:
        if type(suite) is not R002FrozenSuite or suite.authority_id != self._authority_id:
            raise PermissionError("FrozenSuite authority is not trusted")
        if not compare_digest(suite.signature_sha256, self._sign(suite.unsigned_payload())):
            raise PermissionError("FrozenSuite signature is invalid")

    def hydrate_suite(self, value: Mapping[str, object]) -> R002FrozenSuite:
        required = {
            "authority_id",
            "state",
            "workload_ids",
            "qualification_report_sha256s",
            "scenario_receipt_sha256s",
            "fault_receipt_sha256s",
            "content_sha256",
            "signature_sha256",
        }
        if set(value) != required:
            raise ValueError("FrozenSuite fields are not exact")

        def roster(name: str) -> tuple[str, ...]:
            raw = value[name]
            if type(raw) not in (tuple, list):
                raise TypeError("FrozenSuite rosters must be arrays")
            return tuple(cast(tuple[str, ...] | list[str], raw))

        suite = R002FrozenSuite(
            cast(str, value["authority_id"]),
            cast(str, value["state"]),
            roster("workload_ids"),
            roster("qualification_report_sha256s"),
            roster("scenario_receipt_sha256s"),
            roster("fault_receipt_sha256s"),
            cast(str, value["content_sha256"]),
            cast(str, value["signature_sha256"]),
            _FROZEN_SUITE_PROOF,
        )
        self.verify_suite(suite)
        return suite

    def verify(self, authorization: R002SuiteActivationAuthorization, profile: ModelProfileRevision) -> None:
        expected: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "suite_sha256": authorization.suite_sha256,
            "qualified_profile_sha256": profile.content_sha256,
            "qualification_report_sha256": authorization.qualification_report_sha256,
        }
        if authorization.authority_id != self._authority_id or not compare_digest(
            authorization.signature_sha256, self._sign(expected)
        ):
            raise PermissionError("suite activation authorization signature is invalid")
        authorization.verify_profile(profile)

    def _sign(self, payload: Mapping[str, JsonValue]) -> str:
        from hashlib import sha256
        from hmac import new as hmac_new

        return hmac_new(self._signing_key, canonical_sha256(payload).encode(), sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelActivationBinding:
    binding_id: EntityId
    workload_id: WorkloadId
    profile_id: EntityId
    profile_revision: int
    profile_sha256: str
    _proof: InitVar[object]

    @classmethod
    def activate(
        cls,
        binding_id: EntityId,
        profile: ModelProfileRevision,
        authorization: R002SuiteActivationAuthorization | None = None,
    ) -> ModelActivationBinding:
        if profile.qualification_state is not ModelQualificationState.QUALIFIED:
            raise PermissionError("only a qualified model profile can be activated")
        if _is_mvp_r_002_profile(profile):
            raise PermissionError("MVP-R-002 Phase 0 has no trusted FROZEN suite and cannot activate")
        elif authorization is not None:
            raise PermissionError("non-MVP-R-002 activation does not accept a suite authorization")
        return cls(
            binding_id,
            profile.workload_id,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            _MODEL_ACTIVATION_PROOF,
        )

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _MODEL_ACTIVATION_PROOF:
            raise PermissionError("model activation bindings must be factory-issued")
        if type(self.binding_id) is not EntityId or self.binding_id.namespace != "model_activation":
            raise ValueError("activation binding requires model_activation identity")
        if type(self.workload_id) is not WorkloadId:
            raise TypeError("activation binding requires an exact workload id")
        if type(self.profile_id) is not EntityId or self.profile_id.namespace != "model_profile":
            raise ValueError("activation binding requires model_profile identity")
        if type(self.profile_revision) is not int or self.profile_revision < 1:
            raise ValueError("activation binding requires a positive profile revision")
        if not re.fullmatch(r"[0-9a-f]{64}", self.profile_sha256):
            raise ValueError("activation binding requires an exact profile digest")


@dataclass(frozen=True, slots=True)
class ResolvedRunConfig:
    """Exact profile snapshot bound to a run before provider invocation."""

    workload_id: WorkloadId
    activation_binding_id: EntityId
    profile_id: EntityId
    profile_revision: int
    profile_sha256: str
    provider: str
    runner_kind: ModelRunnerKind
    authentication_mode: ModelAuthenticationMode
    model_id: str
    reasoning_effort: str
    prompt_binding: str
    output_schema_binding: str
    toolset_binding: str
    capabilities: ModelRunnerCapabilities
    credential_ref: SecretReference | None

    @classmethod
    def resolve(cls, binding: ModelActivationBinding, profile: ModelProfileRevision) -> ResolvedRunConfig:
        if (
            binding.workload_id != profile.workload_id
            or binding.profile_id != profile.profile_id
            or binding.profile_revision != profile.revision
            or binding.profile_sha256 != profile.content_sha256
        ):
            raise PermissionError("activation binding does not match the exact model profile revision")
        return cls(
            profile.workload_id,
            binding.binding_id,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            profile.provider,
            profile.runner_kind,
            profile.authentication_mode,
            profile.model_id,
            profile.reasoning_effort,
            profile.prompt_binding,
            profile.output_schema_binding,
            profile.toolset_binding,
            profile.capabilities,
            profile.credential_ref,
        )


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    """Exact non-ACTIVE binding used only for capability qualification.

    This deliberately cannot stand in for ``ModelActivationBinding``.  A
    successful capability probe may qualify a profile, but it never enables a
    product workload or a frozen evaluation suite.
    """

    binding_id: EntityId
    workload_id: WorkloadId
    profile_id: EntityId
    profile_revision: int
    profile_sha256: str
    qualification_report_sha256: str | None = None
    activation_binding_id: None = None
    fallback_profile_id: None = None
    reroute_allowed: bool = False

    @classmethod
    def bind(
        cls,
        binding_id: EntityId,
        profile: ModelProfileRevision,
        *,
        qualification_owner_authority: PhaseZeroAuthority | None = None,
        transition: QualifiedProfileTransition | None = None,
    ) -> QualificationBinding:
        if profile.qualification_state not in {ModelQualificationState.EVALUATING, ModelQualificationState.QUALIFIED}:
            raise PermissionError("only evaluating or qualified profiles can be qualification-bound")
        report_sha256: str | None = None
        if profile.qualification_state is ModelQualificationState.QUALIFIED:
            if (
                type(qualification_owner_authority) is not PhaseZeroAuthority
                or type(transition) is not QualifiedProfileTransition
            ):
                raise PermissionError("qualified profile requires an authority-verified qualification transition")
            ProfileQualificationAuthority(qualification_owner_authority).verify_transition(transition, profile)
            report_sha256 = transition.qualification_report_sha256
        elif qualification_owner_authority is not None or transition is not None:
            raise PermissionError("evaluating profile cannot claim a qualification transition")
        return cls(
            binding_id,
            profile.workload_id,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            report_sha256,
        )

    def __post_init__(self) -> None:
        if type(self.binding_id) is not EntityId or self.binding_id.namespace != "model_qualification":
            raise ValueError("qualification binding requires model_qualification identity")
        if type(self.workload_id) is not WorkloadId:
            raise TypeError("qualification binding requires an exact workload id")
        if type(self.profile_id) is not EntityId or self.profile_id.namespace != "model_profile":
            raise ValueError("qualification binding requires model_profile identity")
        if type(self.profile_revision) is not int or self.profile_revision < 1:
            raise ValueError("qualification binding requires a positive profile revision")
        if not re.fullmatch(r"[0-9a-f]{64}", self.profile_sha256):
            raise ValueError("qualification binding requires an exact profile digest")
        if self.qualification_report_sha256 is not None:
            _require_digest(self.qualification_report_sha256, "qualification binding report")
        if self.activation_binding_id is not None:
            raise PermissionError("qualification bindings cannot activate a workload")
        if self.fallback_profile_id is not None or self.reroute_allowed is not False:
            raise PermissionError("qualification bindings forbid fallback and reroute")


@dataclass(frozen=True, slots=True)
class ResolvedQualificationRunConfig:
    """Immutable pre-probe snapshot which is explicitly not ACTIVE."""

    workload_id: WorkloadId
    protocol_family: ModelProtocolFamily
    qualification_binding_id: EntityId
    activation_binding_id: None
    profile_id: EntityId
    profile_revision: int
    profile_sha256: str
    qualification_report_sha256: str | None
    provider: str
    runner_kind: ModelRunnerKind
    authentication_mode: ModelAuthenticationMode
    model_id: str
    reasoning_effort: str
    prompt_binding: str
    output_schema_binding: str
    toolset_binding: str
    capabilities: ModelRunnerCapabilities
    credential_ref: SecretReference | None
    fallback_profile_id: None = None
    reroute_allowed: bool = False
    _proof: InitVar[object] = None

    @classmethod
    def resolve(
        cls,
        binding: QualificationBinding,
        profile: ModelProfileRevision,
    ) -> ResolvedQualificationRunConfig:
        if profile.qualification_state not in {
            ModelQualificationState.EVALUATING,
            ModelQualificationState.QUALIFIED,
        }:
            raise PermissionError("qualification resolution requires evaluating or qualified profile")
        if (
            binding.workload_id != profile.workload_id
            or binding.profile_id != profile.profile_id
            or binding.profile_revision != profile.revision
            or binding.profile_sha256 != profile.content_sha256
        ):
            raise PermissionError("qualification binding does not match the exact model profile revision")
        return cls(
            profile.workload_id,
            profile.protocol_family,
            binding.binding_id,
            None,
            profile.profile_id,
            profile.revision,
            profile.content_sha256,
            binding.qualification_report_sha256,
            profile.provider,
            profile.runner_kind,
            profile.authentication_mode,
            profile.model_id,
            profile.reasoning_effort,
            profile.prompt_binding,
            profile.output_schema_binding,
            profile.toolset_binding,
            profile.capabilities,
            profile.credential_ref,
            _proof=_QUALIFICATION_CONFIG_PROOF,
        )

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _QUALIFICATION_CONFIG_PROOF:
            raise PermissionError("resolved qualification configurations must be factory-issued")
        if type(self.workload_id) is not WorkloadId:
            raise TypeError("resolved qualification config requires an exact workload id")
        if type(self.protocol_family) is not ModelProtocolFamily:
            raise TypeError("resolved qualification config requires an exact signed protocol family")
        if (
            type(self.qualification_binding_id) is not EntityId
            or self.qualification_binding_id.namespace != "model_qualification"
        ):
            raise ValueError("resolved qualification config requires model_qualification identity")
        if self.activation_binding_id is not None:
            raise PermissionError("resolved qualification config cannot be ACTIVE")
        if type(self.profile_id) is not EntityId or self.profile_id.namespace != "model_profile":
            raise ValueError("resolved qualification config requires model_profile identity")
        if type(self.profile_revision) is not int or self.profile_revision < 1:
            raise ValueError("resolved qualification config requires a positive profile revision")
        if not re.fullmatch(r"[0-9a-f]{64}", self.profile_sha256):
            raise ValueError("resolved qualification config requires an exact profile digest")
        if self.qualification_report_sha256 is not None:
            _require_digest(self.qualification_report_sha256, "resolved qualification report")
        if (
            type(self.runner_kind) is not ModelRunnerKind
            or type(self.authentication_mode) is not ModelAuthenticationMode
        ):
            raise TypeError("resolved qualification config requires exact runner and authentication modes")
        if type(self.capabilities) is not ModelRunnerCapabilities:
            raise TypeError("resolved qualification config requires audited runner capabilities")
        if self.fallback_profile_id is not None or self.reroute_allowed is not False:
            raise PermissionError("resolved qualification config forbids fallback and reroute")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "workload_id": str(self.workload_id),
                "protocol_family": self.protocol_family.value,
                "qualification_binding_id": str(self.qualification_binding_id),
                "activation_binding_id": None,
                "profile_id": str(self.profile_id),
                "profile_revision": self.profile_revision,
                "profile_sha256": self.profile_sha256,
                "qualification_report_sha256": self.qualification_report_sha256,
                "provider": self.provider,
                "runner_kind": self.runner_kind.value,
                "authentication_mode": self.authentication_mode.value,
                "model_id": self.model_id,
                "reasoning_effort": self.reasoning_effort,
                "prompt_binding": self.prompt_binding,
                "output_schema_binding": self.output_schema_binding,
                "toolset_binding": self.toolset_binding,
                "capabilities": self.capabilities.payload(),
                "credential_ref": self.credential_ref.uri if self.credential_ref is not None else None,
                "fallback_profile_id": None,
                "reroute_allowed": False,
            }
        )


@dataclass(frozen=True, slots=True)
class ResearchWorkloadBundle:
    """The two independent non-ACTIVE Research workload configurations."""

    hypothesis_synthesis: ResolvedQualificationRunConfig
    preregistration_design: ResolvedQualificationRunConfig

    def __post_init__(self) -> None:
        expected = (
            (self.hypothesis_synthesis, MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD, "medium"),
            (self.preregistration_design, MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD, "medium"),
        )
        for config, workload, effort in expected:
            if type(config) is not ResolvedQualificationRunConfig:
                raise TypeError("research workload bundle requires exact qualification configurations")
            if (
                str(config.workload_id) != workload
                or config.protocol_family is not ModelProtocolFamily.MVP_R_002
                or config.provider != "openai"
                or config.runner_kind is not ModelRunnerKind.CODEX_LOCAL
                or config.authentication_mode is not ModelAuthenticationMode.CHATGPT_SESSION
                or config.model_id != "gpt-5.6-terra"
                or config.reasoning_effort != effort
                or config.toolset_binding != MVP_R_002_EMPTY_TOOLSET_BINDING
                or config.activation_binding_id is not None
                or not all(
                    (
                        config.capabilities.structured_output,
                        config.capabilities.serial_function_tools,
                        config.capabilities.frozen_tool_surface,
                        config.capabilities.actual_model_id,
                        config.capabilities.exact_token_usage,
                        config.capabilities.ephemeral_provider_state,
                    )
                )
            ):
                raise PermissionError("research workload bundle violates the MVP-R-002 qualification policy")
        if self.hypothesis_synthesis.profile_id == self.preregistration_design.profile_id:
            raise ValueError("research workload bundle requires separate profile revisions")
        if (
            self.hypothesis_synthesis.prompt_binding == self.preregistration_design.prompt_binding
            or self.hypothesis_synthesis.output_schema_binding == self.preregistration_design.output_schema_binding
        ):
            raise ValueError("research workload bundle requires separate prompt and schema bindings")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "hypothesis_synthesis": self.hypothesis_synthesis.content_sha256,
                "preregistration_design": self.preregistration_design.content_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class MvpR002QualificationWorkloads:
    """Complete three-profile Phase-0 product qualification surface."""

    research: ResearchWorkloadBundle
    adversarial_critique: ResolvedQualificationRunConfig

    def __post_init__(self) -> None:
        if (
            type(self.research) is not ResearchWorkloadBundle
            or type(self.adversarial_critique) is not ResolvedQualificationRunConfig
        ):
            raise TypeError("MVP-R-002 qualification workloads require exact qualification configurations")
        critic = self.adversarial_critique
        if (
            str(critic.workload_id) != MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD
            or critic.protocol_family is not ModelProtocolFamily.MVP_R_002
            or critic.provider != "openai"
            or critic.runner_kind is not ModelRunnerKind.CODEX_LOCAL
            or critic.authentication_mode is not ModelAuthenticationMode.CHATGPT_SESSION
            or critic.model_id != "gpt-5.6-terra"
            or critic.reasoning_effort != "high"
            or critic.toolset_binding != MVP_R_002_EMPTY_TOOLSET_BINDING
            or critic.activation_binding_id is not None
            or not all(
                (
                    critic.capabilities.structured_output,
                    critic.capabilities.serial_function_tools,
                    critic.capabilities.frozen_tool_surface,
                    critic.capabilities.actual_model_id,
                    critic.capabilities.exact_token_usage,
                    critic.capabilities.ephemeral_provider_state,
                )
            )
        ):
            raise PermissionError("independent Critic violates the MVP-R-002 qualification policy")
        if critic.profile_id in {
            self.research.hypothesis_synthesis.profile_id,
            self.research.preregistration_design.profile_id,
        }:
            raise ValueError("independent Critic requires a separate profile revision")
        if critic.prompt_binding in {
            self.research.hypothesis_synthesis.prompt_binding,
            self.research.preregistration_design.prompt_binding,
        } or critic.output_schema_binding in {
            self.research.hypothesis_synthesis.output_schema_binding,
            self.research.preregistration_design.output_schema_binding,
        }:
            raise ValueError("independent Critic requires separate prompt and schema bindings")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "research": self.research.content_sha256,
                "adversarial_critique": self.adversarial_critique.content_sha256,
            }
        )


MVP_R_REQUIRED_RUNNER_CAPABILITIES = (
    "structured_output",
    "serial_function_tools",
    "frozen_tool_surface",
    "actual_model_id",
    "exact_token_usage",
    "ephemeral_provider_state",
)


def mvp_r_runner_gaps(capabilities: ModelRunnerCapabilities) -> tuple[str, ...]:
    """Return deterministic qualification gaps for the frozen MVP-R protocol."""

    if type(capabilities) is not ModelRunnerCapabilities:
        raise TypeError("MVP-R qualification requires exact runner capabilities")
    return tuple(name for name in MVP_R_REQUIRED_RUNNER_CAPABILITIES if not getattr(capabilities, name))
