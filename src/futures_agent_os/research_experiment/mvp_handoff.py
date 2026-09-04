"""Deterministic, machine-readable handoff for MVP-R research conclusions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_replay import ReplayCritique
from .mvp_roster import EpisodeStratum
from .mvp_validation import (
    AgentEpisodeView,
    HypothesisFamily,
    ModelRunRecord,
    ResearchConclusionKind,
    RetrospectiveMarketWindow,
    ToolExecutionRecord,
)
from .validation_tools import ValidationConfig


class ResearchHandoffDecision(StrEnum):
    CONTINUE_TEST = "CONTINUE_TEST"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    DO_NOT_ADVANCE = "DO_NOT_ADVANCE"
    DEFER = "DEFER"


class DirectionalScheme(StrEnum):
    WITH_TREND = "WITH_TREND"
    AGAINST_TREND = "AGAINST_TREND"


@dataclass(frozen=True, slots=True)
class ReplaySeriesDescriptor:
    instrument_id: str
    exchange: str
    series_type: str
    window_start: str
    window_end: str
    market_cutoff: str
    acquisition_as_of: str
    n_bars: int
    roll_count: int
    adjusted: bool
    source_window_sha256: str

    def __post_init__(self) -> None:
        if (
            not all(
                value.strip()
                for value in (
                    self.instrument_id,
                    self.exchange,
                    self.series_type,
                    self.window_start,
                    self.window_end,
                    self.market_cutoff,
                    self.acquisition_as_of,
                )
            )
            or type(self.n_bars) is not int
            or self.n_bars < 2
            or type(self.roll_count) is not int
            or self.roll_count < 0
            or type(self.adjusted) is not bool
        ):
            raise ValueError("replay series descriptor requires complete exact window facts")
        _digest(self.source_window_sha256)
        if self.adjusted and self.roll_count:
            raise ValueError("MVP-R official continuous replay is explicitly unadjusted")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "instrument_id": self.instrument_id,
            "exchange": self.exchange,
            "series_type": self.series_type,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "market_cutoff": self.market_cutoff,
            "acquisition_as_of": self.acquisition_as_of,
            "n_bars": self.n_bars,
            "roll_count": self.roll_count,
            "adjusted": self.adjusted,
            "source_window_sha256": self.source_window_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ReplaySeriesDescriptor:
        _exact_keys(
            value,
            {
                "instrument_id",
                "exchange",
                "series_type",
                "window_start",
                "window_end",
                "market_cutoff",
                "acquisition_as_of",
                "n_bars",
                "roll_count",
                "adjusted",
                "source_window_sha256",
            },
            "series descriptor",
        )
        return cls(
            _str(value["instrument_id"]),
            _str(value["exchange"]),
            _str(value["series_type"]),
            _str(value["window_start"]),
            _str(value["window_end"]),
            _str(value["market_cutoff"]),
            _str(value["acquisition_as_of"]),
            _int(value["n_bars"]),
            _int(value["roll_count"]),
            _bool(value["adjusted"]),
            _str(value["source_window_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class DirectionalSchemeEvidence:
    scheme: DirectionalScheme
    signal_accuracy: str
    base_cost_net_return: str
    stressed_cost_net_return: str
    positive_fold_ratio: str
    signal_count: int
    return_unit: str
    accuracy_unit: str
    fold_ratio_unit: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if type(self.scheme) is not DirectionalScheme or type(self.signal_count) is not int or self.signal_count < 0:
            raise ValueError("directional evidence requires a typed scheme and signal count")
        for value in (
            self.signal_accuracy,
            self.base_cost_net_return,
            self.stressed_cost_net_return,
            self.positive_fold_ratio,
        ):
            Decimal(value)
        if (self.return_unit, self.accuracy_unit, self.fold_ratio_unit) != ("ratio", "ratio", "ratio"):
            raise ValueError("MVP-R directional evidence uses explicit ratio units")
        _digest(self.evidence_sha256)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "scheme": self.scheme.value,
            "signal_accuracy": self.signal_accuracy,
            "base_cost_net_return": self.base_cost_net_return,
            "stressed_cost_net_return": self.stressed_cost_net_return,
            "positive_fold_ratio": self.positive_fold_ratio,
            "signal_count": self.signal_count,
            "return_unit": self.return_unit,
            "accuracy_unit": self.accuracy_unit,
            "fold_ratio_unit": self.fold_ratio_unit,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> DirectionalSchemeEvidence:
        _exact_keys(
            value,
            {
                "scheme",
                "signal_accuracy",
                "base_cost_net_return",
                "stressed_cost_net_return",
                "positive_fold_ratio",
                "signal_count",
                "return_unit",
                "accuracy_unit",
                "fold_ratio_unit",
                "evidence_sha256",
            },
            "directional evidence",
        )
        return cls(
            DirectionalScheme(_str(value["scheme"])),
            _str(value["signal_accuracy"]),
            _str(value["base_cost_net_return"]),
            _str(value["stressed_cost_net_return"]),
            _str(value["positive_fold_ratio"]),
            _int(value["signal_count"]),
            _str(value["return_unit"]),
            _str(value["accuracy_unit"]),
            _str(value["fold_ratio_unit"]),
            _str(value["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class FrozenNextExperimentRequest:
    request_status: str
    target_scheme: str
    selection_rule: str
    instrument_id: str
    window_bars: int
    embargo_bars: int
    require_non_overlapping_window: bool
    require_adjusted_series: bool
    required_market_state: str
    signal_rule: str
    forward_label_rule: str
    horizon: str
    base_cost_bps_per_signal: str
    stress_multiplier: str
    minimum_signal_accuracy: str
    minimum_positive_fold_ratio: str
    minimum_stressed_net_return: str
    failure_disposition: str
    config_sha256: str

    def __post_init__(self) -> None:
        if self.request_status not in {"READY", "NOT_REQUESTED"}:
            raise ValueError("next experiment request status is not canonical")
        if self.target_scheme not in {value.value for value in DirectionalScheme} | {"NONE"}:
            raise ValueError("next experiment request requires a canonical target scheme")
        if (
            not all(
                value.strip()
                for value in (
                    self.selection_rule,
                    self.instrument_id,
                    self.required_market_state,
                    self.signal_rule,
                    self.forward_label_rule,
                    self.horizon,
                    self.failure_disposition,
                )
            )
            or type(self.window_bars) is not int
            or self.window_bars < 2
            or type(self.embargo_bars) is not int
            or self.embargo_bars < 1
            or type(self.require_non_overlapping_window) is not bool
            or type(self.require_adjusted_series) is not bool
        ):
            raise ValueError("next experiment request requires complete deterministic parameters")
        for value in (
            self.base_cost_bps_per_signal,
            self.stress_multiplier,
            self.minimum_signal_accuracy,
            self.minimum_positive_fold_ratio,
            self.minimum_stressed_net_return,
        ):
            Decimal(value)
        _digest(self.config_sha256)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "request_status": self.request_status,
            "target_scheme": self.target_scheme,
            "selection_rule": self.selection_rule,
            "instrument_id": self.instrument_id,
            "window_bars": self.window_bars,
            "embargo_bars": self.embargo_bars,
            "require_non_overlapping_window": self.require_non_overlapping_window,
            "require_adjusted_series": self.require_adjusted_series,
            "required_market_state": self.required_market_state,
            "signal_rule": self.signal_rule,
            "forward_label_rule": self.forward_label_rule,
            "horizon": self.horizon,
            "base_cost_bps_per_signal": self.base_cost_bps_per_signal,
            "stress_multiplier": self.stress_multiplier,
            "minimum_signal_accuracy": self.minimum_signal_accuracy,
            "minimum_positive_fold_ratio": self.minimum_positive_fold_ratio,
            "minimum_stressed_net_return": self.minimum_stressed_net_return,
            "failure_disposition": self.failure_disposition,
            "config_sha256": self.config_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> FrozenNextExperimentRequest:
        expected = {
            "request_status",
            "target_scheme",
            "selection_rule",
            "instrument_id",
            "window_bars",
            "embargo_bars",
            "require_non_overlapping_window",
            "require_adjusted_series",
            "required_market_state",
            "signal_rule",
            "forward_label_rule",
            "horizon",
            "base_cost_bps_per_signal",
            "stress_multiplier",
            "minimum_signal_accuracy",
            "minimum_positive_fold_ratio",
            "minimum_stressed_net_return",
            "failure_disposition",
            "config_sha256",
        }
        _exact_keys(value, expected, "next experiment request")
        return cls(
            _str(value["request_status"]),
            _str(value["target_scheme"]),
            _str(value["selection_rule"]),
            _str(value["instrument_id"]),
            _int(value["window_bars"]),
            _int(value["embargo_bars"]),
            _bool(value["require_non_overlapping_window"]),
            _bool(value["require_adjusted_series"]),
            _str(value["required_market_state"]),
            _str(value["signal_rule"]),
            _str(value["forward_label_rule"]),
            _str(value["horizon"]),
            _str(value["base_cost_bps_per_signal"]),
            _str(value["stress_multiplier"]),
            _str(value["minimum_signal_accuracy"]),
            _str(value["minimum_positive_fold_ratio"]),
            _str(value["minimum_stressed_net_return"]),
            _str(value["failure_disposition"]),
            _str(value["config_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class MachineResearchHandoff:
    schema_version: str
    episode_id: str
    run_id: str
    market_state: str
    hypothesis_family: str
    decision: ResearchHandoffDecision
    decision_rule: str
    decision_reasons: tuple[str, ...]
    tradable: bool
    approximate_backtest_only: bool
    series: ReplaySeriesDescriptor
    schemes: tuple[DirectionalSchemeEvidence, ...]
    next_experiment: FrozenNextExperimentRequest
    source_result_sha256s: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != "mvp-r.machine-handoff.v1"
            or not self.episode_id.strip()
            or not self.run_id.strip()
            or not self.market_state.strip()
            or self.hypothesis_family not in {value.value for value in HypothesisFamily}
            or type(self.decision) is not ResearchHandoffDecision
            or not self.decision_rule.strip()
            or not self.decision_reasons
            or self.tradable is not False
            or self.approximate_backtest_only is not True
            or type(self.series) is not ReplaySeriesDescriptor
            or tuple(item.scheme for item in self.schemes)
            != (DirectionalScheme.WITH_TREND, DirectionalScheme.AGAINST_TREND)
            or type(self.next_experiment) is not FrozenNextExperimentRequest
        ):
            raise ValueError("machine research handoff is incomplete or unsafe")
        for digest in self.source_result_sha256s:
            _digest(digest)
        if tuple(sorted(set(self.source_result_sha256s))) != self.source_result_sha256s:
            raise ValueError("machine research handoff result references must be canonical")
        _digest(self.content_sha256)
        if canonical_sha256(self.payload()) != self.content_sha256:
            raise ValueError("machine research handoff digest does not bind its exact payload")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "market_state": self.market_state,
            "hypothesis_family": self.hypothesis_family,
            "decision": self.decision.value,
            "decision_rule": self.decision_rule,
            "decision_reasons": self.decision_reasons,
            "tradable": self.tradable,
            "approximate_backtest_only": self.approximate_backtest_only,
            "series": self.series.to_dict(),
            "schemes": tuple(item.to_dict() for item in self.schemes),
            "next_experiment": self.next_experiment.to_dict(),
            "source_result_sha256s": self.source_result_sha256s,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {**self.payload(), "content_sha256": self.content_sha256}

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> MachineResearchHandoff:
        expected = {
            "schema_version",
            "episode_id",
            "run_id",
            "market_state",
            "hypothesis_family",
            "decision",
            "decision_rule",
            "decision_reasons",
            "tradable",
            "approximate_backtest_only",
            "series",
            "schemes",
            "next_experiment",
            "source_result_sha256s",
            "content_sha256",
        }
        _exact_keys(value, expected, "machine research handoff")
        return cls(
            _str(value["schema_version"]),
            _str(value["episode_id"]),
            _str(value["run_id"]),
            _str(value["market_state"]),
            _str(value["hypothesis_family"]),
            ResearchHandoffDecision(_str(value["decision"])),
            _str(value["decision_rule"]),
            tuple(_str(item) for item in _tuple(value["decision_reasons"])),
            _bool(value["tradable"]),
            _bool(value["approximate_backtest_only"]),
            ReplaySeriesDescriptor.hydrate(_mapping(value["series"])),
            tuple(DirectionalSchemeEvidence.hydrate(_mapping(item)) for item in _tuple(value["schemes"])),
            FrozenNextExperimentRequest.hydrate(_mapping(value["next_experiment"])),
            tuple(_str(item) for item in _tuple(value["source_result_sha256s"])),
            _str(value["content_sha256"]),
        )


def build_machine_research_handoff(
    *,
    episode: AgentEpisodeView,
    window: RetrospectiveMarketWindow,
    records: tuple[PointInTimeRecord, ...],
    market_state: EpisodeStratum,
    run: ModelRunRecord,
    critique: ReplayCritique,
    config: ValidationConfig,
) -> MachineResearchHandoff:
    """Join model semantics with owner-produced facts without asking the LLM to copy parameters."""

    if run.conclusion is None or run.conclusion.hypothesis is None:
        raise ValueError("machine handoff requires a completed hypothesis conclusion")
    if str(run.episode_id) != str(episode.episode_id):
        raise PermissionError("machine handoff cannot cross episodes")
    by_tool = {item.tool_name: item for item in run.tool_executions}
    if set(by_tool) != {"historical_query", "l0_signal_test", "l1_bar_backtest"}:
        raise PermissionError("machine handoff requires the exact prefetched result set")
    historical = _metric_map(by_tool["historical_query"])
    l0 = _metric_map(by_tool["l0_signal_test"])
    l1 = _metric_map(by_tool["l1_bar_backtest"])
    required_historical = {"final_bar_count", "market_state", "roll_count"}
    required_l0 = {"signal_accuracy", "counterfactual_signal_accuracy", "signal_count"}
    required_l1 = {
        "proxy_net_return",
        "stressed_net_return",
        "positive_fold_ratio",
        "counterfactual_net_return",
        "counterfactual_stressed_net_return",
        "counterfactual_positive_fold_ratio",
    }
    if not required_historical <= set(historical) or not required_l0 <= set(l0) or not required_l1 <= set(l1):
        raise ValueError("machine handoff source results are incomplete")
    if historical["market_state"] != market_state.value or int(historical["final_bar_count"]) != len(records):
        raise ValueError("machine handoff market/window facts do not match the sealed episode")
    roll_count = int(historical["roll_count"])
    series = ReplaySeriesDescriptor(
        episode.instrument_id,
        episode.instrument_id.split(".", 1)[0],
        "DOMINANT_OI_CONTINUOUS",
        records[0].event_time.to_dict()["recorded_at"],
        records[-1].event_time.to_dict()["recorded_at"],
        episode.market_cutoff.to_dict()["recorded_at"],
        episode.as_of.to_dict()["recorded_at"],
        len(records),
        roll_count,
        False,
        window.content_sha256,
    )
    signal_count = int(l0["signal_count"])
    schemes = (
        DirectionalSchemeEvidence(
            DirectionalScheme.WITH_TREND,
            l0["signal_accuracy"],
            l1["proxy_net_return"],
            l1["stressed_net_return"],
            l1["positive_fold_ratio"],
            signal_count,
            "ratio",
            "ratio",
            "ratio",
            by_tool["l1_bar_backtest"].result_sha256,
        ),
        DirectionalSchemeEvidence(
            DirectionalScheme.AGAINST_TREND,
            l0["counterfactual_signal_accuracy"],
            l1["counterfactual_net_return"],
            l1["counterfactual_stressed_net_return"],
            l1["counterfactual_positive_fold_ratio"],
            signal_count,
            "ratio",
            "ratio",
            "ratio",
            by_tool["l1_bar_backtest"].result_sha256,
        ),
    )
    family = run.conclusion.hypothesis.family
    target_scheme = (
        DirectionalScheme.WITH_TREND.value
        if family
        in {
            HypothesisFamily.MOMENTUM_CONTINUATION,
            HypothesisFamily.BREAKOUT_CONTINUATION,
            HypothesisFamily.PARTICIPATION_CONFIRMED_TREND,
            HypothesisFamily.VOLATILITY_COMPRESSION_BREAKOUT,
        }
        else DirectionalScheme.AGAINST_TREND.value
        if family in {HypothesisFamily.MEAN_REVERSION, HypothesisFamily.FALSE_BREAKOUT_REVERSAL}
        else "NONE"
    )
    reasons = list(critique.high_severity_defects)
    if roll_count:
        reasons.append("UNADJUSTED_COMPONENT_ROLL_REQUIRES_ADJUSTED_RETEST")
    if market_state is EpisodeStratum.EXTREME_VOLATILITY:
        reasons.append("EXTREME_REGIME_REQUIRES_NON_EXTREME_CONFIRMATION")
    if run.conclusion.kind is ResearchConclusionKind.DEFER:
        decision = ResearchHandoffDecision.DEFER
        reasons.append("MODEL_DEFERRED")
    elif run.conclusion.kind is ResearchConclusionKind.NO_OPPORTUNITY:
        decision = ResearchHandoffDecision.DO_NOT_ADVANCE
        reasons.append("MODEL_FOUND_NO_OPPORTUNITY")
    elif not critique.accepted:
        decision = ResearchHandoffDecision.DO_NOT_ADVANCE
    elif roll_count or market_state is EpisodeStratum.EXTREME_VOLATILITY:
        decision = ResearchHandoffDecision.OBSERVE_ONLY
    else:
        decision = ResearchHandoffDecision.CONTINUE_TEST
        reasons.append("ALL_FROZEN_RESEARCH_GATES_PASSED")
    canonical_reasons = tuple(sorted(set(reasons)))
    request = FrozenNextExperimentRequest(
        "READY" if decision is ResearchHandoffDecision.CONTINUE_TEST else "NOT_REQUESTED",
        target_scheme,
        "first-complete-non-overlapping-chronological-window-after-embargo.v1",
        episode.instrument_id,
        len(records),
        config.test_bars,
        True,
        bool(roll_count),
        "NOT_EXTREME_VOLATILITY" if market_state is EpisodeStratum.EXTREME_VOLATILITY else "SAME_STRATUM",
        config.signal_rule,
        config.forward_label_rule,
        "NEXT_CLOSE_DIRECTION_1_BAR",
        _decimal_text(config.round_trip_cost_bps + config.slippage_bps),
        _decimal_text(max(config.stress_multipliers)),
        _decimal_text(Decimal("0.55")),
        _decimal_text(config.minimum_fold_positive_ratio),
        _decimal_text(Decimal(0)),
        "DO_NOT_ADVANCE",
        config.content_sha256,
    )
    payload: dict[str, JsonValue] = {
        "schema_version": "mvp-r.machine-handoff.v1",
        "episode_id": str(episode.episode_id),
        "run_id": str(run.run_id),
        "market_state": market_state.value,
        "hypothesis_family": family.value,
        "decision": decision.value,
        "decision_rule": "mvp-r.research-handoff-decision.v1",
        "decision_reasons": canonical_reasons,
        "tradable": False,
        "approximate_backtest_only": True,
        "series": series.to_dict(),
        "schemes": tuple(item.to_dict() for item in schemes),
        "next_experiment": request.to_dict(),
        "source_result_sha256s": tuple(sorted(item.result_sha256 for item in run.tool_executions)),
    }
    return MachineResearchHandoff(
        "mvp-r.machine-handoff.v1",
        str(episode.episode_id),
        str(run.run_id),
        market_state.value,
        family.value,
        decision,
        "mvp-r.research-handoff-decision.v1",
        canonical_reasons,
        False,
        True,
        series,
        schemes,
        request,
        cast(tuple[str, ...], payload["source_result_sha256s"]),
        canonical_sha256(payload),
    )


def _metric_map(execution: ToolExecutionRecord) -> dict[str, str]:
    if not isinstance(execution.result, Mapping):
        raise TypeError("machine handoff result must be a mapping")
    metrics = execution.result.get("metrics")
    if type(metrics) is not tuple:
        raise TypeError("machine handoff metrics must be immutable pairs")
    mapped: dict[str, str] = {}
    for pair in metrics:
        if type(pair) is not tuple or len(pair) != 2:
            raise TypeError("machine handoff metric pair is malformed")
        key, value = pair
        if type(key) is not str or type(value) is not str or key in mapped:
            raise ValueError("machine handoff metrics must be unique text pairs")
        mapped[key] = value
    return mapped


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001")), "f")


def _digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("expected canonical SHA-256 digest")


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} contains missing or unexpected keys")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("expected a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _tuple(value: object) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise TypeError("expected an array")
    return tuple(cast(tuple[object, ...] | list[object], value))


def _str(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected exact text")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise TypeError("expected exact integer")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected exact boolean")
    return value


__all__ = [
    "DirectionalScheme",
    "DirectionalSchemeEvidence",
    "FrozenNextExperimentRequest",
    "MachineResearchHandoff",
    "ReplaySeriesDescriptor",
    "ResearchHandoffDecision",
    "build_machine_research_handoff",
]
