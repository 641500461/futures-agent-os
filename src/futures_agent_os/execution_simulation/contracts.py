"""Execution & Simulation-owned V2 contract surface."""

from dataclasses import dataclass

from futures_agent_os.decision.trade_contracts import (
    ExecutionPlan as _DecisionExecutionPlan,
    Fill as _DecisionFill,
    Order as _DecisionOrder,
    OrderStatus,
    StopPolicy as _DecisionStopPolicy,
)
from futures_agent_os.execution_simulation.protection import (
    ProtectiveRiskAction,
    RiskReductionRequest,
    RiskReductionValidation,
)

__all__ = [
    "ExecutionPlan",
    "StopPolicy",
    "Order",
    "OrderStatus",
    "Fill",
    "RiskReductionRequest",
    "RiskReductionValidation",
    "ProtectiveRiskAction",
]


@dataclass(frozen=True, slots=True)
class ExecutionPlan(_DecisionExecutionPlan):
    """Execution & Simulation canonical owner type."""

    pass


@dataclass(frozen=True, slots=True)
class StopPolicy(_DecisionStopPolicy):
    """Execution & Simulation canonical owner type for stops."""

    pass


@dataclass(frozen=True, slots=True)
class Order(_DecisionOrder):
    """Execution & Simulation canonical owner type for orders."""

    pass


@dataclass(frozen=True, slots=True)
class Fill(_DecisionFill):
    """Execution & Simulation canonical owner type for fills."""

    pass
