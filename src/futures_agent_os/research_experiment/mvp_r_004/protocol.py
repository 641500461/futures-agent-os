"""Deterministic validation/protocol digest shown to Research and Critic."""

from __future__ import annotations

from futures_agent_os.research_experiment.validation_tools import ValidationConfig

from .contracts import CONTROL_METRIC_BY_PRIMARY, PACKET_PRIMARY_METRICS, ValidationProtocolDigest

_PIT_PROTOCOL = (
    "available_time <= as_of; market_cutoff <= as_of; agent payloads exclude evaluator-only future bars; "
    "unadjusted dominant-contract rolls are disclosed rather than treated as missing data"
)
_MULTIPLE_TESTING_BUDGET = (
    "at most three hypotheses per episode; at most one selected experiment; "
    "primary metric and inverted-direction control must be chosen from the frozen ResultPacket map; "
    "no post-hoc metric switch after seeing results"
)
_KNOWN_LIMITATIONS = (
    "dominant-contract component rolls are not back-adjusted",
    "L1 uses close-to-next-open directional approximation without fill semantics",
    "intraday path and execution are unavailable",
    "walk-forward uses authentic OOS test windows from train_bars/test_bars/step_bars/embargo_bars, not equal-length partitions of full-window signals",
    "minimum_samples constrains train_bars/full-window eligibility, not OOS sample count",
)


def build_validation_protocol_digest(
    config: ValidationConfig,
    *,
    sample_count: int,
    fold_count: int = 3,
    embargo_bars: int = 1,
) -> ValidationProtocolDigest:
    if type(config) is not ValidationConfig:
        raise TypeError("protocol digest requires the existing V1-010 ValidationConfig")
    return ValidationProtocolDigest(
        window_bars=sample_count,
        train_bars=config.train_bars,
        test_bars=config.test_bars,
        step_bars=config.step_bars,
        embargo_bars=embargo_bars,
        sample_count=sample_count,
        minimum_samples=config.minimum_samples,
        fold_count=fold_count,
        stop_after_failures=config.stop_after_failures,
        round_trip_cost_bps=format(config.round_trip_cost_bps, "f"),
        slippage_bps=format(config.slippage_bps, "f"),
        stress_multipliers=tuple(format(item, "f") for item in config.stress_multipliers),
        signal_threshold=format(config.signal_threshold, "f"),
        pit_protocol=_PIT_PROTOCOL,
        multiple_testing_budget=_MULTIPLE_TESTING_BUDGET,
        packet_primary_metrics=PACKET_PRIMARY_METRICS,
        control_metric_by_primary=CONTROL_METRIC_BY_PRIMARY,
        known_limitations=_KNOWN_LIMITATIONS,
    )
