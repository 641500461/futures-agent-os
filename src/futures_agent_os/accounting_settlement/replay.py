"""Append-only accounting event log and deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass

from futures_agent_os.decision import Fill, Settlement
from futures_agent_os.shared_kernel import EntityId
from .ledger import SimulationAccount


@dataclass(frozen=True, slots=True)
class AccountingEvent:
    sequence: int
    event_id: EntityId
    payload: Fill | Settlement


class AccountingEventLog:
    def __init__(self) -> None:
        self._events: list[AccountingEvent] = []

    def append(self, event: AccountingEvent) -> None:
        if not isinstance(event, AccountingEvent) or event.sequence != len(self._events) + 1:
            raise ValueError("accounting events must be appended in strict sequence")
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError("duplicate accounting event")
        self._events.append(event)

    @property
    def events(self) -> tuple[AccountingEvent, ...]:
        return tuple(self._events)

    def replay(self, account: SimulationAccount, *, account_id: EntityId) -> None:
        for event in self._events:
            if isinstance(event.payload, Fill):
                account.apply_fill(event.payload, lot_id=EntityId.new("position_lot"), account_id=account_id)
            else:
                account.settle(event.payload)
