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
from .supervision import SupervisionCard
from .durable import (
    ControlHandler,
    DurableWatchWorker,
    NotificationSLOPolicy,
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
    "SupervisionCard",
    "ChannelRegistry",
    "ControlHandler",
    "DurableWatchWorker",
    "NotificationSLOPolicy",
    "GatewayTask",
    "IdentityMapping",
    "IngestResult",
    "OutboxRecord",
    "OutboxWorker",
    "PostgresNotificationSink",
    "PostgresGatewayStore",
]
from .registry import ChannelRegistry
