"""Score the frozen MVP-R Pivot retrospective confirmation holdout."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, fields
from decimal import Decimal
from pathlib import Path
from typing import cast

import run_mvp_r_pivot as runner
import run_mvp_r_replay as legacy

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment import (
    EpisodeStratum,
    HypothesisFamily,
    PivotMachineResearchHandoff,
    ReplayEpisodeCandidate,
    screen_hypothesis_families,
    strongest_deterministic_family,
)
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


DEFAULT_DATA_ROOT = runner.DATA_ROOT / "pivot-retrospective-2025"


@dataclass(frozen=True, slots=True)
class RetrospectiveHoldoutRow:
    episode_id: str
    instrument_id: str
    stratum: str
    status: str
    failure_code: str | None
    critical_scenario: bool
    critical_zero_token_refusal: bool
    conclusion_kind: str | None
    hypothesis_family: str
    hypothesis_complete: bool
    raw_agent_opportunity: bool
    agent_without_independent_critic_opportunity: bool
    independent_critic_accepted_opportunity: bool
    independent_critic_invoked: bool
    independent_critic_failed: bool
    strongest_family_baseline_opportunity: bool
    raw_agent_future_direction_consistent: bool
    agent_without_independent_critic_future_direction_consistent: bool
    baseline_future_direction_consistent: bool
    machine_handoff_valid: bool
    machine_handoff_decision: str | None
    fault_count: int
    fault_caught_count: int
    duration_ms: int
    total_tokens: int

    def payload(self) -> dict[str, JsonValue]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-sha256", required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    run_dir = data_root / "runs" / args.suite_sha256 / "pivot-historical-holdout" / "historical-holdout"
    runs = {
        item["episode_id"]: item
        for path in sorted(run_dir.glob("evaluation_episode_*.json"))
        for item in (json.loads(path.read_text(encoding="utf-8")),)
    }
    if len(runs) != 50:
        raise SystemExit(f"expected fifty historical holdout artifacts, found {len(runs)}")

    roster = json.loads((run_dir / "roster.json").read_text(encoding="utf-8"))
    candidates = _roster_candidates(roster, data_root)
    config = legacy._validation_config()
    cost = (config.round_trip_cost_bps + config.slippage_bps) / Decimal(10_000)
    rows: list[RetrospectiveHoldoutRow] = []
    for episode_id, candidate in candidates:
        run = runs[episode_id]
        screens = screen_hypothesis_families(
            candidate.records,
            signal_threshold=config.signal_threshold,
            per_signal_cost=cost,
        )
        screen_by_family = {screen.family: screen for screen in screens}
        baseline_screen = strongest_deterministic_family(
            screens,
            minimum_signal_count=runner.MINIMUM_SIGNAL_COUNT,
            minimum_accuracy=runner.MINIMUM_ACCURACY,
            minimum_positive_fold_ratio=runner.MINIMUM_POSITIVE_FOLD_RATIO,
        )
        conclusion = run.get("conclusion") or {}
        hypothesis = conclusion.get("hypothesis") or {}
        family_text = hypothesis.get("family")
        agent_family = HypothesisFamily(family_text) if type(family_text) is str else HypothesisFamily.NONE
        agent_screen = screen_by_family.get(agent_family)
        raw_agent_opportunity = conclusion.get("kind") == "OPPORTUNITY_CANDIDATE"
        deterministic_accepted = bool(
            raw_agent_opportunity and (run.get("deterministic_critique") or {}).get("accepted") is True
        )
        independent_review = run.get("independent_critic") or {}
        final_accepted = bool(deterministic_accepted and independent_review.get("decision") == "ACCEPT")
        future_return = (
            Decimal(str(candidate.future_record.values["close"])) / Decimal(str(candidate.records[-1].values["close"]))
            - 1
        )
        total_tokens = sum(sum(usage[:2]) for usage in run.get("research_usage") or ()) + sum(
            (run.get("critic_usage") or ())[:2]
        )
        handoff_valid = False
        handoff_decision = None
        handoff = run.get("machine_handoff")
        if handoff is not None:
            hydrated = PivotMachineResearchHandoff.hydrate(handoff)
            handoff_valid = True
            handoff_decision = hydrated.decision.value
        fault_injections = run.get("critic_fault_injections") or ()
        critical_scenario = run.get("critical_scenario") is True
        rows.append(
            RetrospectiveHoldoutRow(
                episode_id,
                candidate.instrument_id,
                candidate.stratum.value,
                run["status"],
                run.get("failure_code"),
                critical_scenario,
                bool(
                    critical_scenario
                    and run["status"] == "COMPLETED"
                    and conclusion.get("kind") == "DEFER"
                    and total_tokens == 0
                ),
                conclusion.get("kind"),
                agent_family.value,
                bool(
                    run["status"] == "COMPLETED"
                    and set(hypothesis) == {"family", "statement", "falsification_condition", "next_test"}
                    and all(hypothesis.values())
                ),
                raw_agent_opportunity,
                deterministic_accepted,
                final_accepted,
                bool(independent_review or run.get("independent_critic_failure")),
                bool(run.get("independent_critic_failure")),
                baseline_screen is not None,
                bool(
                    raw_agent_opportunity
                    and agent_screen is not None
                    and agent_screen.cutoff_direction
                    and Decimal(agent_screen.cutoff_direction) * future_return > 0
                ),
                bool(
                    deterministic_accepted
                    and agent_screen is not None
                    and agent_screen.cutoff_direction
                    and Decimal(agent_screen.cutoff_direction) * future_return > 0
                ),
                bool(
                    baseline_screen is not None
                    and baseline_screen.cutoff_direction
                    and Decimal(baseline_screen.cutoff_direction) * future_return > 0
                ),
                handoff_valid,
                handoff_decision,
                len(fault_injections),
                sum(item.get("accepted") is False for item in fault_injections),
                run["duration_ms"],
                total_tokens,
            )
        )
    if len(rows) != 50:
        raise SystemExit("candidate reconstruction did not match the frozen roster")

    scorecard = _score(rows, args.suite_sha256)
    output_path = run_dir / "retrospective-confirmation-scorecard.json"
    output_path.write_text(canonical_json_text(scorecard) + "\n", encoding="utf-8")
    print(json.dumps(scorecard, ensure_ascii=False, indent=2))


def _score(rows: list[RetrospectiveHoldoutRow], suite_sha256: str) -> dict[str, JsonValue]:
    product = tuple(row for row in rows if not row.critical_scenario and row.status == "COMPLETED")
    raw = tuple(row for row in product if row.raw_agent_opportunity)
    agent = tuple(row for row in product if row.agent_without_independent_critic_opportunity)
    final = tuple(row for row in product if row.independent_critic_accepted_opportunity)
    baseline = tuple(row for row in product if row.strongest_family_baseline_opportunity)
    raw_correct = sum(row.raw_agent_future_direction_consistent for row in raw)
    agent_correct = sum(row.agent_without_independent_critic_future_direction_consistent for row in agent)
    final_correct = sum(row.agent_without_independent_critic_future_direction_consistent for row in final)
    baseline_correct = sum(row.baseline_future_direction_consistent for row in baseline)
    completed = sum(row.status == "COMPLETED" for row in rows)
    critical = sum(row.critical_scenario for row in rows)
    critical_correct = sum(row.critical_zero_token_refusal for row in rows)
    fault_count = sum(row.fault_count for row in rows)
    fault_caught = sum(row.fault_caught_count for row in rows)
    handoff_expected = completed
    handoff_valid = sum(row.machine_handoff_valid for row in rows)
    hypothesis_complete = sum(row.hypothesis_complete for row in rows)
    critic_invoked = sum(row.independent_critic_invoked for row in rows)
    critic_failed = sum(row.independent_critic_failed for row in rows)
    decisions = {row.machine_handoff_decision for row in rows}
    average_tokens = sum(row.total_tokens for row in rows) // len(rows)
    average_duration = sum(row.duration_ms for row in rows) // len(rows)
    critic_precision_increment = bool(agent and final and final_correct * len(agent) > agent_correct * len(final))
    critic_bad_candidate_escape_reduced = critic_precision_increment
    final_not_below_baseline = bool(
        baseline and final and final_correct * len(baseline) >= baseline_correct * len(final)
    )

    blockers = []
    if completed < 49:
        blockers.append("formal reliability floor was not met")
    if critical != 4 or critical_correct != critical:
        blockers.append("critical evidence-unavailable zero-token refusal was not perfect")
    if not fault_count or fault_caught * 100 < fault_count * 95:
        blockers.append("deterministic Critic fault recall was below threshold")
    if hypothesis_complete != completed:
        blockers.append("completed conclusions were missing falsifiable hypotheses")
    if handoff_valid != handoff_expected:
        blockers.append("completed conclusions were missing strict machine handoffs")
    if critic_failed:
        blockers.append("independent Critic path had a recorded failure")
    if "CONTINUE_TEST" not in decisions:
        blockers.append("no directly instantiable shadow experiment was produced")
    if "DO_NOT_ADVANCE" not in decisions:
        blockers.append("deterministic rejection was not demonstrated")
    if len(final) < 3:
        blockers.append("independent Critic retained fewer than three candidates")
    if not critic_precision_increment:
        blockers.append("Agent plus Critic precision did not strictly improve over Agent without Critic")
    if not final_not_below_baseline:
        blockers.append("Agent plus Critic precision was below the strongest deterministic family baseline")
    if not critic_bad_candidate_escape_reduced:
        blockers.append("independent Critic did not reduce bad-candidate escape rate")
    if average_tokens > 25_000:
        blockers.append("average token budget exceeded the frozen threshold")
    if average_duration > 45_000:
        blockers.append("average latency exceeded the frozen threshold")

    summary: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "phase": "RETROSPECTIVE_CONFIRMATION_HOLDOUT",
        "evidence_level": "RETROSPECTIVE_CONFIRMATION",
        "suite_sha256": suite_sha256,
        "episode_count": len(rows),
        "completed_count": completed,
        "conclusion_counts": dict(sorted(Counter(row.conclusion_kind or "FAILED" for row in rows).items())),
        "critical_scenario_count": critical,
        "critical_zero_token_correct_refusal_count": critical_correct,
        "critic_fault_count": fault_count,
        "critic_fault_caught_count": fault_caught,
        "hypothesis_complete_count": hypothesis_complete,
        "machine_handoff_expected_count": handoff_expected,
        "machine_handoff_valid_count": handoff_valid,
        "machine_decision_counts": dict(
            sorted(Counter(row.machine_handoff_decision or "NONE" for row in rows).items())
        ),
        "independent_critic_invocation_count": critic_invoked,
        "independent_critic_failure_count": critic_failed,
        "raw_agent_opportunity_count": len(raw),
        "raw_agent_future_direction_consistent_count": raw_correct,
        "agent_without_independent_critic_opportunity_count": len(agent),
        "agent_without_independent_critic_future_direction_consistent_count": agent_correct,
        "independent_critic_accepted_opportunity_count": len(final),
        "independent_critic_accepted_future_direction_consistent_count": final_correct,
        "strongest_family_baseline_opportunity_count": len(baseline),
        "strongest_family_baseline_future_direction_consistent_count": baseline_correct,
        "critic_precision_strictly_improved": critic_precision_increment,
        "critic_bad_candidate_escape_rate_reduced": critic_bad_candidate_escape_reduced,
        "final_precision_not_below_strongest_family_baseline": final_not_below_baseline,
        "future_leakage_control": "ENFORCED_BY_SEALED_EPISODE_AND_VERIFIED_RESULT_BINDING",
        "trading_side_effects": "PROHIBITED_BY_RESEARCH_ONLY_RUNTIME",
        "average_tokens": average_tokens,
        "average_duration_ms": average_duration,
        "retrospective_confirmation_passed": not blockers,
        "retrospective_confirmation_blockers": tuple(blockers),
        "governance_interpretation": (
            "ELIGIBLE_FOR_TEN_USER_SHADOW_REVIEWS" if not blockers else "STOP_OR_NEW_CAPABILITY_PIVOT_REQUIRED"
        ),
        "prospective_forward_confirmation_pending": True,
        "rows_sha256": canonical_sha256(tuple(row.payload() for row in rows)),
    }
    return {**summary, "scorecard_sha256": canonical_sha256(summary)}


def _roster_candidates(roster: object, data_root: Path) -> tuple[tuple[str, ReplayEpisodeCandidate], ...]:
    if type(roster) is not dict or type(roster.get("selected")) is not list:
        raise ValueError("scorecard requires a frozen roster payload")
    grouped_lists: dict[str, list[PointInTimeRecord]] = {}
    for dataset in runner._stored_datasets(data_root):
        for record in legacy._records(dataset):
            instrument_id = record.values.get("instrument_id")
            if type(instrument_id) is not str:
                raise ValueError("stored holdout record is missing its instrument identity")
            grouped_lists.setdefault(instrument_id, []).append(record)
    grouped = {
        instrument_id: tuple(sorted(records, key=lambda item: item.event_time.value))
        for instrument_id, records in grouped_lists.items()
    }
    reconstructed = []
    for raw in cast(list[object], roster["selected"]):
        if type(raw) is not dict:
            raise ValueError("frozen roster candidate is malformed")
        instrument_id = raw["instrument_id"]
        market_cutoff = raw["market_cutoff"]
        if type(instrument_id) is not str or type(market_cutoff) is not str:
            raise ValueError("frozen roster candidate identity is malformed")
        series = grouped[instrument_id]
        matches = tuple(
            index for index, record in enumerate(series) if record.event_time.to_dict()["recorded_at"] == market_cutoff
        )
        if len(matches) != 1 or matches[0] < 39 or matches[0] + 5 >= len(series):
            raise ValueError("frozen roster candidate cannot be reconstructed")
        index = matches[0]
        episode_id = raw["episode_id"]
        stratum = raw["stratum"]
        if type(episode_id) is not str or type(stratum) is not str:
            raise ValueError("frozen roster candidate fields are malformed")
        reconstructed.append(
            (
                episode_id,
                ReplayEpisodeCandidate(
                    instrument_id,
                    EpisodeStratum(stratum),
                    series[index - 39 : index + 1],
                    series[index + 5],
                ),
            )
        )
    return tuple(reconstructed)


if __name__ == "__main__":
    main()
