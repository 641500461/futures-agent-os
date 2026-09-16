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
from .operator_commands import GatewayInboundWorker, LocalOperatorCommandHandler, OperatorCommandHandler
from .local_controls import LocalSimulationControlOwner
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
    "GatewayInboundWorker",
    "LocalOperatorCommandHandler",
    "OperatorCommandHandler",
    "LocalSimulationControlOwner",
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
