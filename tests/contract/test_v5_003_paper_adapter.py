from futures_agent_os.execution_simulation.paper_adapter import ExternalExecution, ExternalStatus, PaperTradingAdapter


def test_reconcile_matches_external_execution():
    result = PaperTradingAdapter().reconcile("o1", 3, ExternalExecution("o1", ExternalStatus.FILLED, 3))
    assert result.matched and result.reason == "MATCHED"


def test_unknown_external_state_fails_closed():
    result = PaperTradingAdapter().reconcile("o1", 0, ExternalExecution("o1", ExternalStatus.UNKNOWN, 0))
    assert not result.matched and result.reason == "UNKNOWN_EXTERNAL_STATE"
