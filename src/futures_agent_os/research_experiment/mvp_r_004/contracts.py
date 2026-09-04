"""Measurement-repair contracts for MVP-R-004. Does not mutate MVP-R-003 v1 Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Mapping

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    HypothesisSpec,
    _Contract,
    _bool,
    _exact_keys,
    _integer,
    _mapping,
    _pairs,
    _sequence,
    _strings,
    _text,
)
from futures_agent_os.shared_kernel.observability import JsonValue


PACKET_PRIMARY_METRICS = (
    "signal_accuracy",
    "proxy_net_return",
    "stressed_net_return",
    "positive_fold_ratio",
)
CONTROL_METRIC_BY_PRIMARY = (
    ("signal_accuracy", "counterfactual_signal_accuracy"),
    ("proxy_net_return", "counterfactual_net_return"),
    ("stressed_net_return", "counterfactual_stressed_net_return"),
    ("positive_fold_ratio", "counterfactual_positive_fold_ratio"),
)
PACKET_CONTROL = "inverted signal direction"


class GoldLabel(StrEnum):
    CLEAN = "CLEAN"
    BAD = "BAD"


@dataclass(frozen=True, slots=True)
class PitBarFact:
    event_time: str
    available_time: str
    close: str
    prior_close_return: str | None
    volume: str
    open_interest: str
    component_instrument: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.event_time, "event time"),
            (self.available_time, "available time"),
            (self.close, "close"),
            (self.volume, "volume"),
            (self.open_interest, "open interest"),
            (self.component_instrument, "component instrument"),
        ):
            _text(value, field)
        if self.prior_close_return is not None:
            _text(self.prior_close_return, "prior close return")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "event_time": self.event_time,
            "available_time": self.available_time,
            "close": self.close,
            "prior_close_return": self.prior_close_return,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "component_instrument": self.component_instrument,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> PitBarFact:
        _exact_keys(
            value,
            {
                "event_time",
                "available_time",
                "close",
                "prior_close_return",
                "volume",
                "open_interest",
                "component_instrument",
            },
            "pit bar fact",
        )
        prior = value["prior_close_return"]
        return cls(
            _text(value["event_time"], "event time"),
            _text(value["available_time"], "available time"),
            _text(value["close"], "close"),
            None if prior is None else _text(prior, "prior close return"),
            _text(value["volume"], "volume"),
            _text(value["open_interest"], "open interest"),
            _text(value["component_instrument"], "component instrument"),
        )


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundle(_Contract):
    schema_version: ClassVar[str] = "mvp-r-004.research-evidence-bundle.v1"

    episode_id: str
    instrument: str
    market_cutoff: str
    as_of: str
    market_state: str
    bars: tuple[PitBarFact, ...]
    summary: tuple[tuple[str, str], ...]
    future_bars_included: bool = False

    def __post_init__(self) -> None:
        for value, field in (
            (self.episode_id, "episode id"),
            (self.instrument, "instrument"),
            (self.market_cutoff, "market cutoff"),
            (self.as_of, "as of"),
            (self.market_state, "market state"),
        ):
            _text(value, field)
        if type(self.bars) is not tuple or not self.bars or any(type(item) is not PitBarFact for item in self.bars):
            raise TypeError("evidence bundle requires exact PitBarFact bars")
        if any(item.available_time > self.as_of for item in self.bars):
            raise ValueError("evidence bundle cannot include bars unavailable at as_of")
        if any(item.event_time > self.market_cutoff for item in self.bars):
            raise ValueError("evidence bundle cannot include bars after market_cutoff")
        _pairs(self.summary, "evidence summary")
        _bool(self.future_bars_included, "future bars included")
        if self.future_bars_included:
            raise ValueError("evidence bundle cannot include evaluator-only future bars")

    @property
    def identity(self) -> str:
        return f"evidence-bundle://{self.episode_id}/{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "episode_id": self.episode_id,
            "instrument": self.instrument,
            "market_cutoff": self.market_cutoff,
            "as_of": self.as_of,
            "market_state": self.market_state,
            "bars": tuple(item.to_dict() for item in self.bars),
            "summary": self.summary,
            "future_bars_included": self.future_bars_included,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchEvidenceBundle:
        payload_keys = {
            "episode_id",
            "instrument",
            "market_cutoff",
            "as_of",
            "market_state",
            "bars",
            "summary",
            "future_bars_included",
        }
        _exact_keys(value, {"schema_version", "content_sha256", *payload_keys}, "evidence bundle")
        instance = cls(
            _text(value["episode_id"], "episode id"),
            _text(value["instrument"], "instrument"),
            _text(value["market_cutoff"], "market cutoff"),
            _text(value["as_of"], "as of"),
            _text(value["market_state"], "market state"),
            tuple(PitBarFact.hydrate(_mapping(item, "pit bar")) for item in _sequence(value["bars"], "bars")),
            _pairs(value["summary"], "evidence summary"),
            _bool(value["future_bars_included"], "future bars included"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class ValidationProtocolDigest(_Contract):
    schema_version: ClassVar[str] = "mvp-r-004.validation-protocol-digest.v1"

    window_bars: int
    train_bars: int
    test_bars: int
    step_bars: int
    embargo_bars: int
    sample_count: int
    minimum_samples: int
    fold_count: int
    stop_after_failures: int
    round_trip_cost_bps: str
    slippage_bps: str
    stress_multipliers: tuple[str, ...]
    signal_threshold: str
    pit_protocol: str
    multiple_testing_budget: str
    packet_primary_metrics: tuple[str, ...]
    control_metric_by_primary: tuple[tuple[str, str], ...]
    known_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for numeric_value, field in (
            (self.window_bars, "window bars"),
            (self.train_bars, "train bars"),
            (self.test_bars, "test bars"),
            (self.step_bars, "step bars"),
            (self.embargo_bars, "embargo bars"),
            (self.sample_count, "sample count"),
            (self.minimum_samples, "minimum samples"),
            (self.fold_count, "fold count"),
            (self.stop_after_failures, "stop after failures"),
        ):
            _integer(numeric_value, field)
        for value, field in (
            (self.round_trip_cost_bps, "round trip cost"),
            (self.slippage_bps, "slippage"),
            (self.signal_threshold, "signal threshold"),
            (self.pit_protocol, "pit protocol"),
            (self.multiple_testing_budget, "multiple testing budget"),
        ):
            _text(value, field)
        _strings(self.stress_multipliers, "stress multipliers")
        _strings(self.packet_primary_metrics, "packet primary metrics")
        _pairs(self.control_metric_by_primary, "control metric map")
        _strings(self.known_limitations, "known limitations")
        if self.packet_primary_metrics != PACKET_PRIMARY_METRICS:
            raise ValueError("protocol digest must freeze the ResultPacket primary metric names")
        if self.control_metric_by_primary != CONTROL_METRIC_BY_PRIMARY:
            raise ValueError("protocol digest must freeze the primary-to-control metric map")

    @property
    def identity(self) -> str:
        return f"validation-protocol://{self.content_sha256}"

    def payload(self) -> dict[str, JsonValue]:
        return {
            "window_bars": self.window_bars,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step_bars,
            "embargo_bars": self.embargo_bars,
            "sample_count": self.sample_count,
            "minimum_samples": self.minimum_samples,
            "fold_count": self.fold_count,
            "stop_after_failures": self.stop_after_failures,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "slippage_bps": self.slippage_bps,
            "stress_multipliers": self.stress_multipliers,
            "signal_threshold": self.signal_threshold,
            "pit_protocol": self.pit_protocol,
            "multiple_testing_budget": self.multiple_testing_budget,
            "packet_primary_metrics": self.packet_primary_metrics,
            "control_metric_by_primary": self.control_metric_by_primary,
            "known_limitations": self.known_limitations,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ValidationProtocolDigest:
        payload_keys = {
            "window_bars",
            "train_bars",
            "test_bars",
            "step_bars",
            "embargo_bars",
            "sample_count",
            "minimum_samples",
            "fold_count",
            "stop_after_failures",
            "round_trip_cost_bps",
            "slippage_bps",
            "stress_multipliers",
            "signal_threshold",
            "pit_protocol",
            "multiple_testing_budget",
            "packet_primary_metrics",
            "control_metric_by_primary",
            "known_limitations",
        }
        _exact_keys(value, {"schema_version", "content_sha256", *payload_keys}, "protocol digest")
        instance = cls(
            _integer(value["window_bars"], "window bars"),
            _integer(value["train_bars"], "train bars"),
            _integer(value["test_bars"], "test bars"),
            _integer(value["step_bars"], "step bars"),
            _integer(value["embargo_bars"], "embargo bars"),
            _integer(value["sample_count"], "sample count"),
            _integer(value["minimum_samples"], "minimum samples"),
            _integer(value["fold_count"], "fold count"),
            _integer(value["stop_after_failures"], "stop after failures"),
            _text(value["round_trip_cost_bps"], "round trip cost"),
            _text(value["slippage_bps"], "slippage"),
            _strings(value["stress_multipliers"], "stress multipliers"),
            _text(value["signal_threshold"], "signal threshold"),
            _text(value["pit_protocol"], "pit protocol"),
            _text(value["multiple_testing_budget"], "multiple testing budget"),
            _strings(value["packet_primary_metrics"], "packet primary metrics"),
            _pairs(value["control_metric_by_primary"], "control metric map"),
            _strings(value["known_limitations"], "known limitations"),
        )
        return cls._verify_hash(value, instance)


@dataclass(frozen=True, slots=True)
class GoldHypothesisCase:
    episode_id: str
    label: GoldLabel
    expected_critic_decision: str
    hypothesis: HypothesisSpec

    def __post_init__(self) -> None:
        _text(self.episode_id, "gold episode id")
        if type(self.label) is not GoldLabel:
            raise TypeError("gold case requires an exact GoldLabel")
        _text(self.expected_critic_decision, "expected critic decision")
        if type(self.hypothesis) is not HypothesisSpec:
            raise TypeError("gold case requires an exact HypothesisSpec")
        if self.label is GoldLabel.CLEAN and self.expected_critic_decision != "SELECT":
            raise ValueError("gold CLEAN cases must expect Critic SELECT")
        if self.label is GoldLabel.BAD and self.expected_critic_decision != "REJECT":
            raise ValueError("gold BAD cases must expect Critic REJECT")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "episode_id": self.episode_id,
            "label": self.label.value,
            "expected_critic_decision": self.expected_critic_decision,
            "hypothesis": self.hypothesis.to_dict(),
        }
