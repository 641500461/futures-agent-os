from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from futures_agent_os.channel_gateway import GatewayInboundWorker, GatewayTask, LocalOperatorCommandHandler
from futures_agent_os.cli import build_parser


def _envelope(text: object = "状态", *, event_id: str = "event-1") -> dict[str, Any]:
    return {
        "channel": "feishu",
        "event_id": event_id,
        "actor_id": "operator",
        "conversation_id": "chat",
        "kind": "message",
        "payload": {"content": json.dumps({"text": text}, ensure_ascii=False)},
        "occurred_at": datetime(2026, 9, 16, 1, 0, tzinfo=UTC).isoformat(),
        "actor_ref": "user:owner",
        "target_ref": "account:simulation",
    }


def test_local_operator_status_trial_and_restart_safe_review(tmp_path: Path) -> None:
    first = LocalOperatorCommandHandler(tmp_path)
    assert "真实订单路由：关闭" in first.handle(_envelope()).text

    completed = first.handle(_envelope("运行模拟", event_id="event-2"))
    assert "模拟演练完成" in completed.text
    assert "合成确定性行情" in completed.text

    restarted = LocalOperatorCommandHandler(tmp_path)
    review = restarted.handle(_envelope("复盘", event_id="event-3"))
    assert "最近一次模拟复盘" in review.text
    assert "不代表策略具有收益优势" in review.text


def test_local_operator_unknown_or_malformed_text_returns_bounded_help(tmp_path: Path) -> None:
    handler = LocalOperatorCommandHandler(tmp_path)
    unknown = handler.handle(_envelope("给我下真实订单"))
    malformed = handler.handle({**_envelope(), "payload": {"content": {"not": "text"}}})
    assert unknown.text == malformed.text
    assert "控制卡片" in unknown.text


def test_local_operator_review_fails_closed_when_artifact_is_modified(tmp_path: Path) -> None:
    handler = LocalOperatorCommandHandler(tmp_path)
    handler.handle(_envelope("运行模拟", event_id="event-2"))
    payload = json.loads(handler.latest_trial_path.read_text(encoding="utf-8"))
    payload["result"]["ending_cash"] = "999999"
    handler.latest_trial_path.write_text(json.dumps(payload), encoding="utf-8")
    assert "完整性校验失败" in handler.handle(_envelope("复盘", event_id="event-3")).text


class _Store:
    def __init__(self) -> None:
        self.task = GatewayTask(uuid4(), _envelope("状态"), 3, "worker")
        self.notifications: list[object] = []
        self.completions: list[tuple[UUID, str, int, bool]] = []

    def claim_tasks(self, worker_id: str, **_: object) -> tuple[GatewayTask, ...]:
        assert worker_id == "worker"
        return (self.task,)

    def enqueue_notification(self, notification: object) -> bool:
        self.notifications.append(notification)
        return True

    def complete_task(self, task_id: UUID, worker_id: str, fencing_token: int, *, success: bool = True) -> bool:
        self.completions.append((task_id, worker_id, fencing_token, success))
        return True


def test_gateway_inbound_worker_claims_fenced_task_and_enqueues_reply(tmp_path: Path) -> None:
    store = _Store()
    worker = GatewayInboundWorker(store, LocalOperatorCommandHandler(tmp_path), worker_id="worker")  # type: ignore[arg-type]
    assert worker.run_once() == 1
    assert len(store.notifications) == 1
    assert store.completions == [(store.task.task_id, "worker", 3, True)]


def test_restricted_research_cli_defaults_match_observed_local_provider() -> None:
    args = build_parser().parse_args(("research",))
    assert args.provider == "custom"
    assert args.timeout_seconds == 300
