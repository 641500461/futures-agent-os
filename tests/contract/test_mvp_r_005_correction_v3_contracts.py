"""MVP-R-005 correction-v3: FAIL over INSUFFICIENT, metric binding, views, hashes, tamper gate."""

from __future__ import annotations

import sys
from copy import deepcopy
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
from futures_agent_os.research_experiment.mvp_r_003.treatment_binding import apply_treatment_stop_rule
from futures_agent_os.research_experiment.mvp_r_004.metrics import packet_metric_map
from futures_agent_os.research_experiment.mvp_r_005 import (
    DecisionBrief,
    PredicateClause,
    PredicateClauseKind,
    R005CorrectionV3EpisodeOutcome,
    bind_falsification_condition,
    build_predecessor_hash_manifest,
    build_treatment_metric_view,
    compute_r005_correction_v3_gate,
    evaluate_falsification_predicate,
    predecessor_hashes_match,
    raw_tool_runs_untransformed,
    view_has_stopped_fold_leak,
)
from futures_agent_os.research_experiment.mvp_r_005.artifact_checks import assess_correction_v3_episode
from futures_agent_os.research_experiment.mvp_r_005.predicate import FalsificationPredicate, parse_predicate_mapping
from futures_agent_os.research_experiment.walk_forward import WALK_FORWARD_ACCURACY_SOURCE
from futures_agent_os.shared_kernel import canonical_json_text

sys.path.insert(0, str(Path(__file__).parent))
from test_mvp_r_003_contracts import hypothesis, plan  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _clause(
    kind: PredicateClauseKind, metric: str | None = None, threshold: str | None = None, fold_n: int | None = None
) -> PredicateClause:
    return PredicateClause(kind, metric, threshold, fold_n, None)


def _walk(
    *,
    fold_count: str = "2",
    stopped: str = "true",
    planned_fold_count: str = "3",
    fold_1_acc: str = "0.40000000",
    fold_2_acc: str = "0.40000000",
    extra: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    base = (
        ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
        ("fold_count", fold_count),
        ("planned_fold_count", planned_fold_count),
        ("stopped_early", stopped),
        ("fold_1_signal_accuracy", fold_1_acc),
        ("fold_1_counterfactual_signal_accuracy", "0.60000000"),
        ("fold_1_signal_count", "5"),
        ("fold_1_proxy_net_return", "-0.01000000"),
        ("fold_1_counterfactual_net_return", "0.00800000"),
        ("fold_2_signal_accuracy", fold_2_acc),
        ("fold_2_counterfactual_signal_accuracy", "0.60000000"),
        ("fold_2_signal_count", "5"),
        ("fold_2_proxy_net_return", "-0.02000000"),
        ("fold_2_counterfactual_net_return", "0.01500000"),
    )
    return base + extra


def _packet(walk_forward: tuple[tuple[str, str], ...]) -> ExperimentResultPacket:
    metrics = {
        "l0_signal_test": (("signal_accuracy", "0.52631579"), ("counterfactual_signal_accuracy", "0.47368421")),
        "l1_bar_backtest": (
            ("proxy_net_return", "0.01000000"),
            ("counterfactual_net_return", "-0.01200000"),
            ("stressed_net_return", "0.05687895"),
            ("counterfactual_stressed_net_return", "-0.10247895"),
        ),
        "walk_forward_test": walk_forward,
        "cost_slippage_stress": (("stressed_net_return", "0.05687895"),),
        "counterfactual_test": (("counterfactual_net_return", "-0.01200000"),),
    }
    runs = tuple(
        ToolRunResult(tool, "SUCCESS", metrics[tool], (), (f"research-tool-result://{tool}-digest",))
        for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-r005-v3",
        plan_ref=plan().identity,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def _passing_v3(index: int, **overrides: object) -> R005CorrectionV3EpisodeOutcome:
    payload = {
        "episode_id": f"r005-e{index}",
        "instrument": "AG",
        "stratum": "UP_TREND",
        "market_cutoff": f"2026-05-0{index}T07:00:00Z",
        "complete": True,
        "agent_loop_complete": True,
        "agent_experiment_complete": True,
        "single_prompt_complete": True,
        "raw_tool_result_lineage": True,
        "predicate_metric_binding": True,
        "verdict_predicate_congruent": True,
        "four_block_report": True,
        "pre_experiment_critic_gate": False,
        "critic_blocked_experiment": False,
        "overlapping_predecessor": False,
        "stopped_folds_invisible": True,
        "treatment_view_bound": True,
        "agent_verdict": "REJECT",
        "single_prompt_verdict": "REJECT",
        "deterministic_agent_outcome": "REJECT",
        "deterministic_single_outcome": "REJECT",
    }
    payload.update(overrides)
    return R005CorrectionV3EpisodeOutcome(**payload)  # type: ignore[arg-type]


def test_fail_plus_missing_required_fold_is_reject() -> None:
    predicate = FalsificationPredicate(
        (
            _clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "signal_accuracy"),
            _clause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, fold_n=3),
        )
    )
    evaluation = evaluate_falsification_predicate(predicate, _packet(_walk(stopped="false", planned_fold_count="3")))
    assert evaluation.outcome is FinalVerdict.REJECT
    assert ("each_oos_fold_primary_beats_control", "FAIL") in evaluation.clause_results
    assert ("required_oos_fold_count", "INSUFFICIENT") in evaluation.clause_results


def test_pass_plus_missing_required_fold_is_need_more_data() -> None:
    predicate = FalsificationPredicate(
        (
            _clause(PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL, "signal_accuracy"),
            _clause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, fold_n=3),
        )
    )
    packet = _packet(_walk(stopped="false", planned_fold_count="2"))
    evaluation = evaluate_falsification_predicate(predicate, packet)
    assert evaluation.outcome is FinalVerdict.NEED_MORE_DATA
    assert ("required_oos_fold_count", "INSUFFICIENT") in evaluation.clause_results
    assert ("aggregate_primary_beats_control", "PASS") in evaluation.clause_results


def test_required_fold_count_fails_when_stop_rule_already_fired() -> None:
    predicate = FalsificationPredicate(
        (
            _clause(PredicateClauseKind.AGGREGATE_PRIMARY_BEATS_CONTROL, "signal_accuracy"),
            _clause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, fold_n=3),
        )
    )
    evaluation = evaluate_falsification_predicate(predicate, _packet(_walk(stopped="true")))
    assert evaluation.outcome is FinalVerdict.REJECT
    assert ("required_oos_fold_count", "FAIL") in evaluation.clause_results


def test_impossible_at_least_n_is_fail_not_insufficient() -> None:
    predicate = FalsificationPredicate(
        (_clause(PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD, "signal_accuracy", "0.50", 3),)
    )
    evaluation = evaluate_falsification_predicate(predicate, _packet(_walk()))
    assert evaluation.outcome is FinalVerdict.REJECT
    assert evaluation.clause_results[0][1] == "FAIL"


def test_still_possible_at_least_n_is_insufficient() -> None:
    predicate = FalsificationPredicate(
        (_clause(PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD, "signal_accuracy", "0.50", 3),)
    )
    packet = _packet(_walk(fold_count="2", stopped="false", fold_1_acc="0.80000000", fold_2_acc="0.80000000"))
    evaluation = evaluate_falsification_predicate(predicate, packet)
    assert evaluation.outcome is FinalVerdict.NEED_MORE_DATA
    assert evaluation.clause_results[0][1] == "INSUFFICIENT"


def test_each_fold_known_failure_is_not_covered_by_missing_later_fold() -> None:
    predicate = FalsificationPredicate(
        (_clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "signal_accuracy"),)
    )
    evaluation = evaluate_falsification_predicate(predicate, _packet(_walk()))
    assert evaluation.outcome is FinalVerdict.REJECT


def test_stressed_net_return_cannot_be_a_fold_clause() -> None:
    with pytest.raises(ValueError, match="registered per-fold"):
        _clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "stressed_net_return")
    with pytest.raises(ValueError, match="no registered per-fold"):
        parse_predicate_mapping(
            {
                "clauses": [
                    {
                        "kind": "each_oos_fold_primary_beats_control",
                        "metric": "stressed_net_return",
                        "threshold": None,
                        "fold_n": None,
                        "minimum_count": None,
                    }
                ]
            }
        )


def test_proxy_net_return_fold_predicate_reads_fold_net_return() -> None:
    predicate = FalsificationPredicate(
        (_clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "proxy_net_return"),)
    )
    packet = _packet(_walk(fold_1_acc="0.80000000", fold_2_acc="0.80000000"))
    evaluation = evaluate_falsification_predicate(predicate, packet)
    assert evaluation.outcome is FinalVerdict.REJECT
    rendered = predicate.clauses[0].render()
    assert "fold_N_proxy_net_return" in rendered
    assert "fold_N_signal_accuracy" not in rendered


def test_missing_registered_fold_metric_is_need_more_data_not_swapped() -> None:
    predicate = FalsificationPredicate(
        (_clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "proxy_net_return"),)
    )
    packet = _packet(
        (
            ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
            ("fold_count", "2"),
            ("fold_1_signal_accuracy", "0.80000000"),
            ("fold_1_counterfactual_signal_accuracy", "0.20000000"),
            ("fold_1_signal_count", "5"),
            ("fold_2_signal_accuracy", "0.80000000"),
            ("fold_2_counterfactual_signal_accuracy", "0.20000000"),
            ("fold_2_signal_count", "5"),
        )
    )
    evaluation = evaluate_falsification_predicate(predicate, packet)
    assert evaluation.outcome is FinalVerdict.NEED_MORE_DATA
    assert "fold_1_proxy_net_return" in evaluation.missing_metrics


def test_stop_rule_removes_raw_stopped_fold_fields() -> None:
    metrics = {
        "fold_count": "3",
        "planned_fold_count": "3",
        "fold_1_signal_accuracy": "0.40000000",
        "fold_2_signal_accuracy": "0.40000000",
        "fold_3_signal_accuracy": "1.00000000",
        "fold_1_signal_count": "5",
        "fold_2_signal_count": "5",
        "fold_3_signal_count": "5",
        "raw_follow_fold_3_signal_accuracy": "1.00000000",
        "raw_invert_fold_3_signal_accuracy": "0.00000000",
        "raw_follow_fold_3_proxy_net_return": "0.10000000",
        "fold_manifest": '[{"fold_index":1},{"fold_index":2},{"fold_index":3}]',
    }
    stopped = apply_treatment_stop_rule(metrics, minimum_signal_accuracy=Decimal("0.50000000"), stop_after_failures=2)
    assert stopped["fold_count"] == "2"
    assert stopped["stopped_early"] == "true"
    assert "fold_3_signal_accuracy" not in stopped
    assert "raw_follow_fold_3_signal_accuracy" not in stopped
    assert "raw_invert_fold_3_signal_accuracy" not in stopped
    assert "raw_follow_fold_3_proxy_net_return" not in stopped
    assert '"fold_index": 3' not in stopped["fold_manifest"] and '"fold_index":3' not in stopped["fold_manifest"]


def test_correction_v3_gate_is_computed_and_not_go() -> None:
    passing = tuple(_passing_v3(index) for index in range(1, 9))
    passed = compute_r005_correction_v3_gate(passing, v3_predecessor_hashes_match=True)
    assert passed["hardcoded"] is False
    assert passed["not_go"] is True
    assert passed["independent_real_user_validation"] is False
    assert passed["pre_v2_byte_stability"] == "NOT_PROVEN"
    assert passed["v3_predecessor_hashes_match"] is True
    assert passed["decision"] == "R005_CORRECTION_V3_PASS"
    assert passed["raw_tool_result_lineage"] == "8/8"
    assert passed["predicate_metric_binding"] == "8/8"
    assert passed["predecessor_window_overlap"] == "0/8"
    assert passed["pre_experiment_critic_gate"] == "0/8"
    assert passed["critic_blocked_experiments"] == 0
    failed = compute_r005_correction_v3_gate(
        (*passing[:-1], replace(passing[-1], raw_tool_result_lineage=False)),
        v3_predecessor_hashes_match=True,
    )
    assert failed["decision"] == "R005_CORRECTION_V3_FAIL"
    hash_fail = compute_r005_correction_v3_gate(passing, v3_predecessor_hashes_match=False)
    assert hash_fail["decision"] == "R005_CORRECTION_V3_FAIL"
    assert "v3 predecessor hashes match false" in hash_fail["decision_reasons"]
    with pytest.raises(ValueError, match="NOT_PROVEN"):
        compute_r005_correction_v3_gate(passing, v3_predecessor_hashes_match=True, pre_v2_byte_stability="PROVEN")


def test_predecessor_hash_manifest_detects_tamper(tmp_path: Path) -> None:
    sample = tmp_path / "evidence" / "mvp-r-005"
    sample.mkdir(parents=True)
    target = sample / "scorecard.json"
    target.write_text('{"gate":{"decision":"R005_PASS"}}', encoding="utf-8")
    from futures_agent_os.research_experiment.mvp_r_005 import evidence as evidence_mod

    original_files = evidence_mod.PROTECTED_FILES
    original_roots = evidence_mod.PROTECTED_ROOTS
    original_trees = evidence_mod.PROTECTED_TREES
    evidence_mod.PROTECTED_FILES = ("evidence/mvp-r-005/scorecard.json",)
    evidence_mod.PROTECTED_ROOTS = ()
    evidence_mod.PROTECTED_TREES = ()
    try:
        baseline = build_predecessor_hash_manifest(tmp_path)
        current = build_predecessor_hash_manifest(tmp_path)
        assert predecessor_hashes_match(baseline, current) is True
        target.write_text('{"gate":{"decision":"TAMPERED"}}', encoding="utf-8")
        tampered = build_predecessor_hash_manifest(tmp_path)
        assert predecessor_hashes_match(baseline, tampered) is False
    finally:
        evidence_mod.PROTECTED_FILES = original_files
        evidence_mod.PROTECTED_ROOTS = original_roots
        evidence_mod.PROTECTED_TREES = original_trees


def _validation_config():
    from futures_agent_os.research_experiment.validation_tools import ValidationConfig, semantic_entity_id

    return ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-005", "revision": "v3-test"}),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.010"),
        Decimal("2.00000000"),
        Decimal("1.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )


def _typed_hypothesis():
    return replace(
        hypothesis(),
        primary_metric="signal_accuracy",
        control="inverted signal direction",
        falsification_condition=bind_falsification_condition(
            FalsificationPredicate(
                (
                    _clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "signal_accuracy"),
                    _clause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, fold_n=3),
                )
            )
        ),
    )


def _raw_three_fold_packet(plan_ref: str) -> ExperimentResultPacket:
    manifest = canonical_json_text(
        (
            {
                "fold_index": 1,
                "signal_count": 5,
                "test_bars": 5,
                "test_start_index": 21,
                "test_end_index": 26,
            },
            {
                "fold_index": 2,
                "signal_count": 5,
                "test_bars": 5,
                "test_start_index": 26,
                "test_end_index": 31,
            },
            {
                "fold_index": 3,
                "signal_count": 5,
                "test_bars": 5,
                "test_start_index": 31,
                "test_end_index": 36,
            },
        )
    )
    walk = (
        ("fold_signal_accuracy_source", WALK_FORWARD_ACCURACY_SOURCE),
        ("fold_count", "3"),
        ("planned_fold_count", "3"),
        ("stopped_early", "false"),
        ("test_bars", "5"),
        ("fold_manifest", manifest),
        ("fold_1_signal_accuracy", "0.40000000"),
        ("fold_1_counterfactual_signal_accuracy", "0.60000000"),
        ("fold_1_signal_count", "5"),
        ("fold_1_proxy_net_return", "-0.01000000"),
        ("fold_1_counterfactual_net_return", "0.00800000"),
        ("fold_2_signal_accuracy", "0.40000000"),
        ("fold_2_counterfactual_signal_accuracy", "0.60000000"),
        ("fold_2_signal_count", "5"),
        ("fold_2_proxy_net_return", "-0.02000000"),
        ("fold_2_counterfactual_net_return", "0.01500000"),
        ("fold_3_signal_accuracy", "1.00000000"),
        ("fold_3_counterfactual_signal_accuracy", "0.00000000"),
        ("fold_3_signal_count", "5"),
        ("fold_3_proxy_net_return", "0.10000000"),
        ("fold_3_counterfactual_net_return", "-0.11000000"),
    )
    l1 = (
        ("proxy_net_return", "0.01000000"),
        ("counterfactual_net_return", "-0.01200000"),
        ("stressed_net_return", "0.05687895"),
        ("counterfactual_stressed_net_return", "-0.10247895"),
        ("positive_fold_ratio", "0.33333333"),
        ("counterfactual_positive_fold_ratio", "0.66666667"),
    )
    metrics = {
        "l0_signal_test": (("signal_accuracy", "0.52631579"), ("counterfactual_signal_accuracy", "0.47368421")),
        "l1_bar_backtest": l1,
        "walk_forward_test": walk,
        "cost_slippage_stress": (("stressed_net_return", "0.05687895"),),
        "counterfactual_test": (("counterfactual_net_return", "-0.01200000"),),
    }
    runs = tuple(
        ToolRunResult(tool, "SUCCESS", metrics[tool], (), (f"{tool}-source/{'a' * 64}",))
        for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-r005-v3-raw",
        plan_ref=plan_ref,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def test_raw_tools_stay_follow_and_invert_view_uses_l1_lineage_for_stressed() -> None:
    hyp = replace(_typed_hypothesis(), parameters=(("direction", "INVERT"), ("threshold", "0.010")))
    cfg = _validation_config()
    bound_plan = replace(
        plan(),
        hypothesis_ref=hyp.identity,
        primary_metric="signal_accuracy",
        config_ref=f"validation-config://{cfg.content_sha256}",
    )
    packet = _raw_three_fold_packet(bound_plan.identity)
    assert raw_tool_runs_untransformed(packet) is True
    cost = next(run for run in packet.tool_runs if run.tool == "cost_slippage_stress")
    assert dict(cost.metrics)["stressed_net_return"] == "0.05687895"
    view = build_treatment_metric_view(packet, hypothesis=hyp, plan=bound_plan, config=cfg)
    assert view.treatment_direction == "INVERT"
    assert view.metric_map["stressed_net_return"] == "-0.10247895"
    stressed = next(item for item in view.lineage if item.metric == "stressed_net_return")
    assert stressed.raw_metric == "counterfactual_stressed_net_return"
    assert stressed.raw_tool == "l1_bar_backtest"
    assert cost.source_refs != () and stressed.raw_source_refs != cost.source_refs
    assert dict(cost.metrics)["stressed_net_return"] == "0.05687895"


def test_treatment_view_and_prompt_payload_hide_stopped_fold() -> None:
    hyp = _typed_hypothesis()
    cfg = _validation_config()
    bound_plan = replace(
        plan(),
        hypothesis_ref=hyp.identity,
        primary_metric="signal_accuracy",
        config_ref=f"validation-config://{cfg.content_sha256}",
    )
    packet = _raw_three_fold_packet(bound_plan.identity)
    assert "fold_3_signal_accuracy" in packet_metric_map(packet)
    view = build_treatment_metric_view(packet, hypothesis=hyp, plan=bound_plan, config=cfg)
    assert view.stopped_early is True
    assert view.fold_count == 2
    assert "fold_3_signal_accuracy" not in view.metric_map
    serialized = canonical_json_text(view.agent_visible_dict())
    assert view_has_stopped_fold_leak(view, serialized) is False
    assert "fold_3_" not in serialized
    assert "raw_follow_fold_3" not in serialized
    evaluation = evaluate_falsification_predicate(
        FalsificationPredicate(
            (
                _clause(PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL, "signal_accuracy"),
                _clause(PredicateClauseKind.REQUIRED_OOS_FOLD_COUNT, fold_n=3),
            )
        ),
        view,
    )
    assert evaluation.outcome is FinalVerdict.REJECT


def _arm_payload(hyp, bound_plan, packet, view, verdict: str) -> dict[str, object]:
    final = ResearchFinalVerdict(
        f"{packet.packet_id}-verdict",
        FinalVerdict(verdict),
        hyp.identity,
        hyp.falsification_condition,
        (packet.identity,),
        "deterministic predicate outcome",
    )
    brief = DecisionBrief("测了什么", "结果", "当前判断", "下一步动作", FinalVerdict(verdict))
    return {
        "schema_version": "mvp-r-005.episode-report.v1",
        "pre_experiment_critic_gate": False,
        "critic_blocked_experiment": False,
        "selected_hypothesis": hyp.to_dict(),
        "experiment_plan": bound_plan.to_dict(),
        "experiment_result": packet.to_dict(),
        "treatment_metric_view": view.to_dict(),
        "agent_visible_experiment": view.agent_visible_dict(),
        "final_verdict": final.to_dict(),
        "decision_brief": brief.to_dict(),
        "shadow_critic": {
            "risk_notes": ("shadow",),
            "would_have_blocked_experiment": False,
            "blocked_experiment": False,
        },
    }


def test_artifact_tampers_fail_correction_v3_assessment() -> None:
    hyp = _typed_hypothesis()
    cfg = _validation_config()
    bound_plan = replace(
        plan(),
        hypothesis_ref=hyp.identity,
        primary_metric="signal_accuracy",
        config_ref=f"validation-config://{cfg.content_sha256}",
    )
    packet = _raw_three_fold_packet(bound_plan.identity)
    view = build_treatment_metric_view(packet, hypothesis=hyp, plan=bound_plan, config=cfg)
    roster_item = {
        "episode_id": "r005-ag-uptrend",
        "instrument": "SHFE.AG.DOMINANT_OI",
        "stratum": "UP_TREND",
        "market_cutoff": "2026-05-14T07:00:00Z",
    }
    markdown = (
        "# 研究决策简报 r005-ag-uptrend\n\n研究与模拟，不是交易指令。\n\n"
        "## 测了什么\n\n测了假设\n\n## 结果怎样\n\n失败\n\n## 当前判断\n\n`REJECT` 拒绝\n\n## 下一步动作\n\n停止\n"
    )
    agent = _arm_payload(hyp, bound_plan, packet, view, "REJECT")
    single = _arm_payload(hyp, bound_plan, packet, view, "REJECT")
    base = assess_correction_v3_episode(
        roster_item=roster_item,
        agent_payload=agent,
        single_payload=single,
        agent_markdown=markdown,
        overlapping_predecessor=False,
        config=cfg,
    )
    assert base.raw_tool_result_lineage is True
    assert base.stopped_folds_invisible is True
    assert base.verdict_predicate_congruent is True

    raw_metric = deepcopy(agent)
    raw_runs = list(raw_metric["experiment_result"]["tool_runs"])
    cost = dict(raw_runs[3])
    cost["metrics"] = (("stressed_net_return", "0.00000001"),)
    raw_runs[3] = cost
    raw_metric["experiment_result"] = {**raw_metric["experiment_result"], "tool_runs": tuple(raw_runs)}
    # hydrate will fail hash; construct via assess expecting lineage false or hydrate error
    with pytest.raises(ValueError):
        assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=raw_metric,
            single_payload=single,
            agent_markdown=markdown,
            overlapping_predecessor=False,
            config=cfg,
        )

    leaked = deepcopy(agent)
    leaked["agent_visible_experiment"] = {
        **leaked["agent_visible_experiment"],
        "metrics": (
            *leaked["agent_visible_experiment"]["metrics"],
            ("raw_follow_fold_3_signal_accuracy", "1.00000000"),
        ),
    }
    leaked_outcome = assess_correction_v3_episode(
        roster_item=roster_item,
        agent_payload=leaked,
        single_payload=single,
        agent_markdown=markdown,
        overlapping_predecessor=False,
        config=cfg,
        agent_visible_serialized=canonical_json_text(leaked["agent_visible_experiment"]),
    )
    assert leaked_outcome.stopped_folds_invisible is False

    mismatch = deepcopy(agent)
    mismatch["final_verdict"] = {
        **mismatch["final_verdict"],
        "verdict": "ACCEPT",
        "content_sha256": mismatch["final_verdict"]["content_sha256"],
    }
    # verdict hydrate will fail hash; check congruence using unhydrated arm verdict path
    mismatch_outcome = assess_correction_v3_episode(
        roster_item=roster_item,
        agent_payload=mismatch,
        single_payload=single,
        agent_markdown=markdown,
        overlapping_predecessor=False,
        config=cfg,
    )
    assert mismatch_outcome.verdict_predicate_congruent is False

    source_ref = deepcopy(agent)
    source_runs = list(source_ref["experiment_result"]["tool_runs"])
    cost_run = dict(source_runs[3])
    cost_run["source_refs"] = ("tampered-source/" + ("b" * 64),)
    source_runs[3] = cost_run
    source_ref["experiment_result"] = {**source_ref["experiment_result"], "tool_runs": tuple(source_runs)}
    with pytest.raises(ValueError):
        assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=source_ref,
            single_payload=single,
            agent_markdown=markdown,
            overlapping_predecessor=False,
            config=cfg,
        )

    direction = deepcopy(agent)
    selected = dict(direction["selected_hypothesis"])
    selected["parameters"] = (("direction", "INVERT"), ("threshold", "0.010"))
    direction["selected_hypothesis"] = selected
    with pytest.raises(ValueError):
        assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=direction,
            single_payload=single,
            agent_markdown=markdown,
            overlapping_predecessor=False,
            config=cfg,
        )

    view_tamper = deepcopy(agent)
    view_tamper["treatment_metric_view"] = {
        **view_tamper["treatment_metric_view"],
        "treatment_direction": "INVERT",
    }
    with pytest.raises(ValueError):
        assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=view_tamper,
            single_payload=single,
            agent_markdown=markdown,
            overlapping_predecessor=False,
            config=cfg,
        )

    manifest = deepcopy(agent)
    view_metrics = list(manifest["treatment_metric_view"]["metrics"])
    view_metrics.append(("fold_count", "1"))
    manifest["treatment_metric_view"] = {**manifest["treatment_metric_view"], "metrics": tuple(view_metrics)}
    with pytest.raises(ValueError):
        assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=manifest,
            single_payload=single,
            agent_markdown=markdown,
            overlapping_predecessor=False,
            config=cfg,
        )

    passing = tuple(_passing_v3(index) for index in range(1, 8))
    gate = compute_r005_correction_v3_gate(
        (*passing, replace(_passing_v3(8), stopped_folds_invisible=False)),
        v3_predecessor_hashes_match=True,
    )
    assert gate["decision"] == "R005_CORRECTION_V3_FAIL"
    hash_gate = compute_r005_correction_v3_gate(
        tuple(_passing_v3(index) for index in range(1, 9)), v3_predecessor_hashes_match=False
    )
    assert hash_gate["decision"] == "R005_CORRECTION_V3_FAIL"


def test_execute_replay_keeps_raw_tool_runs_and_binds_view() -> None:
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
    follow = replace(hypothesis(), primary_metric="signal_accuracy")
    invert = replace(
        follow, hypothesis_id="hypothesis-invert", parameters=(("direction", "INVERT"), ("threshold", "0.010"))
    )
    follow_plan = adapter.instantiate(contract, follow, config, code_ref="git:r005-v3")
    invert_plan = adapter.instantiate(contract, invert, config, code_ref="git:r005-v3")
    kwargs = {
        "episode": episode_view,
        "window": window,
        "records": records,
        "market_state": EpisodeStratum.RANGE,
        "config": config,
        "result_authority": TrustedResearchToolsPort(bytes(range(4, 36))),
    }
    follow_packet = adapter.execute_replay(plan=follow_plan, hypothesis=follow, **kwargs)
    invert_packet = adapter.execute_replay(plan=invert_plan, hypothesis=invert, **kwargs)
    assert raw_tool_runs_untransformed(follow_packet) is True
    assert packet_metric_map(follow_packet)["signal_accuracy"] == packet_metric_map(invert_packet)["signal_accuracy"]
    follow_view = build_treatment_metric_view(follow_packet, hypothesis=follow, plan=follow_plan, config=config)
    invert_view = build_treatment_metric_view(invert_packet, hypothesis=invert, plan=invert_plan, config=config)
    assert follow_view.metric_map["signal_accuracy"] == invert_view.metric_map["counterfactual_signal_accuracy"]
    cost = next(run for run in invert_packet.tool_runs if run.tool == "cost_slippage_stress")
    invert_stressed = invert_view.metric_map["stressed_net_return"]
    cost_raw = dict(cost.metrics)["stressed_net_return"]
    stressed_lineage = next(item for item in invert_view.lineage if item.metric == "stressed_net_return")
    if invert_stressed != cost_raw:
        assert stressed_lineage.raw_metric == "counterfactual_stressed_net_return"
        assert dict(cost.metrics)["stressed_net_return"] == cost_raw
