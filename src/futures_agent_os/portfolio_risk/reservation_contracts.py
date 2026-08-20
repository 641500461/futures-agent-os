"""Portfolio & Risk-owned atomic reservation reference contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from threading import RLock

from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def _scope_text(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _canonical_reference(value: str) -> bool:
    return _scope_text(value)


class ReservationStatus(StrEnum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    RECONCILED = "RECONCILED"


class ReservationSourceKind(StrEnum):
    MANDATE = "MANDATE"
    PLAN_APPROVAL = "PLAN_APPROVAL"


class ReservationAction(StrEnum):
    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class RiskBudgetReservation:
    """A risk amount that can never exceed the immutable Constitution ceiling."""

    reservation_id: EntityId
    account_id: EntityId
    plan_id: EntityId
    plan_version: int
    plan_hash: str
    instrument: str
    strategy: str
    session: str
    authorization_basis_id: EntityId
    authorization_basis_hash: str
    risk_constitution_ref: str
    risk_constitution_version: int
    risk_constitution_hash: str
    risk_constitution_ceiling: Decimal
    worst_case_loss: Decimal
    margin: Decimal
    expires_at: RecordedAt
    status: ReservationStatus = ReservationStatus.HELD
    version: int = 1
    state_version: int = 1
    risk_dimensions: tuple[tuple[str, str], ...] = ()
    quantity: Decimal = Decimal("0")
    action: ReservationAction = ReservationAction.OPEN
    source_kind: ReservationSourceKind = ReservationSourceKind.MANDATE
    source_ref: EntityId | None = None
    source_hash: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.plan_version, bool)
            or not isinstance(self.plan_version, int)
            or self.plan_version < 1
            or not _canonical_reference(self.risk_constitution_ref)
        ):
            raise ValueError("reservations require a version and canonical constitution reference")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
            or isinstance(self.risk_constitution_version, bool)
            or not isinstance(self.risk_constitution_version, int)
            or self.risk_constitution_version < 1
        ):
            raise ValueError("reservations require positive versions")
        if isinstance(self.state_version, bool) or not isinstance(self.state_version, int) or self.state_version < 1:
            raise ValueError("reservations require a positive state version")
        if not isinstance(self.status, ReservationStatus) or not all(
            isinstance(value, EntityId)
            for value in (self.reservation_id, self.account_id, self.plan_id, self.authorization_basis_id)
        ):
            raise TypeError("reservations require typed status and identifiers")
        if not all(_scope_text(value) for value in (self.instrument, self.strategy, self.session)):
            raise ValueError("reservations require an exact execution scope")
        for digest in (self.plan_hash, self.authorization_basis_hash, self.risk_constitution_hash):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("reservation hashes must be lowercase SHA-256")
        for amount in (self.risk_constitution_ceiling, self.worst_case_loss, self.margin):
            if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
                raise ValueError("reservation amounts must be finite non-negative Decimal values")
        if self.worst_case_loss > self.risk_constitution_ceiling:
            raise ValueError("a reservation cannot relax the Risk Constitution")
        if not isinstance(self.expires_at, RecordedAt):
            raise TypeError("reservations require an expiry")
        if not isinstance(self.risk_dimensions, tuple):
            raise TypeError("risk dimensions must be an immutable canonical mapping")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0]
            or pair[0] != pair[0].strip()
            or not isinstance(pair[1], str)
            or not pair[1]
            for pair in self.risk_dimensions
        ):
            raise ValueError("risk dimensions require non-empty immutable text key/value pairs")
        dimension_keys = tuple(pair[0] for pair in self.risk_dimensions)
        if len(dimension_keys) != len(set(dimension_keys)) or dimension_keys != tuple(sorted(dimension_keys)):
            raise ValueError("risk dimensions require unique lexically canonical keys")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("reservation quantity must be a positive finite Decimal")
        if not isinstance(self.action, ReservationAction):
            raise TypeError("reservation action must be typed")
        if (
            not isinstance(self.source_kind, ReservationSourceKind)
            or self.source_ref is None
            or self.source_hash is None
        ):
            raise ValueError("reservations require a typed source union")
        if (
            not isinstance(self.source_ref, EntityId)
            or not isinstance(self.source_hash, str)
            or len(self.source_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.source_hash)
        ):
            raise ValueError("reservation source must use a typed id and lowercase SHA-256")

    @property
    def reservation_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.reservation_id),
                "account": str(self.account_id),
                "plan": str(self.plan_id),
                "plan_version": self.plan_version,
                "plan_hash": self.plan_hash,
                "instrument": self.instrument,
                "strategy": self.strategy,
                "session": self.session,
                "basis": self.authorization_basis_hash,
                "constitution": self.risk_constitution_ref,
                "constitution_version": self.risk_constitution_version,
                "constitution_hash": self.risk_constitution_hash,
                "ceiling": str(self.risk_constitution_ceiling),
                "loss": str(self.worst_case_loss),
                "margin": str(self.margin),
                "expiry": self.expires_at.to_dict()["recorded_at"],
                "status": self.status.value,
                "version": self.version,
                "state_version": self.state_version,
                "dimensions": dict(self.risk_dimensions),
                "quantity": str(self.quantity),
                "action": self.action.value,
                "source_kind": self.source_kind.value,
                "source_ref": str(self.source_ref),
                "source_hash": self.source_hash,
            }
        )

    def active_at(self, now: RecordedAt) -> bool:
        return self.status is ReservationStatus.HELD and now.value < self.expires_at.value


class RiskBudgetLedger:
    """Compare-and-reserve model; production maps this lock to one DB transaction."""

    def __init__(
        self, total_ceiling: Decimal, constitution_ref: str, constitution_version: int, constitution_hash: str
    ) -> None:
        if (
            not isinstance(total_ceiling, Decimal)
            or not total_ceiling.is_finite()
            or total_ceiling < 0
            or not _canonical_reference(constitution_ref)
        ):
            raise ValueError("ledger needs a non-negative constitution ceiling and reference")
        if (
            isinstance(constitution_version, bool)
            or not isinstance(constitution_version, int)
            or constitution_version < 1
        ):
            raise ValueError("ledger requires a positive authority version")
        if (
            not isinstance(constitution_hash, str)
            or len(constitution_hash) != 64
            or any(character not in "0123456789abcdef" for character in constitution_hash)
        ):
            raise ValueError("ledger requires a lowercase authority hash")
        self._total_ceiling = total_ceiling
        self._constitution_ref = constitution_ref
        self._constitution_version = constitution_version
        self._constitution_hash = constitution_hash
        self._reservations: dict[EntityId, RiskBudgetReservation] = {}
        self._reservation_keys: dict[tuple[EntityId, int, EntityId], EntityId] = {}
        self._lock = RLock()

    @staticmethod
    def _reservation_key(reservation: RiskBudgetReservation) -> tuple[EntityId, int, EntityId]:
        return (reservation.plan_id, reservation.plan_version, reservation.authorization_basis_id)

    def reserve(self, reservation: RiskBudgetReservation, now: RecordedAt) -> bool:
        with self._lock:
            if (
                reservation.risk_constitution_ref != self._constitution_ref
                or reservation.risk_constitution_version != self._constitution_version
                or reservation.risk_constitution_hash != self._constitution_hash
                or reservation.risk_constitution_ceiling > self._total_ceiling
            ):
                return False
            self.expire(now)
            existing = self._reservations.get(reservation.reservation_id)
            if existing is not None:
                return existing == reservation
            identity = self._reservation_key(reservation)
            existing_id = self._reservation_keys.get(identity)
            if existing_id is not None:
                # A replay must retain both immutable identity and fingerprint.
                return self._reservations[existing_id] == reservation
            held = sum((item.worst_case_loss for item in self._reservations.values() if item.active_at(now)), Decimal())
            if held + reservation.worst_case_loss > self._total_ceiling or not reservation.active_at(now):
                return False
            self._reservations[reservation.reservation_id] = reservation
            self._reservation_keys[identity] = reservation.reservation_id
            return True

    def release(self, reservation_id: EntityId) -> RiskBudgetReservation | None:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None or reservation.status is not ReservationStatus.HELD:
                return reservation
            result = replace(
                reservation,
                status=ReservationStatus.RELEASED,
                version=reservation.version + 1,
                state_version=reservation.state_version + 1,
            )
            self._reservations[reservation_id] = result
            return result

    def shrink(self, reservation_id: EntityId, worst_case_loss: Decimal) -> RiskBudgetReservation | None:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if (
                reservation is None
                or reservation.status is not ReservationStatus.HELD
                or not isinstance(worst_case_loss, Decimal)
                or not worst_case_loss.is_finite()
                or worst_case_loss < 0
                or worst_case_loss > reservation.worst_case_loss
            ):
                return None
            result = replace(
                reservation,
                worst_case_loss=worst_case_loss,
                version=reservation.version + 1,
                state_version=reservation.state_version + 1,
            )
            self._reservations[reservation_id] = result
            return result

    def consume(self, reservation_id: EntityId, now: RecordedAt) -> RiskBudgetReservation | None:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None or not reservation.active_at(now):
                return None
            result = replace(
                reservation,
                status=ReservationStatus.CONSUMED,
                version=reservation.version + 1,
                state_version=reservation.state_version + 1,
            )
            self._reservations[reservation_id] = result
            return result

    def reconcile(self, reservation_id: EntityId) -> RiskBudgetReservation | None:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None or reservation.status is not ReservationStatus.CONSUMED:
                return None
            result = replace(
                reservation,
                status=ReservationStatus.RECONCILED,
                version=reservation.version + 1,
                state_version=reservation.state_version + 1,
            )
            self._reservations[reservation_id] = result
            return result

    def expire(self, now: RecordedAt) -> None:
        with self._lock:
            for identifier, reservation in tuple(self._reservations.items()):
                if reservation.status is ReservationStatus.HELD and now.value >= reservation.expires_at.value:
                    self._reservations[identifier] = replace(
                        reservation,
                        status=ReservationStatus.EXPIRED,
                        version=reservation.version + 1,
                        state_version=reservation.state_version + 1,
                    )

    @property
    def reservations(self) -> tuple[RiskBudgetReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

    def reservation(self, reservation_id: EntityId) -> RiskBudgetReservation | None:
        """Return the authoritative current row used by the final autonomy gate."""
        if not isinstance(reservation_id, EntityId):
            raise TypeError("reservation lookup requires a typed reservation id")
        with self._lock:
            return self._reservations.get(reservation_id)
