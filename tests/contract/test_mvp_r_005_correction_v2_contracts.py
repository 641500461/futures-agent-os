"""MVP-R-005 correction-v2: direction binding, authentic OOS folds, predicate congruence."""

from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    FinalVerdict,
    ResearchFinalVerdict,
    ToolRunResult,
)
from futures_agent_os.research_experiment.mvp_r_003.treatment_binding import (
    STATIC_TREATMENT_CONTROL_PAIRS,
    swap_treatment_control,
)
from futures_agent_os.research_experiment.mvp_r_004.metrics import packet_metric_map
from futures_agent_os.research_experiment.mvp_r_005 import (
    DecisionBrief,
    PredicateClause,
    PredicateClauseKind,
    PredicateVerdictMismatch,
    R005CorrectionV2EpisodeOutcome,
    bind_falsification_condition,
    compute_r005_correction_v2_gate,
    evaluate_falsification_predicate,
    packet_has_authentic_walk_forward,
)
from futures_agent_os.research_experiment.mvp_r_005.predicate import (
    FalsificationPredicate,
    enforce_verdict_predicate_congruence,
    parse_predicate_mapping,
)
from futures_agent_os.research_experiment.mvp_replay import chronological_fold_diagnostics
from futures_agent_os.research_experiment.walk_forward import (
    WALK_FORWARD_ACCURACY_SOURCE,
    equal_length_partition_counts,
    evaluate_oos_folds,
    plan_walk_forward_fold_windows,
)

sys.path.insert(0, str(Path(__file__).parent))
from test_mvp_r_003_contracts import hypothesis, plan  # noqa: E402


def _aggregate_predicate() -> FalsificationPredicate:
    return FalsificationPredicate(
        (
            PredicateClause(
                PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL,
                "signal_accuracy",
                None,
                None,
                None,
            ),
        )
    )


def _each_fold_predicate() -> FalsificationPredicate:
    return FalsificationPredicate(
        (
            PredicateClause(
                PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL,
                "signal_accuracy",
                None,
                None,
                None,
            ),
        )
    )


def _packet(
    *,
    l0: tuple[tuple[str, str], ...] = (
        ("signal_accuracy", "0.52631579"),
        ("counterfactual_signal_accuracy", "0.47368421"),
    ),
    walk_forward: tuple[tuple[str, str], ...],
) -> ExperimentResultPacket:
    metrics = {
        "l0_signal_test": l0,
        "l1_bar_backtest": (("proxy_net_return", "0.01000000"), ("counterfactual_net_return", "-0.01200000")),
        "walk_forward_test": walk_forward,
        "cost_slippage_stress": (("stressed_net_return", "0.00400000"),),
        "counterfactual_test": (("counterfactual_net_return", "-0.01200000"),),
    }
    runs = tuple(
        ToolRunResult(tool, "SUCCESS", metrics[tool], (), ("market-snapshot://b",)) for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-r005-v2",
        plan_ref=plan().identity,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def _walk_metrics(*, fold_3_accuracy: str, fold_3_control: str) -> tuple[tuple[str, str], ...]:
    return (
        ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
        ("fold_count", "3"),
        ("planned_fold_count", "3"),
        ("stopped_early", "false"),
        ("test_bars", "5"),
        ("full_window_signal_count", "38"),
        ("oos_signal_count", "15"),
        ("raw_follow_signal_accuracy", "0.52631579"),
        ("raw_invert_signal_accuracy", "0.47368421"),
        ("treatment_direction", "FOLLOW"),
        ("raw_computation_direction", "FOLLOW"),
        ("hypothesis_ref", hypothesis().identity),
        ("plan_hypothesis_ref", hypothesis().identity),
        ("positive_fold_ratio", "0.66666667"),
        ("counterfactual_positive_fold_ratio", "0.33333333"),
        ("fold_1_signal_accuracy", "0.60000000"),
        ("fold_1_counterfactual_signal_accuracy", "0.40000000"),
        ("fold_1_signal_count", "5"),
        ("fold_2_signal_accuracy", "0.60000000"),
        ("fold_2_counterfactual_signal_accuracy", "0.40000000"),
        ("fold_2_signal_count", "5"),
        ("fold_3_signal_accuracy", fold_3_accuracy),
        ("fold_3_counterfactual_signal_accuracy", fold_3_control),
        ("fold_3_signal_count", "5"),
    )


def _cu_packet() -> ExperimentResultPacket:
    return _packet(walk_forward=_walk_metrics(fold_3_accuracy="0.20000000", fold_3_control="0.80000000"))


def test_planner_windows_match_v1_010_walk_and_reject_12_13_13() -> None:
    windows = plan_walk_forward_fold_windows(38, train_bars=20, test_bars=5, step_bars=5, embargo_bars=1)
    assert len(windows) == 3
    assert tuple((item.test_start, item.test_end) for item in windows) == ((21, 26), (26, 31), (31, 36))
    assert equal_length_partition_counts(38, folds=3) == (12, 13, 13)
    signals = (1,) * 38
    labels = (1,) * 38
    forward = tuple(Decimal("0.01") for _unused in range(38))
    times = tuple(f"2026-04-{index:02d}T07:00:00Z" for index in range(1, 39))
    folds = evaluate_oos_folds(
        signals=signals,
        labels=labels,
        forward_returns=forward,
        per_signal_cost=Decimal("0.0003"),
        train_bars=20,
        test_bars=5,
        step_bars=5,
        embargo_bars=1,
        signal_times=times,
        label_times=times,
        config_sha256="a" * 64,
    )
    assert tuple(item.signal_count for item in folds) == (5, 5, 5)
    assert all(item.signal_count <= 5 for item in folds)
    assert tuple(item.signal_count for item in folds) != (12, 13, 13)
    forbidden = chronological_fold_diagnostics(signals, (*forward, Decimal("0.01")), Decimal("0.0003"), folds=3)
    assert forbidden.fold_signal_counts == (12, 13, 13)


def test_follow_invert_metric_pairs_are_semantic_mirrors() -> None:
    follow = {
        "signal_accuracy": "0.60526316",
        "counterfactual_signal_accuracy": "0.39473684",
        "proxy_net_return": "0.01000000",
        "counterfactual_net_return": "-0.01200000",
        "stressed_net_return": "0.00400000",
        "counterfactual_stressed_net_return": "-0.01800000",
        "positive_fold_ratio": "0.66666667",
        "counterfactual_positive_fold_ratio": "0.33333333",
        "fold_1_signal_accuracy": "0.80000000",
        "fold_1_counterfactual_signal_accuracy": "0.20000000",
    }
    invert = swap_treatment_control(follow, direction="INVERT")
    for treatment, control in STATIC_TREATMENT_CONTROL_PAIRS:
        assert follow[treatment] == invert[control]
        assert follow[control] == invert[treatment]
    assert follow["fold_1_signal_accuracy"] == invert["fold_1_counterfactual_signal_accuracy"]
    assert follow["fold_1_counterfactual_signal_accuracy"] == invert["fold_1_signal_accuracy"]
    restored = swap_treatment_control(invert, direction="INVERT")
    assert restored == follow


def test_incomplete_at_least_n_clause_is_dropped_not_invented() -> None:
    predicate = parse_predicate_mapping(
        {
            "clauses": [
                {
                    "kind": "aggregate_primary_beats_control",
                    "metric": "signal_accuracy",
                    "threshold": None,
                    "fold_n": None,
                    "minimum_count": None,
                },
                {
                    "kind": "at_least_n_oos_folds_above_threshold",
                    "metric": "signal_accuracy",
                    "threshold": None,
                    "fold_n": None,
                    "minimum_count": None,
                },
            ]
        }
    )
    assert len(predicate.clauses) == 1
    assert predicate.clauses[0].kind is PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL
    with pytest.raises(ValueError, match="no evaluable clauses"):
        parse_predicate_mapping(
            {
                "clauses": [
                    {
                        "kind": "at_least_n_oos_folds_above_threshold",
                        "metric": "signal_accuracy",
                        "threshold": None,
                        "fold_n": None,
                        "minimum_count": None,
                    }
                ]
            }
        )


def test_unused_predicate_clause_fields_are_normalized_to_null() -> None:
    predicate = parse_predicate_mapping(
        {
            "schema_version": "mvp-r-005.falsification-predicate.v1",
            "clauses": [
                {
                    "kind": "primary_positive_and_beats_control",
                    "metric": "signal_accuracy",
                    "threshold": "0.50",
                    "fold_n": 3,
                    "minimum_count": 20,
                }
            ],
        }
    )
    clause = predicate.clauses[0]
    assert clause.kind is PredicateClauseKind.PRIMARY_POSITIVE_AND_BEATS_CONTROL
    assert clause.metric == "signal_accuracy"
    assert clause.threshold is None
    assert clause.fold_n is None
    assert clause.minimum_count is None


def test_cu_extreme_aggregate_predicate_cannot_reject_on_one_fold() -> None:
    packet = _cu_packet()
    evaluation = evaluate_falsification_predicate(_aggregate_predicate(), packet)
    assert evaluation.outcome is FinalVerdict.ACCEPT
    assert packet_metric_map(packet)["fold_3_signal_accuracy"] == "0.20000000"


def test_agent_cannot_rewrite_aggregate_predicate_with_fold_failure() -> None:
    packet = _cu_packet()
    hyp = replace(
        hypothesis(),
        primary_metric="signal_accuracy",
        falsification_condition=bind_falsification_condition(_aggregate_predicate()),
    )
    verdict = ResearchFinalVerdict(
        "verdict-cu",
        FinalVerdict.REJECT,
        hyp.identity,
        hyp.falsification_condition,
        (packet.identity,),
        "fold 3 failed so reject",
    )
    brief = DecisionBrief("测了什么", "第三折失败", "拒绝", "停止", FinalVerdict.REJECT)
    with pytest.raises(PredicateVerdictMismatch):
        enforce_verdict_predicate_congruence(verdict, brief, hyp, packet)


def test_sr_false_breakout_invert_uses_treatment_relative_control() -> None:
    follow = {
        "signal_accuracy": "0.60526316",
        "counterfactual_signal_accuracy": "0.39473684",
        "proxy_net_return": "0.01000000",
        "counterfactual_net_return": "-0.01200000",
        "stressed_net_return": "0.00400000",
        "counterfactual_stressed_net_return": "-0.01800000",
        "positive_fold_ratio": "0.66666667",
        "counterfactual_positive_fold_ratio": "0.33333333",
    }
    invert = swap_treatment_control(follow, direction="INVERT")
    assert invert["signal_accuracy"] == "0.39473684"
    packet = _packet(
        l0=(
            ("signal_accuracy", invert["signal_accuracy"]),
            ("counterfactual_signal_accuracy", invert["counterfactual_signal_accuracy"]),
        ),
        walk_forward=(
            ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
            ("fold_count", "3"),
            ("treatment_direction", "INVERT"),
            ("fold_1_signal_accuracy", "0.20000000"),
            ("fold_1_counterfactual_signal_accuracy", "0.80000000"),
            ("fold_1_signal_count", "5"),
            ("fold_2_signal_accuracy", "0.20000000"),
            ("fold_2_counterfactual_signal_accuracy", "0.80000000"),
            ("fold_2_signal_count", "5"),
            ("fold_3_signal_accuracy", "0.20000000"),
            ("fold_3_counterfactual_signal_accuracy", "0.80000000"),
            ("fold_3_signal_count", "5"),
        ),
    )
    aggregate = evaluate_falsification_predicate(_aggregate_predicate(), packet)
    assert aggregate.outcome is FinalVerdict.REJECT
    folds = evaluate_falsification_predicate(_each_fold_predicate(), packet)
    assert folds.outcome is FinalVerdict.REJECT


def test_sr_extreme_each_fold_predicate_requires_every_oos_fold() -> None:
    packet = _packet(
        l0=(("signal_accuracy", "0.60000000"), ("counterfactual_signal_accuracy", "0.40000000")),
        walk_forward=(
            ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
            ("fold_count", "3"),
            ("fold_1_signal_accuracy", "0.60000000"),
            ("fold_1_counterfactual_signal_accuracy", "0.40000000"),
            ("fold_1_signal_count", "5"),
            ("fold_2_signal_accuracy", "0.60000000"),
            ("fold_2_counterfactual_signal_accuracy", "0.40000000"),
            ("fold_2_signal_count", "5"),
            ("fold_3_signal_accuracy", "0.40000000"),
            ("fold_3_counterfactual_signal_accuracy", "0.60000000"),
            ("fold_3_signal_count", "5"),
        ),
    )
    assert evaluate_falsification_predicate(_aggregate_predicate(), packet).outcome is FinalVerdict.ACCEPT
    assert evaluate_falsification_predicate(_each_fold_predicate(), packet).outcome is FinalVerdict.REJECT


def test_missing_required_fold_is_need_more_data_not_synthesized() -> None:
    predicate = FalsificationPredicate(
        (PredicateClause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, None, None, 3, None),)
    )
    packet = _packet(
        walk_forward=(
            ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
            ("fold_count", "2"),
            ("stopped_early", "false"),
            ("planned_fold_count", "2"),
            ("fold_1_signal_accuracy", "0.40000000"),
            ("fold_1_counterfactual_signal_accuracy", "0.60000000"),
            ("fold_1_signal_count", "5"),
            ("fold_2_signal_accuracy", "0.40000000"),
            ("fold_2_counterfactual_signal_accuracy", "0.60000000"),
            ("fold_2_signal_count", "5"),
        )
    )
    assert evaluate_falsification_predicate(predicate, packet).outcome is FinalVerdict.NEED_MORE_DATA
    assert "fold_3_signal_accuracy" not in packet_metric_map(packet)


def test_equal_split_packet_fails_authentic_walk_forward_gate() -> None:
    packet = _packet(
        walk_forward=(
            ("fold_signal_accuracy_source", "chronological_signal_alignment"),
            ("fold_count", "3"),
            ("fold_1_signal_accuracy", "0.50000000"),
            ("fold_1_signal_count", "12"),
            ("fold_2_signal_accuracy", "0.50000000"),
            ("fold_2_signal_count", "13"),
            ("fold_3_signal_accuracy", "0.50000000"),
            ("fold_3_signal_count", "13"),
        )
    )
    assert packet_has_authentic_walk_forward(packet) is False


def test_correction_v2_gate_is_computed_not_hardcoded() -> None:
    passing = tuple(
        R005CorrectionV2EpisodeOutcome(
            f"r005-e{index}",
            "AG",
            "UP_TREND",
            f"2026-05-0{index}T07:00:00Z",
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
            True,
            True,
            False,
            "ACCEPT",
            "ACCEPT",
            "ACCEPT",
            "ACCEPT",
        )
        for index in range(1, 9)
    )
    passed = compute_r005_correction_v2_gate(passing)
    assert passed["hardcoded"] is False
    assert passed["not_go"] is True
    assert passed["independent_real_user_validation"] is False
    assert passed["decision"] == "R005_CORRECTION_V2_PASS"
    assert passed["direction_binding"] == "8/8"
    assert passed["treatment_control_semantic_mirror"] == "8/8"
    assert passed["authentic_walk_forward_fold_manifest"] == "8/8"
    assert passed["fold_metrics_manifest_binding"] == "8/8"
    assert passed["verdict_predicate_congruence"] == "8/8"
    assert passed["four_block_reports"] == "8/8"
    assert passed["pre_experiment_critic_gate"] == "0/8"
    assert passed["critic_blocked_experiments"] == 0
    failed = compute_r005_correction_v2_gate(
        (*passing[:-1], replace(passing[-1], direction_bound=False, complete=True))
    )
    assert failed["decision"] == "R005_CORRECTION_V2_FAIL"
    assert failed["hardcoded"] is False


def test_v1_scorecard_was_not_rewritten() -> None:
    import json

    payload = json.loads(Path(__file__).resolve().parents[2].joinpath("evidence/mvp-r-005/scorecard.json").read_text())
    assert payload["gate"]["schema_version"] == "mvp-r-005.discovery-gate.v1"
    assert payload["gate"]["decision"] == "R005_PASS"
    rejection = json.loads(
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("evidence/mvp-r-005/reviewer-rejection-2026-09-02.json")
        .read_text()
    )
    assert rejection["v1_scorecard_rewritten"] is False
    assert rejection["rejected_gate_decision"] == "R005_PASS"


def test_execute_replay_binds_direction_and_rejects_plan_mismatch() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "replay"))
    from test_mvp_r_003_vertical_slice import governed_replay_inputs  # noqa: E402
    from test_mvp_r_003_contracts import episode  # noqa: E402
    from test_mvp_r_validation_contracts import _at  # noqa: E402

    from futures_agent_os.research_experiment.mvp_r_003.experiment_adapter import MvpR003ExperimentAdapter
    from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
    from futures_agent_os.research_experiment.validation_tools import TrustedResearchToolsPort

    records, window, episode_view, config = governed_replay_inputs()
    contract = replace(
        episode(),
        instrument="CU",
        as_of=_at(11).to_dict()["recorded_at"],
        market_cutoff=records[-1].event_time.to_dict()["recorded_at"],
        acquired_at=_at(11).to_dict()["recorded_at"],
    )
    adapter = MvpR003ExperimentAdapter()
    follow = hypothesis()
    invert = replace(
        follow, hypothesis_id="hypothesis-invert", parameters=(("direction", "INVERT"), ("threshold", "0.010"))
    )
    follow_plan = adapter.instantiate(contract, follow, config, code_ref="git:r005-v2")
    invert_plan = adapter.instantiate(contract, invert, config, code_ref="git:r005-v2")
    authority = TrustedResearchToolsPort(bytes(range(4, 36)))
    kwargs = {
        "episode": episode_view,
        "window": window,
        "records": records,
        "market_state": EpisodeStratum.RANGE,
        "config": config,
        "result_authority": authority,
    }
    follow_packet = adapter.execute_replay(plan=follow_plan, hypothesis=follow, **kwargs)
    invert_packet = adapter.execute_replay(plan=invert_plan, hypothesis=invert, **kwargs)
    follow_metrics = packet_metric_map(follow_packet)
    invert_metrics = packet_metric_map(invert_packet)
    assert "treatment_direction" not in follow_metrics
    assert follow_metrics["signal_accuracy"] == invert_metrics["signal_accuracy"]
    assert follow_metrics["proxy_net_return"] == invert_metrics["proxy_net_return"]
    from futures_agent_os.research_experiment.mvp_r_005.treatment_view import build_treatment_metric_view

    follow_view = build_treatment_metric_view(follow_packet, hypothesis=follow, plan=follow_plan, config=config)
    invert_view = build_treatment_metric_view(invert_packet, hypothesis=invert, plan=invert_plan, config=config)
    assert follow_view.treatment_direction == "FOLLOW"
    assert invert_view.treatment_direction == "INVERT"
    assert follow_view.raw_computation_direction == "FOLLOW"
    assert invert_view.raw_computation_direction == "FOLLOW"
    assert follow_view.metric_map["signal_accuracy"] == invert_view.metric_map["counterfactual_signal_accuracy"]
    assert follow_view.metric_map["counterfactual_signal_accuracy"] == invert_view.metric_map["signal_accuracy"]
    assert follow_view.metric_map["proxy_net_return"] == invert_view.metric_map["counterfactual_net_return"]
    assert follow_view.metric_map["counterfactual_net_return"] == invert_view.metric_map["proxy_net_return"]
    source = follow_packet.tool_runs[0].source_refs[0]
    assert source.startswith("research-tool-result://")
    with pytest.raises(ValueError, match="does not bind the supplied hypothesis"):
        adapter.execute_replay(plan=follow_plan, hypothesis=invert, **kwargs)
