"""V3 durable autonomy checkpoint primitives."""

from dataclasses import dataclass
from enum import StrEnum


class Checkpoint(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    SCAN = "SCAN"
    DELEGATE = "DELEGATE"
    PLAN = "PLAN"
    PREFLIGHT = "PREFLIGHT"
    FINAL = "FINAL"
    EXECUTE = "EXECUTE"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class DurableState:
    run_id: str
    checkpoint: Checkpoint
    plan_hash: str
    snapshot_hash: str
    basis_hash: str | None = None
    receipt_hash: str | None = None
    risk_hash: str | None = None


class DurableOrchestrator:
    def __init__(self) -> None:
        self._store: dict[str, DurableState] = {}

    def save(self, state: DurableState) -> DurableState:
        if not state.run_id or not state.plan_hash or not state.snapshot_hash:
            raise ValueError("invalid checkpoint")
        self._store[state.run_id] = state
        return state

    def recover(
        self,
        run_id: str,
        *,
        plan_hash: str,
        snapshot_hash: str,
        basis_hash: str | None = None,
        receipt_hash: str | None = None,
        risk_hash: str | None = None,
    ) -> DurableState:
        state = self._store[run_id]
        if (state.plan_hash, state.snapshot_hash, state.basis_hash, state.receipt_hash, state.risk_hash) != (
            plan_hash,
            snapshot_hash,
            basis_hash,
            receipt_hash,
            risk_hash,
        ):
            raise ValueError("stale checkpoint inputs")
        return state


_ORDER = list(Checkpoint)


def advance(state: DurableState, target: Checkpoint) -> DurableState:
    if _ORDER.index(target) != _ORDER.index(state.checkpoint) + 1:
        raise ValueError("invalid checkpoint transition")
    return DurableState(
        state.run_id,
        target,
        state.plan_hash,
        state.snapshot_hash,
        state.basis_hash,
        state.receipt_hash,
        state.risk_hash,
    )

    def start(self, run_id: str, plan_hash: str, snapshot_hash: str) -> DurableState:
        return self.save(DurableState(run_id, Checkpoint.SNAPSHOT, plan_hash, snapshot_hash))

    def advance(self, run_id: str, target: Checkpoint) -> DurableState:
        current = self._store[run_id]
        return self.save(advance(current, target))


def _start(self, run_id: str, plan_hash: str, snapshot_hash: str) -> DurableState:
    return self.save(DurableState(run_id, Checkpoint.SNAPSHOT, plan_hash, snapshot_hash))


def _advance(self, run_id: str, target: Checkpoint) -> DurableState:
    return self.save(advance(self._store[run_id], target))


DurableOrchestrator.start = _start  # type: ignore[attr-defined]
DurableOrchestrator.advance = _advance  # type: ignore[attr-defined]


def _interrupt(self, run_id: str) -> DurableState:
    s = self._store[run_id]
    return self.save(s)


DurableOrchestrator.interrupt = _interrupt  # type: ignore[attr-defined]


def _trigger(self, run_id: str, plan_hash: str, snapshot_hash: str) -> DurableState:
    if run_id in self._store:
        return self._store[run_id]
    return self.start(run_id, plan_hash, snapshot_hash)


DurableOrchestrator.trigger = _trigger  # type: ignore[attr-defined]
