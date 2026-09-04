"""MVP-R-005 decision brief: fold accuracy, validator intercept, computed gate."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    FinalVerdict,
    ResearchFinalVerdict,
    SignalOperator,
    ToolRunResult,
    ValidationStatus,
)
from futures_agent_os.research_experiment.mvp_r_004 import MvpR004HypothesisValidator
from futures_agent_os.research_experiment.mvp_r_005 import (
    DecisionBrief,
    R005EpisodeOutcome,
    apply_need_more_data_guard,
    compute_r005_gate,
    predecessor_evidence_status,
    render_decision_brief_markdown,
    requires_per_fold_signal_accuracy,
)
from futures_agent_os.research_experiment.mvp_r_005.contracts import FALSIFICATION_REQUIRES_FOLD_ACCURACY

sys.path.insert(0, str(Path(__file__).parent))
from test_mvp_r_003_contracts import episode, hypothesis, plan  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _packet(*, walk_forward: tuple[tuple[str, str], ...]) -> ExperimentResultPacket:
    metrics = {
        "l0_signal_test": (("signal_accuracy", "0.60000000"), ("counterfactual_signal_accuracy", "0.40000000")),
        "l1_bar_backtest": (("proxy_net_return", "0.01000000"),),
        "walk_forward_test": walk_forward,
        "cost_slippage_stress": (("stressed_net_return", "0.00400000"),),
        "counterfactual_test": (("counterfactual_net_return", "-0.01200000"),),
    }
    runs = tuple(
        ToolRunResult(tool, "SUCCESS", metrics[tool], (), ("market-snapshot://b",)) for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-r005",
        plan_ref=plan().identity,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def _passing_outcome(index: int) -> R005EpisodeOutcome:
    return R005EpisodeOutcome(
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
        False,
        "ACCEPT",
        "REJECT",
    )


def test_equal_length_partition_is_not_walk_forward_oos() -> None:
    from futures_agent_os.research_experiment.walk_forward import (
        equal_length_partition_counts,
        plan_walk_forward_fold_windows,
    )

    forbidden = equal_length_partition_counts(38, folds=3)
    assert forbidden == (12, 13, 13)
    windows = plan_walk_forward_fold_windows(38, train_bars=20, test_bars=5, step_bars=5, embargo_bars=1)
    assert tuple(item.test_bars for item in windows) == (5, 5, 5)
    assert all(item.test_bars <= 5 for item in windows)


def test_validator_intercepts_illegal_operator_missing_metric_and_direction() -> None:
    source = episode()
    validator = MvpR004HypothesisValidator()
    operator = validator.validate(source, replace(hypothesis(), signal_operator=SignalOperator.VOLUME_CONFIRMATION))
    assert operator.status is ValidationStatus.UNSUPPORTED
    assert "UNSUPPORTED_SIGNAL_OPERATOR" in operator.reason_codes
    metric = validator.validate(source, replace(hypothesis(), primary_metric="net_directional_mean"))
    assert metric.status is ValidationStatus.UNSUPPORTED
    assert "PRIMARY_METRIC_NOT_IN_RESULT_PACKET" in metric.reason_codes
    direction = validator.validate(
        source,
        replace(hypothesis(), parameters=(("direction", "HOLD"), ("threshold", "0.010"))),
    )
    assert direction.status is ValidationStatus.UNSUPPORTED
    assert "UNRESOLVED_PARAMETER" in direction.reason_codes


def test_need_more_data_when_fold_signal_accuracy_is_missing() -> None:
    hyp = replace(hypothesis(), falsification_condition=FALSIFICATION_REQUIRES_FOLD_ACCURACY)
    assert requires_per_fold_signal_accuracy(hyp.falsification_condition) is True
    packet = _packet(walk_forward=(("positive_fold_ratio", "1.00000000"), ("fold_count", "3")))
    verdict = ResearchFinalVerdict(
        "verdict-r005",
        FinalVerdict.ACCEPT,
        hyp.identity,
        hyp.falsification_condition,
        (packet.identity,),
        "packet looks fine if positive_fold_ratio is misread as accuracy",
    )
    brief = DecisionBrief("测了什么", "结果", "接受", "继续", FinalVerdict.ACCEPT)
    guarded, guarded_brief, forced = apply_need_more_data_guard(verdict, brief, hyp, packet)
    assert forced is True
    assert guarded.verdict is FinalVerdict.NEED_MORE_DATA
    assert guarded_brief.verdict is FinalVerdict.NEED_MORE_DATA
    complete = _packet(
        walk_forward=(
            ("fold_1_signal_accuracy", "0.60000000"),
            ("fold_2_signal_accuracy", "0.55000000"),
            ("fold_3_signal_accuracy", "0.58000000"),
            ("fold_1_signal_count", "4"),
            ("fold_2_signal_count", "4"),
            ("fold_3_signal_count", "4"),
        )
    )
    kept, kept_brief, not_forced = apply_need_more_data_guard(verdict, brief, hyp, complete)
    assert not_forced is False
    assert kept.verdict is FinalVerdict.ACCEPT
    assert kept_brief.verdict is FinalVerdict.ACCEPT


def test_user_report_has_only_four_chinese_blocks() -> None:
    markdown = render_decision_brief_markdown(
        "r005-ag-uptrend",
        DecisionBrief("假设 A", "三段命中率已给出", "拒绝", "停止该方向", FinalVerdict.REJECT),
    )
    assert markdown.count("## ") == 4
    assert "## 测了什么" in markdown
    assert "## 结果怎样" in markdown
    assert "## 当前判断" in markdown
    assert "## 下一步动作" in markdown
    assert "Independent Critic" not in markdown


def test_r005_gate_is_computed_not_hardcoded() -> None:
    passing = tuple(_passing_outcome(index) for index in range(1, 9))
    passed = compute_r005_gate(passing)
    assert passed["hardcoded"] is False
    assert passed["decision"] == "R005_PASS"
    assert passed["not_go"] is True
    blocked = (
        *passing[:-1],
        replace(passing[-1], critic_blocked_experiment=True, complete=True),
    )
    failed = compute_r005_gate(blocked)
    assert failed["hardcoded"] is False
    assert failed["decision"] == "R005_FAIL"
    assert failed["critic_blocked_experiments"] == 1
    with pytest.raises(ValueError, match="eight"):
        compute_r005_gate(passing[:7])


def test_predecessor_r003_r004_evidence_is_untouched() -> None:
    status = predecessor_evidence_status(PROJECT_ROOT)
    assert status["r003_v1_decision"] == "STOP/PIVOT"
    assert status["r004_discovery_decision"] == "DISCOVERY_PASS"
    assert status["r004_user_blind_eval"] == "USER_VALUE_FAIL"
    assert status["r004_independent_real_user_validation"] is False
    assert status["r004_product_pivot"] == "SINGLE_RESEARCH_AGENT_PLUS_DETERMINISTIC_EXPERIMENT_LOOP"
