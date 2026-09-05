"""Small deterministic account projection for V2 simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.decision import Fill, PositionLot, Settlement, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt


@dataclass(frozen=True, slots=True)
class AccountState:
    cash: Decimal
    margin: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    lots: tuple[PositionLot, ...] = ()


class SimulationAccount:
    def __init__(
        self, initial_cash: Decimal, contract_multiplier: Decimal = Decimal("1"), account_id: EntityId | None = None
    ) -> None:
        if not isinstance(initial_cash, Decimal) or not initial_cash.is_finite() or initial_cash < 0:
            raise ValueError("initial cash must be non-negative")
        if (
            not isinstance(contract_multiplier, Decimal)
            or not contract_multiplier.is_finite()
            or contract_multiplier <= 0
        ):
            raise ValueError("contract multiplier must be positive")
        self._multiplier = contract_multiplier
        self._account_id = account_id
        self._state = AccountState(initial_cash)
        self._applied_fills: set[EntityId] = set()

    @property
    def state(self) -> AccountState:
        return self._state

    def reserve_margin(self, amount: Decimal) -> AccountState:
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
            raise ValueError("margin reservation must be positive")
        if self._state.cash - self._state.margin < amount:
            raise ValueError("insufficient available cash for margin")
        self._state = AccountState(
            self._state.cash, self._state.margin + amount, self._state.realized_pnl, self._state.fees, self._state.lots
        )
        return self._state

    def release_margin(self, amount: Decimal) -> AccountState:
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0 or amount > self._state.margin:
            raise ValueError("margin release exceeds frozen margin")
        self._state = AccountState(
            self._state.cash, self._state.margin - amount, self._state.realized_pnl, self._state.fees, self._state.lots
        )
        return self._state

    def mark_to_market(
        self, settlement_id: EntityId, trading_date: str, settlement_price: Decimal, now: RecordedAt
    ) -> Settlement:
        if not isinstance(settlement_price, Decimal) or not settlement_price.is_finite() or settlement_price <= 0:
            raise ValueError("settlement price must be positive")
        pnl = Decimal("0")
        for lot in self._state.lots:
            sign = Decimal("1") if lot.direction is TradeDirection.LONG else Decimal("-1")
            pnl += (settlement_price - lot.average_price) * lot.quantity * sign * self._multiplier
        return Settlement(
            settlement_id,
            self._account_id or EntityId.new("simulation_account"),
            trading_date,
            pnl,
            pnl,
            Decimal("0"),
            now,
        )

    def apply_fill(self, fill: Fill, *, lot_id, account_id) -> AccountState:
        if fill.fill_id in self._applied_fills:
            return self._state
        if self._account_id is not None and account_id != self._account_id:
            raise ValueError("fill account mismatch")
        cash = self._state.cash - fill.fee
        lot = PositionLot(
            lot_id, account_id, fill.instrument, fill.direction, fill.quantity, fill.price, fill.filled_at
        )
        self._state = AccountState(
            cash, self._state.margin, self._state.realized_pnl, self._state.fees + fill.fee, self._state.lots + (lot,)
        )
        self._applied_fills.add(fill.fill_id)
        return self._state

    def settle(self, settlement: Settlement) -> AccountState:
        if self._account_id is not None and settlement.account_id != self._account_id:
            raise ValueError("settlement account mismatch")
        self._state = AccountState(
            self._state.cash + settlement.cash_delta,
            self._state.margin,
            self._state.realized_pnl + settlement.realized_pnl,
            self._state.fees + settlement.fees,
            self._state.lots,
        )
        return self._state

    def close(self, fill: Fill) -> AccountState:
        """Apply a reducing fill against the oldest compatible lot."""
        candidates = [
            lot for lot in self._state.lots if lot.instrument == fill.instrument and lot.direction is not fill.direction
        ]
        available = sum((lot.quantity for lot in candidates), Decimal("0"))
        if fill.quantity > available:
            raise ValueError("close quantity exceeds position")
        remaining = fill.quantity
        realized = Decimal("0")
        lots: list[PositionLot] = []
        for lot in self._state.lots:
            if lot not in candidates or remaining <= 0:
                lots.append(lot)
                continue
            matched = min(lot.quantity, remaining)
            direction_sign = Decimal("1") if lot.direction is TradeDirection.LONG else Decimal("-1")
            realized += (fill.price - lot.average_price) * matched * direction_sign * self._multiplier
            remaining -= matched
            if lot.quantity > matched:
                lots.append(
                    PositionLot(
                        lot.lot_id,
                        lot.account_id,
                        lot.instrument,
                        lot.direction,
                        lot.quantity - matched,
                        lot.average_price,
                        lot.opened_at,
                    )
                )
        self._state = AccountState(
            self._state.cash + realized - fill.fee,
            self._state.margin,
            self._state.realized_pnl + realized,
            self._state.fees + fill.fee,
            tuple(lots),
        )
        return self._state
