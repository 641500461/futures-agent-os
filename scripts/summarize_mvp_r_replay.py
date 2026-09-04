"""Produce a deterministic MVP-R diagnostic scorecard from sealed replay artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment import (
    EpisodePhase,
    EpisodeStratum,
    MachineResearchHandoff,
    ReplayEpisodeCandidate,
)
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256

import run_mvp_r_replay as runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-sha256", required=True)
    parser.add_argument("--phase", choices=("diagnostic", "holdout"), required=True)
    args = parser.parse_args()
    phase = EpisodePhase.DIAGNOSTIC if args.phase == "diagnostic" else EpisodePhase.HOLDOUT
    run_dir = runner.DATA_ROOT / "runs" / args.suite_sha256 / args.phase / "official"
    runs = {
        item["episode_id"]: item
        for path in sorted(run_dir.glob("evaluation_episode_*.json"))
        for item in (json.loads(path.read_text(encoding="utf-8")),)
    }
    expected_count = 30 if phase is EpisodePhase.DIAGNOSTIC else 50
    if len(runs) != expected_count:
        raise SystemExit(f"expected {expected_count} run artifacts, found {len(runs)}")

    roster = json.loads((run_dir / "roster.json").read_text(encoding="utf-8"))
    candidates = _roster_candidates(roster)
    rows = []
    for episode_id, candidate in candidates:
        run = runs.get(episode_id)
        if run is None:
            continue
        closes = tuple(Decimal(str(record.values["close"])) for record in candidate.records)
        returns = tuple(closes[index] / closes[index - 1] - 1 for index in range(1, len(closes)))
        signals = tuple(
            1 if value > Decimal("0.0001") else -1 if value < Decimal("-0.0001") else 0 for value in returns[:-1]
        )
        signalled = tuple(index for index, signal in enumerate(signals) if signal)
        gross = sum((Decimal(signals[index]) * returns[index + 1] for index in signalled), Decimal(0))
        accuracy = (
            Decimal(
                sum(
                    signals[index] == (1 if returns[index + 1] > 0 else -1 if returns[index + 1] < 0 else 0)
                    for index in signalled
                )
            )
            / Decimal(len(signalled))
            if signalled
            else Decimal(0)
        )
        cost = Decimal("0.0003") * len(signalled)
        proxy_net = gross - cost
        stressed_net = proxy_net - cost
        counterfactual_net = -gross - cost
        counterfactual_stressed_net = counterfactual_net - cost
        positive_fold_ratio, counterfactual_positive_fold_ratio = _chronological_positive_fold_ratios(
            signals, returns, Decimal("0.0003"), folds=3
        )
        deterministic_family = (
            "MOMENTUM_CONTINUATION" if stressed_net >= counterfactual_stressed_net else "MEAN_REVERSION"
        )
        deterministic_family_accuracy = (
            accuracy if deterministic_family == "MOMENTUM_CONTINUATION" else Decimal(1) - accuracy
        )
        deterministic_family_fold_ratio = (
            positive_fold_ratio
            if deterministic_family == "MOMENTUM_CONTINUATION"
            else counterfactual_positive_fold_ratio
        )
        deterministic_opportunity = bool(
            deterministic_family_accuracy >= Decimal("0.55")
            and max(stressed_net, counterfactual_stressed_net) > 0
            and deterministic_family_fold_ratio >= Decimal("0.50")
        )
        conclusion = run.get("conclusion") or {}
        grounding_pointer_repaired = (
            "Grounding pointers were canonicalized from one unique owner-produced metric."
            in conclusion.get("warnings", ())
        )
        hypothesis = conclusion.get("hypothesis") or {}
        agent_family = hypothesis.get("family")
        agent_opportunity = conclusion.get("kind") == "OPPORTUNITY_CANDIDATE"
        critique = run.get("critique") or {}
        critic_opportunity = agent_opportunity and critique.get("accepted") is True
        machine_handoff = run.get("machine_handoff")
        machine_handoff_valid = False
        machine_experiment_ready = False
        machine_decision = None
        if not run.get("critical_scenario") and run["status"] == "COMPLETED" and machine_handoff is not None:
            hydrated_handoff = MachineResearchHandoff.hydrate(machine_handoff)
            machine_handoff_valid = True
            machine_experiment_ready = hydrated_handoff.next_experiment.request_status == "READY"
            machine_decision = hydrated_handoff.decision.value
        last_return = closes[-1] / closes[-2] - 1
        last_signal = 1 if last_return > Decimal("0.0001") else -1 if last_return < Decimal("-0.0001") else 0
        future_return = Decimal(str(candidate.future_record.values["close"])) / closes[-1] - 1
        agent_direction = last_signal if agent_family == "MOMENTUM_CONTINUATION" else -last_signal
        deterministic_direction = last_signal if deterministic_family == "MOMENTUM_CONTINUATION" else -last_signal
        rows.append(
            {
                "episode_id": episode_id,
                "instrument_id": candidate.instrument_id,
                "stratum": candidate.stratum.value,
                "status": run["status"],
                "conclusion_kind": conclusion.get("kind"),
                "hypothesis_family": agent_family,
                "hypothesis_complete": bool(
                    run["status"] == "COMPLETED"
                    and set(hypothesis) == {"family", "statement", "falsification_condition", "next_test"}
                    and all(hypothesis.values())
                ),
                "grounding_pointer_repaired": grounding_pointer_repaired,
                "critical_scenario": run.get("critical_scenario") is True,
                "deterministic_opportunity": deterministic_opportunity,
                "deterministic_family": deterministic_family,
                "critic_opportunity": critic_opportunity,
                "machine_handoff_valid": machine_handoff_valid,
                "machine_experiment_ready": machine_experiment_ready,
                "machine_decision": machine_decision,
                "agent_matches_deterministic": agent_opportunity == deterministic_opportunity,
                "agent_future_direction_consistent": bool(
                    agent_opportunity and agent_direction and Decimal(agent_direction) * future_return > 0
                ),
                "deterministic_future_direction_consistent": bool(
                    deterministic_opportunity
                    and deterministic_direction
                    and Decimal(deterministic_direction) * future_return > 0
                ),
                "duration_ms": run["duration_ms"],
                "total_tokens": sum(turn["usage"][0] + turn["usage"][1] for turn in run["turns"]),
                "critic_injected_defect_count": len(run.get("critic_fault_injections", ())),
                "critic_injected_caught_count": sum(
                    item.get("accepted") is False for item in run.get("critic_fault_injections", ())
                ),
            }
        )
    if len(rows) != expected_count:
        raise SystemExit("candidate reconstruction did not match the frozen roster")

    product_rows = tuple(row for row in rows if not row["critical_scenario"] and row["status"] == "COMPLETED")
    opportunities = tuple(row for row in product_rows if row["conclusion_kind"] == "OPPORTUNITY_CANDIDATE")
    critic_opportunities = tuple(row for row in product_rows if row["critic_opportunity"])
    deterministic_opportunities = tuple(row for row in product_rows if row["deterministic_opportunity"])
    agent_consistent = sum(row["agent_future_direction_consistent"] for row in opportunities)
    critic_consistent = sum(row["agent_future_direction_consistent"] for row in critic_opportunities)
    deterministic_consistent = sum(
        row["deterministic_future_direction_consistent"] for row in deterministic_opportunities
    )
    positive_increment = bool(
        critic_opportunities
        and opportunities
        and deterministic_opportunities
        and critic_consistent * len(opportunities) > agent_consistent * len(critic_opportunities)
        and critic_consistent * len(deterministic_opportunities) >= deterministic_consistent * len(critic_opportunities)
    )
    critical_count = sum(row["critical_scenario"] for row in rows)
    critical_correct = sum(
        row["critical_scenario"] and row["conclusion_kind"] == "DEFER" and row["status"] == "COMPLETED" for row in rows
    )
    critic_defects = sum(row["critic_injected_defect_count"] for row in rows)
    critic_caught = sum(row["critic_injected_caught_count"] for row in rows)
    completed_count = sum(row["status"] == "COMPLETED" for row in rows)
    hypothesis_complete_count = sum(row["hypothesis_complete"] for row in rows)
    machine_handoff_expected_count = sum(not row["critical_scenario"] and row["status"] == "COMPLETED" for row in rows)
    machine_handoff_valid_count = sum(row["machine_handoff_valid"] for row in rows)
    machine_experiment_ready_count = sum(row["machine_experiment_ready"] for row in rows)
    machine_do_not_advance_count = sum(row["machine_decision"] == "DO_NOT_ADVANCE" for row in rows)
    grounding_pointer_repair_count = sum(row["grounding_pointer_repaired"] for row in rows)
    total_tokens = sum(row["total_tokens"] for row in rows)
    average_tokens = total_tokens // len(rows)
    average_duration = sum(row["duration_ms"] for row in rows) // len(rows)
    reliability_floor = 29 if phase is EpisodePhase.DIAGNOSTIC else 49
    holdout_ready = bool(
        phase is EpisodePhase.DIAGNOSTIC
        and completed_count >= reliability_floor
        and critical_count
        and critical_correct == critical_count
        and critic_defects
        and critic_caught * 100 >= critic_defects * 95
        and positive_increment
        and len(critic_opportunities) >= 2
    )
    blockers = []
    if completed_count < reliability_floor:
        blockers.append("formal reliability floor was not met")
    if not critical_count or critical_correct != critical_count:
        blockers.append("critical-scenario refusal was not perfect")
    if not critic_defects or critic_caught * 100 < critic_defects * 95:
        blockers.append("Critic high-severity recall was below threshold")
    if not positive_increment:
        blockers.append("Agent plus Critic did not improve candidate precision over both ablations")
    if len(critic_opportunities) < 2:
        blockers.append("Critic achieved safety by excessive deferral")
    if hypothesis_complete_count != completed_count:
        blockers.append("completed conclusions were missing falsifiable hypothesis fields")
    if machine_handoff_valid_count != machine_handoff_expected_count:
        blockers.append("completed non-critical conclusions were missing a valid machine handoff")
    if machine_experiment_ready_count < 1:
        blockers.append("machine handoff produced no directly instantiable research experiment")
    if machine_do_not_advance_count < 1:
        blockers.append("machine handoff did not demonstrate deterministic candidate rejection")
    if average_tokens > 25_000:
        blockers.append("average token budget exceeded the frozen threshold")
    if average_duration > 45_000:
        blockers.append("average latency exceeded the frozen threshold")
    automated_gates_passed = not blockers
    summary = {
        "task": "MVP-R-001",
        "phase": phase.value,
        "suite_sha256": args.suite_sha256,
        "episode_count": len(rows),
        "completed_count": completed_count,
        "conclusion_counts": dict(sorted(Counter(row["conclusion_kind"] or "FAILED" for row in rows).items())),
        "opportunity_count": len(opportunities),
        "opportunity_future_direction_consistent_count": agent_consistent,
        "critic_accepted_opportunity_count": len(critic_opportunities),
        "critic_accepted_future_direction_consistent_count": critic_consistent,
        "deterministic_opportunity_count": len(deterministic_opportunities),
        "deterministic_future_direction_consistent_count": deterministic_consistent,
        "agent_only_opportunity_count": sum(
            row["conclusion_kind"] == "OPPORTUNITY_CANDIDATE" and not row["deterministic_opportunity"] for row in rows
        ),
        "deterministic_only_opportunity_count": sum(
            row["conclusion_kind"] != "OPPORTUNITY_CANDIDATE" and row["deterministic_opportunity"] for row in rows
        ),
        "agent_deterministic_decision_agreement_count": sum(row["agent_matches_deterministic"] for row in rows),
        "agent_positive_increment_over_deterministic_baseline": positive_increment,
        "critic_ablation_completed": True,
        "critical_fault_injection_completed": bool(critical_count and critic_defects),
        "critical_scenario_count": critical_count,
        "critical_correct_refusal_count": critical_correct,
        "critic_high_severity_defect_count": critic_defects,
        "critic_high_severity_caught_count": critic_caught,
        "hypothesis_complete_count": hypothesis_complete_count,
        "machine_handoff_expected_count": machine_handoff_expected_count,
        "machine_handoff_valid_count": machine_handoff_valid_count,
        "machine_experiment_ready_count": machine_experiment_ready_count,
        "machine_do_not_advance_count": machine_do_not_advance_count,
        "grounding_pointer_repair_count": grounding_pointer_repair_count,
        "machine_decision_counts": dict(sorted(Counter(row["machine_decision"] or "NONE" for row in rows).items())),
        "total_tokens": total_tokens,
        "average_tokens": average_tokens,
        "average_duration_ms": average_duration,
        "iteration_one_total_tokens": 2_149_792 if phase is EpisodePhase.DIAGNOSTIC else None,
        "holdout_ready": holdout_ready and automated_gates_passed,
        "holdout_passed": phase is EpisodePhase.HOLDOUT and automated_gates_passed,
        "automated_gates_passed": automated_gates_passed,
        "holdout_blockers": tuple(blockers),
        "rows_sha256": canonical_sha256(tuple(rows)),
    }
    output = {**summary, "scorecard_sha256": canonical_sha256(summary)}
    output_path = run_dir / "diagnostic-scorecard.json"
    output_path.write_text(canonical_json_text(output) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _chronological_positive_fold_ratios(
    signals: tuple[int, ...] | list[int],
    returns: tuple[Decimal, ...] | list[Decimal],
    per_signal_cost: Decimal,
    *,
    folds: int,
) -> tuple[Decimal, Decimal]:
    directional_positive = 0
    counterfactual_positive = 0
    populated = 0
    for fold in range(folds):
        start = len(signals) * fold // folds
        end = len(signals) * (fold + 1) // folds
        indices = tuple(index for index in range(start, end) if signals[index])
        if not indices:
            continue
        populated += 1
        fold_gross = sum((Decimal(signals[index]) * returns[index + 1] for index in indices), Decimal(0))
        directional_positive += fold_gross - per_signal_cost * len(indices) > 0
        counterfactual_positive += -fold_gross - per_signal_cost * len(indices) > 0
    if not populated:
        return Decimal(0), Decimal(0)
    return Decimal(directional_positive) / populated, Decimal(counterfactual_positive) / populated


def _roster_candidates(roster: object) -> tuple[tuple[str, ReplayEpisodeCandidate], ...]:
    if type(roster) is not dict or type(roster.get("selected")) is not list:
        raise ValueError("scorecard requires a frozen roster payload")
    grouped_lists: dict[str, list[PointInTimeRecord]] = {}
    for dataset in runner._stored_datasets():
        for record in runner._records(dataset):
            instrument_id = record.values.get("instrument_id")
            if type(instrument_id) is not str:
                raise ValueError("stored replay record is missing its instrument identity")
            grouped_lists.setdefault(instrument_id, []).append(record)
    grouped = {
        instrument_id: tuple(sorted(records, key=lambda item: item.event_time.value))
        for instrument_id, records in grouped_lists.items()
    }
    reconstructed = []
    for raw in roster["selected"]:
        if type(raw) is not dict:
            raise ValueError("frozen roster candidate is malformed")
        instrument_id = raw["instrument_id"]
        market_cutoff = raw["market_cutoff"]
        series = grouped[instrument_id]
        matches = tuple(
            index for index, record in enumerate(series) if record.event_time.to_dict()["recorded_at"] == market_cutoff
        )
        if len(matches) != 1 or matches[0] < 39 or matches[0] + 5 >= len(series):
            raise ValueError("frozen roster candidate cannot be reconstructed")
        index = matches[0]
        reconstructed.append(
            (
                raw["episode_id"],
                ReplayEpisodeCandidate(
                    instrument_id,
                    EpisodeStratum(raw["stratum"]),
                    series[index - 39 : index + 1],
                    series[index + 5],
                ),
            )
        )
    return tuple(reconstructed)


if __name__ == "__main__":
    main()
