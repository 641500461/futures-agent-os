"""Real role-separated PostgreSQL acceptance tests for V0-014 commands."""

from __future__ import annotations

import os
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from futures_agent_os.decision.postgres_repository import PostgresAutonomyRepository


DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")

H = {
    name: character * 64
    for name, character in {
        "plan": "a",
        "approval": "b",
        "scope": "c",
        "basis": "d",
        "constitution": "e",
        "reservation": "f",
        "snapshot": "1",
        "runs": "2",
        "binding": "3",
        "mandate": "4",
    }.items()
}


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(account: UUID, *, starts_at: datetime | None = None, ends_at: datetime | None = None) -> dict[str, object]:
    scope: dict[str, object] = {
        "account_id": str(account),
        "instruments": ["I"],
        "strategies": ["trend"],
        "sessions": ["DAY"],
        "actions": ["OPEN"],
        "quantity_ceiling": "2",
    }
    if starts_at is not None and ends_at is not None:
        scope["window_start_at"] = starts_at.isoformat()
        scope["window_end_at"] = ends_at.isoformat()
    return scope


def _runtime(engine: object):
    connection = engine.connect()  # type: ignore[attr-defined]
    transaction = connection.begin()
    connection.execute(text("SET LOCAL ROLE fao_runtime"))
    return connection, transaction


def _supervisor(engine: object):
    connection = engine.connect()  # type: ignore[attr-defined]
    transaction = connection.begin()
    connection.execute(text("SET LOCAL ROLE fao_supervisor"))
    return connection, transaction


def _approval(engine: object) -> tuple[UUID, UUID, UUID, UUID, datetime]:
    approval, plan, account, token = (uuid4() for _ in range(4))
    now, expiry = _now(), _now() + timedelta(minutes=10)
    with engine.begin() as connection:  # type: ignore[attr-defined]
        connection.execute(
            text("""INSERT INTO fao.plan_approval
          (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,expires_at,requested_at,decided_at,decided_by,requested_by,approval_hash,approval_token,scope_sha256,scope_account_id,allowed_actions,quantity_ceiling,window_start_at,window_end_at)
          VALUES (:id,1,'GRANTED',:plan,1,:plan_hash,CAST(:approval_scope AS jsonb),:expiry,:now,:now,'user:authorized','user:requester',:approval_hash,:token,:scope_hash,:account,jsonb_build_array('OPEN'),2,:now,:expiry)"""),
            {
                "id": approval,
                "plan": plan,
                "plan_hash": H["plan"],
                "expiry": expiry,
                "now": now,
                "approval_hash": H["approval"],
                "token": token,
                "scope_hash": H["scope"],
                "account": account,
                "approval_scope": json.dumps(_scope(account, starts_at=now, ends_at=expiry)),
            },
        )
    return approval, plan, account, token, expiry


def _manual_basis(engine: object) -> tuple[UUID, UUID, UUID, UUID, UUID, datetime]:
    approval, plan, account, token, expiry = _approval(engine)
    connection, transaction = _supervisor(engine)
    try:
        result = PostgresAutonomyRepository().consume_plan_approval(
            connection,
            approval_id=approval,
            approval_version=1,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            account_id=account,
            instrument_id="I",
            strategy_id="trend",
            session_id="DAY",
            action="OPEN",
            quantity=Decimal("1"),
            approval_token=token,
            approval_hash=H["approval"],
            basis_id=uuid4(),
            basis_sha256=H["basis"],
            scope_sha256=H["scope"],
            expires_at=expiry - timedelta(minutes=1),
            now=_now(),
            actor="user:authorized",
        )
        assert result.consumed and result.basis_id is not None
        transaction.commit()
        return approval, plan, account, token, result.basis_id, expiry
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("scope_change", "allowed_actions", "quantity"),
    (
        (lambda scope: scope.pop("instruments"), "OPEN", Decimal("2")),
        (lambda scope: scope.__setitem__("instruments", None), "OPEN", Decimal("2")),
        (lambda scope: scope.__setitem__("instruments", "I"), "OPEN", Decimal("2")),
        (lambda scope: (scope.pop("instruments"), scope.__setitem__("instrument", "I")), "OPEN", Decimal("2")),
        (lambda scope: scope.__setitem__("actions", ["MAGIC"]), "MAGIC", Decimal("2")),
        (lambda scope: scope.__setitem__("quantity_ceiling", "0"), "OPEN", Decimal("0")),
    ),
    ids=("missing", "null", "wrong-type", "singular", "unknown-action", "zero-quantity"),
)
def test_scope_schema_is_plural_typed_and_fail_closed_for_direct_writes(
    scope_change: object, allowed_actions: str, quantity: Decimal
) -> None:
    engine = create_engine(DATABASE_URL)
    account, approval, plan, token = (uuid4() for _ in range(4))
    now, expiry = _now(), _now() + timedelta(minutes=10)
    scope = _scope(account, starts_at=now, ends_at=expiry)
    scope_change(scope)  # type: ignore[operator]
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO fao.plan_approval
                  (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,expires_at,requested_at,decided_at,decided_by,requested_by,approval_hash,approval_token,scope_sha256,scope_account_id,allowed_actions,quantity_ceiling,window_start_at,window_end_at)
                  VALUES (:id,1,'GRANTED',:plan,1,:plan_hash,CAST(:approval_scope AS jsonb),:expiry,:now,:now,'user:authorized','user:requester',:approval_hash,:token,:scope_hash,:account,jsonb_build_array(:action),:quantity,:now,:expiry)"""),
                {
                    "id": approval,
                    "plan": plan,
                    "plan_hash": H["plan"],
                    "approval_scope": json.dumps(scope),
                    "expiry": expiry,
                    "now": now,
                    "approval_hash": H["approval"],
                    "token": token,
                    "scope_hash": H["scope"],
                    "account": account,
                    "action": allowed_actions,
                    "quantity": quantity,
                },
            )


@pytest.mark.parametrize(
    ("collection", "alias"),
    (
        ("instruments", "I ES"),
        ("strategies", "trend\tfast"),
        ("sessions", "DAY\nNIGHT"),
    ),
    ids=("instrument-internal-space", "strategy-tab", "session-newline"),
)
def test_scope_identifiers_reject_all_posix_whitespace_on_direct_insert(collection: str, alias: str) -> None:
    engine = create_engine(DATABASE_URL)
    account, approval, plan, token = (uuid4() for _ in range(4))
    now, expiry = _now(), _now() + timedelta(minutes=10)
    scope = _scope(account, starts_at=now, ends_at=expiry)
    scope[collection] = [alias]
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO fao.plan_approval
                  (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,expires_at,requested_at,decided_at,decided_by,requested_by,approval_hash,approval_token,scope_sha256,scope_account_id,allowed_actions,quantity_ceiling,window_start_at,window_end_at)
                  VALUES (:id,1,'GRANTED',:plan,1,:plan_hash,CAST(:approval_scope AS jsonb),:expiry,:now,:now,'user:authorized','user:requester',:approval_hash,:token,:scope_hash,:account,jsonb_build_array('OPEN'),2,:now,:expiry)"""),
                {
                    "id": approval,
                    "plan": plan,
                    "plan_hash": H["plan"],
                    "approval_scope": json.dumps(scope),
                    "expiry": expiry,
                    "now": now,
                    "approval_hash": H["approval"],
                    "token": token,
                    "scope_hash": H["scope"],
                    "account": account,
                },
            )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT fao.v014_valid_scope(CAST(:scope AS jsonb),:account,TRUE)"),
            {"scope": json.dumps(_scope(account, starts_at=now, ends_at=expiry)), "account": account},
        ).scalar_one()


def test_mandate_scope_direct_write_requires_the_same_canonical_range_schema() -> None:
    engine = create_engine(DATABASE_URL)
    mandate, account = uuid4(), uuid4()
    scope = _scope(account)
    scope["sessions"] = "DAY"
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO fao.simulation_autonomy_mandate
                  (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,notification_policy_ref,escalation_policy_ref,expires_at,recorded_by,authority_sha256)
                  VALUES (:mandate,1,'ACTIVE',:account,'test',CAST(:scope AS jsonb),:scope_hash,'risk://v1','notification://v1','escalation://v1',:expiry,'user:authorized',:authority)"""),
                {
                    "mandate": mandate,
                    "account": account,
                    "scope": json.dumps(scope),
                    "scope_hash": H["scope"],
                    "expiry": _now() + timedelta(minutes=10),
                    "authority": H["mandate"],
                },
            )


def test_risk_dimension_keys_are_trimmed_but_keep_legal_internal_spaces() -> None:
    engine = create_engine(DATABASE_URL)
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO fao.risk_budget_authority
                (account_id,constitution_ref,constitution_version,constitution_sha256,ceiling)
                VALUES (:account,' risk://v1',1,:hash,1)"""),
                {"account": uuid4(), "hash": H["constitution"]},
            )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT fao.v014_valid_risk_dimensions(CAST(:dimensions AS jsonb))"),
                {"dimensions": '{" risk ":"x"}'},
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                text("SELECT fao.v014_valid_risk_dimensions(CAST(:dimensions AS jsonb))"),
                {"dimensions": '{"risk class":"x"}'},
            ).scalar_one()
            is True
        )


def test_paused_observe_and_shadow_bindings_do_not_require_a_mandate_scope() -> None:
    engine = create_engine(DATABASE_URL)
    expiry = _now() + timedelta(minutes=10)
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO fao.autonomy_mode_binding
                (binding_id,version,mode,binding_status,run_versions_sha256,binding_sha256,
                 scope_snapshot,scope_sha256,qualified_artifact_ref,expires_at)
                VALUES (:id,1,'OBSERVE','ACTIVE',:runs,:binding,'{}'::jsonb,:scope,' artifact://run',:expiry)"""),
                {"id": uuid4(), "runs": H["runs"], "binding": H["binding"], "scope": H["scope"], "expiry": expiry},
            )
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
              (binding_id,version,mode,binding_status,account_id,mandate_id,mandate_version,run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,previous_mode,expires_at)
              VALUES (:id,1,'PAUSED','ACTIVE',NULL,NULL,NULL,:runs,:binding,'{}'::jsonb,:scope,'OBSERVE',:expiry)"""),
            {"id": uuid4(), "runs": H["runs"], "binding": H["binding"], "scope": H["scope"], "expiry": expiry},
        )
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
              (binding_id,version,mode,binding_status,account_id,mandate_id,mandate_version,run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,previous_mode,expires_at)
              VALUES (:id,1,'PAUSED','ACTIVE',:account,NULL,NULL,:runs,:binding,'{}'::jsonb,:scope,'SHADOW',:expiry)"""),
            {
                "id": uuid4(),
                "account": uuid4(),
                "runs": H["runs"],
                "binding": H["binding"],
                "scope": H["scope"],
                "expiry": expiry,
            },
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM fao.autonomy_mode_binding WHERE mode='PAUSED' AND previous_mode IN ('OBSERVE','SHADOW')"
                )
            ).scalar_one()
            >= 2
        )


def test_binding_retirement_versions_hashes_and_rejects_stale_expected_versions() -> None:
    engine = create_engine(DATABASE_URL)
    superseded, expired = uuid4(), uuid4()
    now = _now()
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
            (binding_id,version,mode,binding_status,account_id,run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,expires_at)
            VALUES (:binding,1,'OBSERVE','ACTIVE',NULL,:runs,:hash,'{}'::jsonb,:scope,:expires)"""),
            {
                "binding": superseded,
                "runs": H["runs"],
                "hash": H["binding"],
                "scope": H["scope"],
                "expires": now + timedelta(minutes=5),
            },
        )
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
            (binding_id,version,mode,binding_status,account_id,run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,expires_at,recorded_at)
            VALUES (:binding,1,'OBSERVE','ACTIVE',NULL,:runs,:hash,'{}'::jsonb,:scope,:expires,:recorded)"""),
            {
                "binding": expired,
                "runs": H["runs"],
                "hash": H["binding"],
                "scope": H["scope"],
                "expires": now - timedelta(minutes=1),
                "recorded": now - timedelta(minutes=2),
            },
        )
    connection, transaction = _runtime(engine)
    try:
        repo = PostgresAutonomyRepository()
        assert repo.retire_binding(
            connection,
            binding_id=superseded,
            binding_version=1,
            account_id=None,
            status="SUPERSEDED",
            now=now,
            actor="service:runtime",
            reason="replacement",
            new_binding_sha256="5" * 64,
        )
        assert not repo.retire_binding(
            connection,
            binding_id=superseded,
            binding_version=1,
            account_id=None,
            status="SUPERSEDED",
            now=now,
            actor="service:runtime",
            reason="replacement",
            new_binding_sha256="6" * 64,
        )
        assert repo.retire_binding(
            connection,
            binding_id=expired,
            binding_version=1,
            account_id=None,
            status="EXPIRED",
            now=now,
            actor="service:runtime",
            reason="clock-expired",
            new_binding_sha256="7" * 64,
        )
        transaction.commit()
    finally:
        connection.close()
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT version,state_version,binding_status,binding_sha256 FROM fao.autonomy_mode_binding WHERE binding_id=:binding"
            ),
            {"binding": superseded},
        ).one() == (2, 2, "SUPERSEDED", "5" * 64)
        assert connection.execute(
            text(
                "SELECT version,state_version,binding_status,binding_sha256 FROM fao.autonomy_mode_binding WHERE binding_id=:binding"
            ),
            {"binding": expired},
        ).one() == (2, 2, "EXPIRED", "7" * 64)


def test_runtime_manual_chain_is_single_effect_and_all_scope_fields_are_authoritative() -> None:
    engine = create_engine(DATABASE_URL)
    approval, plan, account, token, basis, expiry = _manual_basis(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version,status,consumed_basis_id FROM fao.plan_approval WHERE approval_id=:id"),
            {"id": approval},
        ).one()[:2] == (2, "CONSUMED")
    # Replay must match every authority field, even after a process restart.
    connection, transaction = _supervisor(engine)
    try:
        replay = PostgresAutonomyRepository().consume_plan_approval(
            connection,
            approval_id=approval,
            approval_version=1,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            account_id=account,
            instrument_id="I",
            strategy_id="trend",
            session_id="DAY",
            action="OPEN",
            quantity=Decimal("1"),
            approval_token=token,
            approval_hash=H["approval"],
            basis_id=uuid4(),
            basis_sha256=H["basis"],
            scope_sha256=H["scope"],
            expires_at=expiry - timedelta(minutes=1),
            now=_now(),
            actor="user:authorized",
        )
        assert replay == type(replay)(basis, True)
        mismatch = PostgresAutonomyRepository().consume_plan_approval(
            connection,
            approval_id=approval,
            approval_version=1,
            plan_id=plan,
            plan_version=1,
            plan_sha256=H["plan"],
            account_id=uuid4(),
            instrument_id="I",
            strategy_id="trend",
            session_id="DAY",
            action="OPEN",
            quantity=Decimal("1"),
            approval_token=token,
            approval_hash=H["approval"],
            basis_id=uuid4(),
            basis_sha256=H["basis"],
            scope_sha256=H["scope"],
            expires_at=expiry - timedelta(minutes=1),
            now=_now(),
            actor="user:authorized",
        )
        assert not mismatch.consumed
        transaction.commit()
    finally:
        connection.close()

    reservation = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.risk_budget_authority
          (account_id,constitution_ref,constitution_version,constitution_sha256,ceiling) VALUES (:account,'risk://v1',1,:hash,100)"""),
            {"account": account, "hash": H["constitution"]},
        )
        connection.execute(
            text(
                "INSERT INTO fao.autonomy_health_permit (account_id,environment_policy_ref,permits,valid_until_at) VALUES (:account,'environment://simulation-only',TRUE,:expiry)"
            ),
            {"account": account, "expiry": expiry},
        )
    connection, transaction = _runtime(engine)
    try:
        repo = PostgresAutonomyRepository()
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
            constitution_ref="risk://v1",
            constitution_version=1,
            constitution_sha256=H["constitution"],
            risk_dimensions={"product": "RB", "scenario": "gap"},
            quantity=Decimal("1"),
            worst_case_loss=Decimal("10"),
            margin=Decimal("2"),
            expires_at=expiry - timedelta(minutes=2),
        )
        receipt, nonce = uuid4(), uuid4()
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
                execution_origin="MANUAL_TEST",
                source_sha256=H["approval"],
                scope_sha256=H["scope"],
                snapshot_refs={"market": "snapshot://1", "as_of": _now().isoformat(), "expires_at": expiry.isoformat()},
                snapshot_sha256=H["snapshot"],
                run_versions_sha256=H["runs"],
                mode_binding_id=None,
                mode_binding_version=None,
                mode_binding_sha256=None,
                constitution_ref="risk://v1",
                constitution_version=1,
                constitution_sha256=H["constitution"],
                expires_at=expiry - timedelta(minutes=3),
                now=_now(),
                actor="user:authorized",
                manual_actor_ref="user:authorized",
                environment_policy_ref="environment://simulation-only",
            )
            == receipt
        )
        connection.execute(text("SET LOCAL ROLE NONE"))
        connection.execute(
            text("UPDATE fao.autonomy_health_permit SET permits=FALSE WHERE account_id=:account"), {"account": account}
        )
        connection.execute(text("SET LOCAL ROLE fao_runtime"))
        assert not repo.consume_receipt(connection, receipt_id=receipt, nonce=nonce, now=_now())
        connection.execute(text("SET LOCAL ROLE NONE"))
        connection.execute(
            text("UPDATE fao.autonomy_health_permit SET permits=TRUE WHERE account_id=:account"), {"account": account}
        )
        connection.execute(text("SET LOCAL ROLE fao_runtime"))
        assert repo.consume_receipt(connection, receipt_id=receipt, nonce=nonce, now=_now())
        assert not repo.consume_receipt(connection, receipt_id=receipt, nonce=nonce, now=_now())
        assert repo.consume_risk_budget_reservation(
            connection, reservation_id=reservation, receipt_id=receipt, now=_now()
        )
        assert connection.execute(
            text("SELECT risk_dimensions FROM fao.risk_budget_reservation WHERE reservation_id=:id"),
            {"id": reservation},
        ).scalar_one() == {"product": "RB", "scenario": "gap"}
        transaction.commit()
    finally:
        connection.close()


def test_autonomous_chain_and_pause_resume_stale_only_matching_mandate_objects() -> None:
    engine = create_engine(DATABASE_URL)
    mandate, binding, account, plan = (uuid4() for _ in range(4))
    now, expiry = _now(), _now() + timedelta(minutes=10)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.simulation_autonomy_mandate
          (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,notification_policy_ref,escalation_policy_ref,expires_at,recorded_by,authority_sha256)
          VALUES (:mandate,1,'ACTIVE',:account,'test',CAST(:mandate_scope AS jsonb),:scope,'risk://v1','notification://v1','escalation://v1',:expiry,'user:authorized',:authority)"""),
            {
                "mandate": mandate,
                "account": account,
                "mandate_scope": json.dumps(_scope(account)),
                "scope": H["scope"],
                "expiry": expiry,
                "authority": H["mandate"],
            },
        )
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
          (binding_id,version,mode,binding_status,account_id,mandate_id,mandate_version,run_versions_sha256,binding_sha256,scope_snapshot,scope_sha256,qualified_artifact_ref,expires_at)
          VALUES (:binding,1,'AUTONOMOUS_SIMULATION','ACTIVE',:account,:mandate,1,:runs,:binding_hash,CAST(:binding_scope AS jsonb),:scope,'qualification://v1',:expiry)"""),
            {
                "binding": binding,
                "account": account,
                "mandate": mandate,
                "runs": H["runs"],
                "binding_hash": H["binding"],
                "scope": H["scope"],
                "binding_scope": json.dumps(_scope(account)),
                "expiry": expiry,
            },
        )
        connection.execute(
            text(
                "INSERT INTO fao.risk_budget_authority (account_id,constitution_ref,constitution_version,constitution_sha256,ceiling) VALUES (:account,'risk://v1',1,:hash,100)"
            ),
            {"account": account, "hash": H["constitution"]},
        )
        connection.execute(
            text(
                "INSERT INTO fao.autonomy_health_permit (account_id,environment_policy_ref,permits,valid_until_at) VALUES (:account,'environment://simulation-only',TRUE,:expiry)"
            ),
            {"account": account, "expiry": expiry},
        )
    connection, transaction = _runtime(engine)
    try:
        repo = PostgresAutonomyRepository()
        basis = repo.issue_mandate_basis(
            connection,
            basis_id=uuid4(),
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
        assert basis is not None
        scope_values: dict[str, object] = {
            "instrument_id": "I",
            "strategy_id": "trend",
            "session_id": "DAY",
            "action": "OPEN",
            "quantity": Decimal("1"),
        }
        for field, invalid in (
            ("instrument_id", "CU"),
            ("instrument_id", "I ES"),
            ("strategy_id", "mean-reversion"),
            ("strategy_id", "trend\tfast"),
            ("session_id", "NIGHT"),
            ("session_id", "DAY\nNIGHT"),
            ("action", "CLOSE"),
            ("action", "MAGIC"),
            ("quantity", Decimal("0")),
            ("quantity", Decimal("3")),
        ):
            candidate = {**scope_values, field: invalid}
            assert (
                repo.issue_mandate_basis(
                    connection,
                    basis_id=uuid4(),
                    mandate_id=mandate,
                    mandate_version=1,
                    plan_id=uuid4(),
                    plan_version=1,
                    plan_sha256=H["plan"],
                    account_id=account,
                    mandate_sha256=H["mandate"],
                    scope_sha256=H["scope"],
                    basis_sha256=H["basis"],
                    expires_at=expiry - timedelta(minutes=1),
                    now=now,
                    actor="service:runtime",
                    **candidate,
                )
                is None
            )
        assert not repo.reserve_risk_budget(
            connection,
            reservation_id=uuid4(),
            reservation_sha256=H["reservation"],
            account_id=account,
            plan_id=uuid4(),
            plan_version=1,
            plan_sha256=H["plan"],
            instrument_id="I",
            strategy_id="trend",
            session_id="DAY",
            basis_id=basis,
            basis_sha256=H["basis"],
            constitution_ref=" risk://v1",
            constitution_version=1,
            constitution_sha256=H["constitution"],
            risk_dimensions={"risk": "x"},
            quantity=Decimal("1"),
            worst_case_loss=Decimal("10"),
            margin=Decimal("2"),
            expires_at=expiry - timedelta(minutes=2),
            now=now,
        )
        reservation = uuid4()
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
            constitution_ref="risk://v1",
            constitution_version=1,
            constitution_sha256=H["constitution"],
            risk_dimensions={"instrument": "AG"},
            quantity=Decimal("1"),
            worst_case_loss=Decimal("10"),
            margin=Decimal("2"),
            expires_at=expiry - timedelta(minutes=2),
            now=now,
        )
        receipt, nonce = uuid4(), uuid4()
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
                snapshot_refs={"market": "snapshot://1", "as_of": now.isoformat(), "expires_at": expiry.isoformat()},
                snapshot_sha256=H["snapshot"],
                run_versions_sha256=H["runs"],
                mode_binding_id=binding,
                mode_binding_version=1,
                mode_binding_sha256=H["binding"],
                constitution_ref="risk://v1",
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
        connection.execute(text("SET LOCAL ROLE fao_supervisor"))
        assert not repo.composite_pause(
            connection,
            mandate_id=mandate,
            mandate_version=1,
            binding_id=binding,
            binding_version=1,
            account_id=account,
            now=None,  # type: ignore[arg-type]
            actor=None,  # type: ignore[arg-type]
            evidence_ref=None,  # type: ignore[arg-type]
            new_mandate_sha256="5" * 64,
            new_binding_sha256="6" * 64,
        )
        assert repo.composite_pause(
            connection,
            mandate_id=mandate,
            mandate_version=1,
            binding_id=binding,
            binding_version=1,
            account_id=account,
            now=now,
            actor="user:authorized",
            evidence_ref="evidence://pause",
            new_mandate_sha256="5" * 64,
            new_binding_sha256="6" * 64,
        )
        assert not repo.consume_receipt(connection, receipt_id=receipt, nonce=nonce, now=now)
        assert not repo.composite_resume(
            connection,
            mandate_id=mandate,
            mandate_version=2,
            binding_id=binding,
            binding_version=2,
            account_id=account,
            run_versions_sha256=None,  # type: ignore[arg-type]
            qualified=None,  # type: ignore[arg-type]
            health_permits=None,  # type: ignore[arg-type]
            environment_policy_ref="environment://simulation-only",
            now=None,  # type: ignore[arg-type]
            actor=None,  # type: ignore[arg-type]
            evidence_ref=None,  # type: ignore[arg-type]
            new_mandate_sha256="7" * 64,
            new_binding_sha256="8" * 64,
        )
        assert repo.composite_resume(
            connection,
            mandate_id=mandate,
            mandate_version=2,
            binding_id=binding,
            binding_version=2,
            account_id=account,
            run_versions_sha256=H["runs"],
            qualified=False,
            health_permits=False,
            environment_policy_ref="environment://simulation-only",
            now=now,
            actor="user:authorized",
            evidence_ref="evidence://resume",
            new_mandate_sha256="7" * 64,
            new_binding_sha256="8" * 64,
        )
        assert (
            repo.issue_mandate_basis(
                connection,
                basis_id=uuid4(),
                mandate_id=mandate,
                mandate_version=3,
                plan_id=uuid4(),
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
            is None
        )
        transaction.commit()
    finally:
        connection.close()
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT basis_status FROM fao.authorization_basis WHERE basis_id=:id"), {"id": basis}
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
        assert connection.execute(
            text("SELECT version,status FROM fao.simulation_autonomy_mandate WHERE mandate_id=:id"), {"id": mandate}
        ).one() == (3, "ACTIVE")
        assert (
            connection.execute(
                text("SELECT authority_sha256 FROM fao.simulation_autonomy_mandate WHERE mandate_id=:id"),
                {"id": mandate},
            ).scalar_one()
            == "7" * 64
        )
        assert (
            connection.execute(
                text("SELECT binding_sha256 FROM fao.autonomy_mode_binding WHERE binding_id=:id"),
                {"id": binding},
            ).scalar_one()
            == "8" * 64
        )


def test_two_runtime_connections_cannot_over_reserve_a_shared_constitution_ceiling() -> None:
    engine = create_engine(DATABASE_URL)
    mandate, account = uuid4(), uuid4()
    plans = (uuid4(), uuid4())
    now, expiry = _now(), _now() + timedelta(minutes=10)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.simulation_autonomy_mandate
          (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,notification_policy_ref,escalation_policy_ref,expires_at,recorded_by,authority_sha256)
          VALUES (:mandate,1,'ACTIVE',:account,'test',CAST(:mandate_scope AS jsonb),:scope,'risk://v1','notification://v1','escalation://v1',:expiry,'user:authorized',:authority)"""),
            {
                "mandate": mandate,
                "account": account,
                "mandate_scope": json.dumps(_scope(account)),
                "scope": H["scope"],
                "expiry": expiry,
                "authority": H["mandate"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO fao.risk_budget_authority (account_id,constitution_ref,constitution_version,constitution_sha256,ceiling) VALUES (:account,'risk://v1',1,:hash,100)"
            ),
            {"account": account, "hash": H["constitution"]},
        )
    bases: list[UUID] = []
    for plan in plans:
        connection, transaction = _runtime(engine)
        try:
            basis = PostgresAutonomyRepository().issue_mandate_basis(
                connection,
                basis_id=uuid4(),
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
            assert basis is not None
            bases.append(basis)
            transaction.commit()
        finally:
            connection.close()

    def reserve(index: int, *, loss: Decimal = Decimal("60")) -> bool:
        connection, transaction = _runtime(engine)
        try:
            result = PostgresAutonomyRepository().reserve_risk_budget(
                connection,
                reservation_id=uuid4(),
                reservation_sha256=H["reservation"],
                account_id=account,
                plan_id=plans[index],
                plan_version=1,
                plan_sha256=H["plan"],
                instrument_id="I",
                strategy_id="trend",
                session_id="DAY",
                basis_id=bases[index],
                basis_sha256=H["basis"],
                constitution_ref="risk://v1",
                constitution_version=1,
                constitution_sha256=H["constitution"],
                risk_dimensions={"instrument": f"T{index}"},
                quantity=Decimal("1"),
                worst_case_loss=loss,
                margin=Decimal("2"),
                expires_at=expiry - timedelta(minutes=2),
                now=now,
            )
            transaction.commit()
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))
    assert outcomes.count(True) == 1
    winner = outcomes.index(True)
    assert reserve(winner)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda loss: reserve(winner, loss=loss), (Decimal("60"), Decimal("59")))) == [
            True,
            False,
        ]
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM fao.risk_budget_reservation WHERE plan_id=:plan AND basis_id=:basis"),
                {"plan": plans[winner], "basis": bases[winner]},
            ).scalar_one()
            == 1
        )


def test_runtime_is_command_only_and_public_agent_worker_cannot_execute_commands() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        for role in ("fao_runtime", "fao_agent_worker"):
            transaction = connection.begin()
            connection.execute(text(f"SET LOCAL ROLE {role}"))
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("INSERT INTO fao.decision_journal (journal_id,projection_version) VALUES (:id,1)"),
                    {"id": uuid4()},
                )
            transaction.rollback()
        transaction = connection.begin()
        connection.execute(text("SET LOCAL ROLE fao_agent_worker"))
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "SELECT fao.reserve_risk_budget(NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{}'::jsonb,0,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        transaction.rollback()
        transaction = connection.begin()
        connection.execute(text("SET LOCAL ROLE fao_runtime"))
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "SELECT fao.composite_pause(NULL,NULL,NULL,NULL,NULL,CURRENT_TIMESTAMP,'user:forged','evidence://forged',:hash,:hash)"
                ),
                {"hash": H["basis"]},
            )
        transaction.rollback()
        assert (
            connection.execute(
                text(
                    "SELECT has_function_privilege('public','fao.reserve_risk_budget(uuid,text,uuid,uuid,bigint,text,text,text,text,uuid,text,text,bigint,text,jsonb,numeric,numeric,numeric,timestamptz,timestamptz)'::regprocedure,'EXECUTE')"
                )
            ).scalar_one()
            is False
        )


def test_global_source_event_identity_is_idempotent_but_rejects_cross_projection_conflicts() -> None:
    engine = create_engine(DATABASE_URL)
    journal, episode, decision, source, correlation = (uuid4() for _ in range(5))
    now = _now()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fao.domain_event (event_id,aggregate_type,aggregate_id,aggregate_version,event_type,schema_version,correlation_id,idempotency_key,actor_ref,payload,payload_sha256,occurred_at,recorded_at) VALUES (:source,'Decision',:aggregate,1,'TradePlan','1',:correlation,'projection-source','service:test','{}'::jsonb,:hash,:now,:now)"
            ),
            {"source": source, "aggregate": uuid4(), "correlation": correlation, "hash": H["plan"], "now": now},
        )
    connection, transaction = _runtime(engine)
    try:
        assert connection.execute(
            text(
                "SELECT fao.append_decision_journal(:journal,1,:entry,:source,1,'POST_HOC','Decision','TradePlan',1,:hash,:now,:now,:now,NULL,:correlation)"
            ),
            {
                "journal": journal,
                "entry": uuid4(),
                "source": source,
                "hash": H["plan"],
                "now": now,
                "correlation": correlation,
            },
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT fao.append_trade_episode_projection(:episode,1,:decision,:source,'Decision','TradePlan',1,:now,:now,:correlation,:hash,:projection)"
            ),
            {
                "episode": episode,
                "decision": decision,
                "source": source,
                "now": now,
                "correlation": correlation,
                "hash": H["plan"],
                "projection": H["snapshot"],
            },
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT fao.append_trade_episode_projection(:episode,1,:decision,:source,'Decision','TradePlan',1,:now,:now,:correlation,:hash,:projection)"
            ),
            {
                "episode": episode,
                "decision": decision,
                "source": source,
                "now": now,
                "correlation": correlation,
                "hash": H["plan"],
                "projection": H["snapshot"],
            },
        ).scalar_one()
        assert not connection.execute(
            text(
                "SELECT fao.append_trade_episode_projection(:episode,1,:decision,:source,'Decision','TradePlan',1,:now,:now,:correlation,:hash,:projection)"
            ),
            {
                "episode": episode,
                "decision": decision,
                "source": source,
                "now": now,
                "correlation": correlation,
                "hash": H["approval"],
                "projection": H["snapshot"],
            },
        ).scalar_one()
        transaction.commit()
    finally:
        connection.close()


def test_trade_episode_projection_concurrent_replay_is_idempotent_and_conflicts_fail_closed() -> None:
    engine = create_engine(DATABASE_URL)
    now = _now()

    def create_source() -> tuple[UUID, UUID]:
        source, correlation = uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO fao.domain_event (event_id,aggregate_type,aggregate_id,aggregate_version,event_type,schema_version,correlation_id,idempotency_key,actor_ref,payload,payload_sha256,occurred_at,recorded_at) VALUES (:source,'Decision',:aggregate,1,'TradePlan','1',:correlation,:key,'service:test','{}'::jsonb,:hash,:now,:now)"
                ),
                {
                    "source": source,
                    "aggregate": uuid4(),
                    "correlation": correlation,
                    "key": str(uuid4()),
                    "hash": H["plan"],
                    "now": now,
                },
            )
        return source, correlation

    def append(episode: UUID, decision: UUID, source: UUID, correlation: UUID, projection: str) -> bool:
        connection, transaction = _runtime(engine)
        try:
            result = bool(
                connection.execute(
                    text(
                        "SELECT fao.append_trade_episode_projection(:episode,1,:decision,:source,'Decision','TradePlan',1,:now,:now,:correlation,:hash,:projection)"
                    ),
                    {
                        "episode": episode,
                        "decision": decision,
                        "source": source,
                        "now": now,
                        "correlation": correlation,
                        "hash": H["plan"],
                        "projection": projection,
                    },
                ).scalar_one()
            )
            transaction.commit()
            return result
        finally:
            connection.close()

    episode, decision = uuid4(), uuid4()
    source, correlation = create_source()
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(
            executor.map(lambda _: append(episode, decision, source, correlation, H["snapshot"]), range(2))
        ) == [True, True]
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM fao.trade_episode_projection WHERE episode_id=:episode"),
                {"episode": episode},
            ).scalar_one()
            == 1
        )
    conflict_episode, conflict_decision = uuid4(), uuid4()
    conflict_source, conflict_correlation = create_source()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda projection: append(
                    conflict_episode, conflict_decision, conflict_source, conflict_correlation, projection
                ),
                (H["snapshot"], H["runs"]),
            )
        )
    assert sorted(outcomes) == [False, True]
