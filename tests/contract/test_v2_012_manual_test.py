import pytest

from futures_agent_os.decision import ExecutionOrigin, ManualTestContext, require_manual_test


def test_manual_test_context_is_simulation_only() -> None:
    context = ManualTestContext("user:test", "environment://simulation-only", "basis:test")
    require_manual_test(ExecutionOrigin.MANUAL_TEST, context)
    with pytest.raises(ValueError):
        require_manual_test(ExecutionOrigin.AUTONOMOUS_AGENT, context)


def test_manual_test_rejects_non_simulation_environment() -> None:
    with pytest.raises(ValueError):
        ManualTestContext("user:test", "environment://live", "basis:test")
