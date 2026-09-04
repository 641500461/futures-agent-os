"""Bind HypothesisSpec FOLLOW/INVERT onto treatment-relative ResultPacket metrics."""

from __future__ import annotations

from decimal import Decimal

from futures_agent_os.research_experiment.mvp_r_003.contracts import HypothesisSpec, ToolRunResult
from futures_agent_os.research_experiment.validation_tools import ValidationConfig
from futures_agent_os.shared_kernel import canonical_json_text
from futures_agent_os.shared_kernel.observability import JsonValue

STATIC_TREATMENT_CONTROL_PAIRS = (
    ("signal_accuracy", "counterfactual_signal_accuracy"),
    ("proxy_net_return", "counterfactual_net_return"),
    ("stressed_net_return", "counterfactual_stressed_net_return"),
    ("positive_fold_ratio", "counterfactual_positive_fold_ratio"),
)
_FOLD_ACCURACY_SUFFIX = "_signal_accuracy"
_FOLD_NET_SUFFIX = "_proxy_net_return"
_RECOMPUTED_AFTER_STOP = {"positive_fold_ratio", "counterfactual_positive_fold_ratio"}
_RAW_PREFIX = "raw_follow_"
_RAW_INVERT_PREFIX = "raw_invert_"


def hypothesis_direction(hypothesis: HypothesisSpec) -> str:
    if type(hypothesis) is not HypothesisSpec:
        raise TypeError("direction binding requires an exact HypothesisSpec")
    direction = dict(hypothesis.parameters).get("direction")
    if direction not in {"FOLLOW", "INVERT"}:
        raise ValueError("experiment hypothesis direction must be FOLLOW or INVERT")
    return direction


def treatment_control_pairs(keys: set[str]) -> tuple[tuple[str, str], ...]:
    pairs = list(STATIC_TREATMENT_CONTROL_PAIRS)
    for key in sorted(keys):
        if key.startswith("fold_") and key.endswith(_FOLD_ACCURACY_SUFFIX) and "counterfactual" not in key:
            control = key[: -len(_FOLD_ACCURACY_SUFFIX)] + "_counterfactual_signal_accuracy"
            if control in keys:
                pairs.append((key, control))
        if key.startswith("fold_") and key.endswith(_FOLD_NET_SUFFIX) and "counterfactual" not in key:
            control = key[: -len(_FOLD_NET_SUFFIX)] + "_counterfactual_net_return"
            if control in keys:
                pairs.append((key, control))
    return tuple(pairs)


def swap_treatment_control(metrics: dict[str, str], *, direction: str) -> dict[str, str]:
    if direction not in {"FOLLOW", "INVERT"}:
        raise ValueError("treatment direction must be FOLLOW or INVERT")
    if direction == "FOLLOW":
        return dict(metrics)
    swapped = dict(metrics)
    for treatment, control in treatment_control_pairs(set(metrics)):
        if treatment not in metrics or control not in metrics:
            raise ValueError(f"cannot invert incomplete metric pair {treatment}/{control}")
        swapped[treatment] = metrics[control]
        swapped[control] = metrics[treatment]
    return swapped


def apply_treatment_stop_rule(
    metrics: dict[str, str],
    *,
    minimum_signal_accuracy: Decimal,
    stop_after_failures: int,
) -> dict[str, str]:
    if "fold_count" not in metrics:
        return dict(metrics)
    planned = int(metrics.get("planned_fold_count", metrics["fold_count"]))
    available = int(metrics["fold_count"])
    if planned == 0 or available == 0:
        output = dict(metrics)
        output["planned_fold_count"] = metrics.get("planned_fold_count", "0")
        output["stopped_early"] = "false"
        return output
    failures = 0
    evaluated = 0
    stopped = False
    for index in range(1, available + 1):
        accuracy_key = f"fold_{index}_signal_accuracy"
        if accuracy_key not in metrics:
            raise ValueError(f"walk-forward packet is missing {accuracy_key}")
        accuracy = Decimal(metrics[accuracy_key])
        evaluated = index
        failures = failures + 1 if accuracy < minimum_signal_accuracy else 0
        if failures >= stop_after_failures:
            stopped = True
            break
    output = dict(metrics)
    _pop_stopped_fold_fields(output, planned=max(planned, available), evaluated=evaluated)
    manifest = _trim_fold_manifest(metrics.get("fold_manifest"), evaluated)
    output["fold_count"] = str(evaluated)
    output["planned_fold_count"] = str(planned)
    output["stopped_early"] = "true" if stopped else "false"
    if manifest is not None:
        output["fold_manifest"] = manifest
    remaining = tuple(index for index in range(1, evaluated + 1) if f"fold_{index}_signal_count" in output)
    oos_total = sum(int(output[f"fold_{index}_signal_count"]) for index in remaining)
    output["oos_signal_count"] = str(oos_total)
    populated = tuple(index for index in remaining if int(output[f"fold_{index}_signal_count"]) > 0)
    if populated and all(f"fold_{index}_proxy_net_return" in output for index in populated):
        positive = sum(Decimal(output[f"fold_{index}_proxy_net_return"]) > 0 for index in populated)
        counterfactual_positive = sum(
            Decimal(output[f"fold_{index}_counterfactual_net_return"]) > 0 for index in populated
        )
        output["positive_fold_ratio"] = _ratio_text(positive, len(populated))
        output["counterfactual_positive_fold_ratio"] = _ratio_text(counterfactual_positive, len(populated))
    return output


def bind_tool_runs_to_hypothesis(
    runs: tuple[ToolRunResult, ...],
    *,
    hypothesis: HypothesisSpec,
    plan_hypothesis_ref: str,
    config: ValidationConfig,
) -> tuple[ToolRunResult, ...]:
    """Keep raw ToolRunResult bytes unchanged. Treatment-relative values live on the view."""
    del config
    if hypothesis.identity != plan_hypothesis_ref:
        raise ValueError("experiment plan does not bind the supplied hypothesis")
    hypothesis_direction(hypothesis)
    if any(type(run) is not ToolRunResult for run in runs):
        raise TypeError("hypothesis binding requires exact ToolRunResult values")
    return tuple(
        ToolRunResult(
            tool=run.tool,
            status=run.status,
            metrics=run.metrics,
            warnings=run.warnings,
            source_refs=run.source_refs,
        )
        for run in runs
    )


def merge_tool_metrics(runs: tuple[ToolRunResult, ...]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for run in runs:
        for name, value in run.metrics:
            existing = merged.get(name)
            if existing is not None and existing != value:
                raise ValueError(f"result packet has conflicting values for {name}")
            merged[name] = value
    return merged


def metric_owners(runs: tuple[ToolRunResult, ...]) -> dict[str, tuple[str, tuple[str, ...], str]]:
    owners: dict[str, tuple[str, tuple[str, ...], str]] = {}
    for run in runs:
        for name, value in run.metrics:
            owners[name] = (run.tool, run.source_refs, value)
    return owners


def unique_metric_pairs(pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    merged: dict[str, str] = {}
    for name, value in pairs:
        existing = merged.get(name)
        if existing is not None and existing != value:
            raise ValueError(f"result packet has conflicting values for {name}")
        merged[name] = value
    return tuple(sorted(merged.items()))


def raw_audit_fields(follow_metrics: dict[str, str]) -> dict[str, str]:
    audit: dict[str, str] = {}
    for treatment, control in treatment_control_pairs(set(follow_metrics)):
        audit[f"{_RAW_PREFIX}{treatment}"] = follow_metrics[treatment]
        audit[f"{_RAW_INVERT_PREFIX}{treatment}"] = follow_metrics[control]
    return audit


def assert_follow_identity(metrics: dict[str, str], raw_audit: dict[str, str]) -> None:
    for treatment, control in treatment_control_pairs(set(metrics) | set(raw_audit)):
        if treatment in _RECOMPUTED_AFTER_STOP:
            continue
        raw_follow = raw_audit.get(f"{_RAW_PREFIX}{treatment}")
        raw_invert = raw_audit.get(f"{_RAW_INVERT_PREFIX}{treatment}")
        if raw_follow is None or treatment not in metrics:
            continue
        if metrics[treatment] != raw_follow:
            raise ValueError(f"FOLLOW treatment {treatment} is not the raw FOLLOW metric")
        if control in metrics and raw_invert is not None and metrics[control] != raw_invert:
            raise ValueError(f"FOLLOW control {control} is not the raw INVERT metric")


def assert_invert_mirror(metrics: dict[str, str], raw_audit: dict[str, str]) -> None:
    for treatment, control in treatment_control_pairs(set(metrics) | set(raw_audit)):
        if treatment in _RECOMPUTED_AFTER_STOP:
            continue
        raw_follow = raw_audit.get(f"{_RAW_PREFIX}{treatment}")
        raw_invert = raw_audit.get(f"{_RAW_INVERT_PREFIX}{treatment}")
        if raw_invert is None or treatment not in metrics:
            continue
        if metrics[treatment] != raw_invert:
            raise ValueError(f"INVERT treatment {treatment} is not the raw INVERT metric")
        if control in metrics and raw_follow is not None and metrics[control] != raw_follow:
            raise ValueError(f"INVERT control {control} is not the raw FOLLOW metric")


def _pop_stopped_fold_fields(output: dict[str, str], *, planned: int, evaluated: int) -> None:
    for index in range(evaluated + 1, planned + 1):
        token = f"fold_{index}_"
        for key in tuple(output):
            if key.startswith(token) or key.startswith(f"raw_follow_{token}") or key.startswith(f"raw_invert_{token}"):
                output.pop(key)


def _trim_fold_manifest(raw: str | None, evaluated: int) -> str | None:
    if raw is None:
        return None
    payload = _load_manifest(raw)
    kept = tuple(item for item in payload if int(_require_int(item["fold_index"])) <= evaluated)
    return canonical_json_text(kept)


def _load_manifest(raw: str) -> tuple[dict[str, JsonValue], ...]:
    import json

    loaded = json.loads(raw)
    if type(loaded) is not list:
        raise ValueError("fold_manifest must be a JSON array")
    rows: list[dict[str, JsonValue]] = []
    for item in loaded:
        if type(item) is not dict:
            raise ValueError("fold_manifest entries must be objects")
        rows.append({str(key): _json_value(value) for key, value in item.items()})
    return tuple(rows)


def _require_int(value: JsonValue) -> int:
    if type(value) is not int:
        raise ValueError("fold_manifest fold_index must be an integer")
    return value


def _json_value(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return value  # type: ignore[return-value]
    raise ValueError("fold_manifest values must be canonical JSON scalars")


def _ratio_text(numerator: int, denominator: int) -> str:
    value = Decimal(0) if denominator == 0 else Decimal(numerator) / Decimal(denominator)
    return format(value.quantize(Decimal("0.00000001")), "f")


__all__ = [
    "STATIC_TREATMENT_CONTROL_PAIRS",
    "apply_treatment_stop_rule",
    "assert_follow_identity",
    "assert_invert_mirror",
    "bind_tool_runs_to_hypothesis",
    "hypothesis_direction",
    "merge_tool_metrics",
    "metric_owners",
    "raw_audit_fields",
    "swap_treatment_control",
    "treatment_control_pairs",
    "unique_metric_pairs",
]
