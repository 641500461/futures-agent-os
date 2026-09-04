"""MVP-R-005 single Research Agent decision brief. Does not mutate R-003/R-004 Evidence."""

from .brief import render_decision_brief_markdown
from .contracts import (
    AGENT_LOOP_ARM,
    FALSIFICATION_REQUIRES_FOLD_ACCURACY,
    FOLD_SIGNAL_ACCURACY_FIELDS,
    SINGLE_PROMPT_ARM,
    DecisionBrief,
    ShadowCritique,
)
from .artifact_checks import assess_correction_v3_episode, assess_correction_v5_episode
from .evidence import (
    PRE_V2_BYTE_STABILITY,
    build_predecessor_hash_manifest,
    predecessor_evidence_status,
    predecessor_hashes_match,
)
from .fallback import fallback_hypothesis
from .formal_eval import BlindSelection, FormalEvalPhase, compute_formal_automated_gate, freeze_blind_selection
from .packet import (
    apply_need_more_data_guard,
    fold_metrics_bound_to_manifest,
    packet_can_evaluate_per_fold_accuracy,
    packet_direction_bound,
    packet_has_authentic_walk_forward,
    packet_has_fold_signal_accuracies,
    packet_treatment_control_mirror,
    requires_per_fold_signal_accuracy,
    resolve_treatment_relative_metrics,
)
from .predicate import (
    FOLD_METRIC_FIELDS,
    FalsificationPredicate,
    PredicateClause,
    PredicateClauseKind,
    PredicateVerdictMismatch,
    bind_falsification_condition,
    evaluate_falsification_predicate,
    fold_metric_fields,
    parse_falsification_condition,
)
from .scorecard import (
    R005CorrectionV2EpisodeOutcome,
    R005CorrectionV3EpisodeOutcome,
    R005EpisodeOutcome,
    compute_r005_correction_v2_gate,
    compute_r005_correction_v3_gate,
    compute_r005_correction_v4_gate,
    compute_r005_correction_v5_gate,
    compute_r005_gate,
)
from .treatment_view import (
    TreatmentMetricView,
    build_treatment_metric_view,
    expected_treatment_metric_lineage,
    raw_tool_runs_untransformed,
    view_has_stopped_fold_leak,
)
from .workloads import MvpR005ModelWorkloads, result_feedback_model_input

__all__ = [
    "AGENT_LOOP_ARM",
    "FALSIFICATION_REQUIRES_FOLD_ACCURACY",
    "FOLD_METRIC_FIELDS",
    "FOLD_SIGNAL_ACCURACY_FIELDS",
    "PRE_V2_BYTE_STABILITY",
    "SINGLE_PROMPT_ARM",
    "DecisionBrief",
    "FalsificationPredicate",
    "MvpR005ModelWorkloads",
    "PredicateClause",
    "PredicateClauseKind",
    "PredicateVerdictMismatch",
    "R005CorrectionV2EpisodeOutcome",
    "R005CorrectionV3EpisodeOutcome",
    "R005EpisodeOutcome",
    "ShadowCritique",
    "TreatmentMetricView",
    "apply_need_more_data_guard",
    "assess_correction_v3_episode",
    "assess_correction_v5_episode",
    "bind_falsification_condition",
    "build_predecessor_hash_manifest",
    "build_treatment_metric_view",
    "expected_treatment_metric_lineage",
    "compute_r005_correction_v2_gate",
    "compute_r005_correction_v3_gate",
    "compute_r005_correction_v4_gate",
    "compute_r005_correction_v5_gate",
    "compute_r005_gate",
    "evaluate_falsification_predicate",
    "fallback_hypothesis",
    "BlindSelection",
    "FormalEvalPhase",
    "compute_formal_automated_gate",
    "freeze_blind_selection",
    "fold_metric_fields",
    "fold_metrics_bound_to_manifest",
    "packet_can_evaluate_per_fold_accuracy",
    "packet_direction_bound",
    "packet_has_authentic_walk_forward",
    "packet_has_fold_signal_accuracies",
    "packet_treatment_control_mirror",
    "parse_falsification_condition",
    "predecessor_evidence_status",
    "predecessor_hashes_match",
    "raw_tool_runs_untransformed",
    "render_decision_brief_markdown",
    "requires_per_fold_signal_accuracy",
    "resolve_treatment_relative_metrics",
    "result_feedback_model_input",
    "view_has_stopped_fold_leak",
]
