"""Transaction-owned, NO_LLM manual simulation acceptance API.

The request freezes the plan and both market inputs before approval. Only this
application commits a manual episode: approval, authorization, risk, order,
fills, protection, settlement and report share a PostgreSQL transaction. A
failed process has no durable CLAIMED state; a retry either runs the rolled
back command or reads its committed result. Accounts are isolated one-episode
test fixtures, not the V3 daily account workflow.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, text

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.execution_simulation.engine import SimulationEngine
from futures_agent_os.execution_simulation.fill_model import L1Bar
from futures_agent_os.execution_simulation.manual_shadow import run_manual_shadow_episode
from futures_agent_os.portfolio_risk import RiskBudgetLedger, RiskConstitution
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

from .autonomy_contracts import ApprovalAction, ApprovalScope, ExecutionOrigin, PlanApproval, PlanApprovalStatus
from .manual_test import _approval_from_payload, _approval_to_payload
from .postgres_repository import PostgresAutonomyRepository
from .submission import TradePlanSubmitter
from .submit_trade_plan import SubmitTradePlanService
from .trade_contracts import OrderStatus, StopPolicy, TradePlan, _canonical_value


def _wire(value: Any) -> Any:
    return json.loads(json.dumps(_canonical_value(value), allow_nan=False))


def _bar(value: dict[str, Any]) -> L1Bar:
    quantity = value.get("available_quantity", value.get("volume"))
    if quantity is None:
        raise ValueError("bar available quantity missing")
    return L1Bar(
        open=Decimal(value["open"]),
        high=Decimal(value["high"]),
        low=Decimal(value["low"]),
        close=Decimal(value["close"]),
        available_quantity=Decimal(quantity),
    )


def replay_manual_episode(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute an isolated episode from frozen inputs, never touching its DB."""
    if report.get("schema_version") != "manual-episode.v2":
        raise ValueError("unsupported manual episode")
    request = report["request"]
    plan = TradePlan.hydrate(request["plan"])
    facts = report["facts"]
    order = replace(SubmitTradePlanService._recovered_order(facts["order"]), status=OrderStatus.WORKING)
    if (
        facts["basis"]["plan_hash"] != plan.plan_hash
        or facts["receipt"]["execution_origin"] != "MANUAL_TEST"
        or facts["risk"]["plan_id"] != str(plan.plan_id)
        or facts["receipt"]["basis_id"] != facts["basis"]["basis_id"]
        or facts["reservation"]["authorization_basis_id"] != facts["basis"]["basis_id"]
        or facts["risk"]["approved_quantity"] != str(order.quantity)
        or facts["receipt"]["plan_hash"] != plan.plan_hash
    ):
        raise ValueError("manual episode authorization chain mismatch")
    now = RecordedAt.parse(report["executed_at"])
    account = SimulationAccount(Decimal(request["initial_cash"]), account_id=plan.account_id)
    probe = SimulationAccount.restore(account.snapshot())
    preview = SimulationEngine().execute_l1(order, _bar(request["open_bar"]), probe, now=now)
    if preview.fill is None:
        raise ValueError("manual episode has no entry liquidity")
    stop = StopPolicy(
        EntityId.deterministic("stop_policy", str(order.order_id)),
        EntityId.deterministic("position_lot", str(preview.fill.fill_id)),
        plan.protection.stop_price,
        plan.protection.stop_price,
        created_at=now,
    )
    episode = run_manual_shadow_episode(
        order,
        account,
        open_bar=_bar(request["open_bar"]),
        exit_bar=_bar(request["exit_bar"]),
        stop_policy=stop,
        now=now,
    )
    computed = {"episode": _wire(episode), "account": _wire(account.snapshot()), "stop_policy": _wire(stop)}
    committed_episode = report["result"]["episode"]
    committed_account = report["result"]["account"]
    computed_ids = {
        "open": computed["episode"]["open_result"].get("fill", {}).get("fill_id"),
        "protective": computed["episode"]["protective_action"].get("action_id")
        if computed["episode"].get("protective_action")
        else None,
        "exit": computed["episode"]["exit_fill"].get("fill_id") if computed["episode"].get("exit_fill") else None,
        "settlement": computed["episode"]["settlement"].get("settlement_id")
        if computed["episode"].get("settlement")
        else None,
    }
    committed_ids = {
        "open": committed_episode["open_result"].get("fill", {}).get("fill_id"),
        "protective": committed_episode["protective_action"].get("action_id")
        if committed_episode.get("protective_action")
        else None,
        "exit": committed_episode["exit_fill"].get("fill_id") if committed_episode.get("exit_fill") else None,
        "settlement": committed_episode["settlement"].get("settlement_id")
        if committed_episode.get("settlement")
        else None,
    }
    if (
        computed["episode"]["status"] != committed_episode["status"]
        or computed["episode"].get("replay_cash") != committed_episode.get("replay_cash")
        or computed["account"]["state"]["cash"] != committed_account["state"]["cash"]
        or computed["account"]["state"]["realized_pnl"] != committed_account["state"]["realized_pnl"]
        or computed["account"]["state"]["lots"] != committed_account["state"]["lots"]
        or computed["stop_policy"] != report["result"]["stop_policy"]
        or computed_ids != committed_ids
    ):
        raise ValueError(
            f"manual episode replay differs from committed projection: {computed['account']['state']} != {committed_account['state']} stop={computed['stop_policy']} != {report['result']['stop_policy']}"
        )
    account.assert_conservation()
    return computed


class ManualTestApplication:
    """Local trusted-operator API; callers receive facts, never write handles.

    The operator must provision risk_budget_authority and a valid simulation
    health permit beforehand. This endpoint cannot activate or enlarge them.
    """

    def __init__(self, engine: Engine, constitution: RiskConstitution) -> None:
        self._engine = engine
        self._constitution = constitution
        self._repository = PostgresAutonomyRepository()

    def _append(
        self, connection: Connection, kind: str, seed: str, plan: TradePlan, payload: dict[str, Any], now: RecordedAt
    ) -> None:
        if not self._repository.append_execution_fact(
            connection,
            aggregate_id=EntityId.deterministic("audit_event", seed).value,
            aggregate_type=kind,
            payload=payload,
            correlation_id=plan.plan_id.value,
            now=now.value,
        ):
            raise ValueError("manual command replay conflicts with committed facts")

    def request(
        self,
        plan: TradePlan,
        *,
        open_bar: L1Bar,
        exit_bar: L1Bar,
        initial_cash: Decimal,
        session: str,
        actor: str,
        now: RecordedAt,
    ) -> PlanApproval:
        if TradePlanSubmitter.validate_plan(plan, now=now) != "PLAN_VALID":
            raise ValueError("manual request requires a valid protected plan")
        if not actor.startswith("user:") or any(c.isspace() for c in actor) or actor == "user:":
            raise ValueError("manual request requires a local operator")
        SimulationAccount(initial_cash, account_id=plan.account_id)
        approval = PlanApproval(
            EntityId.deterministic("plan_approval", plan.plan_hash),
            1,
            PlanApprovalStatus.REQUESTED,
            plan.plan_id,
            plan.version,
            plan.plan_hash,
            plan.account_id,
            ApprovalScope(
                plan.account_id,
                (plan.instrument,),
                (plan.strategy_ref,),
                (session,),
                frozenset({ApprovalAction.OPEN}),
                plan.quantity,
                now,
                plan.expires_at,
            ),
            EntityId.deterministic("approval_token", plan.plan_hash),
            actor,
            plan.expires_at,
            now,
        )
        request = {
            "plan": plan.to_dict(),
            "approval": _approval_to_payload(approval),
            "open_bar": _wire(open_bar),
            "exit_bar": _wire(exit_bar),
            "initial_cash": str(initial_cash),
            "session": session,
            "constitution": _wire(self._constitution),
        }
        scope = {
            "account_id": str(plan.account_id.value),
            "instruments": [plan.instrument],
            "strategies": [plan.strategy_ref],
            "sessions": [session],
            "actions": ["OPEN"],
            "quantity_ceiling": str(plan.quantity),
            "window_start_at": now.value.isoformat(),
            "window_end_at": plan.expires_at.value.isoformat(),
        }
        with self._engine.begin() as connection:
            self._append(connection, "ManualTestRequest", str(approval.approval_id), plan, _wire(request), now)
            connection.execute(
                text("""INSERT INTO fao.plan_approval
                (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,
                 expires_at,requested_at,requested_by,approval_hash,approval_token,scope_sha256,
                 scope_account_id,allowed_actions,quantity_ceiling,window_start_at,window_end_at)
                VALUES (:id,1,'REQUESTED',:plan,:version,:hash,CAST(:scope AS jsonb),:expiry,:now,
                 :actor,:approval_hash,:token,:scope_hash,:account,'["OPEN"]'::jsonb,:quantity,:now,:expiry)
                ON CONFLICT (approval_id,version) DO NOTHING"""),
                {
                    "id": approval.approval_id.value,
                    "plan": plan.plan_id.value,
                    "version": plan.version,
                    "hash": plan.plan_hash,
                    "scope": json.dumps(scope),
                    "expiry": plan.expires_at.value,
                    "now": now.value,
                    "actor": actor,
                    "approval_hash": approval.authorization_hash,
                    "token": approval.approval_token.value,
                    "scope_hash": approval.scope.scope_hash,
                    "account": plan.account_id.value,
                    "quantity": plan.quantity,
                },
            )
        return approval

    def _load(self, connection: Connection, approval_id: EntityId) -> tuple[dict[str, Any], PlanApproval]:
        row = (
            connection.execute(
                text("SELECT * FROM fao.plan_approval WHERE approval_id=:id ORDER BY version DESC LIMIT 1 FOR UPDATE"),
                {"id": approval_id.value},
            )
            .mappings()
            .one()
        )
        request = connection.execute(
            text("SELECT payload FROM fao.domain_event WHERE aggregate_type='ManualTestRequest' AND aggregate_id=:id"),
            {"id": EntityId.deterministic("audit_event", str(approval_id)).value},
        ).scalar_one()
        original = _approval_from_payload(request["approval"])
        current = replace(
            original,
            version=row["version"],
            status=PlanApprovalStatus(row["status"]),
            decided_at=RecordedAt.from_datetime(row["decided_at"]) if row["decided_at"] else None,
            decided_by=row["decided_by"],
            consumed_at=RecordedAt.from_datetime(row["consumed_at"]) if row["consumed_at"] else None,
            consumer_basis_id=EntityId("authorization_basis", row["consumed_basis_id"])
            if row["consumed_basis_id"]
            else None,
        )
        return dict(request), current

    def decide(self, approval_id: EntityId, status: PlanApprovalStatus, *, actor: str, now: RecordedAt) -> PlanApproval:
        if status not in {PlanApprovalStatus.GRANTED, PlanApprovalStatus.REJECTED, PlanApprovalStatus.EXPIRED}:
            raise ValueError("unsupported manual decision")
        with self._engine.begin() as connection:
            request, current = self._load(connection, approval_id)
            if current.status is status:
                return current
            updated = (
                replace(current, status=PlanApprovalStatus.EXPIRED, version=current.version + 1)
                if status is PlanApprovalStatus.EXPIRED
                else current.decide(status, now, actor=actor)
            )
            connection.execute(
                text("""UPDATE fao.plan_approval SET version=:version,status=:status,
                state_version=state_version+1,decided_at=:at,decided_by=:actor,approval_hash=:hash
                WHERE approval_id=:id AND version=:previous"""),
                {
                    "version": updated.version,
                    "status": updated.status.value,
                    "at": updated.decided_at.value if updated.decided_at else None,
                    "actor": updated.decided_by,
                    "hash": updated.authorization_hash,
                    "id": approval_id.value,
                    "previous": current.version,
                },
            )
            self._append(
                connection,
                "ManualApprovalDecision",
                f"{approval_id}:{updated.version}",
                TradePlan.hydrate(request["plan"]),
                _approval_to_payload(updated),
                now,
            )
            return updated

    def run(self, approval_id: EntityId, *, now: RecordedAt) -> dict[str, Any]:
        """Consume once and commit one complete SHADOW-validated simulation."""
        with self._engine.begin() as connection:
            request, approval = self._load(connection, approval_id)
            plan = TradePlan.hydrate(request["plan"])
            existing = self._report(connection, approval_id)
            if existing is not None:
                return existing
            if request["constitution"] != _wire(self._constitution):
                raise ValueError("manual fixture risk policy changed; request a new plan")
            # Serialize the account as well as its approval. A test fixture is
            # consumed once; we must never reset the cash of an existing account.
            connection.execute(
                text("SELECT account_id FROM fao.risk_budget_authority WHERE account_id=:id FOR UPDATE"),
                {"id": plan.account_id.value},
            ).all()
            if connection.execute(
                text(
                    "SELECT 1 FROM fao.domain_event WHERE aggregate_type='ManualEpisode' AND payload->>'account_id'=:id"
                ),
                {"id": str(plan.account_id)},
            ).first():
                raise ValueError("manual test account fixture already used")
            service = SubmitTradePlanService(
                constitution=self._constitution,
                risk_ledger=RiskBudgetLedger(
                    self._constitution.max_single_loss,
                    self._constitution.ref,
                    self._constitution.version,
                    self._constitution.content_hash,
                ),
            )
            submitted = service._submit_durable(
                plan,
                now=now,
                execution_origin=ExecutionOrigin.MANUAL_TEST,
                snapshot_hash=canonical_sha256(request["open_bar"]),
                snapshot_expires_at=plan.expires_at,
                run_versions_hash=canonical_sha256({"fixture": "manual-episode.v2"}),
                session=request["session"],
                approval=approval,
                approval_allowed=True,
                durable_repository=self._repository,
                durable_connection=connection,
            )
            if submitted.outcome != "SUBMITTED" or submitted.order is None or submitted.risk is None:
                raise ValueError(f"manual submission rejected: {submitted.reason}")
            order = replace(submitted.order, status=OrderStatus.WORKING)
            account = SimulationAccount(Decimal(request["initial_cash"]), account_id=plan.account_id)
            assert submitted.reservation is not None
            account.reserve_margin(submitted.reservation.margin)
            probe = SimulationAccount.restore(account.snapshot())
            opened = SimulationEngine().execute_l1(order, _bar(request["open_bar"]), probe, now=now)
            if opened.fill is None:
                raise ValueError("manual shadow has no entry liquidity")
            stop = StopPolicy(
                EntityId.deterministic("stop_policy", str(order.order_id)),
                EntityId.deterministic("position_lot", str(opened.fill.fill_id)),
                plan.protection.stop_price,
                plan.protection.stop_price,
                created_at=now,
            )
            episode = run_manual_shadow_episode(
                order,
                account,
                open_bar=_bar(request["open_bar"]),
                exit_bar=_bar(request["exit_bar"]),
                stop_policy=stop,
                now=now,
            )
            if episode.status != "SHADOW_COMPLETED":
                raise ValueError(f"manual shadow incomplete: {episode.status}")
            account.release_margin(submitted.reservation.margin)
            facts = {
                "plan": plan.to_dict(),
                "approval": _approval_to_payload(approval),
                "basis": _wire(submitted.basis),
                "reservation": _wire(submitted.reservation),
                "receipt": _wire(submitted.receipt),
                "risk": _wire(submitted.risk),
                "protection": _wire(submitted.protection),
                "execution_plan": _wire(submitted.execution_plan),
                "order": service._order_payload(order, plan=plan),
                "ledger": _wire(submitted.ledger),
            }
            report = {
                "schema_version": "manual-episode.v2",
                "status": "SHADOW_COMPLETED",
                "approval_id": str(approval_id),
                "account_id": str(plan.account_id),
                "execution_origin": "MANUAL_TEST",
                "executed_at": now.to_dict()["recorded_at"],
                "request": request,
                "facts": facts,
                "result": {"episode": _wire(episode), "account": _wire(account.snapshot()), "stop_policy": _wire(stop)},
            }
            report = _wire(report)
            replay_manual_episode(report)
            for name, payload in facts.items():
                self._append(
                    connection,
                    "ManualTradeFact",
                    f"{approval_id}:{name}",
                    plan,
                    {"kind": name, "plan_id": str(plan.plan_id), "fact": payload},
                    now,
                )
            self._append(connection, "ManualEpisode", f"{approval_id}:episode", plan, report, now)
            return report

    def _report(self, connection: Connection, approval_id: EntityId) -> dict[str, Any] | None:
        result = connection.execute(
            text("SELECT payload FROM fao.domain_event WHERE aggregate_type='ManualEpisode' AND aggregate_id=:id"),
            {"id": EntityId.deterministic("audit_event", f"{approval_id}:episode").value},
        ).scalar_one_or_none()
        return dict(result) if result is not None else None

    def report(self, approval_id: EntityId) -> dict[str, Any]:
        with self._engine.connect() as connection:
            result = self._report(connection, approval_id)
        if result is None:
            raise ValueError("no committed manual episode")
        replay_manual_episode(result)
        return result
