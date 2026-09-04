"""Treatment-relative metric view. Raw ToolRunResult values stay untransformed."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import ClassVar, Mapping

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    HypothesisSpec,
    _Contract,
    _bool,
    _digest,
    _exact_keys,
    _integer,
    _mapping,
    _pairs,
    _sequence,
    _strings,
    _text,
)
from futures_agent_os.research_experiment.mvp_r_003.treatment_binding import (
    apply_treatment_stop_rule,
    assert_follow_identity,
    assert_invert_mirror,
    hypothesis_direction,
    merge_tool_metrics,
    metric_owners,
    raw_audit_fields,
    swap_treatment_control,
    treatment_control_pairs,
    unique_metric_pairs,
)
from futures_agent_os.research_experiment.validation_tools import ValidationConfig, semantic_entity_id
from futures_agent_os.shared_kernel.observability import JsonValue

TREATMENT_VIEW_SCHEMA_VERSION = "mvp-r-005.treatment-metric-view.v1"
_METADATA_KEYS = {
    "treatment_direction",
    "raw_computation_direction",
    "hypothesis_ref",
    "plan_hypothesis_ref",
    "planned_fold_count",
    "stopped_early",
    "oos_signal_count",
    "full_window_signal_count",
    "fold_count",
    "fold_manifest",
    "fold_signal_accuracy_source",
    "config_sha256",
    "test_bars",
}


@dataclass(frozen=True, slots=True)
class TreatmentMetricLineage:
    metric: str
    value: str
    raw_metric: str
    raw_tool: str
    raw_source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.metric, "lineage metric")
        _text(self.value, "lineage value")
        _text(self.raw_metric, "lineage raw metric")
        _text(self.raw_tool, "lineage raw tool")
        _strings(self.raw_source_refs, "lineage source refs")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "metric": self.metric,
            "value": self.value,
            "raw_metric": self.raw_metric,
            "raw_tool": self.raw_tool,
            "raw_source_refs": self.raw_source_refs,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> TreatmentMetricLineage:
        _exact_keys(value, {"metric", "value", "raw_metric", "raw_tool", "raw_source_refs"}, "metric lineage")
        return cls(
            _text(value["metric"], "lineage metric"),
            _text(value["value"], "lineage value"),
            _text(value["raw_metric"], "lineage raw metric"),
            _text(value["raw_tool"], "lineage raw tool"),
            _strings(value["raw_source_refs"], "lineage source refs"),
        )


@dataclass(frozen=True, slots=True)
class TreatmentMetricView(_Contract):
    schema_version: ClassVar[str] = TREATMENT_VIEW_SCHEMA_VERSION

    view_id: str
    raw_packet_ref: str
    raw_packet_digest: str
    plan_ref: str
    hypothesis_ref: str
    treatment_direction: str
    raw_computation_direction: str
    metrics: tuple[tuple[str, str], ...]
    lineage: tuple[TreatmentMetricLineage, ...]
    planned_fold_count: int
    fold_count: int
    stopped_early: bool
    config_digest: str
    minimum_signal_accuracy: str
    stop_after_failures: int
    test_bars: int

    def __post_init__(self) -> None:
        _text(self.view_id, "view id")
        _text(self.raw_packet_ref, "raw packet ref")
        _digest(self.raw_packet_digest)
        _text(self.plan_ref, "plan ref")
        _text(self.hypothesis_ref, "hypothesis ref")
        if self.treatment_direction not in {"FOLLOW", "INVERT"}:
            raise ValueError("treatment direction must be FOLLOW or INVERT")
        if self.raw_computation_direction != "FOLLOW":
            raise ValueError("raw computation direction must remain FOLLOW")
        unique_metric_pairs(self.metrics)
        if any(type(item) is not TreatmentMetricLineage for item in self.lineage):
            raise TypeError("treatment view lineage must be exact")
        if self.planned_fold_count < 0 or self.fold_count < 0:
            raise ValueError("fold counts cannot be negative")
        if self.fold_count > self.planned_fold_count:
            raise ValueError("evaluated fold count cannot exceed planned fold count")
        _bool(self.stopped_early, "stopped early")
        _digest(self.config_digest)
        Decimal(self.minimum_signal_accuracy)
        if type(self.stop_after_failures) is not int or self.stop_after_failures < 1:
            raise ValueError("stop_after_failures must be a positive integer")
        if type(self.test_bars) is not int or self.test_bars < 1:
            raise ValueError("test_bars must be a positive integer")
        self._assert_no_stopped_fold_fields()

    def _assert_no_stopped_fold_fields(self) -> None:
        metric_map = dict(self.metrics)
        for index in range(self.fold_count + 1, self.planned_fold_count + 1):
            token = f"fold_{index}_"
            leaked = tuple(
                name
                for name in metric_map
                if token in name or name.startswith(f"raw_follow_{token}") or name.startswith(f"raw_invert_{token}")
            )
            if leaked:
                raise ValueError(f"treatment view leaked stopped fold fields: {','.join(leaked)}")

    @property
    def identity(self) -> str:
        return f"treatment-metric-view://{self.view_id}/{self.content_sha256}"

    @property
    def metric_map(self) -> dict[str, str]:
        return dict(self.metrics)

    def payload(self) -> dict[str, JsonValue]:
        return {
            "view_id": self.view_id,
            "raw_packet_ref": self.raw_packet_ref,
            "raw_packet_digest": self.raw_packet_digest,
            "plan_ref": self.plan_ref,
            "hypothesis_ref": self.hypothesis_ref,
            "treatment_direction": self.treatment_direction,
            "raw_computation_direction": self.raw_computation_direction,
            "metrics": self.metrics,
            "lineage": tuple(item.to_dict() for item in self.lineage),
            "planned_fold_count": self.planned_fold_count,
            "fold_count": self.fold_count,
            "stopped_early": self.stopped_early,
            "config_digest": self.config_digest,
            "minimum_signal_accuracy": self.minimum_signal_accuracy,
            "stop_after_failures": self.stop_after_failures,
            "test_bars": self.test_bars,
        }

    def agent_visible_dict(self) -> dict[str, JsonValue]:
        return self.to_dict()

    def stopped_fold_indices(self) -> tuple[int, ...]:
        return tuple(range(self.fold_count + 1, self.planned_fold_count + 1))

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> TreatmentMetricView:
        required = {
            "schema_version",
            "view_id",
            "raw_packet_ref",
            "raw_packet_digest",
            "plan_ref",
            "hypothesis_ref",
            "treatment_direction",
            "raw_computation_direction",
            "metrics",
            "lineage",
            "planned_fold_count",
            "fold_count",
            "stopped_early",
            "config_digest",
            "minimum_signal_accuracy",
            "stop_after_failures",
            "test_bars",
            "content_sha256",
        }
        _exact_keys(value, required, "treatment metric view")
        instance = cls(
            view_id=_text(value["view_id"], "view id"),
            raw_packet_ref=_text(value["raw_packet_ref"], "raw packet ref"),
            raw_packet_digest=_digest(_text(value["raw_packet_digest"], "raw packet digest")),
            plan_ref=_text(value["plan_ref"], "plan ref"),
            hypothesis_ref=_text(value["hypothesis_ref"], "hypothesis ref"),
            treatment_direction=_text(value["treatment_direction"], "treatment direction"),
            raw_computation_direction=_text(value["raw_computation_direction"], "raw computation direction"),
            metrics=_pairs(value["metrics"], "view metrics"),
            lineage=tuple(
                TreatmentMetricLineage.hydrate(_mapping(item, "lineage"))
                for item in _sequence(value["lineage"], "lineage")
            ),
            planned_fold_count=_nonnegative_int(value["planned_fold_count"], "planned fold count"),
            fold_count=_nonnegative_int(value["fold_count"], "fold count"),
            stopped_early=_bool(value["stopped_early"], "stopped early"),
            config_digest=_digest(_text(value["config_digest"], "config digest")),
            minimum_signal_accuracy=_text(value["minimum_signal_accuracy"], "minimum signal accuracy"),
            stop_after_failures=_integer(value["stop_after_failures"], "stop after failures"),
            test_bars=_integer(value["test_bars"], "test bars"),
        )
        return cls._verify_hash(value, instance)


def build_treatment_metric_view(
    packet: ExperimentResultPacket,
    *,
    hypothesis: HypothesisSpec,
    plan: ExecutableExperimentPlan,
    config: ValidationConfig,
) -> TreatmentMetricView:
    if type(packet) is not ExperimentResultPacket:
        raise TypeError("treatment view requires an exact ExperimentResultPacket")
    if type(hypothesis) is not HypothesisSpec:
        raise TypeError("treatment view requires an exact HypothesisSpec")
    if type(plan) is not ExecutableExperimentPlan:
        raise TypeError("treatment view requires an exact ExecutableExperimentPlan")
    if type(config) is not ValidationConfig:
        raise TypeError("treatment view requires an exact ValidationConfig")
    if hypothesis.identity != plan.hypothesis_ref:
        raise ValueError("experiment plan does not bind the supplied hypothesis")
    if plan.identity != packet.plan_ref:
        raise ValueError("result packet does not bind the supplied plan")
    config_digest = config.content_sha256
    if plan.config_ref != f"validation-config://{config_digest}":
        raise ValueError("experiment plan does not bind the supplied V1-010 config")
    direction = hypothesis_direction(hypothesis)
    merged = merge_tool_metrics(packet.tool_runs)
    if merged.get("treatment_direction") not in {None, "FOLLOW"}:
        raise ValueError("raw ToolRunResult metrics must not already be treatment-swapped")
    owners = metric_owners(packet.tool_runs)
    audit = raw_audit_fields(merged)
    swapped = swap_treatment_control(merged, direction=direction)
    swapped.update(audit)
    stopped = apply_treatment_stop_rule(
        swapped,
        minimum_signal_accuracy=config.minimum_signal_accuracy,
        stop_after_failures=config.stop_after_failures,
    )
    stopped["treatment_direction"] = direction
    stopped["raw_computation_direction"] = "FOLLOW"
    stopped["hypothesis_ref"] = hypothesis.identity
    stopped["plan_hypothesis_ref"] = plan.hypothesis_ref
    if "config_sha256" not in stopped:
        stopped["config_sha256"] = config_digest
    elif stopped["config_sha256"] != config_digest:
        raise ValueError("walk-forward config digest does not bind ValidationConfig")
    if direction == "FOLLOW":
        assert_follow_identity(stopped, audit)
    else:
        assert_invert_mirror(stopped, audit)
    metrics = unique_metric_pairs(tuple(stopped.items()))
    lineage = _lineage(owners, dict(metrics), direction)
    planned = int(stopped.get("planned_fold_count", stopped.get("fold_count", "0")))
    fold_count = int(stopped.get("fold_count", "0"))
    stopped_early = stopped.get("stopped_early") == "true"
    seed = {
        "raw_packet": packet.content_sha256,
        "plan": plan.content_sha256,
        "hypothesis": hypothesis.identity,
        "direction": direction,
        "schema": TREATMENT_VIEW_SCHEMA_VERSION,
    }
    view_id = f"mvp-r-005-{semantic_entity_id('treatment_metric_view', seed).value}"
    return TreatmentMetricView(
        view_id=view_id,
        raw_packet_ref=packet.identity,
        raw_packet_digest=packet.content_sha256,
        plan_ref=plan.identity,
        hypothesis_ref=hypothesis.identity,
        treatment_direction=direction,
        raw_computation_direction="FOLLOW",
        metrics=metrics,
        lineage=lineage,
        planned_fold_count=planned,
        fold_count=fold_count,
        stopped_early=stopped_early,
        config_digest=config_digest,
        minimum_signal_accuracy=format(config.minimum_signal_accuracy, "f"),
        stop_after_failures=config.stop_after_failures,
        test_bars=config.test_bars,
    )


def view_has_stopped_fold_leak(view: TreatmentMetricView, serialized: str) -> bool:
    if type(view) is not TreatmentMetricView:
        raise TypeError("stopped-fold leak check requires an exact TreatmentMetricView")
    if type(serialized) is not str:
        raise TypeError("stopped-fold leak check requires serialized text")
    for index in view.stopped_fold_indices():
        token = f"fold_{index}_"
        if token in serialized or f"raw_follow_fold_{index}" in serialized or f"raw_invert_fold_{index}" in serialized:
            return True
        if f'"fold_index": {index}' in serialized or f'"fold_index":{index}' in serialized:
            return True
    return False


def raw_tool_runs_untransformed(packet: ExperimentResultPacket) -> bool:
    metrics = merge_tool_metrics(packet.tool_runs)
    if metrics.get("treatment_direction") in {"INVERT"}:
        return False
    if any(name.startswith("raw_follow_") or name.startswith("raw_invert_") for name in metrics):
        return False
    return True


def expected_treatment_metric_lineage(
    packet: ExperimentResultPacket,
    view: TreatmentMetricView,
) -> tuple[TreatmentMetricLineage, ...]:
    """Rebuild exact packet-to-view lineage without asserting source authenticity."""
    if type(packet) is not ExperimentResultPacket or type(view) is not TreatmentMetricView:
        raise TypeError("lineage rebuild requires exact packet and treatment view")
    return _lineage(metric_owners(packet.tool_runs), view.metric_map, view.treatment_direction)


def _lineage(
    owners: dict[str, tuple[str, tuple[str, ...], str]],
    view_metrics: dict[str, str],
    direction: str,
) -> tuple[TreatmentMetricLineage, ...]:
    pairs = treatment_control_pairs(set(owners) | set(view_metrics))
    treatment_to_control = dict(pairs)
    control_to_treatment = {control: treatment for treatment, control in pairs}
    rows: list[TreatmentMetricLineage] = []
    for name, value in sorted(view_metrics.items()):
        if name in _METADATA_KEYS or name.startswith("raw_follow_") or name.startswith("raw_invert_"):
            continue
        if name.endswith("_unit"):
            continue
        raw_name = name
        if direction == "INVERT":
            if name in treatment_to_control:
                raw_name = treatment_to_control[name]
            elif name in control_to_treatment:
                raw_name = control_to_treatment[name]
        owner = owners.get(raw_name)
        if owner is None:
            continue
        tool, source_refs, raw_value = owner
        if name in {"positive_fold_ratio", "counterfactual_positive_fold_ratio"}:
            expected = _derived_positive_fold_ratio(view_metrics, name)
            if value != (expected if expected is not None else raw_value):
                raise ValueError(f"derived treatment metric {name} does not match visible folds")
        elif raw_value != value:
            raise ValueError(f"treatment metric {name} does not match mapped raw metric {raw_name}")
        rows.append(
            TreatmentMetricLineage(
                metric=name,
                value=value,
                raw_metric=raw_name,
                raw_tool=tool,
                raw_source_refs=source_refs,
            )
        )
    return tuple(rows)


def _derived_positive_fold_ratio(metrics: dict[str, str], name: str) -> str | None:
    fold_count = int(metrics.get("fold_count", "0"))
    prefix = "counterfactual_" if name == "counterfactual_positive_fold_ratio" else ""
    populated = tuple(
        index for index in range(1, fold_count + 1) if int(metrics.get(f"fold_{index}_signal_count", "0")) > 0
    )
    if not populated:
        return None
    metric_suffix = "counterfactual_net_return" if prefix else "proxy_net_return"
    positive = sum(Decimal(metrics[f"fold_{index}_{metric_suffix}"]) > 0 for index in populated)
    ratio = (Decimal(positive) / Decimal(len(populated))).quantize(Decimal("0.00000001"), ROUND_HALF_EVEN)
    return format(ratio, "f")


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} requires a non-negative integer")
    return value


__all__ = [
    "TREATMENT_VIEW_SCHEMA_VERSION",
    "TreatmentMetricLineage",
    "TreatmentMetricView",
    "build_treatment_metric_view",
    "expected_treatment_metric_lineage",
    "raw_tool_runs_untransformed",
    "view_has_stopped_fold_leak",
]
