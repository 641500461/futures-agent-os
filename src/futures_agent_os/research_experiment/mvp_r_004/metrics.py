"""Map hypothesis primary/control names onto actual ResultPacket metric fields."""

from __future__ import annotations

from decimal import Decimal

from futures_agent_os.research_experiment.mvp_r_003.contracts import ExperimentResultPacket, HypothesisSpec

from .contracts import CONTROL_METRIC_BY_PRIMARY, PACKET_CONTROL, PACKET_PRIMARY_METRICS


def packet_metric_map(packet: ExperimentResultPacket) -> dict[str, str]:
    if type(packet) is not ExperimentResultPacket:
        raise TypeError("metric map requires an exact ExperimentResultPacket")
    merged: dict[str, str] = {}
    for run in packet.tool_runs:
        for name, value in run.metrics:
            if name.endswith("_unit"):
                continue
            existing = merged.get(name)
            if existing is not None and existing != value:
                raise ValueError(f"result packet has conflicting values for {name}")
            merged[name] = value
    return merged


def control_metric_name(primary_metric: str) -> str:
    mapping = dict(CONTROL_METRIC_BY_PRIMARY)
    if primary_metric not in mapping:
        raise ValueError(f"primary metric {primary_metric} is not a ResultPacket field")
    return mapping[primary_metric]


def resolve_registered_metrics(hypothesis: HypothesisSpec, packet: ExperimentResultPacket) -> dict[str, str]:
    if type(hypothesis) is not HypothesisSpec:
        raise TypeError("metric resolver requires an exact HypothesisSpec")
    if hypothesis.primary_metric not in PACKET_PRIMARY_METRICS:
        raise ValueError("primary metric must be an actual ResultPacket field")
    if hypothesis.control != PACKET_CONTROL:
        raise ValueError("control must be inverted signal direction")
    metrics = packet_metric_map(packet)
    control_name = control_metric_name(hypothesis.primary_metric)
    if hypothesis.primary_metric not in metrics:
        raise ValueError(f"result packet is missing primary metric {hypothesis.primary_metric}")
    if control_name not in metrics:
        raise ValueError(f"result packet is missing control metric {control_name}")
    return {
        "primary_metric": hypothesis.primary_metric,
        "primary_value": metrics[hypothesis.primary_metric],
        "control": hypothesis.control,
        "control_metric": control_name,
        "control_value": metrics[control_name],
    }


def decimal_metrics(packet: ExperimentResultPacket) -> dict[str, Decimal]:
    parsed: dict[str, Decimal] = {}
    for name, value in packet_metric_map(packet).items():
        try:
            parsed[name] = Decimal(value)
        except Exception:
            continue
    return parsed
