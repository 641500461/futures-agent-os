"""Immutable V0 contracts for simulation autonomy; no order or risk authority.

The in-memory registries are deliberately reference models for the future
PostgreSQL transactions.  They make race and TOCTOU requirements executable
without implementing an execution runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import TYPE_CHECKING

from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

if TYPE_CHECKING:
    from futures_agent_os.portfolio_risk import RiskBudgetReservation


def _sha(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("hashes must be lowercase SHA-256 digests")
    return value


def _positive_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("version must be a positive integer")
    return value


def _actor(value: str) -> str:
    """Accept only canonical auditable actor identities, never whitespace aliases."""
    if not isinstance(value, str) or value != value.strip() or ":" not in value:
        raise ValueError("actors must be non-empty canonical identities")
    kind, subject = value.split(":", 1)
    if (
        kind not in {"user", "service", "system"}
        or not subject
        or subject != subject.strip()
        or any(character.isspace() for character in subject)
    ):
        raise ValueError("actors require a non-empty user, service, or system subject")
    return value


def _scope_text(value: str) -> bool:
    """Canonical execution identifiers cannot carry whitespace aliases."""
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _canonical_reference(value: str) -> bool:
    """Policy references are auditable identifiers, never whitespace aliases."""
    return _scope_text(value)


class MandateStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    HALTED = "HALTED"
    RECOVERING = "RECOVERING"


class AutonomyMode(StrEnum):
    OBSERVE = "OBSERVE"
    SHADOW = "SHADOW"
    AUTONOMOUS_SIMULATION = "AUTONOMOUS_SIMULATION"
    PAUSED = "PAUSED"


class BindingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PlanApprovalStatus(StrEnum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class BasisKind(StrEnum):
    MANDATE = "MANDATE"
    PLAN_APPROVAL = "PLAN_APPROVAL"


class BasisStatus(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class ExecutionOrigin(StrEnum):
    AUTONOMOUS_AGENT = "AUTONOMOUS_AGENT"
    MANUAL_TEST = "MANUAL_TEST"


class ApprovalAction(StrEnum):
    """The deliberately small V0 action vocabulary for a manual approval."""

    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


class PreflightOutcome(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"


class FinalGateOutcome(StrEnum):
    PERMIT = "PERMIT"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    """The non-expandable account, action, quantity, and time envelope of an approval."""

    simulation_account_id: EntityId
    instruments: tuple[str, ...]
    strategies: tuple[str, ...]
    sessions: tuple[str, ...]
    actions: frozenset[ApprovalAction]
    quantity_ceiling: Decimal
    valid_from_at: RecordedAt
    valid_until_at: RecordedAt

    def __post_init__(self) -> None:
        if not isinstance(self.simulation_account_id, EntityId):
            raise TypeError("approval scope requires a typed simulation account")
        for collection in (self.instruments, self.strategies, self.sessions):
            if (
                not isinstance(collection, tuple)
                or not collection
                or any(not _scope_text(item) for item in collection)
                or len(collection) != len(set(collection))
                or collection != tuple(sorted(collection))
            ):
                raise ValueError("approval scope dimensions must be canonical immutable sorted text tuples")
        if (
            not isinstance(self.actions, frozenset)
            or not self.actions
            or any(not isinstance(action, ApprovalAction) for action in self.actions)
        ):
            raise TypeError("approval scope actions must be a non-empty immutable ApprovalAction set")
        if (
            not isinstance(self.quantity_ceiling, Decimal)
            or not self.quantity_ceiling.is_finite()
            or self.quantity_ceiling <= 0
        ):
            raise ValueError("approval scope quantity ceiling must be a positive finite Decimal")
        if not isinstance(self.valid_from_at, RecordedAt) or not isinstance(self.valid_until_at, RecordedAt):
            raise TypeError("approval scope requires typed timestamps")
        if self.valid_until_at.value <= self.valid_from_at.value:
            raise ValueError("approval scope requires a non-empty validity window")

    @property
    def scope_hash(self) -> str:
        return canonical_sha256(
            {
                "account": str(self.simulation_account_id),
                "instruments": self.instruments,
                "strategies": self.strategies,
                "sessions": self.sessions,
                "actions": tuple(sorted(action.value for action in self.actions)),
                "quantity_ceiling": str(self.quantity_ceiling),
                "valid_from": self.valid_from_at.to_dict()["recorded_at"],
                "valid_until": self.valid_until_at.to_dict()["recorded_at"],
            }
        )

    def permits(
        self,
        account_id: EntityId,
        instrument: str,
        strategy: str,
        session: str,
        action: ApprovalAction,
        quantity: Decimal,
        now: RecordedAt,
    ) -> bool:
        return (
            account_id == self.simulation_account_id
            and instrument in self.instruments
            and strategy in self.strategies
            and session in self.sessions
            and isinstance(action, ApprovalAction)
            and isinstance(quantity, Decimal)
            and quantity.is_finite()
            and quantity > 0
            and quantity <= self.quantity_ceiling
            and action in self.actions
            and self.valid_from_at.value <= now.value < self.valid_until_at.value
        )


@dataclass(frozen=True, slots=True)
class MandateScope:
    """The immutable, non-expandable envelope of a user delegation."""

    simulation_account_id: EntityId
    instruments: tuple[str, ...]
    strategies: tuple[str, ...]
    sessions: tuple[str, ...]
    actions: frozenset[ApprovalAction]
    quantity_ceiling: Decimal
    risk_constitution_ref: str
    notification_policy_ref: str
    escalation_policy_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.simulation_account_id, EntityId):
            raise TypeError("mandate scope requires a simulation account id")
        for collection in (self.instruments, self.strategies, self.sessions):
            if not isinstance(collection, tuple):
                raise TypeError("mandate scope collections must be immutable tuples")
            if (
                not collection
                or any(not _scope_text(item) for item in collection)
                or len(collection) != len(set(collection))
                or collection != tuple(sorted(collection))
            ):
                raise ValueError("mandate scope collections must be canonical sorted text tuples")
        if (
            not isinstance(self.actions, frozenset)
            or not self.actions
            or any(not isinstance(action, ApprovalAction) for action in self.actions)
        ):
            raise TypeError("mandate scope actions must be a non-empty immutable ApprovalAction set")
        if (
            not isinstance(self.quantity_ceiling, Decimal)
            or not self.quantity_ceiling.is_finite()
            or self.quantity_ceiling <= 0
        ):
            raise ValueError("mandate scope quantity ceiling must be a positive finite Decimal")
        if not all(
            _canonical_reference(value)
            for value in (self.risk_constitution_ref, self.notification_policy_ref, self.escalation_policy_ref)
        ):
            raise ValueError("mandate scope requires canonical risk, notification, and escalation references")

    @property
    def sha256(self) -> str:
        return canonical_sha256(
            {
                "account": str(self.simulation_account_id),
                "instruments": self.instruments,
                "strategies": self.strategies,
                "sessions": self.sessions,
                "actions": tuple(sorted(action.value for action in self.actions)),
                "quantity_ceiling": str(self.quantity_ceiling),
                "risk_constitution_ref": self.risk_constitution_ref,
                "notification_policy_ref": self.notification_policy_ref,
                "escalation_policy_ref": self.escalation_policy_ref,
            }
        )

    def matches(
        self,
        account_id: EntityId,
        instrument: str,
        strategy: str,
        session: str,
        action: ApprovalAction,
        quantity: Decimal,
    ) -> bool:
        return account_id == self.simulation_account_id and all(
            (
                instrument in self.instruments,
                strategy in self.strategies,
                session in self.sessions,
                isinstance(action, ApprovalAction) and action in self.actions,
                isinstance(quantity, Decimal)
                and quantity.is_finite()
                and quantity > 0
                and quantity <= self.quantity_ceiling,
            )
        )


_MANDATE_TRANSITIONS: dict[MandateStatus, frozenset[MandateStatus]] = {
    MandateStatus.DRAFT: frozenset({MandateStatus.VALIDATED}),
    MandateStatus.VALIDATED: frozenset({MandateStatus.APPROVED}),
    MandateStatus.APPROVED: frozenset({MandateStatus.ACTIVE, MandateStatus.REVOKED}),
    MandateStatus.ACTIVE: frozenset({MandateStatus.SUSPENDED, MandateStatus.HALTED, MandateStatus.REVOKED}),
    MandateStatus.SUSPENDED: frozenset({MandateStatus.ACTIVE, MandateStatus.REVOKED}),
    MandateStatus.HALTED: frozenset({MandateStatus.RECOVERING, MandateStatus.REVOKED}),
    MandateStatus.RECOVERING: frozenset({MandateStatus.ACTIVE, MandateStatus.HALTED, MandateStatus.REVOKED}),
    MandateStatus.EXPIRED: frozenset(),
    MandateStatus.REVOKED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class SimulationAutonomyMandate:
    mandate_id: EntityId
    version: int
    status: MandateStatus
    scope: MandateScope
    expires_at: RecordedAt
    recorded_at: RecordedAt
    recorded_by: str
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        _positive_version(self.version)
        if not isinstance(self.mandate_id, EntityId) or not isinstance(self.scope, MandateScope):
            raise TypeError("mandates require ids and a mandate scope")
        if (
            not isinstance(self.status, MandateStatus)
            or not isinstance(self.expires_at, RecordedAt)
            or not isinstance(self.recorded_at, RecordedAt)
        ):
            raise TypeError("mandates require status and timestamps")
        if self.status is MandateStatus.EXPIRED:
            if self.recorded_at.value < self.expires_at.value:
                raise ValueError("expired mandates may only be recorded at or after expiry")
        elif self.status is not MandateStatus.REVOKED and self.expires_at.value <= self.recorded_at.value:
            raise ValueError("nonterminal mandates require a future expiry")
        _actor(self.recorded_by)
        if self.status is MandateStatus.REVOKED and not self.revocation_reason:
            raise ValueError("revoked mandates require a reason")

    @property
    def authorization_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.mandate_id),
                "version": self.version,
                "scope": self.scope.sha256,
                "expiry": self.expires_at.to_dict()["recorded_at"],
                "status": self.status.value,
            }
        )

    @property
    def state_hash(self) -> str:
        """The state-bearing authorization digest; aliases the V0 mandate hash."""
        return self.authorization_hash

    def status_at(self, now: RecordedAt) -> MandateStatus:
        if (
            self.status not in {MandateStatus.DRAFT, MandateStatus.EXPIRED, MandateStatus.REVOKED}
            and now.value >= self.expires_at.value
        ):
            return MandateStatus.EXPIRED
        return self.status

    def is_active_at(self, now: RecordedAt) -> bool:
        return self.status_at(now) is MandateStatus.ACTIVE

    def transition(
        self, target: MandateStatus, now: RecordedAt, *, actor_is_human: bool, reason: str | None = None
    ) -> SimulationAutonomyMandate:
        current = self.status_at(now)
        if target is MandateStatus.EXPIRED:
            if current is MandateStatus.EXPIRED:
                return replace(self, status=target, version=self.version + 1, recorded_at=now)
            raise ValueError("expiry is clock-derived")
        if target not in _MANDATE_TRANSITIONS[current]:
            raise ValueError(f"invalid mandate transition: {current} -> {target}")
        if target in {MandateStatus.ACTIVE, MandateStatus.RECOVERING, MandateStatus.REVOKED} and not actor_is_human:
            raise PermissionError("agents cannot activate, recover, or revoke mandates")
        if target is MandateStatus.REVOKED and not reason:
            raise ValueError("revocation requires a reason")
        if now.value >= self.expires_at.value:
            raise ValueError("expired mandates cannot transition")
        return replace(
            self,
            status=target,
            revocation_reason=reason if target is MandateStatus.REVOKED else None,
            version=self.version + 1,
            recorded_at=now,
        )


@dataclass(frozen=True, slots=True)
class AutonomyModeBinding:
    binding_id: EntityId
    version: int
    mode: AutonomyMode
    status: BindingStatus
    simulation_account_id: EntityId | None
    mandate_id: EntityId | None
    mandate_version: int | None
    run_versions_hash: str
    expires_at: RecordedAt
    recorded_at: RecordedAt
    scope_snapshot_hash: str
    scan_policy_ref: str
    universe_policy_ref: str
    qualified_artifact_ref: str | None
    transition_reason: str
    transition_actor: str
    evidence_ref: str
    previous_mode: AutonomyMode | None = None

    def __post_init__(self) -> None:
        _positive_version(self.version)
        _sha(self.run_versions_hash)
        _sha(self.scope_snapshot_hash)
        if (
            not isinstance(self.binding_id, EntityId)
            or not isinstance(self.mode, AutonomyMode)
            or not isinstance(self.status, BindingStatus)
        ):
            raise TypeError("mode bindings require typed ids and enum values")
        if self.simulation_account_id is not None and not isinstance(self.simulation_account_id, EntityId):
            raise TypeError("mode binding account must be a typed id when present")
        if self.mandate_id is not None and not isinstance(self.mandate_id, EntityId):
            raise TypeError("mode binding mandate must be a typed id when present")
        if self.previous_mode is not None and not isinstance(self.previous_mode, AutonomyMode):
            raise TypeError("mode binding previous mode must be typed")
        if not isinstance(self.expires_at, RecordedAt) or not isinstance(self.recorded_at, RecordedAt):
            raise ValueError("mode bindings require typed timestamps")
        if self.status is BindingStatus.EXPIRED:
            if self.recorded_at.value < self.expires_at.value:
                raise ValueError("expired bindings may only be recorded at or after expiry")
        elif self.status is BindingStatus.ACTIVE and self.expires_at.value <= self.recorded_at.value:
            raise ValueError("active bindings require a future expiry")
        if not all(
            isinstance(value, str) and value
            for value in (
                self.scan_policy_ref,
                self.universe_policy_ref,
                self.transition_reason,
                self.transition_actor,
                self.evidence_ref,
            )
        ):
            raise ValueError("mode bindings require scope policy and transition evidence references")
        _actor(self.transition_actor)
        if self.qualified_artifact_ref is not None and not _canonical_reference(self.qualified_artifact_ref):
            raise ValueError("qualified artifact reference must be canonical when supplied")
        if self.mode is AutonomyMode.OBSERVE:
            if self.mandate_id is not None or self.mandate_version is not None:
                raise ValueError("observe bindings cannot name a mandate")
        elif self.mode is AutonomyMode.SHADOW:
            if self.simulation_account_id is None or self.mandate_id is not None or self.mandate_version is not None:
                raise ValueError("shadow requires an account and no mandate")
        elif self.mode is AutonomyMode.AUTONOMOUS_SIMULATION:
            if (
                self.simulation_account_id is None
                or self.mandate_id is None
                or self.mandate_version is None
                or self.qualified_artifact_ref is None
            ):
                raise ValueError("autonomous simulation requires account and mandate")
        elif self.mode is AutonomyMode.PAUSED:
            if self.previous_mode not in {
                AutonomyMode.OBSERVE,
                AutonomyMode.SHADOW,
                AutonomyMode.AUTONOMOUS_SIMULATION,
            }:
                raise ValueError("paused bindings retain a legal previous mode")
            if self.previous_mode is AutonomyMode.OBSERVE and (
                self.mandate_id is not None or self.mandate_version is not None
            ):
                raise ValueError("paused observe bindings cannot name a mandate")
            if self.previous_mode is AutonomyMode.SHADOW and (
                self.simulation_account_id is None or self.mandate_id is not None or self.mandate_version is not None
            ):
                raise ValueError("paused shadow bindings require account and no mandate")
            if self.previous_mode is AutonomyMode.AUTONOMOUS_SIMULATION and (
                self.simulation_account_id is None
                or self.mandate_id is None
                or self.mandate_version is None
                or self.qualified_artifact_ref is None
            ):
                raise ValueError("paused autonomous bindings retain account, mandate, and qualification")
        if self.mandate_version is not None:
            _positive_version(self.mandate_version)

    @property
    def binding_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.binding_id),
                "version": self.version,
                "mode": self.mode.value,
                "status": self.status.value,
                "account": str(self.simulation_account_id) if self.simulation_account_id else None,
                "mandate": str(self.mandate_id) if self.mandate_id else None,
                "mandate_version": self.mandate_version,
                "run_versions": self.run_versions_hash,
                "scope": self.scope_snapshot_hash,
                "scan_policy": self.scan_policy_ref,
                "universe_policy": self.universe_policy_ref,
                "qualified_artifact": self.qualified_artifact_ref,
                "transition_reason": self.transition_reason,
                "transition_actor": self.transition_actor,
                "evidence": self.evidence_ref,
                "previous_mode": self.previous_mode.value if self.previous_mode else None,
                "expiry": self.expires_at.to_dict()["recorded_at"],
            }
        )

    def is_active_at(self, now: RecordedAt) -> bool:
        return self.status is BindingStatus.ACTIVE and now.value < self.expires_at.value

    def pause(
        self, now: RecordedAt, *, reason: str, actor: str, evidence_ref: str, mandate_version: int | None = None
    ) -> AutonomyModeBinding:
        if not self.is_active_at(now) or self.mode is AutonomyMode.PAUSED:
            raise ValueError("only active non-paused bindings may pause")
        if not all(isinstance(value, str) and value for value in (reason, actor, evidence_ref)):
            raise ValueError("pauses require reason, actor, and evidence")
        _actor(actor)
        if mandate_version is not None:
            _positive_version(mandate_version)
        return replace(
            self,
            mode=AutonomyMode.PAUSED,
            previous_mode=self.mode,
            mandate_version=mandate_version if mandate_version is not None else self.mandate_version,
            transition_reason=reason,
            transition_actor=actor,
            evidence_ref=evidence_ref,
            version=self.version + 1,
            recorded_at=now,
        )

    def resume(
        self,
        now: RecordedAt,
        *,
        actor_is_human: bool,
        actor: str,
        qualified: bool,
        health_permits: bool,
        mandate: SimulationAutonomyMandate | None,
        run_versions_hash: str,
        evidence_ref: str,
    ) -> AutonomyModeBinding:
        if (
            not actor_is_human
            or not self.is_active_at(now)
            or self.mode is not AutonomyMode.PAUSED
            or self.previous_mode is None
        ):
            raise PermissionError("only an authorized actor may resume an active paused binding")
        _sha(run_versions_hash)
        _actor(actor)
        if not actor.startswith("user:"):
            raise PermissionError("binding resume requires a human actor")
        if not evidence_ref:
            raise ValueError("resume requires actor and evidence")
        if self.previous_mode is AutonomyMode.AUTONOMOUS_SIMULATION:
            if (
                mandate is None
                or not mandate.is_active_at(now)
                or self.mandate_id != mandate.mandate_id
                or not qualified
                or not health_permits
                or self.run_versions_hash != run_versions_hash
            ):
                raise ValueError("autonomous resume requires the exact active mandate, qualified run, and health")
            mandate_version: int | None = mandate.version
        else:
            mandate_version = None
        return replace(
            self,
            mode=self.previous_mode,
            previous_mode=None,
            mandate_version=mandate_version,
            transition_reason="USER_RESUME",
            transition_actor=actor,
            evidence_ref=evidence_ref,
            version=self.version + 1,
            recorded_at=now,
        )

    def expire(self, now: RecordedAt) -> AutonomyModeBinding:
        if self.status is not BindingStatus.ACTIVE or now.value < self.expires_at.value:
            raise ValueError("bindings only expire at their expiry boundary")
        return replace(self, status=BindingStatus.EXPIRED, version=self.version + 1, recorded_at=now)

    def supersede(self, now: RecordedAt) -> AutonomyModeBinding:
        if not self.is_active_at(now):
            raise ValueError("only active bindings may be superseded")
        return replace(self, status=BindingStatus.SUPERSEDED, version=self.version + 1, recorded_at=now)


@dataclass(frozen=True, slots=True)
class EffectiveAutonomy:
    permitted: bool
    reason: str

    @classmethod
    def evaluate(
        cls,
        mandate: SimulationAutonomyMandate | None,
        binding: AutonomyModeBinding | None,
        *,
        qualified: bool,
        health_permits: bool,
        now: RecordedAt,
    ) -> EffectiveAutonomy:
        if not health_permits:
            return cls(False, "HEALTH_BLOCKED")
        if mandate is None or not mandate.is_active_at(now):
            if mandate is not None and mandate.status_at(now) in {MandateStatus.HALTED, MandateStatus.SUSPENDED}:
                return cls(False, "MANDATE_PROTECT_ONLY")
            return cls(False, "MANDATE_INACTIVE")
        if binding is None or not binding.is_active_at(now):
            return cls(False, "MODE_INACTIVE")
        if binding.mode is AutonomyMode.PAUSED:
            return cls(False, "MODE_PAUSED")
        if binding.mode is not AutonomyMode.AUTONOMOUS_SIMULATION:
            return cls(False, "MODE_INACTIVE")
        if binding.mandate_id != mandate.mandate_id or binding.mandate_version != mandate.version:
            return cls(False, "MANDATE_BINDING_MISMATCH")
        if binding.simulation_account_id != mandate.scope.simulation_account_id:
            return cls(False, "BINDING_ACCOUNT_MISMATCH")
        if binding.scope_snapshot_hash != mandate.scope.sha256:
            return cls(False, "BINDING_SCOPE_MISMATCH")
        if not qualified:
            return cls(False, "RUN_UNQUALIFIED")
        return cls(True, "EFFECTIVE")


@dataclass(frozen=True, slots=True)
class CompositePause:
    mandate: SimulationAutonomyMandate
    binding: AutonomyModeBinding
    stale_bases: tuple[AuthorizationBasis, ...]
    invalidated_receipts: tuple[AutonomyGateReceipt, ...]
    released_reservations: tuple[RiskBudgetReservation, ...]

    @property
    def invalidated_authorization_hashes(self) -> tuple[str, ...]:
        """Audit convenience only; the state transition is held in stale_bases."""
        return tuple(basis.basis_hash for basis in self.stale_bases)

    @property
    def invalidated_receipt_hashes(self) -> tuple[str, ...]:
        """Audit convenience only; receipt invalidation is performed by the coordinator."""
        return tuple(receipt.receipt_hash for receipt in self.invalidated_receipts)

    @property
    def released_reservation_ids(self) -> tuple[EntityId, ...]:
        """Audit convenience only; the ledger is the source of reservation state."""
        return tuple(reservation.reservation_id for reservation in self.released_reservations)

    @classmethod
    def apply(
        cls,
        mandate: SimulationAutonomyMandate,
        binding: AutonomyModeBinding,
        now: RecordedAt,
        *,
        coordinator: BindingArtifactCoordinator,
        actor: str = "user:authorized",
        evidence_ref: str = "evidence://user-pause",
    ) -> CompositePause:
        if mandate.status_at(now) is not MandateStatus.ACTIVE or binding.mode is not AutonomyMode.AUTONOMOUS_SIMULATION:
            raise ValueError("composite pause requires active autonomous mandate and binding")
        if (
            binding.simulation_account_id != mandate.scope.simulation_account_id
            or binding.mandate_id != mandate.mandate_id
            or binding.mandate_version != mandate.version
        ):
            raise ValueError("composite pause requires a matching mandate and binding account")
        _actor(actor)
        if not actor.startswith("user:"):
            raise PermissionError("composite pause requires a human actor")
        if not evidence_ref:
            raise ValueError("composite pause requires a human audit actor and evidence")
        suspended = mandate.transition(MandateStatus.SUSPENDED, now, actor_is_human=True, reason="USER_PAUSE")
        paused = binding.pause(
            now, reason="USER_PAUSE", actor=actor, evidence_ref=evidence_ref, mandate_version=suspended.version
        )
        if not isinstance(coordinator, BindingArtifactCoordinator):
            raise TypeError("composite pause requires the artifact coordinator")
        invalidation = coordinator.pause(paused, now)
        return cls(
            suspended,
            paused,
            invalidation.stale_bases,
            invalidation.invalidated_receipts,
            invalidation.released_reservations,
        )


@dataclass(frozen=True, slots=True)
class CompositeResume:
    """A human-only reactivation that creates new state hashes and invalidates paused artifacts."""

    mandate: SimulationAutonomyMandate
    binding: AutonomyModeBinding

    @classmethod
    def apply(
        cls,
        mandate: SimulationAutonomyMandate,
        binding: AutonomyModeBinding,
        now: RecordedAt,
        *,
        actor: str,
        qualified: bool,
        health_permits: bool,
        run_versions_hash: str,
        evidence_ref: str,
    ) -> CompositeResume:
        try:
            _actor(actor)
        except ValueError as error:
            raise PermissionError("composite resume requires a human actor") from error
        if not actor.startswith("user:"):
            raise PermissionError("composite resume requires a human actor")
        if mandate.status_at(now) is not MandateStatus.SUSPENDED:
            raise ValueError("only a non-expired suspended mandate may resume")
        if binding.mode is not AutonomyMode.PAUSED or binding.previous_mode is not AutonomyMode.AUTONOMOUS_SIMULATION:
            raise ValueError("composite resume requires a paused autonomous binding")
        if (binding.mandate_id, binding.mandate_version) != (mandate.mandate_id, mandate.version):
            raise ValueError("paused binding does not match current suspended mandate version")
        reactivated = mandate.transition(MandateStatus.ACTIVE, now, actor_is_human=True, reason="USER_RESUME")
        resumed = binding.resume(
            now,
            actor_is_human=True,
            actor=actor,
            qualified=qualified,
            health_permits=health_permits,
            mandate=reactivated,
            run_versions_hash=run_versions_hash,
            evidence_ref=evidence_ref,
        )
        return cls(reactivated, resumed)


@dataclass(frozen=True, slots=True)
class PlanApproval:
    approval_id: EntityId
    version: int
    status: PlanApprovalStatus
    plan_id: EntityId
    plan_version: int
    plan_hash: str
    account_id: EntityId
    scope: ApprovalScope
    approval_token: EntityId
    requested_by: str
    expires_at: RecordedAt
    requested_at: RecordedAt
    consumer_basis_id: EntityId | None = None
    consumed_at: RecordedAt | None = None
    decided_at: RecordedAt | None = None
    decided_by: str | None = None

    def __post_init__(self) -> None:
        _positive_version(self.version)
        _positive_version(self.plan_version)
        _sha(self.plan_hash)
        if not isinstance(self.status, PlanApprovalStatus) or not all(
            isinstance(value, EntityId) for value in (self.approval_id, self.plan_id, self.account_id)
        ):
            raise TypeError("approvals require typed status and identifiers")
        if not isinstance(self.scope, ApprovalScope) or not isinstance(self.approval_token, EntityId):
            raise TypeError("approvals require a typed approval scope and one-time token")
        if self.account_id != self.scope.simulation_account_id:
            raise ValueError("approval account must equal its non-expandable scope account")
        _actor(self.requested_by)
        if (
            not isinstance(self.expires_at, RecordedAt)
            or not isinstance(self.requested_at, RecordedAt)
            or self.expires_at.value <= self.requested_at.value
        ):
            raise ValueError("approvals require future expiry")
        if (
            self.scope.valid_from_at.value < self.requested_at.value
            or self.scope.valid_until_at.value > self.expires_at.value
        ):
            raise ValueError("approval scope must remain within the approval validity window")
        if self.status is PlanApprovalStatus.CONSUMED and (self.consumer_basis_id is None or self.consumed_at is None):
            raise ValueError("consumed approvals require their one consumer basis")
        if self.status is not PlanApprovalStatus.CONSUMED and (self.consumer_basis_id or self.consumed_at):
            raise ValueError("only consumed approvals may name a consumer")
        if self.status in {PlanApprovalStatus.GRANTED, PlanApprovalStatus.REJECTED, PlanApprovalStatus.CONSUMED} and (
            self.decided_at is None or not self.decided_by
        ):
            raise ValueError("decided approvals require a decision actor and timestamp")
        if self.decided_by is not None:
            _actor(self.decided_by)
        if self.status in {PlanApprovalStatus.GRANTED, PlanApprovalStatus.CONSUMED} and not (
            self.decided_by or ""
        ).startswith("user:"):
            raise PermissionError("only a human user may grant a plan approval")

    @property
    def authorization_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.approval_id),
                "version": self.version,
                "plan": str(self.plan_id),
                "plan_version": self.plan_version,
                "plan_hash": self.plan_hash,
                "account": str(self.account_id),
                "scope": self.scope.scope_hash,
                "token": str(self.approval_token),
                "requested_by": self.requested_by,
                "decided_at": self.decided_at.to_dict()["recorded_at"] if self.decided_at else None,
                "decided_by": self.decided_by,
                "expiry": self.expires_at.to_dict()["recorded_at"],
                "status": self.status.value,
            }
        )

    @property
    def granted_authorization_hash(self) -> str:
        """The immutable GRANTED source fact consumed by an approval Basis."""
        if self.status is PlanApprovalStatus.GRANTED:
            return self.authorization_hash
        if self.status is PlanApprovalStatus.CONSUMED:
            return replace(
                self,
                status=PlanApprovalStatus.GRANTED,
                version=self.version - 1,
                consumer_basis_id=None,
                consumed_at=None,
            ).authorization_hash
        raise ValueError("only granted or consumed approvals have a grant source hash")

    def status_at(self, now: RecordedAt) -> PlanApprovalStatus:
        if (
            self.status in {PlanApprovalStatus.REQUESTED, PlanApprovalStatus.GRANTED}
            and now.value >= self.expires_at.value
        ):
            return PlanApprovalStatus.EXPIRED
        return self.status

    def decide(self, target: PlanApprovalStatus, now: RecordedAt, *, actor: str = "user:authorized") -> PlanApproval:
        if self.status_at(now) is not PlanApprovalStatus.REQUESTED:
            raise ValueError("only requested approvals may be decided")
        if target not in {PlanApprovalStatus.GRANTED, PlanApprovalStatus.REJECTED}:
            raise ValueError("approval decisions are GRANTED or REJECTED")
        _actor(actor)
        if target is PlanApprovalStatus.GRANTED and not actor.startswith("user:"):
            raise PermissionError("only a human user may grant a plan approval")
        return replace(self, status=target, version=self.version + 1, decided_at=now, decided_by=actor)


@dataclass(frozen=True, slots=True)
class AuthorizationBasis:
    basis_id: EntityId
    kind: BasisKind
    plan_id: EntityId
    plan_version: int
    plan_hash: str
    account_id: EntityId
    instrument: str
    strategy: str
    session: str
    source_id: EntityId
    source_version: int
    source_hash: str
    created_at: RecordedAt
    expires_at: RecordedAt
    scope_snapshot_hash: str
    authorized_action: ApprovalAction
    authorized_quantity: Decimal
    approval_token: EntityId | None
    approval_valid_from_at: RecordedAt | None
    approval_valid_until_at: RecordedAt | None
    issued_by: str
    actor_audit_ref: str
    status: BasisStatus = BasisStatus.ACTIVE

    def __post_init__(self) -> None:
        _positive_version(self.plan_version)
        _positive_version(self.source_version)
        _sha(self.plan_hash)
        _sha(self.source_hash)
        _sha(self.scope_snapshot_hash)
        if not isinstance(self.kind, BasisKind) or not isinstance(self.status, BasisStatus):
            raise TypeError("authorization bases require enum values")
        if not all(
            isinstance(value, EntityId) for value in (self.basis_id, self.plan_id, self.account_id, self.source_id)
        ):
            raise TypeError("authorization bases require typed identifiers")
        if not all(_scope_text(value) for value in (self.instrument, self.strategy, self.session)):
            raise ValueError("authorization bases require an exact execution scope")
        if (
            not isinstance(self.created_at, RecordedAt)
            or not isinstance(self.expires_at, RecordedAt)
            or self.expires_at.value <= self.created_at.value
        ):
            raise ValueError("authorization bases require a future expiry")
        if (
            not isinstance(self.authorized_action, ApprovalAction)
            or not isinstance(self.authorized_quantity, Decimal)
            or not self.authorized_quantity.is_finite()
            or self.authorized_quantity <= 0
        ):
            raise ValueError("authorization bases require a typed selected action and positive finite quantity")
        if self.kind is BasisKind.MANDATE:
            if any(
                value is not None
                for value in (self.approval_token, self.approval_valid_from_at, self.approval_valid_until_at)
            ):
                raise ValueError("mandate bases cannot carry approval token or window")
        elif (
            not isinstance(self.approval_token, EntityId)
            or not isinstance(self.approval_valid_from_at, RecordedAt)
            or not isinstance(self.approval_valid_until_at, RecordedAt)
            or self.approval_valid_until_at.value <= self.approval_valid_from_at.value
            or self.expires_at.value > self.approval_valid_until_at.value
        ):
            raise ValueError("approval bases require token and a bounded approval window")
        if not isinstance(self.actor_audit_ref, str) or not self.actor_audit_ref:
            raise ValueError("authorization bases require issuer and audit actor")
        _actor(self.issued_by)

    @property
    def basis_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.basis_id),
                "kind": self.kind.value,
                "plan": str(self.plan_id),
                "plan_version": self.plan_version,
                "plan_hash": self.plan_hash,
                "account": str(self.account_id),
                "instrument": self.instrument,
                "strategy": self.strategy,
                "session": self.session,
                "source": str(self.source_id),
                "source_version": self.source_version,
                "source_hash": self.source_hash,
                "scope": self.scope_snapshot_hash,
                "authorized_action": self.authorized_action.value,
                "authorized_quantity": str(self.authorized_quantity),
                "approval_token": str(self.approval_token) if self.approval_token else None,
                "approval_valid_from": self.approval_valid_from_at.to_dict()["recorded_at"]
                if self.approval_valid_from_at
                else None,
                "approval_valid_until": self.approval_valid_until_at.to_dict()["recorded_at"]
                if self.approval_valid_until_at
                else None,
                "expiry": self.expires_at.to_dict()["recorded_at"],
                "status": self.status.value,
            }
        )

    def active_at(self, now: RecordedAt) -> bool:
        """A Basis never outlives either branch of its source authorization."""
        if not isinstance(now, RecordedAt) or self.status is not BasisStatus.ACTIVE:
            return False
        if not self.created_at.value <= now.value < self.expires_at.value:
            return False
        return self.kind is BasisKind.MANDATE or (
            self.approval_valid_from_at is not None
            and self.approval_valid_until_at is not None
            and self.approval_valid_from_at.value <= now.value < self.approval_valid_until_at.value
        )


class BasisIssuanceRegistry:
    """The authoritative idempotency boundary for Mandate-derived Bases.

    PostgreSQL enforces the same source-plus-plan uniqueness in one transaction.
    A replay returns its original immutable Basis; any alternate request under the
    same source/plan key is rejected rather than widening authority.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._issued: dict[tuple[EntityId, int, EntityId, int], tuple[str, AuthorizationBasis]] = {}

    def issue(
        self,
        request: GateRequest,
        mandate: SimulationAutonomyMandate,
        now: RecordedAt,
    ) -> AuthorizationBasis | None:
        if not isinstance(request, GateRequest) or not isinstance(mandate, SimulationAutonomyMandate):
            raise TypeError("basis issuance requires a typed request and mandate")
        key = (mandate.mandate_id, mandate.version, request.plan_id, request.plan_version)
        fingerprint = canonical_sha256(
            {
                "source_hash": mandate.authorization_hash,
                "plan_hash": request.plan_hash,
                "account": str(request.account_id),
                "instrument": request.instrument,
                "strategy": request.strategy,
                "session": request.session,
                "action": request.action.value,
                "quantity": str(request.quantity),
                "expiry": mandate.expires_at.to_dict()["recorded_at"],
                "scope": mandate.scope.sha256,
            }
        )
        with self._lock:
            existing = self._issued.get(key)
            if existing is not None:
                return existing[1] if existing[0] == fingerprint else None
            basis = AuthorizationBasis(
                EntityId.new("authorization_basis"),
                BasisKind.MANDATE,
                request.plan_id,
                request.plan_version,
                request.plan_hash,
                request.account_id,
                request.instrument,
                request.strategy,
                request.session,
                mandate.mandate_id,
                mandate.version,
                mandate.authorization_hash,
                now,
                mandate.expires_at,
                mandate.scope.sha256,
                request.action,
                request.quantity,
                None,
                None,
                None,
                "system:autonomy-gate",
                "audit://mandate-preflight",
            )
            self._issued[key] = (fingerprint, basis)
            return basis


class PlanApprovalRegistry:
    """Serializes GRANTED -> CONSUMED and emits exactly one approval basis."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._consumed: dict[
            EntityId,
            tuple[
                str,
                PlanApproval,
                AuthorizationBasis,
                tuple[EntityId, int, str, EntityId, str, str, str, ApprovalAction, Decimal],
            ],
        ] = {}

    def consume(
        self,
        approval: PlanApproval,
        now: RecordedAt,
        basis_id: EntityId,
        *,
        plan_id: EntityId,
        plan_version: int,
        plan_hash: str,
        account_id: EntityId,
        instrument: str,
        strategy: str,
        session: str,
        action: ApprovalAction,
        quantity: Decimal,
    ) -> tuple[PlanApproval, AuthorizationBasis | None]:
        with self._lock:
            previous = self._consumed.get(approval.approval_id)
            if previous is not None:
                granted_hash, consumed, basis, command = previous
                if (
                    approval.authorization_hash != granted_hash
                    or (
                        plan_id,
                        plan_version,
                        plan_hash,
                        account_id,
                        instrument,
                        strategy,
                        session,
                        action,
                        quantity,
                    )
                    != command
                    or not approval.scope.permits(account_id, instrument, strategy, session, action, quantity, now)
                ):
                    return approval, None
                return consumed, basis
            current_status = approval.status_at(now)
            if current_status is not PlanApprovalStatus.GRANTED:
                return (
                    replace(approval, status=current_status, version=approval.version + 1)
                    if current_status is PlanApprovalStatus.EXPIRED
                    and approval.status is not PlanApprovalStatus.EXPIRED
                    else approval,
                    None,
                )
            if (
                plan_id != approval.plan_id
                or plan_version != approval.plan_version
                or plan_hash != approval.plan_hash
                or account_id != approval.account_id
                or not approval.scope.permits(account_id, instrument, strategy, session, action, quantity, now)
            ):
                return approval, None
            basis = AuthorizationBasis(
                basis_id,
                BasisKind.PLAN_APPROVAL,
                approval.plan_id,
                approval.plan_version,
                approval.plan_hash,
                approval.account_id,
                instrument,
                strategy,
                session,
                approval.approval_id,
                approval.version,
                approval.authorization_hash,
                now,
                min((approval.expires_at, approval.scope.valid_until_at), key=lambda at: at.value),
                approval.scope.scope_hash,
                action,
                quantity,
                approval.approval_token,
                approval.scope.valid_from_at,
                approval.scope.valid_until_at,
                "system:autonomy-gate",
                "audit://plan-approval-consume",
            )
            consumed = replace(
                approval,
                status=PlanApprovalStatus.CONSUMED,
                consumer_basis_id=basis_id,
                consumed_at=now,
                version=approval.version + 1,
                decided_at=approval.decided_at or now,
                decided_by=approval.decided_by or "user:authorized",
            )
            self._consumed[approval.approval_id] = (
                approval.authorization_hash,
                consumed,
                basis,
                (plan_id, plan_version, plan_hash, account_id, instrument, strategy, session, action, quantity),
            )
            return consumed, basis


@dataclass(frozen=True, slots=True)
class GateRequest:
    plan_id: EntityId
    plan_version: int
    plan_hash: str
    account_id: EntityId
    instrument: str
    strategy: str
    session: str
    action: ApprovalAction
    quantity: Decimal
    execution_origin: ExecutionOrigin
    snapshot_hash: str
    snapshot_expires_at: RecordedAt
    run_versions_hash: str

    def __post_init__(self) -> None:
        _positive_version(self.plan_version)
        _sha(self.plan_hash)
        _sha(self.snapshot_hash)
        _sha(self.run_versions_hash)
        if (
            not isinstance(self.execution_origin, ExecutionOrigin)
            or not isinstance(self.action, ApprovalAction)
            or not all(isinstance(value, EntityId) for value in (self.plan_id, self.account_id))
        ):
            raise TypeError("gate requests require typed origin and identifiers")
        if not all(_scope_text(value) for value in (self.instrument, self.strategy, self.session)):
            raise ValueError("gate requests require an exact execution scope")
        if not isinstance(self.snapshot_expires_at, RecordedAt):
            raise TypeError("gate requests require a snapshot expiry")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("gate requests require a positive finite Decimal quantity")


@dataclass(frozen=True, slots=True)
class PreflightResult:
    outcome: PreflightOutcome
    basis: AuthorizationBasis | None = None
    reason: str = ""


class AutonomyGate:
    """Two-phase fail-closed validator; only final PERMIT creates a receipt."""

    @staticmethod
    def preflight(
        request: GateRequest,
        mandate: SimulationAutonomyMandate | None,
        binding: AutonomyModeBinding | None,
        *,
        qualified: bool,
        health_permits: bool,
        now: RecordedAt,
        approval_allowed: bool,
        basis_registry: BasisIssuanceRegistry,
    ) -> PreflightResult:
        if request.execution_origin is ExecutionOrigin.MANUAL_TEST:
            return PreflightResult(
                PreflightOutcome.ESCALATE if approval_allowed else PreflightOutcome.REJECT,
                reason="MANUAL_REQUIRES_APPROVAL",
            )
        effective = EffectiveAutonomy.evaluate(
            mandate, binding, qualified=qualified, health_permits=health_permits, now=now
        )
        if not effective.permitted:
            return PreflightResult(
                PreflightOutcome.PROTECT_ONLY
                if effective.reason in {"HEALTH_BLOCKED", "MANDATE_PROTECT_ONLY", "MODE_PAUSED"}
                else PreflightOutcome.REJECT,
                reason=effective.reason,
            )
        assert mandate is not None
        if (
            binding is None
            or binding.simulation_account_id != mandate.scope.simulation_account_id
            or binding.simulation_account_id != request.account_id
            or binding.scope_snapshot_hash != mandate.scope.sha256
        ):
            return PreflightResult(PreflightOutcome.REJECT, reason="MANDATE_BINDING_MISMATCH")
        if not mandate.scope.matches(
            request.account_id,
            request.instrument,
            request.strategy,
            request.session,
            request.action,
            request.quantity,
        ):
            return PreflightResult(
                PreflightOutcome.ESCALATE if approval_allowed else PreflightOutcome.REJECT, reason="SCOPE_MISMATCH"
            )
        if not isinstance(basis_registry, BasisIssuanceRegistry):
            raise TypeError("preflight requires the authoritative Basis issuance registry")
        basis = basis_registry.issue(request, mandate, now)
        if basis is None:
            return PreflightResult(PreflightOutcome.REJECT, reason="BASIS_ISSUANCE_CONFLICT")
        return PreflightResult(PreflightOutcome.AUTHORIZED, basis, "MANDATE_AUTHORIZED")

    @staticmethod
    def final_gate(
        request: GateRequest,
        basis: AuthorizationBasis,
        *,
        mandate: SimulationAutonomyMandate | None,
        approval: PlanApproval | None,
        reservation: object,
        binding: AutonomyModeBinding | None,
        qualified: bool,
        health_permits: bool,
        now: RecordedAt,
        issuance_registry: ReceiptIssuanceRegistry,
        risk_ledger: object,
    ) -> FinalGateResult:
        """Revalidate every mutable external fact after reservation, before receipt."""
        from futures_agent_os.portfolio_risk import ReservationSourceKind, RiskBudgetLedger, RiskBudgetReservation

        if request.execution_origin is ExecutionOrigin.MANUAL_TEST and not health_permits:
            return FinalGateResult(FinalGateOutcome.REJECT, reason="HEALTH_BLOCKED")
        if request.snapshot_expires_at.value <= now.value:
            return FinalGateResult(FinalGateOutcome.REJECT, reason="SNAPSHOT_STALE")
        if (
            not isinstance(reservation, RiskBudgetReservation)
            or not isinstance(risk_ledger, RiskBudgetLedger)
            or risk_ledger.reservation(reservation.reservation_id) != reservation
            or not reservation.active_at(now)
        ):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="STALE_AUTHORIZATION_OR_RESERVATION")
        if not basis.active_at(now):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="BASIS_INACTIVE")
        if (
            basis.plan_id,
            basis.plan_version,
            basis.plan_hash,
            basis.account_id,
            basis.instrument,
            basis.strategy,
            basis.session,
        ) != (
            request.plan_id,
            request.plan_version,
            request.plan_hash,
            request.account_id,
            request.instrument,
            request.strategy,
            request.session,
        ):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="BASIS_PLAN_MISMATCH")
        if (basis.authorized_action, basis.authorized_quantity) != (request.action, request.quantity):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="BASIS_ACTION_QUANTITY_MISMATCH")
        if (
            reservation.plan_id,
            reservation.plan_version,
            reservation.plan_hash,
            reservation.account_id,
            reservation.instrument,
            reservation.strategy,
            reservation.session,
            reservation.authorization_basis_id,
            reservation.authorization_basis_hash,
            reservation.action.value,
            reservation.quantity,
        ) != (
            request.plan_id,
            request.plan_version,
            request.plan_hash,
            request.account_id,
            request.instrument,
            request.strategy,
            request.session,
            basis.basis_id,
            basis.basis_hash,
            request.action.value,
            request.quantity,
        ):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="RESERVATION_BINDING_MISMATCH")
        expected_source_kind = (
            ReservationSourceKind.MANDATE if basis.kind is BasisKind.MANDATE else ReservationSourceKind.PLAN_APPROVAL
        )
        if (reservation.source_kind, reservation.source_ref, reservation.source_hash) != (
            expected_source_kind,
            basis.source_id,
            basis.source_hash,
        ):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="RESERVATION_SOURCE_MISMATCH")
        if request.execution_origin is ExecutionOrigin.AUTONOMOUS_AGENT and basis.kind is not BasisKind.MANDATE:
            return FinalGateResult(FinalGateOutcome.REJECT, reason="ORIGIN_BASIS_MISMATCH")
        if request.execution_origin is ExecutionOrigin.MANUAL_TEST and basis.kind is not BasisKind.PLAN_APPROVAL:
            return FinalGateResult(FinalGateOutcome.REJECT, reason="ORIGIN_BASIS_MISMATCH")
        if basis.kind is BasisKind.MANDATE:
            if (
                mandate is None
                or not mandate.is_active_at(now)
                or (basis.source_id, basis.source_version, basis.source_hash)
                != (mandate.mandate_id, mandate.version, mandate.authorization_hash)
                or not mandate.scope.matches(
                    request.account_id,
                    request.instrument,
                    request.strategy,
                    request.session,
                    request.action,
                    request.quantity,
                )
            ):
                return FinalGateResult(FinalGateOutcome.REJECT, reason="MANDATE_SOURCE_INACTIVE")
        elif (
            approval is None
            or approval.status is not PlanApprovalStatus.CONSUMED
            or (
                basis.source_id,
                basis.plan_id,
                basis.plan_version,
                basis.plan_hash,
                basis.account_id,
            )
            != (
                approval.approval_id,
                approval.plan_id,
                approval.plan_version,
                approval.plan_hash,
                approval.account_id,
            )
            or basis.source_version != approval.version - 1
            or basis.source_hash != approval.granted_authorization_hash
            or basis.scope_snapshot_hash != approval.scope.scope_hash
            or basis.approval_token != approval.approval_token
            or (basis.approval_valid_from_at, basis.approval_valid_until_at)
            != (approval.scope.valid_from_at, approval.scope.valid_until_at)
            or not approval.scope.permits(
                request.account_id,
                request.instrument,
                request.strategy,
                request.session,
                request.action,
                request.quantity,
                now,
            )
        ):
            return FinalGateResult(FinalGateOutcome.REJECT, reason="APPROVAL_SOURCE_INACTIVE")
        mode_binding_id: EntityId | None = None
        mode_binding_version: int | None = None
        mode_binding_hash: str | None = None
        if request.execution_origin is ExecutionOrigin.AUTONOMOUS_AGENT:
            if mandate is None or not mandate.is_active_at(now):
                return FinalGateResult(FinalGateOutcome.REJECT, reason="MANDATE_INACTIVE")
            if (
                binding is None
                or not binding.is_active_at(now)
                or binding.mode is not AutonomyMode.AUTONOMOUS_SIMULATION
            ):
                return FinalGateResult(FinalGateOutcome.REJECT, reason="MODE_INACTIVE")
            if not qualified or not health_permits:
                return FinalGateResult(
                    FinalGateOutcome.PROTECT_ONLY if not health_permits else FinalGateOutcome.REJECT,
                    reason="HEALTH_BLOCKED" if not health_permits else "RUN_UNQUALIFIED",
                )
            if binding.run_versions_hash != request.run_versions_hash:
                return FinalGateResult(FinalGateOutcome.REJECT, reason="RUN_VERSION_DRIFT")
            assert binding is not None
            if (
                (binding.mandate_id, binding.mandate_version) != (mandate.mandate_id, mandate.version)
                or binding.simulation_account_id != mandate.scope.simulation_account_id
                or binding.simulation_account_id != request.account_id
                or binding.scope_snapshot_hash != mandate.scope.sha256
            ):
                return FinalGateResult(FinalGateOutcome.REJECT, reason="MANDATE_BINDING_MISMATCH")
            if basis.kind is BasisKind.MANDATE and (basis.source_id, basis.source_version) != (
                mandate.mandate_id,
                mandate.version,
            ):
                return FinalGateResult(FinalGateOutcome.REJECT, reason="BASIS_SOURCE_MISMATCH")
            mode_binding_id = binding.binding_id
            mode_binding_version = binding.version
            mode_binding_hash = binding.binding_hash
        if not isinstance(issuance_registry, ReceiptIssuanceRegistry):
            raise TypeError("final gate requires the receipt issuance registry")
        expiry = min(
            (
                basis.expires_at,
                reservation.expires_at,
                request.snapshot_expires_at,
                binding.expires_at if binding else basis.expires_at,
            ),
            key=lambda at: at.value,
        )
        fingerprint = canonical_sha256(
            {
                "basis": basis.basis_hash,
                "plan": request.plan_hash,
                "account": str(request.account_id),
                "action": request.action.value,
                "quantity": str(request.quantity),
                "reservation": reservation.reservation_hash,
                "snapshot": request.snapshot_hash,
                "runs": request.run_versions_hash,
                "mode": mode_binding_hash,
                "expiry": expiry.to_dict()["recorded_at"],
            }
        )
        receipt = issuance_registry.issue(
            basis.basis_id,
            fingerprint,
            lambda: AutonomyGateReceipt(
                EntityId.new("autonomy_gate_receipt"),
                request.plan_id,
                request.plan_version,
                request.plan_hash,
                request.account_id,
                request.instrument,
                request.strategy,
                request.session,
                request.action,
                request.quantity,
                basis.basis_id,
                basis.basis_hash,
                basis.source_id,
                basis.source_version,
                basis.source_hash,
                request.execution_origin,
                request.snapshot_hash,
                request.run_versions_hash,
                reservation.reservation_id,
                reservation.reservation_hash,
                expiry,
                now,
                EntityId.new("receipt_nonce"),
                issuance_registry.registry_id,
                mode_binding_id,
                mode_binding_version,
                mode_binding_hash,
                approval.decided_by if request.execution_origin is ExecutionOrigin.MANUAL_TEST and approval else None,
                "environment://simulation-only",
            ),
        )
        if receipt is None:
            return FinalGateResult(FinalGateOutcome.REJECT, reason="BASIS_ALREADY_ISSUED")
        return FinalGateResult(FinalGateOutcome.PERMIT, receipt, "PERMITTED")


@dataclass(frozen=True, slots=True)
class AutonomyGateReceipt:
    receipt_id: EntityId
    plan_id: EntityId
    plan_version: int
    plan_hash: str
    account_id: EntityId
    instrument: str
    strategy: str
    session: str
    action: ApprovalAction
    quantity: Decimal
    basis_id: EntityId
    basis_hash: str
    source_id: EntityId
    source_version: int
    source_hash: str
    execution_origin: ExecutionOrigin
    snapshot_hash: str
    run_versions_hash: str
    reservation_id: EntityId
    reservation_hash: str
    expires_at: RecordedAt
    issued_at: RecordedAt
    nonce: EntityId
    issuance_registry_id: EntityId
    mode_binding_id: EntityId | None = None
    mode_binding_version: int | None = None
    mode_binding_hash: str | None = None
    manual_actor_ref: str | None = None
    environment_policy_ref: str = ""

    def __post_init__(self) -> None:
        _positive_version(self.plan_version)
        _positive_version(self.source_version)
        for digest in (
            self.plan_hash,
            self.basis_hash,
            self.source_hash,
            self.snapshot_hash,
            self.run_versions_hash,
            self.reservation_hash,
        ):
            _sha(digest)
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.receipt_id,
                self.plan_id,
                self.account_id,
                self.basis_id,
                self.source_id,
                self.reservation_id,
                self.nonce,
                self.issuance_registry_id,
            )
        ):
            raise TypeError("receipts require typed identifiers")
        if (
            not isinstance(self.execution_origin, ExecutionOrigin)
            or not isinstance(self.expires_at, RecordedAt)
            or not isinstance(self.issued_at, RecordedAt)
        ):
            raise TypeError("receipts require typed origin and timestamps")
        if not all(_scope_text(value) for value in (self.instrument, self.strategy, self.session)):
            raise ValueError("receipts require an exact execution scope")
        if (
            self.expires_at.value <= self.issued_at.value
            or not isinstance(self.action, ApprovalAction)
            or not isinstance(self.quantity, Decimal)
            or not self.quantity.is_finite()
            or self.quantity <= 0
            or not self.environment_policy_ref
        ):
            raise ValueError("receipts require action, environment policy, and future expiry")
        if self.execution_origin is ExecutionOrigin.AUTONOMOUS_AGENT:
            if self.mode_binding_id is None or self.mode_binding_version is None or self.mode_binding_hash is None:
                raise ValueError("autonomous receipts bind the exact active mode binding")
            _positive_version(self.mode_binding_version)
            _sha(self.mode_binding_hash)
            if self.manual_actor_ref is not None:
                raise ValueError("autonomous receipts cannot name a manual actor")
        elif any(
            value is not None for value in (self.mode_binding_id, self.mode_binding_version, self.mode_binding_hash)
        ):
            raise ValueError("manual-test receipts do not bind autonomy mode")
        elif not self.manual_actor_ref:
            raise ValueError("manual-test receipts require an actor")
        elif self.execution_origin is ExecutionOrigin.MANUAL_TEST:
            _actor(self.manual_actor_ref)

    @property
    def receipt_hash(self) -> str:
        return canonical_sha256(
            {
                "id": str(self.receipt_id),
                "plan": str(self.plan_id),
                "plan_version": self.plan_version,
                "plan_hash": self.plan_hash,
                "basis": self.basis_hash,
                "instrument": self.instrument,
                "strategy": self.strategy,
                "session": self.session,
                "action": self.action.value,
                "quantity": str(self.quantity),
                "source": self.source_hash,
                "origin": self.execution_origin.value,
                "snapshot": self.snapshot_hash,
                "runs": self.run_versions_hash,
                "reservation": self.reservation_hash,
                "expiry": self.expires_at.to_dict()["recorded_at"],
                "nonce": str(self.nonce),
                "mode": self.mode_binding_hash,
            }
        )


class ReceiptIssuanceRegistry:
    """The only in-memory issuance authority: one immutable receipt per Basis."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.registry_id = EntityId.new("receipt_issuance_registry")
        self._issued: dict[EntityId, tuple[str, AutonomyGateReceipt]] = {}
        self._invalidated_bases: set[EntityId] = set()
        self._consumed_bases: set[EntityId] = set()

    def issue(self, basis_id: EntityId, fingerprint: str, factory: object) -> AutonomyGateReceipt | None:
        if not isinstance(basis_id, EntityId):
            raise TypeError("receipt issuance requires a typed Basis id")
        _sha(fingerprint)
        if not callable(factory):
            raise TypeError("receipt issuance requires an internal receipt factory")
        with self._lock:
            if basis_id in self._invalidated_bases:
                return None
            existing = self._issued.get(basis_id)
            if existing is not None:
                return existing[1] if existing[0] == fingerprint else None
            receipt = factory()
            if (
                not isinstance(receipt, AutonomyGateReceipt)
                or receipt.basis_id != basis_id
                or receipt.issuance_registry_id != self.registry_id
            ):
                raise ValueError("receipt factory must bind the supplied Basis")
            self._issued[basis_id] = (fingerprint, receipt)
            return receipt

    def contains(self, receipt: AutonomyGateReceipt) -> bool:
        with self._lock:
            issued = self._issued.get(receipt.basis_id)
            return (
                issued is not None
                and receipt.basis_id not in self._invalidated_bases
                and receipt.issuance_registry_id == self.registry_id
                and issued[1] == receipt
            )

    def invalidate_basis(self, basis_id: EntityId) -> AutonomyGateReceipt | None:
        """Invalidate an unconsumed receipt before releasing its reservation."""
        if not isinstance(basis_id, EntityId):
            raise TypeError("receipt invalidation requires a typed Basis id")
        with self._lock:
            self._invalidated_bases.add(basis_id)
            issued = self._issued.get(basis_id)
            if issued is None or basis_id in self._consumed_bases:
                return None
            return issued[1]

    def mark_consumed(self, receipt: AutonomyGateReceipt) -> bool:
        """Globally serialize a receipt consumption against a concurrent pause."""
        if not isinstance(receipt, AutonomyGateReceipt):
            raise TypeError("receipt consumption requires a typed receipt")
        with self._lock:
            issued = self._issued.get(receipt.basis_id)
            if (
                issued is None
                or receipt.basis_id in self._invalidated_bases
                or receipt.basis_id in self._consumed_bases
                or receipt.issuance_registry_id != self.registry_id
                or issued[1] != receipt
            ):
                return False
            self._consumed_bases.add(receipt.basis_id)
            return True


@dataclass(frozen=True, slots=True)
class BindingArtifactInvalidation:
    binding: AutonomyModeBinding
    stale_bases: tuple[AuthorizationBasis, ...]
    invalidated_receipts: tuple[AutonomyGateReceipt, ...]
    released_reservations: tuple[RiskBudgetReservation, ...]

    @property
    def released_reservation_ids(self) -> tuple[EntityId, ...]:
        return tuple(reservation.reservation_id for reservation in self.released_reservations)


class BindingArtifactCoordinator:
    """Explicit aggregate operation for invalidating artifacts when a Binding ends."""

    def __init__(self, issuance_registry: ReceiptIssuanceRegistry, risk_ledger: object) -> None:
        from futures_agent_os.portfolio_risk import RiskBudgetLedger

        if not isinstance(issuance_registry, ReceiptIssuanceRegistry) or not isinstance(risk_ledger, RiskBudgetLedger):
            raise TypeError("binding artifact coordination requires issuance and risk registries")
        self._issuance_registry = issuance_registry
        self._risk_ledger = risk_ledger
        self._tracked: dict[EntityId, tuple[AutonomyModeBinding, AuthorizationBasis, EntityId]] = {}
        self._basis_states: dict[EntityId, AuthorizationBasis] = {}
        self._lock = RLock()

    def track(self, binding: AutonomyModeBinding, basis: AuthorizationBasis, reservation_id: EntityId) -> None:
        if (
            not isinstance(binding, AutonomyModeBinding)
            or not isinstance(basis, AuthorizationBasis)
            or not isinstance(reservation_id, EntityId)
        ):
            raise TypeError("tracked artifacts require typed binding, basis, and reservation")
        with self._lock:
            self._tracked[basis.basis_id] = (binding, basis, reservation_id)
            self._basis_states[basis.basis_id] = basis

    def basis_state(self, basis_id: EntityId) -> AuthorizationBasis | None:
        """Expose the current coordinated Basis state for final/consume revalidation."""
        if not isinstance(basis_id, EntityId):
            raise TypeError("basis state requires a typed Basis id")
        with self._lock:
            return self._basis_states.get(basis_id)

    def expire(self, binding: AutonomyModeBinding, now: RecordedAt) -> BindingArtifactInvalidation:
        return self._end(binding.expire(now), now)

    def supersede(self, binding: AutonomyModeBinding, now: RecordedAt) -> BindingArtifactInvalidation:
        return self._end(binding.supersede(now), now)

    def pause(self, binding: AutonomyModeBinding, now: RecordedAt) -> BindingArtifactInvalidation:
        if binding.mode is not AutonomyMode.PAUSED:
            raise ValueError("artifact pause requires a paused binding")
        return self._end(binding, now)

    def _end(self, ended_binding: AutonomyModeBinding, now: RecordedAt) -> BindingArtifactInvalidation:
        from futures_agent_os.portfolio_risk import ReservationStatus

        stale: list[AuthorizationBasis] = []
        invalidated_receipts: list[AutonomyGateReceipt] = []
        released: list[RiskBudgetReservation] = []
        with self._lock:
            for basis_id, (binding, basis, reservation_id) in tuple(self._tracked.items()):
                if binding.binding_id != ended_binding.binding_id:
                    continue
                invalidated_receipt = self._issuance_registry.invalidate_basis(basis_id)
                if invalidated_receipt is not None:
                    invalidated_receipts.append(invalidated_receipt)
                if basis.status is BasisStatus.ACTIVE:
                    stale_basis = replace(basis, status=BasisStatus.STALE)
                    stale.append(stale_basis)
                    self._basis_states[basis_id] = stale_basis
                prior_reservation = self._risk_ledger.reservation(reservation_id)
                released_result = self._risk_ledger.release(reservation_id)
                if (
                    prior_reservation is not None
                    and prior_reservation.status is ReservationStatus.HELD
                    and released_result is not None
                    and released_result.status is ReservationStatus.RELEASED
                ):
                    released.append(released_result)
                del self._tracked[basis_id]
        return BindingArtifactInvalidation(ended_binding, tuple(stale), tuple(invalidated_receipts), tuple(released))


@dataclass(frozen=True, slots=True)
class FinalGateResult:
    outcome: FinalGateOutcome
    receipt: AutonomyGateReceipt | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.outcome is FinalGateOutcome.PERMIT) != (self.receipt is not None):
            raise ValueError("only PERMIT returns a receipt")


class ReceiptRegistry:
    """Reference model for the database's receipt nonce unique constraint."""

    def __init__(self, issuance_registry: ReceiptIssuanceRegistry) -> None:
        if not isinstance(issuance_registry, ReceiptIssuanceRegistry):
            raise TypeError("receipt consumption requires the issuance registry")
        self._lock = RLock()
        self._issuance_registry = issuance_registry
        self._used: set[EntityId] = set()
        self._used_bases: set[EntityId] = set()

    def consume(
        self,
        receipt: AutonomyGateReceipt,
        now: RecordedAt,
        *,
        request: GateRequest,
        basis: AuthorizationBasis,
        mandate: SimulationAutonomyMandate | None,
        approval: PlanApproval | None,
        reservation: object,
        binding: AutonomyModeBinding | None,
        qualified: bool,
        health_permits: bool,
    ) -> bool:
        with self._lock:
            from futures_agent_os.portfolio_risk import ReservationSourceKind, RiskBudgetReservation

            if (
                receipt.nonce in self._used
                or receipt.basis_id in self._used_bases
                or now.value >= receipt.expires_at.value
                or now.value >= request.snapshot_expires_at.value
                or not self._issuance_registry.contains(receipt)
            ):
                return False
            if not isinstance(reservation, RiskBudgetReservation) or not reservation.active_at(now):
                return False
            if (
                receipt.plan_id,
                receipt.plan_version,
                receipt.plan_hash,
                receipt.account_id,
                receipt.instrument,
                receipt.strategy,
                receipt.session,
                receipt.action,
                receipt.quantity,
                receipt.execution_origin,
                receipt.basis_id,
                receipt.basis_hash,
                receipt.snapshot_hash,
                receipt.run_versions_hash,
                receipt.reservation_id,
                receipt.reservation_hash,
            ) != (
                request.plan_id,
                request.plan_version,
                request.plan_hash,
                request.account_id,
                request.instrument,
                request.strategy,
                request.session,
                request.action,
                request.quantity,
                request.execution_origin,
                basis.basis_id,
                basis.basis_hash,
                request.snapshot_hash,
                request.run_versions_hash,
                reservation.reservation_id,
                reservation.reservation_hash,
            ):
                return False
            if not basis.active_at(now):
                return False
            if (basis.authorized_action, basis.authorized_quantity) != (request.action, request.quantity):
                return False
            expected_source_kind = (
                ReservationSourceKind.MANDATE
                if basis.kind is BasisKind.MANDATE
                else ReservationSourceKind.PLAN_APPROVAL
            )
            if (reservation.source_kind, reservation.source_ref, reservation.source_hash) != (
                expected_source_kind,
                basis.source_id,
                basis.source_hash,
            ):
                return False
            if (reservation.action.value, reservation.quantity) != (request.action.value, request.quantity):
                return False
            if receipt.execution_origin is ExecutionOrigin.AUTONOMOUS_AGENT:
                if (
                    basis.kind is not BasisKind.MANDATE
                    or mandate is None
                    or not mandate.is_active_at(now)
                    or binding is None
                    or not binding.is_active_at(now)
                    or binding.mode is not AutonomyMode.AUTONOMOUS_SIMULATION
                    or not qualified
                    or not health_permits
                    or (receipt.source_id, receipt.source_version, receipt.source_hash)
                    != (mandate.mandate_id, mandate.version, mandate.authorization_hash)
                    or not mandate.scope.matches(
                        request.account_id,
                        request.instrument,
                        request.strategy,
                        request.session,
                        request.action,
                        request.quantity,
                    )
                    or binding.simulation_account_id != mandate.scope.simulation_account_id
                    or binding.simulation_account_id != request.account_id
                    or binding.scope_snapshot_hash != mandate.scope.sha256
                    or (receipt.mode_binding_id, receipt.mode_binding_version, receipt.mode_binding_hash)
                    != (binding.binding_id, binding.version, binding.binding_hash)
                ):
                    return False
            elif (
                basis.kind is not BasisKind.PLAN_APPROVAL
                or approval is None
                or approval.status is not PlanApprovalStatus.CONSUMED
                or receipt.manual_actor_ref is None
                or receipt.manual_actor_ref != approval.decided_by
                or not health_permits
                or (receipt.source_id, receipt.source_version) != (approval.approval_id, approval.version - 1)
                or receipt.source_hash != approval.granted_authorization_hash
                or basis.approval_token != approval.approval_token
                or (basis.approval_valid_from_at, basis.approval_valid_until_at)
                != (approval.scope.valid_from_at, approval.scope.valid_until_at)
                or not approval.scope.permits(
                    request.account_id,
                    request.instrument,
                    request.strategy,
                    request.session,
                    request.action,
                    request.quantity,
                    now,
                )
            ):
                return False
            if not self._issuance_registry.mark_consumed(receipt):
                return False
            self._used.add(receipt.nonce)
            self._used_bases.add(receipt.basis_id)
            return True
