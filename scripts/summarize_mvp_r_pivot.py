"""Summarize the contaminated-data development diagnostic for the MVP-R Pivot."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, fields
from decimal import Decimal

import run_mvp_r_pivot as runner
import summarize_mvp_r_replay as legacy_summary

from futures_agent_os.research_experiment import (
    HypothesisFamily,
    PivotMachineResearchHandoff,
    screen_hypothesis_families,
    strongest_deterministic_family,
)
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


@dataclass(frozen=True, slots=True)
class PivotDevelopmentRow:
    episode_id: str
    instrument_id: str
    stratum: str
    status: str
    failure_code: str | None
    critical_scenario: bool
    conclusion_kind: str | None
    hypothesis_family: str
    hypothesis_complete: bool
    raw_opportunity: bool
    deterministic_accepted_opportunity: bool
    independent_critic_accepted_opportunity: bool
    independent_critic_invoked: bool
    independent_critic_failed: bool
    baseline_opportunity: bool
    agent_future_direction_consistent: bool
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
    args = parser.parse_args()
    run_dir = runner.DATA_ROOT / "runs" / args.suite_sha256 / "pivot-diagnostic" / "development"
    runs = {
        item["episode_id"]: item
        for path in sorted(run_dir.glob("evaluation_episode_*.json"))
        for item in (json.loads(path.read_text(encoding="utf-8")),)
    }
    if len(runs) != 30:
        raise SystemExit(f"expected thirty development artifacts, found {len(runs)}")
    roster = json.loads((run_dir / "roster.json").read_text(encoding="utf-8"))
    candidates = legacy_summary._roster_candidates(roster)
    config = runner.legacy._validation_config()
    cost = (config.round_trip_cost_bps + config.slippage_bps) / Decimal(10_000)

    rows: list[PivotDevelopmentRow] = []
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
        raw_opportunity = conclusion.get("kind") == "OPPORTUNITY_CANDIDATE"
        deterministic_accepted = bool(
            raw_opportunity and (run.get("deterministic_critique") or {}).get("accepted") is True
        )
        independent_review = run.get("independent_critic") or {}
        final_accepted = bool(deterministic_accepted and independent_review.get("decision") == "ACCEPT")
        future_return = (
            Decimal(str(candidate.future_record.values["close"])) / Decimal(str(candidate.records[-1].values["close"]))
            - 1
        )
        handoff_valid = False
        handoff_decision = None
        handoff = run.get("machine_handoff")
        if handoff is not None:
            hydrated = PivotMachineResearchHandoff.hydrate(handoff)
            handoff_valid = True
            handoff_decision = hydrated.decision.value
        fault_injections = run.get("critic_fault_injections") or ()
        rows.append(
            PivotDevelopmentRow(
                episode_id,
                candidate.instrument_id,
                candidate.stratum.value,
                run["status"],
                run.get("failure_code"),
                run.get("critical_scenario") is True,
                conclusion.get("kind"),
                agent_family.value,
                bool(
                    run["status"] == "COMPLETED"
                    and set(hypothesis) == {"family", "statement", "falsification_condition", "next_test"}
                    and all(hypothesis.values())
                ),
                raw_opportunity,
                deterministic_accepted,
                final_accepted,
                bool(independent_review or run.get("independent_critic_failure")),
                bool(run.get("independent_critic_failure")),
                baseline_screen is not None,
                bool(
                    raw_opportunity
                    and agent_screen is not None
                    and agent_screen.cutoff_direction
                    and Decimal(agent_screen.cutoff_direction) * future_return > 0
                ),
                bool(baseline_screen is not None and Decimal(baseline_screen.cutoff_direction) * future_return > 0),
                handoff_valid,
                handoff_decision,
                len(fault_injections),
                sum(item.get("accepted") is False for item in fault_injections),
                run["duration_ms"],
                sum(sum(usage[:2]) for usage in run.get("research_usage") or ())
                + sum((run.get("critic_usage") or ())[:2]),
            )
        )

    product = tuple(row for row in rows if not row.critical_scenario and row.status == "COMPLETED")
    raw = tuple(row for row in product if row.raw_opportunity)
    deterministic_agent = tuple(row for row in product if row.deterministic_accepted_opportunity)
    final = tuple(row for row in product if row.independent_critic_accepted_opportunity)
    baseline_rows = tuple(row for row in product if row.baseline_opportunity)
    raw_correct = sum(row.agent_future_direction_consistent for row in raw)
    deterministic_agent_correct = sum(row.agent_future_direction_consistent for row in deterministic_agent)
    final_correct = sum(row.agent_future_direction_consistent for row in final)
    baseline_correct = sum(row.baseline_future_direction_consistent for row in baseline_rows)
    completed = sum(row.status == "COMPLETED" for row in rows)
    critical = sum(row.critical_scenario for row in rows)
    critical_correct = sum(
        row.critical_scenario and row.conclusion_kind == "DEFER" and row.status == "COMPLETED" for row in rows
    )
    fault_count = sum(row.fault_count for row in rows)
    fault_caught = sum(row.fault_caught_count for row in rows)
    handoff_expected = sum(row.status == "COMPLETED" for row in rows)
    handoff_valid_count = sum(row.machine_handoff_valid for row in rows)
    critic_invoked = sum(row.independent_critic_invoked for row in rows)
    critic_failed = sum(row.independent_critic_failed for row in rows)
    average_tokens = sum(row.total_tokens for row in rows) // len(rows)
    average_duration = sum(row.duration_ms for row in rows) // len(rows)
    blockers = []
    if completed < 29:
        blockers.append("development reliability floor was not met")
    if critical != 4 or critical_correct != critical:
        blockers.append("critical evidence-unavailable refusal was not perfect")
    if not fault_count or fault_caught * 100 < fault_count * 95:
        blockers.append("deterministic Critic fault recall was below threshold")
    if sum(row.hypothesis_complete for row in rows) != completed:
        blockers.append("completed conclusions were missing falsifiable hypotheses")
    if handoff_valid_count != handoff_expected:
        blockers.append("completed conclusions were missing strict machine handoffs")
    if not critic_invoked or critic_failed:
        blockers.append("independent Critic path was not proven reliable")
    if "CONTINUE_TEST" not in {row.machine_handoff_decision for row in rows}:
        blockers.append("no directly instantiable forward experiment was produced")
    if "DO_NOT_ADVANCE" not in {row.machine_handoff_decision for row in rows}:
        blockers.append("deterministic rejection was not demonstrated")
    if average_tokens > 25_000:
        blockers.append("average token budget exceeded the development threshold")
    if average_duration > 45_000:
        blockers.append("average latency exceeded the development threshold")

    summary: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "phase": "CONTAMINATED_DEVELOPMENT_DIAGNOSTIC",
        "suite_sha256": args.suite_sha256,
        "episode_count": len(rows),
        "completed_count": completed,
        "conclusion_counts": dict(sorted(Counter(row.conclusion_kind or "FAILED" for row in rows).items())),
        "critical_scenario_count": critical,
        "critical_correct_refusal_count": critical_correct,
        "critic_fault_count": fault_count,
        "critic_fault_caught_count": fault_caught,
        "hypothesis_complete_count": sum(row.hypothesis_complete for row in rows),
        "machine_handoff_expected_count": handoff_expected,
        "machine_handoff_valid_count": handoff_valid_count,
        "machine_decision_counts": dict(
            sorted(Counter(row.machine_handoff_decision or "NONE" for row in rows).items())
        ),
        "independent_critic_invocation_count": critic_invoked,
        "independent_critic_failure_count": critic_failed,
        "raw_agent_opportunity_count": len(raw),
        "raw_agent_future_direction_consistent_count": raw_correct,
        "deterministically_admissible_agent_opportunity_count": len(deterministic_agent),
        "deterministically_admissible_agent_future_direction_consistent_count": deterministic_agent_correct,
        "independent_critic_accepted_opportunity_count": len(final),
        "independent_critic_accepted_future_direction_consistent_count": final_correct,
        "strongest_family_baseline_opportunity_count": len(baseline_rows),
        "strongest_family_baseline_future_direction_consistent_count": baseline_correct,
        "performance_interpretation": "DESCRIPTIVE_ONLY_FUTURE_PATH_PREVIOUSLY_EXPOSED",
        "average_tokens": average_tokens,
        "average_duration_ms": average_duration,
        "development_diagnostic_passed": not blockers,
        "development_blockers": tuple(blockers),
        "forward_holdout_ready": False,
        "forward_holdout_blocker": "POST_PIVOT_FORWARD_DATA_NOT_YET_AVAILABLE",
        "rows_sha256": canonical_sha256(tuple(row.payload() for row in rows)),
    }
    output = {**summary, "scorecard_sha256": canonical_sha256(summary)}
    (run_dir / "development-scorecard.json").write_text(canonical_json_text(output) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
