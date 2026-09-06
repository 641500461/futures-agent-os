"""Durable append-only audit facts and deterministic accounting projection.

The V2 reference implementation deliberately uses a small JSON-lines-like
snapshot instead of hiding persistence behind the accounting aggregate.  A
write is committed by writing a complete immutable chain to a temporary file
and atomically replacing the state file.  Existing events are never edited;
corrections are new events that point at the event they supersede.
"""

from __future__ import annotations

import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, cast

from futures_agent_os.decision import Fill, Settlement, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256


_GENESIS = "0" * 64


def _canonical_hash(value: object) -> str:
    return canonical_sha256(cast(Any, value))


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, EntityId):
        return str(value)
    if isinstance(value, RecordedAt):
        return value.to_dict()["recorded_at"]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("audit payload keys must be strings")
        return {key: _freeze(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"unsupported audit payload value: {type(value).__name__}")


def _fact_payload(fact: object) -> tuple[str, dict[str, object]]:
    if isinstance(fact, Fill):
        return "FILL", {
            "fill_id": str(fact.fill_id),
            "order_id": str(fact.order_id),
            "instrument": fact.instrument,
            "direction": fact.direction.value,
            "quantity": str(fact.quantity),
            "price": str(fact.price),
            "fee": str(fact.fee),
            "filled_at": fact.filled_at.to_dict()["recorded_at"],
            "version": fact.version,
            "schema_version": str(fact.schema_version),
            "source_ref": fact.source_ref,
        }
    if isinstance(fact, Settlement):
        return "SETTLEMENT", {
            "settlement_id": str(fact.settlement_id),
            "account_id": str(fact.account_id),
            "trading_date": fact.trading_date,
            "cash_delta": str(fact.cash_delta),
            "realized_pnl": str(fact.realized_pnl),
            "fees": str(fact.fees),
            "recorded_at": fact.recorded_at.to_dict()["recorded_at"],
            "source_ref": fact.source_ref,
            "version": fact.version,
            "schema_version": str(fact.schema_version),
            "settlement_price": str(fact.settlement_price) if fact.settlement_price is not None else None,
        }
    if not isinstance(fact, Mapping):
        raise TypeError("audit payload must be a Fill, Settlement, or JSON mapping")
    frozen = _freeze(fact)
    assert isinstance(frozen, dict)
    return "GENERIC", frozen


@dataclass(frozen=True, slots=True)
class DurableAuditEvent:
    sequence: int
    event_id: EntityId
    event_type: str
    aggregate_id: EntityId
    payload: Mapping[str, object]
    recorded_at: RecordedAt
    source_ref: str
    previous_hash: str
    event_hash: str
    correction_of: EntityId | None = None

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("audit sequence must be positive")
        for identifier, label in ((self.event_id, "event_id"), (self.aggregate_id, "aggregate_id")):
            if not isinstance(identifier, EntityId):
                raise TypeError(f"{label} must be typed")
        if self.event_id.namespace != "audit_event":
            raise ValueError("event_id must belong to audit_event namespace")
        if (
            not isinstance(self.event_type, str)
            or not self.event_type.strip()
            or any(c.isspace() for c in self.event_type)
        ):
            raise ValueError("event_type must be canonical text")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("recorded_at must be typed")
        if (
            not isinstance(self.source_ref, str)
            or not self.source_ref.strip()
            or any(c.isspace() for c in self.source_ref)
        ):
            raise ValueError("source_ref must be canonical text")
        _digest(self.previous_hash, "previous_hash")
        _digest(self.event_hash, "event_hash")
        object.__setattr__(self, "payload", _freeze(self.payload))
        if self.correction_of is not None and not isinstance(self.correction_of, EntityId):
            raise TypeError("correction_of must be typed when supplied")

    def hash_payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "aggregate_id": str(self.aggregate_id),
            "payload": self.payload,
            "recorded_at": self.recorded_at.to_dict()["recorded_at"],
            "source_ref": self.source_ref,
            "previous_hash": self.previous_hash,
            "correction_of": str(self.correction_of) if self.correction_of else None,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.hash_payload(), "event_hash": self.event_hash}


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    valid_chain: bool
    event_count: int
    correction_count: int
    replay_cash: Decimal | None
    projection_cash: Decimal | None
    balanced: bool
    reason: str = ""


class DurableAuditLog:
    """Atomic file-backed audit chain with replay and reconciliation helpers."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._events: list[DurableAuditEvent] = []
        self._suspend_persist = False
        if self.path.exists():
            self._load()

    @property
    def events(self) -> tuple[DurableAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def head_hash(self) -> str:
        with self._lock:
            return self._events[-1].event_hash if self._events else _GENESIS

    @contextmanager
    def _writer_lock(self):
        lock_path = self.path.expanduser().resolve().with_name(f".{self.path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        event_type: str,
        aggregate_id: EntityId,
        payload: object,
        recorded_at: RecordedAt,
        *,
        source_ref: str = "source:v2",
        event_id: EntityId | None = None,
        correction_of: EntityId | None = None,
    ) -> DurableAuditEvent:
        """Append one event under a process-wide file lock."""
        with self._writer_lock():
            if self.path.exists() and not self._suspend_persist:
                self._load()
            return self._append_unlocked(
                event_type,
                aggregate_id,
                payload,
                recorded_at,
                source_ref=source_ref,
                event_id=event_id,
                correction_of=correction_of,
            )

    def _append_unlocked(
        self,
        event_type: str,
        aggregate_id: EntityId,
        payload: object,
        recorded_at: RecordedAt,
        *,
        source_ref: str = "source:v2",
        event_id: EntityId | None = None,
        correction_of: EntityId | None = None,
    ) -> DurableAuditEvent:
        if not isinstance(aggregate_id, EntityId) or not isinstance(recorded_at, RecordedAt):
            raise TypeError("audit append requires typed aggregate and timestamp")
        kind, fact = _fact_payload(payload)
        event_type = event_type or kind
        frozen = _freeze(fact)
        assert isinstance(frozen, dict)
        with self._lock:
            sequence = len(self._events) + 1
            previous = self.head_hash
            if event_id is None:
                event_id = EntityId.deterministic(
                    "audit_event",
                    canonical_sha256(
                        {"sequence": sequence, "kind": event_type, "payload": frozen, "previous": previous}
                    ),
                )
            if event_id in {item.event_id for item in self._events}:
                raise ValueError("audit event ids must be unique")
            if correction_of is not None and correction_of not in {item.event_id for item in self._events}:
                raise ValueError("correction_of must reference an existing event")
            provisional = DurableAuditEvent(
                sequence,
                event_id,
                event_type,
                aggregate_id,
                frozen,
                recorded_at,
                source_ref,
                previous,
                _GENESIS,
                correction_of,
            )
            digest = _canonical_hash(provisional.hash_payload())
            event = DurableAuditEvent(
                sequence,
                event_id,
                event_type,
                aggregate_id,
                frozen,
                recorded_at,
                source_ref,
                previous,
                digest,
                correction_of,
            )
            self._events.append(event)
            if not self._suspend_persist:
                self._persist()
            return event

    def append_trade_episode(
        self,
        *,
        correlation_id: EntityId,
        recorded_at: RecordedAt,
        authorization: Mapping[str, object],
        risk: Mapping[str, object],
        execution: Mapping[str, object],
        protection: Mapping[str, object],
        fills: tuple[Fill, ...],
        settlement: Settlement,
        source_ref: str = "source:v2:episode",
        close_fill: bool = False,
    ) -> tuple[DurableAuditEvent, ...]:
        """Append one linked authorization→settlement episode atomically.

        Generic decision facts and typed accounting facts share one hash-chain
        sequence and correlation id.  If any fact is invalid, no partial
        episode is persisted because the file replacement occurs only after
        all events have been constructed.
        """
        if not isinstance(correlation_id, EntityId) or not isinstance(recorded_at, RecordedAt):
            raise TypeError("episode requires typed correlation and timestamp")
        if not isinstance(settlement, Settlement) or any(not isinstance(fill, Fill) for fill in fills):
            raise TypeError("episode requires typed fills and settlement")
        facts: list[tuple[str, EntityId, object]] = [
            ("AUTHORIZATION", correlation_id, {"correlation_id": str(correlation_id), **dict(authorization)}),
            ("RISK_DECISION", correlation_id, {"correlation_id": str(correlation_id), **dict(risk)}),
            ("EXECUTION_PLAN", correlation_id, {"correlation_id": str(correlation_id), **dict(execution)}),
            ("PROTECTION", correlation_id, {"correlation_id": str(correlation_id), **dict(protection)}),
        ]
        # Use the account as aggregate for accounting facts so a multi-account
        # audit file can be projected without leaking another account's fills.
        # Production shadow episodes mark later fills as explicit reductions;
        # generic callers retain the historical all-FILL behavior by default.
        facts.extend(
            (("FILL" if index == 0 or not close_fill else "CLOSE_FILL"), settlement.account_id, fill)
            for index, fill in enumerate(fills)
        )
        facts.append(("SETTLEMENT", settlement.account_id, settlement))
        with self._writer_lock(), self._lock:
            if self.path.exists():
                self._load()
            existing = [event for event in self._events if event.source_ref.endswith(f":{correlation_id}")]
            if {event.event_type for event in existing} >= {
                "AUTHORIZATION",
                "RISK_DECISION",
                "EXECUTION_PLAN",
                "PROTECTION",
                "FILL",
                "SETTLEMENT",
            }:
                return tuple(existing)
            original = list(self._events)
            try:
                episode_source = f"{source_ref}:{correlation_id}"
                self._suspend_persist = True
                created = [
                    self._append_unlocked(kind, aggregate, payload, recorded_at, source_ref=episode_source)
                    for kind, aggregate, payload in facts
                ]
                self._suspend_persist = False
                self._persist()
            except Exception:
                self._suspend_persist = False
                self._events = original
                self._persist()
                raise
            return tuple(created)

    def append_manual_shadow_episode(
        self,
        report: object,
        *,
        correlation_id: EntityId,
        recorded_at: RecordedAt | None = None,
        source_ref: str = "source:v2:manual-shadow",
    ) -> tuple[DurableAuditEvent, ...]:
        """Persist a completed :class:`ManualShadowReport` as one lifecycle.

        This is the production-shaped bridge between the simulation engine and
        the durable audit log.  Callers hand over the immutable report emitted
        by ``run_manual_shadow_episode``; authorization, risk, execution and
        protection facts are derived from the report's typed order/fill/action
        objects rather than supplied as ad-hoc database facts.  Incomplete
        (open or pending) reports are rejected because V2-010 requires a
        reconstructable authorization→settlement episode.
        """
        # Keep the accounting package independent from execution_simulation at
        # import time; duck typing also permits replaying equivalent reports.
        open_result = getattr(report, "open_result", None)
        open_fill = getattr(open_result, "fill", None)
        exit_fill = getattr(report, "exit_fill", None)
        settlement = getattr(report, "settlement", None)
        action = getattr(report, "protective_action", None)
        validation = getattr(report, "protection_validation", None)
        if open_fill is None or exit_fill is None or settlement is None:
            raise ValueError("manual shadow report must be a completed flat episode")
        if not isinstance(open_fill, Fill) or not isinstance(exit_fill, Fill) or not isinstance(settlement, Settlement):
            raise TypeError("manual shadow report contains invalid accounting facts")
        if recorded_at is None:
            recorded_at = settlement.recorded_at
        order = getattr(open_result, "order", None)
        if order is None:
            raise ValueError("manual shadow report is missing its execution order")

        def ident(value: object) -> str | None:
            return str(value) if isinstance(value, EntityId) else None

        authorization = {
            "authorization_id": str(EntityId.deterministic("authorization", str(correlation_id))),
            "plan_id": str(correlation_id),
            "execution_origin": "MANUAL_TEST",
        }
        risk = {
            "decision_id": str(EntityId.deterministic("risk_decision", str(correlation_id))),
            "plan_id": str(correlation_id),
            "account_id": str(settlement.account_id),
            "approved_quantity": str(open_fill.quantity),
        }
        execution = {
            "execution_plan_id": ident(getattr(order, "execution_plan_id", None)),
            "order_id": ident(getattr(order, "order_id", None)),
            "instrument": getattr(order, "instrument", open_fill.instrument),
            "direction": getattr(getattr(order, "direction", None), "value", open_fill.direction.value),
            "quantity": str(getattr(order, "quantity", open_fill.quantity)),
        }
        protection = {
            "action_id": ident(getattr(action, "action_id", None)),
            "request_id": ident(getattr(action, "request_id", None)),
            "validation_id": ident(getattr(validation, "validation_id", None))
            or ident(getattr(action, "validation_id", None)),
            "position_id": ident(getattr(action, "position_id", None)),
            "status": getattr(report, "status", "SHADOW_COMPLETED"),
        }
        return self.append_trade_episode(
            correlation_id=correlation_id,
            recorded_at=recorded_at,
            authorization=authorization,
            risk=risk,
            execution=execution,
            protection=protection,
            fills=(open_fill, exit_fill),
            settlement=settlement,
            source_ref=source_ref,
            close_fill=True,
        )

    def replay_trade_episode(self, account: object, *, account_id: EntityId, correlation_id: EntityId) -> None:
        """Replay a linked episode and reject missing lifecycle stages."""
        all_events = self.events
        episode_ids = {
            event.event_id
            for event in all_events
            if event.payload.get("correlation_id") == str(correlation_id)
            or event.source_ref.endswith(f":{correlation_id}")
        }
        # Corrections carry the target event identity rather than repeating
        # correlation metadata; include them when they amend this episode.
        events = [
            event
            for event in all_events
            if event.event_id in episode_ids
            or (event.event_type == "CORRECTION" and event.correction_of in episode_ids)
        ]
        event_types = {event.event_type for event in events}
        required = {"AUTHORIZATION", "RISK_DECISION", "EXECUTION_PLAN", "PROTECTION", "FILL", "SETTLEMENT"}
        if not required.issubset(event_types):
            raise ValueError("trade episode is missing a lifecycle stage")
        if any(event.event_type == "SETTLEMENT" and event.aggregate_id != account_id for event in events):
            raise ValueError("trade episode settlement account mismatch")
        # Replay only this correlation, not unrelated episodes in the same log.
        subset = object.__new__(DurableAuditLog)
        subset.path = self.path
        subset._lock = RLock()
        subset._events = events
        subset._suspend_persist = True
        subset.replay(account, account_id=account_id)

    def correction(
        self,
        target_event_id: EntityId,
        payload: Mapping[str, object],
        recorded_at: RecordedAt,
        *,
        actor_ref: str = "system:reconciliation",
    ) -> DurableAuditEvent:
        target = next((event for event in self.events if event.event_id == target_event_id), None)
        if target is None:
            raise ValueError("correction target does not exist")
        details = {
            "target_event_id": str(target_event_id),
            "target_event_hash": target.event_hash,
            "actor_ref": actor_ref,
            "replacement": dict(payload),
        }
        return self.append(
            "CORRECTION",
            target.aggregate_id,
            details,
            recorded_at,
            source_ref="source:v2:correction",
            correction_of=target_event_id,
        )

    def correct_fact(
        self,
        target_event_id: EntityId,
        replacement: Fill | Settlement,
        recorded_at: RecordedAt,
        *,
        actor_ref: str = "system:reconciliation",
    ) -> DurableAuditEvent:
        """Append a complete replacement fact without rewriting history.

        The replacement retains the original Fill/Settlement identity.  A
        replay applies the latest complete correction for a target while the
        original event and every correction remain in the hash chain.
        """
        target = next((event for event in self.events if event.event_id == target_event_id), None)
        if target is None or target.event_type not in {"FILL", "CLOSE_FILL", "CLOSE_TODAY_FILL", "SETTLEMENT"}:
            raise ValueError("fact correction target must be an accounting fact")
        kind, payload = _fact_payload(replacement)
        replacement_type = (
            target.event_type if target.event_type in {"CLOSE_FILL", "CLOSE_TODAY_FILL"} and kind == "FILL" else kind
        )
        if replacement_type != target.event_type:
            raise ValueError("fact correction cannot change accounting event type")
        identity_field = "settlement_id" if target.event_type == "SETTLEMENT" else "fill_id"
        if payload.get(identity_field) != target.payload.get(identity_field):
            raise ValueError("fact correction must retain the accounting identity")
        details = {
            "target_event_id": str(target_event_id),
            "target_event_hash": target.event_hash,
            "actor_ref": actor_ref,
            "replacement_event_type": replacement_type,
            "replacement": payload,
        }
        return self.append(
            "CORRECTION",
            target.aggregate_id,
            details,
            recorded_at,
            source_ref="source:v2:correction",
            correction_of=target_event_id,
        )

    def verify(self) -> bool:
        expected_previous = _GENESIS
        for sequence, event in enumerate(self.events, 1):
            if event.sequence != sequence or event.previous_hash != expected_previous:
                return False
            if event.event_hash != _canonical_hash(event.hash_payload()):
                return False
            expected_previous = event.event_hash
        return True

    def replay(self, account: object, *, account_id: EntityId) -> None:
        """Replay accounting facts in sequence; correction records are audit-only.

        ``CLOSE_FILL`` and ``CLOSE_TODAY_FILL`` are explicit event types rather
        than inferred opposite-side opens.  This preserves the domain
        distinction between a reducing fill and a new position when
        reconstructing a trade episode, including the exchange-specific
        same-day offset rule.
        """
        from .ledger import SimulationAccount

        if not isinstance(account, SimulationAccount):
            raise TypeError("replay requires a SimulationAccount")
        replacements: dict[EntityId, tuple[str, Mapping[str, object]]] = {}
        for event in self.events:
            if event.event_type != "CORRECTION" or event.correction_of is None:
                continue
            replacement_type = event.payload.get("replacement_event_type")
            replacement = event.payload.get("replacement")
            if isinstance(replacement_type, str) and isinstance(replacement, Mapping):
                replacements[event.correction_of] = (replacement_type, replacement)
        for event in self.events:
            if event.event_type == "CORRECTION":
                continue
            if event.event_type in {"FILL", "CLOSE_FILL", "CLOSE_TODAY_FILL", "SETTLEMENT"}:
                payload_account = event.payload.get("account_id")
                if event.aggregate_id != account_id and payload_account not in {None, str(account_id)}:
                    continue
                if event.aggregate_id != account_id and payload_account is None:
                    continue
            event_type, payload = replacements.get(event.event_id, (event.event_type, event.payload))
            if event_type in {"FILL", "CLOSE_FILL", "CLOSE_TODAY_FILL"}:
                fill = Fill(
                    EntityId.parse(str(payload["fill_id"])),
                    EntityId.parse(str(payload["order_id"])),
                    str(payload["instrument"]),
                    TradeDirection(str(payload["direction"])),
                    Decimal(str(payload["quantity"])),
                    Decimal(str(payload["price"])),
                    Decimal(str(payload["fee"])),
                    RecordedAt.parse(str(payload["filled_at"])),
                    int(str(payload.get("version", 1))),
                )
                if event_type in {"CLOSE_FILL", "CLOSE_TODAY_FILL"}:
                    account.close(fill, close_today=event_type == "CLOSE_TODAY_FILL")
                else:
                    account.apply_fill(
                        fill,
                        lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)),
                        account_id=account_id,
                    )
            elif event_type == "SETTLEMENT":
                settlement = Settlement(
                    EntityId.parse(str(payload["settlement_id"])),
                    EntityId.parse(str(payload["account_id"])),
                    str(payload["trading_date"]),
                    Decimal(str(payload["cash_delta"])),
                    Decimal(str(payload["realized_pnl"])),
                    Decimal(str(payload["fees"])),
                    RecordedAt.parse(str(payload["recorded_at"])),
                    str(payload.get("source_ref", "source:v2")),
                    int(str(payload.get("version", 1))),
                    settlement_price=Decimal(str(payload["settlement_price"]))
                    if payload.get("settlement_price") is not None
                    else None,
                )
                account.settle(settlement)

    def reconcile(self, account: object, *, account_id: EntityId) -> ReconciliationReport:
        from .ledger import SimulationAccount

        if not isinstance(account, SimulationAccount):
            raise TypeError("reconciliation requires a SimulationAccount")
        valid = self.verify()
        corrections = sum(event.event_type == "CORRECTION" for event in self.events)
        replayed = SimulationAccount(account.initial_cash, account.contract_multiplier, account_id)
        reason = ""
        if valid:
            try:
                self.replay(replayed, account_id=account_id)
            except (TypeError, ValueError, KeyError) as error:
                valid = False
                reason = str(error)
        balanced = valid and replayed.state == account.state
        if valid and not balanced:
            reason = "current projection differs from deterministic replay"
        return ReconciliationReport(
            valid,
            len(self.events),
            corrections,
            replayed.state.cash if valid else None,
            account.state.cash,
            balanced,
            reason,
        )

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_text(cast(Any, tuple(event.to_dict() for event in self._events)))
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> None:
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, list):
                raise ValueError("audit file must contain an array")
            events: list[DurableAuditEvent] = []
            for value in values:
                if not isinstance(value, dict):
                    raise ValueError("audit event must be an object")
                event = DurableAuditEvent(
                    int(value["sequence"]),
                    EntityId.parse(str(value["event_id"])),
                    str(value["event_type"]),
                    EntityId.parse(str(value["aggregate_id"])),
                    value["payload"],
                    RecordedAt.parse(str(value["recorded_at"])),
                    str(value["source_ref"]),
                    str(value["previous_hash"]),
                    str(value["event_hash"]),
                    EntityId.parse(str(value["correction_of"])) if value.get("correction_of") else None,
                )
                events.append(event)
            self._events = events
            if not self.verify():
                raise ValueError("audit file hash chain is invalid")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("cannot load durable audit log") from error


def append_simulation_episode(
    audit_log: DurableAuditLog,
    *,
    correlation_id: EntityId,
    recorded_at: RecordedAt,
    plan: object,
    submission: object,
    shadow_report: object,
    source_ref: str = "source:v2:simulation",
) -> tuple[DurableAuditEvent, ...]:
    """Persist a completed simulation result as a linked audit episode.

    This production-shaped adapter consumes the immutable outputs of the
    submit service and shadow runner; callers do not hand-author accounting
    facts.  Incomplete shadow runs are rejected before any append.
    """
    status = getattr(shadow_report, "status", None)
    if status != "SHADOW_COMPLETED":
        raise ValueError("only completed simulation episodes can be audited")
    opened = getattr(shadow_report, "open_result", None)
    open_fill = getattr(opened, "fill", None)
    exit_fill = getattr(shadow_report, "exit_fill", None)
    settlement = getattr(shadow_report, "settlement", None)
    if not isinstance(open_fill, Fill) or not isinstance(exit_fill, Fill) or not isinstance(settlement, Settlement):
        raise ValueError("completed simulation episode requires entry/exit fills and settlement")
    plan_id = getattr(plan, "plan_id", None)
    plan_hash = getattr(plan, "plan_hash", None)
    order = getattr(submission, "order", None)
    risk = getattr(submission, "risk", None)
    receipt = getattr(submission, "receipt", None)
    protection = getattr(submission, "protection", None)
    execution_plan = getattr(submission, "execution_plan", None)
    if not isinstance(plan_id, EntityId) or order is None or risk is None or receipt is None or protection is None:
        raise ValueError("submission output is missing durable lifecycle facts")
    origin = getattr(receipt, "execution_origin", None)
    origin = getattr(origin, "value", origin)
    if not isinstance(origin, str) or not origin:
        raise ValueError("submission receipt is missing execution origin")
    return audit_log.append_trade_episode(
        correlation_id=correlation_id,
        recorded_at=recorded_at,
        authorization={
            "plan_id": str(plan_id),
            "plan_hash": plan_hash,
            "authorization_receipt_id": str(getattr(receipt, "receipt_id", "")),
            "execution_origin": origin,
        },
        risk={
            "decision_id": str(getattr(risk, "decision_id", "")),
            "plan_id": str(plan_id),
            "outcome": str(getattr(getattr(risk, "outcome", None), "value", "")),
            "approved_quantity": str(getattr(risk, "approved_quantity", "")),
        },
        execution={
            "execution_plan_id": str(getattr(execution_plan, "execution_plan_id", "")),
            "order_id": str(getattr(order, "order_id", "")),
            "instrument": str(getattr(order, "instrument", "")),
            "quantity": str(getattr(order, "quantity", "")),
        },
        protection={
            "mandate_id": str(getattr(protection, "mandate_id", "")),
            "stop_price": str(getattr(protection, "stop_price", "")),
            "protective_action_id": str(getattr(getattr(shadow_report, "protective_action", None), "action_id", "")),
        },
        fills=(open_fill, exit_fill),
        settlement=settlement,
        source_ref=source_ref,
        close_fill=True,
    )


__all__ = ["DurableAuditEvent", "DurableAuditLog", "ReconciliationReport", "append_simulation_episode"]
