"""Small deterministic account projection for V2 simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from dataclasses import replace

from futures_agent_os.decision import Fill, PositionLot, Settlement, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt


@dataclass(frozen=True, slots=True)
class AccountState:
    cash: Decimal
    margin: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    lots: tuple[PositionLot, ...] = ()

    @property
    def equity(self) -> Decimal:
        """Cash balance; realized PnL is already reflected by settlement/close."""
        return self.cash


@dataclass(frozen=True, slots=True)
class SimulationAccountSnapshot:
    """Durable-ready account projection snapshot.

    Applied event identities are part of the snapshot.  Restoring only the
    visible cash/lots would make a retried Fill or Settlement create a second
    business effect after a process restart.
    """

    initial_cash: Decimal
    contract_multiplier: Decimal
    account_id: EntityId | None
    state: AccountState
    applied_fills: tuple[EntityId, ...]
    applied_settlements: tuple[EntityId, ...]
    settlement_dates: tuple[str, ...]
    settlement_cash_adjustment: Decimal


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
        self._initial_cash = initial_cash
        self._state = AccountState(initial_cash)
        self._applied_fills: set[EntityId] = set()
        self._applied_settlements: set[EntityId] = set()
        self._settlement_dates: set[str] = set()
        # A settlement's cash_delta may include a component other than
        # realized_pnl (for example fees or exchange adjustments).  Track that
        # component so conservation remains checkable after replay.
        self._settlement_cash_adjustment = Decimal("0")
        self._lock = RLock()

    @property
    def state(self) -> AccountState:
        return self._state

    @property
    def account_id(self) -> EntityId | None:
        return self._account_id

    @property
    def equity(self) -> Decimal:
        return self._state.equity

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        if not isinstance(mark_price, Decimal) or not mark_price.is_finite() or mark_price <= 0:
            raise ValueError("mark price must be positive")
        with self._lock:
            total = Decimal("0")
            for lot in self._state.lots:
                sign = Decimal("1") if lot.direction is TradeDirection.LONG else Decimal("-1")
                total += (mark_price - lot.average_price) * lot.quantity * sign * self._multiplier
            return total

    def reserve_margin(self, amount: Decimal) -> AccountState:
        with self._lock:
            if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
                raise ValueError("margin reservation must be positive")
            if self._state.cash - self._state.margin < amount:
                raise ValueError("insufficient available cash for margin")
            self._state = AccountState(
                self._state.cash,
                self._state.margin + amount,
                self._state.realized_pnl,
                self._state.fees,
                self._state.lots,
            )
            return self._state

    def release_margin(self, amount: Decimal) -> AccountState:
        with self._lock:
            if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0 or amount > self._state.margin:
                raise ValueError("margin release exceeds frozen margin")
            self._state = AccountState(
                self._state.cash,
                self._state.margin - amount,
                self._state.realized_pnl,
                self._state.fees,
                self._state.lots,
            )
            return self._state

    def mark_to_market(
        self, settlement_id: EntityId, trading_date: str, settlement_price: Decimal, now: RecordedAt
    ) -> Settlement:
        if not isinstance(settlement_price, Decimal) or not settlement_price.is_finite() or settlement_price <= 0:
            raise ValueError("settlement price must be positive")
        if not isinstance(settlement_id, EntityId) or settlement_id.namespace != "settlement":
            raise ValueError("mark-to-market requires a settlement id")
        if not isinstance(now, RecordedAt):
            raise TypeError("mark-to-market requires a RecordedAt")
        with self._lock:
            pnl = Decimal("0")
            for lot in self._state.lots:
                sign = Decimal("1") if lot.direction is TradeDirection.LONG else Decimal("-1")
                pnl += (settlement_price - lot.average_price) * lot.quantity * sign * self._multiplier
            return Settlement(
                settlement_id,
                self._account_id or EntityId.deterministic("simulation_account", "anonymous"),
                trading_date,
                pnl,
                pnl,
                Decimal("0"),
                now,
                settlement_price=settlement_price,
            )

    def apply_fill(self, fill: Fill, *, lot_id, account_id) -> AccountState:
        with self._lock:
            if not isinstance(fill, Fill):
                raise TypeError("account projection requires a Fill")
            if fill.fill_id in self._applied_fills:
                return self._state
            if not isinstance(account_id, EntityId) or account_id.namespace != "simulation_account":
                raise ValueError("fill account must be a simulation_account id")
            if self._account_id is not None and account_id != self._account_id:
                raise ValueError("fill account mismatch")
            if not isinstance(lot_id, EntityId) or lot_id.namespace != "position_lot":
                raise ValueError("fill lot must be a position_lot id")
            if any(lot.lot_id == lot_id for lot in self._state.lots):
                raise ValueError("lot id already exists")
            cash = self._state.cash - fill.fee
            lot = PositionLot(
                lot_id,
                account_id,
                fill.instrument,
                fill.direction,
                fill.quantity,
                fill.price,
                fill.filled_at,
                source_fill_id=fill.fill_id,
            )
            self._state = AccountState(
                cash,
                self._state.margin,
                self._state.realized_pnl,
                self._state.fees + fill.fee,
                self._state.lots + (lot,),
            )
            self._applied_fills.add(fill.fill_id)
            return self._state

    def settle(self, settlement: Settlement) -> AccountState:
        with self._lock:
            if not isinstance(settlement, Settlement):
                raise TypeError("account projection requires a Settlement")
            if settlement.settlement_id in self._applied_settlements:
                return self._state
            if settlement.trading_date in self._settlement_dates:
                raise ValueError("duplicate settlement trading date")
            if self._account_id is not None and settlement.account_id != self._account_id:
                raise ValueError("settlement account mismatch")
            lots = self._state.lots
            # An end-of-day mark becomes the next day's cost basis.  This is
            # what makes successive daily settlements incremental rather than
            # repeatedly re-realising the entire position from the opening fill.
            if settlement.settlement_price is not None:
                lots = tuple(
                    replace(lot, average_price=settlement.settlement_price, version=lot.version + 1) for lot in lots
                )
            self._state = AccountState(
                self._state.cash + settlement.cash_delta,
                self._state.margin,
                self._state.realized_pnl + settlement.realized_pnl,
                self._state.fees + settlement.fees,
                lots,
            )
            # ``cash_delta`` is the net amount applied to cash.  Keep the
            # non-PnL component plus settlement fees explicit so the
            # conservation equation also holds when a settlement charges a
            # fee (fees are included in ``state.fees`` below).
            self._settlement_cash_adjustment += settlement.cash_delta - settlement.realized_pnl + settlement.fees
            self._applied_settlements.add(settlement.settlement_id)
            self._settlement_dates.add(settlement.trading_date)
            return self._state

    def close(self, fill: Fill, *, close_today: bool = False) -> AccountState:
        """Apply a reducing fill against the oldest compatible lot."""
        with self._lock:
            return self._close_locked(fill, close_today=close_today)

    def _close_locked(self, fill: Fill, *, close_today: bool = False) -> AccountState:
        if fill.fill_id in self._applied_fills:
            return self._state
        if self._account_id is not None and fill.order_id.namespace != "order":
            raise ValueError("close fill requires an order id")
        candidates = [
            lot
            for lot in self._state.lots
            if lot.instrument == fill.instrument
            and lot.direction is not fill.direction
            and (not close_today or lot.opened_at.value.date() == fill.filled_at.value.date())
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
                        source_fill_id=lot.source_fill_id,
                        version=lot.version + 1,
                    )
                )
        self._state = AccountState(
            self._state.cash + realized - fill.fee,
            self._state.margin,
            self._state.realized_pnl + realized,
            self._state.fees + fill.fee,
            tuple(lots),
        )
        self._applied_fills.add(fill.fill_id)
        return self._state

    @property
    def initial_cash(self) -> Decimal:
        return self._initial_cash

    @property
    def contract_multiplier(self) -> Decimal:
        return self._multiplier

    def conservation_residual(self) -> Decimal:
        """Return cash minus the deterministic cash-flow projection."""
        with self._lock:
            expected = (
                self._initial_cash + self._state.realized_pnl + self._settlement_cash_adjustment - self._state.fees
            )
            return self._state.cash - expected

    def assert_conservation(self) -> None:
        """Fail closed if cash, realized PnL, fees and settlements diverge."""
        residual = self.conservation_residual()
        if residual != 0:
            raise ValueError(f"account cash conservation violated: residual={residual}")

    def snapshot(self) -> SimulationAccountSnapshot:
        with self._lock:
            self.assert_conservation()
            return SimulationAccountSnapshot(
                self._initial_cash,
                self._multiplier,
                self._account_id,
                self._state,
                tuple(sorted(self._applied_fills, key=str)),
                tuple(sorted(self._applied_settlements, key=str)),
                tuple(sorted(self._settlement_dates)),
                self._settlement_cash_adjustment,
            )

    @classmethod
    def restore(cls, snapshot: SimulationAccountSnapshot) -> SimulationAccount:
        if not isinstance(snapshot, SimulationAccountSnapshot):
            raise TypeError("snapshot must be a SimulationAccountSnapshot")
        account = cls(snapshot.initial_cash, snapshot.contract_multiplier, snapshot.account_id)
        with account._lock:
            if not isinstance(snapshot.state, AccountState):
                raise TypeError("snapshot state must be AccountState")
            if (
                not isinstance(snapshot.settlement_cash_adjustment, Decimal)
                or not snapshot.settlement_cash_adjustment.is_finite()
            ):
                raise ValueError("snapshot settlement adjustment must be finite")
            if len(set(snapshot.applied_fills)) != len(snapshot.applied_fills) or any(
                not isinstance(identifier, EntityId) or identifier.namespace != "fill"
                for identifier in snapshot.applied_fills
            ):
                raise ValueError("snapshot contains invalid or duplicate fill identities")
            if len(set(snapshot.applied_settlements)) != len(snapshot.applied_settlements) or any(
                not isinstance(identifier, EntityId) or identifier.namespace != "settlement"
                for identifier in snapshot.applied_settlements
            ):
                raise ValueError("snapshot contains invalid or duplicate settlement identities")
            if len(set(snapshot.settlement_dates)) != len(snapshot.settlement_dates) or any(
                not isinstance(value, str) or not value for value in snapshot.settlement_dates
            ):
                raise ValueError("snapshot contains invalid or duplicate settlement dates")
            lot_ids = [lot.lot_id for lot in snapshot.state.lots]
            if len(set(lot_ids)) != len(lot_ids) or any(
                not isinstance(lot, PositionLot)
                or (snapshot.account_id is not None and lot.account_id != snapshot.account_id)
                for lot in snapshot.state.lots
            ):
                raise ValueError("snapshot contains invalid or duplicate lots")
            account._state = snapshot.state
            account._applied_fills = set(snapshot.applied_fills)
            account._applied_settlements = set(snapshot.applied_settlements)
            account._settlement_dates = set(snapshot.settlement_dates)
            account._settlement_cash_adjustment = snapshot.settlement_cash_adjustment
            account.assert_conservation()
        return account
