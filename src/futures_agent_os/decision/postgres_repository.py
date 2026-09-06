"""Narrow PostgreSQL command client for durable V0-014 authorization facts.

The runtime role has no direct table mutation rights.  Every write below is a
typed call to an owner-controlled SECURITY DEFINER function; callers still
own the surrounding transaction so retries remain explicit and auditable.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    basis_id: UUID | None
    consumed: bool


@dataclass(frozen=True, slots=True)
class RecoveredSubmission:
    """Immutable projection used when a process retries a completed submit."""

    plan_id: UUID
    plan_version: int
    plan_sha256: str
    basis_id: UUID
    reservation_id: UUID
    receipt_id: UUID
    order_payload: dict[str, object]
    ledger_payload: dict[str, object]


class PostgresAutonomyRepository:
    """Only invokes the least-privilege V0-014 PostgreSQL commands."""

    def consume_plan_approval(
        self,
        connection: Connection,
        *,
        approval_id: UUID,
        approval_version: int,
        plan_id: UUID,
        plan_version: int,
        plan_sha256: str,
        account_id: UUID,
        instrument_id: str,
        strategy_id: str,
        session_id: str,
        action: str,
        quantity: Decimal,
        approval_token: UUID,
        approval_hash: str,
        basis_id: UUID,
        basis_sha256: str,
        scope_sha256: str,
        expires_at: datetime,
        now: datetime,
        actor: str,
    ) -> ConsumeResult:
        result = connection.execute(
            text("""SELECT fao.consume_plan_approval(
                :approval,:approval_version,:plan,:plan_version,:plan_hash,:account,:instrument,:strategy,:session,:action,:quantity,:token,
                :approval_hash,:scope_hash,:basis,:basis_hash,:expires,:now,:actor)"""),
            {
                "approval": approval_id,
                "approval_version": approval_version,
                "plan": plan_id,
                "plan_version": plan_version,
                "plan_hash": plan_sha256,
                "account": account_id,
                "instrument": instrument_id,
                "strategy": strategy_id,
                "session": session_id,
                "action": action,
                "quantity": quantity,
                "token": approval_token,
                "approval_hash": approval_hash,
                "scope_hash": scope_sha256,
                "basis": basis_id,
                "basis_hash": basis_sha256,
                "expires": expires_at,
                "now": now,
                "actor": actor,
            },
        ).scalar_one()
        return ConsumeResult(result, result is not None)

    def issue_mandate_basis(
        self,
        connection: Connection,
        *,
        basis_id: UUID,
        mandate_id: UUID,
        mandate_version: int,
        plan_id: UUID,
        plan_version: int,
        plan_sha256: str,
        account_id: UUID,
        instrument_id: str,
        strategy_id: str,
        session_id: str,
        action: str,
        quantity: Decimal,
        mandate_sha256: str,
        scope_sha256: str,
        basis_sha256: str,
        expires_at: datetime,
        now: datetime,
        actor: str,
    ) -> UUID | None:
        return connection.execute(
            text("""SELECT fao.issue_mandate_basis(
                :basis,:mandate,:mandate_version,:plan,:plan_version,:plan_hash,:account,:instrument,:strategy,:session,:action,:quantity,
                :mandate_hash,:scope_hash,:basis_hash,:expires,:now,:actor)"""),
            {
                "basis": basis_id,
                "mandate": mandate_id,
                "mandate_version": mandate_version,
                "plan": plan_id,
                "plan_version": plan_version,
                "plan_hash": plan_sha256,
                "account": account_id,
                "instrument": instrument_id,
                "strategy": strategy_id,
                "session": session_id,
                "action": action,
                "quantity": quantity,
                "mandate_hash": mandate_sha256,
                "scope_hash": scope_sha256,
                "basis_hash": basis_sha256,
                "expires": expires_at,
                "now": now,
                "actor": actor,
            },
        ).scalar_one()

    def consume_autonomy_gate_receipt(
        self, connection: Connection, *, receipt_id: UUID, reservation_id: UUID, now: datetime
    ) -> bool:
        """Consume an issued receipt inside the caller's transaction."""
        return bool(
            connection.execute(
                text("SELECT fao.consume_autonomy_gate_receipt(:receipt,:reservation,:now)"),
                {"receipt": receipt_id, "reservation": reservation_id, "now": now},
            ).scalar_one()
        )

    def consume_risk_budget_reservation(
        self, connection: Connection, *, reservation_id: UUID, receipt_id: UUID, now: datetime
    ) -> bool:
        """Consume a held reservation after its receipt is consumed."""
        return bool(
            connection.execute(
                text("SELECT fao.consume_risk_budget_reservation(:reservation,:receipt,:now)"),
                {"reservation": reservation_id, "receipt": receipt_id, "now": now},
            ).scalar_one()
        )

    def consume_receipt_and_reservation(
        self, connection: Connection, *, receipt_id: UUID, reservation_id: UUID, nonce: UUID, now: datetime
    ) -> bool:
        """Consume both facts in the caller-owned transaction.

        The method never commits or rolls back the connection.  A false
        result leaves the transaction to the caller, which can roll it back
        together with any preceding order-side effects.
        """
        if not self.consume_receipt(connection, receipt_id=receipt_id, nonce=nonce, now=now):
            return False
        return self.consume_risk_budget_reservation(
            connection, reservation_id=reservation_id, receipt_id=receipt_id, now=now
        )

    def append_execution_facts(
        self,
        connection: Connection,
        *,
        order_id: UUID,
        order_payload: dict[str, object],
        ledger_id: UUID,
        ledger_payload: dict[str, object],
        correlation_id: UUID,
        now: datetime,
    ) -> bool:
        """Append order and ledger facts in the caller-owned transaction."""
        facts = ((order_id, "Order", order_payload), (ledger_id, "LedgerEntry", ledger_payload))
        for aggregate_id, aggregate_type, payload in facts:
            if not self.append_execution_fact(
                connection,
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                payload=payload,
                correlation_id=correlation_id,
                now=now,
            ):
                return False
        return True

    def append_execution_fact(
        self,
        connection: Connection,
        *,
        aggregate_id: UUID,
        aggregate_type: str,
        payload: dict[str, object],
        correlation_id: UUID,
        now: datetime,
    ) -> bool:
        """Append one immutable execution fact with aggregate idempotency."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        result = connection.execute(
            text("""INSERT INTO fao.domain_event
                (event_id,aggregate_type,aggregate_id,aggregate_version,event_type,schema_version,correlation_id,idempotency_key,actor_ref,payload,payload_sha256,occurred_at,recorded_at)
                VALUES (:event,:type,:aggregate,1,'CREATED','v2.1',:correlation,:key,'service:execution',CAST(:payload AS jsonb),:hash,:now,:now)
                ON CONFLICT (aggregate_type,aggregate_id,aggregate_version) DO NOTHING"""),
            {
                "event": aggregate_id,
                "type": aggregate_type,
                "aggregate": aggregate_id,
                "correlation": correlation_id,
                "key": str(aggregate_id),
                "payload": canonical,
                "hash": digest,
                "now": now,
            },
        )
        if result.rowcount == 0:
            existing = connection.execute(
                text(
                    "SELECT payload_sha256 FROM fao.domain_event WHERE aggregate_type=:type AND aggregate_id=:aggregate AND aggregate_version=1"
                ),
                {"type": aggregate_type, "aggregate": aggregate_id},
            ).scalar_one_or_none()
            return existing == digest
        return True

    @staticmethod
    def _fact_payload_hash(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def load_completed_submission(
        self,
        connection: Connection,
        *,
        plan_id: UUID,
        plan_version: int,
        plan_sha256: str,
    ) -> RecoveredSubmission | None:
        """Read a completed chain for retry/recovery after a process restart."""
        row = (
            connection.execute(
                text("""
                SELECT b.basis_id, r.reservation_id, x.receipt_id,
                       o.payload AS order_payload, l.payload AS ledger_payload
                  FROM fao.authorization_basis b
                  JOIN fao.risk_budget_reservation r ON r.basis_id=b.basis_id
                  JOIN fao.autonomy_gate_receipt x ON x.basis_id=b.basis_id AND x.reservation_id=r.reservation_id
                  JOIN fao.domain_event o ON o.aggregate_type='Order' AND right(o.payload->>'plan_id',36)=b.plan_id::text
                  JOIN fao.domain_event l ON l.aggregate_type='LedgerEntry' AND right(l.payload->>'plan_id',36)=b.plan_id::text
                 WHERE b.plan_id=:plan AND b.plan_version=:plan_version AND b.plan_sha256=:plan_hash
                   AND r.reservation_status='CONSUMED' AND x.receipt_status='CONSUMED'
                 ORDER BY o.recorded_at DESC
                 LIMIT 1
            """),
                {"plan": plan_id, "plan_version": plan_version, "plan_hash": plan_sha256},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return RecoveredSubmission(
            plan_id=plan_id,
            plan_version=plan_version,
            plan_sha256=plan_sha256,
            basis_id=row["basis_id"],
            reservation_id=row["reservation_id"],
            receipt_id=row["receipt_id"],
            order_payload=dict(row["order_payload"]),
            ledger_payload=dict(row["ledger_payload"]),
        )

    def persist_prepared_chain(
        self,
        connection: Connection,
        *,
        basis: Any,
        reservation: Any,
        receipt: Any,
        constitution_ref: str,
        constitution_version: int,
        constitution_hash: str,
        mandate: Any | None,
        approval: Any | None,
        now: datetime,
    ) -> bool:
        """Persist the prepared Basis → Reservation → Receipt chain atomically."""
        kind = getattr(getattr(basis, "kind"), "value")
        if kind == "MANDATE":
            if mandate is None:
                return False
            issued = self.issue_mandate_basis(
                connection,
                basis_id=basis.basis_id.value,
                mandate_id=mandate.mandate_id.value,
                mandate_version=mandate.version,
                plan_id=basis.plan_id.value,
                plan_version=basis.plan_version,
                plan_sha256=basis.plan_hash,
                account_id=basis.account_id.value,
                instrument_id=basis.instrument,
                strategy_id=basis.strategy,
                session_id=basis.session,
                action=basis.authorized_action.value,
                quantity=basis.authorized_quantity,
                mandate_sha256=mandate.authorization_hash,
                scope_sha256=basis.scope_snapshot_hash,
                basis_sha256=basis.basis_hash,
                expires_at=basis.expires_at.value,
                now=now,
                # The SQL owner function accepts only the service actor for a
                # mandate-derived basis.  The domain candidate's audit label
                # remains in memory; PostgreSQL records the enforcing actor.
                actor="service:autonomy-gate",
            )
            if issued is None:
                return False
        elif kind == "PLAN_APPROVAL":
            if approval is None:
                return False
            consumed = self.consume_plan_approval(
                connection,
                approval_id=approval.approval_id.value,
                approval_version=approval.version - 1,
                plan_id=basis.plan_id.value,
                plan_version=basis.plan_version,
                plan_sha256=basis.plan_hash,
                account_id=basis.account_id.value,
                instrument_id=basis.instrument,
                strategy_id=basis.strategy,
                session_id=basis.session,
                action=basis.authorized_action.value,
                quantity=basis.authorized_quantity,
                approval_token=approval.approval_token.value,
                approval_hash=basis.source_hash,
                basis_id=basis.basis_id.value,
                basis_sha256=basis.basis_hash,
                scope_sha256=basis.scope_snapshot_hash,
                expires_at=basis.expires_at.value,
                now=now,
                # The database binds PlanApproval consumption to the human
                # decision actor; Basis.issued_by is the enforcing service
                # label and is not a valid MANUAL_TEST actor.
                actor=approval.decided_by or basis.issued_by,
            )
            if not consumed.consumed:
                return False
        else:
            return False
        if not self.reserve_risk_budget(
            connection,
            reservation_id=reservation.reservation_id.value,
            reservation_sha256=reservation.reservation_hash,
            account_id=reservation.account_id.value,
            plan_id=reservation.plan_id.value,
            plan_version=reservation.plan_version,
            plan_sha256=reservation.plan_hash,
            instrument_id=reservation.instrument,
            strategy_id=reservation.strategy,
            session_id=reservation.session,
            basis_id=reservation.authorization_basis_id.value,
            basis_sha256=reservation.authorization_basis_hash,
            constitution_ref=constitution_ref,
            constitution_version=constitution_version,
            constitution_sha256=constitution_hash,
            risk_dimensions=dict(reservation.risk_dimensions),
            quantity=reservation.quantity,
            worst_case_loss=reservation.worst_case_loss,
            margin=reservation.margin,
            expires_at=reservation.expires_at.value,
            now=now,
        ):
            return False
        issued_receipt = self.issue_receipt(
            connection,
            receipt_id=receipt.receipt_id.value,
            nonce=receipt.nonce.value,
            basis_id=receipt.basis_id.value,
            basis_sha256=receipt.basis_hash,
            reservation_id=receipt.reservation_id.value,
            reservation_sha256=receipt.reservation_hash,
            plan_id=receipt.plan_id.value,
            plan_version=receipt.plan_version,
            plan_sha256=receipt.plan_hash,
            account_id=receipt.account_id.value,
            instrument_id=receipt.instrument,
            strategy_id=receipt.strategy,
            session_id=receipt.session,
            action=receipt.action.value,
            execution_origin=receipt.execution_origin.value,
            source_sha256=receipt.source_hash,
            scope_sha256=basis.scope_snapshot_hash,
            snapshot_refs={
                "as_of": receipt.issued_at.to_dict()["recorded_at"],
                "expires_at": receipt.expires_at.to_dict()["recorded_at"],
                "snapshot_hash": receipt.snapshot_hash,
            },
            snapshot_sha256=receipt.snapshot_hash,
            run_versions_sha256=receipt.run_versions_hash,
            mode_binding_id=receipt.mode_binding_id.value if receipt.mode_binding_id else None,
            mode_binding_version=receipt.mode_binding_version,
            mode_binding_sha256=receipt.mode_binding_hash,
            constitution_ref=constitution_ref,
            constitution_version=constitution_version,
            constitution_sha256=constitution_hash,
            expires_at=receipt.expires_at.value,
            now=now,
            actor=receipt.manual_actor_ref or "service:runtime",
            manual_actor_ref=receipt.manual_actor_ref,
            environment_policy_ref=receipt.environment_policy_ref,
        )
        return issued_receipt == receipt.receipt_id.value

    def persist_authorization_chain(self, connection: Connection, **kwargs: Any) -> bool:
        """Persist Basis → Reservation → Receipt behind a savepoint.

        The caller still owns the outer transaction.  The savepoint prevents a
        rejected attempt from leaving an approval, basis, or held reservation
        behind when the caller decides to continue using that transaction.
        """
        nested = connection.begin_nested()
        try:
            if not self.persist_prepared_chain(connection, **kwargs):
                nested.rollback()
                return False
            nested.commit()
            return True
        except SQLAlchemyError:
            nested.rollback()
            return False

    def persist_submission_chain(
        self,
        connection: Connection,
        *,
        basis: Any,
        reservation: Any,
        receipt: Any,
        order_id: UUID,
        order_payload: dict[str, object],
        ledger_id: UUID,
        ledger_payload: dict[str, object],
        constitution_ref: str,
        constitution_version: int,
        constitution_hash: str,
        mandate: Any | None,
        approval: Any | None,
        correlation_id: UUID,
        now: datetime,
    ) -> bool:
        """Persist and consume the complete golden chain in one transaction.

        A retry of an already completed chain is accepted only when the stored
        immutable facts are present; no second Order or LedgerEntry is created.
        All writes happen under one caller-owned transaction and one savepoint.
        """
        existing = self.load_completed_submission(
            connection,
            plan_id=basis.plan_id.value,
            plan_version=basis.plan_version,
            plan_sha256=basis.plan_hash,
        )
        if existing is not None:
            return (
                existing.basis_id == basis.basis_id.value
                and existing.reservation_id == reservation.reservation_id.value
                and existing.receipt_id == receipt.receipt_id.value
                and existing.order_payload == order_payload
                and existing.ledger_payload == ledger_payload
            )
        nested = connection.begin_nested()
        try:
            if not self.persist_prepared_chain(
                connection,
                basis=basis,
                reservation=reservation,
                receipt=receipt,
                constitution_ref=constitution_ref,
                constitution_version=constitution_version,
                constitution_hash=constitution_hash,
                mandate=mandate,
                approval=approval,
                now=now,
            ):
                nested.rollback()
                return False
            if not self.consume_receipt_and_reservation(
                connection,
                receipt_id=receipt.receipt_id.value,
                reservation_id=reservation.reservation_id.value,
                nonce=receipt.nonce.value,
                now=now,
            ):
                nested.rollback()
                return False
            if not self.append_execution_facts(
                connection,
                order_id=order_id,
                order_payload=order_payload,
                ledger_id=ledger_id,
                ledger_payload=ledger_payload,
                correlation_id=correlation_id,
                now=now,
            ):
                nested.rollback()
                return False
            nested.commit()
            return True
        except SQLAlchemyError:
            nested.rollback()
            return False

    def reserve_risk_budget(
        self,
        connection: Connection,
        *,
        reservation_id: UUID,
        reservation_sha256: str,
        account_id: UUID,
        plan_id: UUID,
        plan_version: int,
        plan_sha256: str,
        instrument_id: str,
        strategy_id: str,
        session_id: str,
        basis_id: UUID,
        basis_sha256: str,
        constitution_ref: str,
        constitution_version: int,
        constitution_sha256: str,
        risk_dimensions: dict[str, str],
        quantity: Decimal,
        worst_case_loss: Decimal,
        margin: Decimal,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> bool:
        """Atomically locks the aggregate authority and persists all dimensions."""
        if any(
            not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
            for key, value in risk_dimensions.items()
        ):
            raise ValueError("risk_dimensions must be a non-empty-string-to-non-empty-string map")
        canonical_dimensions = dict(sorted(risk_dimensions.items()))
        return bool(
            connection.execute(
                text("""SELECT fao.reserve_risk_budget(
                    :reservation,:reservation_hash,:account,:plan,:plan_version,:plan_hash,:instrument,:strategy,:session,:basis,:basis_hash,
                    :constitution_ref,:constitution_version,:constitution_hash,CAST(:dimensions AS jsonb),
                    :quantity,:loss,:margin,:expires,:now)"""),
                {
                    "reservation": reservation_id,
                    "reservation_hash": reservation_sha256,
                    "account": account_id,
                    "plan": plan_id,
                    "plan_version": plan_version,
                    "plan_hash": plan_sha256,
                    "instrument": instrument_id,
                    "strategy": strategy_id,
                    "session": session_id,
                    "basis": basis_id,
                    "basis_hash": basis_sha256,
                    "constitution_ref": constitution_ref,
                    "constitution_version": constitution_version,
                    "constitution_hash": constitution_sha256,
                    "dimensions": json.dumps(canonical_dimensions, sort_keys=True, separators=(",", ":")),
                    "quantity": quantity,
                    "loss": worst_case_loss,
                    "margin": margin,
                    "expires": expires_at,
                    "now": now or datetime.now(UTC),
                },
            ).scalar_one()
        )

    def issue_receipt(
        self,
        connection: Connection,
        *,
        receipt_id: UUID,
        nonce: UUID,
        basis_id: UUID,
        basis_sha256: str,
        reservation_id: UUID,
        reservation_sha256: str,
        plan_id: UUID,
        plan_version: int,
        plan_sha256: str,
        account_id: UUID,
        instrument_id: str,
        strategy_id: str,
        session_id: str,
        action: str,
        execution_origin: str,
        source_sha256: str,
        scope_sha256: str,
        snapshot_refs: dict[str, str],
        snapshot_sha256: str,
        run_versions_sha256: str,
        mode_binding_id: UUID | None,
        mode_binding_version: int | None,
        mode_binding_sha256: str | None,
        constitution_ref: str,
        constitution_version: int,
        constitution_sha256: str,
        expires_at: datetime,
        now: datetime,
        actor: str,
        manual_actor_ref: str | None,
        environment_policy_ref: str,
    ) -> UUID | None:
        return connection.execute(
            text("""SELECT fao.issue_autonomy_gate_receipt(
                :receipt,:nonce,:basis,:basis_hash,:reservation,:reservation_hash,:plan,:plan_version,:plan_hash,
                :account,:instrument,:strategy,:session,:action,:origin,:source_hash,:scope_hash,CAST(:snapshots AS jsonb),:snapshot_hash,:runs,
                :binding,:binding_version,:binding_hash,:constitution_ref,:constitution_version,:constitution_hash,
                :expires,:now,:actor,:manual_actor,:environment)"""),
            {
                "receipt": receipt_id,
                "nonce": nonce,
                "basis": basis_id,
                "basis_hash": basis_sha256,
                "reservation": reservation_id,
                "reservation_hash": reservation_sha256,
                "plan": plan_id,
                "plan_version": plan_version,
                "plan_hash": plan_sha256,
                "account": account_id,
                "instrument": instrument_id,
                "strategy": strategy_id,
                "session": session_id,
                "action": action,
                "origin": execution_origin,
                "source_hash": source_sha256,
                "scope_hash": scope_sha256,
                "snapshots": json.dumps(snapshot_refs, sort_keys=True, separators=(",", ":")),
                "snapshot_hash": snapshot_sha256,
                "runs": run_versions_sha256,
                "binding": mode_binding_id,
                "binding_version": mode_binding_version,
                "binding_hash": mode_binding_sha256,
                "constitution_ref": constitution_ref,
                "constitution_version": constitution_version,
                "constitution_hash": constitution_sha256,
                "expires": expires_at,
                "now": now,
                "actor": actor,
                "manual_actor": manual_actor_ref,
                "environment": environment_policy_ref,
            },
        ).scalar_one()

    def consume_receipt(self, connection: Connection, *, receipt_id: UUID, nonce: UUID, now: datetime) -> bool:
        return bool(
            connection.execute(
                text("SELECT fao.consume_autonomy_gate_receipt(:receipt,:nonce,:now)"),
                {"receipt": receipt_id, "nonce": nonce, "now": now},
            ).scalar_one()
        )

    def composite_pause(
        self,
        connection: Connection,
        *,
        mandate_id: UUID,
        mandate_version: int,
        binding_id: UUID,
        binding_version: int,
        account_id: UUID,
        now: datetime,
        actor: str,
        evidence_ref: str,
        new_mandate_sha256: str,
        new_binding_sha256: str,
    ) -> bool:
        return bool(
            connection.execute(
                text("""SELECT fao.composite_pause(
                    :mandate,:mandate_version,:binding,:binding_version,:account,:now,:actor,:evidence,:new_mandate_hash,:new_binding_hash)"""),
                {
                    "mandate": mandate_id,
                    "mandate_version": mandate_version,
                    "binding": binding_id,
                    "binding_version": binding_version,
                    "account": account_id,
                    "now": now,
                    "actor": actor,
                    "evidence": evidence_ref,
                    "new_mandate_hash": new_mandate_sha256,
                    "new_binding_hash": new_binding_sha256,
                },
            ).scalar_one()
        )

    def composite_resume(
        self,
        connection: Connection,
        *,
        mandate_id: UUID,
        mandate_version: int,
        binding_id: UUID,
        binding_version: int,
        account_id: UUID,
        run_versions_sha256: str,
        qualified: bool,
        health_permits: bool,
        environment_policy_ref: str,
        now: datetime,
        actor: str,
        evidence_ref: str,
        new_mandate_sha256: str,
        new_binding_sha256: str,
    ) -> bool:
        return bool(
            connection.execute(
                text("""SELECT fao.composite_resume(
                    :mandate,:mandate_version,:binding,:binding_version,:account,:runs,:qualified,:health,:environment,:now,:actor,:evidence,:new_mandate_hash,:new_binding_hash)"""),
                {
                    "mandate": mandate_id,
                    "mandate_version": mandate_version,
                    "binding": binding_id,
                    "binding_version": binding_version,
                    "account": account_id,
                    "runs": run_versions_sha256,
                    "qualified": qualified,
                    "health": health_permits,
                    "environment": environment_policy_ref,
                    "now": now,
                    "actor": actor,
                    "evidence": evidence_ref,
                    "new_mandate_hash": new_mandate_sha256,
                    "new_binding_hash": new_binding_sha256,
                },
            ).scalar_one()
        )

    def retire_binding(
        self,
        connection: Connection,
        *,
        binding_id: UUID,
        binding_version: int,
        account_id: UUID | None,
        status: str,
        now: datetime,
        actor: str,
        reason: str,
        new_binding_sha256: str,
    ) -> bool:
        return bool(
            connection.execute(
                text("""SELECT fao.retire_autonomy_mode_binding(
                    :binding,:binding_version,:account,:status,:now,:actor,:reason,:new_binding_hash)"""),
                {
                    "binding": binding_id,
                    "binding_version": binding_version,
                    "account": account_id,
                    "status": status,
                    "now": now,
                    "actor": actor,
                    "reason": reason,
                    "new_binding_hash": new_binding_sha256,
                },
            ).scalar_one()
        )
