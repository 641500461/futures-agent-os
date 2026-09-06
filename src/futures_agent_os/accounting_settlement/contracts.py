"""Accounting & Settlement-owned V2 contract surface."""

from dataclasses import dataclass

from futures_agent_os.decision.trade_contracts import (
    LedgerEntry as _DecisionLedgerEntry,
    PositionLot as _DecisionPositionLot,
    Settlement as _DecisionSettlement,
)


@dataclass(frozen=True, slots=True)
class PositionLot(_DecisionPositionLot):
    """Accounting & Settlement canonical owner type for position lots."""

    pass


@dataclass(frozen=True, slots=True)
class LedgerEntry(_DecisionLedgerEntry):
    """Accounting & Settlement canonical owner type for ledger entries."""

    pass


@dataclass(frozen=True, slots=True)
class Settlement(_DecisionSettlement):
    """Accounting & Settlement canonical owner type for settlements."""

    pass


__all__ = ["PositionLot", "LedgerEntry", "Settlement"]
