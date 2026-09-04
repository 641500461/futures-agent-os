"""Recompute correction-v3 checks from raw episode artifacts."""

from __future__ import annotations

from typing import Mapping

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    HypothesisSpec,
    ToolRunResult,
)
from futures_agent_os.research_experiment.validation_tools import ValidationConfig
from futures_agent_os.shared_kernel import canonical_json_text
from futures_agent_os.shared_kernel.observability import JsonValue

from .packet import (
    metrics_bound_to_fold_manifest,
    metrics_have_authentic_walk_forward,
    metrics_treatment_control_mirror,
    view_direction_bound,
)
from .brief import render_decision_brief_markdown
from .contracts import DecisionBrief
from .predicate import (
    FOLD_METRIC_FIELDS,
    PredicateClauseKind,
    evaluate_falsification_predicate,
    fold_metric_fields,
    parse_falsification_condition,
)
from .scorecard import R005CorrectionV3EpisodeOutcome
from .treatment_view import (
    TreatmentMetricView,
    build_treatment_metric_view,
    expected_treatment_metric_lineage,
    raw_tool_runs_untransformed,
    view_has_stopped_fold_leak,
)

FOUR_BLOCK_HEADINGS = ("## 测了什么", "## 结果怎样", "## 当前判断", "## 下一步动作")


def assess_correction_v3_episode(
    *,
    roster_item: Mapping[str, object],
    agent_payload: Mapping[str, object] | None,
    single_payload: Mapping[str, object] | None,
    agent_markdown: str,
    overlapping_predecessor: bool,
    config: ValidationConfig | None = None,
    agent_visible_serialized: str | None = None,
) -> R005CorrectionV3EpisodeOutcome:
    episode_id = str(roster_item["episode_id"])
    agent_complete = _complete_arm(agent_payload)
    single_complete = _complete_arm(single_payload)
    four_blocks = _four_blocks(agent_markdown)
    agent_hyp = _hypothesis(agent_payload)
    single_hyp = _hypothesis(single_payload)
    agent_packet = _packet(agent_payload)
    single_packet = _packet(single_payload)
    agent_view = _view(agent_payload)
    single_view = _view(single_payload)
    agent_plan = _plan(agent_payload)
    single_plan = _plan(single_payload)
    agent_visible = _agent_model_input(agent_payload or {})
    single_visible = _agent_model_input(single_payload or {})
    visible = agent_visible_serialized or canonical_json_text(agent_visible)
    stopped_invisible = True
    if agent_view is not None and visible is not None:
        stopped_invisible = not view_has_stopped_fold_leak(agent_view, visible)
    if single_view is not None:
        single_text = canonical_json_text(single_visible)
        stopped_invisible = stopped_invisible and not view_has_stopped_fold_leak(single_view, single_text)
    visible_bound = _visible_matches_view(agent_visible, agent_view) and _visible_matches_view(
        single_visible, single_view
    )
    view_bound = visible_bound and _arm_view_bound(agent_hyp, agent_plan, agent_packet, agent_view, config)
    view_bound = view_bound and _arm_view_bound(single_hyp, single_plan, single_packet, single_view, config)
    lineage = (
        agent_packet is not None
        and single_packet is not None
        and raw_tool_runs_untransformed(agent_packet)
        and raw_tool_runs_untransformed(single_packet)
        and _lineage_matches_raw(agent_view, agent_packet)
        and _lineage_matches_raw(single_view, single_packet)
    )
    binding = _predicate_metric_binding(agent_hyp, agent_view) and _predicate_metric_binding(single_hyp, single_view)
    congruent = _verdict_congruent(agent_payload, agent_hyp, agent_view) and _verdict_congruent(
        single_payload, single_hyp, single_view
    )
    return R005CorrectionV3EpisodeOutcome(
        episode_id,
        str(roster_item["instrument"]),
        str(roster_item["stratum"]),
        str(roster_item["market_cutoff"]),
        agent_complete and single_complete and four_blocks,
        agent_complete and bool(agent_markdown),
        agent_complete,
        single_complete,
        lineage,
        binding,
        congruent,
        four_blocks,
        bool((agent_payload or {}).get("pre_experiment_critic_gate")),
        bool((agent_payload or {}).get("critic_blocked_experiment")),
        overlapping_predecessor,
        stopped_invisible,
        view_bound,
        _arm_verdict(agent_payload),
        _arm_verdict(single_payload),
        _deterministic_outcome(agent_hyp, agent_view),
        _deterministic_outcome(single_hyp, single_view),
    )


def assess_correction_v5_episode(
    *,
    roster_item: Mapping[str, object],
    agent_payload: Mapping[str, object] | None,
    single_payload: Mapping[str, object] | None,
    agent_markdown: str,
    single_markdown: str,
    overlapping_predecessor: bool,
    config: ValidationConfig,
) -> R005CorrectionV3EpisodeOutcome:
    outcome = assess_correction_v3_episode(
        roster_item=roster_item,
        agent_payload=agent_payload,
        single_payload=single_payload,
        agent_markdown=agent_markdown,
        overlapping_predecessor=overlapping_predecessor,
        config=config,
    )
    reports_bound = _report_bound(str(roster_item["episode_id"]), agent_payload, agent_markdown) and _report_bound(
        str(roster_item["episode_id"]), single_payload, single_markdown
    )
    return R005CorrectionV3EpisodeOutcome(
        outcome.episode_id,
        outcome.instrument,
        outcome.stratum,
        outcome.market_cutoff,
        outcome.agent_loop_complete and outcome.single_prompt_complete and reports_bound,
        outcome.agent_loop_complete,
        outcome.agent_experiment_complete,
        outcome.single_prompt_complete,
        outcome.raw_tool_result_lineage,
        outcome.predicate_metric_binding,
        outcome.verdict_predicate_congruent,
        reports_bound,
        outcome.pre_experiment_critic_gate,
        outcome.critic_blocked_experiment,
        outcome.overlapping_predecessor,
        outcome.stopped_folds_invisible,
        outcome.treatment_view_bound,
        outcome.agent_verdict,
        outcome.single_prompt_verdict,
        outcome.deterministic_agent_outcome,
        outcome.deterministic_single_outcome,
    )


def _complete_arm(payload: Mapping[str, object] | None) -> bool:
    if payload is None:
        return False
    result = payload.get("experiment_result")
    return type(result) is dict and bool(result.get("complete"))


def _four_blocks(text: str) -> bool:
    if not text or "Independent Critic" in text:
        return False
    return all(heading in text for heading in FOUR_BLOCK_HEADINGS)


def _hypothesis(payload: Mapping[str, object] | None) -> HypothesisSpec | None:
    if payload is None:
        return None
    selected = payload.get("selected_hypothesis")
    if type(selected) is not dict:
        return None
    return HypothesisSpec.hydrate(selected)


def _packet(payload: Mapping[str, object] | None) -> ExperimentResultPacket | None:
    if payload is None:
        return None
    result = payload.get("experiment_result")
    if type(result) is not dict:
        return None
    return ExperimentResultPacket.hydrate(result)


def _view(payload: Mapping[str, object] | None) -> TreatmentMetricView | None:
    if payload is None:
        return None
    raw = payload.get("treatment_metric_view")
    if type(raw) is not dict:
        return None
    return TreatmentMetricView.hydrate(raw)


def _plan(payload: Mapping[str, object] | None) -> ExecutableExperimentPlan | None:
    if payload is None:
        return None
    raw = payload.get("experiment_plan")
    if type(raw) is not dict:
        return None
    return ExecutableExperimentPlan.hydrate(raw)


def _agent_model_input(payload: Mapping[str, object]) -> JsonValue | None:
    if "agent_visible_experiment" not in payload:
        return None
    value = payload["agent_visible_experiment"]
    if type(value) is not dict:
        return None
    return {str(key): _json_scalar_tree(item) for key, item in value.items()}


def _visible_matches_view(value: JsonValue | None, view: TreatmentMetricView | None) -> bool:
    if view is None or type(value) is not dict or not value:
        return False
    return canonical_json_text(value) == canonical_json_text(view.agent_visible_dict())


def _decision_brief(payload: Mapping[str, object] | None) -> DecisionBrief | None:
    if payload is None or "decision_brief" not in payload:
        return None
    try:
        return DecisionBrief.hydrate(payload["decision_brief"])
    except TypeError, ValueError:
        return None


def _report_bound(episode_id: str, payload: Mapping[str, object] | None, markdown: str) -> bool:
    brief = _decision_brief(payload)
    verdict = _arm_verdict(payload)
    if brief is None or verdict is None or brief.verdict.value != verdict:
        return False
    return markdown == render_decision_brief_markdown(episode_id, brief)


def _arm_view_bound(
    hypothesis: HypothesisSpec | None,
    plan: ExecutableExperimentPlan | None,
    packet: ExperimentResultPacket | None,
    view: TreatmentMetricView | None,
    config: ValidationConfig | None,
) -> bool:
    if hypothesis is None or plan is None or packet is None or view is None:
        return False
    metrics = view.metric_map
    bound = (
        view_direction_bound(hypothesis, view)
        and metrics_treatment_control_mirror(metrics)
        and metrics_bound_to_fold_manifest(metrics)
        and metrics_have_authentic_walk_forward(metrics)
    )
    if not bound or config is None:
        return bound
    try:
        recomputed = build_treatment_metric_view(packet, hypothesis=hypothesis, plan=plan, config=config)
    except TypeError, ValueError:
        return False
    return recomputed.content_sha256 == view.content_sha256


def _json_scalar_tree(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (tuple, list)):
        return tuple(_json_scalar_tree(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_scalar_tree(item) for key, item in value.items()}
    raise ValueError("agent-visible payload must be JSON")


def _arm_verdict(payload: Mapping[str, object] | None) -> str | None:
    if payload is None:
        return None
    verdict = payload.get("final_verdict")
    if type(verdict) is not dict:
        return None
    value = verdict.get("verdict")
    return value if type(value) is str else None


def _deterministic_outcome(hypothesis: HypothesisSpec | None, view: TreatmentMetricView | None) -> str | None:
    if hypothesis is None or view is None:
        return None
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        return None
    return evaluate_falsification_predicate(predicate, view).outcome.value


def _verdict_congruent(
    payload: Mapping[str, object] | None,
    hypothesis: HypothesisSpec | None,
    view: TreatmentMetricView | None,
) -> bool:
    expected = _deterministic_outcome(hypothesis, view)
    actual = _arm_verdict(payload)
    if expected is None or actual is None:
        return False
    if actual == "MODIFY":
        verdict = (payload or {}).get("final_verdict")
        if type(verdict) is not dict:
            return False
        return (
            expected == "REJECT"
            and verdict.get("modified_hypothesis") is not None
            and verdict.get("auto_execute_modified") is False
        )
    return actual == expected


def _predicate_metric_binding(hypothesis: HypothesisSpec | None, view: TreatmentMetricView | None) -> bool:
    if hypothesis is None or view is None:
        return False
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        return False
    metrics = view.metric_map
    if hypothesis.primary_metric not in metrics:
        return False
    for clause in predicate.clauses:
        if clause.kind in {
            PredicateClauseKind.EACH_OOS_FOLD_PRIMARY_BEATS_CONTROL,
            PredicateClauseKind.AT_LEAST_N_OOS_FOLDS_ABOVE_THRESHOLD,
        }:
            if clause.metric not in FOLD_METRIC_FIELDS:
                return False
            fold_count = int(metrics.get("fold_count", "0"))
            for index in range(1, fold_count + 1):
                primary, control = fold_metric_fields(clause.metric, index)
                if clause.metric == "signal_accuracy" and (
                    f"fold_{index}_proxy_net_return" in (primary, control) or "stressed" in primary
                ):
                    return False
                if clause.metric == "proxy_net_return" and "signal_accuracy" in primary:
                    return False
    evaluate_falsification_predicate(predicate, view)
    return True


def _lineage_matches_raw(view: TreatmentMetricView | None, packet: ExperimentResultPacket | None) -> bool:
    if view is None or packet is None:
        return False
    if view.raw_packet_digest != packet.content_sha256:
        return False
    try:
        expected = expected_treatment_metric_lineage(packet, view)
    except KeyError, TypeError, ValueError:
        return False
    if view.lineage != expected:
        return False
    for run in packet.tool_runs:
        if type(run) is not ToolRunResult:
            return False
    return True


__all__ = ["FOUR_BLOCK_HEADINGS", "assess_correction_v3_episode", "assess_correction_v5_episode"]
