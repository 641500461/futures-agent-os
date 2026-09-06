from .contracts import (
    ChannelAdapter,
    ControlCallback,
    IdempotentControls,
    NotificationDispatcher,
    InboundEvent,
    OutboundNotification,
    InboxStore,
    MemoryInboxStore,
)


class ChannelGateway:
    def __init__(self) -> None:
        self.inbox: InboxStore = MemoryInboxStore()
        self.controls = IdempotentControls()
        self.notifications = NotificationDispatcher()

    def ingest(self, event: InboundEvent) -> bool:
        return self.inbox.put_if_absent(event)

    def poll(self, adapter: ChannelAdapter) -> tuple[InboundEvent, ...]:
        accepted = []
        for event in adapter.receive():
            if self.ingest(event):
                accepted.append(event)
        return tuple(accepted)

    def control(self, callback: ControlCallback) -> bool:
        return self.controls.accept(callback)

    def notify(self, adapter: ChannelAdapter, notification: OutboundNotification) -> bool:
        return self.notifications.dispatch(adapter, notification)
