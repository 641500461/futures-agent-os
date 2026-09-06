"""Feishu adapter: protocol translation only."""
from datetime import datetime, timezone
from typing import Any, Mapping
from .contracts import InboundEvent, OutboundNotification, ControlCallback

class FeishuAdapter:
    channel = "feishu"
    def __init__(self) -> None:
        self.outbox: list[OutboundNotification] = []
    def parse_event(self, payload: Mapping[str, Any]) -> InboundEvent:
        event_id = str(payload["event_id"])
        return InboundEvent(self.channel, event_id, str(payload["actor_id"]), str(payload["conversation_id"]), str(payload.get("kind", "message")), dict(payload.get("data", {})), datetime.now(timezone.utc))
    def parse_callback(self, payload: Mapping[str, Any]) -> ControlCallback:
        return ControlCallback(self.channel, str(payload["callback_id"]), str(payload["actor_id"]), str(payload["action"]), dict(payload.get("data", {})))
    def send(self, notification: OutboundNotification) -> None:
        if notification.channel != self.channel:
            raise ValueError("wrong channel")
        self.outbox.append(notification)
    def capabilities(self) -> frozenset[str]:
        return frozenset({"notify", "explain", "pause", "resume", "revoke", "kill_switch"})
