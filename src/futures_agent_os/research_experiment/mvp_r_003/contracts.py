"""Versioned, synchronous, non-trading contracts for the MVP-R-003 discovery loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from collections.abc import Iterable
from typing import ClassVar, Mapping, Self, cast

from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


def _digest(value: str) -> str:
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("content digest requires 64 lowercase hexadecimal characters")
    return value


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} requires non-empty text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} requires a positive integer")
    return value


def _bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} requires a boolean")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise ValueError(f"{field} requires a sequence")
    return tuple(cast("Iterable[object]", value))


def _strings(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    output = tuple(_text(item, field) for item in _sequence(value, field))
    if not allow_empty and not output:
        raise ValueError(f"{field} cannot be empty")
    if len(set(output)) != len(output):
        raise ValueError(f"{field} cannot contain duplicates")
    return output


def _pairs(value: object, field: str) -> tuple[tuple[str, str], ...]:
    output: list[tuple[str, str]] = []
    for item in _sequence(value, field):
        pair = _sequence(item, field)
        if len(pair) != 2:
            raise ValueError(f"{field} entries require key and value")
        output.append((_text(pair[0], field), _text(pair[1], field)))
    if len({key for key, _ in output}) != len(output):
        raise ValueError(f"{field} keys must be unique")
    return tuple(output)


def _time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} requires an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} requires a timezone")
    return parsed.astimezone(UTC)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{field} requires an object")
    return cast("Mapping[str, object]", value)


def _exact_keys(value: Mapping[str, object], required: set[str], field: str) -> None:
    if set(value) != required:
        raise ValueError(f"{field} fields do not match schema")


class _Contract:
    schema_version: ClassVar[str]

    def payload(self) -> dict[str, JsonValue]:
        raise NotImplementedError

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            **self.payload(),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def _verify_hash(cls, value: Mapping[str, object], instance: Self) -> Self:
        if _text(value["schema_version"], "schema_version") != cls.schema_version:
            raise ValueError("unsupported schema version")
        if _digest(_text(value["content_sha256"], "content_sha256")) != instance.content_sha256:
            raise ValueError("contract content hash mismatch")
        return instance


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: str
    uri: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text(self.kind, "artifact kind")
        _text(self.uri, "artifact uri")
        _digest(self.content_sha256)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "uri": self.uri, "content_sha256": self.content_sha256}

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ArtifactRef:
        _exact_keys(value, {"kind", "uri", "content_sha256"}, "artifact ref")
        return cls(
            _text(value["kind"], "artifact kind"),
            _text(value["uri"], "artifact uri"),
            _text(value["content_sha256"], "artifact digest"),
        )


class SignalOperator(StrEnum):
    PRIOR_CLOSE_RETURN_THRESHOLD = "PRIOR_CLOSE_RETURN_THRESHOLD"
    VOLUME_CONFIRMATION = "VOLUME_CONFIRMATION"


class HypothesisFamily(StrEnum):
    MOMENTUM_CONTINUATION = "MOMENTUM_CONTINUATION"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    FALSE_BREAKOUT_REVERSAL = "FALSE_BREAKOUT_REVERSAL"
    PARTICIPATION_CONFIRMED_TREND = "PARTICIPATION_CONFIRMED_TREND"
    VOLATILITY_COMPRESSION_BREAKOUT = "VOLATILITY_COMPRESSION_BREAKOUT"


class ValidationStatus(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    UNSUPPORTED = "UNSUPPORTED"
    DEFER = "DEFER"


class CriticDecision(StrEnum):
    SELECT = "SELECT"
    REJECT = "REJECT"
    DEFER = "DEFER"


class FinalVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    MODIFY = "MODIFY"
    NEED_MORE_DATA = "NEED_MORE_DATA"


@dataclass(frozen=True, slots=True)
class ResearchEpisodeInput(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.research-episode-input.v1"

    episode_id: str
    instrument: str
    as_of: str
    market_cutoff: str
    acquired_at: str
    dataset_ref: ArtifactRef
    market_snapshot_ref: ArtifactRef
    feature_ref: ArtifactRef
    rule_ref: ArtifactRef
    cost_ref: ArtifactRef
    toolset_ref: ArtifactRef
    signal_operators: tuple[SignalOperator, ...]
    allowed_parameter_values: tuple[tuple[str, tuple[str, ...]], ...]
    market_state: str
    warnings: tuple[str, ...]
    unknowns: tuple[str, ...]
    evidence_refs: tuple[ArtifactRef, ...]
    tradable: bool = False
    future_result_present: bool = False

    def __post_init__(self) -> None:
        _text(self.episode_id, "episode id")
        _text(self.instrument, "instrument")
        as_of = _time(self.as_of, "as_of")
        cutoff = _time(self.market_cutoff, "market_cutoff")
        acquired = _time(self.acquired_at, "acquired_at")
        if cutoff > as_of or as_of > acquired:
            raise ValueError("episode requires market_cutoff <= as_of <= acquired_at")
        refs = (
            self.dataset_ref,
            self.market_snapshot_ref,
            self.feature_ref,
            self.rule_ref,
            self.cost_ref,
            self.toolset_ref,
            *self.evidence_refs,
        )
        if any(type(item) is not ArtifactRef for item in refs):
            raise TypeError("episode refs must be exact ArtifactRef values")
        if not self.signal_operators or any(type(item) is not SignalOperator for item in self.signal_operators):
            raise ValueError("episode requires registered signal operators")
        parameter_names: set[str] = set()
        for name, values in self.allowed_parameter_values:
            _text(name, "parameter name")
            _strings(values, "parameter values")
            if name in parameter_names:
                raise ValueError("parameter bounds cannot contain duplicate names")
            parameter_names.add(name)
        _text(self.market_state, "market state")
        _strings(self.warnings, "warnings", allow_empty=True)
        _strings(self.unknowns, "unknowns", allow_empty=True)
        if self.tradable:
            raise ValueError("MVP-R-003 episode must remain non-trading")
        if self.future_result_present:
            raise ValueError("MVP-R-003 episode cannot contain future result")

    @property
    def available_ref_uris(self) -> frozenset[str]:
        return frozenset(
            ref.uri
            for ref in (
                self.dataset_ref,
                self.market_snapshot_ref,
                self.feature_ref,
                self.rule_ref,
                self.cost_ref,
                self.toolset_ref,
                *self.evidence_refs,
            )
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "episode_id": self.episode_id,
            "instrument": self.instrument,
            "as_of": self.as_of,
            "market_cutoff": self.market_cutoff,
            "acquired_at": self.acquired_at,
            "dataset_ref": self.dataset_ref.to_dict(),
            "market_snapshot_ref": self.market_snapshot_ref.to_dict(),
            "feature_ref": self.feature_ref.to_dict(),
            "rule_ref": self.rule_ref.to_dict(),
            "cost_ref": self.cost_ref.to_dict(),
            "toolset_ref": self.toolset_ref.to_dict(),
            "signal_operators": tuple(item.value for item in self.signal_operators),
            "allowed_parameter_values": self.allowed_parameter_values,
            "market_state": self.market_state,
            "warnings": self.warnings,
            "unknowns": self.unknowns,
            "evidence_refs": tuple(item.to_dict() for item in self.evidence_refs),
            "tradable": self.tradable,
            "future_result_present": self.future_result_present,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchEpisodeInput:
        required = {
            "schema_version",
            "episode_id",
            "instrument",
            "as_of",
            "market_cutoff",
            "acquired_at",
            "dataset_ref",
            "market_snapshot_ref",
            "feature_ref",
            "rule_ref",
            "cost_ref",
            "toolset_ref",
            "signal_operators",
            "allowed_parameter_values",
            "market_state",
            "warnings",
            "unknowns",
            "evidence_refs",
            "tradable",
            "future_result_present",
            "content_sha256",
        }
        _exact_keys(value, required, "research episode input")
        parameter_values = tuple(
            (
                _text(_sequence(item, "allowed parameter values")[0], "parameter name"),
                _strings(_sequence(item, "allowed parameter values")[1], "parameter values"),
            )
            for item in _sequence(value["allowed_parameter_values"], "allowed parameter values")
        )
        instance = cls(
            _text(value["episode_id"], "episode id"),
            _text(value["instrument"], "instrument"),
            _text(value["as_of"], "as_of"),
            _text(value["market_cutoff"], "market cutoff"),
            _text(value["acquired_at"], "acquired at"),
            ArtifactRef.hydrate(_mapping(value["dataset_ref"], "dataset ref")),
            ArtifactRef.hydrate(_mapping(value["market_snapshot_ref"], "snapshot ref")),
            ArtifactRef.hydrate(_mapping(value["feature_ref"], "feature ref")),
            ArtifactRef.hydrate(_mapping(value["rule_ref"], "rule ref")),
            ArtifactRef.hydrate(_mapping(value["cost_ref"], "cost ref")),
            ArtifactRef.hydrate(_mapping(value["toolset_ref"], "toolset ref")),
            tuple(
                SignalOperator(_text(item, "signal operator"))
                for item in _sequence(value["signal_operators"], "operators")
            ),
            parameter_values,
            _text(value["market_state"], "market state"),
            _strings(value["warnings"], "warnings", allow_empty=True),
            _strings(value["unknowns"], "unknowns", allow_empty=True),
            tuple(
                ArtifactRef.hydrate(_mapping(item, "evidence ref"))
                for item in _sequence(value["evidence_refs"], "evidence refs")
            ),
            _bool(value["tradable"], "tradable"),
            _bool(value["future_result_present"], "future result present"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class HypothesisSpec(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.hypothesis-spec.v1"

    hypothesis_id: str
    version: int
    family: HypothesisFamily
    market_condition: str
    signal_operator: SignalOperator
    parameters: tuple[tuple[str, str], ...]
    expected_observable: str
    falsification_condition: str
    supporting_evidence_refs: tuple[str, ...]
    strongest_counter_evidence_refs: tuple[str, ...]
    unknowns: tuple[str, ...]
    primary_metric: str
    control: str
    cost_assumption_ref: str
    tradable: bool = False
    parent_hypothesis_ref: str | None = None

    def __post_init__(self) -> None:
        _text(self.hypothesis_id, "hypothesis id")
        _integer(self.version, "hypothesis version")
        if type(self.family) is not HypothesisFamily or type(self.signal_operator) is not SignalOperator:
            raise TypeError("hypothesis family and signal operator must be registered enums")
        for value, field in (
            (self.market_condition, "market condition"),
            (self.expected_observable, "expected observable"),
            (self.falsification_condition, "falsification condition"),
            (self.primary_metric, "primary metric"),
            (self.control, "control"),
            (self.cost_assumption_ref, "cost assumption ref"),
        ):
            _text(value, field)
        _pairs(self.parameters, "hypothesis parameters")
        _strings(self.supporting_evidence_refs, "supporting evidence refs")
        _strings(self.strongest_counter_evidence_refs, "counter evidence refs")
        _strings(self.unknowns, "unknowns", allow_empty=True)
        if self.tradable:
            raise ValueError("MVP-R-003 hypothesis must remain non-trading")
        if self.parent_hypothesis_ref is not None:
            _text(self.parent_hypothesis_ref, "parent hypothesis ref")

    @property
    def identity(self) -> str:
        return f"hypothesis://{self.hypothesis_id}/v{self.version}/{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "version": self.version,
            "family": self.family.value,
            "market_condition": self.market_condition,
            "signal_operator": self.signal_operator.value,
            "parameters": self.parameters,
            "expected_observable": self.expected_observable,
            "falsification_condition": self.falsification_condition,
            "supporting_evidence_refs": self.supporting_evidence_refs,
            "strongest_counter_evidence_refs": self.strongest_counter_evidence_refs,
            "unknowns": self.unknowns,
            "primary_metric": self.primary_metric,
            "control": self.control,
            "cost_assumption_ref": self.cost_assumption_ref,
            "tradable": self.tradable,
            "parent_hypothesis_ref": self.parent_hypothesis_ref,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> HypothesisSpec:
        required = {
            "schema_version",
            "hypothesis_id",
            "version",
            "family",
            "market_condition",
            "signal_operator",
            "parameters",
            "expected_observable",
            "falsification_condition",
            "supporting_evidence_refs",
            "strongest_counter_evidence_refs",
            "unknowns",
            "primary_metric",
            "control",
            "cost_assumption_ref",
            "tradable",
            "parent_hypothesis_ref",
            "content_sha256",
        }
        _exact_keys(value, required, "hypothesis spec")
        parent = value["parent_hypothesis_ref"]
        instance = cls(
            _text(value["hypothesis_id"], "hypothesis id"),
            _integer(value["version"], "hypothesis version"),
            HypothesisFamily(_text(value["family"], "family")),
            _text(value["market_condition"], "market condition"),
            SignalOperator(_text(value["signal_operator"], "signal operator")),
            _pairs(value["parameters"], "parameters"),
            _text(value["expected_observable"], "expected observable"),
            _text(value["falsification_condition"], "falsification condition"),
            _strings(value["supporting_evidence_refs"], "supporting refs"),
            _strings(value["strongest_counter_evidence_refs"], "counter refs"),
            _strings(value["unknowns"], "unknowns", allow_empty=True),
            _text(value["primary_metric"], "primary metric"),
            _text(value["control"], "control"),
            _text(value["cost_assumption_ref"], "cost ref"),
            _bool(value["tradable"], "tradable"),
            None if parent is None else _text(parent, "parent hypothesis ref"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class HypothesisValidation(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.hypothesis-validation.v1"

    hypothesis_ref: str
    status: ValidationStatus
    reason_codes: tuple[str, ...]
    parameters_resolved: bool
    data_resolved: bool
    window_resolved: bool
    metric_resolved: bool
    control_resolved: bool
    cost_resolved: bool
    future_leak_detected: bool
    duplicate_detected: bool

    def __post_init__(self) -> None:
        _text(self.hypothesis_ref, "hypothesis ref")
        if type(self.status) is not ValidationStatus:
            raise TypeError("validation status must be typed")
        _strings(self.reason_codes, "validation reason codes")
        for value in (
            self.parameters_resolved,
            self.data_resolved,
            self.window_resolved,
            self.metric_resolved,
            self.control_resolved,
            self.cost_resolved,
            self.future_leak_detected,
            self.duplicate_detected,
        ):
            _bool(value, "validation flag")

    @property
    def identity(self) -> str:
        return f"hypothesis-validation://{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "hypothesis_ref": self.hypothesis_ref,
            "status": self.status.value,
            "reason_codes": self.reason_codes,
            "parameters_resolved": self.parameters_resolved,
            "data_resolved": self.data_resolved,
            "window_resolved": self.window_resolved,
            "metric_resolved": self.metric_resolved,
            "control_resolved": self.control_resolved,
            "cost_resolved": self.cost_resolved,
            "future_leak_detected": self.future_leak_detected,
            "duplicate_detected": self.duplicate_detected,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> HypothesisValidation:
        payload_keys = {
            "hypothesis_ref",
            "status",
            "reason_codes",
            "parameters_resolved",
            "data_resolved",
            "window_resolved",
            "metric_resolved",
            "control_resolved",
            "cost_resolved",
            "future_leak_detected",
            "duplicate_detected",
        }
        _exact_keys(value, {"schema_version", "content_sha256", *payload_keys}, "hypothesis validation")
        instance = cls(
            _text(value["hypothesis_ref"], "hypothesis ref"),
            ValidationStatus(_text(value["status"], "validation status")),
            _strings(value["reason_codes"], "reason codes"),
            _bool(value["parameters_resolved"], "parameters resolved"),
            _bool(value["data_resolved"], "data resolved"),
            _bool(value["window_resolved"], "window resolved"),
            _bool(value["metric_resolved"], "metric resolved"),
            _bool(value["control_resolved"], "control resolved"),
            _bool(value["cost_resolved"], "cost resolved"),
            _bool(value["future_leak_detected"], "future leak detected"),
            _bool(value["duplicate_detected"], "duplicate detected"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class CriticReview(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.critic-review.v1"

    review_id: str
    hypothesis_id: str
    decision: CriticDecision
    checks: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.review_id, "review id")
        _text(self.hypothesis_id, "hypothesis id")
        if type(self.decision) is not CriticDecision:
            raise TypeError("critic decision must be typed")
        checks = _pairs(self.checks, "critic checks")
        required = {"leakage", "cost", "sample", "regime", "falsifiability", "multiple_testing"}
        if {key for key, _ in checks} != required:
            raise ValueError("critic review requires all fixed checks")
        _strings(self.reason_codes, "critic reason codes")
        _strings(self.source_refs, "critic source refs")

    @property
    def identity(self) -> str:
        return f"critic-review://{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "review_id": self.review_id,
            "hypothesis_id": self.hypothesis_id,
            "decision": self.decision.value,
            "checks": self.checks,
            "reason_codes": self.reason_codes,
            "source_refs": self.source_refs,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> CriticReview:
        required = {
            "schema_version",
            "review_id",
            "hypothesis_id",
            "decision",
            "checks",
            "reason_codes",
            "source_refs",
            "content_sha256",
        }
        _exact_keys(value, required, "critic review")
        instance = cls(
            _text(value["review_id"], "review id"),
            _text(value["hypothesis_id"], "hypothesis id"),
            CriticDecision(_text(value["decision"], "critic decision")),
            _pairs(value["checks"], "critic checks"),
            _strings(value["reason_codes"], "critic reason codes"),
            _strings(value["source_refs"], "critic source refs"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class ExecutableExperimentPlan(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.executable-experiment-plan.v1"

    plan_id: str
    hypothesis_ref: str
    dataset_ref: str
    window: str
    train_bars: int
    test_bars: int
    step_bars: int
    embargo_bars: int
    tool_requests: tuple[str, ...]
    primary_metric: str
    control: str
    stop_rule: str
    config_ref: str
    code_ref: str
    tradable: bool = False

    def __post_init__(self) -> None:
        for value, field in (
            (self.plan_id, "plan id"),
            (self.hypothesis_ref, "hypothesis ref"),
            (self.dataset_ref, "dataset ref"),
            (self.window, "window"),
            (self.primary_metric, "primary metric"),
            (self.control, "control"),
            (self.stop_rule, "stop rule"),
            (self.config_ref, "config ref"),
            (self.code_ref, "code ref"),
        ):
            _text(value, field)
        for numeric_value, field in (
            (self.train_bars, "train bars"),
            (self.test_bars, "test bars"),
            (self.step_bars, "step bars"),
            (self.embargo_bars, "embargo bars"),
        ):
            _integer(numeric_value, field)
        required = {
            "l0_signal_test",
            "l1_bar_backtest",
            "walk_forward_test",
            "cost_slippage_stress",
            "counterfactual_test",
        }
        if set(_strings(self.tool_requests, "tool requests")) != required:
            raise ValueError("experiment plan requires the complete V1-010 experiment suite")
        if self.tradable:
            raise ValueError("MVP-R-003 experiment plan must remain non-trading")

    @property
    def identity(self) -> str:
        return f"experiment-plan://{self.plan_id}/{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "plan_id": self.plan_id,
            "hypothesis_ref": self.hypothesis_ref,
            "dataset_ref": self.dataset_ref,
            "window": self.window,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step_bars,
            "embargo_bars": self.embargo_bars,
            "tool_requests": self.tool_requests,
            "primary_metric": self.primary_metric,
            "control": self.control,
            "stop_rule": self.stop_rule,
            "config_ref": self.config_ref,
            "code_ref": self.code_ref,
            "tradable": self.tradable,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExecutableExperimentPlan:
        payload_keys = {
            "plan_id",
            "hypothesis_ref",
            "dataset_ref",
            "window",
            "train_bars",
            "test_bars",
            "step_bars",
            "embargo_bars",
            "tool_requests",
            "primary_metric",
            "control",
            "stop_rule",
            "config_ref",
            "code_ref",
            "tradable",
        }
        _exact_keys(value, {"schema_version", "content_sha256", *payload_keys}, "experiment plan")
        instance = cls(
            _text(value["plan_id"], "plan id"),
            _text(value["hypothesis_ref"], "hypothesis ref"),
            _text(value["dataset_ref"], "dataset ref"),
            _text(value["window"], "window"),
            _integer(value["train_bars"], "train bars"),
            _integer(value["test_bars"], "test bars"),
            _integer(value["step_bars"], "step bars"),
            _integer(value["embargo_bars"], "embargo bars"),
            _strings(value["tool_requests"], "tool requests"),
            _text(value["primary_metric"], "primary metric"),
            _text(value["control"], "control"),
            _text(value["stop_rule"], "stop rule"),
            _text(value["config_ref"], "config ref"),
            _text(value["code_ref"], "code ref"),
            _bool(value["tradable"], "tradable"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    tool: str
    status: str
    metrics: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.tool, "tool")
        if self.status not in {"SUCCESS", "FAILED"}:
            raise ValueError("tool status must be SUCCESS or FAILED")
        _pairs(self.metrics, "tool metrics")
        _strings(self.warnings, "tool warnings", allow_empty=True)
        _strings(self.source_refs, "tool source refs")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "tool": self.tool,
            "status": self.status,
            "metrics": self.metrics,
            "warnings": self.warnings,
            "source_refs": self.source_refs,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ToolRunResult:
        _exact_keys(value, {"tool", "status", "metrics", "warnings", "source_refs"}, "tool run result")
        return cls(
            _text(value["tool"], "tool"),
            _text(value["status"], "status"),
            _pairs(value["metrics"], "metrics"),
            _strings(value["warnings"], "warnings", allow_empty=True),
            _strings(value["source_refs"], "source refs"),
        )


@dataclass(frozen=True, slots=True)
class ExperimentResultPacket(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.experiment-result-packet.v1"

    packet_id: str
    plan_ref: str
    tool_runs: tuple[ToolRunResult, ...]
    limitations: tuple[str, ...]
    complete: bool
    evaluator_future_data_present: bool = False

    def __post_init__(self) -> None:
        _text(self.packet_id, "packet id")
        _text(self.plan_ref, "plan ref")
        if any(type(item) is not ToolRunResult for item in self.tool_runs):
            raise TypeError("result packet requires exact ToolRunResult values")
        required = {
            "l0_signal_test",
            "l1_bar_backtest",
            "walk_forward_test",
            "cost_slippage_stress",
            "counterfactual_test",
        }
        if {item.tool for item in self.tool_runs} != required:
            raise ValueError("result packet requires exactly the complete experiment suite")
        _strings(self.limitations, "limitations", allow_empty=True)
        _bool(self.complete, "complete")
        if self.evaluator_future_data_present:
            raise ValueError("result packet cannot contain evaluator-only future data")
        if self.complete != all(item.status == "SUCCESS" for item in self.tool_runs):
            raise ValueError("result packet completeness must match tool statuses")

    @property
    def identity(self) -> str:
        return f"experiment-result://{self.packet_id}/{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "packet_id": self.packet_id,
            "plan_ref": self.plan_ref,
            "tool_runs": tuple(item.to_dict() for item in self.tool_runs),
            "limitations": self.limitations,
            "complete": self.complete,
            "evaluator_future_data_present": self.evaluator_future_data_present,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExperimentResultPacket:
        required = {
            "schema_version",
            "packet_id",
            "plan_ref",
            "tool_runs",
            "limitations",
            "complete",
            "evaluator_future_data_present",
            "content_sha256",
        }
        _exact_keys(value, required, "experiment result packet")
        instance = cls(
            _text(value["packet_id"], "packet id"),
            _text(value["plan_ref"], "plan ref"),
            tuple(
                ToolRunResult.hydrate(_mapping(item, "tool run")) for item in _sequence(value["tool_runs"], "tool runs")
            ),
            _strings(value["limitations"], "limitations", allow_empty=True),
            _bool(value["complete"], "complete"),
            _bool(value["evaluator_future_data_present"], "future data"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class ResearchFinalVerdict(_Contract):
    schema_version: ClassVar[str] = "mvp-r-003.research-final-verdict.v1"

    verdict_id: str
    verdict: FinalVerdict
    hypothesis_ref: str
    falsification_condition: str
    result_refs: tuple[str, ...]
    rationale: str
    modified_hypothesis: HypothesisSpec | None = None
    auto_execute_modified: bool = False

    def __post_init__(self) -> None:
        _text(self.verdict_id, "verdict id")
        if type(self.verdict) is not FinalVerdict:
            raise TypeError("final verdict must be typed")
        _text(self.hypothesis_ref, "hypothesis ref")
        _text(self.falsification_condition, "falsification condition")
        _strings(self.result_refs, "result refs")
        _text(self.rationale, "rationale")
        if self.auto_execute_modified:
            raise ValueError("modified hypothesis cannot auto-execute in the same episode")
        if self.verdict is FinalVerdict.MODIFY:
            if type(self.modified_hypothesis) is not HypothesisSpec:
                raise ValueError("MODIFY requires a new HypothesisSpec")
            identity_parts = self.hypothesis_ref.split("/")
            if self.modified_hypothesis.parent_hypothesis_ref != self.hypothesis_ref:
                raise ValueError("modified hypothesis must bind the original identity")
            if len(identity_parts) < 2 or self.modified_hypothesis.version != int(identity_parts[-2][1:]) + 1:
                raise ValueError("modified hypothesis must increment the original version once")
        elif self.modified_hypothesis is not None:
            raise ValueError("only MODIFY may include a modified hypothesis")

    @property
    def identity(self) -> str:
        return f"research-final-verdict://{self.verdict_id}/{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "verdict_id": self.verdict_id,
            "verdict": self.verdict.value,
            "hypothesis_ref": self.hypothesis_ref,
            "falsification_condition": self.falsification_condition,
            "result_refs": self.result_refs,
            "rationale": self.rationale,
            "modified_hypothesis": None if self.modified_hypothesis is None else self.modified_hypothesis.to_dict(),
            "auto_execute_modified": self.auto_execute_modified,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchFinalVerdict:
        required = {
            "schema_version",
            "verdict_id",
            "verdict",
            "hypothesis_ref",
            "falsification_condition",
            "result_refs",
            "rationale",
            "modified_hypothesis",
            "auto_execute_modified",
            "content_sha256",
        }
        _exact_keys(value, required, "research final verdict")
        modified = value["modified_hypothesis"]
        instance = cls(
            _text(value["verdict_id"], "verdict id"),
            FinalVerdict(_text(value["verdict"], "verdict")),
            _text(value["hypothesis_ref"], "hypothesis ref"),
            _text(value["falsification_condition"], "falsification condition"),
            _strings(value["result_refs"], "result refs"),
            _text(value["rationale"], "rationale"),
            None if modified is None else HypothesisSpec.hydrate(_mapping(modified, "modified hypothesis")),
            _bool(value["auto_execute_modified"], "auto execute modified"),
        )
        return cls._verify_hash(value, instance)
