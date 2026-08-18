from futures_agent_os.health import get_health_status


def test_health_is_local_and_greenfield() -> None:
    health = get_health_status()

    assert health.status == "ok"
    assert health.project == "futures-agent-os"
    assert health.version == "0.0.1"
    assert health.legacy_runtime_dependency is False

