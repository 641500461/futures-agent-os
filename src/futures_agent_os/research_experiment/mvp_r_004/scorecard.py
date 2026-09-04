"""Compute Discovery/canary gates from labeled metrics. Never hardcode the decision."""

from __future__ import annotations

from dataclasses import dataclass

from futures_agent_os.research_experiment.mvp_r_003.contracts import CriticDecision

from .contracts import GoldLabel


@dataclass(frozen=True, slots=True)
class LabeledCriticOutcome:
    episode_id: str
    label: GoldLabel
    expected_decision: str
    actual_decision: str


@dataclass(frozen=True, slots=True)
class CanaryEpisodeOutcome:
    episode_id: str
    instrument: str
    stratum: str
    gold_clean_decision: str
    gold_bad_decision: str
    full_arm_complete: bool
    experiment_ran: bool
    result_feedback_present: bool
    agent_hypothesis_count: int


def gold_retention_recall(
    outcomes: tuple[LabeledCriticOutcome, ...],
) -> dict[str, str | int | bool]:
    clean = tuple(item for item in outcomes if item.label is GoldLabel.CLEAN)
    bad = tuple(item for item in outcomes if item.label is GoldLabel.BAD)
    if not clean or not bad:
        raise ValueError("gold metrics require both CLEAN and BAD labels")
    retained = sum(item.actual_decision == CriticDecision.SELECT.value for item in clean)
    false_selected_bad = sum(item.actual_decision == CriticDecision.SELECT.value for item in bad)
    caught_bad = sum(item.actual_decision == CriticDecision.REJECT.value for item in bad)
    return {
        "gold_clean_count": len(clean),
        "gold_bad_count": len(bad),
        "clean_retention": f"{retained}/{len(clean)}",
        "clean_retention_pass": retained == len(clean),
        "bad_recall": f"{caught_bad}/{len(bad)}",
        "bad_selected_into_experiment": false_selected_bad,
        "bad_exclusion_pass": false_selected_bad == 0,
    }


def compute_canary_gate(
    episodes: tuple[CanaryEpisodeOutcome, ...],
    labeled: tuple[LabeledCriticOutcome, ...],
) -> dict[str, object]:
    if len(episodes) != 2:
        raise ValueError("canary gate requires exactly two episodes")
    gold = gold_retention_recall(labeled)
    full = sum(item.full_arm_complete for item in episodes)
    experiments = sum(item.experiment_ran for item in episodes)
    feedback = sum(item.result_feedback_present for item in episodes)
    reasons: list[str] = []
    if full != 2:
        reasons.append(f"full arm complete {full}/2")
    if experiments != 2:
        reasons.append(f"selected experiments actually run {experiments}/2")
    if feedback != 2:
        reasons.append(f"result feedback present {feedback}/2")
    if not gold["clean_retention_pass"]:
        reasons.append(f"gold clean retention {gold['clean_retention']} is below 2/2")
    if not gold["bad_exclusion_pass"]:
        reasons.append("gold BAD hypotheses were selected into experiments")
    return {
        "schema_version": "mvp-r-004.canary-gate.v1",
        "full_arm_complete": f"{full}/2",
        "experiments_run": f"{experiments}/2",
        "result_feedback_present": f"{feedback}/2",
        **gold,
        "decision": "CANARY_PASS" if not reasons else "CANARY_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
    }


@dataclass(frozen=True, slots=True)
class DiscoveryEpisodeOutcome:
    episode_id: str
    instrument: str
    stratum: str
    market_cutoff: str
    repaired: bool
    complete: bool
    executable_count: int
    gold_clean_decision: str
    gold_bad_decision: str
    without_experiment_complete: bool
    full_arm_complete: bool
    critic_selected_agent: int
    selected_experiments_run: int
    template_verdict: str | None
    single_prompt_verdict: str | None
    without_verdict: str | None
    full_arm_verdict: str | None
    agent_hypothesis_count: int


def _ratio_pass(count: int, total: int, numerator: int, denominator: int) -> bool:
    if total < 1:
        return False
    return count * denominator >= total * numerator


COMPLETE_FLOW_ARM = "research_critic_result_feedback"
SINGLE_PROMPT_ARM = "single_prompt_analyst"
TEMPLATE_ARM = "deterministic_template"
WITHOUT_CRITIC_ARM = "research_without_critic"


@dataclass(frozen=True, slots=True)
class UserBlindEpisode:
    episode_id: str
    preferred_label: str
    preferred_arm: str
    understandable_without_extra_explanation: bool
    clearly_saves_research_time: bool
    leads_to_clear_action: bool


def compute_user_blind_gate(episodes: tuple[UserBlindEpisode, ...]) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("user blind eval requires exactly eight episodes")
    complete_preferred = sum(item.preferred_arm == COMPLETE_FLOW_ARM for item in episodes)
    single_preferred = sum(item.preferred_arm == SINGLE_PROMPT_ARM for item in episodes)
    template_preferred = sum(item.preferred_arm == TEMPLATE_ARM for item in episodes)
    without_preferred = sum(item.preferred_arm == WITHOUT_CRITIC_ARM for item in episodes)
    understandable = sum(item.understandable_without_extra_explanation for item in episodes)
    saves_time = sum(item.clearly_saves_research_time for item in episodes)
    clear_action = sum(item.leads_to_clear_action for item in episodes)
    complete_pass = complete_preferred >= 6
    understandable_pass = understandable >= 6
    saves_time_pass = saves_time >= 4
    action_pass = clear_action >= 3
    reasons: list[str] = []
    if not complete_pass:
        reasons.append(f"complete flow preferred {complete_preferred}/8 is below the 6/8 user-value gate")
    if not understandable_pass:
        reasons.append(f"understandable without extra explanation {understandable}/8 is below 6/8")
    if not saves_time_pass:
        reasons.append(f"clearly saves research time {saves_time}/8 is below 4/8")
    if not action_pass:
        reasons.append(f"leads to a clear next research action {clear_action}/8 is below 3/8")
    failed = bool(reasons)
    pivot_triggers = []
    if complete_preferred < 6:
        pivot_triggers.append("complete flow preference below 6/8")
    if complete_preferred <= single_preferred:
        pivot_triggers.append("complete flow was not preferred over single-prompt")
    return {
        "schema_version": "mvp-r-004.user-blind-gate.v1",
        "complete_flow_preferred": f"{complete_preferred}/8",
        "complete_flow_preferred_pass": complete_pass,
        "single_prompt_preferred": f"{single_preferred}/8",
        "template_preferred": f"{template_preferred}/8",
        "without_critic_preferred": f"{without_preferred}/8",
        "understandable_without_extra_explanation": f"{understandable}/8",
        "understandable_pass": understandable_pass,
        "clearly_saves_research_time": f"{saves_time}/8",
        "saves_time_pass": saves_time_pass,
        "leads_to_clear_action": f"{clear_action}/8",
        "clear_action_pass": action_pass,
        "decision": "USER_VALUE_FAIL" if failed else "USER_VALUE_PASS",
        "decision_reasons": tuple(reasons),
        "product_stop": "STOP/PIVOT" if failed else "NONE",
        "pivot_triggers": tuple(pivot_triggers),
        "hardcoded": False,
    }


def compute_discovery_gate(
    episodes: tuple[DiscoveryEpisodeOutcome, ...],
    labeled: tuple[LabeledCriticOutcome, ...],
    *,
    user_blind_eval: str = "NOT_STARTED",
) -> dict[str, object]:
    if len(episodes) != 8:
        raise ValueError("discovery gate requires exactly eight episodes")
    gold = gold_retention_recall(labeled)
    retained = int(str(gold["clean_retention"]).split("/", 1)[0])
    caught = int(str(gold["bad_recall"]).split("/", 1)[0])
    gold_clean_total = int(gold["gold_clean_count"])
    gold_bad_total = int(gold["gold_bad_count"])
    gold_clean_pass = _ratio_pass(retained, gold_clean_total, 3, 4)
    gold_recall_pass = _ratio_pass(caught, gold_bad_total, 9, 10)
    unattended = sum(item.complete and not item.repaired for item in episodes)
    executable_episodes = sum(item.executable_count > 0 for item in episodes)
    without_experiments = sum(item.without_experiment_complete for item in episodes)
    full_experiments = sum(item.full_arm_complete for item in episodes)
    selected = sum(item.critic_selected_agent for item in episodes)
    selected_episodes = sum(item.critic_selected_agent > 0 for item in episodes)
    selected_run = sum(item.selected_experiments_run > 0 for item in episodes)
    selected_all_run = all(
        (item.critic_selected_agent > 0 and item.selected_experiments_run > 0 and item.full_arm_complete)
        or (item.critic_selected_agent == 0 and item.selected_experiments_run == 0)
        for item in episodes
    )
    template_vs_single = sum(
        item.template_verdict is not None and item.template_verdict == item.single_prompt_verdict for item in episodes
    )
    complete = sum(item.complete for item in episodes)
    reasons: list[str] = []
    if complete != 8:
        reasons.append(f"complete {complete}/8")
    if unattended < 7:
        reasons.append(f"unattended complete {unattended}/8 is below the 7/8 hard gate")
    if executable_episodes < 6:
        reasons.append(f"executable-hypothesis episodes {executable_episodes}/8 is below the 6/8 hard gate")
    if without_experiments != 8:
        reasons.append(f"research-without-critic experiments {without_experiments}/8")
    if not selected_all_run:
        reasons.append(f"first selected hypothesis experiments actually run {selected_run}/{selected_episodes}")
    if not gold_clean_pass:
        reasons.append(f"gold clean retention {gold['clean_retention']} is below 75%")
    if not gold["bad_exclusion_pass"]:
        reasons.append("gold BAD hypotheses were selected into experiments")
    if not gold_recall_pass:
        reasons.append(f"gold bad recall {gold['bad_recall']} is below 90%")
    return {
        "schema_version": "mvp-r-004.discovery-gate.v1",
        "complete": f"{complete}/8",
        "unattended_complete": f"{unattended}/8",
        "unattended_complete_pass": unattended >= 7 and complete == 8,
        "executable_hypothesis_episodes": f"{executable_episodes}/8",
        "executable_hypothesis_pass": executable_episodes >= 6,
        "without_critic_experiments_complete": f"{without_experiments}/8",
        "full_arm_experiments_complete": f"{full_experiments}/8",
        "critic_select_count": selected,
        "selected_episodes": selected_episodes,
        "selected_experiments_run": selected_run,
        "selected_experiments_all_run": selected_all_run,
        "template_single_prompt_agreement": f"{template_vs_single}/8",
        "user_blind_eval": user_blind_eval,
        **gold,
        "clean_retention_pass": gold_clean_pass,
        "bad_recall_pass": gold_recall_pass,
        "decision": "DISCOVERY_PASS" if not reasons else "DISCOVERY_FAIL",
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
    }
