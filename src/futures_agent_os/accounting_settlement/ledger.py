"""Small deterministic account projection for V2 simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.decision import Fill, PositionLot, Settlement
from futures_agent_os.shared_kernel import EntityId


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
