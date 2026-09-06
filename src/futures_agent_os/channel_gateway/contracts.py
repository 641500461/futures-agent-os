"""Channel-neutral gateway contracts and idempotent inbox."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Mapping, Any


@dataclass(frozen=True)
class InboundEvent:
    channel: str
    event_id: str
    actor_id: str
    conversation_id: str
    kind: str
    payload: Mapping[str, Any]
    occurred_at: datetime

    @property
    def dedup_key(self) -> str:
        return f"{self.channel}:{self.event_id}"


@dataclass(frozen=True)
class OutboundNotification:
    channel: str
    conversation_id: str
    severity: str
    text: str
    idempotency_key: str


@dataclass(frozen=True)
class ControlCallback:
    channel: str
    callback_id: str
    actor_id: str
    action: str
    payload: Mapping[str, Any]


class ChannelAdapter(Protocol):
    channel: str

    def receive(self) -> list[InboundEvent]: ...
    def send(self, notification: OutboundNotification) -> None: ...
    def capabilities(self) -> frozenset[str]: ...


class IdempotentInbox:
    def __init__(self) -> None:
        self._events: dict[str, InboundEvent] = {}

    def ingest(self, event: InboundEvent) -> bool:
        prior = self._events.get(event.dedup_key)
        if prior is not None:
            if prior != event:
                raise ValueError("conflicting replay for channel event")
            return False
        self._events[event.dedup_key] = event
        return True

    def get(self, channel: str, event_id: str) -> InboundEvent | None:
        return self._events.get(f"{channel}:{event_id}")


class IdempotentControls:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def accept(self, callback: ControlCallback) -> bool:
        key = f"{callback.channel}:{callback.callback_id}"
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class NotificationDispatcher:
    def __init__(self) -> None:
        self._sent: set[str] = set()

    def dispatch(self, adapter: ChannelAdapter, notification: OutboundNotification) -> bool:
        if notification.channel != adapter.channel:
            raise ValueError("notification channel does not match adapter")
        if notification.idempotency_key in self._sent:
            return False
        adapter.send(notification)
        self._sent.add(notification.idempotency_key)
        return True


_ALLOWED_CONTROL_ACTIONS = frozenset({"pause", "resume", "revoke", "kill_switch"})


def validate_control(callback: ControlCallback) -> None:
    if callback.action not in _ALLOWED_CONTROL_ACTIONS:
        raise ValueError("unsupported control action")
