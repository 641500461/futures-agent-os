"""Execution simulation bounded context."""

from .fill_model import FillDecision, FillOrderType, IntrabarAmbiguityPolicy, L1Bar, L1FillModel
from .protection import (
    ProtectionTriggerEvaluator,
    ProtectionTriggerKind,
    ProtectionValidator,
    ProtectiveRiskAction,
    RiskReductionRequest,
    RiskReductionValidation,
    ThesisInvalidationSpec,
    ValidationOutcome,
    ProtectiveActionRegistry,
    DurableProtectiveActionRegistry,
)
from .l2_model import BookEvent, L2EventFillModel
from .fault_injection import FaultInjector, FaultKind, FaultResult, RecoveryResult
from .engine import EngineResult, SimulationEngine
from .manual_shadow import ManualShadowReport, run_manual_shadow_episode
from .strategy_replay import FrozenStrategySpecFixture, L2ReplayMatrix, L2ReplayResult, replay_v1_candidate_l2_matrix

# Execution owns these contracts; decision re-exports remain for callers on
# the initial V2-001 surface.
from .contracts import ExecutionPlan, Fill, Order, OrderStatus, StopPolicy
from .order_processor import (
    DurableOrderCommandProcessor,
    OrderCommandProcessor,
    OrderCommandResult,
    OrderProcessorSnapshot,
)

__all__ = [
    "FillDecision",
    "FillOrderType",
    "IntrabarAmbiguityPolicy",
    "L1Bar",
    "L1FillModel",
    "ProtectionTriggerKind",
    "ProtectionValidator",
    "ProtectiveRiskAction",
    "ThesisInvalidationSpec",
    "RiskReductionRequest",
    "RiskReductionValidation",
    "ValidationOutcome",
    "ProtectionTriggerEvaluator",
    "ProtectiveActionRegistry",
    "DurableProtectiveActionRegistry",
    "BookEvent",
    "L2EventFillModel",
    "FaultInjector",
    "FaultKind",
    "FaultResult",
    "RecoveryResult",
    "EngineResult",
    "SimulationEngine",
    "ManualShadowReport",
    "run_manual_shadow_episode",
    "FrozenStrategySpecFixture",
    "L2ReplayResult",
    "L2ReplayMatrix",
    "replay_v1_candidate_l2_matrix",
    "ExecutionPlan",
    "StopPolicy",
    "Order",
    "OrderStatus",
    "Fill",
    "OrderCommandProcessor",
    "OrderCommandResult",
    "OrderProcessorSnapshot",
    "DurableOrderCommandProcessor",
]
