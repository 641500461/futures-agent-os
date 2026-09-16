from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from futures_agent_os.channel_gateway import ControlCallback, LocalSimulationControlOwner
from futures_agent_os.channel_gateway.operator_commands import LocalOperatorCommandHandler


def _callback(action: str, *, target: str = "account:local-simulation") -> ControlCallback:
    return ControlCallback(
        "feishu",
        f"callback-{action}",
        "user:owner",
        action,
        {},
        target_id=target,
        target_version=1,
        target_sha256="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_signed_control_changes_local_simulation_gate(tmp_path: Path) -> None:
    owner = LocalSimulationControlOwner(tmp_path)
    owner.dispatch(_callback("pause"), None)  # type: ignore[arg-type]
    assert not owner.permits_new_simulation()
    assert (
        "PAUSED"
        in LocalOperatorCommandHandler(tmp_path, owner)
        .handle(
            {
                "channel": "feishu",
                "event_id": "status",
                "actor_id": "user:owner",
                "conversation_id": "chat",
                "kind": "message",
                "payload": {"text": "状态"},
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        )
        .text
    )
    with pytest.raises(RuntimeError, match="paused"):
        LocalOperatorCommandHandler(tmp_path, owner).handle(
            {
                "channel": "feishu",
                "event_id": "run",
                "actor_id": "user:owner",
                "conversation_id": "chat",
                "kind": "message",
                "payload": {"text": "运行模拟"},
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        )
    owner.dispatch(_callback("resume"), None)  # type: ignore[arg-type]
    assert owner.permits_new_simulation()


def test_kill_switch_and_wrong_target_fail_closed(tmp_path: Path) -> None:
    owner = LocalSimulationControlOwner(tmp_path)
    owner.dispatch(_callback("kill_switch"), None)  # type: ignore[arg-type]
    assert owner.state() == "KILL_SWITCH"
    with pytest.raises(PermissionError):
        owner.dispatch(_callback("resume"), None)  # type: ignore[arg-type]
    with pytest.raises(PermissionError):
        owner.dispatch(_callback("resume", target="account:other"), None)  # type: ignore[arg-type]
