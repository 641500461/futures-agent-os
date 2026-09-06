"""Shared deterministic event-to-fill-to-account simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Order
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from .fill_model import FillOrderType, L1Bar, L1FillModel
from .l2_model import BookEvent, L2EventFillModel


@dataclass(frozen=True, slots=True)
class EngineResult:
    order: Order
    account_cash: Decimal
    fill: Fill | None = None


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
        # The same immutable order/bar/timestamp tuple must produce the same
        # Fill identity after a restart.  Runtime UUIDv7 entropy here would
        # make an otherwise identical replay appear as a second business fact.
        fill_seed = canonical_sha256(
            {
                "order_id": str(order.order_id),
                "quantity": str(decision.filled_quantity),
                "price": str(decision.price),
                "filled_at": now.to_dict()["recorded_at"],
            }
        )
        fill = Fill(
            EntityId.deterministic("fill", fill_seed),
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
            lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)),
            account_id=account.account_id or EntityId.new("simulation_account"),
        )
        return EngineResult(filled, account.state.cash, fill)

    def execute_l2(
        self,
        order: Order,
        events: tuple[BookEvent, ...],
        account: SimulationAccount,
        *,
        now: RecordedAt,
        order_type: FillOrderType = FillOrderType.MARKET,
    ) -> EngineResult:
        """Run the same order/account path against a frozen L2 event stream."""
        decision = L2EventFillModel().simulate(order, events, order_type=order_type)
        if decision.filled_quantity <= 0 or decision.price is None:
            return EngineResult(order, account.state.cash)
        filled = order.apply_fill(decision.filled_quantity)
        fill_seed = canonical_sha256(
            {
                "order_id": str(order.order_id),
                "quantity": str(decision.filled_quantity),
                "price": str(decision.price),
                "filled_at": now.to_dict()["recorded_at"],
                "events": tuple(event.sequence for event in events),
            }
        )
        fill = Fill(
            EntityId.deterministic("fill", fill_seed),
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
            lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)),
            account_id=account.account_id or EntityId.new("simulation_account"),
        )
        return EngineResult(filled, account.state.cash, fill)
