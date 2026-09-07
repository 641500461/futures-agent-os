from .contracts import (
    ChannelAdapter,
    ControlCallback,
    IdempotentControls,
    InboundEvent,
    OutboundNotification,
    InboxStore,
    MemoryInboxStore,
    NotificationSink,
    MemoryNotificationSink,
)
from .durable import PostgresGatewayStore


class ChannelGateway:
    def __init__(self, store: PostgresGatewayStore | None = None) -> None:
        self.store = store
        self.inbox: InboxStore = store if store is not None else MemoryInboxStore()
        self.controls = IdempotentControls()
        self.notifications: NotificationSink = MemoryNotificationSink()

    def ingest(self, event: InboundEvent) -> bool:
        if self.store is not None:
            return self.store.ingest(event).accepted
        return self.inbox.put_if_absent(event)

    def poll(self, adapter: ChannelAdapter) -> tuple[InboundEvent, ...]:
        accepted = []
        for event in adapter.receive():
            if self.ingest(event):
                accepted.append(event)
        return tuple(accepted)

    def control(self, callback: ControlCallback) -> bool:
        return self.controls.accept(callback)

    def dispatch_control(self, callback: ControlCallback, handler: object, **kwargs: object) -> bool:
        if self.store is None:
            raise RuntimeError("durable store is required for control dispatch")
        return self.store.dispatch_control(callback, handler, **kwargs)  # type: ignore[arg-type]

    def notify(
        self, adapter: ChannelAdapter, notification: OutboundNotification, *, connection: object | None = None
    ) -> bool:
        if self.store is not None:
            if notification.channel != adapter.channel:
                raise ValueError("notification channel does not match adapter")
            capabilities = getattr(adapter, "capabilities", lambda: frozenset({"notify"}))()
            if "notify" not in capabilities:
                raise NotImplementedError(f"channel {adapter.channel} does not support notifications")
            return self.store.enqueue_notification(notification, connection=connection)  # type: ignore[arg-type]
        capabilities = getattr(adapter, "capabilities", lambda: frozenset({"notify"}))()
        if "notify" not in capabilities:
            raise NotImplementedError(f"channel {adapter.channel} does not support notifications")
        return self.notifications.send(adapter, notification)
