from datetime import UTC, datetime

from futures_agent_os.local_trial import run_local_trial


def test_local_trial_completes_full_simulation_journey_deterministically():
    at = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
    first = run_local_trial(at).as_dict()
    second = run_local_trial(at).as_dict()
    assert first == second
    assert first["status"] == "LOCAL_TRIAL_COMPLETED"
    assert first["boundary"] == "RESEARCH_AND_SIMULATION_ONLY"
    assert first["outcome"] == "TRADE"
    assert first["steps"] == (
        "SNAPSHOT",
        "OPPORTUNITY_SCAN",
        "STRATEGY_DELIBERATION",
        "PRE_TRADE_CRITIQUE",
        "AUTHORIZATION_BASIS",
        "RISK_DECISION",
        "SIMULATED_EXECUTION",
        "POSITION_PROTECTION",
        "IMPORTANT_NOTIFICATION",
        "POST_TRADE_REVIEW",
    )
    assert first["journal_entries"] == 9
    assert first["open_fill_id"]
    assert first["protective_action_id"]
    assert first["exit_fill_id"]
    assert first["settlement_id"]
