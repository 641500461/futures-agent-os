"""Channel-neutral gateway contracts.

The contracts in this module deliberately contain no database or vendor SDK
types.  Durable implementations live in :mod:`channel_gateway.durable` and
channel adapters translate their wire payloads into these values.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Mapping, Any

_SEVERITIES = frozenset({"INFO", "TRADE", "ACTION_REQUIRED", "RISK", "CRITICAL"})


@dataclass(frozen=True)
class InboundEvent:
    channel: str
    event_id: str
    actor_id: str
    conversation_id: str
    kind: str
    payload: Mapping[str, Any]
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("channel", "event_id", "actor_id", "conversation_id", "kind"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

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
    payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.channel.strip() or not self.conversation_id.strip() or not self.idempotency_key.strip():
            raise ValueError("channel, conversation_id, and idempotency_key are required")
        normalized = self.severity.upper()
        if normalized not in _SEVERITIES:
            raise ValueError(f"unsupported notification severity: {self.severity}")
        object.__setattr__(self, "severity", normalized)
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise ValueError("notification payload must be a mapping")

    @property
    def delivery_key(self) -> str:
        """Stable key scoped to the channel, suitable for durable deduplication."""

        return f"{self.channel}:{self.idempotency_key}"


@dataclass(frozen=True)
class ControlCallback:
    channel: str
    callback_id: str
    actor_id: str
    action: str
    payload: Mapping[str, Any]
    target_id: str | None = None
    target_version: int | None = None
    target_sha256: str | None = None
    expires_at: datetime | None = None
    token: str | None = None

    def __post_init__(self) -> None:
        if not self.channel.strip() or not self.callback_id.strip() or not self.actor_id.strip():
            raise ValueError("channel, callback_id, and actor_id are required")
        action = self.action.lower().strip()
        object.__setattr__(self, "action", action)
        if action not in _ALLOWED_CONTROL_ACTIONS:
            raise ValueError("unsupported control action")
        if self.target_version is not None and self.target_version < 0:
            raise ValueError("target_version must be non-negative")
        if self.target_sha256 is not None and (
            len(self.target_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.target_sha256)
        ):
            raise ValueError("target_sha256 must be a lowercase SHA-256 digest")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


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
        capabilities = getattr(adapter, "capabilities", lambda: frozenset({"notify"}))()
        if "notify" not in capabilities:
            raise NotImplementedError(f"channel {adapter.channel} does not support notifications")
        if notification.delivery_key in self._sent:
            return False
        adapter.send(notification)
        self._sent.add(notification.delivery_key)
        return True


_ALLOWED_CONTROL_ACTIONS = frozenset({"pause", "resume", "revoke", "kill_switch"})


def validate_control(callback: ControlCallback) -> None:
    if callback.action.lower() not in _ALLOWED_CONTROL_ACTIONS:
        raise ValueError("unsupported control action")


class InboxStore(Protocol):
    def put_if_absent(self, event: InboundEvent) -> bool: ...
    def get(self, key: str) -> InboundEvent | None: ...


class MemoryInboxStore:
    def __init__(self) -> None:
        self._items: dict[str, InboundEvent] = {}

    def put_if_absent(self, event: InboundEvent) -> bool:
        old = self._items.get(event.dedup_key)
        if old is not None:
            if old != event:
                raise ValueError("conflicting replay for channel event")
            return False
        self._items[event.dedup_key] = event
        return True

    def get(self, key: str) -> InboundEvent | None:
        return self._items.get(key)


class NotificationSink(Protocol):
    def send(self, adapter: ChannelAdapter, notification: OutboundNotification) -> bool: ...


class MemoryNotificationSink:
    def __init__(self) -> None:
        self._sent: set[str] = set()

    def send(self, adapter: ChannelAdapter, notification: OutboundNotification) -> bool:
        if notification.delivery_key in self._sent:
            return False
        adapter.send(notification)
        self._sent.add(notification.delivery_key)
        return True


def notification_severities() -> frozenset[str]:
    return _SEVERITIES
