"""MVP-R-004 measurement repair: numeric evidence, protocol digest, packet metrics, gold labels."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    ToolRunResult,
    ValidationStatus,
)
from futures_agent_os.research_experiment.mvp_r_003.hypothesis_validator import HypothesisValidator
from futures_agent_os.research_experiment.mvp_r_004 import (
    CanaryEpisodeOutcome,
    DiscoveryEpisodeOutcome,
    LabeledCriticOutcome,
    MvpR004HypothesisValidator,
    compute_canary_gate,
    compute_discovery_gate,
    gold_retention_recall,
    packet_metric_map,
    resolve_registered_metrics,
)
from futures_agent_os.research_experiment.mvp_r_004.contracts import GoldLabel, ResearchEvidenceBundle
from futures_agent_os.research_experiment.mvp_r_004.evidence import build_research_evidence_bundle
from futures_agent_os.research_experiment.mvp_r_004.gold_labels import gold_cases
from futures_agent_os.research_experiment.mvp_r_004.protocol import build_validation_protocol_digest
from futures_agent_os.research_experiment.validation_tools import ValidationConfig
from futures_agent_os.shared_kernel import RecordedAt
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id

sys.path.insert(0, str(Path(__file__).parent))
from test_mvp_r_003_contracts import episode, hypothesis, plan  # noqa: E402


def _records() -> tuple[PointInTimeRecord, ...]:
    start = RecordedAt.parse("2026-04-01T07:00:00Z")
    bars = []
    for index in range(40):
        event = RecordedAt(start.value + timedelta(days=index))
        close = Decimal("100") + Decimal(index)
        bars.append(
            PointInTimeRecord(
                event,
                event,
                {
                    "close": format(close, "f"),
                    "volume": "10",
                    "open_interest": "20",
                    "component_instrument": "AG2606" if index < 20 else "AG2608",
                },
            )
        )
    return tuple(bars)


def _packet() -> ExperimentResultPacket:
    metrics = {
        "l0_signal_test": (("signal_accuracy", "0.60000000"), ("counterfactual_signal_accuracy", "0.40000000")),
        "l1_bar_backtest": (
            ("proxy_net_return", "0.01000000"),
            ("counterfactual_net_return", "-0.01200000"),
            ("stressed_net_return", "0.00400000"),
            ("counterfactual_stressed_net_return", "-0.01800000"),
            ("positive_fold_ratio", "0.66666667"),
            ("counterfactual_positive_fold_ratio", "0.33333333"),
        ),
        "walk_forward_test": (("positive_fold_ratio", "0.66666667"), ("fold_count", "3")),
        "cost_slippage_stress": (("stressed_net_return", "0.00400000"),),
        "counterfactual_test": (("counterfactual_net_return", "-0.01200000"),),
    }
    runs = tuple(
        ToolRunResult(tool, "SUCCESS", metrics[tool], (), ("market-snapshot://b",)) for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-r004",
        plan_ref=plan().identity,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def test_evidence_bundle_contains_numeric_bars_and_rejects_future() -> None:
    records = _records()
    bundle = build_research_evidence_bundle(
        episode_id="r004-canary-ag-uptrend",
        instrument="SHFE.AG.DOMINANT_OI",
        market_cutoff=records[-1].event_time.to_dict()["recorded_at"],
        as_of=records[-1].available_time.to_dict()["recorded_at"],
        market_state="UP_TREND",
        records=records,
    )
    assert len(bundle.bars) == 40
    assert bundle.bars[-1].close == "139"
    assert bundle.future_bars_included is False
    assert ResearchEvidenceBundle.hydrate(bundle.to_dict()) == bundle
    with pytest.raises(ValueError, match="market_cutoff"):
        replace(bundle, market_cutoff="2026-03-01T07:00:00Z")


def test_protocol_digest_freezes_costs_samples_folds_and_packet_metrics() -> None:
    config = ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-004", "test": 1}),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.00010000"),
        Decimal("2.0"),
        Decimal("1.0"),
        (Decimal("1.0"), Decimal("2.0")),
        2,
    )
    digest = build_validation_protocol_digest(config, sample_count=40)
    assert digest.sample_count == 40
    assert digest.fold_count == 3
    assert digest.round_trip_cost_bps.startswith("2")
    assert "signal_accuracy" in digest.packet_primary_metrics
    assert ("proxy_net_return", "counterfactual_net_return") in digest.control_metric_by_primary
    assert type(digest).hydrate(digest.to_dict()) == digest


def test_primary_metric_must_exist_on_result_packet() -> None:
    packet = _packet()
    mapped = packet_metric_map(packet)
    assert "signal_accuracy" in mapped
    assert "net_directional_mean" not in mapped
    clean = replace(hypothesis(), primary_metric="signal_accuracy")
    resolved = resolve_registered_metrics(clean, packet)
    assert resolved["control_metric"] == "counterfactual_signal_accuracy"
    with pytest.raises(ValueError, match="ResultPacket field"):
        resolve_registered_metrics(replace(hypothesis(), primary_metric="net_directional_mean"), packet)


def test_r004_validator_rejects_v1_metric_alias_and_gold_bad_case() -> None:
    source = episode()
    v1 = HypothesisValidator().validate(source, hypothesis())
    assert v1.status is ValidationStatus.EXECUTABLE
    repaired = MvpR004HypothesisValidator().validate(source, hypothesis())
    assert repaired.status is ValidationStatus.UNSUPPORTED
    assert "PRIMARY_METRIC_NOT_IN_RESULT_PACKET" in repaired.reason_codes
    clean, bad = gold_cases(source, "0.010")
    assert MvpR004HypothesisValidator().validate(source, clean.hypothesis).status is ValidationStatus.EXECUTABLE
    assert MvpR004HypothesisValidator().validate(source, bad.hypothesis).status is ValidationStatus.UNSUPPORTED


def test_canary_gate_is_computed_from_gold_labels_not_hardcoded() -> None:
    labeled = (
        LabeledCriticOutcome("a", GoldLabel.CLEAN, "SELECT", "SELECT"),
        LabeledCriticOutcome("a", GoldLabel.BAD, "REJECT", "REJECT"),
        LabeledCriticOutcome("b", GoldLabel.CLEAN, "SELECT", "DEFER"),
        LabeledCriticOutcome("b", GoldLabel.BAD, "REJECT", "REJECT"),
    )
    gold = gold_retention_recall(labeled)
    assert gold["clean_retention"] == "1/2"
    assert gold["clean_retention_pass"] is False
    episodes = (
        CanaryEpisodeOutcome("a", "AG", "UP_TREND", "SELECT", "REJECT", True, True, True, 2),
        CanaryEpisodeOutcome("b", "SR", "FALSE_BREAKOUT", "DEFER", "REJECT", False, False, False, 2),
    )
    gate = compute_canary_gate(episodes, labeled)
    assert gate["hardcoded"] is False
    assert gate["decision"] == "CANARY_FAIL"
    passing = (
        CanaryEpisodeOutcome("a", "AG", "UP_TREND", "SELECT", "REJECT", True, True, True, 2),
        CanaryEpisodeOutcome("b", "SR", "FALSE_BREAKOUT", "SELECT", "REJECT", True, True, True, 2),
    )
    passing_labels = (
        LabeledCriticOutcome("a", GoldLabel.CLEAN, "SELECT", "SELECT"),
        LabeledCriticOutcome("a", GoldLabel.BAD, "REJECT", "REJECT"),
        LabeledCriticOutcome("b", GoldLabel.CLEAN, "SELECT", "SELECT"),
        LabeledCriticOutcome("b", GoldLabel.BAD, "REJECT", "REJECT"),
    )
    assert compute_canary_gate(passing, passing_labels)["decision"] == "CANARY_PASS"


def test_discovery_gate_is_computed_from_gold_labels_not_hardcoded() -> None:

    def episode(
        episode_id: str,
        *,
        gold_clean: str,
        gold_bad: str,
        repaired: bool = False,
        full: bool = True,
        selected: int = 1,
        selected_run: int = 1,
        template: str = "REJECT",
        single: str = "ACCEPT",
    ) -> DiscoveryEpisodeOutcome:
        return DiscoveryEpisodeOutcome(
            episode_id,
            "SHFE.AG.DOMINANT_OI",
            "UP_TREND",
            "2026-01-01T00:00:00Z",
            repaired,
            True,
            2,
            gold_clean,
            gold_bad,
            True,
            full,
            selected,
            selected_run,
            template,
            single,
            "REJECT",
            "ACCEPT" if full else "NO_EXPERIMENT_CRITIC_SELECTED_NONE",
            2,
        )

    labeled = tuple(
        outcome
        for index in range(8)
        for outcome in (
            LabeledCriticOutcome(f"e{index}", GoldLabel.CLEAN, "SELECT", "SELECT"),
            LabeledCriticOutcome(f"e{index}", GoldLabel.BAD, "REJECT", "REJECT"),
        )
    )
    passing = tuple(episode(f"e{index}", gold_clean="SELECT", gold_bad="REJECT") for index in range(8))
    gate = compute_discovery_gate(passing, labeled)
    assert gate["hardcoded"] is False
    assert gate["decision"] == "DISCOVERY_PASS"
    assert gate["user_blind_eval"] == "NOT_STARTED"
    assert gate["clean_retention_pass"] is True
    two_selects = tuple(
        episode(f"e{index}", gold_clean="SELECT", gold_bad="REJECT", selected=2, selected_run=1) for index in range(8)
    )
    assert compute_discovery_gate(two_selects, labeled)["decision"] == "DISCOVERY_PASS"
    failing_labels = labeled[:-1] + (LabeledCriticOutcome("e7", GoldLabel.BAD, "REJECT", "SELECT"),)
    failing = tuple(
        episode(f"e{index}", gold_clean="SELECT", gold_bad="SELECT" if index == 7 else "REJECT") for index in range(8)
    )
    failed = compute_discovery_gate(failing, failing_labels)
    assert failed["decision"] == "DISCOVERY_FAIL"
    assert failed["hardcoded"] is False
    assert "gold BAD hypotheses were selected into experiments" in failed["decision_reasons"]
