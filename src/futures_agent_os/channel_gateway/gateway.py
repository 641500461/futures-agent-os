from .contracts import ChannelAdapter, ControlCallback, IdempotentInbox, IdempotentControls, NotificationDispatcher, InboundEvent, OutboundNotification


class ChannelGateway:
    def __init__(self) -> None:
        self.inbox = IdempotentInbox()
        self.controls = IdempotentControls()
        self.notifications = NotificationDispatcher()

    def ingest(self, event: InboundEvent) -> bool:
        return self.inbox.ingest(event)

    def control(self, callback: ControlCallback) -> bool:
        return self.controls.accept(callback)

    def notify(self, adapter: ChannelAdapter, notification: OutboundNotification) -> bool:
        return self.notifications.dispatch(adapter, notification)
