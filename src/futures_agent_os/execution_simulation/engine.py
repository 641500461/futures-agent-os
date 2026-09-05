"""Shared deterministic event-to-fill-to-account simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Order
from futures_agent_os.shared_kernel import EntityId, RecordedAt
from .fill_model import FillOrderType, L1Bar, L1FillModel


@dataclass(frozen=True, slots=True)
class EngineResult:
    order: Order
    account_cash: Decimal


class SimulationEngine:
    """The same deterministic path can be used by replay and paper simulation."""

    def execute_l1(
        self,
        order: Order,
        bar: L1Bar,
        account: SimulationAccount,
        *,
        now: RecordedAt,
        order_type: FillOrderType = FillOrderType.MARKET,
    ) -> EngineResult:
        decision = L1FillModel().simulate(order, bar, order_type=order_type)
        if decision.filled_quantity <= 0 or decision.price is None:
            return EngineResult(order, account.state.cash)
        filled = order.apply_fill(decision.filled_quantity)
        fill = Fill(
            EntityId.new("fill"),
            order.order_id,
            order.instrument,
            order.direction,
            decision.filled_quantity,
            decision.price,
            Decimal("0"),
            now,
        )
        account.apply_fill(
            fill,
            lot_id=EntityId.new("position_lot"),
            account_id=account.account_id or EntityId.new("simulation_account"),
        )
        return EngineResult(filled, account.state.cash)
