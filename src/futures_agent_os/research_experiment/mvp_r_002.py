"""MVP-R-002 Phase 0 immutable, non-trading research-brief contracts."""

from __future__ import annotations

import json
import re
from dataclasses import InitVar, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Mapping, cast

from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_pivot import PIVOT_HYPOTHESIS_FAMILIES, HypothesisFamilyScreen
from .model_routing import PhaseZeroAuthority
from .mvp_validation import HypothesisFamily


_SCHEMA = "mvp-r-002.phase0.v2"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NUMBER = re.compile(r"\d")
_FORBIDDEN_TEXT = re.compile(
    r"future|未来|trade|交易|strategy|策略|order|fill|position|ledger|activation",
    re.I,
)


class ResearchEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class ResearchAction(StrEnum):
    TEST_NEXT = "TEST_NEXT"
    WATCH_FOR_DATA = "WATCH_FOR_DATA"
    REJECT_AS_UNSUPPORTED = "REJECT_AS_UNSUPPORTED"
    DEFER = "DEFER"


class ExperimentReadiness(StrEnum):
    READY = "READY"
    NOT_REQUESTED = "NOT_REQUESTED"


class CriticDecision(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"
    DEFER = "DEFER"


class EvidenceKind(StrEnum):
    ACQUISITION = "ACQUISITION"
    DATASET = "DATASET"
    SCREEN = "SCREEN"
    TOOLSET = "TOOLSET"
    RUNTIME = "RUNTIME"
    PROFILE = "PROFILE"
    PROMPT = "PROMPT"
    SCHEMA = "SCHEMA"
    COST = "COST"
    REPRODUCTION = "REPRODUCTION"
    SOURCE = "SOURCE"
    FAILURE = "FAILURE"
    RESEARCH_INVOCATION = "RESEARCH_INVOCATION"
    RUNTIME_RECEIPT = "RUNTIME_RECEIPT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    RESEARCH_RUN = "RESEARCH_RUN"
    FAULT_INPUT = "FAULT_INPUT"
    FAULT_ROSTER = "FAULT_ROSTER"
    FAULT_CASE = "FAULT_CASE"
    CRITIC_RUN = "CRITIC_RUN"
    EVALUATION_RUN = "EVALUATION_RUN"


class SourcePurpose(StrEnum):
    PIT_RESEARCH_INPUT = "PIT_RESEARCH_INPUT"


class NarrativeCategory(StrEnum):
    SCREENING_SUPPORTS_RESEARCH = "SCREENING_SUPPORTS_RESEARCH"
    INDEPENDENT_WINDOW_UNKNOWN = "INDEPENDENT_WINDOW_UNKNOWN"
    FROZEN_THRESHOLD_RATIONALE = "FROZEN_THRESHOLD_RATIONALE"
    FROZEN_HYPOTHESIS = "FROZEN_HYPOTHESIS"
    DETERMINISTIC_INPUT_UNAVAILABLE = "DETERMINISTIC_INPUT_UNAVAILABLE"
    INPUT_RECOVERY_REEVALUATION = "INPUT_RECOVERY_REEVALUATION"
    FIXED_ABLATION = "FIXED_ABLATION"
    ABLATION_COUNTERFACTUAL = "ABLATION_COUNTERFACTUAL"


class EvaluationScenarioKind(StrEnum):
    CLEAN = "CLEAN"
    FAULT_INJECTION = "FAULT_INJECTION"


class FaultCategory(StrEnum):
    FUTURE_LEAK = "FUTURE_LEAK"
    FORGED_SOURCE = "FORGED_SOURCE"
    UNAUTHORIZED_ACTION = "UNAUTHORIZED_ACTION"
    TRADING_REQUEST = "TRADING_REQUEST"


class FaultFailureCode(StrEnum):
    SOURCE_SCHEMA_REJECTED = "SOURCE_SCHEMA_REJECTED"
    SOURCE_REFERENCE_REJECTED = "SOURCE_REFERENCE_REJECTED"
    ACTION_AUTHORITY_REJECTED = "ACTION_AUTHORITY_REJECTED"
    NARRATIVE_REJECTED = "NARRATIVE_REJECTED"
    CASE_SCHEMA_MISMATCH = "CASE_SCHEMA_MISMATCH"


@dataclass(frozen=True, slots=True)
class FaultCase:
    category: FaultCategory
    fault_roster_sha256: str
    original_input_sha256: str
    mutated_input_sha256: str
    expected_failure: FaultFailureCode

    def __post_init__(self) -> None:
        if type(self.category) is not FaultCategory or type(self.expected_failure) is not FaultFailureCode:
            raise TypeError("fault case category must be closed")
        _digest(self.original_input_sha256, "fault original input")
        _digest(self.mutated_input_sha256, "fault mutated input")
        _digest(self.fault_roster_sha256, "fault roster")
        expected = {
            FaultCategory.FUTURE_LEAK: FaultFailureCode.SOURCE_SCHEMA_REJECTED,
            FaultCategory.FORGED_SOURCE: FaultFailureCode.SOURCE_REFERENCE_REJECTED,
            FaultCategory.UNAUTHORIZED_ACTION: FaultFailureCode.ACTION_AUTHORITY_REJECTED,
            FaultCategory.TRADING_REQUEST: FaultFailureCode.NARRATIVE_REJECTED,
        }[self.category]
        if self.expected_failure is not expected:
            raise PermissionError("fault case expected failure does not match its closed category")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "fault_roster_sha256": self.fault_roster_sha256,
            "original_input_sha256": self.original_input_sha256,
            "mutated_input_sha256": self.mutated_input_sha256,
            "expected_failure": self.expected_failure.value,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> FaultCase:
        _keys(
            value,
            {"category", "fault_roster_sha256", "original_input_sha256", "mutated_input_sha256", "expected_failure"},
            "fault case",
        )
        return cls(
            FaultCategory(_text(value["category"], "fault category")),
            _text(value["fault_roster_sha256"], "fault roster"),
            _text(value["original_input_sha256"], "fault original input"),
            _text(value["mutated_input_sha256"], "fault mutated input"),
            FaultFailureCode(_text(value["expected_failure"], "fault expected failure")),
        )


_NARRATIVE_TEXT: Mapping[NarrativeCategory, str] = {
    NarrativeCategory.SCREENING_SUPPORTS_RESEARCH: "冻结来源支持继续研究",
    NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN: "独立窗口结果仍未知",
    NarrativeCategory.FROZEN_THRESHOLD_RATIONALE: "按冻结门槛映射研究处置",
    NarrativeCategory.FROZEN_HYPOTHESIS: "若独立窗口未通过冻结门槛则命题不成立",
    NarrativeCategory.DETERMINISTIC_INPUT_UNAVAILABLE: "确定性输入不可用",
    NarrativeCategory.INPUT_RECOVERY_REEVALUATION: "输入恢复后可重新评估",
    NarrativeCategory.FIXED_ABLATION: "固定消融处置",
    NarrativeCategory.ABLATION_COUNTERFACTUAL: "该基线不使用候选差异",
}


class ProposalIntent(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"


def _validate_action_authority(
    eligibility: ResearchEligibility,
    action: ResearchAction,
    *,
    deterministic_failure: bool = False,
) -> None:
    """The one closed action gate used before an action becomes authoritative."""

    if deterministic_failure:
        if action is not ResearchAction.DEFER:
            raise PermissionError("deterministic failure authority only permits DEFER")
        return
    permitted = {
        ResearchEligibility.ELIGIBLE: {
            ResearchAction.TEST_NEXT,
            ResearchAction.WATCH_FOR_DATA,
            ResearchAction.REJECT_AS_UNSUPPORTED,
        },
        ResearchEligibility.INSUFFICIENT_EVIDENCE: {
            ResearchAction.WATCH_FOR_DATA,
            ResearchAction.REJECT_AS_UNSUPPORTED,
        },
        ResearchEligibility.REJECTED: {ResearchAction.REJECT_AS_UNSUPPORTED},
    }
    if action not in permitted[eligibility]:
        raise PermissionError("action violates the deterministic eligibility matrix")


def _critic_action(
    eligibility: ResearchEligibility, decision: CriticDecision, agent_action: ResearchAction
) -> ResearchAction:
    requested = {
        CriticDecision.PASS: agent_action,
        CriticDecision.REVISE: ResearchAction.WATCH_FOR_DATA,
        CriticDecision.REJECT: ResearchAction.REJECT_AS_UNSUPPORTED,
        CriticDecision.DEFER: ResearchAction.WATCH_FOR_DATA,
    }[decision]
    try:
        _validate_action_authority(eligibility, requested)
    except PermissionError:
        requested = ResearchAction.REJECT_AS_UNSUPPORTED
    _validate_action_authority(eligibility, requested)
    return requested


def _digest(value: object, label: str = "digest") -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ValueError(f"{label} must be a canonical SHA-256 digest")
    return value


def _text(value: object, label: str, *, model_text: bool = False) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError(f"{label} must be exact non-empty text")
    if model_text and (_NUMBER.search(value) or _FORBIDDEN_TEXT.search(value)):
        raise PermissionError(f"{label} contains a numeric, future, trading, or governance claim")
    return value


def _narrative(value: object, label: str) -> str:
    """Accept only a closed semantic category for model-authored narrative."""

    if type(value) is not NarrativeCategory:
        raise PermissionError(f"{label} must use a closed narrative category")
    return _NARRATIVE_TEXT[value]


def _closed_narrative_text(value: object, label: str) -> str:
    text = _text(value, label)
    if text not in _NARRATIVE_TEXT.values():
        raise PermissionError(f"{label} is not a closed narrative rendering")
    return text


def _array(value: object, label: str) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise TypeError(f"{label} must be an array")
    return tuple(cast(tuple[object, ...] | list[object], value))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{label} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _json_value(value: object, label: str = "JSON value") -> JsonValue:
    """Restore immutable JSON values after decoding canonical evidence bytes."""

    if value is None or type(value) in (str, int, bool):
        return cast(JsonValue, value)
    if type(value) is list:
        return tuple(_json_value(item, label) for item in cast(list[object], value))
    if isinstance(value, Mapping):
        mapping = _mapping(value, label)
        return {key: _json_value(item, label) for key, item in mapping.items()}
    raise TypeError(f"{label} must be finite JSON-compatible data")


def _keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} contains missing or unexpected keys")


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{label} must be an exact boolean")
    return value


def _pointer(pointer: str) -> tuple[str, ...]:
    if type(pointer) is not str or not pointer.startswith("/"):
        raise ValueError("source pointer must be a non-root RFC6901 pointer")
    result: list[str] = []
    for segment in pointer[1:].split("/"):
        index = 0
        output = ""
        while index < len(segment):
            if segment[index] != "~":
                output += segment[index]
                index += 1
            elif index + 1 < len(segment) and segment[index + 1] in "01":
                output += "~" if segment[index + 1] == "0" else "/"
                index += 2
            else:
                raise ValueError("source pointer has invalid RFC6901 escaping")
        if output == "future_label":
            raise PermissionError("future labels cannot be referenced by MVP-R-002")
        result.append(output)
    return tuple(result)


def _utc_datetime(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _screen(value: Mapping[str, object]) -> HypothesisFamilyScreen:
    _keys(
        value,
        {
            "family",
            "cutoff_direction",
            "signal_count",
            "signal_accuracy",
            "net_return",
            "stressed_net_return",
            "positive_fold_ratio",
        },
        "hypothesis family screen",
    )
    try:
        metrics = tuple(
            Decimal(_text(value[name], name))
            for name in ("signal_accuracy", "net_return", "stressed_net_return", "positive_fold_ratio")
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("screen metrics must be canonical decimals") from error
    return HypothesisFamilyScreen(
        HypothesisFamily(_text(value["family"], "screen family")),
        _integer(value["cutoff_direction"], "screen direction"),
        _integer(value["signal_count"], "screen signal count", minimum=0),
        *metrics,
    )


class RuntimeInputKind(StrEnum):
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    EXPERIMENT_BINDING = "EXPERIMENT_BINDING"
    CRITIC_INVOCATION = "CRITIC_INVOCATION"
    AGENT_OUTCOME = "AGENT_OUTCOME"
    RESEARCH_RUN = "RESEARCH_RUN"
    RESEARCH_BRIEF = "RESEARCH_BRIEF"


@dataclass(frozen=True, slots=True)
class RuntimeInputRef:
    """One typed, content-addressed input consumed by a model invocation."""

    kind: RuntimeInputKind
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.kind) is not RuntimeInputKind:
            raise TypeError("runtime input kind must be closed")
        _digest(self.content_sha256, "runtime input")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"kind": self.kind.value, "content_sha256": self.content_sha256}

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> RuntimeInputRef:
        _keys(value, {"kind", "content_sha256"}, "runtime input reference")
        return cls(
            RuntimeInputKind(_text(value["kind"], "runtime input kind")),
            _text(value["content_sha256"], "runtime input digest"),
        )


@dataclass(frozen=True, slots=True)
class RuntimeAssetRef:
    """One identity for the assembled bytes and their owner-signed envelope."""

    asset_sha256: str
    owner_evidence_sha256: str

    def __post_init__(self) -> None:
        _digest(self.asset_sha256, "runtime asset")
        _digest(self.owner_evidence_sha256, "runtime asset owner evidence")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "asset_sha256": self.asset_sha256,
            "owner_evidence_sha256": self.owner_evidence_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> RuntimeAssetRef:
        _keys(value, {"asset_sha256", "owner_evidence_sha256"}, "runtime asset reference")
        return cls(
            _text(value["asset_sha256"], "runtime asset"),
            _text(value["owner_evidence_sha256"], "runtime asset owner evidence"),
        )


_RUNTIME_OWNER_BINDING_PROOF = object()


@dataclass(frozen=True, slots=True)
class RuntimeOwnerBinding:
    """Typed bridge between exact runtime bytes and domain evidence ids."""

    workload_id: str
    asset_ref: RuntimeAssetRef
    profile_ref: RuntimeAssetRef
    prompt_ref: RuntimeAssetRef
    schema_ref: RuntimeAssetRef
    toolset_ref: RuntimeAssetRef
    runtime_ref: RuntimeAssetRef
    _proof: InitVar[object]

    def __post_init__(self, _proof: object) -> None:
        if _proof is not _RUNTIME_OWNER_BINDING_PROOF:
            raise PermissionError("runtime owner bindings must be hydrated and frozen-asset verified")
        if self.workload_id not in _RUNTIME_WORKLOADS:
            raise ValueError("runtime owner binding workload must be closed")
        if any(
            type(value) is not RuntimeAssetRef
            for value in (
                self.asset_ref,
                self.profile_ref,
                self.prompt_ref,
                self.schema_ref,
                self.toolset_ref,
                self.runtime_ref,
            )
        ):
            raise TypeError("runtime owner binding requires exact component references")

    @property
    def owner_digests(self) -> tuple[str, str, str, str, str]:
        return (
            self.profile_ref.owner_evidence_sha256,
            self.prompt_ref.owner_evidence_sha256,
            self.schema_ref.owner_evidence_sha256,
            self.toolset_ref.owner_evidence_sha256,
            self.runtime_ref.owner_evidence_sha256,
        )

    @property
    def inner_digests(self) -> tuple[str, str, str, str, str]:
        return tuple(
            value.asset_sha256
            for value in (
                self.profile_ref,
                self.prompt_ref,
                self.schema_ref,
                self.toolset_ref,
                self.runtime_ref,
            )
        )  # type: ignore[return-value]

    @property
    def profile_sha256(self) -> str:
        return self.profile_ref.owner_evidence_sha256

    @property
    def prompt_sha256(self) -> str:
        return self.prompt_ref.owner_evidence_sha256

    @property
    def schema_sha256(self) -> str:
        return self.schema_ref.owner_evidence_sha256

    @property
    def toolset_sha256(self) -> str:
        return self.toolset_ref.owner_evidence_sha256

    @property
    def runtime_sha256(self) -> str:
        return self.runtime_ref.owner_evidence_sha256

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "workload_id": self.workload_id,
            "asset_ref": self.asset_ref.to_dict(),
            "profile_ref": self.profile_ref.to_dict(),
            "prompt_ref": self.prompt_ref.to_dict(),
            "schema_ref": self.schema_ref.to_dict(),
            "toolset_ref": self.toolset_ref.to_dict(),
            "runtime_ref": self.runtime_ref.to_dict(),
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> RuntimeOwnerBinding:
        _keys(value, set(cls.__dataclass_fields__) - {"_proof"}, "runtime owner binding")
        return cls(
            _text(value["workload_id"], "runtime owner workload"),
            RuntimeAssetRef.hydrate(_mapping(value["asset_ref"], "runtime asset reference")),
            RuntimeAssetRef.hydrate(_mapping(value["profile_ref"], "runtime profile reference")),
            RuntimeAssetRef.hydrate(_mapping(value["prompt_ref"], "runtime prompt reference")),
            RuntimeAssetRef.hydrate(_mapping(value["schema_ref"], "runtime schema reference")),
            RuntimeAssetRef.hydrate(_mapping(value["toolset_ref"], "runtime toolset reference")),
            RuntimeAssetRef.hydrate(_mapping(value["runtime_ref"], "runtime identity reference")),
            _RUNTIME_OWNER_BINDING_PROOF,
        )


_RUNTIME_WORKLOADS = {
    "research.hypothesis_synthesis",
    "experiment.preregistration_design",
    "assurance.adversarial_critique",
}
_RUNTIME_FAILURE_CODES = {
    "CONFIG_NOT_QUALIFIED",
    "INPUT_REJECTED",
    "PROVIDER_CALL_FAILED",
    "PROVIDER_MISMATCH",
    "MODEL_DRIFT",
    "EFFORT_DRIFT",
    "REROUTE_REJECTED",
    "ACTIVITY_REJECTED",
    "TURN_INCOMPLETE",
    "USAGE_INCOMPLETE",
    "FINAL_COUNT_INVALID",
    "RESPONSE_INVALID_JSON",
    "RESPONSE_SCHEMA_INVALID",
}
_RUNTIME_FAILURE_STAGES = {"PRE_FLIGHT", "PROVIDER", "OBSERVATION", "RESPONSE"}


@dataclass(frozen=True, slots=True)
class RuntimeReceiptPayload:
    """Owner-signed runtime truth, independent of the runtime adapter module.

    Keeping this wire contract in the domain module lets the owner registry
    strictly hydrate receipts without importing the adapter that produces
    them.  RuntimeReceiptRef below is the only downstream reference shape, so
    receipts never hash an artifact that already contains their own digest.
    """

    workload_id: str
    invocation_id: str
    run_id: str
    subject_sha256: str
    input_lineage: tuple[RuntimeInputRef, ...]
    qualification_report_sha256: str
    config_sha256: str
    asset_ref: RuntimeAssetRef
    profile_sha256: str
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    raw_request_sha256: str
    canonical_request_sha256: str
    raw_response_sha256: str | None
    canonical_response_sha256: str | None
    response_id: str | None
    requested_model_id: str
    requested_reasoning_effort: str
    actual_provider: str | None
    actual_model_id: str | None
    actual_reasoning_effort: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cache_write_input_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    reroute_sha256s: tuple[str, ...]
    activity_sha256s: tuple[str, ...]
    status: str
    failure_code: str | None
    failure_stage: str | None
    cost_mode: str
    cost_available: bool
    cost_amount: None
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.workload_id not in _RUNTIME_WORKLOADS:
            raise ValueError("runtime receipt workload must be closed")
        for text_value, label in (
            (self.invocation_id, "runtime invocation"),
            (self.run_id, "runtime run"),
            (self.requested_model_id, "requested model"),
            (self.requested_reasoning_effort, "requested effort"),
        ):
            _text(text_value, label)
        if not self.input_lineage or any(type(item) is not RuntimeInputRef for item in self.input_lineage):
            raise ValueError("runtime receipt needs typed input lineage")
        identities = tuple((item.kind, item.content_sha256) for item in self.input_lineage)
        if len(set(identities)) != len(identities):
            raise ValueError("runtime input lineage must be unique")
        for digest_value in (
            self.subject_sha256,
            self.qualification_report_sha256,
            self.config_sha256,
            self.asset_ref.asset_sha256,
            self.asset_ref.owner_evidence_sha256,
            self.profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
            self.raw_request_sha256,
            self.canonical_request_sha256,
            self.content_sha256,
            self.signature_sha256,
            self.raw_response_sha256,
            self.canonical_response_sha256,
            *self.reroute_sha256s,
            *self.activity_sha256s,
        ):
            if digest_value is not None:
                _digest(digest_value, "runtime receipt binding")
        if self.status not in {"COMPLETED", "FAILED"}:
            raise ValueError("runtime receipt status must be closed")
        failure_code = None if self.failure_code is None else str(self.failure_code)
        failure_stage = None if self.failure_stage is None else str(self.failure_stage)
        if (self.status == "COMPLETED") != (failure_code is None):
            raise ValueError("runtime receipt status/failure is incongruent")
        if self.status == "COMPLETED" and failure_stage is not None:
            raise ValueError("completed receipt cannot have failure stage")
        if self.status == "FAILED" and (
            failure_code not in _RUNTIME_FAILURE_CODES or failure_stage not in _RUNTIME_FAILURE_STAGES
        ):
            raise ValueError("failed receipt needs a closed failure code and stage")
        if any(value is not None and (type(value) is not int or value < 0) for value in self.usage):
            raise ValueError("runtime receipt usage must be exact non-negative integers")
        if None not in self.usage:
            assert self.input_tokens is not None
            assert self.cached_input_tokens is not None
            assert self.output_tokens is not None
            assert self.reasoning_tokens is not None
            assert self.cache_write_input_tokens is not None
            assert self.total_tokens is not None
            if (
                self.cached_input_tokens > self.input_tokens
                or self.reasoning_tokens > self.output_tokens
                or self.cache_write_input_tokens > self.input_tokens
                or self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens
                or self.total_tokens != self.input_tokens + self.output_tokens
            ):
                raise ValueError("runtime receipt usage relationships are impossible")
        if self.status == "COMPLETED" and (
            None in self.usage
            or self.response_id is None
            or self.actual_provider is None
            or self.actual_model_id is None
            or self.actual_reasoning_effort is None
            or self.raw_response_sha256 is None
            or self.canonical_response_sha256 is None
        ):
            raise ValueError("completed receipt needs a complete observed response")
        for optional_text, label in (
            (self.response_id, "response id"),
            (self.actual_provider, "actual provider"),
            (self.actual_model_id, "actual model"),
            (self.actual_reasoning_effort, "actual effort"),
        ):
            if optional_text is not None:
                _text(optional_text, label)
        if str(self.cost_mode) != "SUBSCRIPTION_UNAVAILABLE" or self.cost_available or self.cost_amount is not None:
            raise PermissionError("R-002 receipts only allow unavailable subscription cost")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("runtime receipt digest is invalid")

    @property
    def usage(self) -> tuple[int | None, ...]:
        return (
            self.input_tokens,
            self.cached_input_tokens,
            self.output_tokens,
            self.reasoning_tokens,
            self.cache_write_input_tokens,
            self.total_tokens,
            self.latency_ms,
        )

    def unsigned_payload(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for name in self.__dataclass_fields__:
            if name in {"content_sha256", "signature_sha256"}:
                continue
            value = getattr(self, name)
            if name == "input_lineage":
                result[name] = tuple(item.to_dict() for item in self.input_lineage)
            elif name == "asset_ref":
                result[name] = self.asset_ref.to_dict()
            else:
                result[name] = cast(JsonValue, value.value if isinstance(value, StrEnum) else value)
        return result

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> RuntimeReceiptPayload:
        _keys(value, set(cls.__dataclass_fields__), "runtime receipt")
        values = dict(value)
        values["input_lineage"] = tuple(
            RuntimeInputRef.hydrate(_mapping(item, "runtime input"))
            for item in _array(values["input_lineage"], "runtime inputs")
        )
        values["asset_ref"] = RuntimeAssetRef.hydrate(_mapping(values["asset_ref"], "runtime asset reference"))
        values["reroute_sha256s"] = tuple(
            _text(item, "reroute") for item in _array(values["reroute_sha256s"], "reroutes")
        )
        values["activity_sha256s"] = tuple(
            _text(item, "activity") for item in _array(values["activity_sha256s"], "activities")
        )
        receipt = cls(**values)  # type: ignore[arg-type]
        if not authority.verify(receipt.unsigned_payload(), receipt.signature_sha256):
            raise PermissionError("runtime receipt signature is invalid")
        return receipt


@dataclass(frozen=True, slots=True)
class RuntimeReceiptRef:
    evidence_sha256: str
    receipt_sha256: str
    workload_id: str
    invocation_id: str
    run_id: str
    response_id: str | None

    def __post_init__(self) -> None:
        _digest(self.evidence_sha256, "runtime receipt evidence")
        _digest(self.receipt_sha256, "runtime receipt")
        if self.workload_id not in _RUNTIME_WORKLOADS:
            raise ValueError("runtime receipt reference workload must be closed")
        _text(self.invocation_id, "runtime receipt reference invocation")
        _text(self.run_id, "runtime receipt reference run")
        if self.response_id is not None:
            _text(self.response_id, "runtime receipt reference response")

    @classmethod
    def from_payload(cls, evidence_sha256: str, receipt: RuntimeReceiptPayload) -> RuntimeReceiptRef:
        return cls(
            evidence_sha256,
            receipt.content_sha256,
            receipt.workload_id,
            receipt.invocation_id,
            receipt.run_id,
            receipt.response_id,
        )


@dataclass(frozen=True, slots=True)
class ResearchInvocationAuthorization:
    """One pre-authorized, append-only Phase-0 research invocation."""

    candidate_sha256: str
    workload_id: str
    request_sha256: str
    profile_sha256: str
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    invocation_id: str
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.workload_id != "research.hypothesis_synthesis":
            raise PermissionError("Phase-0 invocation only authorizes research hypothesis synthesis")
        for value in (
            self.candidate_sha256,
            self.request_sha256,
            self.profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
        ):
            _digest(value, "invocation binding")
        _text(self.invocation_id, "invocation id")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("research invocation authorization digest is invalid")
        _digest(self.signature_sha256, "research invocation authorization signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "candidate_sha256": self.candidate_sha256,
            "workload_id": self.workload_id,
            "request_sha256": self.request_sha256,
            "profile_sha256": self.profile_sha256,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
            "invocation_id": self.invocation_id,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def issue(
        cls,
        authority: PhaseZeroAuthority,
        *,
        candidate_sha256: str,
        request_sha256: str,
        profile_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        toolset_sha256: str,
        runtime_sha256: str,
        invocation_id: str,
    ) -> ResearchInvocationAuthorization:
        payload: dict[str, JsonValue] = {
            "candidate_sha256": candidate_sha256,
            "workload_id": "research.hypothesis_synthesis",
            "request_sha256": request_sha256,
            "profile_sha256": profile_sha256,
            "prompt_sha256": prompt_sha256,
            "schema_sha256": schema_sha256,
            "toolset_sha256": toolset_sha256,
            "runtime_sha256": runtime_sha256,
            "invocation_id": invocation_id,
        }
        return cls(
            candidate_sha256,
            "research.hypothesis_synthesis",
            request_sha256,
            profile_sha256,
            prompt_sha256,
            schema_sha256,
            toolset_sha256,
            runtime_sha256,
            invocation_id,
            canonical_sha256(payload),
            authority.sign(payload),
        )

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> ResearchInvocationAuthorization:
        _keys(value, set(cls.__dataclass_fields__), "research invocation authorization")
        authorization = cls(
            _text(value["candidate_sha256"], "invocation candidate"),
            _text(value["workload_id"], "invocation workload"),
            _text(value["request_sha256"], "invocation request"),
            _text(value["profile_sha256"], "invocation profile"),
            _text(value["prompt_sha256"], "invocation prompt"),
            _text(value["schema_sha256"], "invocation schema"),
            _text(value["toolset_sha256"], "invocation toolset"),
            _text(value["runtime_sha256"], "invocation runtime"),
            _text(value["invocation_id"], "invocation id"),
            _text(value["content_sha256"], "invocation content"),
            _text(value["signature_sha256"], "invocation signature"),
        )
        if not authority.verify(authorization.unsigned_payload(), authorization.signature_sha256):
            raise PermissionError("research invocation authorization signature is invalid")
        return authorization


@dataclass(frozen=True, slots=True)
class SourceReference:
    artifact_sha256: str
    json_pointer: str
    label: str

    def __post_init__(self) -> None:
        _digest(self.artifact_sha256, "source artifact")
        _pointer(self.json_pointer)
        _text(self.label, "source label")

    def identity(self) -> tuple[str, str]:
        return self.artifact_sha256, self.json_pointer

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "json_pointer": self.json_pointer,
            "label": self.label,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> SourceReference:
        _keys(value, {"artifact_sha256", "json_pointer", "label"}, "source reference")
        return cls(
            _text(value["artifact_sha256"], "artifact"),
            _text(value["json_pointer"], "pointer"),
            _text(value["label"], "label"),
        )


@dataclass(frozen=True, slots=True)
class FaultInput:
    """Owner-signed, closed input snapshot used only for deterministic fault replay."""

    category: FaultCategory
    source_ref: SourceReference
    source_purpose: str
    eligibility: ResearchEligibility
    action: ResearchAction
    narrative: str

    def __post_init__(self) -> None:
        if type(self.category) is not FaultCategory or type(self.source_ref) is not SourceReference:
            raise TypeError("fault input requires closed category and typed source reference")
        if type(self.eligibility) is not ResearchEligibility or type(self.action) is not ResearchAction:
            raise TypeError("fault input requires closed authority enums")
        _text(self.source_purpose, "fault source purpose")
        _text(self.narrative, "fault narrative")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "source_ref": self.source_ref.to_dict(),
            "source_purpose": self.source_purpose,
            "eligibility": self.eligibility.value,
            "action": self.action.value,
            "narrative": self.narrative,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> FaultInput:
        _keys(
            value,
            {"category", "source_ref", "source_purpose", "eligibility", "action", "narrative"},
            "fault input",
        )
        return cls(
            FaultCategory(_text(value["category"], "fault category")),
            SourceReference.hydrate(_mapping(value["source_ref"], "fault source reference")),
            _text(value["source_purpose"], "fault source purpose"),
            ResearchEligibility(_text(value["eligibility"], "fault eligibility")),
            ResearchAction(_text(value["action"], "fault action")),
            _text(value["narrative"], "fault narrative"),
        )


@dataclass(frozen=True, slots=True)
class FrozenFaultRoster:
    """Pre-signed synthetic fault suite; unrelated to any market-data roster."""

    suite_id: str
    candidate_sha256: str
    evaluator_schema_version: str
    entries: tuple[tuple[FaultCategory, str, str], ...]
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        _text(self.suite_id, "fault suite")
        _digest(self.candidate_sha256, "fault suite candidate")
        if self.evaluator_schema_version != _SCHEMA:
            raise ValueError("fault roster evaluator version is invalid")
        if len(self.entries) != len(FaultCategory) or {entry[0] for entry in self.entries} != set(FaultCategory):
            raise ValueError("fault roster must pre-authorize each closed category exactly once")
        for category, original, mutated in self.entries:
            if type(category) is not FaultCategory:
                raise TypeError("fault roster category must be closed")
            _digest(original, "fault roster original input")
            _digest(mutated, "fault roster mutated input")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("fault roster digest is invalid")
        _digest(self.signature_sha256, "fault roster signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "suite_id": self.suite_id,
            "candidate_sha256": self.candidate_sha256,
            "evaluator_schema_version": self.evaluator_schema_version,
            "entries": tuple(
                {"category": category.value, "original_input_sha256": original, "mutated_input_sha256": mutated}
                for category, original, mutated in self.entries
            ),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def issue(
        cls,
        authority: PhaseZeroAuthority,
        *,
        suite_id: str,
        candidate_sha256: str,
        entries: tuple[tuple[FaultCategory, str, str], ...],
    ) -> FrozenFaultRoster:
        payload: dict[str, JsonValue] = {
            "suite_id": suite_id,
            "candidate_sha256": candidate_sha256,
            "evaluator_schema_version": _SCHEMA,
            "entries": tuple(
                {"category": category.value, "original_input_sha256": original, "mutated_input_sha256": mutated}
                for category, original, mutated in entries
            ),
        }
        return cls(suite_id, candidate_sha256, _SCHEMA, entries, canonical_sha256(payload), authority.sign(payload))

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> FrozenFaultRoster:
        _keys(
            value,
            {
                "suite_id",
                "candidate_sha256",
                "evaluator_schema_version",
                "entries",
                "content_sha256",
                "signature_sha256",
            },
            "fault roster",
        )
        parsed_entries: list[tuple[FaultCategory, str, str]] = []
        for item in _array(value["entries"], "fault roster entries"):
            entry = _mapping(item, "fault roster entry")
            _keys(entry, {"category", "original_input_sha256", "mutated_input_sha256"}, "fault roster entry")
            parsed_entries.append(
                (
                    FaultCategory(_text(entry["category"], "fault roster category")),
                    _text(entry["original_input_sha256"], "fault roster original"),
                    _text(entry["mutated_input_sha256"], "fault roster mutated"),
                )
            )
        entries = tuple(parsed_entries)
        roster = cls(
            _text(value["suite_id"], "fault suite"),
            _text(value["candidate_sha256"], "fault candidate"),
            _text(value["evaluator_schema_version"], "fault evaluator version"),
            entries,
            _text(value["content_sha256"], "fault roster content"),
            _text(value["signature_sha256"], "fault roster signature"),
        )
        if not authority.verify(roster.unsigned_payload(), roster.signature_sha256):
            raise PermissionError("fault roster signature is invalid")
        return roster


@dataclass(frozen=True, slots=True)
class SourceRecord:
    event_time: str
    available_time: str
    close: str
    component_id: str
    revision: str

    def __post_init__(self) -> None:
        if _utc_datetime(self.available_time, "record available time") < _utc_datetime(
            self.event_time, "record event time"
        ):
            raise PermissionError("source record cannot be available before its event")
        close = Decimal(_text(self.close, "record close"))
        if not close.is_finite() or close <= 0 or format(close, "f") != self.close:
            raise ValueError("record close must be a finite positive canonical decimal")
        _text(self.component_id, "record component")
        _text(self.revision, "record revision")

    def identity(self, instrument_id: str) -> tuple[str, str, datetime]:
        """Natural observation identity: revisions cannot create additional bars."""

        return instrument_id, self.component_id, _utc_datetime(self.event_time, "record event time")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "event_time": self.event_time,
            "available_time": self.available_time,
            "close": self.close,
            "component_id": self.component_id,
            "revision": self.revision,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> SourceRecord:
        _keys(value, {"event_time", "available_time", "close", "component_id", "revision"}, "source record")
        return cls(
            _text(value["event_time"], "record event time"),
            _text(value["available_time"], "record available time"),
            _text(value["close"], "record close"),
            _text(value["component_id"], "record component"),
            _text(value["revision"], "record revision"),
        )


@dataclass(frozen=True, slots=True)
class SourceManifest:
    purpose: SourcePurpose
    instrument_id: str
    market_cutoff: str
    acquired_at: str
    records: tuple[SourceRecord, ...]

    def __post_init__(self) -> None:
        if type(self.purpose) is not SourcePurpose or self.purpose is not SourcePurpose.PIT_RESEARCH_INPUT:
            raise PermissionError("source purpose must be the closed PIT research-input purpose")
        _text(self.instrument_id, "source instrument")
        cutoff = _utc_datetime(self.market_cutoff, "source cutoff")
        acquired = _utc_datetime(self.acquired_at, "source acquired")
        if cutoff > acquired:
            raise PermissionError("source manifest cutoff cannot follow acquisition")
        if not self.records or any(type(record) is not SourceRecord for record in self.records):
            raise TypeError("source manifest requires non-empty typed records")
        if any(_utc_datetime(record.available_time, "record available time") > cutoff for record in self.records):
            raise PermissionError("source manifest violates point-in-time availability")
        identities = tuple(record.identity(self.instrument_id) for record in self.records)
        if len(set(identities)) != len(identities):
            raise ValueError("source manifest records must have unique natural identities")
        if identities != tuple(sorted(identities, key=lambda value: value[2])):
            raise ValueError("source manifest records must be canonical chronological order")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "purpose": self.purpose.value,
            "instrument_id": self.instrument_id,
            "market_cutoff": self.market_cutoff,
            "acquired_at": self.acquired_at,
            "records": tuple(record.to_dict() for record in self.records),
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> SourceManifest:
        _keys(value, {"purpose", "instrument_id", "market_cutoff", "acquired_at", "records"}, "source manifest")
        return cls(
            SourcePurpose(_text(value["purpose"], "source purpose")),
            _text(value["instrument_id"], "source instrument"),
            _text(value["market_cutoff"], "source cutoff"),
            _text(value["acquired_at"], "source acquired"),
            tuple(
                SourceRecord.hydrate(_mapping(record, "source record"))
                for record in _array(value["records"], "source records")
            ),
        )


@dataclass(frozen=True, slots=True)
class FrozenProfileQualification:
    provider: str
    model_id: str
    profile_id: str
    workload_id: str
    asset_sha256: str
    status: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "profile provider"),
            (self.model_id, "profile model"),
            (self.profile_id, "profile id"),
        ):
            _text(value, label)
        if self.workload_id not in _RUNTIME_WORKLOADS:
            raise ValueError("profile workload must be closed")
        _digest(self.asset_sha256, "frozen profile bytes")
        if self.status != "FROZEN":
            raise PermissionError("only frozen profile qualifications can enter Phase 0")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "profile_id": self.profile_id,
            "workload_id": self.workload_id,
            "asset_sha256": self.asset_sha256,
            "status": self.status,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> FrozenProfileQualification:
        _keys(value, {"provider", "model_id", "profile_id", "workload_id", "asset_sha256", "status"}, "frozen profile")
        return cls(
            _text(value["provider"], "profile provider"),
            _text(value["model_id"], "profile model"),
            _text(value["profile_id"], "profile id"),
            _text(value["workload_id"], "profile workload"),
            _text(value["asset_sha256"], "profile bytes"),
            _text(value["status"], "profile status"),
        )


@dataclass(frozen=True, slots=True)
class OwnerEvidenceArtifact:
    kind: EvidenceKind
    issuer: str
    payload_json: str
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if type(self.kind) is not EvidenceKind:
            raise TypeError("evidence kind must be closed")
        _text(self.issuer, "evidence issuer")
        _text(self.payload_json, "evidence payload JSON")
        _digest(self.content_sha256, "evidence content")
        _digest(self.signature_sha256, "evidence signature")
        parsed = self.payload()
        if canonical_json_text(parsed) != self.payload_json or canonical_sha256(parsed) != self.content_sha256:
            raise ValueError("evidence payload must be canonical and content-addressed")

    def payload(self) -> Mapping[str, JsonValue]:
        try:
            value = json.loads(self.payload_json)
        except json.JSONDecodeError as error:
            raise ValueError("evidence payload is invalid canonical JSON") from error
        return cast(Mapping[str, JsonValue], _mapping(_json_value(value, "evidence payload"), "evidence payload"))

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "issuer": self.issuer,
            "payload_json": self.payload_json,
            "content_sha256": self.content_sha256,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {**self.unsigned_payload(), "signature_sha256": self.signature_sha256}

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> OwnerEvidenceArtifact:
        _keys(value, {"kind", "issuer", "payload_json", "content_sha256", "signature_sha256"}, "owner evidence")
        artifact = cls(
            EvidenceKind(_text(value["kind"], "kind")),
            _text(value["issuer"], "issuer"),
            _text(value["payload_json"], "payload JSON"),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(artifact.unsigned_payload(), artifact.signature_sha256):
            raise PermissionError("owner evidence signature is invalid")
        return artifact


class OwnerEvidenceIssuer:
    def __init__(self, authority: PhaseZeroAuthority, issuer: str) -> None:
        self._authority = authority
        self._issuer = _text(issuer, "issuer")

    def issue(self, kind: EvidenceKind, payload: Mapping[str, JsonValue]) -> OwnerEvidenceArtifact:
        if type(kind) is not EvidenceKind:
            raise TypeError("evidence issuer requires a closed kind")
        payload_json = canonical_json_text(payload)
        content_sha256 = canonical_sha256(payload)
        unsigned: dict[str, JsonValue] = {
            "kind": kind.value,
            "issuer": self._issuer,
            "payload_json": payload_json,
            "content_sha256": content_sha256,
        }
        return OwnerEvidenceArtifact(kind, self._issuer, payload_json, content_sha256, self._authority.sign(unsigned))

    def issue_source(self, manifest: SourceManifest) -> OwnerEvidenceArtifact:
        if type(manifest) is not SourceManifest:
            raise TypeError("source issuer requires a typed source manifest")
        return self.issue(EvidenceKind.SOURCE, manifest.to_dict())

    def issue_profile(self, qualification: FrozenProfileQualification) -> OwnerEvidenceArtifact:
        if type(qualification) is not FrozenProfileQualification:
            raise TypeError("profile issuer requires a frozen typed qualification")
        return self.issue(EvidenceKind.PROFILE, qualification.to_dict())

    def issue_research_invocation(self, authorization: ResearchInvocationAuthorization) -> OwnerEvidenceArtifact:
        if type(authorization) is not ResearchInvocationAuthorization:
            raise TypeError("invocation issuer requires a typed authorization")
        return self.issue(EvidenceKind.RESEARCH_INVOCATION, authorization.to_dict())

    def issue_fault_roster(self, roster: FrozenFaultRoster) -> OwnerEvidenceArtifact:
        if type(roster) is not FrozenFaultRoster:
            raise TypeError("fault roster issuer requires a frozen typed roster")
        return self.issue(EvidenceKind.FAULT_ROSTER, roster.to_dict())


class OwnerEvidenceRegistry:
    __slots__ = (
        "_authority",
        "_artifacts",
        "_invocation_ids",
        "_runtime_receipt_invocations",
        "_runtime_receipt_runs",
        "_runtime_receipt_responses",
        "_runtime_receipt_subjects",
        "_model_output_receipts",
        "_research_run_arms",
        "_critic_run_requests",
        "_fault_suite_categories",
        "_fault_case_categories",
    )

    def __init__(self, authority: PhaseZeroAuthority, artifacts: tuple[OwnerEvidenceArtifact, ...] = ()) -> None:
        self._authority = authority
        self._artifacts: dict[str, OwnerEvidenceArtifact] = {}
        self._invocation_ids: set[str] = set()
        self._runtime_receipt_invocations: set[tuple[str, str]] = set()
        self._runtime_receipt_runs: set[tuple[str, str]] = set()
        self._runtime_receipt_responses: set[str] = set()
        self._runtime_receipt_subjects: set[tuple[str, str]] = set()
        self._model_output_receipts: set[str] = set()
        self._research_run_arms: set[tuple[str, str]] = set()
        self._critic_run_requests: set[str] = set()
        self._fault_suite_categories: set[tuple[str, FaultCategory]] = set()
        self._fault_case_categories: set[tuple[str, FaultCategory]] = set()
        for artifact in artifacts:
            self.add(artifact)

    def add(self, artifact: OwnerEvidenceArtifact) -> None:
        self._add(artifact)

    def _add(self, artifact: OwnerEvidenceArtifact) -> None:
        checked = OwnerEvidenceArtifact.hydrate(artifact.to_dict(), self._authority)
        if checked.content_sha256 in self._artifacts:
            raise ValueError("owner evidence cannot be duplicated")
        invocation_id_to_add: str | None = None
        runtime_receipt_identity_to_add: tuple[tuple[str, str], tuple[str, str], str | None, tuple[str, str]] | None = (
            None
        )
        research_arm_to_add: tuple[str, str] | None = None
        critic_request_to_add: str | None = None
        model_output_receipt_to_add: str | None = None
        fault_case_identity_to_add: tuple[str, FaultCategory] | None = None
        fault_suite_identities_to_add: set[tuple[str, FaultCategory]] = set()
        if checked.kind is EvidenceKind.RESEARCH_INVOCATION:
            authorization = ResearchInvocationAuthorization.hydrate(checked.payload(), self._authority)
            if authorization.invocation_id in self._invocation_ids:
                raise ValueError("research invocation id cannot be reused")
            invocation_id_to_add = authorization.invocation_id
        if checked.kind is EvidenceKind.RUNTIME_RECEIPT:
            receipt = RuntimeReceiptPayload.hydrate(checked.payload(), self._authority)
            if receipt.status == "COMPLETED":
                raise PermissionError(
                    "completed runtime receipts require one atomic receipt + output + run evidence batch"
                )
            invocation_identity = (receipt.workload_id, receipt.invocation_id)
            run_identity = (receipt.workload_id, receipt.run_id)
            subject_identity = (receipt.workload_id, receipt.subject_sha256)
            if (
                invocation_identity in self._runtime_receipt_invocations
                or run_identity in self._runtime_receipt_runs
                or subject_identity in self._runtime_receipt_subjects
                or (receipt.response_id is not None and receipt.response_id in self._runtime_receipt_responses)
            ):
                raise ValueError("runtime receipt invocation/run/response cannot be replayed or re-signed")
            runtime_receipt_identity_to_add = (
                invocation_identity,
                run_identity,
                receipt.response_id,
                subject_identity,
            )
        if checked.kind is EvidenceKind.MODEL_OUTPUT:
            output = checked.payload()
            _keys(output, {"workload_id", "receipt_sha256", "wire"}, "model output evidence")
            receipt_sha256 = _digest(output["receipt_sha256"], "model output receipt")
            receipt = self.require_runtime_receipt(receipt_sha256)
            if (
                receipt_sha256 in self._model_output_receipts
                or output["workload_id"] != receipt.workload_id
                or canonical_sha256(output["wire"]) != receipt.canonical_response_sha256
            ):
                raise PermissionError("model output does not exactly derive from its completed runtime receipt")
            model_output_receipt_to_add = receipt_sha256
        if checked.kind is EvidenceKind.RESEARCH_RUN:
            run = checked.payload()
            _keys(
                run,
                {
                    "candidate_sha256",
                    "proposal_sha256",
                    "agent_brief_sha256",
                    "invocation_authorization_sha256",
                    "invocation_id",
                    "synthesis_receipt_sha256",
                    "experiment_design_receipt_sha256",
                    "synthesis_output_sha256",
                    "experiment_design_output_sha256",
                    "synthesis_owner_binding",
                    "experiment_design_owner_binding",
                    "experiment_binding_sha256",
                    "response_sha256",
                    "response_id",
                    "workload_id",
                    "profile_sha256",
                    "prompt_sha256",
                    "schema_sha256",
                    "toolset_sha256",
                    "runtime_sha256",
                    "actual_provider",
                    "actual_model_id",
                    "actual_reasoning_effort",
                    "actual_profile_id",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cache_tokens",
                    "latency_ms",
                    "reroutes",
                },
                "research run evidence",
            )
            authorization_sha256 = _digest(run.get("invocation_authorization_sha256"), "invocation authorization")
            authorization = ResearchInvocationAuthorization.hydrate(
                self.require(authorization_sha256, EvidenceKind.RESEARCH_INVOCATION).payload(), self._authority
            )
            expected = {
                "candidate_sha256": authorization.candidate_sha256,
                "workload_id": authorization.workload_id,
                "proposal_sha256": authorization.request_sha256,
                "profile_sha256": authorization.profile_sha256,
                "prompt_sha256": authorization.prompt_sha256,
                "schema_sha256": authorization.schema_sha256,
                "toolset_sha256": authorization.toolset_sha256,
                "runtime_sha256": authorization.runtime_sha256,
                "invocation_id": authorization.invocation_id,
            }
            if any(run.get(key) != value for key, value in expected.items()):
                raise PermissionError("research run does not bind its pre-authorized invocation")
            synthesis = self.require_runtime_receipt(_digest(run.get("synthesis_receipt_sha256"), "synthesis receipt"))
            experiment = self.require_runtime_receipt(
                _digest(run.get("experiment_design_receipt_sha256"), "experiment receipt")
            )
            synthesis_output = self.require(
                _digest(run.get("synthesis_output_sha256"), "synthesis output"), EvidenceKind.MODEL_OUTPUT
            ).payload()
            experiment_output = self.require(
                _digest(run.get("experiment_design_output_sha256"), "experiment output"), EvidenceKind.MODEL_OUTPUT
            ).payload()
            binding_sha256 = _digest(run.get("experiment_binding_sha256"), "experiment binding")
            synthesis_binding = RuntimeOwnerBinding.hydrate(
                _mapping(run.get("synthesis_owner_binding"), "synthesis owner binding")
            )
            experiment_binding = RuntimeOwnerBinding.hydrate(
                _mapping(run.get("experiment_design_owner_binding"), "experiment owner binding")
            )
            if (
                synthesis.status != "COMPLETED"
                or synthesis.workload_id != "research.hypothesis_synthesis"
                or synthesis.subject_sha256 != authorization.candidate_sha256
                or synthesis.input_lineage
                != (RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, authorization.candidate_sha256),)
                or synthesis.invocation_id != authorization.invocation_id
                or synthesis.profile_sha256 != authorization.profile_sha256
                or synthesis.prompt_sha256 != authorization.prompt_sha256
                or synthesis.schema_sha256 != authorization.schema_sha256
                or synthesis.toolset_sha256 != authorization.toolset_sha256
                or synthesis.runtime_sha256 != authorization.runtime_sha256
                or synthesis_binding.workload_id != synthesis.workload_id
                or synthesis_binding.asset_ref != synthesis.asset_ref
                or synthesis_binding.owner_digests
                != (
                    synthesis.profile_sha256,
                    synthesis.prompt_sha256,
                    synthesis.schema_sha256,
                    synthesis.toolset_sha256,
                    synthesis.runtime_sha256,
                )
                or synthesis_output.get("receipt_sha256") != run.get("synthesis_receipt_sha256")
                or experiment.status != "COMPLETED"
                or experiment.workload_id != "experiment.preregistration_design"
                or experiment.subject_sha256 != authorization.candidate_sha256
                or experiment.input_lineage
                != (
                    RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, authorization.candidate_sha256),
                    RuntimeInputRef(RuntimeInputKind.EXPERIMENT_BINDING, binding_sha256),
                )
                or experiment_output.get("receipt_sha256") != run.get("experiment_design_receipt_sha256")
                or experiment_output.get("wire") != {"design_category": "USE_FROZEN_BINDING"}
                or experiment_binding.workload_id != experiment.workload_id
                or experiment_binding.asset_ref != experiment.asset_ref
                or experiment_binding.owner_digests
                != (
                    experiment.profile_sha256,
                    experiment.prompt_sha256,
                    experiment.schema_sha256,
                    experiment.toolset_sha256,
                    experiment.runtime_sha256,
                )
                or experiment_binding == synthesis_binding
            ):
                raise PermissionError("research run receipt lineage is not exact")
            _digest(run.get("response_sha256"), "research response")
            _text(run.get("response_id"), "research response id")
            arm = (authorization.candidate_sha256, authorization.workload_id)
            if arm in self._research_run_arms:
                raise ValueError("Phase-0 research arm already has an append-only semantic run")
            research_arm_to_add = arm
        if checked.kind is EvidenceKind.CRITIC_RUN:
            run = checked.payload()
            request_sha256 = _digest(run.get("request_sha256"), "critic request")
            receipt = self.require_runtime_receipt(_digest(run.get("critic_receipt_sha256"), "critic receipt"))
            output = self.require(
                _digest(run.get("critic_output_sha256"), "critic output"), EvidenceKind.MODEL_OUTPUT
            ).payload()
            wire = _mapping(output.get("wire"), "critic output wire")
            owner_binding = RuntimeOwnerBinding.hydrate(
                _mapping(run.get("critic_owner_binding"), "critic owner binding")
            )
            if (
                run.get("workload_id") != "assurance.adversarial_critique"
                or receipt.status != "COMPLETED"
                or receipt.workload_id != "assurance.adversarial_critique"
                or receipt.profile_sha256 != run.get("profile_sha256")
                or receipt.prompt_sha256 != run.get("prompt_sha256")
                or receipt.schema_sha256 != run.get("schema_sha256")
                or receipt.toolset_sha256 != run.get("toolset_sha256")
                or receipt.runtime_sha256 != run.get("runtime_sha256")
                or owner_binding.workload_id != receipt.workload_id
                or owner_binding.asset_ref != receipt.asset_ref
                or owner_binding.owner_digests
                != (
                    receipt.profile_sha256,
                    receipt.prompt_sha256,
                    receipt.schema_sha256,
                    receipt.toolset_sha256,
                    receipt.runtime_sha256,
                )
                or output.get("receipt_sha256") != run.get("critic_receipt_sha256")
                or set(wire) != {"decision", "reason_category"}
                or run.get("decision") != wire.get("decision")
                or run.get("reason_category") != wire.get("reason_category")
            ):
                raise PermissionError("critic run does not bind its exact runtime receipt")
            if request_sha256 in self._critic_run_requests:
                raise ValueError("critic request already has an append-only semantic run")
            critic_request_to_add = request_sha256
        if checked.kind is EvidenceKind.FAULT_CASE:
            case = FaultCase.hydrate(checked.payload())
            roster = FrozenFaultRoster.hydrate(
                self.require(case.fault_roster_sha256, EvidenceKind.FAULT_ROSTER).payload(), self._authority
            )
            original = FaultInput.hydrate(self.require(case.original_input_sha256, EvidenceKind.FAULT_INPUT).payload())
            mutated = FaultInput.hydrate(self.require(case.mutated_input_sha256, EvidenceKind.FAULT_INPUT).payload())
            if (
                original.category is not case.category
                or mutated.category is not case.category
                or (case.category, case.original_input_sha256, case.mutated_input_sha256) not in roster.entries
            ):
                raise PermissionError("fault case must bind exact same-category owner fault inputs")
            identity = (case.fault_roster_sha256, case.category)
            if identity in self._fault_case_categories:
                raise ValueError("fault roster category already has an append-only semantic case")
            fault_case_identity_to_add = identity
        if checked.kind is EvidenceKind.FAULT_ROSTER:
            roster = FrozenFaultRoster.hydrate(checked.payload(), self._authority)
            for category, original_sha256, mutated_sha256 in roster.entries:
                original = FaultInput.hydrate(self.require(original_sha256, EvidenceKind.FAULT_INPUT).payload())
                mutated = FaultInput.hydrate(self.require(mutated_sha256, EvidenceKind.FAULT_INPUT).payload())
                if original.category is not category or mutated.category is not category:
                    raise PermissionError("fault roster entry must bind exact same-category inputs")
                identity = (roster.suite_id, category)
                if identity in self._fault_suite_categories or identity in fault_suite_identities_to_add:
                    raise ValueError("fault suite category cannot be re-signed or replaced")
                fault_suite_identities_to_add.add(identity)
        if invocation_id_to_add is not None:
            self._invocation_ids.add(invocation_id_to_add)
        if runtime_receipt_identity_to_add is not None:
            invocation_identity, run_identity, response_id, subject_identity = runtime_receipt_identity_to_add
            self._runtime_receipt_invocations.add(invocation_identity)
            self._runtime_receipt_runs.add(run_identity)
            self._runtime_receipt_subjects.add(subject_identity)
            if response_id is not None:
                self._runtime_receipt_responses.add(response_id)
        if research_arm_to_add is not None:
            self._research_run_arms.add(research_arm_to_add)
        if critic_request_to_add is not None:
            self._critic_run_requests.add(critic_request_to_add)
        if model_output_receipt_to_add is not None:
            self._model_output_receipts.add(model_output_receipt_to_add)
        if fault_case_identity_to_add is not None:
            self._fault_case_categories.add(fault_case_identity_to_add)
        self._fault_suite_categories.update(fault_suite_identities_to_add)
        self._artifacts[checked.content_sha256] = checked

    def add_many_atomic(self, artifacts: tuple[OwnerEvidenceArtifact, ...]) -> None:
        """Validate a related evidence batch on a clone, then commit once."""

        if type(artifacts) is not tuple or not artifacts:
            raise TypeError("atomic owner evidence append requires a non-empty tuple")
        completed = self._validate_completed_runtime_batch(artifacts)
        staged = self._clone()
        # Completed receipts never pass through ``add`` or a mutable allow flag.
        # The validated batch is inserted directly into the isolated clone so
        # no caller-controlled registry attribute can weaken the public rule.
        for artifact in artifacts:
            if artifact.content_sha256 not in completed:
                continue
            checked = OwnerEvidenceArtifact.hydrate(artifact.to_dict(), staged._authority)
            receipt = completed[checked.content_sha256]
            invocation_identity = (receipt.workload_id, receipt.invocation_id)
            run_identity = (receipt.workload_id, receipt.run_id)
            subject_identity = (receipt.workload_id, receipt.subject_sha256)
            if (
                checked.content_sha256 in staged._artifacts
                or invocation_identity in staged._runtime_receipt_invocations
                or run_identity in staged._runtime_receipt_runs
                or subject_identity in staged._runtime_receipt_subjects
                or (receipt.response_id is not None and receipt.response_id in staged._runtime_receipt_responses)
            ):
                raise ValueError("runtime receipt invocation/run/response cannot be replayed or re-signed")
            staged._runtime_receipt_invocations.add(invocation_identity)
            staged._runtime_receipt_runs.add(run_identity)
            staged._runtime_receipt_subjects.add(subject_identity)
            if receipt.response_id is not None:
                staged._runtime_receipt_responses.add(receipt.response_id)
            staged._artifacts[checked.content_sha256] = checked
        for artifact in artifacts:
            if artifact.content_sha256 in completed:
                continue
            staged._add(artifact)
        self._artifacts = staged._artifacts
        self._invocation_ids = staged._invocation_ids
        self._runtime_receipt_invocations = staged._runtime_receipt_invocations
        self._runtime_receipt_runs = staged._runtime_receipt_runs
        self._runtime_receipt_responses = staged._runtime_receipt_responses
        self._runtime_receipt_subjects = staged._runtime_receipt_subjects
        self._model_output_receipts = staged._model_output_receipts
        self._research_run_arms = staged._research_run_arms
        self._critic_run_requests = staged._critic_run_requests
        self._fault_suite_categories = staged._fault_suite_categories
        self._fault_case_categories = staged._fault_case_categories

    def _clone(self) -> OwnerEvidenceRegistry:
        staged = OwnerEvidenceRegistry(self._authority)
        staged._artifacts = dict(self._artifacts)
        staged._invocation_ids = set(self._invocation_ids)
        staged._runtime_receipt_invocations = set(self._runtime_receipt_invocations)
        staged._runtime_receipt_runs = set(self._runtime_receipt_runs)
        staged._runtime_receipt_responses = set(self._runtime_receipt_responses)
        staged._runtime_receipt_subjects = set(self._runtime_receipt_subjects)
        staged._model_output_receipts = set(self._model_output_receipts)
        staged._research_run_arms = set(self._research_run_arms)
        staged._critic_run_requests = set(self._critic_run_requests)
        staged._fault_suite_categories = set(self._fault_suite_categories)
        staged._fault_case_categories = set(self._fault_case_categories)
        return staged

    def _validate_completed_runtime_batch(
        self, artifacts: tuple[OwnerEvidenceArtifact, ...]
    ) -> dict[str, RuntimeReceiptPayload]:
        checked = tuple(OwnerEvidenceArtifact.hydrate(item.to_dict(), self._authority) for item in artifacts)
        completed: dict[str, RuntimeReceiptPayload] = {}
        outputs: dict[str, Mapping[str, JsonValue]] = {}
        runs: list[OwnerEvidenceArtifact] = []
        for artifact in checked:
            if artifact.kind is EvidenceKind.RUNTIME_RECEIPT:
                receipt = RuntimeReceiptPayload.hydrate(artifact.payload(), self._authority)
                if receipt.status == "COMPLETED":
                    completed[artifact.content_sha256] = receipt
            elif artifact.kind is EvidenceKind.MODEL_OUTPUT:
                output = artifact.payload()
                _keys(output, {"workload_id", "receipt_sha256", "wire"}, "model output evidence")
                outputs[_digest(output["receipt_sha256"], "model output receipt")] = output
            elif artifact.kind in {EvidenceKind.RESEARCH_RUN, EvidenceKind.CRITIC_RUN}:
                runs.append(artifact)
        if not completed:
            return {}
        if set(outputs) != set(completed) or len(runs) != 1:
            raise PermissionError("completed runtime batch requires exact model outputs and one corresponding run")
        for digest, receipt in completed.items():
            output = outputs[digest]
            if (
                output.get("workload_id") != receipt.workload_id
                or canonical_sha256(output.get("wire")) != receipt.canonical_response_sha256
            ):
                raise PermissionError("completed runtime batch output does not match its exact receipt")
        run = runs[0]
        payload = run.payload()
        if run.kind is EvidenceKind.RESEARCH_RUN:
            expected = {
                _digest(payload.get("synthesis_receipt_sha256"), "synthesis receipt"),
                _digest(payload.get("experiment_design_receipt_sha256"), "experiment receipt"),
            }
            if len(completed) != 2 or expected != set(completed):
                raise PermissionError("research batch requires its exact two completed runtime receipts")
        else:
            expected = {_digest(payload.get("critic_receipt_sha256"), "critic receipt")}
            if len(completed) != 1 or expected != set(completed):
                raise PermissionError("critic batch requires its exact completed runtime receipt")
        return completed

    def require(self, digest: str, kind: EvidenceKind) -> OwnerEvidenceArtifact:
        artifact = self._artifacts.get(_digest(digest))
        if artifact is None or artifact.kind is not kind:
            raise PermissionError("required owner evidence is absent or has the wrong kind")
        return OwnerEvidenceArtifact.hydrate(artifact.to_dict(), self._authority)

    def require_runtime_receipt(self, digest: str) -> RuntimeReceiptPayload:
        artifact = self.require(digest, EvidenceKind.RUNTIME_RECEIPT)
        return RuntimeReceiptPayload.hydrate(artifact.payload(), self._authority)

    def runtime_receipt_ref(self, digest: str) -> RuntimeReceiptRef:
        checked_digest = _digest(digest, "runtime receipt evidence")
        return RuntimeReceiptRef.from_payload(checked_digest, self.require_runtime_receipt(checked_digest))

    def runtime_receipt_for_invocation(self, workload_id: str, invocation_id: str) -> tuple[str, RuntimeReceiptPayload]:
        """Read one append-only receipt by its semantic invocation identity."""

        identity = (_text(workload_id, "runtime receipt workload"), _text(invocation_id, "runtime invocation"))
        matches: list[tuple[str, RuntimeReceiptPayload]] = []
        for digest, artifact in self._artifacts.items():
            if artifact.kind is EvidenceKind.RUNTIME_RECEIPT:
                receipt = RuntimeReceiptPayload.hydrate(artifact.payload(), self._authority)
                if (receipt.workload_id, receipt.invocation_id) == identity:
                    matches.append((digest, receipt))
        if len(matches) != 1:
            raise PermissionError("runtime receipt invocation identity is absent or non-unique")
        return matches[0]

    def verify_source(self, reference: SourceReference) -> None:
        artifact = self.require(reference.artifact_sha256, EvidenceKind.SOURCE)
        manifest = SourceManifest.hydrate(artifact.payload())
        tokens = _pointer(reference.json_pointer)
        if (
            len(tokens) != 3
            or tokens[0] != "records"
            or not tokens[1].isdigit()
            or tokens[2] not in {"event_time", "available_time", "close", "component_id", "revision"}
        ):
            raise PermissionError("source reference must select one allowed typed record field")
        if int(tokens[1]) >= len(manifest.records):
            raise PermissionError("source pointer does not exist in owner evidence")
        current: object = artifact.payload()
        for token in tokens:
            if isinstance(current, Mapping):
                if token not in current:
                    raise PermissionError("source pointer does not exist in owner evidence")
                current = current[token]
            elif type(current) in (tuple, list):
                values = cast(tuple[object, ...] | list[object], current)
                if not token.isdigit() or str(int(token)) != token or int(token) >= len(values):
                    raise PermissionError("source pointer does not exist in owner evidence")
                current = values[int(token)]
            else:
                raise PermissionError("source pointer does not exist in owner evidence")


@dataclass(frozen=True, slots=True)
class CandidateEvidenceBundle:
    acquisition_sha256: str
    dataset_sha256: str
    screen_sha256: str
    toolset_sha256: str
    runtime_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.acquisition_sha256,
            self.dataset_sha256,
            self.screen_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
        ):
            _digest(value, "candidate evidence digest")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "acquisition_sha256": self.acquisition_sha256,
            "dataset_sha256": self.dataset_sha256,
            "screen_sha256": self.screen_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> CandidateEvidenceBundle:
        _keys(
            value,
            {"acquisition_sha256", "dataset_sha256", "screen_sha256", "toolset_sha256", "runtime_sha256"},
            "candidate evidence bundle",
        )
        return cls(
            _text(value["acquisition_sha256"], "acquisition digest"),
            _text(value["dataset_sha256"], "dataset digest"),
            _text(value["screen_sha256"], "screen digest"),
            _text(value["toolset_sha256"], "toolset digest"),
            _text(value["runtime_sha256"], "runtime digest"),
        )


@dataclass(frozen=True, slots=True)
class ResearchCandidatePacket:
    schema_version: str
    suite_id: str
    episode_id: str
    instrument_id: str
    as_of: str
    market_cutoff: str
    acquired_at: str
    evidence: CandidateEvidenceBundle
    sources: tuple[SourceReference, ...]
    screens: tuple[HypothesisFamilyScreen, ...]
    selected_family: HypothesisFamily
    selected_direction: int
    eligibility: ResearchEligibility
    reason_codes: tuple[str, ...]
    strongest_competing_family: HypothesisFamily
    component_id: str
    roll_warnings: tuple[str, ...]
    available_data_range: tuple[str, str]
    warnings: tuple[str, ...]
    unknowns: tuple[str, ...]
    tradable: bool
    future_label_present: bool
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.evidence) is not CandidateEvidenceBundle:
            raise ValueError("candidate schema/evidence is invalid")
        if tuple(item.family for item in self.screens) != PIVOT_HYPOTHESIS_FAMILIES:
            raise ValueError("candidate requires the complete deterministic screen roster")
        for value, label in (
            (self.suite_id, "suite"),
            (self.episode_id, "episode"),
            (self.instrument_id, "instrument"),
            (self.component_id, "component"),
        ):
            _text(value, label)
        try:
            data_from, data_to = (_utc_datetime(value, "candidate data range") for value in self.available_data_range)
            cutoff = _utc_datetime(self.market_cutoff, "candidate cutoff")
            as_of = _utc_datetime(self.as_of, "candidate as_of")
            acquired = _utc_datetime(self.acquired_at, "candidate acquired")
        except (TypeError, ValueError) as error:
            raise ValueError("candidate timestamps must be timezone-aware ISO-8601 values") from error
        if not (data_from <= data_to <= cutoff <= as_of <= acquired):
            raise ValueError("candidate PIT timestamps are out of order")
        if type(self.selected_direction) is not int or self.selected_direction not in {-1, 0, 1}:
            raise TypeError("candidate direction must be an exact bounded integer")
        if type(self.eligibility) is not ResearchEligibility or type(self.selected_family) is not HypothesisFamily:
            raise TypeError("candidate uses closed deterministic enums")
        if self.tradable is not False or self.future_label_present is not False:
            raise PermissionError("candidate is strictly future-blind and non-trading")
        if len({item.identity() for item in self.sources}) != len(self.sources) or not self.sources:
            raise ValueError("candidate source identities must be unique and non-empty")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))) or not self.reason_codes:
            raise ValueError("candidate reason codes must be canonical")
        if any(
            type(value) is not str or not value.strip()
            for value in (*self.roll_warnings, *self.warnings, *self.unknowns)
        ):
            raise TypeError("candidate warnings and unknowns must be exact text")
        if self.eligibility is ResearchEligibility.ELIGIBLE:
            screen = next((item for item in self.screens if item.family is self.selected_family), None)
            if screen is None or screen.cutoff_direction != self.selected_direction or self.selected_direction == 0:
                raise ValueError("eligible candidate selection must be deterministic")
        elif self.selected_family is not HypothesisFamily.NONE or self.selected_direction != 0:
            raise ValueError("ineligible candidates cannot retain family or direction")
        if self.selected_family is self.strongest_competing_family:
            raise ValueError("selected and competing family must be distinct")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("candidate content digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "episode_id": self.episode_id,
            "instrument_id": self.instrument_id,
            "as_of": self.as_of,
            "market_cutoff": self.market_cutoff,
            "acquired_at": self.acquired_at,
            "evidence": self.evidence.to_dict(),
            "sources": tuple(item.to_dict() for item in self.sources),
            "screens": tuple(item.payload() for item in self.screens),
            "selected_family": self.selected_family.value,
            "selected_direction": self.selected_direction,
            "eligibility": self.eligibility.value,
            "reason_codes": self.reason_codes,
            "strongest_competing_family": self.strongest_competing_family.value,
            "component_id": self.component_id,
            "roll_warnings": self.roll_warnings,
            "available_data_range": self.available_data_range,
            "warnings": self.warnings,
            "unknowns": self.unknowns,
            "tradable": False,
            "future_label_present": False,
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
        authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
    ) -> ResearchCandidatePacket:
        _keys(value, set(cls.__dataclass_fields__), "research candidate packet")
        packet = cls(
            _text(value["schema_version"], "schema"),
            _text(value["suite_id"], "suite"),
            _text(value["episode_id"], "episode"),
            _text(value["instrument_id"], "instrument"),
            _text(value["as_of"], "as_of"),
            _text(value["market_cutoff"], "market cutoff"),
            _text(value["acquired_at"], "acquired_at"),
            CandidateEvidenceBundle.hydrate(_mapping(value["evidence"], "evidence bundle")),
            tuple(SourceReference.hydrate(_mapping(item, "source")) for item in _array(value["sources"], "sources")),
            tuple(_screen(_mapping(item, "screen")) for item in _array(value["screens"], "screens")),
            HypothesisFamily(_text(value["selected_family"], "selected family")),
            _integer(value["selected_direction"], "selected direction"),
            ResearchEligibility(_text(value["eligibility"], "eligibility")),
            tuple(_text(item, "reason code") for item in _array(value["reason_codes"], "reason codes")),
            HypothesisFamily(_text(value["strongest_competing_family"], "competing family")),
            _text(value["component_id"], "component"),
            tuple(_text(item, "roll warning") for item in _array(value["roll_warnings"], "roll warnings")),
            cast(
                tuple[str, str],
                tuple(_text(item, "data range") for item in _array(value["available_data_range"], "data range")),
            ),
            tuple(_text(item, "warning") for item in _array(value["warnings"], "warnings")),
            tuple(_text(item, "unknown") for item in _array(value["unknowns"], "unknowns")),
            _boolean(value["tradable"], "tradable"),
            _boolean(value["future_label_present"], "future label"),
            _text(value["content_sha256"], "content digest"),
            _text(value["signature_sha256"], "signature"),
        )
        if len(packet.available_data_range) != 2 or not authority.verify(
            packet.unsigned_payload(), packet.signature_sha256
        ):
            raise PermissionError("candidate packet signature or data range is invalid")
        expected = ResearchCandidateFactory(authority, registry).issue(packet.evidence)
        if expected.unsigned_payload() != packet.unsigned_payload():
            raise PermissionError("candidate packet is not derivable from current owner evidence")
        return packet


class ResearchCandidateFactory:
    """Issues candidates only from independently signed deterministic evidence."""

    def __init__(self, authority: PhaseZeroAuthority, registry: OwnerEvidenceRegistry) -> None:
        self._authority = authority
        self._registry = registry

    def issue(self, bundle: CandidateEvidenceBundle) -> ResearchCandidatePacket:
        acquisition = self._registry.require(bundle.acquisition_sha256, EvidenceKind.ACQUISITION).payload()
        dataset = self._registry.require(bundle.dataset_sha256, EvidenceKind.DATASET).payload()
        screen_payload = self._registry.require(bundle.screen_sha256, EvidenceKind.SCREEN).payload()
        self._registry.require(bundle.toolset_sha256, EvidenceKind.TOOLSET)
        self._registry.require(bundle.runtime_sha256, EvidenceKind.RUNTIME)
        _keys(
            acquisition,
            {
                "suite_id",
                "episode_id",
                "instrument_id",
                "as_of",
                "market_cutoff",
                "acquired_at",
                "component_id",
                "roll_warnings",
                "available_data_range",
                "warnings",
                "unknowns",
                "sources",
            },
            "acquisition evidence",
        )
        _keys(
            dataset,
            {"instrument_id", "acquisition_sha256", "source_sha256s", "row_count"},
            "dataset evidence",
        )
        _keys(screen_payload, {"acquisition_sha256", "dataset_sha256", "screens"}, "screen evidence")
        if (
            dataset["instrument_id"] != acquisition["instrument_id"]
            or dataset["acquisition_sha256"] != bundle.acquisition_sha256
        ):
            raise PermissionError("dataset evidence does not bind the acquisition")
        if (
            screen_payload["acquisition_sha256"] != bundle.acquisition_sha256
            or screen_payload["dataset_sha256"] != bundle.dataset_sha256
        ):
            raise PermissionError("screen evidence does not bind acquisition and dataset")
        sources = tuple(
            SourceReference.hydrate(_mapping(item, "source")) for item in _array(acquisition["sources"], "sources")
        )
        source_digests = tuple(
            _digest(item, "dataset source digest") for item in _array(dataset["source_sha256s"], "dataset sources")
        )
        if (
            len(set(source_digests)) != len(source_digests)
            or tuple(source.artifact_sha256 for source in sources) != source_digests
        ):
            raise PermissionError("dataset evidence does not bind the exact acquisition source roster")
        declared_row_count = _integer(dataset["row_count"], "dataset row count", minimum=1)
        derived_row_count = 0
        record_identities: set[tuple[str, str, datetime]] = set()
        for source in sources:
            self._registry.verify_source(source)
            manifest = SourceManifest.hydrate(
                self._registry.require(source.artifact_sha256, EvidenceKind.SOURCE).payload()
            )
            if (
                manifest.instrument_id != acquisition["instrument_id"]
                or _utc_datetime(manifest.market_cutoff, "source cutoff")
                != _utc_datetime(acquisition["market_cutoff"], "acquisition cutoff")
                or _utc_datetime(manifest.acquired_at, "source acquired")
                > _utc_datetime(acquisition["acquired_at"], "acquisition acquired")
            ):
                raise PermissionError("source manifest does not bind the acquisition point-in-time contract")
            derived_row_count += len(manifest.records)
            for record in manifest.records:
                identity = record.identity(manifest.instrument_id)
                if identity in record_identities:
                    raise PermissionError("dataset source roster repeats a natural source-record identity")
                record_identities.add(identity)
        if declared_row_count != derived_row_count:
            raise PermissionError("dataset row count is not derivable from exact typed source records")
        screens = tuple(
            _screen(_mapping(item, "screen")) for item in _array(screen_payload["screens"], "screen roster")
        )
        if tuple(item.family for item in screens) != PIVOT_HYPOTHESIS_FAMILIES:
            raise PermissionError("screen evidence must contain the frozen complete roster")
        qualifying = tuple(
            item
            for item in screens
            if item.qualifies(
                minimum_signal_count=10,
                minimum_accuracy=Decimal("0.55"),
                minimum_positive_fold_ratio=Decimal("0.60"),
            )
        )
        if all(item.signal_count == 0 for item in screens):
            eligibility, selected = ResearchEligibility.REJECTED, None
        elif qualifying:
            eligibility, selected = (
                ResearchEligibility.ELIGIBLE,
                max(
                    qualifying,
                    key=lambda item: (item.stressed_net_return, item.signal_accuracy, item.family.value),
                ),
            )
        else:
            eligibility, selected = ResearchEligibility.INSUFFICIENT_EVIDENCE, None
        selected_family = selected.family if selected else HypothesisFamily.NONE
        selected_direction = selected.cutoff_direction if selected else 0
        competing = max(
            (item for item in screens if item.family is not selected_family),
            key=lambda item: (item.stressed_net_return, item.signal_accuracy, item.family.value),
        ).family
        reason_codes = (f"DETERMINISTIC_{eligibility.value}",)
        available_data_range = tuple(
            _text(item, "data range") for item in _array(acquisition["available_data_range"], "data range")
        )
        if len(available_data_range) != 2:
            raise ValueError("acquisition evidence must contain one exact data range")
        payload: dict[str, JsonValue] = {
            "schema_version": _SCHEMA,
            "suite_id": _text(acquisition["suite_id"], "suite"),
            "episode_id": _text(acquisition["episode_id"], "episode"),
            "instrument_id": _text(acquisition["instrument_id"], "instrument"),
            "as_of": _text(acquisition["as_of"], "as_of"),
            "market_cutoff": _text(acquisition["market_cutoff"], "market cutoff"),
            "acquired_at": _text(acquisition["acquired_at"], "acquired_at"),
            "evidence": bundle.to_dict(),
            "sources": tuple(item.to_dict() for item in sources),
            "screens": tuple(item.payload() for item in screens),
            "selected_family": selected_family.value,
            "selected_direction": selected_direction,
            "eligibility": eligibility.value,
            "reason_codes": reason_codes,
            "strongest_competing_family": competing.value,
            "component_id": _text(acquisition["component_id"], "component"),
            "roll_warnings": tuple(
                _text(item, "roll warning") for item in _array(acquisition["roll_warnings"], "roll warnings")
            ),
            "available_data_range": available_data_range,
            "warnings": tuple(_text(item, "warning") for item in _array(acquisition["warnings"], "warnings")),
            "unknowns": tuple(_text(item, "unknown") for item in _array(acquisition["unknowns"], "unknowns")),
            "tradable": False,
            "future_label_present": False,
        }
        content_sha256 = canonical_sha256(payload)
        return ResearchCandidatePacket(
            _SCHEMA,
            cast(str, payload["suite_id"]),
            cast(str, payload["episode_id"]),
            cast(str, payload["instrument_id"]),
            cast(str, payload["as_of"]),
            cast(str, payload["market_cutoff"]),
            cast(str, payload["acquired_at"]),
            bundle,
            sources,
            screens,
            selected_family,
            selected_direction,
            eligibility,
            reason_codes,
            competing,
            cast(str, payload["component_id"]),
            cast(tuple[str, ...], payload["roll_warnings"]),
            available_data_range,
            cast(tuple[str, ...], payload["warnings"]),
            cast(tuple[str, ...], payload["unknowns"]),
            False,
            False,
            content_sha256,
            self._authority.sign(payload),
        )


class BriefProducer(StrEnum):
    AGENT = "AGENT"
    DETERMINISTIC_TEMPLATE = "DETERMINISTIC_TEMPLATE"
    ALWAYS_REJECT = "ALWAYS_REJECT"
    ALWAYS_DEFER = "ALWAYS_DEFER"
    DETERMINISTIC_FAILURE = "DETERMINISTIC_FAILURE"


class DeterministicFailureCode(StrEnum):
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PIT_INVALID = "PIT_INVALID"
    RULE_UNAVAILABLE = "RULE_UNAVAILABLE"
    REQUIRED_TOOL_FAILED = "REQUIRED_TOOL_FAILED"


@dataclass(frozen=True, slots=True)
class GroundedTextClaim:
    category: NarrativeCategory
    evidence_refs: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        _narrative(self.category, "claim category")
        if not self.evidence_refs or any(type(value) is not SourceReference for value in self.evidence_refs):
            raise TypeError("grounded claims require typed evidence references")
        if len({value.identity() for value in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError("grounded claims cannot repeat source identities")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "evidence_refs": tuple(value.to_dict() for value in self.evidence_refs),
            "numeric_value": None,
            "unit": None,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> GroundedTextClaim:
        _keys(value, {"category", "evidence_refs", "numeric_value", "unit"}, "grounded text claim")
        if value["numeric_value"] is not None or value["unit"] is not None:
            raise PermissionError("MVP-R-002 model claims cannot restate numeric values")
        return cls(
            NarrativeCategory(_text(value["category"], "claim category")),
            tuple(
                SourceReference.hydrate(_mapping(item, "claim evidence"))
                for item in _array(value["evidence_refs"], "claim evidence")
            ),
        )

    @property
    def statement(self) -> str:
        return _narrative(self.category, "claim category")


@dataclass(frozen=True, slots=True)
class ResearchProposal:
    candidate_sha256: str
    intent: ProposalIntent
    action: ResearchAction
    why_now: NarrativeCategory
    supporting_claims: tuple[GroundedTextClaim, ...]
    strongest_counter_claim: GroundedTextClaim
    additional_unknowns: tuple[NarrativeCategory, ...]
    falsifiable_hypothesis: NarrativeCategory
    source_refs: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        _digest(self.candidate_sha256, "proposal candidate")
        if type(self.intent) is not ProposalIntent or self.intent is not ProposalIntent.RESEARCH_ONLY:
            raise PermissionError("proposal intent must be research-only")
        if type(self.action) is not ResearchAction or self.action is ResearchAction.DEFER:
            raise PermissionError("Agent proposals cannot manufacture deterministic DEFER")
        _narrative(self.why_now, "why-now category")
        _narrative(self.falsifiable_hypothesis, "hypothesis category")
        if not self.supporting_claims or any(type(value) is not GroundedTextClaim for value in self.supporting_claims):
            raise TypeError("proposal requires typed supporting claims")
        if type(self.strongest_counter_claim) is not GroundedTextClaim:
            raise TypeError("proposal requires one typed strongest counter claim")
        for value in self.additional_unknowns:
            _narrative(value, "additional unknown category")
        if len({value.identity() for value in self.source_refs}) != len(self.source_refs):
            raise ValueError("proposal source identities must be unique")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "candidate_sha256": self.candidate_sha256,
            "intent": self.intent.value,
            "action": self.action.value,
            "why_now": self.why_now.value,
            "supporting_claims": tuple(value.to_dict() for value in self.supporting_claims),
            "strongest_counter_claim": self.strongest_counter_claim.to_dict(),
            "additional_unknowns": tuple(value.value for value in self.additional_unknowns),
            "falsifiable_hypothesis": self.falsifiable_hypothesis.value,
            "source_refs": tuple(value.to_dict() for value in self.source_refs),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())


def _research_proposal_wire(proposal: ResearchProposal) -> dict[str, JsonValue]:
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


def _research_proposal_from_wire(value: Mapping[str, object], candidate_sha256: str) -> ResearchProposal:
    _keys(
        value,
        {
            "intent",
            "action",
            "why_now",
            "supporting_claims",
            "strongest_counter_claim",
            "additional_unknowns",
            "falsifiable_hypothesis",
            "source_refs",
        },
        "research model output",
    )
    return ResearchProposal(
        candidate_sha256,
        ProposalIntent(_text(value["intent"], "proposal intent")),
        ResearchAction(_text(value["action"], "proposal action")),
        NarrativeCategory(_text(value["why_now"], "proposal why-now")),
        tuple(
            GroundedTextClaim.hydrate(_mapping(item, "proposal supporting claim"))
            for item in _array(value["supporting_claims"], "proposal supporting claims")
        ),
        GroundedTextClaim.hydrate(_mapping(value["strongest_counter_claim"], "proposal counter claim")),
        tuple(
            NarrativeCategory(_text(item, "proposal unknown"))
            for item in _array(value["additional_unknowns"], "proposal unknowns")
        ),
        NarrativeCategory(_text(value["falsifiable_hypothesis"], "proposal hypothesis")),
        tuple(
            SourceReference.hydrate(_mapping(item, "proposal source"))
            for item in _array(value["source_refs"], "proposal sources")
        ),
    )


@dataclass(frozen=True, slots=True)
class ExperimentBinding:
    profile_sha256: str
    prompt_sha256: str
    schema_sha256: str
    cost_sha256: str
    reproduction_sha256: str
    window_start: str
    window_end: str
    train_end: str
    validation_end: str
    test_end: str
    embargo_bars: int
    baseline: str
    control: str
    primary_metric: str
    stop_rule: str
    failure_disposition: str
    bias_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.cost_sha256,
            self.reproduction_sha256,
        ):
            _digest(value, "experiment binding")
        try:
            boundaries = tuple(
                _utc_datetime(value, "experiment boundary")
                for value in (self.window_start, self.train_end, self.validation_end, self.test_end, self.window_end)
            )
        except ValueError as error:
            raise ValueError("experiment boundaries must be ISO-8601") from error
        if not (boundaries[0] < boundaries[1] < boundaries[2] < boundaries[3] <= boundaries[4]):
            raise ValueError("experiment boundaries must be timezone-aware and ordered")
        if type(self.embargo_bars) is not int or self.embargo_bars < 1:
            raise ValueError("experiment embargo must be a positive exact integer")
        for value in (
            self.baseline,
            self.control,
            self.primary_metric,
            self.stop_rule,
            self.failure_disposition,
            *self.bias_checks,
        ):
            _text(value, "experiment parameter")
        if not self.bias_checks:
            raise ValueError("experiment requires bias checks")
        if self.baseline == self.control:
            raise ValueError("experiment baseline and control must be distinct")
        if self.bias_checks != tuple(dict.fromkeys(self.bias_checks)):
            raise ValueError("experiment bias checks must be unique")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "profile_sha256": self.profile_sha256,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "cost_sha256": self.cost_sha256,
            "reproduction_sha256": self.reproduction_sha256,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "train_end": self.train_end,
            "validation_end": self.validation_end,
            "test_end": self.test_end,
            "embargo_bars": self.embargo_bars,
            "baseline": self.baseline,
            "control": self.control,
            "primary_metric": self.primary_metric,
            "stop_rule": self.stop_rule,
            "failure_disposition": self.failure_disposition,
            "bias_checks": self.bias_checks,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExperimentBinding:
        _keys(value, set(cls.__dataclass_fields__), "experiment binding")
        return cls(
            _text(value["profile_sha256"], "profile digest"),
            _text(value["prompt_sha256"], "prompt digest"),
            _text(value["schema_sha256"], "schema digest"),
            _text(value["cost_sha256"], "cost digest"),
            _text(value["reproduction_sha256"], "reproduction digest"),
            _text(value["window_start"], "window start"),
            _text(value["window_end"], "window end"),
            _text(value["train_end"], "train end"),
            _text(value["validation_end"], "validation end"),
            _text(value["test_end"], "test end"),
            _integer(value["embargo_bars"], "embargo bars"),
            _text(value["baseline"], "baseline"),
            _text(value["control"], "control"),
            _text(value["primary_metric"], "primary metric"),
            _text(value["stop_rule"], "stop rule"),
            _text(value["failure_disposition"], "failure disposition"),
            tuple(_text(item, "bias check") for item in _array(value["bias_checks"], "bias checks")),
        )


@dataclass(frozen=True, slots=True)
class NextResearchExperiment:
    schema_version: str
    candidate_sha256: str
    readiness: ExperimentReadiness
    evidence: CandidateEvidenceBundle
    binding: ExperimentBinding
    research_question: str
    primary_change: str
    tradable: bool
    strategy_candidate_created: bool
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.readiness) is not ExperimentReadiness:
            raise ValueError("next experiment schema/readiness is invalid")
        _digest(self.candidate_sha256, "experiment candidate")
        if type(self.evidence) is not CandidateEvidenceBundle or type(self.binding) is not ExperimentBinding:
            raise TypeError("next experiment requires exact evidence and binding")
        _text(self.research_question, "research question")
        _text(self.primary_change, "primary change")
        if self.tradable is not False or self.strategy_candidate_created is not False:
            raise PermissionError("next experiment is strictly non-trading")
        _digest(self.content_sha256, "experiment content")
        _digest(self.signature_sha256, "experiment signature")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("next experiment digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "candidate_sha256": self.candidate_sha256,
            "readiness": self.readiness.value,
            "evidence": self.evidence.to_dict(),
            "binding": self.binding.to_dict(),
            "research_question": self.research_question,
            "primary_change": self.primary_change,
            "tradable": False,
            "strategy_candidate_created": False,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> NextResearchExperiment:
        _keys(value, set(cls.__dataclass_fields__), "next research experiment")
        experiment = cls(
            _text(value["schema_version"], "schema"),
            _text(value["candidate_sha256"], "candidate"),
            ExperimentReadiness(_text(value["readiness"], "readiness")),
            CandidateEvidenceBundle.hydrate(_mapping(value["evidence"], "evidence")),
            ExperimentBinding.hydrate(_mapping(value["binding"], "binding")),
            _text(value["research_question"], "research question"),
            _text(value["primary_change"], "primary change"),
            _boolean(value["tradable"], "tradable"),
            _boolean(value["strategy_candidate_created"], "strategy candidate"),
            _text(value["content_sha256"], "content digest"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(experiment.unsigned_payload(), experiment.signature_sha256):
            raise PermissionError("next experiment signature is invalid")
        return experiment

    def instantiate_request(self, authority: PhaseZeroAuthority) -> PhaseZeroExperimentRequest:
        checked = type(self).hydrate(self.to_dict(), authority)
        if checked.readiness is not ExperimentReadiness.READY:
            raise PermissionError("only READY experiments can instantiate requests")
        payload: dict[str, JsonValue] = {
            "experiment_sha256": checked.content_sha256,
            "candidate_sha256": checked.candidate_sha256,
            "evidence": checked.evidence.to_dict(),
            "binding": checked.binding.to_dict(),
            "research_question": checked.research_question,
            "primary_change": checked.primary_change,
            "next_action": "RESEARCH_ONLY",
            "tradable": False,
            "strategy_candidate_created": False,
        }
        return PhaseZeroExperimentRequest(
            checked.content_sha256,
            checked.candidate_sha256,
            checked.evidence,
            checked.binding,
            checked.research_question,
            checked.primary_change,
            "RESEARCH_ONLY",
            False,
            False,
            canonical_sha256(payload),
            authority.sign(payload),
        )


@dataclass(frozen=True, slots=True)
class PhaseZeroExperimentRequest:
    experiment_sha256: str
    candidate_sha256: str
    evidence: CandidateEvidenceBundle
    binding: ExperimentBinding
    research_question: str
    primary_change: str
    next_action: str
    tradable: bool
    strategy_candidate_created: bool
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for value in (self.experiment_sha256, self.candidate_sha256, self.content_sha256, self.signature_sha256):
            _digest(value, "experiment request digest")
        if (
            self.next_action != "RESEARCH_ONLY"
            or self.tradable is not False
            or self.strategy_candidate_created is not False
        ):
            raise PermissionError("experiment requests have no trading or strategy semantics")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("experiment request digest is invalid")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "experiment_sha256": self.experiment_sha256,
            "candidate_sha256": self.candidate_sha256,
            "evidence": self.evidence.to_dict(),
            "binding": self.binding.to_dict(),
            "research_question": self.research_question,
            "primary_change": self.primary_change,
            "next_action": self.next_action,
            "tradable": False,
            "strategy_candidate_created": False,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> PhaseZeroExperimentRequest:
        _keys(value, set(cls.__dataclass_fields__), "experiment request")
        request = cls(
            _text(value["experiment_sha256"], "experiment"),
            _text(value["candidate_sha256"], "candidate"),
            CandidateEvidenceBundle.hydrate(_mapping(value["evidence"], "evidence")),
            ExperimentBinding.hydrate(_mapping(value["binding"], "binding")),
            _text(value["research_question"], "research question"),
            _text(value["primary_change"], "primary change"),
            _text(value["next_action"], "next action"),
            _boolean(value["tradable"], "tradable"),
            _boolean(value["strategy_candidate_created"], "strategy candidate"),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(request.unsigned_payload(), request.signature_sha256):
            raise PermissionError("experiment request signature is invalid")
        return request


def build_next_experiment(
    candidate: ResearchCandidatePacket,
    readiness: ExperimentReadiness,
    binding: ExperimentBinding,
    authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
) -> NextResearchExperiment:
    ResearchCandidatePacket.hydrate(candidate.to_dict(), authority, registry)
    for digest, kind in (
        (binding.profile_sha256, EvidenceKind.PROFILE),
        (binding.prompt_sha256, EvidenceKind.PROMPT),
        (binding.schema_sha256, EvidenceKind.SCHEMA),
        (binding.cost_sha256, EvidenceKind.COST),
        (binding.reproduction_sha256, EvidenceKind.REPRODUCTION),
    ):
        registry.require(digest, kind)
    qualification = FrozenProfileQualification.hydrate(
        registry.require(binding.profile_sha256, EvidenceKind.PROFILE).payload()
    )
    if qualification.workload_id != "research.hypothesis_synthesis":
        raise PermissionError("experiment profile must be a frozen research synthesis qualification")
    dataset = registry.require(candidate.evidence.dataset_sha256, EvidenceKind.DATASET).payload()
    row_count = _integer(dataset["row_count"], "dataset row count", minimum=1)
    if binding.embargo_bars >= row_count:
        raise ValueError("experiment embargo cannot exhaust the frozen dataset")
    try:
        coverage_start, coverage_end = (
            _utc_datetime(value, "candidate coverage") for value in candidate.available_data_range
        )
        window_start = _utc_datetime(binding.window_start, "experiment window start")
        window_end = _utc_datetime(binding.window_end, "experiment window end")
    except ValueError as error:
        raise ValueError("candidate and experiment windows must be ISO-8601") from error
    if not coverage_start <= window_start < window_end <= coverage_end:
        raise PermissionError("experiment window is outside frozen candidate dataset coverage")
    record_identities = tuple(
        record.identity(
            SourceManifest.hydrate(registry.require(source_digest, EvidenceKind.SOURCE).payload()).instrument_id
        )
        for source_digest in tuple(source.artifact_sha256 for source in candidate.sources)
        for record in SourceManifest.hydrate(registry.require(source_digest, EvidenceKind.SOURCE).payload()).records
    )
    if len(set(record_identities)) != len(record_identities):
        raise PermissionError("experiment cannot split duplicate source records")
    record_times = tuple(identity[2] for identity in record_identities)
    train = tuple(
        value for value in record_times if window_start <= value < _utc_datetime(binding.train_end, "train end")
    )
    validation = tuple(
        value
        for value in record_times
        if _utc_datetime(binding.train_end, "train end")
        <= value
        < _utc_datetime(binding.validation_end, "validation end")
    )
    test = tuple(
        value
        for value in record_times
        if _utc_datetime(binding.validation_end, "validation end")
        <= value
        <= _utc_datetime(binding.test_end, "test end")
    )
    validation_after_embargo = validation[binding.embargo_bars :]
    test_after_embargo = test[binding.embargo_bars :]
    if not train or not validation_after_embargo or not test_after_embargo:
        raise PermissionError("experiment split or post-embargo validation/test sample is empty")
    if readiness is ExperimentReadiness.READY and candidate.eligibility is not ResearchEligibility.ELIGIBLE:
        raise PermissionError("only eligible candidates can create READY experiments")
    payload: dict[str, JsonValue] = {
        "schema_version": _SCHEMA,
        "candidate_sha256": candidate.content_sha256,
        "readiness": readiness.value,
        "evidence": candidate.evidence.to_dict(),
        "binding": binding.to_dict(),
        "research_question": "该确定性候选能否在独立窗口保持预注册研究门槛",
        "primary_change": "只改变独立时间窗口并保持其他输入冻结",
        "tradable": False,
        "strategy_candidate_created": False,
    }
    return NextResearchExperiment(
        _SCHEMA,
        candidate.content_sha256,
        readiness,
        candidate.evidence,
        binding,
        cast(str, payload["research_question"]),
        cast(str, payload["primary_change"]),
        False,
        False,
        canonical_sha256(payload),
        authority.sign(payload),
    )


@dataclass(frozen=True, slots=True)
class ResearchDecisionBrief:
    schema_version: str
    producer: BriefProducer
    candidate_sha256: str
    action: ResearchAction
    why_now: str
    supporting_claims: tuple[GroundedTextClaim, ...]
    strongest_counter_claim: GroundedTextClaim
    candidate_unknowns: tuple[str, ...]
    additional_unknown_categories: tuple[NarrativeCategory, ...]
    falsifiable_hypothesis: str
    source_refs: tuple[SourceReference, ...]
    deterministic_facts_json: str
    warnings: tuple[str, ...]
    next_experiment: NextResearchExperiment
    tradable: bool
    strategy_candidate_created: bool
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.producer) is not BriefProducer:
            raise ValueError("research brief schema/producer is invalid")
        _digest(self.candidate_sha256, "brief candidate")
        if type(self.action) is not ResearchAction:
            raise TypeError("research brief action must be closed")
        _closed_narrative_text(self.why_now, "brief rationale")
        _closed_narrative_text(self.falsifiable_hypothesis, "brief hypothesis")
        if not self.supporting_claims or any(type(value) is not GroundedTextClaim for value in self.supporting_claims):
            raise TypeError("research brief requires grounded supporting claims")
        if type(self.strongest_counter_claim) is not GroundedTextClaim:
            raise TypeError("research brief requires one strongest counter claim")
        if not self.candidate_unknowns or any(
            type(value) is not str or not value.strip() for value in self.candidate_unknowns
        ):
            raise TypeError("research brief requires exact candidate unknowns")
        if not self.additional_unknown_categories:
            raise TypeError("research brief requires closed additional unknown categories")
        for category in self.additional_unknown_categories:
            _narrative(category, "additional unknown category")
        if not self.source_refs or len({value.identity() for value in self.source_refs}) != len(self.source_refs):
            raise ValueError("research brief requires unique source identities")
        try:
            facts = json.loads(self.deterministic_facts_json)
        except json.JSONDecodeError as error:
            raise ValueError("research brief deterministic facts are invalid JSON") from error
        if (
            canonical_json_text(_json_value(facts, "research brief deterministic facts"))
            != self.deterministic_facts_json
        ):
            raise ValueError("research brief deterministic facts must be canonical JSON")
        if not self.warnings or any(type(value) is not str or not value.strip() for value in self.warnings):
            raise TypeError("research brief requires exact warnings")
        if type(self.next_experiment) is not NextResearchExperiment:
            raise TypeError("research brief requires a signed next experiment")
        if self.tradable is not False or self.strategy_candidate_created is not False:
            raise PermissionError("research briefs are strictly non-trading")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("research brief digest is invalid")
        _digest(self.signature_sha256, "research brief signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "producer": self.producer.value,
            "candidate_sha256": self.candidate_sha256,
            "action": self.action.value,
            "why_now": self.why_now,
            "supporting_claims": tuple(value.to_dict() for value in self.supporting_claims),
            "strongest_counter_claim": self.strongest_counter_claim.to_dict(),
            "candidate_unknowns": self.candidate_unknowns,
            "additional_unknown_categories": tuple(value.value for value in self.additional_unknown_categories),
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "source_refs": tuple(value.to_dict() for value in self.source_refs),
            "deterministic_facts_json": self.deterministic_facts_json,
            "warnings": self.warnings,
            "next_experiment": self.next_experiment.to_dict(),
            "tradable": False,
            "strategy_candidate_created": False,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> ResearchDecisionBrief:
        _keys(value, set(cls.__dataclass_fields__), "research decision brief")
        brief = cls(
            _text(value["schema_version"], "schema"),
            BriefProducer(_text(value["producer"], "producer")),
            _text(value["candidate_sha256"], "candidate"),
            ResearchAction(_text(value["action"], "action")),
            _text(value["why_now"], "why now"),
            tuple(
                GroundedTextClaim.hydrate(_mapping(item, "supporting claim"))
                for item in _array(value["supporting_claims"], "supporting claims")
            ),
            GroundedTextClaim.hydrate(_mapping(value["strongest_counter_claim"], "counter claim")),
            tuple(
                _text(item, "candidate unknown") for item in _array(value["candidate_unknowns"], "candidate unknowns")
            ),
            tuple(
                NarrativeCategory(_text(item, "additional unknown category"))
                for item in _array(value["additional_unknown_categories"], "additional unknown categories")
            ),
            _text(value["falsifiable_hypothesis"], "hypothesis"),
            tuple(
                SourceReference.hydrate(_mapping(item, "source reference"))
                for item in _array(value["source_refs"], "source references")
            ),
            _text(value["deterministic_facts_json"], "deterministic facts"),
            tuple(_text(item, "warning") for item in _array(value["warnings"], "warnings")),
            NextResearchExperiment.hydrate(_mapping(value["next_experiment"], "next experiment"), authority),
            _boolean(value["tradable"], "tradable"),
            _boolean(value["strategy_candidate_created"], "strategy candidate"),
            _text(value["content_sha256"], "content digest"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(brief.unsigned_payload(), brief.signature_sha256):
            raise PermissionError("research brief signature is invalid")
        return brief

    @property
    def unknowns(self) -> tuple[str, ...]:
        return self.candidate_unknowns + tuple(
            _narrative(value, "additional unknown category") for value in self.additional_unknown_categories
        )

    def verify_for_candidate(self, candidate: ResearchCandidatePacket) -> None:
        if self.candidate_sha256 != candidate.content_sha256 or self.candidate_unknowns != candidate.unknowns:
            raise PermissionError("research brief does not preserve exact candidate unknowns")


@dataclass(frozen=True, slots=True)
class AgentRunOutcome:
    candidate_sha256: str
    proposal_sha256: str
    research_run_sha256: str
    synthesis_receipt_sha256: str
    experiment_design_receipt_sha256: str
    brief: ResearchDecisionBrief
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.candidate_sha256,
            self.proposal_sha256,
            self.research_run_sha256,
            self.synthesis_receipt_sha256,
            self.experiment_design_receipt_sha256,
        ):
            _digest(value, "agent outcome binding")
        if type(self.brief) is not ResearchDecisionBrief or self.brief.candidate_sha256 != self.candidate_sha256:
            raise PermissionError("agent outcome requires its exact candidate-bound brief")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("agent outcome digest is invalid")
        _digest(self.signature_sha256, "agent outcome signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "candidate_sha256": self.candidate_sha256,
            "proposal_sha256": self.proposal_sha256,
            "research_run_sha256": self.research_run_sha256,
            "synthesis_receipt_sha256": self.synthesis_receipt_sha256,
            "experiment_design_receipt_sha256": self.experiment_design_receipt_sha256,
            "brief": self.brief.to_dict(),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> AgentRunOutcome:
        _keys(value, set(cls.__dataclass_fields__), "agent run outcome")
        outcome = cls(
            _text(value["candidate_sha256"], "agent outcome candidate"),
            _text(value["proposal_sha256"], "agent outcome proposal"),
            _text(value["research_run_sha256"], "agent outcome research run"),
            _text(value["synthesis_receipt_sha256"], "agent outcome synthesis receipt"),
            _text(value["experiment_design_receipt_sha256"], "agent outcome experiment receipt"),
            ResearchDecisionBrief.hydrate(_mapping(value["brief"], "agent outcome brief"), authority),
            _text(value["content_sha256"], "agent outcome content"),
            _text(value["signature_sha256"], "agent outcome signature"),
        )
        if not authority.verify(outcome.unsigned_payload(), outcome.signature_sha256):
            raise PermissionError("agent outcome signature is invalid")
        return outcome

    @property
    def action(self) -> ResearchAction:
        return self.brief.action

    @property
    def next_experiment(self) -> NextResearchExperiment:
        return self.brief.next_experiment

    @property
    def strongest_counter_claim(self) -> GroundedTextClaim:
        return self.brief.strongest_counter_claim


def _require_completed_receipt(
    registry: OwnerEvidenceRegistry,
    receipt_sha256: str,
    *,
    workload_id: str,
    subject_sha256: str,
    input_lineage: tuple[RuntimeInputRef, ...],
) -> RuntimeReceiptPayload:
    receipt = registry.require_runtime_receipt(receipt_sha256)
    if (
        receipt.status != "COMPLETED"
        or receipt.workload_id != workload_id
        or receipt.subject_sha256 != subject_sha256
        or receipt.input_lineage != input_lineage
        or receipt.reroute_sha256s
        or receipt.activity_sha256s
    ):
        raise PermissionError("runtime receipt does not bind the completed frozen workload and typed inputs")
    return receipt


def _verify_research_receipts(
    *,
    registry: OwnerEvidenceRegistry,
    candidate: ResearchCandidatePacket,
    proposal: ResearchProposal,
    binding: ExperimentBinding,
    run: Mapping[str, object],
    synthesis_receipt_sha256: str,
    experiment_design_receipt_sha256: str,
) -> tuple[RuntimeReceiptPayload, RuntimeReceiptPayload]:
    binding_sha256 = canonical_sha256(binding.to_dict())
    if run.get("experiment_binding_sha256") != binding_sha256:
        raise PermissionError("research run does not bind the exact experiment design input")
    synthesis = _require_completed_receipt(
        registry,
        synthesis_receipt_sha256,
        workload_id="research.hypothesis_synthesis",
        subject_sha256=candidate.content_sha256,
        input_lineage=(RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, candidate.content_sha256),),
    )
    experiment = _require_completed_receipt(
        registry,
        experiment_design_receipt_sha256,
        workload_id="experiment.preregistration_design",
        subject_sha256=candidate.content_sha256,
        input_lineage=(
            RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, candidate.content_sha256),
            RuntimeInputRef(RuntimeInputKind.EXPERIMENT_BINDING, binding_sha256),
        ),
    )
    synthesis_output = registry.require(
        _digest(run.get("synthesis_output_sha256"), "synthesis output"), EvidenceKind.MODEL_OUTPUT
    ).payload()
    experiment_output = registry.require(
        _digest(run.get("experiment_design_output_sha256"), "experiment output"), EvidenceKind.MODEL_OUTPUT
    ).payload()
    if (
        run.get("synthesis_receipt_sha256") != synthesis_receipt_sha256
        or run.get("experiment_design_receipt_sha256") != experiment_design_receipt_sha256
        or synthesis_output.get("wire") != _research_proposal_wire(proposal)
        or experiment_output.get("wire") != {"design_category": "USE_FROZEN_BINDING"}
        or synthesis.profile_sha256 != binding.profile_sha256
        or synthesis.prompt_sha256 != binding.prompt_sha256
        or synthesis.schema_sha256 != binding.schema_sha256
        or synthesis.toolset_sha256 != candidate.evidence.toolset_sha256
        or synthesis.runtime_sha256 != candidate.evidence.runtime_sha256
        or RuntimeOwnerBinding.hydrate(
            _mapping(run.get("synthesis_owner_binding"), "synthesis owner binding")
        ).owner_digests
        != (
            synthesis.profile_sha256,
            synthesis.prompt_sha256,
            synthesis.schema_sha256,
            synthesis.toolset_sha256,
            synthesis.runtime_sha256,
        )
        or RuntimeOwnerBinding.hydrate(
            _mapping(run.get("experiment_design_owner_binding"), "experiment owner binding")
        ).owner_digests
        != (
            experiment.profile_sha256,
            experiment.prompt_sha256,
            experiment.schema_sha256,
            experiment.toolset_sha256,
            experiment.runtime_sha256,
        )
        or synthesis.invocation_id != run.get("invocation_id")
        or synthesis.response_id != run.get("response_id")
        or synthesis.actual_provider != run.get("actual_provider")
        or synthesis.actual_model_id != run.get("actual_model_id")
        or synthesis.actual_reasoning_effort != run.get("actual_reasoning_effort")
        or synthesis.input_tokens != run.get("input_tokens")
        or synthesis.output_tokens != run.get("output_tokens")
        or synthesis.reasoning_tokens != run.get("reasoning_tokens")
        or (synthesis.cached_input_tokens or 0) + (synthesis.cache_write_input_tokens or 0) != run.get("cache_tokens")
        or synthesis.latency_ms != run.get("latency_ms")
    ):
        raise PermissionError("research run facts do not exactly derive from its synthesis receipt")
    return synthesis, experiment


def verify_agent_run_outcome(
    candidate: ResearchCandidatePacket,
    outcome: AgentRunOutcome,
    authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
    binding: ExperimentBinding | None = None,
) -> AgentRunOutcome:
    """Rehydrate the signed Agent result and its exact owner-signed run lineage.

    A brief alone is deliberately not a model-run artifact.  Every downstream
    consumer uses this verifier so a different, lower-usage RESEARCH_RUN that
    happens to have produced an identical brief cannot be substituted.
    """

    checked_candidate = ResearchCandidatePacket.hydrate(candidate.to_dict(), authority, registry)
    checked = AgentRunOutcome.hydrate(outcome.to_dict(), authority)
    checked.brief.verify_for_candidate(checked_candidate)
    if (
        checked.candidate_sha256 != checked_candidate.content_sha256
        or checked.brief.producer is not BriefProducer.AGENT
    ):
        raise PermissionError("agent run outcome does not bind the original Agent candidate and brief")
    run = registry.require(checked.research_run_sha256, EvidenceKind.RESEARCH_RUN).payload()
    _keys(
        run,
        {
            "candidate_sha256",
            "proposal_sha256",
            "agent_brief_sha256",
            "invocation_authorization_sha256",
            "invocation_id",
            "synthesis_receipt_sha256",
            "experiment_design_receipt_sha256",
            "synthesis_output_sha256",
            "experiment_design_output_sha256",
            "synthesis_owner_binding",
            "experiment_design_owner_binding",
            "experiment_binding_sha256",
            "response_sha256",
            "response_id",
            "workload_id",
            "profile_sha256",
            "prompt_sha256",
            "schema_sha256",
            "toolset_sha256",
            "runtime_sha256",
            "actual_provider",
            "actual_model_id",
            "actual_reasoning_effort",
            "actual_profile_id",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_tokens",
            "latency_ms",
            "reroutes",
        },
        "research run evidence",
    )
    expected = {
        "candidate_sha256": checked_candidate.content_sha256,
        "proposal_sha256": checked.proposal_sha256,
        "agent_brief_sha256": checked.brief.content_sha256,
        "workload_id": "research.hypothesis_synthesis",
        "toolset_sha256": checked_candidate.evidence.toolset_sha256,
        "runtime_sha256": checked_candidate.evidence.runtime_sha256,
    }
    if binding is not None:
        expected.update(
            {
                "profile_sha256": binding.profile_sha256,
                "prompt_sha256": binding.prompt_sha256,
                "schema_sha256": binding.schema_sha256,
            }
        )
    if any(run[key] != value for key, value in expected.items()):
        raise PermissionError("agent run outcome does not bind its exact frozen research run")
    synthesis_output = registry.require(
        _digest(run["synthesis_output_sha256"], "synthesis output"), EvidenceKind.MODEL_OUTPUT
    ).payload()
    proposal = _research_proposal_from_wire(
        _mapping(synthesis_output["wire"], "synthesis output wire"), checked_candidate.content_sha256
    )
    if proposal.content_sha256 != checked.proposal_sha256:
        raise PermissionError("agent outcome proposal does not derive from the exact runtime output")
    _verify_research_receipts(
        registry=registry,
        candidate=checked_candidate,
        proposal=proposal,
        binding=binding or checked.brief.next_experiment.binding,
        run=run,
        synthesis_receipt_sha256=checked.synthesis_receipt_sha256,
        experiment_design_receipt_sha256=checked.experiment_design_receipt_sha256,
    )
    authorization = ResearchInvocationAuthorization.hydrate(
        registry.require(
            _digest(run["invocation_authorization_sha256"], "invocation authorization"),
            EvidenceKind.RESEARCH_INVOCATION,
        ).payload(),
        authority,
    )
    if (
        authorization.request_sha256 != checked.proposal_sha256
        or authorization.invocation_id != _text(run["invocation_id"], "invocation id")
        or _digest(run["response_sha256"], "research response") != checked.brief.content_sha256
    ):
        raise PermissionError("agent run outcome does not preserve its exact invocation and response")
    _text(run["response_id"], "research response id")
    for digest, kind in (
        (_text(run["profile_sha256"], "research profile"), EvidenceKind.PROFILE),
        (_text(run["prompt_sha256"], "research prompt"), EvidenceKind.PROMPT),
        (_text(run["schema_sha256"], "research schema"), EvidenceKind.SCHEMA),
        (_text(run["toolset_sha256"], "research toolset"), EvidenceKind.TOOLSET),
        (_text(run["runtime_sha256"], "research runtime"), EvidenceKind.RUNTIME),
    ):
        registry.require(digest, kind)
    qualification = FrozenProfileQualification.hydrate(
        registry.require(_text(run["profile_sha256"], "research profile"), EvidenceKind.PROFILE).payload()
    )
    if qualification.workload_id != "research.hypothesis_synthesis" or (
        _text(run["actual_provider"], "actual provider"),
        _text(run["actual_model_id"], "actual model"),
        _text(run["actual_profile_id"], "actual profile"),
    ) != (qualification.provider, qualification.model_id, qualification.profile_id):
        raise PermissionError("agent run outcome does not match its frozen research profile")
    for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens", "latency_ms"):
        _integer(run[name], name, minimum=0)
    if _array(run["reroutes"], "research reroutes"):
        raise PermissionError("agent run outcome reports a forbidden reroute")
    return checked


def _issue_brief(
    *,
    authority: PhaseZeroAuthority,
    candidate: ResearchCandidatePacket,
    binding: ExperimentBinding,
    registry: OwnerEvidenceRegistry,
    producer: BriefProducer,
    action: ResearchAction,
    why_now: NarrativeCategory,
    supporting_claims: tuple[GroundedTextClaim, ...],
    strongest_counter_claim: GroundedTextClaim,
    unknowns: tuple[NarrativeCategory, ...],
    falsifiable_hypothesis: NarrativeCategory,
) -> ResearchDecisionBrief:
    readiness = ExperimentReadiness.READY if action is ResearchAction.TEST_NEXT else ExperimentReadiness.NOT_REQUESTED
    experiment = build_next_experiment(candidate, readiness, binding, authority, registry)
    facts = canonical_json_text(candidate.unsigned_payload())
    warnings = candidate.roll_warnings + candidate.warnings
    rendered_why_now = _narrative(why_now, "brief why-now category")
    rendered_hypothesis = _narrative(falsifiable_hypothesis, "brief hypothesis category")
    payload: dict[str, JsonValue] = {
        "schema_version": _SCHEMA,
        "producer": producer.value,
        "candidate_sha256": candidate.content_sha256,
        "action": action.value,
        "why_now": rendered_why_now,
        "supporting_claims": tuple(value.to_dict() for value in supporting_claims),
        "strongest_counter_claim": strongest_counter_claim.to_dict(),
        "candidate_unknowns": candidate.unknowns,
        "additional_unknown_categories": tuple(value.value for value in unknowns),
        "falsifiable_hypothesis": rendered_hypothesis,
        "source_refs": tuple(value.to_dict() for value in candidate.sources),
        "deterministic_facts_json": facts,
        "warnings": warnings,
        "next_experiment": experiment.to_dict(),
        "tradable": False,
        "strategy_candidate_created": False,
    }
    return ResearchDecisionBrief(
        _SCHEMA,
        producer,
        candidate.content_sha256,
        action,
        rendered_why_now,
        supporting_claims,
        strongest_counter_claim,
        candidate.unknowns,
        unknowns,
        rendered_hypothesis,
        candidate.sources,
        facts,
        warnings,
        experiment,
        False,
        False,
        canonical_sha256(payload),
        authority.sign(payload),
    )


class ResearchRunner:
    """Converts a typed model proposal into a signed, governed research brief."""

    def __init__(
        self,
        authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
        experiment_binding: ExperimentBinding,
    ) -> None:
        self._authority = authority
        self._registry = registry
        self._binding = experiment_binding

    @property
    def side_effects(self) -> tuple[object, ...]:
        return ()

    def _candidate(self, candidate: ResearchCandidatePacket) -> ResearchCandidatePacket:
        return ResearchCandidatePacket.hydrate(candidate.to_dict(), self._authority, self._registry)

    def _validate_proposal(self, candidate: ResearchCandidatePacket, proposal: ResearchProposal) -> None:
        if proposal.candidate_sha256 != candidate.content_sha256:
            raise PermissionError("proposal does not bind the signed candidate")
        _validate_action_authority(candidate.eligibility, proposal.action)
        if tuple(value.to_dict() for value in proposal.source_refs) != tuple(
            value.to_dict() for value in candidate.sources
        ):
            raise PermissionError("proposal must preserve the exact candidate source roster")
        canonical_sources = {value.identity(): value for value in candidate.sources}
        for claim in (*proposal.supporting_claims, proposal.strongest_counter_claim):
            for reference in claim.evidence_refs:
                if canonical_sources.get(reference.identity()) != reference:
                    raise PermissionError("claim grounding must use an exact candidate source reference")
                self._registry.verify_source(reference)
        if len(set(proposal.additional_unknowns)) != len(proposal.additional_unknowns):
            raise ValueError("proposal unknowns must be unique")

    def preview_agent_brief(
        self, candidate: ResearchCandidatePacket, proposal: ResearchProposal
    ) -> ResearchDecisionBrief:
        checked = self._candidate(candidate)
        self._validate_proposal(checked, proposal)
        return _issue_brief(
            authority=self._authority,
            candidate=checked,
            binding=self._binding,
            registry=self._registry,
            producer=BriefProducer.AGENT,
            action=proposal.action,
            why_now=proposal.why_now,
            supporting_claims=proposal.supporting_claims,
            strongest_counter_claim=proposal.strongest_counter_claim,
            unknowns=proposal.additional_unknowns,
            falsifiable_hypothesis=proposal.falsifiable_hypothesis,
        )

    def _verify_research_run(
        self,
        candidate: ResearchCandidatePacket,
        proposal: ResearchProposal,
        brief: ResearchDecisionBrief,
        research_run_sha256: str,
    ) -> None:
        run = self._registry.require(research_run_sha256, EvidenceKind.RESEARCH_RUN).payload()
        _keys(
            run,
            {
                "candidate_sha256",
                "proposal_sha256",
                "agent_brief_sha256",
                "invocation_authorization_sha256",
                "invocation_id",
                "synthesis_receipt_sha256",
                "experiment_design_receipt_sha256",
                "synthesis_output_sha256",
                "experiment_design_output_sha256",
                "synthesis_owner_binding",
                "experiment_design_owner_binding",
                "experiment_binding_sha256",
                "response_sha256",
                "response_id",
                "workload_id",
                "profile_sha256",
                "prompt_sha256",
                "schema_sha256",
                "toolset_sha256",
                "runtime_sha256",
                "actual_provider",
                "actual_model_id",
                "actual_reasoning_effort",
                "actual_profile_id",
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cache_tokens",
                "latency_ms",
                "reroutes",
            },
            "research run evidence",
        )
        expected = {
            "candidate_sha256": candidate.content_sha256,
            "proposal_sha256": proposal.content_sha256,
            "agent_brief_sha256": brief.content_sha256,
            "workload_id": "research.hypothesis_synthesis",
            "profile_sha256": self._binding.profile_sha256,
            "prompt_sha256": self._binding.prompt_sha256,
            "schema_sha256": self._binding.schema_sha256,
            "toolset_sha256": candidate.evidence.toolset_sha256,
            "runtime_sha256": candidate.evidence.runtime_sha256,
        }
        if any(run[key] != value for key, value in expected.items()):
            raise PermissionError("research run evidence does not bind the frozen proposal and brief")
        _verify_research_receipts(
            registry=self._registry,
            candidate=candidate,
            proposal=proposal,
            binding=self._binding,
            run=run,
            synthesis_receipt_sha256=_text(run["synthesis_receipt_sha256"], "synthesis receipt"),
            experiment_design_receipt_sha256=_text(
                run["experiment_design_receipt_sha256"], "experiment design receipt"
            ),
        )
        authorization = ResearchInvocationAuthorization.hydrate(
            self._registry.require(
                _digest(run["invocation_authorization_sha256"], "invocation authorization"),
                EvidenceKind.RESEARCH_INVOCATION,
            ).payload(),
            self._authority,
        )
        if (
            authorization.request_sha256 != proposal.content_sha256
            or authorization.invocation_id != _text(run["invocation_id"], "invocation id")
            or _digest(run["response_sha256"], "research response") != brief.content_sha256
        ):
            raise PermissionError("research run does not preserve its exact invocation and response")
        _text(run["response_id"], "research response id")
        qualification = FrozenProfileQualification.hydrate(
            self._registry.require(self._binding.profile_sha256, EvidenceKind.PROFILE).payload()
        )
        if (qualification.workload_id, qualification.provider, qualification.model_id, qualification.profile_id) != (
            "research.hypothesis_synthesis",
            run["actual_provider"],
            run["actual_model_id"],
            run["actual_profile_id"],
        ):
            raise PermissionError("research run does not match its frozen provider/model/profile")
        for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens", "latency_ms"):
            _integer(run[name], name, minimum=0)
        if _array(run["reroutes"], "research reroutes"):
            raise PermissionError("research run reports a forbidden reroute")

    def agent_without_critic(
        self,
        candidate: ResearchCandidatePacket,
        proposal: ResearchProposal,
        research_run_sha256: str,
    ) -> AgentRunOutcome:
        brief = self.preview_agent_brief(candidate, proposal)
        checked = self._candidate(candidate)
        self._verify_research_run(checked, proposal, brief, research_run_sha256)
        payload: dict[str, JsonValue] = {
            "candidate_sha256": checked.content_sha256,
            "proposal_sha256": proposal.content_sha256,
            "research_run_sha256": research_run_sha256,
            "synthesis_receipt_sha256": _text(
                self._registry.require(research_run_sha256, EvidenceKind.RESEARCH_RUN).payload()[
                    "synthesis_receipt_sha256"
                ],
                "synthesis receipt",
            ),
            "experiment_design_receipt_sha256": _text(
                self._registry.require(research_run_sha256, EvidenceKind.RESEARCH_RUN).payload()[
                    "experiment_design_receipt_sha256"
                ],
                "experiment design receipt",
            ),
            "brief": brief.to_dict(),
        }
        return AgentRunOutcome(
            checked.content_sha256,
            proposal.content_sha256,
            research_run_sha256,
            cast(str, payload["synthesis_receipt_sha256"]),
            cast(str, payload["experiment_design_receipt_sha256"]),
            brief,
            canonical_sha256(payload),
            self._authority.sign(payload),
        )

    def defer_for_failure(
        self,
        candidate: ResearchCandidatePacket,
        failure_sha256: str,
    ) -> ResearchDecisionBrief:
        checked = self._candidate(candidate)
        failure = self._registry.require(failure_sha256, EvidenceKind.FAILURE).payload()
        _keys(failure, {"candidate_sha256", "failure_code", "detail_source", "token_usage"}, "failure evidence")
        if failure["candidate_sha256"] != checked.content_sha256:
            raise PermissionError("failure evidence does not bind the candidate")
        DeterministicFailureCode(_text(failure["failure_code"], "failure code"))
        reference = SourceReference.hydrate(_mapping(failure["detail_source"], "failure detail source"))
        if reference not in checked.sources:
            raise PermissionError("failure detail must use an exact candidate source")
        usage = _mapping(failure["token_usage"], "failure token usage")
        _keys(usage, {"input_tokens", "output_tokens", "reasoning_tokens"}, "failure token usage")
        if any(_integer(usage[name], name, minimum=0) != 0 for name in usage):
            raise PermissionError("deterministic failure DEFER must consume zero model tokens")
        _validate_action_authority(checked.eligibility, ResearchAction.DEFER, deterministic_failure=True)
        claim = GroundedTextClaim(NarrativeCategory.DETERMINISTIC_INPUT_UNAVAILABLE, (reference,))
        return _issue_brief(
            authority=self._authority,
            candidate=checked,
            binding=self._binding,
            registry=self._registry,
            producer=BriefProducer.DETERMINISTIC_FAILURE,
            action=ResearchAction.DEFER,
            why_now=NarrativeCategory.DETERMINISTIC_INPUT_UNAVAILABLE,
            supporting_claims=(claim,),
            strongest_counter_claim=GroundedTextClaim(NarrativeCategory.INPUT_RECOVERY_REEVALUATION, (reference,)),
            unknowns=(NarrativeCategory.INPUT_RECOVERY_REEVALUATION,),
            falsifiable_hypothesis=NarrativeCategory.INPUT_RECOVERY_REEVALUATION,
        )

    def agent_with_critic(
        self,
        candidate: ResearchCandidatePacket,
        agent_outcome: AgentRunOutcome,
        critic_request: IndependentCriticRequest,
        critic_artifact: CriticArtifact,
        critic: IndependentCritic,
    ) -> AgentCriticOutcome:
        return _issue_governed_outcome(
            authority=self._authority,
            registry=self._registry,
            binding=self._binding,
            candidate=self._candidate(candidate),
            agent_outcome=agent_outcome,
            critic_request=critic_request,
            critic_artifact=critic_artifact,
            critic=critic,
        )


class DeterministicTemplateBaseline:
    def __init__(
        self,
        authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
        experiment_binding: ExperimentBinding,
    ) -> None:
        self._authority = authority
        self._registry = registry
        self._binding = experiment_binding

    def render(self, candidate: ResearchCandidatePacket) -> ResearchDecisionBrief:
        checked = ResearchCandidatePacket.hydrate(candidate.to_dict(), self._authority, self._registry)
        action = {
            ResearchEligibility.ELIGIBLE: ResearchAction.TEST_NEXT,
            ResearchEligibility.INSUFFICIENT_EVIDENCE: ResearchAction.WATCH_FOR_DATA,
            ResearchEligibility.REJECTED: ResearchAction.REJECT_AS_UNSUPPORTED,
        }[checked.eligibility]
        claim = GroundedTextClaim(NarrativeCategory.SCREENING_SUPPORTS_RESEARCH, checked.sources)
        return _issue_brief(
            authority=self._authority,
            candidate=checked,
            binding=self._binding,
            registry=self._registry,
            producer=BriefProducer.DETERMINISTIC_TEMPLATE,
            action=action,
            why_now=NarrativeCategory.FROZEN_THRESHOLD_RATIONALE,
            supporting_claims=(claim,),
            strongest_counter_claim=GroundedTextClaim(NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN, checked.sources),
            unknowns=(NarrativeCategory.INDEPENDENT_WINDOW_UNKNOWN,),
            falsifiable_hypothesis=NarrativeCategory.FROZEN_HYPOTHESIS,
        )


class AlwaysDispositionBaseline:
    def __init__(
        self,
        authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
        experiment_binding: ExperimentBinding,
    ) -> None:
        self._authority = authority
        self._registry = registry
        self._binding = experiment_binding

    def render(self, candidate: ResearchCandidatePacket, action: ResearchAction) -> ResearchDecisionBrief:
        if action not in {ResearchAction.REJECT_AS_UNSUPPORTED, ResearchAction.DEFER}:
            raise ValueError("always-disposition baseline supports only REJECT or DEFER")
        checked = ResearchCandidatePacket.hydrate(candidate.to_dict(), self._authority, self._registry)
        producer = (
            BriefProducer.ALWAYS_REJECT
            if action is ResearchAction.REJECT_AS_UNSUPPORTED
            else BriefProducer.ALWAYS_DEFER
        )
        claim = GroundedTextClaim(NarrativeCategory.FIXED_ABLATION, checked.sources)
        return _issue_brief(
            authority=self._authority,
            candidate=checked,
            binding=self._binding,
            registry=self._registry,
            producer=producer,
            action=action,
            why_now=NarrativeCategory.FIXED_ABLATION,
            supporting_claims=(claim,),
            strongest_counter_claim=GroundedTextClaim(NarrativeCategory.ABLATION_COUNTERFACTUAL, checked.sources),
            unknowns=(NarrativeCategory.ABLATION_COUNTERFACTUAL,),
            falsifiable_hypothesis=NarrativeCategory.ABLATION_COUNTERFACTUAL,
        )


@dataclass(frozen=True, slots=True)
class IndependentCriticInvocation:
    schema_version: str
    workload_id: str
    run_id: str
    candidate_sha256: str
    agent_outcome_sha256: str
    research_run_sha256: str
    brief_sha256: str
    profile_sha256: str
    prompt_sha256: str
    schema_sha256: str
    toolset_sha256: str
    runtime_sha256: str
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or self.workload_id != "assurance.adversarial_critique":
            raise ValueError("critic request schema/workload is invalid")
        _text(self.run_id, "critic run id")
        for value in (
            self.candidate_sha256,
            self.agent_outcome_sha256,
            self.research_run_sha256,
            self.brief_sha256,
            self.profile_sha256,
            self.prompt_sha256,
            self.schema_sha256,
            self.toolset_sha256,
            self.runtime_sha256,
        ):
            _digest(value, "critic request binding")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("critic request digest is invalid")
        _digest(self.signature_sha256, "critic request signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "run_id": self.run_id,
            "candidate_sha256": self.candidate_sha256,
            "agent_outcome_sha256": self.agent_outcome_sha256,
            "research_run_sha256": self.research_run_sha256,
            "brief_sha256": self.brief_sha256,
            "profile_sha256": self.profile_sha256,
            "prompt_sha256": self.prompt_sha256,
            "schema_sha256": self.schema_sha256,
            "toolset_sha256": self.toolset_sha256,
            "runtime_sha256": self.runtime_sha256,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> IndependentCriticInvocation:
        _keys(value, set(cls.__dataclass_fields__), "independent critic request")
        request = cls(
            _text(value["schema_version"], "schema"),
            _text(value["workload_id"], "workload"),
            _text(value["run_id"], "run id"),
            _text(value["candidate_sha256"], "candidate"),
            _text(value["agent_outcome_sha256"], "agent outcome"),
            _text(value["research_run_sha256"], "research run"),
            _text(value["brief_sha256"], "brief"),
            _text(value["profile_sha256"], "profile"),
            _text(value["prompt_sha256"], "prompt"),
            _text(value["schema_sha256"], "response schema"),
            _text(value["toolset_sha256"], "toolset"),
            _text(value["runtime_sha256"], "runtime"),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(request.unsigned_payload(), request.signature_sha256):
            raise PermissionError("critic request signature is invalid")
        return request


@dataclass(frozen=True, slots=True)
class IndependentCriticRequest:
    invocation: IndependentCriticInvocation
    critic_receipt_sha256: str
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if type(self.invocation) is not IndependentCriticInvocation:
            raise TypeError("critic request requires a typed invocation")
        _digest(self.critic_receipt_sha256, "critic receipt")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("critic request digest is invalid")
        _digest(self.signature_sha256, "critic request signature")

    @property
    def schema_version(self) -> str:
        return self.invocation.schema_version

    @property
    def workload_id(self) -> str:
        return self.invocation.workload_id

    @property
    def run_id(self) -> str:
        return self.invocation.run_id

    @property
    def candidate_sha256(self) -> str:
        return self.invocation.candidate_sha256

    @property
    def agent_outcome_sha256(self) -> str:
        return self.invocation.agent_outcome_sha256

    @property
    def research_run_sha256(self) -> str:
        return self.invocation.research_run_sha256

    @property
    def brief_sha256(self) -> str:
        return self.invocation.brief_sha256

    @property
    def profile_sha256(self) -> str:
        return self.invocation.profile_sha256

    @property
    def prompt_sha256(self) -> str:
        return self.invocation.prompt_sha256

    @property
    def schema_sha256(self) -> str:
        return self.invocation.schema_sha256

    @property
    def toolset_sha256(self) -> str:
        return self.invocation.toolset_sha256

    @property
    def runtime_sha256(self) -> str:
        return self.invocation.runtime_sha256

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "invocation": self.invocation.to_dict(),
            "critic_receipt_sha256": self.critic_receipt_sha256,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> IndependentCriticRequest:
        _keys(value, set(cls.__dataclass_fields__), "independent critic request")
        request = cls(
            IndependentCriticInvocation.hydrate(_mapping(value["invocation"], "critic invocation"), authority),
            _text(value["critic_receipt_sha256"], "critic receipt"),
            _text(value["content_sha256"], "critic request content"),
            _text(value["signature_sha256"], "critic request signature"),
        )
        if not authority.verify(request.unsigned_payload(), request.signature_sha256):
            raise PermissionError("critic request signature is invalid")
        return request


@dataclass(frozen=True, slots=True)
class CriticArtifact:
    schema_version: str
    request_sha256: str
    candidate_sha256: str
    brief_sha256: str
    run_evidence_sha256: str
    critic_receipt_sha256: str
    decision: CriticDecision
    reason: str
    actual_provider: str
    actual_model_id: str
    actual_profile_id: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_tokens: int
    latency_ms: int
    reroutes: tuple[str, ...]
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.decision) is not CriticDecision:
            raise ValueError("critic artifact schema/decision is invalid")
        for value in (
            self.request_sha256,
            self.candidate_sha256,
            self.brief_sha256,
            self.run_evidence_sha256,
            self.critic_receipt_sha256,
        ):
            _digest(value, "critic artifact binding")
        _closed_narrative_text(self.reason, "critic reason")
        _text(self.actual_provider, "critic actual provider")
        _text(self.actual_model_id, "critic actual model")
        _text(self.actual_profile_id, "critic actual profile")
        for numeric_value, label in (
            (self.input_tokens, "input tokens"),
            (self.output_tokens, "output tokens"),
            (self.reasoning_tokens, "reasoning tokens"),
            (self.cache_tokens, "cache tokens"),
            (self.latency_ms, "latency"),
        ):
            _integer(numeric_value, label, minimum=0)
        if self.reroutes:
            raise PermissionError("Phase-0 critic runs cannot silently reroute")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("critic artifact digest is invalid")
        _digest(self.signature_sha256, "critic artifact signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "request_sha256": self.request_sha256,
            "candidate_sha256": self.candidate_sha256,
            "brief_sha256": self.brief_sha256,
            "run_evidence_sha256": self.run_evidence_sha256,
            "critic_receipt_sha256": self.critic_receipt_sha256,
            "decision": self.decision.value,
            "reason": self.reason,
            "actual_provider": self.actual_provider,
            "actual_model_id": self.actual_model_id,
            "actual_profile_id": self.actual_profile_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_tokens": self.cache_tokens,
            "latency_ms": self.latency_ms,
            "reroutes": self.reroutes,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> CriticArtifact:
        _keys(value, set(cls.__dataclass_fields__), "critic artifact")
        artifact = cls(
            _text(value["schema_version"], "schema"),
            _text(value["request_sha256"], "request"),
            _text(value["candidate_sha256"], "candidate"),
            _text(value["brief_sha256"], "brief"),
            _text(value["run_evidence_sha256"], "run evidence"),
            _text(value["critic_receipt_sha256"], "critic receipt"),
            CriticDecision(_text(value["decision"], "decision")),
            _closed_narrative_text(value["reason"], "reason"),
            _text(value["actual_provider"], "actual provider"),
            _text(value["actual_model_id"], "actual model"),
            _text(value["actual_profile_id"], "actual profile"),
            _integer(value["input_tokens"], "input tokens", minimum=0),
            _integer(value["output_tokens"], "output tokens", minimum=0),
            _integer(value["reasoning_tokens"], "reasoning tokens", minimum=0),
            _integer(value["cache_tokens"], "cache tokens", minimum=0),
            _integer(value["latency_ms"], "latency", minimum=0),
            tuple(_text(item, "reroute") for item in _array(value["reroutes"], "reroutes")),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(artifact.unsigned_payload(), artifact.signature_sha256):
            raise PermissionError("critic artifact signature is invalid")
        return artifact


class IndependentCritic:
    """Consumes a signed model-run record; callers cannot supply a verdict directly."""

    def __init__(
        self,
        candidate_authority: PhaseZeroAuthority,
        critic_authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
    ) -> None:
        self._candidate_authority = candidate_authority
        self._critic_authority = critic_authority
        self._registry = registry

    def prepare_request(
        self,
        candidate: ResearchCandidatePacket,
        agent_outcome: AgentRunOutcome,
        *,
        run_id: str,
        profile_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        toolset_sha256: str,
        runtime_sha256: str,
    ) -> IndependentCriticInvocation:
        checked_candidate = ResearchCandidatePacket.hydrate(
            candidate.to_dict(), self._candidate_authority, self._registry
        )
        checked_outcome = verify_agent_run_outcome(
            checked_candidate,
            agent_outcome,
            self._candidate_authority,
            self._registry,
        )
        checked_brief = checked_outcome.brief
        if (
            checked_brief.producer is not BriefProducer.AGENT
            or checked_brief.candidate_sha256 != checked_candidate.content_sha256
        ):
            raise PermissionError("critic requests require the original candidate-bound Agent brief")
        _validate_action_authority(checked_candidate.eligibility, checked_brief.action)
        checked_brief.verify_for_candidate(checked_candidate)
        if checked_outcome.candidate_sha256 != checked_candidate.content_sha256:
            raise PermissionError("critic request outcome does not bind the candidate")
        for digest, kind in (
            (profile_sha256, EvidenceKind.PROFILE),
            (prompt_sha256, EvidenceKind.PROMPT),
            (schema_sha256, EvidenceKind.SCHEMA),
            (toolset_sha256, EvidenceKind.TOOLSET),
            (runtime_sha256, EvidenceKind.RUNTIME),
        ):
            self._registry.require(digest, kind)
        payload: dict[str, JsonValue] = {
            "schema_version": _SCHEMA,
            "workload_id": "assurance.adversarial_critique",
            "run_id": _text(run_id, "critic run id"),
            "candidate_sha256": checked_candidate.content_sha256,
            "agent_outcome_sha256": checked_outcome.content_sha256,
            "research_run_sha256": checked_outcome.research_run_sha256,
            "brief_sha256": checked_brief.content_sha256,
            "profile_sha256": _digest(profile_sha256, "profile"),
            "prompt_sha256": _digest(prompt_sha256, "prompt"),
            "schema_sha256": _digest(schema_sha256, "schema"),
            "toolset_sha256": _digest(toolset_sha256, "toolset"),
            "runtime_sha256": _digest(runtime_sha256, "runtime"),
        }
        return IndependentCriticInvocation(
            _SCHEMA,
            "assurance.adversarial_critique",
            cast(str, payload["run_id"]),
            checked_candidate.content_sha256,
            checked_outcome.content_sha256,
            checked_outcome.research_run_sha256,
            checked_brief.content_sha256,
            profile_sha256,
            prompt_sha256,
            schema_sha256,
            toolset_sha256,
            runtime_sha256,
            canonical_sha256(payload),
            self._critic_authority.sign(payload),
        )

    def bind_request(
        self,
        invocation: IndependentCriticInvocation,
        critic_receipt_sha256: str,
    ) -> IndependentCriticRequest:
        checked = IndependentCriticInvocation.hydrate(invocation.to_dict(), self._critic_authority)
        receipt = _require_completed_receipt(
            self._registry,
            critic_receipt_sha256,
            workload_id="assurance.adversarial_critique",
            subject_sha256=checked.content_sha256,
            input_lineage=(
                RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, checked.content_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, checked.candidate_sha256),
                RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, checked.agent_outcome_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, checked.research_run_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, checked.brief_sha256),
            ),
        )
        return self._bind_checked_receipt(checked, receipt, critic_receipt_sha256)

    def _bind_unregistered_receipt(
        self,
        invocation: IndependentCriticInvocation,
        receipt: RuntimeReceiptPayload,
        critic_receipt_sha256: str,
    ) -> IndependentCriticRequest:
        checked = IndependentCriticInvocation.hydrate(invocation.to_dict(), self._critic_authority)
        if type(receipt) is not RuntimeReceiptPayload or canonical_sha256(receipt.to_dict()) != _digest(
            critic_receipt_sha256, "critic receipt evidence"
        ):
            raise PermissionError("critic receipt evidence does not bind its signed payload")
        return self._bind_checked_receipt(checked, receipt, critic_receipt_sha256)

    def _bind_checked_receipt(
        self,
        checked: IndependentCriticInvocation,
        receipt: RuntimeReceiptPayload,
        critic_receipt_sha256: str,
    ) -> IndependentCriticRequest:
        if (
            receipt.status != "COMPLETED"
            or receipt.workload_id != "assurance.adversarial_critique"
            or receipt.subject_sha256 != checked.content_sha256
            or receipt.input_lineage
            != (
                RuntimeInputRef(RuntimeInputKind.CRITIC_INVOCATION, checked.content_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_CANDIDATE, checked.candidate_sha256),
                RuntimeInputRef(RuntimeInputKind.AGENT_OUTCOME, checked.agent_outcome_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_RUN, checked.research_run_sha256),
                RuntimeInputRef(RuntimeInputKind.RESEARCH_BRIEF, checked.brief_sha256),
            )
            or receipt.reroute_sha256s
            or receipt.activity_sha256s
            or receipt.run_id != checked.run_id
            or receipt.profile_sha256 != checked.profile_sha256
            or receipt.prompt_sha256 != checked.prompt_sha256
            or receipt.schema_sha256 != checked.schema_sha256
            or receipt.toolset_sha256 != checked.toolset_sha256
            or receipt.runtime_sha256 != checked.runtime_sha256
        ):
            raise PermissionError("critic receipt does not bind the exact request config and run")
        payload: dict[str, JsonValue] = {
            "invocation": checked.to_dict(),
            "critic_receipt_sha256": critic_receipt_sha256,
        }
        return IndependentCriticRequest(
            checked,
            critic_receipt_sha256,
            canonical_sha256(payload),
            self._critic_authority.sign(payload),
        )

    def request(
        self,
        candidate: ResearchCandidatePacket,
        agent_outcome: AgentRunOutcome,
        *,
        run_id: str,
        profile_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        toolset_sha256: str,
        runtime_sha256: str,
        critic_receipt_sha256: str,
    ) -> IndependentCriticRequest:
        return self.bind_request(
            self.prepare_request(
                candidate,
                agent_outcome,
                run_id=run_id,
                profile_sha256=profile_sha256,
                prompt_sha256=prompt_sha256,
                schema_sha256=schema_sha256,
                toolset_sha256=toolset_sha256,
                runtime_sha256=runtime_sha256,
            ),
            critic_receipt_sha256,
        )

    def review(self, request: IndependentCriticRequest, run_evidence_sha256: str) -> CriticArtifact:
        checked = self.verify_request(request)
        run = self._registry.require(run_evidence_sha256, EvidenceKind.CRITIC_RUN).payload()
        expected_keys = {
            "request_sha256",
            "workload_id",
            "candidate_sha256",
            "brief_sha256",
            "profile_sha256",
            "prompt_sha256",
            "schema_sha256",
            "toolset_sha256",
            "runtime_sha256",
            "critic_receipt_sha256",
            "critic_output_sha256",
            "critic_owner_binding",
            "decision",
            "reason_category",
            "reason",
            "actual_provider",
            "actual_model_id",
            "actual_reasoning_effort",
            "actual_profile_id",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_tokens",
            "latency_ms",
            "reroutes",
        }
        _keys(run, expected_keys, "critic run evidence")
        expected_bindings = {
            "request_sha256": checked.content_sha256,
            "workload_id": checked.workload_id,
            "candidate_sha256": checked.candidate_sha256,
            "brief_sha256": checked.brief_sha256,
            "profile_sha256": checked.profile_sha256,
            "prompt_sha256": checked.prompt_sha256,
            "schema_sha256": checked.schema_sha256,
            "toolset_sha256": checked.toolset_sha256,
            "runtime_sha256": checked.runtime_sha256,
            "critic_receipt_sha256": checked.critic_receipt_sha256,
        }
        if any(run[key] != value for key, value in expected_bindings.items()):
            raise PermissionError("critic run evidence does not bind the frozen request")
        receipt = self._registry.require_runtime_receipt(checked.critic_receipt_sha256)
        output = self._registry.require(
            _digest(run["critic_output_sha256"], "critic output"), EvidenceKind.MODEL_OUTPUT
        ).payload()
        wire = _mapping(output["wire"], "critic output wire")
        _keys(wire, {"decision", "reason_category"}, "critic output wire")
        decision = CriticDecision(_text(wire["decision"], "critic decision"))
        reason_category = NarrativeCategory(_text(wire["reason_category"], "critic reason category"))
        reason = _narrative(reason_category, "critic reason category")
        if (
            run["decision"] != decision.value
            or run["reason_category"] != reason_category.value
            or run["reason"] != reason
        ):
            raise PermissionError("critic verdict must derive from its exact runtime output")
        qualification = FrozenProfileQualification.hydrate(
            self._registry.require(checked.profile_sha256, EvidenceKind.PROFILE).payload()
        )
        if qualification.workload_id != checked.workload_id:
            raise PermissionError("critic profile qualification does not bind the workload")
        actual_provider = _text(run["actual_provider"], "actual provider")
        actual_model = _text(run["actual_model_id"], "actual model")
        actual_effort = _text(run["actual_reasoning_effort"], "actual effort")
        actual_profile = _text(run["actual_profile_id"], "actual profile")
        if (actual_provider, actual_model, actual_profile) != (
            qualification.provider,
            qualification.model_id,
            qualification.profile_id,
        ):
            raise PermissionError("critic run does not match its frozen provider/model/profile")
        usage = tuple(
            _integer(run[name], name, minimum=0)
            for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens", "latency_ms")
        )
        reroutes = tuple(_text(item, "reroute") for item in _array(run["reroutes"], "reroutes"))
        if reroutes:
            raise PermissionError("critic run evidence reports a forbidden reroute")
        if (
            receipt.actual_provider != actual_provider
            or receipt.actual_model_id != actual_model
            or receipt.actual_reasoning_effort != actual_effort
            or receipt.input_tokens != usage[0]
            or receipt.output_tokens != usage[1]
            or receipt.reasoning_tokens != usage[2]
            or (receipt.cached_input_tokens or 0) + (receipt.cache_write_input_tokens or 0) != usage[3]
            or receipt.latency_ms != usage[4]
        ):
            raise PermissionError("critic run facts do not exactly derive from its receipt")
        payload: dict[str, JsonValue] = {
            "schema_version": _SCHEMA,
            "request_sha256": checked.content_sha256,
            "candidate_sha256": checked.candidate_sha256,
            "brief_sha256": checked.brief_sha256,
            "run_evidence_sha256": _digest(run_evidence_sha256, "run evidence"),
            "critic_receipt_sha256": checked.critic_receipt_sha256,
            "decision": decision.value,
            "reason": reason,
            "actual_provider": actual_provider,
            "actual_model_id": actual_model,
            "actual_profile_id": actual_profile,
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "reasoning_tokens": usage[2],
            "cache_tokens": usage[3],
            "latency_ms": usage[4],
            "reroutes": reroutes,
        }
        return CriticArtifact(
            _SCHEMA,
            checked.content_sha256,
            checked.candidate_sha256,
            checked.brief_sha256,
            run_evidence_sha256,
            checked.critic_receipt_sha256,
            decision,
            reason,
            actual_provider,
            actual_model,
            actual_profile,
            usage[0],
            usage[1],
            usage[2],
            usage[3],
            usage[4],
            reroutes,
            canonical_sha256(payload),
            self._critic_authority.sign(payload),
        )

    def verify_request(self, request: IndependentCriticRequest) -> IndependentCriticRequest:
        checked = IndependentCriticRequest.hydrate(request.to_dict(), self._critic_authority)
        if self.bind_request(checked.invocation, checked.critic_receipt_sha256) != checked:
            raise PermissionError("critic request does not exactly bind its runtime receipt")
        for digest, kind in (
            (checked.profile_sha256, EvidenceKind.PROFILE),
            (checked.prompt_sha256, EvidenceKind.PROMPT),
            (checked.schema_sha256, EvidenceKind.SCHEMA),
            (checked.toolset_sha256, EvidenceKind.TOOLSET),
            (checked.runtime_sha256, EvidenceKind.RUNTIME),
        ):
            self._registry.require(digest, kind)
        return checked

    def verify_artifact(self, artifact: CriticArtifact) -> CriticArtifact:
        checked = CriticArtifact.hydrate(artifact.to_dict(), self._critic_authority)
        run = self._registry.require(checked.run_evidence_sha256, EvidenceKind.CRITIC_RUN).payload()
        if run.get("critic_receipt_sha256") != checked.critic_receipt_sha256:
            raise PermissionError("critic artifact receipt does not match its run")
        self._registry.require_runtime_receipt(checked.critic_receipt_sha256)
        return checked


@dataclass(frozen=True, slots=True)
class GovernedResearchDecision:
    schema_version: str
    candidate_sha256: str
    original_brief_sha256: str
    critic_sha256: str
    final_action: ResearchAction
    final_reason: str
    next_experiment: NextResearchExperiment
    tradable: bool
    strategy_candidate_created: bool
    content_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.final_action) is not ResearchAction:
            raise ValueError("governed decision schema/action is invalid")
        for value in (self.candidate_sha256, self.original_brief_sha256, self.critic_sha256):
            _digest(value, "governed decision binding")
        _text(self.final_reason, "governed reason")
        if type(self.next_experiment) is not NextResearchExperiment:
            raise TypeError("governed decision requires a signed experiment")
        if self.tradable is not False or self.strategy_candidate_created is not False:
            raise PermissionError("governed decisions are strictly non-trading")
        if (
            self.final_action is not ResearchAction.TEST_NEXT
            and self.next_experiment.readiness is not ExperimentReadiness.NOT_REQUESTED
        ):
            raise PermissionError("non-TEST governed decisions cannot retain a READY experiment")
        if canonical_sha256(self.unsigned_payload()) != self.content_sha256:
            raise ValueError("governed decision digest is invalid")
        _digest(self.signature_sha256, "governed decision signature")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "candidate_sha256": self.candidate_sha256,
            "original_brief_sha256": self.original_brief_sha256,
            "critic_sha256": self.critic_sha256,
            "final_action": self.final_action.value,
            "final_reason": self.final_reason,
            "next_experiment": self.next_experiment.to_dict(),
            "tradable": False,
            "strategy_candidate_created": False,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self.unsigned_payload(),
            "content_sha256": self.content_sha256,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object], authority: PhaseZeroAuthority) -> GovernedResearchDecision:
        _keys(value, set(cls.__dataclass_fields__), "governed research decision")
        decision = cls(
            _text(value["schema_version"], "schema"),
            _text(value["candidate_sha256"], "candidate"),
            _text(value["original_brief_sha256"], "original brief"),
            _text(value["critic_sha256"], "critic"),
            ResearchAction(_text(value["final_action"], "final action")),
            _text(value["final_reason"], "final reason"),
            NextResearchExperiment.hydrate(_mapping(value["next_experiment"], "next experiment"), authority),
            _boolean(value["tradable"], "tradable"),
            _boolean(value["strategy_candidate_created"], "strategy candidate"),
            _text(value["content_sha256"], "content"),
            _text(value["signature_sha256"], "signature"),
        )
        if not authority.verify(decision.unsigned_payload(), decision.signature_sha256):
            raise PermissionError("governed decision signature is invalid")
        return decision


@dataclass(frozen=True, slots=True)
class AgentCriticOutcome:
    agent_run: AgentRunOutcome
    request: IndependentCriticRequest
    critic: CriticArtifact
    governed: GovernedResearchDecision

    @property
    def display_action(self) -> ResearchAction:
        return self.governed.final_action

    @property
    def display_experiment(self) -> NextResearchExperiment:
        return self.governed.next_experiment

    @property
    def brief(self) -> ResearchDecisionBrief:
        return self.agent_run.brief


def verify_agent_critic_outcome(
    candidate: ResearchCandidatePacket,
    outcome: AgentCriticOutcome,
    research_authority: PhaseZeroAuthority,
    critic_authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
) -> tuple[ResearchDecisionBrief, IndependentCriticRequest, CriticArtifact, GovernedResearchDecision]:
    """Verify the complete immutable chain before any evaluator or renderer consumes it."""

    checked_candidate = ResearchCandidatePacket.hydrate(candidate.to_dict(), research_authority, registry)
    agent_run = verify_agent_run_outcome(
        checked_candidate,
        outcome.agent_run,
        research_authority,
        registry,
        outcome.governed.next_experiment.binding,
    )
    brief = agent_run.brief
    request = IndependentCriticRequest.hydrate(outcome.request.to_dict(), critic_authority)
    critic = IndependentCritic(research_authority, critic_authority, registry)
    review = critic.review(request, outcome.critic.run_evidence_sha256)
    if review != outcome.critic:
        raise PermissionError("critic artifact does not exactly derive from frozen CRITIC_RUN evidence")
    governed = GovernedResearchDecision.hydrate(outcome.governed.to_dict(), research_authority)
    brief.verify_for_candidate(checked_candidate)
    if (
        agent_run.candidate_sha256 != checked_candidate.content_sha256
        or brief.producer is not BriefProducer.AGENT
        or brief.candidate_sha256 != checked_candidate.content_sha256
        or request.candidate_sha256 != checked_candidate.content_sha256
        or request.agent_outcome_sha256 != agent_run.content_sha256
        or request.research_run_sha256 != agent_run.research_run_sha256
        or request.brief_sha256 != brief.content_sha256
        or review.candidate_sha256 != checked_candidate.content_sha256
        or review.brief_sha256 != brief.content_sha256
        or review.critic_receipt_sha256 != request.critic_receipt_sha256
        or governed.candidate_sha256 != checked_candidate.content_sha256
        or governed.original_brief_sha256 != brief.content_sha256
        or governed.critic_sha256 != review.content_sha256
    ):
        raise PermissionError("agent-critic outcome bindings do not form one candidate chain")
    _validate_action_authority(checked_candidate.eligibility, brief.action)
    expected_action = _critic_action(checked_candidate.eligibility, review.decision, brief.action)
    if governed.final_action is not expected_action:
        raise PermissionError("governed action is not authorized by candidate eligibility and critic decision")
    expected_readiness = (
        ExperimentReadiness.READY if expected_action is ResearchAction.TEST_NEXT else ExperimentReadiness.NOT_REQUESTED
    )
    if governed.next_experiment.readiness is not expected_readiness:
        raise PermissionError("governed experiment readiness is not congruent with authorized action")
    if (
        governed.next_experiment.candidate_sha256 != checked_candidate.content_sha256
        or governed.next_experiment.evidence != checked_candidate.evidence
    ):
        raise PermissionError("governed experiment is not candidate-bound")
    expected_experiment = build_next_experiment(
        checked_candidate,
        governed.next_experiment.readiness,
        governed.next_experiment.binding,
        research_authority,
        registry,
    )
    if expected_experiment != governed.next_experiment:
        raise PermissionError("governed experiment is not the deterministic bound experiment")
    return brief, request, review, governed


def _issue_governed_outcome(
    *,
    authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
    binding: ExperimentBinding,
    candidate: ResearchCandidatePacket,
    agent_outcome: AgentRunOutcome,
    critic_request: IndependentCriticRequest,
    critic_artifact: CriticArtifact,
    critic: IndependentCritic,
) -> AgentCriticOutcome:
    agent_run = verify_agent_run_outcome(candidate, agent_outcome, authority, registry, binding)
    brief = agent_run.brief
    request = critic.verify_request(critic_request)
    review = critic.verify_artifact(critic_artifact)
    if critic.review(request, review.run_evidence_sha256) != review:
        raise PermissionError("critic artifact is not exactly derived from its frozen CRITIC_RUN evidence")
    if brief.producer is not BriefProducer.AGENT or brief.candidate_sha256 != candidate.content_sha256:
        raise PermissionError("governance requires the original candidate-bound Agent brief")
    if (
        request.candidate_sha256 != candidate.content_sha256
        or request.agent_outcome_sha256 != agent_run.content_sha256
        or request.research_run_sha256 != agent_run.research_run_sha256
        or request.brief_sha256 != brief.content_sha256
        or review.request_sha256 != request.content_sha256
        or review.candidate_sha256 != candidate.content_sha256
        or review.brief_sha256 != brief.content_sha256
        or review.critic_receipt_sha256 != request.critic_receipt_sha256
    ):
        raise PermissionError("critic governance bindings do not match the original Agent brief")
    _validate_action_authority(candidate.eligibility, brief.action)
    final_action = _critic_action(candidate.eligibility, review.decision, brief.action)
    experiment = (
        brief.next_experiment
        if review.decision is CriticDecision.PASS
        else build_next_experiment(candidate, ExperimentReadiness.NOT_REQUESTED, binding, authority, registry)
    )
    reason = f"CRITIC_{review.decision.value}"
    payload: dict[str, JsonValue] = {
        "schema_version": _SCHEMA,
        "candidate_sha256": candidate.content_sha256,
        "original_brief_sha256": brief.content_sha256,
        "critic_sha256": review.content_sha256,
        "final_action": final_action.value,
        "final_reason": reason,
        "next_experiment": experiment.to_dict(),
        "tradable": False,
        "strategy_candidate_created": False,
    }
    governed = GovernedResearchDecision(
        _SCHEMA,
        candidate.content_sha256,
        brief.content_sha256,
        review.content_sha256,
        final_action,
        reason,
        experiment,
        False,
        False,
        canonical_sha256(payload),
        authority.sign(payload),
    )
    return AgentCriticOutcome(agent_run, request, review, governed)


@dataclass(frozen=True, slots=True)
class PhaseZeroEvaluation:
    schema_version: str
    accepted: bool
    critical_failures: tuple[str, ...]
    artifact_sha256s: tuple[str, ...]
    evaluation_run_sha256: str
    fault_roster_sha256: str
    fault_case_sha256s: tuple[str, ...]
    fault_input_sha256s: tuple[str, ...]
    total_tokens: int
    latency_ms: int
    injected_fault_count: int
    recalled_fault_count: int
    replay_semantic_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA or type(self.accepted) is not bool:
            raise ValueError("Phase-0 evaluation schema/status is invalid")
        if self.critical_failures != tuple(sorted(set(self.critical_failures))):
            raise ValueError("Phase-0 failures must be canonical")
        if self.accepted == bool(self.critical_failures):
            raise ValueError("accepted evaluation cannot contain critical failures")
        if len(self.artifact_sha256s) != 12:
            raise ValueError("Phase-0 evaluation requires all four arms, governed artifacts, and three receipts")
        for value in self.artifact_sha256s:
            _digest(value, "evaluated artifact")
        _digest(self.evaluation_run_sha256, "evaluation run")
        _digest(self.fault_roster_sha256, "fault roster")
        for value in (*self.fault_case_sha256s, *self.fault_input_sha256s):
            _digest(value, "fault evaluation artifact")
        _integer(self.total_tokens, "total tokens", minimum=0)
        _integer(self.latency_ms, "latency", minimum=0)
        _integer(self.injected_fault_count, "injected fault count", minimum=0)
        _integer(self.recalled_fault_count, "recalled fault count", minimum=0)
        if self.recalled_fault_count > self.injected_fault_count:
            raise ValueError("fault recall cannot exceed injected faults")
        _digest(self.replay_semantic_sha256, "replay semantic digest")
        if canonical_sha256(self.payload()) != self.content_sha256:
            raise ValueError("Phase-0 evaluation digest is invalid")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "accepted": self.accepted,
            "critical_failures": self.critical_failures,
            "artifact_sha256s": self.artifact_sha256s,
            "evaluation_run_sha256": self.evaluation_run_sha256,
            "fault_roster_sha256": self.fault_roster_sha256,
            "fault_case_sha256s": self.fault_case_sha256s,
            "fault_input_sha256s": self.fault_input_sha256s,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "injected_fault_count": self.injected_fault_count,
            "recalled_fault_count": self.recalled_fault_count,
            "replay_semantic_sha256": self.replay_semantic_sha256,
        }


def _replay_fault_case(
    original: FaultInput, mutated: FaultInput, registry: OwnerEvidenceRegistry
) -> FaultFailureCode | None:
    """Replay one closed mutation, accepting exactly one category-specific delta."""

    if original.category is not mutated.category:
        return FaultFailureCode.CASE_SCHEMA_MISMATCH
    category = original.category
    allowed_change = {
        FaultCategory.FUTURE_LEAK: "source_purpose",
        FaultCategory.FORGED_SOURCE: "source_ref",
        FaultCategory.UNAUTHORIZED_ACTION: "action",
        FaultCategory.TRADING_REQUEST: "narrative",
    }[category]
    original_payload, mutated_payload = original.to_dict(), mutated.to_dict()
    changed = {key for key in original_payload if original_payload[key] != mutated_payload[key]}
    if changed != {allowed_change}:
        return FaultFailureCode.CASE_SCHEMA_MISMATCH
    try:
        if category in {FaultCategory.FUTURE_LEAK, FaultCategory.FORGED_SOURCE}:
            if original.source_purpose != SourcePurpose.PIT_RESEARCH_INPUT.value:
                return FaultFailureCode.CASE_SCHEMA_MISMATCH
            registry.verify_source(original.source_ref)
        elif category is FaultCategory.UNAUTHORIZED_ACTION:
            _validate_action_authority(original.eligibility, original.action)
        else:
            _narrative(NarrativeCategory(original.narrative), "fault original narrative")
    except TypeError, ValueError, PermissionError:
        return FaultFailureCode.CASE_SCHEMA_MISMATCH
    if category is FaultCategory.FUTURE_LEAK:
        return (
            FaultFailureCode.SOURCE_SCHEMA_REJECTED
            if mutated.source_purpose == "futureLabel"
            else FaultFailureCode.CASE_SCHEMA_MISMATCH
        )
    if category is FaultCategory.FORGED_SOURCE:
        try:
            registry.verify_source(mutated.source_ref)
        except PermissionError:
            return FaultFailureCode.SOURCE_REFERENCE_REJECTED
        return FaultFailureCode.CASE_SCHEMA_MISMATCH
    if category is FaultCategory.UNAUTHORIZED_ACTION:
        try:
            _validate_action_authority(mutated.eligibility, mutated.action)
        except PermissionError:
            return FaultFailureCode.ACTION_AUTHORITY_REJECTED
        return FaultFailureCode.CASE_SCHEMA_MISMATCH
    try:
        _narrative(NarrativeCategory(mutated.narrative), "fault mutated narrative")
    except ValueError, PermissionError:
        return FaultFailureCode.NARRATIVE_REJECTED
    return FaultFailureCode.CASE_SCHEMA_MISMATCH


class PhaseZeroEvaluator:
    """Verifies one complete four-arm episode without reading any future label."""

    def __init__(
        self,
        research_authority: PhaseZeroAuthority,
        critic_authority: PhaseZeroAuthority,
        registry: OwnerEvidenceRegistry,
        experiment_binding: ExperimentBinding,
    ) -> None:
        self._research_authority = research_authority
        self._critic_authority = critic_authority
        self._registry = registry
        self._binding = experiment_binding

    def _brief_failures(
        self,
        candidate: ResearchCandidatePacket,
        brief: ResearchDecisionBrief,
        producer: BriefProducer,
    ) -> set[str]:
        failures: set[str] = set()
        try:
            checked = ResearchDecisionBrief.hydrate(brief.to_dict(), self._research_authority)
        except TypeError, ValueError, PermissionError:
            return {f"{producer.value}_HYDRATION_FAILED"}
        if checked.producer is not producer:
            failures.add(f"{producer.value}_PRODUCER_MISMATCH")
        if checked.candidate_sha256 != candidate.content_sha256:
            failures.add(f"{producer.value}_CANDIDATE_MISMATCH")
        try:
            checked.verify_for_candidate(candidate)
        except PermissionError:
            failures.add(f"{producer.value}_UNKNOWNS_INCOMPLETE")
        if checked.deterministic_facts_json != canonical_json_text(candidate.unsigned_payload()):
            failures.add(f"{producer.value}_FACTS_INCOMPLETE")
        if tuple(value.to_dict() for value in checked.source_refs) != tuple(
            value.to_dict() for value in candidate.sources
        ):
            failures.add(f"{producer.value}_SOURCE_ROSTER_MISMATCH")
        if checked.warnings != candidate.roll_warnings + candidate.warnings:
            failures.add(f"{producer.value}_WARNINGS_INCOMPLETE")
        try:
            _validate_action_authority(
                candidate.eligibility,
                checked.action,
                deterministic_failure=producer in {BriefProducer.DETERMINISTIC_FAILURE, BriefProducer.ALWAYS_DEFER},
            )
        except PermissionError:
            failures.add(f"{producer.value}_ACTION_AUTHORITY_MISMATCH")
        for reference in checked.source_refs:
            try:
                self._registry.verify_source(reference)
            except TypeError, ValueError, PermissionError:
                failures.add(f"{producer.value}_GROUNDING_INVALID")
        experiment = checked.next_experiment
        expected_ready = (
            ExperimentReadiness.READY
            if checked.action is ResearchAction.TEST_NEXT
            else ExperimentReadiness.NOT_REQUESTED
        )
        if (
            experiment.candidate_sha256 != candidate.content_sha256
            or experiment.evidence != candidate.evidence
            or experiment.binding != self._binding
        ):
            failures.add(f"{producer.value}_EXPERIMENT_BINDING_MISMATCH")
        if experiment.readiness is not expected_ready:
            failures.add(f"{producer.value}_ACTION_READINESS_MISMATCH")
        if expected_ready is ExperimentReadiness.READY:
            try:
                request = experiment.instantiate_request(self._research_authority)
                if (
                    request.candidate_sha256 != candidate.content_sha256
                    or request.evidence != candidate.evidence
                    or request.binding != self._binding
                ):
                    failures.add(f"{producer.value}_REQUEST_BINDING_MISMATCH")
            except TypeError, ValueError, PermissionError:
                failures.add(f"{producer.value}_REQUEST_HYDRATION_FAILED")
        try:
            build_next_experiment(
                candidate, experiment.readiness, experiment.binding, self._research_authority, self._registry
            )
        except TypeError, ValueError, PermissionError:
            failures.add(f"{producer.value}_EXPERIMENT_REVALIDATION_FAILED")
        return failures

    def evaluate(
        self,
        *,
        candidate: ResearchCandidatePacket,
        deterministic_template: ResearchDecisionBrief,
        agent_without_critic: AgentRunOutcome,
        agent_with_critic: AgentCriticOutcome,
        always_reject: ResearchDecisionBrief,
        always_defer: ResearchDecisionBrief,
        critic_request: IndependentCriticRequest,
        research_run_sha256: str,
        evaluation_run_sha256: str,
    ) -> PhaseZeroEvaluation:
        failures: set[str] = set()
        try:
            checked_candidate = ResearchCandidatePacket.hydrate(
                candidate.to_dict(), self._research_authority, self._registry
            )
        except TypeError, ValueError, PermissionError:
            checked_candidate = candidate
            failures.add("CANDIDATE_HYDRATION_FAILED")
        try:
            verified_agent_run = verify_agent_run_outcome(
                checked_candidate,
                agent_without_critic,
                self._research_authority,
                self._registry,
                self._binding,
            )
        except TypeError, ValueError, PermissionError:
            verified_agent_run = agent_without_critic
            failures.add("AGENT_RUN_OUTCOME_HYDRATION_FAILED")
        for brief, producer in (
            (deterministic_template, BriefProducer.DETERMINISTIC_TEMPLATE),
            (verified_agent_run.brief, BriefProducer.AGENT),
            (always_reject, BriefProducer.ALWAYS_REJECT),
            (always_defer, BriefProducer.ALWAYS_DEFER),
        ):
            failures.update(self._brief_failures(checked_candidate, brief, producer))
        if always_reject.action is not ResearchAction.REJECT_AS_UNSUPPORTED:
            failures.add("ALWAYS_REJECT_ACTION_MISMATCH")
        if always_defer.action is not ResearchAction.DEFER:
            failures.add("ALWAYS_DEFER_ACTION_MISMATCH")
        try:
            brief, request, review, governed = verify_agent_critic_outcome(
                checked_candidate,
                agent_with_critic,
                self._research_authority,
                self._critic_authority,
                self._registry,
            )
            if request != IndependentCriticRequest.hydrate(critic_request.to_dict(), self._critic_authority):
                failures.add("CRITIC_REQUEST_ARGUMENT_MISMATCH")
        except TypeError, ValueError, PermissionError:
            failures.add("CRITIC_GOVERNANCE_HYDRATION_FAILED")
            request, review, governed = critic_request, agent_with_critic.critic, agent_with_critic.governed
        agent_brief = verified_agent_run.brief
        if research_run_sha256 != verified_agent_run.research_run_sha256:
            failures.add("RESEARCH_RUN_ARGUMENT_MISMATCH")
        if agent_with_critic.brief.content_sha256 != agent_brief.content_sha256:
            failures.add("CRITIC_ORIGINAL_BRIEF_MISMATCH")
        try:
            research_run = self._registry.require(research_run_sha256, EvidenceKind.RESEARCH_RUN).payload()
            _keys(
                research_run,
                {
                    "candidate_sha256",
                    "proposal_sha256",
                    "agent_brief_sha256",
                    "invocation_authorization_sha256",
                    "invocation_id",
                    "synthesis_receipt_sha256",
                    "experiment_design_receipt_sha256",
                    "synthesis_output_sha256",
                    "experiment_design_output_sha256",
                    "synthesis_owner_binding",
                    "experiment_design_owner_binding",
                    "experiment_binding_sha256",
                    "response_sha256",
                    "response_id",
                    "workload_id",
                    "profile_sha256",
                    "prompt_sha256",
                    "schema_sha256",
                    "toolset_sha256",
                    "runtime_sha256",
                    "actual_provider",
                    "actual_model_id",
                    "actual_reasoning_effort",
                    "actual_profile_id",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cache_tokens",
                    "latency_ms",
                    "reroutes",
                },
                "research run evidence",
            )
            if (
                research_run["candidate_sha256"] != checked_candidate.content_sha256
                or research_run["agent_brief_sha256"] != agent_brief.content_sha256
                or research_run["workload_id"] != "research.hypothesis_synthesis"
                or research_run["profile_sha256"] != self._binding.profile_sha256
                or research_run["prompt_sha256"] != self._binding.prompt_sha256
                or research_run["schema_sha256"] != self._binding.schema_sha256
                or research_run["toolset_sha256"] != checked_candidate.evidence.toolset_sha256
                or research_run["runtime_sha256"] != checked_candidate.evidence.runtime_sha256
                or _array(research_run["reroutes"], "research reroutes")
            ):
                failures.add("RESEARCH_RUN_BINDING_MISMATCH")
            qualification = FrozenProfileQualification.hydrate(
                self._registry.require(self._binding.profile_sha256, EvidenceKind.PROFILE).payload()
            )
            if (
                research_run["actual_provider"],
                research_run["actual_model_id"],
                research_run["actual_profile_id"],
            ) != (
                qualification.provider,
                qualification.model_id,
                qualification.profile_id,
            ):
                failures.add("RESEARCH_RUN_PROFILE_MISMATCH")
            for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cache_tokens", "latency_ms"):
                _integer(research_run[name], name, minimum=0)
        except TypeError, ValueError, PermissionError:
            failures.add("RESEARCH_RUN_HYDRATION_FAILED")
        if (
            request.candidate_sha256 != checked_candidate.content_sha256
            or request.agent_outcome_sha256 != verified_agent_run.content_sha256
            or request.research_run_sha256 != verified_agent_run.research_run_sha256
            or request.brief_sha256 != agent_brief.content_sha256
            or review.request_sha256 != request.content_sha256
            or review.candidate_sha256 != checked_candidate.content_sha256
            or review.brief_sha256 != agent_brief.content_sha256
            or governed.candidate_sha256 != checked_candidate.content_sha256
            or governed.original_brief_sha256 != agent_brief.content_sha256
            or governed.critic_sha256 != review.content_sha256
        ):
            failures.add("CRITIC_GOVERNANCE_BINDING_MISMATCH")
        expected_action = _critic_action(checked_candidate.eligibility, review.decision, agent_brief.action)
        if governed.final_action is not expected_action:
            failures.add("CRITIC_ACTION_MISMATCH")
        if (
            review.decision is not CriticDecision.PASS
            and governed.next_experiment.readiness is not ExperimentReadiness.NOT_REQUESTED
        ):
            failures.add("CRITIC_NON_PASS_RETAINED_READY_EXPERIMENT")
        if (
            governed.next_experiment.candidate_sha256 != checked_candidate.content_sha256
            or governed.next_experiment.evidence != checked_candidate.evidence
            or governed.next_experiment.binding != self._binding
        ):
            failures.add("GOVERNED_EXPERIMENT_BINDING_MISMATCH")

        artifacts = (
            checked_candidate.content_sha256,
            deterministic_template.content_sha256,
            verified_agent_run.content_sha256,
            verified_agent_run.research_run_sha256,
            verified_agent_run.synthesis_receipt_sha256,
            verified_agent_run.experiment_design_receipt_sha256,
            request.content_sha256,
            review.content_sha256,
            review.critic_receipt_sha256,
            governed.content_sha256,
            always_reject.content_sha256,
            always_defer.content_sha256,
        )
        run = self._registry.require(evaluation_run_sha256, EvidenceKind.EVALUATION_RUN).payload()
        _keys(
            run,
            {
                "artifact_sha256s",
                "candidate_sha256",
                "proposal_sha256",
                "agent_outcome_sha256",
                "critic_request_sha256",
                "runtime_config_sha256s",
                "runtime_asset_refs",
                "runtime_owner_bindings",
                "workload_ids",
                "fault_roster_sha256",
                "fault_case_sha256s",
                "fault_input_sha256s",
                "replay_semantic_sha256",
                "scenario_kind",
            },
            "evaluation run evidence",
        )
        recorded_artifacts = tuple(
            _text(item, "recorded artifact") for item in _array(run["artifact_sha256s"], "recorded artifacts")
        )
        if recorded_artifacts != artifacts:
            failures.add("EVALUATION_RUN_BINDING_MISMATCH")
        receipts = (
            self._registry.require_runtime_receipt(verified_agent_run.synthesis_receipt_sha256),
            self._registry.require_runtime_receipt(verified_agent_run.experiment_design_receipt_sha256),
            self._registry.require_runtime_receipt(review.critic_receipt_sha256),
        )
        recorded_configs = tuple(
            _digest(item, "runtime config") for item in _array(run["runtime_config_sha256s"], "runtime configs")
        )
        recorded_workloads = tuple(
            _text(item, "runtime workload") for item in _array(run["workload_ids"], "runtime workloads")
        )
        recorded_asset_refs = tuple(
            RuntimeAssetRef.hydrate(_mapping(item, "runtime asset ref"))
            for item in _array(run["runtime_asset_refs"], "runtime asset refs")
        )
        recorded_owner_bindings = tuple(
            RuntimeOwnerBinding.hydrate(_mapping(item, "runtime owner binding"))
            for item in _array(run["runtime_owner_bindings"], "runtime owner bindings")
        )
        research_run = self._registry.require(
            verified_agent_run.research_run_sha256, EvidenceKind.RESEARCH_RUN
        ).payload()
        critic_run = self._registry.require(review.run_evidence_sha256, EvidenceKind.CRITIC_RUN).payload()
        expected_owner_bindings = (
            RuntimeOwnerBinding.hydrate(_mapping(research_run["synthesis_owner_binding"], "synthesis owner binding")),
            RuntimeOwnerBinding.hydrate(
                _mapping(research_run["experiment_design_owner_binding"], "experiment owner binding")
            ),
            RuntimeOwnerBinding.hydrate(_mapping(critic_run["critic_owner_binding"], "critic owner binding")),
        )
        if (
            run["candidate_sha256"] != checked_candidate.content_sha256
            or run["proposal_sha256"] != verified_agent_run.proposal_sha256
            or run["agent_outcome_sha256"] != verified_agent_run.content_sha256
            or run["critic_request_sha256"] != request.content_sha256
            or recorded_configs != tuple(receipt.config_sha256 for receipt in receipts)
            or recorded_workloads != tuple(receipt.workload_id for receipt in receipts)
            or recorded_asset_refs != tuple(receipt.asset_ref for receipt in receipts)
            or recorded_owner_bindings != expected_owner_bindings
        ):
            failures.add("EVALUATION_RUN_LINEAGE_MISMATCH")
        if any(
            receipt.status != "COMPLETED" or receipt.total_tokens is None or receipt.latency_ms is None
            for receipt in receipts
        ):
            failures.add("RUNTIME_RECEIPT_USAGE_INCOMPLETE")
            total_tokens = latency_ms = 0
        else:
            total_tokens = sum(cast(int, receipt.total_tokens) for receipt in receipts)
            latency_ms = sum(cast(int, receipt.latency_ms) for receipt in receipts)
        if total_tokens > 20_000:
            failures.add("TOKEN_BUDGET_EXCEEDED")
        if latency_ms > 35_000:
            failures.add("LATENCY_BUDGET_EXCEEDED")
        scenario = EvaluationScenarioKind(_text(run["scenario_kind"], "evaluation scenario"))
        fault_case_sha256s = tuple(
            _digest(item, "fault case") for item in _array(run["fault_case_sha256s"], "fault case roster")
        )
        fault_input_sha256s = tuple(
            _digest(item, "fault input") for item in _array(run["fault_input_sha256s"], "fault input roster")
        )
        fault_roster_sha256 = _digest(run["fault_roster_sha256"], "fault roster")
        try:
            roster = FrozenFaultRoster.hydrate(
                self._registry.require(fault_roster_sha256, EvidenceKind.FAULT_ROSTER).payload(),
                self._research_authority,
            )
            if roster.candidate_sha256 != checked_candidate.content_sha256:
                raise PermissionError("fault roster candidate binding is invalid")
            cases = tuple(
                FaultCase.hydrate(self._registry.require(digest, EvidenceKind.FAULT_CASE).payload())
                for digest in fault_case_sha256s
            )
            inputs = tuple(
                FaultInput.hydrate(self._registry.require(digest, EvidenceKind.FAULT_INPUT).payload())
                for digest in fault_input_sha256s
            )
        except TypeError, ValueError, PermissionError:
            roster, cases, inputs = None, (), ()
            failures.add("FAULT_ARTIFACT_HYDRATION_FAILED")
        if len(set(fault_case_sha256s)) != len(fault_case_sha256s) or len({case.category for case in cases}) != len(
            cases
        ):
            failures.add("FAULT_CASE_ROSTER_INVALID")
        if any(case.fault_roster_sha256 != fault_roster_sha256 for case in cases):
            failures.add("FAULT_CASE_ROSTER_BINDING_INVALID")
        if len(set(fault_input_sha256s)) != len(fault_input_sha256s):
            failures.add("FAULT_INPUT_ROSTER_INVALID")
        input_by_digest = {digest: value for digest, value in zip(fault_input_sha256s, inputs, strict=True)}
        recalled_fault_count = 0
        for case in cases:
            original = input_by_digest.get(case.original_input_sha256)
            mutated = input_by_digest.get(case.mutated_input_sha256)
            if (
                original is None
                or mutated is None
                or original.category is not case.category
                or mutated.category is not case.category
            ):
                failures.add("FAULT_CASE_INPUT_BINDING_INVALID")
                continue
            actual = _replay_fault_case(original, mutated, self._registry)
            if actual is not case.expected_failure:
                failures.add("FAULT_REPLAY_RECALL_FAILED")
            else:
                recalled_fault_count += 1
        if scenario is EvaluationScenarioKind.CLEAN and cases:
            failures.add("CLEAN_SCENARIO_HAS_FAULTS")
        if scenario is EvaluationScenarioKind.FAULT_INJECTION and {case.category for case in cases} != set(
            FaultCategory
        ):
            failures.add("FAULT_RECALL_THRESHOLD_FAILED")
        replay_payload: dict[str, JsonValue] = {
            "candidate_sha256": checked_candidate.content_sha256,
            "eligibility": checked_candidate.eligibility.value,
            "selected_family": checked_candidate.selected_family.value,
            "agent_action": agent_brief.action.value,
            "counter_claim": agent_brief.strongest_counter_claim.statement,
            "governed_action": governed.final_action.value,
            "experiment_readiness": governed.next_experiment.readiness.value,
        }
        replay_digest = canonical_sha256(replay_payload)
        if _digest(run["replay_semantic_sha256"], "recorded replay semantic") != replay_digest:
            failures.add("REPLAY_SEMANTIC_MISMATCH")
        failure_tuple = tuple(sorted(failures))
        payload: dict[str, JsonValue] = {
            "schema_version": _SCHEMA,
            "accepted": not failure_tuple,
            "critical_failures": failure_tuple,
            "artifact_sha256s": artifacts,
            "evaluation_run_sha256": evaluation_run_sha256,
            "fault_roster_sha256": fault_roster_sha256,
            "fault_case_sha256s": fault_case_sha256s,
            "fault_input_sha256s": fault_input_sha256s,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "injected_fault_count": len(cases),
            "recalled_fault_count": recalled_fault_count,
            "replay_semantic_sha256": replay_digest,
        }
        return PhaseZeroEvaluation(
            _SCHEMA,
            not failure_tuple,
            failure_tuple,
            artifacts,
            evaluation_run_sha256,
            fault_roster_sha256,
            fault_case_sha256s,
            fault_input_sha256s,
            total_tokens,
            latency_ms,
            len(cases),
            recalled_fault_count,
            replay_digest,
            canonical_sha256(payload),
        )


def _experiment_projection(experiment: NextResearchExperiment) -> tuple[str, ...]:
    return (
        f"研究问题：{experiment.research_question}",
        f"唯一变化：{experiment.primary_change}",
        f"窗口：{experiment.binding.window_start} 至 {experiment.binding.window_end}",
        f"切分：训练至 {experiment.binding.train_end}，验证至 {experiment.binding.validation_end}，测试至 {experiment.binding.test_end}",
        f"隔离：{experiment.binding.embargo_bars} bars",
        f"基线/对照：{experiment.binding.baseline} / {experiment.binding.control}",
        f"主指标：{experiment.binding.primary_metric}",
        f"停止条件：{experiment.binding.stop_rule}",
        f"失败解释：{experiment.binding.failure_disposition}",
        f"数据集：{experiment.evidence.dataset_sha256}",
        f"研究 Profile：{experiment.binding.profile_sha256}",
        f"Prompt：{experiment.binding.prompt_sha256}",
        f"Schema：{experiment.binding.schema_sha256}",
        f"Toolset：{experiment.evidence.toolset_sha256}",
        f"Runtime：{experiment.evidence.runtime_sha256}",
        f"成本假设：{experiment.binding.cost_sha256}",
        f"复现：{experiment.binding.reproduction_sha256}",
        f"偏差检查：{', '.join(experiment.binding.bias_checks)}",
    )


def render_chinese_report(
    candidate: ResearchCandidatePacket,
    outcome: AgentCriticOutcome,
    research_authority: PhaseZeroAuthority,
    critic_authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
) -> str:
    """Render only the signed governed outcome; the original READY artifact is never authoritative here."""

    checked_candidate = ResearchCandidatePacket.hydrate(candidate.to_dict(), research_authority, registry)
    brief, _request, critic, governed = verify_agent_critic_outcome(
        checked_candidate, outcome, research_authority, critic_authority, registry
    )
    for reference in brief.source_refs:
        registry.verify_source(reference)
    lines = [
        "研究简报（已经独立复核）",
        f"研究处置：{governed.final_action.value}",
        f"候选资格：{checked_candidate.eligibility.value}",
        f"候选家族：{checked_candidate.selected_family.value}",
        f"最强竞争家族：{checked_candidate.strongest_competing_family.value}",
        f"现在为什么：{brief.why_now}",
        "支持证据：",
    ]
    lines.extend(f"- {claim.statement}" for claim in brief.supporting_claims)
    lines.extend(("最强反证：", f"- {brief.strongest_counter_claim.statement}", "未知与证据缺口："))
    lines.extend(f"- {value}" for value in brief.unknowns)
    lines.append("确定性筛选事实：")
    lines.extend(
        (
            f"- {screen.family.value}：方向 {screen.cutoff_direction}，样本 {screen.signal_count}，"
            f"准确率 {screen.signal_accuracy}，净变化 {screen.net_return}，压力后净变化 {screen.stressed_net_return}，"
            f"正向折叠占比 {screen.positive_fold_ratio}"
        )
        for screen in checked_candidate.screens
    )
    lines.append(f"确定性理由：{', '.join(checked_candidate.reason_codes)}")
    lines.append(
        f"数据范围：{checked_candidate.available_data_range[0]} 至 {checked_candidate.available_data_range[1]}"
    )
    lines.append(f"连续序列成分：{checked_candidate.component_id}")
    lines.extend(
        (
            f"合约：{checked_candidate.instrument_id}",
            f"截至：{checked_candidate.as_of}",
            f"市场截点：{checked_candidate.market_cutoff}",
            f"采集时间：{checked_candidate.acquired_at}",
        )
    )
    lines.append("警告：")
    lines.extend(f"- {value}" for value in brief.warnings)
    lines.append("证据引用：")
    lines.extend(
        f"- {reference.label}：{reference.artifact_sha256} {reference.json_pointer}" for reference in brief.source_refs
    )
    lines.extend(
        (
            f"独立复核：{critic.decision.value} — {critic.reason}",
            f"下一实验：{governed.next_experiment.readiness.value}",
        )
    )
    if governed.next_experiment.readiness is ExperimentReadiness.READY:
        lines.extend(_experiment_projection(governed.next_experiment))
    lines.append("本简报仅用于研究与模拟，不用于交易，不创建策略候选，也不产生订单、成交、持仓或账本变更。")
    return "\n".join(lines)


def render_deterministic_template_chinese_report(
    candidate: ResearchCandidatePacket,
    template: ResearchDecisionBrief,
    authority: PhaseZeroAuthority,
    registry: OwnerEvidenceRegistry,
) -> str:
    """Render the fully verified deterministic-template arm for the Phase-0 A/B view."""

    checked = ResearchCandidatePacket.hydrate(candidate.to_dict(), authority, registry)
    brief = ResearchDecisionBrief.hydrate(template.to_dict(), authority)
    if brief.producer is not BriefProducer.DETERMINISTIC_TEMPLATE or brief.candidate_sha256 != checked.content_sha256:
        raise PermissionError("template report requires the verified deterministic-template arm")
    _validate_action_authority(checked.eligibility, brief.action)
    for reference in brief.source_refs:
        registry.verify_source(reference)
    lines = [
        "确定性模板研究简报",
        f"研究处置：{brief.action.value}",
        f"候选资格：{checked.eligibility.value}",
        f"候选家族：{checked.selected_family.value}",
        f"最强竞争家族：{checked.strongest_competing_family.value}",
        f"确定性理由：{', '.join(checked.reason_codes)}",
        f"数据范围：{checked.available_data_range[0]} 至 {checked.available_data_range[1]}",
        f"合约：{checked.instrument_id}",
        f"截至：{checked.as_of}",
        f"市场截点：{checked.market_cutoff}",
        f"采集时间：{checked.acquired_at}",
        f"连续序列成分：{checked.component_id}",
        f"下一实验：{brief.next_experiment.readiness.value}",
        "未知与证据缺口：",
    ]
    lines.extend(f"- {value}" for value in brief.unknowns)
    lines.append("警告：")
    lines.extend(f"- {value}" for value in brief.warnings)
    lines.extend(
        f"- {screen.family.value}：方向 {screen.cutoff_direction}，样本 {screen.signal_count}"
        for screen in checked.screens
    )
    lines.extend(f"- {reference.artifact_sha256} {reference.json_pointer}" for reference in brief.source_refs)
    if brief.next_experiment.readiness is ExperimentReadiness.READY:
        lines.extend(_experiment_projection(brief.next_experiment))
    lines.append("本简报仅用于研究与模拟，不用于交易，也不创建策略候选。")
    return "\n".join(lines)


__all__ = [
    "AgentCriticOutcome",
    "AgentRunOutcome",
    "AlwaysDispositionBaseline",
    "BriefProducer",
    "CandidateEvidenceBundle",
    "CriticArtifact",
    "CriticDecision",
    "DeterministicFailureCode",
    "DeterministicTemplateBaseline",
    "EvidenceKind",
    "EvaluationScenarioKind",
    "FaultCategory",
    "FaultCase",
    "FaultFailureCode",
    "FaultInput",
    "FrozenFaultRoster",
    "ExperimentBinding",
    "ExperimentReadiness",
    "GovernedResearchDecision",
    "GroundedTextClaim",
    "FrozenProfileQualification",
    "IndependentCritic",
    "IndependentCriticInvocation",
    "IndependentCriticRequest",
    "NextResearchExperiment",
    "NarrativeCategory",
    "OwnerEvidenceArtifact",
    "OwnerEvidenceIssuer",
    "OwnerEvidenceRegistry",
    "PhaseZeroAuthority",
    "PhaseZeroEvaluation",
    "PhaseZeroEvaluator",
    "PhaseZeroExperimentRequest",
    "ProposalIntent",
    "ResearchAction",
    "ResearchCandidateFactory",
    "ResearchCandidatePacket",
    "ResearchDecisionBrief",
    "ResearchEligibility",
    "ResearchInvocationAuthorization",
    "ResearchProposal",
    "ResearchRunner",
    "RuntimeInputKind",
    "RuntimeInputRef",
    "RuntimeReceiptPayload",
    "RuntimeReceiptRef",
    "SourceReference",
    "SourceManifest",
    "SourceRecord",
    "SourcePurpose",
    "build_next_experiment",
    "render_chinese_report",
    "render_deterministic_template_chinese_report",
    "verify_agent_critic_outcome",
]
