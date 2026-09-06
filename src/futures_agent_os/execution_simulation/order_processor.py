"""Idempotent deterministic application of order lifecycle commands.

The processor is deliberately a single logical writer.  Callers may provide
an exchange/event sequence; the sequence is consumed exactly once and gaps
are rejected.  That gives cancel/fill races a deterministic outcome after a
restart: whichever event has the lower sequence is applied first and a later
event observes the resulting terminal/partial order state.
"""

import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any, TypeAlias, cast

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256

_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.ACCEPTED, OrderStatus.REJECTED}),
    OrderStatus.ACCEPTED: frozenset({OrderStatus.WORKING, OrderStatus.EXPIRED}),
    OrderStatus.WORKING: frozenset(
        {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class OrderCommandResult:
    command_id: str
    accepted: bool
    order: Order | None
    reason: str | None = None
    event_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class OrderProcessorSnapshot:
    """Durable-ready state for crash recovery.

    The snapshot carries command outcomes as well as orders.  Restoring only
    orders would permit a retried command to create a second business effect.
    """

    orders: tuple[Order, ...]
    commands: tuple[OrderCommandResult, ...]
    command_fingerprints: tuple[tuple[str, str, str], ...]
    last_event_sequence: int = 0


_CommandFingerprint: TypeAlias = tuple[str, str, str]


def _tupleize(value: object) -> object:
    """Convert JSON arrays to immutable tuples for the shared hash contract."""
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    if isinstance(value, dict):
        return {key: _tupleize(item) for key, item in value.items()}
    return value


class OrderCommandProcessor:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._commands: dict[str, OrderCommandResult] = {}
        self._command_fingerprints: dict[str, _CommandFingerprint] = {}
        self._last_event_sequence = 0
        self._lock = RLock()

    def register(self, order: Order) -> None:
        with self._lock:
            key = str(order.order_id)
            if key in self._orders:
                raise ValueError("order already registered")
            self._orders[key] = order

    @staticmethod
    def _validate_command_id(command_id: str) -> None:
        if (
            not isinstance(command_id, str)
            or not command_id
            or command_id != command_id.strip()
            or any(character.isspace() for character in command_id)
        ):
            raise ValueError("command_id must be canonical text")

    @staticmethod
    def _validate_event_sequence(event_sequence: int | None) -> None:
        if event_sequence is not None and (
            isinstance(event_sequence, bool) or not isinstance(event_sequence, int) or event_sequence < 1
        ):
            raise ValueError("event_sequence must be a positive integer")

    def _begin_command(
        self,
        command_id: str,
        fingerprint: _CommandFingerprint,
        event_sequence: int | None,
    ) -> OrderCommandResult | None:
        """Return an idempotent result or reserve the next sequence.

        ``None`` means this is a new command and the caller can apply it.  A
        conflicting reuse of a command id is rejected without mutating state.
        """
        self._validate_command_id(command_id)
        self._validate_event_sequence(event_sequence)
        existing = self._commands.get(command_id)
        if existing is not None:
            # A command id names one immutable command.  Replays with the
            # same payload return the original outcome; reusing it for a
            # different order/target/quantity fails closed when the caller is
            # using the explicit event-stream API.  Legacy calls without an
            # event sequence retain historical command-id idempotency.
            if self._command_fingerprints.get(command_id) == fingerprint:
                return existing
            if event_sequence is None:
                return existing
            return OrderCommandResult(command_id, False, existing.order, "COMMAND_ID_CONFLICT", existing.event_sequence)
        expected = self._last_event_sequence + 1
        if event_sequence is not None and event_sequence != expected:
            result = OrderCommandResult(command_id, False, None, "EVENT_SEQUENCE_GAP", event_sequence)
            # A rejected gap does not consume a stream sequence or command
            # identity.  The caller can retry the same command after applying
            # the missing event; recording it here would make that impossible.
            return result
        sequence = expected if event_sequence is None else event_sequence
        self._last_event_sequence = sequence
        self._command_fingerprints[command_id] = fingerprint
        return None

    def transition(
        self, command_id: str, order_id: str, target: OrderStatus, *, event_sequence: int | None = None
    ) -> OrderCommandResult:
        with self._lock:
            if not isinstance(target, OrderStatus):
                raise TypeError("target must be an OrderStatus")
            fingerprint: _CommandFingerprint = ("TRANSITION", order_id, target.value)
            prior = self._begin_command(command_id, fingerprint, event_sequence)
            if prior is not None:
                return prior
            current = self._orders.get(order_id)
            if current is None:
                result = OrderCommandResult(command_id, False, None, "UNKNOWN_ORDER", self._last_event_sequence)
            elif target not in _TRANSITIONS[current.status]:
                result = OrderCommandResult(command_id, False, current, "INVALID_TRANSITION", self._last_event_sequence)
            else:
                updated = current.transition(target)
                self._orders[order_id] = updated
                result = OrderCommandResult(command_id, True, updated, event_sequence=self._last_event_sequence)
            self._commands[command_id] = result
            return result

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def apply_fill(
        self, command_id: str, order_id: str, quantity: object, *, event_sequence: int | None = None
    ) -> OrderCommandResult:
        """Apply one fill command; duplicate command IDs are business-idempotent."""
        with self._lock:
            fingerprint: _CommandFingerprint = ("FILL", order_id, repr(quantity))
            prior = self._begin_command(command_id, fingerprint, event_sequence)
            if prior is not None:
                return prior
            current = self._orders.get(order_id)
            if current is None:
                result = OrderCommandResult(command_id, False, None, "UNKNOWN_ORDER", self._last_event_sequence)
            else:
                try:
                    updated = current.apply_fill(quantity)  # type: ignore[arg-type]
                except (TypeError, ValueError) as exc:
                    result = OrderCommandResult(command_id, False, current, str(exc), self._last_event_sequence)
                else:
                    self._orders[order_id] = updated
                    result = OrderCommandResult(command_id, True, updated, event_sequence=self._last_event_sequence)
            self._commands[command_id] = result
            return result

    @property
    def last_event_sequence(self) -> int:
        with self._lock:
            return self._last_event_sequence

    def snapshot(self) -> OrderProcessorSnapshot:
        with self._lock:
            return OrderProcessorSnapshot(
                tuple(self._orders.values()),
                tuple(self._commands.values()),
                tuple(
                    (key, value[0], value[1] + "\x00" + value[2]) for key, value in self._command_fingerprints.items()
                ),
                self._last_event_sequence,
            )

    @classmethod
    def restore(cls, snapshot: OrderProcessorSnapshot) -> OrderCommandProcessor:
        if not isinstance(snapshot, OrderProcessorSnapshot):
            raise TypeError("snapshot must be an OrderProcessorSnapshot")
        if (
            isinstance(snapshot.last_event_sequence, bool)
            or not isinstance(snapshot.last_event_sequence, int)
            or snapshot.last_event_sequence < 0
        ):
            raise ValueError("snapshot event sequence must be non-negative")
        processor = cls()
        with processor._lock:
            for order in snapshot.orders:
                if not isinstance(order, Order):
                    raise TypeError("snapshot orders must be Order values")
                key = str(order.order_id)
                if key in processor._orders:
                    raise ValueError("duplicate order in snapshot")
                processor._orders[key] = order
            if len({result.command_id for result in snapshot.commands}) != len(snapshot.commands):
                raise ValueError("duplicate command in snapshot")
            expected_sequences = [result.event_sequence for result in snapshot.commands]
            if any(sequence is None for sequence in expected_sequences):
                raise ValueError("snapshot command outcomes must carry event sequences")
            if len(set(expected_sequences)) != len(expected_sequences) or set(expected_sequences) != set(
                range(1, snapshot.last_event_sequence + 1)
            ):
                raise ValueError("snapshot sequence does not match command outcomes")
            for result in snapshot.commands:
                if not isinstance(result, OrderCommandResult):
                    raise TypeError("snapshot commands must be OrderCommandResult values")
                processor._commands[result.command_id] = result
            # Fingerprints are persisted as compact deterministic text.  They
            # are only used to detect command-id reuse after a restart.
            if len({key for key, _, _ in snapshot.command_fingerprints}) != len(snapshot.command_fingerprints):
                raise ValueError("duplicate command fingerprint")
            for key, kind, encoded in snapshot.command_fingerprints:
                if not all(isinstance(value, str) for value in (key, kind, encoded)):
                    raise TypeError("snapshot fingerprints must be text")
                if "\x00" not in encoded:
                    raise ValueError("snapshot fingerprint encoding is invalid")
                second, third = encoded.split("\x00", 1)
                processor._command_fingerprints[key] = (kind, second, third)
            if set(processor._commands) != set(processor._command_fingerprints):
                raise ValueError("snapshot command and fingerprint sets differ")
            processor._last_event_sequence = snapshot.last_event_sequence
        return processor


def _order_to_payload(order: Order) -> dict[str, object]:
    """Serialize an order without losing typed identity or version metadata."""
    return {
        "order_id": str(order.order_id),
        "execution_plan_id": str(order.execution_plan_id),
        "instrument": order.instrument,
        "direction": order.direction.value,
        "quantity": str(order.quantity),
        "status": order.status.value,
        "filled_quantity": str(order.filled_quantity),
        "limit_price": str(order.limit_price) if order.limit_price is not None else None,
        "stop_price": str(order.stop_price) if order.stop_price is not None else None,
        "created_at": order.created_at.to_dict()["recorded_at"],
        "version": order.version,
        "schema_version": str(order.schema_version),
        "source_ref": order.source_ref,
    }


def _order_from_payload(value: object) -> Order:
    if not isinstance(value, dict):
        raise ValueError("durable order must be an object")
    required = {
        "order_id",
        "execution_plan_id",
        "instrument",
        "direction",
        "quantity",
        "status",
        "filled_quantity",
        "limit_price",
        "stop_price",
        "created_at",
        "version",
        "schema_version",
        "source_ref",
    }
    if set(value) != required:
        raise ValueError("durable order fields are not exact")
    return Order(
        EntityId.parse(str(value["order_id"])),
        EntityId.parse(str(value["execution_plan_id"])),
        str(value["instrument"]),
        TradeDirection(str(value["direction"])),
        Decimal(str(value["quantity"])),
        OrderStatus(str(value["status"])),
        Decimal(str(value["filled_quantity"])),
        Decimal(str(value["limit_price"])) if value["limit_price"] is not None else None,
        Decimal(str(value["stop_price"])) if value["stop_price"] is not None else None,
        RecordedAt.parse(str(value["created_at"])),
        int(str(value["version"])),
        SchemaVersion.parse(str(value["schema_version"])),
        str(value["source_ref"]),
    )


def _command_result_to_payload(result: OrderCommandResult) -> dict[str, object]:
    return {
        "command_id": result.command_id,
        "accepted": result.accepted,
        "order": _order_to_payload(result.order) if result.order is not None else None,
        "reason": result.reason,
        "event_sequence": result.event_sequence,
    }


def _command_result_from_payload(value: object) -> OrderCommandResult:
    if not isinstance(value, dict):
        raise ValueError("durable command result must be an object")
    required = {"command_id", "accepted", "order", "reason", "event_sequence"}
    if set(value) != required:
        raise ValueError("durable command result fields are not exact")
    if not isinstance(value["accepted"], bool):
        raise ValueError("durable command accepted flag must be boolean")
    sequence = value["event_sequence"]
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)):
        raise ValueError("durable command event sequence must be an integer")
    return OrderCommandResult(
        str(value["command_id"]),
        value["accepted"],
        _order_from_payload(value["order"]) if value["order"] is not None else None,
        str(value["reason"]) if value["reason"] is not None else None,
        sequence,
    )


class DurableOrderCommandProcessor:
    """Atomic file-backed command inbox for process/database restart tests.

    Every public mutating operation persists the complete processor snapshot
    before returning.  The file contains a content digest, so a restart either
    restores the exact command outcomes or fails closed.  This is intentionally
    a local simulation adapter; PostgreSQL is the production durable owner.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._processor = OrderCommandProcessor()
        self._lock = RLock()
        if self.path.exists():
            self._load()

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

    @property
    def last_event_sequence(self) -> int:
        return self._processor.last_event_sequence

    def get(self, order_id: str) -> Order | None:
        with self._writer_lock(), self._lock:
            if self.path.exists():
                self._load()
            return self._processor.get(order_id)

    def snapshot(self) -> OrderProcessorSnapshot:
        with self._lock:
            return self._processor.snapshot()

    def register(self, order: Order) -> None:
        with self._writer_lock(), self._lock:
            if self.path.exists():
                self._load()
            existing = self._processor.get(str(order.order_id))
            if existing is None:
                self._processor.register(order)
            elif existing != order:
                raise ValueError("order already registered with different payload")
            self._persist()

    def transition(
        self, command_id: str, order_id: str, target: OrderStatus, *, event_sequence: int | None = None
    ) -> OrderCommandResult:
        with self._writer_lock(), self._lock:
            if self.path.exists():
                self._load()
            result = self._processor.transition(command_id, order_id, target, event_sequence=event_sequence)
            self._persist()
            return result

    def apply_fill(
        self, command_id: str, order_id: str, quantity: object, *, event_sequence: int | None = None
    ) -> OrderCommandResult:
        with self._writer_lock(), self._lock:
            if self.path.exists():
                self._load()
            result = self._processor.apply_fill(command_id, order_id, quantity, event_sequence=event_sequence)
            self._persist()
            return result

    @classmethod
    def restore(cls, path: str | os.PathLike[str]) -> DurableOrderCommandProcessor:
        return cls(path)

    def _payload(self) -> dict[str, object]:
        snapshot = self._processor.snapshot()
        return {
            "orders": [_order_to_payload(order) for order in snapshot.orders],
            "commands": [_command_result_to_payload(result) for result in snapshot.commands],
            "command_fingerprints": [list(item) for item in snapshot.command_fingerprints],
            "last_event_sequence": snapshot.last_event_sequence,
        }

    def _persist(self) -> None:
        payload = self._payload()
        envelope = {
            "schema": "v2.order-command.1",
            "payload": payload,
            "digest": canonical_sha256(cast(Any, _tupleize(payload))),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> None:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or set(envelope) != {"schema", "payload", "digest"}:
                raise ValueError("durable order state envelope is invalid")
            if envelope["schema"] != "v2.order-command.1" or not isinstance(envelope["payload"], dict):
                raise ValueError("durable order state schema is invalid")
            payload = envelope["payload"]
            digest = envelope["digest"]
            if not isinstance(digest, str) or digest != canonical_sha256(cast(Any, _tupleize(payload))):
                raise ValueError("durable order state digest mismatch")
            required = {"orders", "commands", "command_fingerprints", "last_event_sequence"}
            if (
                set(payload) != required
                or not isinstance(payload["orders"], list)
                or not isinstance(payload["commands"], list)
            ):
                raise ValueError("durable order state payload is invalid")
            fingerprints = payload["command_fingerprints"]
            if not isinstance(fingerprints, list):
                raise ValueError("durable command fingerprints must be a list")
            parsed_fingerprints: list[_CommandFingerprint] = []
            for item in fingerprints:
                if not isinstance(item, list) or len(item) != 3 or not all(isinstance(part, str) for part in item):
                    raise ValueError("durable command fingerprint must contain three text fields")
                parsed_fingerprints.append((item[0], item[1], item[2]))
            snapshot = OrderProcessorSnapshot(
                tuple(_order_from_payload(value) for value in payload["orders"]),
                tuple(_command_result_from_payload(value) for value in payload["commands"]),
                tuple(parsed_fingerprints),
                int(str(payload["last_event_sequence"])),
            )
            self._processor = OrderCommandProcessor.restore(snapshot)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("cannot load durable order command state") from error


__all__ = [
    "OrderCommandResult",
    "OrderProcessorSnapshot",
    "OrderCommandProcessor",
    "DurableOrderCommandProcessor",
]
