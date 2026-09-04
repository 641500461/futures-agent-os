"""Compute the MVP-R-005 gate from labeled metrics. Never hardcode the decision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class R005EpisodeOutcome:
    episode_id: str
    instrument: str
    stratum: str
    market_cutoff: str
    complete: bool
    agent_loop_complete: bool
    agent_experiment_complete: bool
    single_prompt_complete: bool
    pre_experiment_critic_gate: bool
    critic_blocked_experiment: bool
    shadow_ran: bool
    shadow_would_have_blocked: bool
    packet_has_fold_signal_accuracy: bool
    four_block_report: bool
    overlapping_predecessor: bool
    agent_verdict: str | None
    single_prompt_verdict: str | None


def compute_r005_gate(episodes: tuple[R005EpisodeOutcome, ...]) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("R-005 gate requires exactly eight episodes")
    complete = sum(item.complete for item in episodes)
    agent_complete = sum(item.agent_loop_complete for item in episodes)
    experiments = sum(item.agent_experiment_complete for item in episodes)
    single = sum(item.single_prompt_complete for item in episodes)
    pre_gates = sum(item.pre_experiment_critic_gate for item in episodes)
    blocked = sum(item.critic_blocked_experiment for item in episodes)
    shadow = sum(item.shadow_ran for item in episodes)
    fold_packets = sum(item.packet_has_fold_signal_accuracy for item in episodes)
    four_blocks = sum(item.four_block_report for item in episodes)
    overlap = sum(item.overlapping_predecessor for item in episodes)
    reasons: list[str] = []
    if complete != 8:
        reasons.append(f"complete {complete}/8")
    if agent_complete != 8:
        reasons.append(f"research agent loop complete {agent_complete}/8")
    if experiments != 8:
        reasons.append(f"deterministic experiments run {experiments}/8")
    if single != 8:
        reasons.append(f"single-prompt baseline complete {single}/8")
    if pre_gates != 0:
        reasons.append(f"pre-experiment critic gate present {pre_gates}/8")
    if blocked != 0:
        reasons.append(f"critic blocked experiments {blocked}")
    if shadow != 8:
        reasons.append(f"shadow critic recorded {shadow}/8")
    if fold_packets != 8:
        reasons.append(f"packets with per-fold signal_accuracy {fold_packets}/8")
    if four_blocks != 8:
        reasons.append(f"four-block user reports {four_blocks}/8")
    if overlap != 0:
        reasons.append(f"predecessor window overlap {overlap}/8")
    return {
        "schema_version": "mvp-r-005.discovery-gate.v1",
        "complete": f"{complete}/8",
        "agent_loop_complete": f"{agent_complete}/8",
        "experiments_run": f"{experiments}/8",
        "single_prompt_complete": f"{single}/8",
        "pre_experiment_critic_gate": f"{pre_gates}/8",
        "critic_blocked_experiments": blocked,
        "shadow_critic_recorded": f"{shadow}/8",
        "packets_with_fold_signal_accuracy": f"{fold_packets}/8",
        "four_block_reports": f"{four_blocks}/8",
        "predecessor_overlap": f"{overlap}/8",
        "decision": "R005_PASS" if not reasons else "R005_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
        "not_go": True,
        "independent_real_user_validation": False,
    }


@dataclass(frozen=True, slots=True)
class R005CorrectionV2EpisodeOutcome:
    episode_id: str
    instrument: str
    stratum: str
    market_cutoff: str
    complete: bool
    agent_loop_complete: bool
    agent_experiment_complete: bool
    single_prompt_complete: bool
    pre_experiment_critic_gate: bool
    critic_blocked_experiment: bool
    shadow_ran: bool
    shadow_would_have_blocked: bool
    direction_bound: bool
    treatment_control_mirror: bool
    authentic_walk_forward_manifest: bool
    fold_metrics_bound_to_manifest: bool
    verdict_predicate_congruent: bool
    four_block_report: bool
    overlapping_predecessor: bool
    agent_verdict: str | None
    single_prompt_verdict: str | None
    deterministic_agent_outcome: str | None
    deterministic_single_outcome: str | None


def compute_r005_correction_v2_gate(episodes: tuple[R005CorrectionV2EpisodeOutcome, ...]) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("R-005 correction-v2 gate requires exactly eight episodes")
    complete = sum(item.complete for item in episodes)
    agent_complete = sum(item.agent_loop_complete for item in episodes)
    experiments = sum(item.agent_experiment_complete for item in episodes)
    single = sum(item.single_prompt_complete for item in episodes)
    pre_gates = sum(item.pre_experiment_critic_gate for item in episodes)
    blocked = sum(item.critic_blocked_experiment for item in episodes)
    direction = sum(item.direction_bound for item in episodes)
    mirror = sum(item.treatment_control_mirror for item in episodes)
    authentic = sum(item.authentic_walk_forward_manifest for item in episodes)
    fold_bound = sum(item.fold_metrics_bound_to_manifest for item in episodes)
    congruent = sum(item.verdict_predicate_congruent for item in episodes)
    four_blocks = sum(item.four_block_report for item in episodes)
    overlap = sum(item.overlapping_predecessor for item in episodes)
    reasons: list[str] = []
    if complete != 8:
        reasons.append(f"complete {complete}/8")
    if agent_complete != 8:
        reasons.append(f"research agent loop complete {agent_complete}/8")
    if experiments != 8:
        reasons.append(f"deterministic experiments run {experiments}/8")
    if single != 8:
        reasons.append(f"single-prompt baseline complete {single}/8")
    if direction != 8:
        reasons.append(f"direction binding {direction}/8")
    if mirror != 8:
        reasons.append(f"treatment/control semantic mirror {mirror}/8")
    if authentic != 8:
        reasons.append(f"authentic walk-forward fold manifest {authentic}/8")
    if fold_bound != 8:
        reasons.append(f"fold metrics bound to manifest {fold_bound}/8")
    if congruent != 8:
        reasons.append(f"verdict/predicate congruence {congruent}/8")
    if four_blocks != 8:
        reasons.append(f"four-block user reports {four_blocks}/8")
    if pre_gates != 0:
        reasons.append(f"pre-experiment critic gate present {pre_gates}/8")
    if blocked != 0:
        reasons.append(f"critic blocked experiments {blocked}")
    if overlap != 0:
        reasons.append(f"predecessor window overlap {overlap}/8")
    return {
        "schema_version": "mvp-r-005.correction-v2-gate.v1",
        "complete": f"{complete}/8",
        "agent_loop_complete": f"{agent_complete}/8",
        "experiments_run": f"{experiments}/8",
        "single_prompt_complete": f"{single}/8",
        "direction_binding": f"{direction}/8",
        "treatment_control_semantic_mirror": f"{mirror}/8",
        "authentic_walk_forward_fold_manifest": f"{authentic}/8",
        "fold_metrics_manifest_binding": f"{fold_bound}/8",
        "verdict_predicate_congruence": f"{congruent}/8",
        "four_block_reports": f"{four_blocks}/8",
        "pre_experiment_critic_gate": f"{pre_gates}/8",
        "critic_blocked_experiments": blocked,
        "predecessor_overlap": f"{overlap}/8",
        "predecessor_evidence_untouched": overlap == 0,
        "decision": "R005_CORRECTION_V2_PASS" if not reasons else "R005_CORRECTION_V2_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
        "not_go": True,
        "independent_real_user_validation": False,
    }


@dataclass(frozen=True, slots=True)
class R005CorrectionV3EpisodeOutcome:
    episode_id: str
    instrument: str
    stratum: str
    market_cutoff: str
    complete: bool
    agent_loop_complete: bool
    agent_experiment_complete: bool
    single_prompt_complete: bool
    raw_tool_result_lineage: bool
    predicate_metric_binding: bool
    verdict_predicate_congruent: bool
    four_block_report: bool
    pre_experiment_critic_gate: bool
    critic_blocked_experiment: bool
    overlapping_predecessor: bool
    stopped_folds_invisible: bool
    treatment_view_bound: bool
    agent_verdict: str | None
    single_prompt_verdict: str | None
    deterministic_agent_outcome: str | None
    deterministic_single_outcome: str | None

    @property
    def raw_packet_to_view_lineage(self) -> bool:
        """Honest scope: packet projection to treatment view, not source-ref authenticity."""
        return self.raw_tool_result_lineage


def compute_r005_correction_v3_gate(
    episodes: tuple[R005CorrectionV3EpisodeOutcome, ...],
    *,
    v3_predecessor_hashes_match: bool,
    pre_v2_byte_stability: str = "NOT_PROVEN",
) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("R-005 correction-v3 gate requires exactly eight episodes")
    if pre_v2_byte_stability != "NOT_PROVEN":
        raise ValueError("pre-v2 byte stability has no machine baseline and must be NOT_PROVEN")
    if type(v3_predecessor_hashes_match) is not bool:
        raise TypeError("v3 predecessor hash match must be a boolean")
    complete = sum(item.complete for item in episodes)
    agent_complete = sum(item.agent_loop_complete for item in episodes)
    experiments = sum(item.agent_experiment_complete for item in episodes)
    single = sum(item.single_prompt_complete for item in episodes)
    lineage = sum(item.raw_tool_result_lineage for item in episodes)
    binding = sum(item.predicate_metric_binding for item in episodes)
    congruent = sum(item.verdict_predicate_congruent for item in episodes)
    four_blocks = sum(item.four_block_report for item in episodes)
    pre_gates = sum(item.pre_experiment_critic_gate for item in episodes)
    blocked = sum(item.critic_blocked_experiment for item in episodes)
    overlap = sum(item.overlapping_predecessor for item in episodes)
    invisible = sum(item.stopped_folds_invisible for item in episodes)
    views = sum(item.treatment_view_bound for item in episodes)
    reasons: list[str] = []
    if complete != 8:
        reasons.append(f"complete {complete}/8")
    if agent_complete != 8:
        reasons.append(f"research agent loop complete {agent_complete}/8")
    if experiments != 8:
        reasons.append(f"deterministic experiments run {experiments}/8")
    if single != 8:
        reasons.append(f"single-prompt baseline complete {single}/8")
    if lineage != 8:
        reasons.append(f"raw tool result lineage {lineage}/8")
    if binding != 8:
        reasons.append(f"predicate metric binding {binding}/8")
    if congruent != 8:
        reasons.append(f"verdict/predicate congruence {congruent}/8")
    if four_blocks != 8:
        reasons.append(f"four-block user reports {four_blocks}/8")
    if pre_gates != 0:
        reasons.append(f"pre-experiment critic gate present {pre_gates}/8")
    if blocked != 0:
        reasons.append(f"critic blocked experiments {blocked}")
    if overlap != 0:
        reasons.append(f"predecessor window overlap {overlap}/8")
    if invisible != 8:
        reasons.append(f"stopped folds invisible {invisible}/8")
    if views != 8:
        reasons.append(f"treatment view bound {views}/8")
    if v3_predecessor_hashes_match is False:
        reasons.append("v3 predecessor hashes match false")
    return {
        "schema_version": "mvp-r-005.correction-v3-gate.v1",
        "complete": f"{complete}/8",
        "agent_loop_complete": f"{agent_complete}/8",
        "experiments_run": f"{experiments}/8",
        "single_prompt_complete": f"{single}/8",
        "raw_tool_result_lineage": f"{lineage}/8",
        "predicate_metric_binding": f"{binding}/8",
        "verdict_predicate_congruence": f"{congruent}/8",
        "four_block_reports": f"{four_blocks}/8",
        "pre_experiment_critic_gate": f"{pre_gates}/8",
        "critic_blocked_experiments": blocked,
        "predecessor_window_overlap": f"{overlap}/8",
        "stopped_folds_invisible": f"{invisible}/8",
        "treatment_view_bound": f"{views}/8",
        "v3_predecessor_hashes_match": v3_predecessor_hashes_match,
        "pre_v2_byte_stability": pre_v2_byte_stability,
        "decision": "R005_CORRECTION_V3_PASS" if not reasons else "R005_CORRECTION_V3_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
        "not_go": True,
        "independent_real_user_validation": False,
    }


def compute_r005_correction_v4_gate(
    episodes: tuple[R005CorrectionV3EpisodeOutcome, ...],
    *,
    v4_predecessor_hashes_match: bool,
) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("R-005 correction-v4 gate requires exactly eight episodes")
    if type(v4_predecessor_hashes_match) is not bool:
        raise TypeError("v4 predecessor hash match must be a boolean")
    complete = sum(item.complete for item in episodes)
    agent_complete = sum(item.agent_loop_complete for item in episodes)
    experiments = sum(item.agent_experiment_complete for item in episodes)
    single = sum(item.single_prompt_complete for item in episodes)
    lineage = sum(item.raw_packet_to_view_lineage for item in episodes)
    binding = sum(item.predicate_metric_binding for item in episodes)
    congruent = sum(item.verdict_predicate_congruent for item in episodes)
    four_blocks = sum(item.four_block_report for item in episodes)
    pre_gates = sum(item.pre_experiment_critic_gate for item in episodes)
    blocked = sum(item.critic_blocked_experiment for item in episodes)
    overlap = sum(item.overlapping_predecessor for item in episodes)
    invisible = sum(item.stopped_folds_invisible for item in episodes)
    views = sum(item.treatment_view_bound for item in episodes)
    reasons: list[str] = []
    checks = (
        (complete == 8, f"complete {complete}/8"),
        (agent_complete == 8, f"research agent loop complete {agent_complete}/8"),
        (experiments == 8, f"deterministic experiments run {experiments}/8"),
        (single == 8, f"single-prompt baseline complete {single}/8"),
        (lineage == 8, f"raw packet to view lineage {lineage}/8"),
        (binding == 8, f"predicate metric binding {binding}/8"),
        (congruent == 8, f"verdict/predicate congruence {congruent}/8"),
        (four_blocks == 8, f"four-block user reports {four_blocks}/8"),
        (pre_gates == 0, f"pre-experiment critic gate present {pre_gates}/8"),
        (blocked == 0, f"critic blocked experiments {blocked}"),
        (overlap == 0, f"predecessor window overlap {overlap}/8"),
        (invisible == 8, f"stopped folds invisible {invisible}/8"),
        (views == 8, f"treatment view bound {views}/8"),
        (v4_predecessor_hashes_match, "v4 predecessor hashes match false"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    return {
        "schema_version": "mvp-r-005.correction-v4-gate.v1",
        "complete": f"{complete}/8",
        "agent_loop_complete": f"{agent_complete}/8",
        "experiments_run": f"{experiments}/8",
        "single_prompt_complete": f"{single}/8",
        "raw_packet_to_view_lineage": f"{lineage}/8",
        "predicate_metric_binding": f"{binding}/8",
        "verdict_predicate_congruence": f"{congruent}/8",
        "four_block_reports": f"{four_blocks}/8",
        "pre_experiment_critic_gate": f"{pre_gates}/8",
        "critic_blocked_experiments": blocked,
        "predecessor_window_overlap": f"{overlap}/8",
        "stopped_folds_invisible": f"{invisible}/8",
        "treatment_view_bound": f"{views}/8",
        "v4_predecessor_hashes_match": v4_predecessor_hashes_match,
        "decision": "R005_CORRECTION_V4_PASS" if not reasons else "R005_CORRECTION_V4_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
        "not_go": True,
        "independent_real_user_validation": False,
    }


def compute_r005_correction_v5_gate(
    episodes: tuple[R005CorrectionV3EpisodeOutcome, ...],
    *,
    v5_predecessor_hashes_match: bool,
) -> dict[str, object]:
    gate = compute_r005_correction_v4_gate(
        episodes,
        v4_predecessor_hashes_match=v5_predecessor_hashes_match,
    )
    gate["schema_version"] = "mvp-r-005.correction-v5-gate.v1"
    gate["v5_predecessor_hashes_match"] = gate.pop("v4_predecessor_hashes_match")
    reasons = gate["decision_reasons"]
    if type(reasons) is not tuple or any(type(reason) is not str for reason in reasons):
        raise TypeError("correction-v5 gate reasons must be text")
    gate["decision_reasons"] = tuple(reason.replace("v4 predecessor", "v5 predecessor") for reason in reasons)
    gate["decision"] = (
        "R005_CORRECTION_V5_PASS" if gate["decision"] == "R005_CORRECTION_V4_PASS" else "R005_CORRECTION_V5_FAIL"
    )
    return gate
