"""Bounded local operator commands consumed from the durable gateway inbox.

This module deliberately exposes only read-only status/help commands and the
existing synthetic, simulation-only local trial.  Risk controls continue to
use pre-issued :class:`ControlCallback` values and are never inferred from
free-form chat text.
"""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from futures_agent_os.local_trial import run_local_trial
from futures_agent_os.shared_kernel import canonical_json_text

from .contracts import InboundEvent, OutboundNotification
from .durable import GatewayTask, PostgresGatewayStore
from .local_controls import LocalSimulationControlOwner


class OperatorCommandHandler(Protocol):
    def handle(self, envelope: Mapping[str, Any]) -> OutboundNotification: ...


@dataclass(frozen=True, slots=True)
class LocalOperatorCommandHandler:
    """Handle the minimal trusted-local operator command vocabulary."""

    state_directory: Path
    control_owner: LocalSimulationControlOwner | None = None

    @property
    def latest_trial_path(self) -> Path:
        return self.state_directory / "latest-trial.json"

    def handle(self, envelope: Mapping[str, Any]) -> OutboundNotification:
        event = _hydrate_event(envelope)
        command = _command_text(event.payload)
        if command in {"状态", "status"}:
            text = _status_text(self.control_owner)
        elif command in {"运行模拟", "模拟", "run simulation", "trial"}:
            if self.control_owner is not None and not self.control_owner.permits_new_simulation():
                raise RuntimeError("local simulation is paused by an issued control callback")
            record = self._run_trial(event)
            text = _trial_text(record)
        elif command in {"复盘", "review"}:
            text = self._review_text()
        else:
            text = _help_text()
        return OutboundNotification(
            event.channel,
            event.conversation_id,
            "INFO",
            text,
            f"operator-command:{event.dedup_key}",
        )

    def _run_trial(self, event: InboundEvent) -> Mapping[str, Any]:
        result = run_local_trial(event.occurred_at).as_dict()
        payload: dict[str, Any] = {
            "schema_version": "local-operator-trial.v1",
            "source_event": event.dedup_key,
            "executed_at": event.occurred_at.isoformat(),
            "result": result,
        }
        payload["content_sha256"] = _json_sha256(payload)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.latest_trial_path.with_suffix(".json.tmp")
        temporary.write_text(canonical_json_text(payload) + "\n", encoding="utf-8")
        os.replace(temporary, self.latest_trial_path)
        return result

    def _review_text(self) -> str:
        try:
            value = json.loads(self.latest_trial_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "尚无本地模拟记录。发送“运行模拟”后再查看复盘。"
        if not isinstance(value, dict):
            return "最近模拟记录无效，已安全拒绝复盘。"
        digest = value.pop("content_sha256", None)
        if not isinstance(digest, str) or _json_sha256(value) != digest:
            return "最近模拟记录完整性校验失败，已安全拒绝复盘。"
        result = value.get("result")
        if not isinstance(result, dict):
            return "最近模拟记录无效，已安全拒绝复盘。"
        return _review_text(result)


class GatewayInboundWorker:
    """Claim durable inbound tasks and emit idempotent outbox replies."""

    def __init__(
        self,
        store: PostgresGatewayStore,
        handler: OperatorCommandHandler,
        worker_id: str = "gateway-inbound",
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self.store = store
        self.handler = handler
        self.worker_id = worker_id

    def run_once(self, *, limit: int = 10) -> int:
        tasks = self.store.claim_tasks(
            self.worker_id,
            limit=limit,
            assigned_role_prefix="gateway.inbound",
        )
        for task in tasks:
            self._handle_task(task)
        return len(tasks)

    def _handle_task(self, task: GatewayTask) -> None:
        try:
            notification = self.handler.handle(task.envelope)
            self.store.enqueue_notification(notification)
        except Exception as error:
            event = _hydrate_event(task.envelope)
            self.store.enqueue_notification(
                OutboundNotification(
                    event.channel,
                    event.conversation_id,
                    "ACTION_REQUIRED",
                    f"操作者命令处理失败，系统已安全停止：{type(error).__name__}",
                    f"operator-command-failed:{task.task_id}",
                )
            )
            self.store.complete_task(task.task_id, task.worker_id, task.fencing_token, success=False)
            return
        self.store.complete_task(task.task_id, task.worker_id, task.fencing_token)


def _hydrate_event(envelope: Mapping[str, Any]) -> InboundEvent:
    required = ("channel", "event_id", "actor_id", "conversation_id", "kind", "payload", "occurred_at")
    if any(name not in envelope for name in required) or not isinstance(envelope["payload"], Mapping):
        raise ValueError("invalid gateway inbound envelope")
    return InboundEvent(
        str(envelope["channel"]),
        str(envelope["event_id"]),
        str(envelope["actor_id"]),
        str(envelope["conversation_id"]),
        str(envelope["kind"]),
        envelope["payload"],
        datetime.fromisoformat(str(envelope["occurred_at"])),
    )


def _command_text(payload: Mapping[str, Any]) -> str:
    raw = payload.get("text", payload.get("content", ""))
    if not isinstance(raw, str):
        return ""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = raw
    if isinstance(decoded, Mapping):
        decoded = decoded.get("text", "")
    return str(decoded).strip().casefold()


def _json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _status_text(control_owner: LocalSimulationControlOwner | None = None) -> str:
    control_state = control_owner.state() if control_owner is not None else "RUNNING"
    return "\n".join(
        (
            "Futures Agent OS 已在线。",
            "运行边界：研究与模拟。",
            "飞书：双向长连接。",
            "真实订单路由：关闭。",
            "当前范围：SHFE AG/CU 受限研究；本地演练使用合成确定性行情。",
            f"本地模拟控制状态：{control_state}。",
        )
    )


def _trial_text(result: Mapping[str, Any]) -> str:
    return "\n".join(
        (
            "模拟演练完成。",
            f"结果：{result['outcome']}",
            f"流程阶段：{len(result['steps'])}",
            f"审计日志：{result['journal_entries']} 条",
            f"保护动作：{result['protective_action_id']}",
            f"期末现金：{result['ending_cash']}",
            "发送“复盘”查看结论。",
            "说明：本次使用合成确定性行情，不是实时行情或真实交易。",
        )
    )


def _review_text(result: Mapping[str, Any]) -> str:
    return "\n".join(
        (
            "最近一次模拟复盘：",
            f"• 周期结果：{result['outcome']}",
            "• 建仓后价格跌破保护阈值，确定性保护链执行退出",
            "• 成交、持仓、保护、退出和结算均已形成引用",
            f"• 期末现金：{result['ending_cash']}",
            "该结果验证系统闭环，不代表策略具有收益优势。",
        )
    )


def _help_text() -> str:
    return "可用命令：状态、运行模拟、复盘。暂停、撤销和 Kill Switch 只能使用系统签发的控制卡片。"


__all__ = ["GatewayInboundWorker", "LocalOperatorCommandHandler", "OperatorCommandHandler"]
