"""Replaceable communication channel gateway surfaces."""

from .contracts import (
    ChannelAdapter,
    ControlCallback,
    IdempotentControls,
    IdempotentInbox,
    InboundEvent,
    NotificationDispatcher,
    OutboundNotification,
)
from .feishu import FeishuAdapter, FeishuLongConnectionAdapter
from .gateway import ChannelGateway
from .durable import (
    ControlHandler,
    GatewayTask,
    IdentityMapping,
    IngestResult,
    OutboxRecord,
    OutboxWorker,
    PostgresNotificationSink,
    PostgresGatewayStore,
)

__all__ = [
    "ChannelAdapter",
    "ControlCallback",
    "IdempotentControls",
    "IdempotentInbox",
    "InboundEvent",
    "NotificationDispatcher",
    "OutboundNotification",
    "FeishuAdapter",
    "FeishuLongConnectionAdapter",
    "ChannelGateway",
    "ChannelRegistry",
    "ControlHandler",
    "GatewayTask",
    "IdentityMapping",
    "IngestResult",
    "OutboxRecord",
    "OutboxWorker",
    "PostgresNotificationSink",
    "PostgresGatewayStore",
]
from .registry import ChannelRegistry
