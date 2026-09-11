from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import pytest

from futures_agent_os.operations import (
    StabilityHeartbeat,
    StabilityJournal,
    StabilityRunPlan,
    evaluate_stability_run,
    run_simulation_stability_probe,
)
from futures_agent_os.shared_kernel import RecordedAt


START = RecordedAt.from_datetime(datetime(2026, 9, 11, 0, 0, tzinfo=UTC))


def _plan(**overrides: object) -> StabilityRunPlan:
    values: dict[str, object] = {
        "run_id": "v5-011-test",
        "started_at": START,
        "minimum_end_at": RecordedAt.from_datetime(START.value + timedelta(days=1)),
        "code_commit": "a" * 40,
        "environment": "sim-prod",
        "heartbeat_interval_seconds": 900,
        "maximum_single_gap_seconds": 3600,
        "maximum_total_gap_seconds": 21600,
    }
    values.update(overrides)
    return StabilityRunPlan(**values)  # type: ignore[arg-type]


def _append(journal: StabilityJournal, when: datetime, **overrides: object) -> StabilityHeartbeat:
    values: dict[str, object] = {
        "now": RecordedAt.from_datetime(when),
        "code_commit": "a" * 40,
        "health_ok": True,
        "simulated_trade_count": 1,
        "duplicate_trade_count": 0,
        "unprotected_position_count": 0,
        "audit_chain_break_count": 0,
        "ledger_difference": Decimal("0"),
    }
    values.update(overrides)
    return journal.append(**values)  # type: ignore[arg-type]


def test_plan_enforces_real_duration_and_simulation_gap_policy() -> None:
    with pytest.raises(ValueError, match="at least 1 real day"):
        _plan(minimum_end_at=RecordedAt.from_datetime(START.value + timedelta(hours=23, minutes=59, seconds=59)))
    with pytest.raises(ValueError, match="simulation environment"):
        _plan(environment="production")
    with pytest.raises(ValueError, match="single-gap threshold"):
        _plan(maximum_single_gap_seconds=900)


def test_real_simulation_probe_measures_all_acceptance_invariants() -> None:
    result = run_simulation_stability_probe(now=START)
    assert result.health_ok
    assert result.simulated_trade_count == 1
    assert result.duplicate_trade_count == 0
    assert result.unprotected_position_count == 0
    assert result.audit_chain_break_count == 0
    assert result.ledger_difference == 0


def test_journal_is_bucket_idempotent_and_hash_chained(tmp_path) -> None:
    journal = StabilityJournal(tmp_path / "run")
    journal.start(_plan())
    first = _append(journal, START.value)
    replay = _append(journal, START.value + timedelta(seconds=30))
    second = _append(journal, START.value + timedelta(seconds=900))
    assert replay == first
    assert second.sequence == 2 and second.previous_digest == first.digest
    assert len(journal.load_heartbeats()) == 2


def test_journal_rejects_code_drift_and_persisted_tampering(tmp_path) -> None:
    journal = StabilityJournal(tmp_path / "run")
    journal.start(_plan())
    _append(journal, START.value)
    with pytest.raises(ValueError, match="code commit drifted"):
        _append(journal, START.value + timedelta(seconds=900), code_commit="b" * 40)

    payload = json.loads(journal.heartbeat_path.read_text(encoding="utf-8"))
    payload["duplicate_trade_count"] = 1
    journal.heartbeat_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot load stability heartbeat chain"):
        journal.load_heartbeats()


def test_gap_is_reported_and_budgeted(tmp_path) -> None:
    journal = StabilityJournal(tmp_path / "run")
    journal.start(_plan())
    _append(journal, START.value)
    delayed = _append(journal, START.value + timedelta(seconds=3700))
    assert delayed.incidents[0].category == "HEARTBEAT_GAP"
    evaluation = evaluate_stability_run(
        journal.load_plan(), journal.load_heartbeats(), now=RecordedAt.from_datetime(delayed.recorded_at.value)
    )
    assert "SINGLE_GAP_BUDGET_EXCEEDED" in evaluation.reason_codes
    assert evaluation.total_gap_seconds == Decimal("2800.0")


def test_one_day_completion_gate_cannot_be_satisfied_early(tmp_path) -> None:
    plan = _plan(
        heartbeat_interval_seconds=86400,
        maximum_single_gap_seconds=172801,
        maximum_total_gap_seconds=172801,
    )
    journal = StabilityJournal(tmp_path / "run")
    journal.start(plan)
    for day in range(2):
        _append(journal, START.value + timedelta(days=day))
    heartbeats = journal.load_heartbeats()
    early = evaluate_stability_run(
        plan,
        heartbeats[:-1],
        now=RecordedAt.from_datetime(START.value + timedelta(hours=23)),
    )
    assert not early.complete and early.reason_codes == ("MINIMUM_1_DAY_NOT_ELAPSED",)
    complete = evaluate_stability_run(plan, heartbeats, now=RecordedAt.from_datetime(START.value + timedelta(days=1)))
    assert complete.complete and complete.reason_codes == () and complete.heartbeat_count == 2


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("health_ok", False, "HEALTH_CHECK_FAILED"),
        ("simulated_trade_count", 0, "NO_SIMULATED_TRADE"),
        ("duplicate_trade_count", 1, "DUPLICATE_TRADE"),
        ("unprotected_position_count", 1, "UNPROTECTED_POSITION"),
        ("audit_chain_break_count", 1, "AUDIT_CHAIN_BREAK"),
        ("ledger_difference", Decimal("0.01"), "LEDGER_DIFFERENCE"),
    ],
)
def test_any_measured_invariant_violation_blocks_completion(tmp_path, field: str, value: object, reason: str) -> None:
    plan = _plan(
        heartbeat_interval_seconds=86400,
        maximum_single_gap_seconds=172801,
        maximum_total_gap_seconds=172801,
    )
    journal = StabilityJournal(tmp_path / field)
    journal.start(plan)
    for day in range(2):
        _append(journal, START.value + timedelta(days=day))
    _append(journal, START.value + timedelta(days=2), **{field: value})
    evaluation = evaluate_stability_run(
        plan,
        journal.load_heartbeats(),
        now=RecordedAt.from_datetime(START.value + timedelta(days=2)),
    )
    assert not evaluation.complete and reason in evaluation.reason_codes


def test_heartbeat_payload_digest_detects_mutation() -> None:
    heartbeat = StabilityHeartbeat.issue(
        run_id="v5-011-test",
        sequence=1,
        bucket=0,
        recorded_at=START,
        code_commit="a" * 40,
        health_ok=True,
        simulated_trade_count=1,
        duplicate_trade_count=0,
        unprotected_position_count=0,
        audit_chain_break_count=0,
        ledger_difference=Decimal("0"),
        incidents=(),
        previous_digest="0" * 64,
    )
    payload = heartbeat.to_payload()
    payload["audit_chain_break_count"] = 1
    with pytest.raises(ValueError, match="digest does not match"):
        StabilityHeartbeat.from_payload(payload)
