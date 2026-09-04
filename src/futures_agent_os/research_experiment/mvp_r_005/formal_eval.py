"""Frozen automated gates and blind selection for the post-R-005 formal MVP-R eval."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from .scorecard import R005CorrectionV3EpisodeOutcome


class FormalEvalPhase(StrEnum):
    DIAGNOSTIC = "diagnostic"
    HOLDOUT = "holdout"

    @property
    def episode_count(self) -> int:
        return 30 if self is FormalEvalPhase.DIAGNOSTIC else 50

    @property
    def minimum_complete(self) -> int:
        return 29 if self is FormalEvalPhase.DIAGNOSTIC else 49

    @property
    def token_limit(self) -> int:
        return 4_000_000 if self is FormalEvalPhase.DIAGNOSTIC else 7_000_000

    @property
    def wall_time_limit_ms(self) -> int:
        hours = 4 if self is FormalEvalPhase.DIAGNOSTIC else 6
        return hours * 60 * 60 * 1_000

    @property
    def pass_decision(self) -> str:
        return f"FORMAL_{self.value.upper()}_PASS"

    @property
    def fail_decision(self) -> str:
        return f"FORMAL_{self.value.upper()}_FAIL"


@dataclass(frozen=True, slots=True)
class BlindSelection:
    episode_id: str
    agent_label: str
    single_prompt_label: str

    def to_dict(self) -> dict[str, str]:
        return {
            "episode_id": self.episode_id,
            "agent_label": self.agent_label,
            "single_prompt_label": self.single_prompt_label,
        }


def compute_formal_automated_gate(
    episodes: tuple[R005CorrectionV3EpisodeOutcome, ...],
    *,
    phase: FormalEvalPhase,
    total_tokens: int,
    model_wall_time_ms: int,
    critical_fail_closed: int,
    predecessor_hashes_match: bool,
) -> dict[str, object]:
    """Compute the preregistered machine gate without converting missing rows into good rows."""

    expected = phase.episode_count
    if len(episodes) != expected:
        raise ValueError(f"formal {phase.value} gate requires exactly {expected} episodes")
    if total_tokens < 0 or model_wall_time_ms < 0:
        raise ValueError("usage values cannot be negative")
    if type(predecessor_hashes_match) is not bool:
        raise TypeError("predecessor hash comparison must be boolean")

    complete = tuple(item for item in episodes if item.complete)
    complete_count = len(complete)
    exact_checks = {
        "agent_loop_complete": sum(item.agent_loop_complete for item in complete),
        "experiments_run": sum(item.agent_experiment_complete for item in complete),
        "single_prompt_complete": sum(item.single_prompt_complete for item in complete),
        "raw_packet_to_view_lineage": sum(item.raw_packet_to_view_lineage for item in complete),
        "predicate_metric_binding": sum(item.predicate_metric_binding for item in complete),
        "verdict_predicate_congruence": sum(item.verdict_predicate_congruent for item in complete),
        "four_block_reports": sum(item.four_block_report for item in complete),
        "stopped_folds_invisible": sum(item.stopped_folds_invisible for item in complete),
        "treatment_view_bound": sum(item.treatment_view_bound for item in complete),
    }
    pre_gates = sum(item.pre_experiment_critic_gate for item in episodes)
    blocked = sum(item.critic_blocked_experiment for item in episodes)
    overlap = sum(item.overlapping_predecessor for item in episodes)

    reasons: list[str] = []
    if complete_count < phase.minimum_complete:
        reasons.append(f"complete {complete_count}/{expected}, minimum {phase.minimum_complete}")
    for name, count in exact_checks.items():
        if count != complete_count:
            reasons.append(f"{name} {count}/{complete_count} completed episodes")
    if pre_gates:
        reasons.append(f"pre-experiment critic gate present {pre_gates}/{expected}")
    if blocked:
        reasons.append(f"critic blocked experiments {blocked}")
    if overlap:
        reasons.append(f"predecessor/formal roster overlap {overlap}/{expected}")
    if critical_fail_closed != 4:
        reasons.append(f"critical fail-closed {critical_fail_closed}/4")
    if not predecessor_hashes_match:
        reasons.append("predecessor hashes changed")
    if total_tokens > phase.token_limit:
        reasons.append(f"token budget {total_tokens}/{phase.token_limit}")
    if model_wall_time_ms > phase.wall_time_limit_ms:
        reasons.append(f"model wall-time budget {model_wall_time_ms}/{phase.wall_time_limit_ms} ms")

    return {
        "schema_version": "mvp-r.formal-automated-gate.v1",
        "phase": phase.value,
        "episode_count": expected,
        "complete": f"{complete_count}/{expected}",
        "minimum_complete": phase.minimum_complete,
        **{name: f"{count}/{complete_count}" for name, count in exact_checks.items()},
        "pre_experiment_critic_gate": f"{pre_gates}/{expected}",
        "critic_blocked_experiments": blocked,
        "predecessor_or_formal_overlap": f"{overlap}/{expected}",
        "critical_fail_closed": f"{critical_fail_closed}/4",
        "predecessor_hashes_match": predecessor_hashes_match,
        "total_tokens": total_tokens,
        "token_limit": phase.token_limit,
        "model_wall_time_ms": model_wall_time_ms,
        "model_wall_time_limit_ms": phase.wall_time_limit_ms,
        "decision": phase.pass_decision if not reasons else phase.fail_decision,
        "decision_reasons": tuple(reasons),
        "hardcoded": False,
        "go": False,
        "user_shadow_required": phase is FormalEvalPhase.HOLDOUT,
    }


def freeze_blind_selection(completed_episode_ids: tuple[str, ...], *, seed: str) -> tuple[BlindSelection, ...]:
    """Select ten stable A/B packets without relying on filesystem or PRNG state."""

    unique = tuple(sorted(set(completed_episode_ids)))
    if len(unique) < 10:
        raise ValueError("at least 10 completed holdout episodes are required")
    ranked = sorted(unique, key=lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest())[:10]
    selections = []
    for index, episode_id in enumerate(ranked):
        agent_label = "A" if index < 5 else "B"
        selections.append(
            BlindSelection(
                episode_id=episode_id,
                agent_label=agent_label,
                single_prompt_label="B" if agent_label == "A" else "A",
            )
        )
    return tuple(selections)
