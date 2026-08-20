"""Narrow PostgreSQL command client for durable V0-014 authorization facts.

The runtime role has no direct table mutation rights.  Every write below is a
typed call to an owner-controlled SECURITY DEFINER function; callers still
own the surrounding transaction so retries remain explicit and auditable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    basis_id: UUID | None
    consumed: bool


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

    def consume_risk_budget_reservation(
        self, connection: Connection, *, reservation_id: UUID, receipt_id: UUID, now: datetime
    ) -> bool:
        return bool(
            connection.execute(
                text("SELECT fao.consume_risk_budget_reservation(:reservation,:receipt,:now)"),
                {"reservation": reservation_id, "receipt": receipt_id, "now": now},
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
