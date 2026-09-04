"""Per-fold signal accuracy helpers. positive_fold_ratio must not substitute."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisSpec,
    ResearchFinalVerdict,
)
from futures_agent_os.research_experiment.mvp_r_004.contracts import CONTROL_METRIC_BY_PRIMARY
from futures_agent_os.research_experiment.mvp_r_004.metrics import packet_metric_map, resolve_registered_metrics

from .contracts import (
    FOLD_SIGNAL_ACCURACY_FIELDS,
    FOLD_SIGNAL_COUNT_FIELDS,
    DecisionBrief,
)
from futures_agent_os.research_experiment.walk_forward import WALK_FORWARD_ACCURACY_SOURCE

NEED_MORE_DATA_RATIONALE = (
    "Registered falsification requires per-fold signal_accuracy, but fold_1_signal_accuracy, "
    "fold_2_signal_accuracy and fold_3_signal_accuracy cannot be evaluated from this packet. "
    "positive_fold_ratio is net-positive fold share and must not substitute."
)
NEED_MORE_DATA_JUDGMENT = "结果包无法按登记的分段命中率做判断，不能用盈利分段比例代替，因此需要更多数据。"


def requires_per_fold_signal_accuracy(condition: str) -> bool:
    if type(condition) is not str or not condition.strip():
        raise ValueError("falsification condition requires non-empty text")
    lowered = condition.lower()
    named = all(name in lowered for name in FOLD_SIGNAL_ACCURACY_FIELDS)
    chinese = "分段" in condition and ("命中" in condition or "signal_accuracy" in lowered)
    per_fold = "per-fold" in lowered and "signal_accuracy" in lowered
    return named or chinese or per_fold


def fold_signal_accuracy_map(packet: ExperimentResultPacket) -> dict[str, str]:
    metrics = packet_metric_map(packet)
    return {name: metrics[name] for name in FOLD_SIGNAL_ACCURACY_FIELDS if name in metrics}


def packet_has_fold_signal_accuracies(packet: ExperimentResultPacket) -> bool:
    metrics = packet_metric_map(packet)
    return all(name in metrics for name in FOLD_SIGNAL_ACCURACY_FIELDS)


def packet_can_evaluate_per_fold_accuracy(packet: ExperimentResultPacket) -> bool:
    metrics = packet_metric_map(packet)
    if not all(name in metrics for name in (*FOLD_SIGNAL_ACCURACY_FIELDS, *FOLD_SIGNAL_COUNT_FIELDS)):
        return False
    return all(Decimal(metrics[name]) >= 1 for name in FOLD_SIGNAL_COUNT_FIELDS)


def apply_need_more_data_guard(
    verdict: ResearchFinalVerdict,
    brief: DecisionBrief,
    hypothesis: HypothesisSpec,
    packet: ExperimentResultPacket,
) -> tuple[ResearchFinalVerdict, DecisionBrief, bool]:
    if type(verdict) is not ResearchFinalVerdict or type(brief) is not DecisionBrief:
        raise TypeError("need-more-data guard requires exact verdict and brief")
    if type(hypothesis) is not HypothesisSpec:
        raise TypeError("need-more-data guard requires an exact HypothesisSpec")
    if not requires_per_fold_signal_accuracy(hypothesis.falsification_condition):
        return verdict, brief, False
    if packet_can_evaluate_per_fold_accuracy(packet):
        return verdict, brief, False
    forced = replace(
        verdict,
        verdict=FinalVerdict.NEED_MORE_DATA,
        modified_hypothesis=None,
        rationale=NEED_MORE_DATA_RATIONALE,
    )
    forced_brief = DecisionBrief(
        brief.what_was_tested,
        brief.results,
        NEED_MORE_DATA_JUDGMENT,
        brief.next_action,
        FinalVerdict.NEED_MORE_DATA,
    )
    return forced, forced_brief, True


def resolve_treatment_relative_metrics(hypothesis: HypothesisSpec, source: object) -> dict[str, str]:
    from .treatment_view import TreatmentMetricView

    if type(source) is TreatmentMetricView:
        if source.hypothesis_ref != hypothesis.identity:
            raise ValueError("treatment view does not bind the selected hypothesis")
        if source.treatment_direction != dict(hypothesis.parameters).get("direction"):
            raise ValueError("treatment view direction does not bind hypothesis direction")
        if source.raw_computation_direction != "FOLLOW":
            raise ValueError("raw deterministic tool lineage must remain FOLLOW")
        metrics = source.metric_map
        control_metric = dict(CONTROL_METRIC_BY_PRIMARY)[hypothesis.primary_metric]
        if hypothesis.primary_metric not in metrics or control_metric not in metrics:
            raise ValueError("treatment view is missing the hypothesis primary or control metric")
        resolved = {
            "primary_metric": hypothesis.primary_metric,
            "primary_value": metrics[hypothesis.primary_metric],
            "control": hypothesis.control,
            "control_metric": control_metric,
            "control_value": metrics[control_metric],
        }
        return {
            **resolved,
            "treatment_direction": source.treatment_direction,
            "raw_computation_direction": "FOLLOW",
            "hypothesis_ref": hypothesis.identity,
        }
    if type(source) is not ExperimentResultPacket:
        raise TypeError("metric resolver requires a packet or treatment view")
    resolved = resolve_registered_metrics(hypothesis, source)
    metrics = packet_metric_map(source)
    direction = dict(hypothesis.parameters).get("direction")
    if metrics.get("treatment_direction") != direction:
        raise ValueError("packet treatment_direction does not bind hypothesis direction")
    if metrics.get("hypothesis_ref") != hypothesis.identity:
        raise ValueError("packet hypothesis_ref does not bind the selected hypothesis")
    if metrics.get("plan_hypothesis_ref") != hypothesis.identity:
        raise ValueError("packet plan_hypothesis_ref does not exact-bind the selected hypothesis")
    if metrics.get("raw_computation_direction") != "FOLLOW":
        raise ValueError("raw deterministic tool lineage must remain FOLLOW")
    return {
        **resolved,
        "treatment_direction": str(direction),
        "raw_computation_direction": "FOLLOW",
        "hypothesis_ref": hypothesis.identity,
    }


def packet_has_authentic_walk_forward(packet: ExperimentResultPacket, *, test_bars: int = 5) -> bool:
    return metrics_have_authentic_walk_forward(packet_metric_map(packet), test_bars=test_bars)


def metrics_have_authentic_walk_forward(metrics: dict[str, str], *, test_bars: int = 5) -> bool:
    if metrics.get("fold_signal_accuracy_source") != WALK_FORWARD_ACCURACY_SOURCE:
        return False
    if "fold_manifest" not in metrics or "fold_count" not in metrics:
        return False
    fold_count = int(metrics["fold_count"])
    if fold_count < 0:
        return False
    if f"fold_{fold_count + 1}_signal_accuracy" in metrics:
        return False
    counts: list[int] = []
    for index in range(1, fold_count + 1):
        count_name = f"fold_{index}_signal_count"
        accuracy_name = f"fold_{index}_signal_accuracy"
        if count_name not in metrics or accuracy_name not in metrics:
            return False
        count = int(metrics[count_name])
        if count > test_bars:
            return False
        counts.append(count)
    if counts == [12, 13, 13]:
        return False
    return True


def fold_metrics_bound_to_manifest(packet: ExperimentResultPacket, *, test_bars: int = 5) -> bool:
    return metrics_bound_to_fold_manifest(packet_metric_map(packet), test_bars=test_bars)


def metrics_bound_to_fold_manifest(metrics: dict[str, str], *, test_bars: int = 5) -> bool:
    import json

    if not metrics_have_authentic_walk_forward(metrics, test_bars=test_bars):
        return False
    loaded = json.loads(metrics["fold_manifest"])
    if type(loaded) is not list:
        return False
    fold_count = int(metrics["fold_count"])
    if len(loaded) != fold_count:
        return False
    for index, row in enumerate(loaded, start=1):
        if type(row) is not dict:
            return False
        if int(row["fold_index"]) != index:
            return False
        if int(row["signal_count"]) != int(metrics[f"fold_{index}_signal_count"]):
            return False
        if int(row["signal_count"]) > test_bars or int(row["test_bars"]) > test_bars:
            return False
        if int(row["test_end_index"]) - int(row["test_start_index"]) != int(row["test_bars"]):
            return False
    return True


def packet_direction_bound(hypothesis: HypothesisSpec, packet: ExperimentResultPacket) -> bool:
    try:
        resolve_treatment_relative_metrics(hypothesis, packet)
    except TypeError, ValueError:
        return False
    return True


def view_direction_bound(hypothesis: HypothesisSpec, source: object) -> bool:
    try:
        resolve_treatment_relative_metrics(hypothesis, source)
    except TypeError, ValueError, KeyError:
        return False
    return True


def packet_treatment_control_mirror(packet: ExperimentResultPacket) -> bool:
    return metrics_treatment_control_mirror(packet_metric_map(packet))


def metrics_treatment_control_mirror(metrics: dict[str, str]) -> bool:
    direction = metrics.get("treatment_direction")
    if direction not in {"FOLLOW", "INVERT"}:
        return False
    pairs = (
        ("signal_accuracy", "counterfactual_signal_accuracy"),
        ("proxy_net_return", "counterfactual_net_return"),
        ("stressed_net_return", "counterfactual_stressed_net_return"),
    )
    for treatment, control in pairs:
        raw_follow = metrics.get(f"raw_follow_{treatment}")
        raw_invert = metrics.get(f"raw_invert_{treatment}")
        if treatment not in metrics or raw_follow is None or raw_invert is None:
            return False
        if direction == "FOLLOW":
            if metrics[treatment] != raw_follow or metrics.get(control) != raw_invert:
                return False
        elif metrics[treatment] != raw_invert or metrics.get(control) != raw_follow:
            return False
    fold_count = int(metrics.get("fold_count", "0"))
    for index in range(1, fold_count + 1):
        treatment = f"fold_{index}_signal_accuracy"
        control = f"fold_{index}_counterfactual_signal_accuracy"
        raw_follow = metrics.get(f"raw_follow_{treatment}")
        raw_invert = metrics.get(f"raw_invert_{treatment}")
        if treatment not in metrics:
            continue
        if raw_follow is None or raw_invert is None:
            return False
        if direction == "FOLLOW":
            if metrics[treatment] != raw_follow or metrics.get(control) != raw_invert:
                return False
        elif metrics[treatment] != raw_invert or metrics.get(control) != raw_follow:
            return False
    return True
