"""Deterministic candidate and tool facts for MVP-R sealed replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import NamedTuple, cast

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_roster import EpisodeStratum
from .mvp_pivot import family_screen_metrics, screen_hypothesis_families
from .mvp_validation import (
    AgentEpisodeView,
    HypothesisFamily,
    ResearchConclusion,
    ResearchConclusionKind,
    RetrospectiveMarketWindow,
    ToolExecutionRecord,
)
from .validation_tools import (
    ResearchArtifactRef,
    ResearchToolName,
    ResearchToolResult,
    ToolFailureCode,
    TrustedResearchToolsPort,
    ValidationConfig,
    semantic_entity_id,
)
from .walk_forward import (
    WALK_FORWARD_ACCURACY_SOURCE,
    evaluate_oos_folds,
    fold_manifest_json,
)


MVP_R_REPLAY_CLASSIFIER = "balanced-market-state-score.v1"
_WINDOW_BARS = 40
_FUTURE_BARS = 5


@dataclass(frozen=True, slots=True)
class ReplayEpisodeCandidate:
    instrument_id: str
    stratum: EpisodeStratum
    records: tuple[PointInTimeRecord, ...]
    future_record: PointInTimeRecord

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or type(self.stratum) is not EpisodeStratum:
            raise ValueError("replay candidate requires instrument and stratum")
        if len(self.records) != _WINDOW_BARS or any(type(item) is not PointInTimeRecord for item in self.records):
            raise ValueError("replay candidate requires the frozen historical window")
        if any(item.values.get("instrument_id") != self.instrument_id for item in self.records):
            raise PermissionError("replay candidate cannot cross instruments")
        if tuple(sorted(self.records, key=lambda item: item.event_time.value)) != self.records:
            raise ValueError("replay candidate records must be chronological")
        if self.future_record.values.get("instrument_id") != self.instrument_id:
            raise PermissionError("replay future record cannot cross instruments")
        if self.future_record.event_time.value <= self.records[-1].event_time.value:
            raise ValueError("replay future record must follow the market cutoff")

    @property
    def market_cutoff(self) -> RecordedAt:
        return self.records[-1].event_time


@dataclass(frozen=True, slots=True)
class ReplayCritique:
    accepted: bool
    high_severity_defects: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool or not self.high_severity_defects == tuple(
            sorted(set(self.high_severity_defects))
        ):
            raise ValueError("replay critique requires canonical defect facts")
        if self.accepted == bool(self.high_severity_defects):
            raise ValueError("accepted critique cannot contain high-severity defects")
        if canonical_sha256(self.payload()) != self.content_sha256:
            raise ValueError("replay critique digest must bind its exact payload")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "accepted": self.accepted,
            "high_severity_defects": self.high_severity_defects,
        }


def critique_replay_conclusion(
    conclusion: ResearchConclusion,
    market_state: EpisodeStratum,
    executions: tuple[ToolExecutionRecord, ...],
) -> ReplayCritique:
    """Independent deterministic veto for the frozen residual-research policy."""

    if type(conclusion) is not ResearchConclusion or type(market_state) is not EpisodeStratum:
        raise TypeError("replay Critic requires an exact conclusion and market state")
    by_tool = {item.tool_name: item for item in executions}
    if set(by_tool) != {"historical_query", "l0_signal_test", "l1_bar_backtest"}:
        raise PermissionError("replay Critic requires the exact prefetched evidence set")
    l0 = _metric_map(by_tool["l0_signal_test"])
    l1 = _metric_map(by_tool["l1_bar_backtest"])
    defects: list[str] = []
    hypothesis = conclusion.hypothesis
    if hypothesis is None:
        defects.append("hypothesis_missing")
    elif conclusion.kind is ResearchConclusionKind.OPPORTUNITY_CANDIDATE:
        if hypothesis.family is HypothesisFamily.NONE:
            defects.append("opportunity_without_directional_hypothesis")
        required_l0 = {"signal_accuracy"}
        required_l1 = {
            "counterfactual_positive_fold_ratio",
            "proxy_net_return",
            "positive_fold_ratio",
            "stressed_net_return",
            "counterfactual_net_return",
            "counterfactual_stressed_net_return",
        }
        if not required_l0 <= set(l0) or not required_l1 <= set(l1):
            defects.append("opportunity_required_evidence_missing")
        elif hypothesis.family is HypothesisFamily.MOMENTUM_CONTINUATION and Decimal(l0["signal_accuracy"]) < Decimal(
            "0.55"
        ):
            defects.append("momentum_accuracy_below_frozen_floor")
        elif hypothesis.family is HypothesisFamily.MEAN_REVERSION and Decimal(1) - Decimal(
            l0["signal_accuracy"]
        ) < Decimal("0.55"):
            defects.append("mean_reversion_accuracy_below_frozen_floor")
        residual_states = (
            {
                EpisodeStratum.NOISE,
                EpisodeStratum.EXTREME_VOLATILITY,
                EpisodeStratum.FALSE_BREAKOUT,
            }
            if hypothesis.family is HypothesisFamily.MOMENTUM_CONTINUATION
            else {
                EpisodeStratum.RANGE,
                EpisodeStratum.REVERSAL,
                EpisodeStratum.FALSE_BREAKOUT,
            }
            if hypothesis.family is HypothesisFamily.MEAN_REVERSION
            else set()
        )
        if market_state not in residual_states:
            defects.append("hypothesis_family_outside_residual_regime")
        if (
            required_l1 <= set(l1)
            and hypothesis.family is HypothesisFamily.MOMENTUM_CONTINUATION
            and (Decimal(l1["proxy_net_return"]) <= 0 or Decimal(l1["stressed_net_return"]) <= 0)
        ):
            defects.append("momentum_hypothesis_lacks_positive_stressed_evidence")
        if (
            required_l1 <= set(l1)
            and hypothesis.family is HypothesisFamily.MOMENTUM_CONTINUATION
            and Decimal(l1["positive_fold_ratio"]) < Decimal("0.50")
        ):
            defects.append("momentum_positive_fold_ratio_below_frozen_floor")
        if (
            required_l1 <= set(l1)
            and hypothesis.family is HypothesisFamily.MEAN_REVERSION
            and (
                Decimal(l1["counterfactual_net_return"]) <= 0 or Decimal(l1["counterfactual_stressed_net_return"]) <= 0
            )
        ):
            defects.append("mean_reversion_hypothesis_lacks_positive_stressed_evidence")
        if (
            required_l1 <= set(l1)
            and hypothesis.family is HypothesisFamily.MEAN_REVERSION
            and Decimal(l1["counterfactual_positive_fold_ratio"]) < Decimal("0.50")
        ):
            defects.append("mean_reversion_positive_fold_ratio_below_frozen_floor")
        l1_digest = by_tool["l1_bar_backtest"].result_sha256
        if l1_digest not in conclusion.counter_evidence_sha256s:
            defects.append("competing_family_counter_evidence_missing")
    canonical_defects = tuple(sorted(set(defects)))
    payload: dict[str, JsonValue] = {
        "accepted": not canonical_defects,
        "high_severity_defects": canonical_defects,
    }
    return ReplayCritique(not canonical_defects, canonical_defects, canonical_sha256(payload))


def stratified_replay_candidates(
    records: tuple[PointInTimeRecord, ...],
    *,
    cutoff_start: RecordedAt,
    cutoff_end: RecordedAt,
    candidates_per_cell: int,
) -> tuple[ReplayEpisodeCandidate, ...]:
    """Select a balanced candidate pool without exposing future outcomes."""

    if candidates_per_cell < 2:
        raise ValueError("replay candidate pool requires at least two candidates per cell")
    grouped: dict[str, list[PointInTimeRecord]] = {}
    for record in records:
        instrument_id = record.values.get("instrument_id")
        if type(instrument_id) is not str:
            raise ValueError("replay record requires instrument_id")
        grouped.setdefault(instrument_id, []).append(record)

    selected: list[ReplayEpisodeCandidate] = []
    for instrument_id, raw_series in sorted(grouped.items()):
        series = tuple(sorted(raw_series, key=lambda item: item.event_time.value))
        scored: list[tuple[int, dict[EpisodeStratum, Decimal]]] = []
        for index in range(_WINDOW_BARS - 1, len(series) - _FUTURE_BARS):
            cutoff = series[index].event_time
            if not cutoff_start.value <= cutoff.value <= cutoff_end.value:
                continue
            window = series[index - _WINDOW_BARS + 1 : index + 1]
            if any(_close(item) is None for item in window):
                continue
            scored.append((index, _scores(window)))
        if len(scored) < len(EpisodeStratum) * candidates_per_cell:
            raise ValueError(f"insufficient replay candidates for {instrument_id}")
        used: set[int] = set()
        for stratum in EpisodeStratum:
            ranked = sorted(scored, key=lambda item: (-item[1][stratum], item[0]))
            chosen = [item for item in ranked if item[0] not in used][:candidates_per_cell]
            if len(chosen) != candidates_per_cell:
                raise ValueError(f"insufficient unique {stratum.value} candidates for {instrument_id}")
            for index, _ in chosen:
                used.add(index)
                selected.append(
                    ReplayEpisodeCandidate(
                        instrument_id,
                        stratum,
                        series[index - _WINDOW_BARS + 1 : index + 1],
                        series[index + _FUTURE_BARS],
                    )
                )
    return tuple(sorted(selected, key=lambda item: (item.instrument_id, item.stratum.value, item.market_cutoff.value)))


def replay_market_state_scores(records: tuple[PointInTimeRecord, ...]) -> tuple[tuple[EpisodeStratum, Decimal], ...]:
    """Return the future-blind market-state scores used for roster stratification."""

    if len(records) != _WINDOW_BARS or any(type(item) is not PointInTimeRecord for item in records):
        raise ValueError("market-state scoring requires the frozen forty-bar window")
    if tuple(sorted(records, key=lambda item: item.event_time.value)) != records:
        raise ValueError("market-state scoring requires chronological records")
    instruments = {item.values.get("instrument_id") for item in records}
    if len(instruments) != 1 or None in instruments:
        raise PermissionError("market-state scoring cannot cross instruments")
    if any(_close(item) is None for item in records):
        raise ValueError("market-state scoring requires complete close values")
    scores = _scores(records)
    return tuple((stratum, scores[stratum]) for stratum in EpisodeStratum)


def issue_replay_tool_results(
    *,
    episode: AgentEpisodeView,
    window: RetrospectiveMarketWindow,
    records: tuple[PointInTimeRecord, ...],
    market_state: EpisodeStratum,
    request_sha256: str,
    config: ValidationConfig,
    run_id: EntityId,
    result_authority: TrustedResearchToolsPort,
    inject_insufficient_l1: bool = False,
    include_pivot_family_screen: bool = False,
    embargo_bars: int = 1,
) -> tuple[ResearchToolResult, ...]:
    if type(inject_insufficient_l1) is not bool or type(include_pivot_family_screen) is not bool:
        raise TypeError("replay fault-injection flag must be exact boolean")
    if type(embargo_bars) is not int or embargo_bars < 1:
        raise ValueError("replay tools require a positive embargo")
    if type(market_state) is not EpisodeStratum:
        raise TypeError("replay tools require an exact deterministic market state")
    if window.content_sha256 not in episode.input_artifact_sha256s or window.record_sha256s != tuple(
        canonical_sha256(_record_payload(record)) for record in records
    ):
        raise PermissionError("replay tools require the exact sealed Episode window")
    if episode.market_cutoff != window.market_cutoff or episode.as_of != window.acquisition_as_of:
        raise PermissionError("replay tools cannot change acquisition or market cutoff")
    valid_until = RecordedAt(episode.as_of.value + timedelta(hours=1))
    source = ResearchArtifactRef(
        semantic_entity_id("artifact", {"kind": "retrospective_market_window", "sha256": window.content_sha256}),
        "retrospective_market_window",
        SchemaVersion(1, 0),
        window.content_sha256,
        episode.as_of,
        valid_until,
    )
    closes = tuple(cast(Decimal, _close(item)) for item in records)
    returns = tuple(closes[index] / closes[index - 1] - 1 for index in range(1, len(closes)))
    threshold = config.signal_threshold
    signals = tuple(1 if value > threshold else -1 if value < -threshold else 0 for value in returns[:-1])
    labels = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in returns[1:])
    forward_returns = returns[1:]
    signalled = tuple(index for index, signal in enumerate(signals) if signal)
    accuracy = _ratio(sum(signals[index] == labels[index] for index in signalled), len(signalled))
    invert_accuracy = _ratio(sum(-signals[index] == labels[index] for index in signalled), len(signalled))
    gross = sum((Decimal(signals[index]) * returns[index + 1] for index in signalled), Decimal(0))
    per_signal_cost = (config.round_trip_cost_bps + config.slippage_bps) / Decimal(10_000)
    net = gross - per_signal_cost * len(signalled)
    counterfactual = -gross - per_signal_cost * len(signalled)
    signal_times = tuple(records[index + 1].event_time.to_dict()["recorded_at"] for index in range(len(signals)))
    label_times = tuple(records[index + 2].event_time.to_dict()["recorded_at"] for index in range(len(signals)))
    oos_folds = evaluate_oos_folds(
        signals=signals,
        labels=labels,
        forward_returns=forward_returns,
        per_signal_cost=per_signal_cost,
        train_bars=config.train_bars,
        test_bars=config.test_bars,
        step_bars=config.step_bars,
        embargo_bars=embargo_bars,
        signal_times=signal_times,
        label_times=label_times,
        config_sha256=config.content_sha256,
    )
    populated = tuple(item for item in oos_folds if item.signal_count)
    if populated:
        positive_fold_ratio = _ratio(sum(item.follow_net > 0 for item in populated), len(populated))
        counterfactual_positive_fold_ratio = _ratio(sum(item.invert_net > 0 for item in populated), len(populated))
    else:
        positive_fold_ratio = Decimal(0)
        counterfactual_positive_fold_ratio = Decimal(0)
    oos_signal_count = sum(item.signal_count for item in oos_folds)
    walk_forward_metrics: dict[str, object] = {
        "counterfactual_positive_fold_ratio": counterfactual_positive_fold_ratio,
        "counterfactual_positive_fold_ratio_unit": "ratio",
        "positive_fold_ratio": positive_fold_ratio,
        "positive_fold_ratio_unit": "ratio",
        "fold_count": len(oos_folds),
        "fold_count_unit": "folds",
        "planned_fold_count": len(oos_folds),
        "planned_fold_count_unit": "folds",
        "stopped_early": "false",
        "fold_signal_accuracy_source": WALK_FORWARD_ACCURACY_SOURCE,
        "fold_manifest": fold_manifest_json(oos_folds),
        "full_window_signal_count": len(signalled),
        "full_window_signal_count_unit": "signals",
        "oos_signal_count": oos_signal_count,
        "oos_signal_count_unit": "signals",
        "embargo_bars": embargo_bars,
        "embargo_bars_unit": "bars",
        "test_bars": config.test_bars,
        "test_bars_unit": "bars",
        "config_sha256": config.content_sha256,
    }
    for item in oos_folds:
        index = item.window.fold_index
        if item.signal_count > config.test_bars:
            raise ValueError("OOS fold signal_count cannot exceed test_bars")
        walk_forward_metrics[f"fold_{index}_signal_accuracy"] = item.follow_accuracy
        walk_forward_metrics[f"fold_{index}_signal_accuracy_unit"] = "ratio"
        walk_forward_metrics[f"fold_{index}_counterfactual_signal_accuracy"] = item.invert_accuracy
        walk_forward_metrics[f"fold_{index}_counterfactual_signal_accuracy_unit"] = "ratio"
        walk_forward_metrics[f"fold_{index}_signal_count"] = item.signal_count
        walk_forward_metrics[f"fold_{index}_signal_count_unit"] = "signals"
        walk_forward_metrics[f"fold_{index}_proxy_net_return"] = item.follow_net
        walk_forward_metrics[f"fold_{index}_proxy_net_return_unit"] = "ratio"
        walk_forward_metrics[f"fold_{index}_counterfactual_net_return"] = item.invert_net
        walk_forward_metrics[f"fold_{index}_counterfactual_net_return_unit"] = "ratio"
    roll_count = sum(
        records[index].values.get("component_instrument") != records[index - 1].values.get("component_instrument")
        for index in range(1, len(records))
    )
    family_metrics = (
        family_screen_metrics(
            screen_hypothesis_families(
                records,
                signal_threshold=config.signal_threshold,
                per_signal_cost=per_signal_cost,
            )
        )
        if include_pivot_family_screen
        else ()
    )
    common_warnings = ("unadjusted component roll exists",) if roll_count else ()
    metrics: dict[ResearchToolName, tuple[tuple[str, str], ...]] = {
        ResearchToolName.MARKET_QUERY: _metrics(
            latest_close=closes[-1],
            latest_close_unit="CNY/contract_quote_unit",
            record_count=len(records),
            record_count_unit="bars",
        ),
        ResearchToolName.HISTORICAL_QUERY: _metrics(
            final_bar_count=len(records),
            final_bar_count_unit="bars",
            market_state=market_state.value,
            roll_count=roll_count,
            roll_count_unit="rolls",
        ),
        ResearchToolName.FEATURE_QUERY: family_metrics,
        ResearchToolName.CONTRACT_QUERY: _metrics(roll_count=roll_count, roll_count_unit="rolls"),
        ResearchToolName.MEMORY_SEARCH: (),
        ResearchToolName.EXPERIMENT_SEARCH: (),
        ResearchToolName.L0_SIGNAL_TEST: _metrics(
            counterfactual_signal_accuracy=invert_accuracy,
            counterfactual_signal_accuracy_unit="ratio",
            signal_accuracy=accuracy,
            signal_accuracy_unit="ratio",
            signal_count=len(signalled),
            signal_count_unit="signals",
            full_window_signal_count=len(signalled),
            full_window_signal_count_unit="signals",
        ),
        ResearchToolName.L1_BAR_BACKTEST: _metrics(
            counterfactual_positive_fold_ratio=counterfactual_positive_fold_ratio,
            counterfactual_positive_fold_ratio_unit="ratio",
            counterfactual_net_return=counterfactual,
            counterfactual_net_return_unit="ratio",
            counterfactual_stressed_net_return=counterfactual - per_signal_cost * len(signalled),
            counterfactual_stressed_net_return_unit="ratio",
            positive_fold_ratio=positive_fold_ratio,
            positive_fold_ratio_unit="ratio",
            proxy_net_return=net,
            proxy_net_return_unit="ratio",
            signal_count=len(signalled),
            signal_count_unit="signals",
            stressed_net_return=net - per_signal_cost * len(signalled),
            stressed_net_return_unit="ratio",
        ),
        ResearchToolName.WALK_FORWARD: _metrics(**walk_forward_metrics),
        ResearchToolName.COST_STRESS: _metrics(
            stressed_net_return=net - per_signal_cost * len(signalled),
            stressed_net_return_unit="ratio",
        ),
        ResearchToolName.COUNTERFACTUAL: _metrics(
            counterfactual_net_return=counterfactual,
            counterfactual_net_return_unit="ratio",
        ),
    }
    no_match = {ResearchToolName.MEMORY_SEARCH, ResearchToolName.EXPERIMENT_SEARCH}
    if not include_pivot_family_screen:
        no_match.add(ResearchToolName.FEATURE_QUERY)
    results = []
    for tool in ResearchToolName:
        critical_insufficient = inject_insufficient_l1 and tool is ResearchToolName.L1_BAR_BACKTEST
        failure = (
            ToolFailureCode.INSUFFICIENT_SAMPLE
            if critical_insufficient
            else ToolFailureCode.NO_MATCH
            if tool in no_match
            else ToolFailureCode.NONE
        )
        warnings = tuple(
            sorted(
                (
                    *common_warnings,
                    *(("governed sample unavailable",) if critical_insufficient else ()),
                    *(("no governed match",) if tool in no_match else ()),
                )
            )
        )
        results.append(
            _result(
                tool,
                episode,
                source,
                warnings,
                failure,
                request_sha256,
                config,
                run_id,
                () if critical_insufficient else metrics[tool],
                result_authority,
            )
        )
    return tuple(results)


def _scores(records: tuple[PointInTimeRecord, ...]) -> dict[EpisodeStratum, Decimal]:
    closes = tuple(cast(Decimal, _close(item)) for item in records)
    returns = tuple(closes[index] / closes[index - 1] - 1 for index in range(1, len(closes)))
    trend = closes[-1] / closes[-21] - 1
    recent = closes[-1] / closes[-6] - 1
    prior = closes[-6] / closes[-11] - 1
    volatility = sum(abs(value) for value in returns[-20:]) / Decimal(20)
    sign_changes = sum(
        (returns[index] > 0) != (returns[index - 1] > 0) for index in range(len(returns) - 19, len(returns))
    )
    prior_high = max(closes[-11:-1])
    prior_low = min(closes[-11:-1])
    false_break = max(
        max(closes[-5:]) / prior_high - 1 if max(closes[-5:]) > prior_high and closes[-1] < prior_high else Decimal(0),
        prior_low / min(closes[-5:]) - 1 if min(closes[-5:]) < prior_low and closes[-1] > prior_low else Decimal(0),
    )
    reversal = abs(prior) + abs(recent) if prior * recent < 0 else Decimal(0)
    noise = Decimal(sign_changes) / Decimal(20) + volatility - abs(trend)
    return {
        EpisodeStratum.UP_TREND: trend,
        EpisodeStratum.DOWN_TREND: -trend,
        EpisodeStratum.RANGE: volatility - abs(trend),
        EpisodeStratum.REVERSAL: reversal,
        EpisodeStratum.EXTREME_VOLATILITY: volatility,
        EpisodeStratum.FALSE_BREAKOUT: false_break,
        EpisodeStratum.NOISE: noise,
    }


def _result(
    tool: ResearchToolName,
    episode: AgentEpisodeView,
    source: ResearchArtifactRef,
    warnings: tuple[str, ...],
    failure: ToolFailureCode,
    request_sha256: str,
    config: ValidationConfig,
    run_id: EntityId,
    metrics: tuple[tuple[str, str], ...],
    authority: TrustedResearchToolsPort,
) -> ResearchToolResult:
    valid_until = RecordedAt(episode.as_of.value + timedelta(hours=1))
    payload: dict[str, JsonValue] = {
        "tool": tool.value,
        "tool_version": "research-validation.v1",
        "schema_version": "1.5",
        "as_of": episode.as_of.to_dict()["recorded_at"],
        "valid_until": valid_until.to_dict()["recorded_at"],
        "source_refs": (source.to_dict(),),
        "warnings": warnings,
        "failure_code": failure.value,
        "request_sha256": request_sha256,
        "config": config.payload(),
        "config_sha256": config.content_sha256,
        "run_id": str(run_id),
        "metrics": metrics,
    }
    content_sha256 = canonical_sha256(payload)
    return ResearchToolResult(
        semantic_entity_id("research_tool_result", {"request_sha256": request_sha256, "tool": tool.value}),
        tool,
        episode.as_of,
        valid_until,
        (source,),
        warnings,
        failure,
        request_sha256,
        config,
        run_id,
        metrics,
        content_sha256,
        "research_experiment.deterministic_tools.v1",
        authority.sign(content_sha256),
    )


def _metrics(**values: object) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, _metric_text(value)) for key, value in values.items()))


class ChronologicalFoldDiagnostics(NamedTuple):
    """Net-positive fold share is not per-fold hit rate."""

    positive_fold_ratio: Decimal
    counterfactual_positive_fold_ratio: Decimal
    fold_signal_accuracies: tuple[Decimal, ...]
    fold_counterfactual_signal_accuracies: tuple[Decimal, ...]
    fold_signal_counts: tuple[int, ...]


def chronological_fold_diagnostics(
    signals: tuple[int, ...],
    returns: tuple[Decimal, ...],
    per_signal_cost: Decimal,
    *,
    folds: int,
) -> ChronologicalFoldDiagnostics:
    """Measure net-positive fold share and per-fold signal accuracy separately."""

    if folds < 2 or len(returns) != len(signals) + 1:
        raise ValueError("chronological fold diagnostics require aligned returns and at least two folds")
    labels = tuple(1 if value > 0 else -1 if value < 0 else 0 for value in returns[1:])
    if len(labels) != len(signals):
        raise ValueError("chronological fold diagnostics require aligned signal labels")
    directional_positive = 0
    counterfactual_positive = 0
    populated = 0
    accuracies: list[Decimal] = []
    counterfactual_accuracies: list[Decimal] = []
    counts: list[int] = []
    for fold in range(folds):
        start = len(signals) * fold // folds
        end = len(signals) * (fold + 1) // folds
        indices = tuple(index for index in range(start, end) if signals[index])
        counts.append(len(indices))
        if not indices:
            accuracies.append(Decimal(0))
            counterfactual_accuracies.append(Decimal(0))
            continue
        populated += 1
        hits = sum(signals[index] == labels[index] for index in indices)
        counterfactual_hits = sum(-signals[index] == labels[index] for index in indices)
        accuracies.append(_ratio(hits, len(indices)))
        counterfactual_accuracies.append(_ratio(counterfactual_hits, len(indices)))
        gross = sum((Decimal(signals[index]) * returns[index + 1] for index in indices), Decimal(0))
        directional_net = gross - per_signal_cost * len(indices)
        counterfactual_net = -gross - per_signal_cost * len(indices)
        directional_positive += directional_net > 0
        counterfactual_positive += counterfactual_net > 0
    if populated == 0:
        positive_ratio = Decimal(0)
        counterfactual_ratio = Decimal(0)
    else:
        positive_ratio = _ratio(directional_positive, populated)
        counterfactual_ratio = _ratio(counterfactual_positive, populated)
    return ChronologicalFoldDiagnostics(
        positive_ratio,
        counterfactual_ratio,
        tuple(accuracies),
        tuple(counterfactual_accuracies),
        tuple(counts),
    )


def _chronological_positive_fold_ratios(
    signals: tuple[int, ...],
    returns: tuple[Decimal, ...],
    per_signal_cost: Decimal,
    *,
    folds: int,
) -> tuple[Decimal, Decimal]:
    diagnostics = chronological_fold_diagnostics(signals, returns, per_signal_cost, folds=folds)
    return diagnostics.positive_fold_ratio, diagnostics.counterfactual_positive_fold_ratio


def _metric_map(execution: ToolExecutionRecord) -> dict[str, str]:
    if not isinstance(execution.result, Mapping):
        raise TypeError("Critic tool result must be a mapping")
    metrics = execution.result.get("metrics")
    if type(metrics) is not tuple:
        raise TypeError("Critic metrics must be immutable pairs")
    mapped: dict[str, str] = {}
    for pair in metrics:
        if type(pair) is not tuple or len(pair) != 2 or any(type(value) is not str for value in pair):
            raise TypeError("Critic metric pair is malformed")
        key, value = cast(tuple[str, str], pair)
        if key in mapped:
            raise ValueError("Critic metrics must be unique")
        mapped[key] = value
    return mapped


def _metric_text(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.00000001")), "f")
    return str(value)


def _close(record: PointInTimeRecord) -> Decimal | None:
    value = record.values.get("close")
    return None if value is None else Decimal(str(value))


def _ratio(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)


def _record_payload(record: PointInTimeRecord) -> JsonValue:
    return {
        "event_time": record.event_time.to_dict()["recorded_at"],
        "available_time": record.available_time.to_dict()["recorded_at"],
        "values": cast(JsonValue, dict(record.values)),
    }


__all__ = [
    "ChronologicalFoldDiagnostics",
    "MVP_R_REPLAY_CLASSIFIER",
    "ReplayCritique",
    "ReplayEpisodeCandidate",
    "chronological_fold_diagnostics",
    "critique_replay_conclusion",
    "issue_replay_tool_results",
    "stratified_replay_candidates",
]
