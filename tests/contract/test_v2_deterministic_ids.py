from futures_agent_os.shared_kernel import EntityId


def test_deterministic_entity_id_is_replay_stable_and_uuid7() -> None:
    first = EntityId.deterministic("reduction_request", "position:1:STOP:2026-01-01")
    second = EntityId.deterministic("reduction_request", "position:1:STOP:2026-01-01")
    other = EntityId.deterministic("reduction_request", "position:1:STOP:2026-01-02")
    assert first == second
    assert first != other
    assert first.value.version == 7
    assert first.value.variant == "specified in RFC 4122"
