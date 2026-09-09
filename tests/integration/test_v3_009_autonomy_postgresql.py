"""Durable V3-009 owner-command acceptance against isolated PostgreSQL."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from futures_agent_os.decision.postgres_repository import PostgresAutonomyRepository


DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")

H = {
    name: digit * 64
    for name, digit in zip(
        (
            "mandate",
            "scope",
            "runs",
            "binding",
            "plan",
            "basis",
            "constitution",
            "reservation",
            "snapshot",
            "receipt",
            "approval",
        ),
        "123456789ab",
        strict=True,
    )
}


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(account: UUID) -> dict[str, object]:
    return {
        "account_id": str(account),
        "instruments": ["I"],
        "strategies": ["trend"],
        "sessions": ["DAY"],
        "actions": ["OPEN"],
        "quantity_ceiling": "2",
    }


def _insert_authority(*, escalation_mode: str = "REQUEST_ONE_OFF") -> tuple[Engine, UUID, UUID, UUID, datetime]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    mandate, binding, account = uuid4(), uuid4(), uuid4()
    expiry = _now() + timedelta(minutes=10)
    scope = _scope(account)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.simulation_autonomy_mandate
              (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,
               risk_policy_ref,notification_policy_ref,escalation_policy_ref,escalation_mode,
               expires_at,recorded_by,authority_sha256)
              VALUES (:mandate,1,'ACTIVE',:account,'test',CAST(:scope AS jsonb),:scope_hash,
               'risk://v3','notification://v3','escalation://v3',:escalation,
               :expiry,'user:owner',:mandate_hash)"""),
            {
                "mandate": mandate,
                "account": account,
                "scope": json.dumps(scope),
                "scope_hash": H["scope"],
                "escalation": escalation_mode,
                "expiry": expiry,
                "mandate_hash": H["mandate"],
            },
        )
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
              (binding_id,version,mode,binding_status,account_id,mandate_id,mandate_version,
               run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,
               qualified_artifact_ref,expires_at,transition_reason,transition_actor,evidence_ref)
              VALUES (:binding,1,'AUTONOMOUS_SIMULATION','ACTIVE',:account,:mandate,1,
               :runs,:binding_hash,CAST(:scope AS jsonb),:scope_hash,'qualification://v3',:expiry,
               'INITIAL_BINDING','user:owner','evidence://binding')"""),
            {
                "binding": binding,
                "account": account,
                "mandate": mandate,
                "runs": H["runs"],
                "binding_hash": H["binding"],
                "scope": json.dumps(scope),
                "scope_hash": H["scope"],
                "expiry": expiry,
            },
        )
        connection.execute(
            text(
                "INSERT INTO fao.autonomy_health_permit (account_id,environment_policy_ref,permits,valid_until_at) VALUES (:account,'environment://simulation-only',TRUE,:expiry)"
            ),
            {"account": account, "expiry": expiry},
        )
    return engine, mandate, binding, account, expiry


def _runtime(engine: Engine):
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(text("SET LOCAL ROLE fao_runtime"))
    return connection, transaction


def test_agent_exception_request_is_durable_idempotent_and_requires_exact_active_mode() -> None:
    engine, mandate, binding, account, authority_expiry = _insert_authority()
    repo = PostgresAutonomyRepository()
    approval, plan, token = uuid4(), uuid4(), uuid4()
    expiry = authority_expiry - timedelta(minutes=1)
    kwargs = {
        "approval_id": approval,
        "plan_id": plan,
        "plan_version": 1,
        "plan_sha256": H["plan"],
        "account_id": account,
        "instrument_id": "CU",
        "strategy_id": "trend",
        "session_id": "DAY",
        "action": "OPEN",
        "quantity": Decimal("1"),
        "approval_token": token,
        "scope_sha256": H["scope"],
        "approval_sha256": H["approval"],
        "expires_at": expiry,
        "mandate_id": mandate,
        "mandate_version": 1,
        "binding_id": binding,
        "binding_version": 1,
        "environment_policy_ref": "environment://simulation-only",
        "requested_by": "service:autonomous-quant-pm",
        "now": _now(),
    }
    connection, transaction = _runtime(engine)
    try:
        assert repo.request_agent_plan_approval(connection, **kwargs)
        assert repo.request_agent_plan_approval(connection, **kwargs)
        assert not repo.request_agent_plan_approval(connection, **{**kwargs, "approval_id": uuid4()})
        transaction.commit()
    finally:
        connection.close()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status,requested_by,scope_account_id,approval_scope FROM fao.plan_approval WHERE approval_id=:id"
            ),
            {"id": approval},
        ).one()
        assert row[:3] == ("REQUESTED", "service:autonomous-quant-pm", account)
        assert row.approval_scope["instruments"] == ["CU"]

    denied_engine, denied_mandate, denied_binding, denied_account, denied_expiry = _insert_authority(
        escalation_mode="SKIP_AND_NOTIFY"
    )
    denied_connection, denied_transaction = _runtime(denied_engine)
    try:
        assert not repo.request_agent_plan_approval(
            denied_connection,
            **{
                **kwargs,
                "approval_id": uuid4(),
                "plan_id": uuid4(),
                "approval_token": uuid4(),
                "account_id": denied_account,
                "mandate_id": denied_mandate,
                "binding_id": denied_binding,
                "expires_at": denied_expiry - timedelta(minutes=1),
            },
        )
        denied_transaction.commit()
    finally:
        denied_connection.close()


def test_agent_exception_scope_and_health_are_fail_closed() -> None:
    """Only an out-of-scope request may create a one-off approval."""
    repo = PostgresAutonomyRepository()

    # The mandate scope contains instrument I, so an in-scope request is denied.
    engine, mandate, binding, account, authority_expiry = _insert_authority()
    common = {
        "plan_version": 1,
        "plan_sha256": H["plan"],
        "account_id": account,
        "strategy_id": "trend",
        "session_id": "DAY",
        "action": "OPEN",
        "quantity": Decimal("1"),
        "scope_sha256": H["scope"],
        "approval_sha256": H["approval"],
        "expires_at": authority_expiry - timedelta(minutes=1),
        "mandate_id": mandate,
        "mandate_version": 1,
        "binding_id": binding,
        "binding_version": 1,
        "environment_policy_ref": "environment://simulation-only",
        "requested_by": "service:autonomous-quant-pm",
        "now": _now(),
    }
    connection, transaction = _runtime(engine)
    try:
        assert not repo.request_agent_plan_approval(
            connection,
            approval_id=uuid4(),
            plan_id=uuid4(),
            instrument_id="I",
            approval_token=uuid4(),
            **common,
        )
        transaction.commit()
    finally:
        connection.close()

    # Out of scope under REQUEST_ONE_OFF is allowed, while SKIP_AND_NOTIFY is not.
    skip_engine, skip_mandate, skip_binding, skip_account, skip_expiry = _insert_authority(
        escalation_mode="SKIP_AND_NOTIFY"
    )
    skip_common = {
        **common,
        "account_id": skip_account,
        "mandate_id": skip_mandate,
        "binding_id": skip_binding,
        "expires_at": skip_expiry - timedelta(minutes=1),
    }
    connection, transaction = _runtime(skip_engine)
    try:
        assert not repo.request_agent_plan_approval(
            connection,
            approval_id=uuid4(),
            plan_id=uuid4(),
            instrument_id="CU",
            approval_token=uuid4(),
            **skip_common,
        )
        transaction.commit()
    finally:
        connection.close()

    # Removing the health permit denies even a valid out-of-scope one-off request.
    unhealthy_engine, unhealthy_mandate, unhealthy_binding, unhealthy_account, unhealthy_expiry = _insert_authority()
    with unhealthy_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM fao.autonomy_health_permit WHERE account_id=:account"),
            {"account": unhealthy_account},
        )
    unhealthy_common = {
        **common,
        "account_id": unhealthy_account,
        "mandate_id": unhealthy_mandate,
        "binding_id": unhealthy_binding,
        "expires_at": unhealthy_expiry - timedelta(minutes=1),
    }
    connection, transaction = _runtime(unhealthy_engine)
    try:
        assert not repo.request_agent_plan_approval(
            connection,
            approval_id=uuid4(),
            plan_id=uuid4(),
            instrument_id="CU",
            approval_token=uuid4(),
            **unhealthy_common,
        )
        transaction.commit()
    finally:
        connection.close()


def test_operational_mode_pause_is_atomic_and_does_not_rewrite_mandate() -> None:
    engine, mandate, binding, account, expiry = _insert_authority()
    plan, basis, reservation, receipt, nonce = (uuid4() for _ in range(5))
    now = _now()
    repo = PostgresAutonomyRepository()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fao.risk_budget_authority (account_id,constitution_ref,constitution_version,constitution_sha256,ceiling) VALUES (:account,'risk://v3',1,:hash,100)"
            ),
            {"account": account, "hash": H["constitution"]},
        )
    connection, transaction = _runtime(engine)
    try:
        assert (
            repo.issue_mandate_basis(
                connection,
                basis_id=basis,
                mandate_id=mandate,
                mandate_version=1,
                plan_id=plan,
                plan_version=1,
                plan_sha256=H["plan"],
                account_id=account,
                instrument_id="I",
                strategy_id="trend",
                session_id="DAY",
                action="OPEN",
                quantity=Decimal("1"),
                mandate_sha256=H["mandate"],
                scope_sha256=H["scope"],
                basis_sha256=H["basis"],
                expires_at=expiry - timedelta(minutes=1),
                now=now,
                actor="service:runtime",
            )
            == basis
        )
        assert repo.reserve_risk_budget(
            connection,
            reservation_id=reservation,
            reservation_sha256=H["reservation"],
            account_id=account,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            instrument_id="I",
            strategy_id="trend",
            session_id="DAY",
            basis_id=basis,
            basis_sha256=H["basis"],
            constitution_ref="risk://v3",
            constitution_version=1,
            constitution_sha256=H["constitution"],
            risk_dimensions={"scenario": "gap"},
            quantity=Decimal("1"),
            worst_case_loss=Decimal("10"),
            margin=Decimal("2"),
            expires_at=expiry - timedelta(minutes=2),
            now=now,
        )
        assert (
            repo.issue_receipt(
                connection,
                receipt_id=receipt,
                nonce=nonce,
                basis_id=basis,
                basis_sha256=H["basis"],
                reservation_id=reservation,
                reservation_sha256=H["reservation"],
                plan_id=plan,
                plan_version=1,
                plan_sha256=H["plan"],
                account_id=account,
                instrument_id="I",
                strategy_id="trend",
                session_id="DAY",
                action="OPEN",
                execution_origin="AUTONOMOUS_AGENT",
                source_sha256=H["mandate"],
                scope_sha256=H["scope"],
                snapshot_refs={"market": "snapshot://v3", "as_of": now.isoformat(), "expires_at": expiry.isoformat()},
                snapshot_sha256=H["snapshot"],
                run_versions_sha256=H["runs"],
                mode_binding_id=binding,
                mode_binding_version=1,
                mode_binding_sha256=H["binding"],
                constitution_ref="risk://v3",
                constitution_version=1,
                constitution_sha256=H["constitution"],
                expires_at=expiry - timedelta(minutes=3),
                now=now,
                actor="service:runtime",
                manual_actor_ref=None,
                environment_policy_ref="environment://simulation-only",
            )
            == receipt
        )
        assert not repo.pause_autonomy_mode(
            connection,
            binding_id=binding,
            binding_version=1,
            account_id=account,
            now=now,
            actor="service:health",
            reason="USER_PAUSE",
            evidence_ref="health://bad-reason",
            new_binding_sha256="c" * 64,
        )
        assert repo.pause_autonomy_mode(
            connection,
            binding_id=binding,
            binding_version=1,
            account_id=account,
            now=now,
            actor="service:health",
            reason="HEALTH_DEGRADED",
            evidence_ref="health://degraded",
            new_binding_sha256="d" * 64,
        )
        transaction.commit()
    finally:
        connection.close()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version,status FROM fao.simulation_autonomy_mandate WHERE mandate_id=:id"),
            {"id": mandate},
        ).one() == (1, "ACTIVE")
        assert connection.execute(
            text(
                "SELECT version,mode,previous_mode,binding_status FROM fao.autonomy_mode_binding WHERE binding_id=:id"
            ),
            {"id": binding},
        ).one() == (2, "PAUSED", "AUTONOMOUS_SIMULATION", "ACTIVE")
        assert (
            connection.execute(
                text("SELECT basis_status FROM fao.authorization_basis WHERE basis_id=:id"), {"id": basis}
            ).scalar_one()
            == "STALE"
        )
        assert (
            connection.execute(
                text("SELECT receipt_status FROM fao.autonomy_gate_receipt WHERE receipt_id=:id"), {"id": receipt}
            ).scalar_one()
            == "STALE"
        )
        assert (
            connection.execute(
                text("SELECT reservation_status FROM fao.risk_budget_reservation WHERE reservation_id=:id"),
                {"id": reservation},
            ).scalar_one()
            == "RELEASED"
        )


def test_agent_worker_cannot_call_v3_009_owner_commands() -> None:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL ROLE fao_agent_worker"))
        with pytest.raises(DBAPIError):
            connection.execute(
                text("SELECT fao.pause_autonomy_mode(NULL,NULL,NULL,CURRENT_TIMESTAMP,NULL,NULL,NULL,NULL)")
            )
        transaction.rollback()


def test_human_grant_command_is_supervisor_only_and_idempotent() -> None:
    assert DATABASE_URL is not None
    engine, mandate, binding, account, expiry = _insert_authority()
    repo = PostgresAutonomyRepository()
    approval, plan = uuid4(), uuid4()
    now = _now()
    connection, transaction = _runtime(engine)
    try:
        assert repo.request_agent_plan_approval(
            connection,
            **{
                "approval_id": approval,
                "plan_id": plan,
                "plan_version": 1,
                "plan_sha256": H["plan"],
                "account_id": account,
                "instrument_id": "CU",
                "strategy_id": "trend",
                "session_id": "DAY",
                "action": "OPEN",
                "quantity": Decimal("1"),
                "approval_token": uuid4(),
                "scope_sha256": H["scope"],
                "approval_sha256": H["approval"],
                "expires_at": expiry - timedelta(minutes=1),
                "mandate_id": mandate,
                "mandate_version": 1,
                "binding_id": binding,
                "binding_version": 1,
                "environment_policy_ref": "environment://simulation-only",
                "requested_by": "service:agent",
                "now": now,
            },
        )
        transaction.commit()
    finally:
        connection.close()
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL ROLE fao_supervisor"))
        assert repo.grant_plan_approval(
            connection,
            approval_id=approval,
            approval_version=1,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            actor="user:owner",
            now=now,
        )
        assert not repo.grant_plan_approval(
            connection,
            approval_id=approval,
            approval_version=1,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            actor="user:owner",
            now=now,
        )
        transaction.commit()
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status,version,decided_by FROM fao.plan_approval WHERE approval_id=:id"), {"id": approval}
        ).one()
        assert row == ("GRANTED", 2, "user:owner")
