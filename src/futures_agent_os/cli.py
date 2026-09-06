"""Local command-line entry point."""

import argparse
import json
from pathlib import Path
from typing import Any
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_agent_os.decision import (
    ApprovalAction,
    ApprovalScope,
    ExecutionOrigin,
    ManualTestApprovalStore,
    PlanApproval,
    PlanApprovalStatus,
)
from futures_agent_os.health import get_health_status
from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Order, OrderStatus, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import L1Bar, run_manual_shadow_episode
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="futures-agent-os")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("health", help="print the local health contract")
    manual = subcommands.add_parser("manual-test", help="simulation-only manual PlanApproval lifecycle")
    manual.add_argument("action", choices=("request", "grant", "reject", "expire", "consume", "shadow", "report"))
    manual.add_argument("--state", required=True, help="durable local state file")
    manual.add_argument("--approval-id")
    manual.add_argument("--plan-id")
    manual.add_argument("--plan-hash")
    manual.add_argument("--account-id")
    manual.add_argument("--instrument", default="SHFE_AG_2601")
    manual.add_argument("--strategy", default="strategy:manual-test")
    manual.add_argument("--session", default="DAY")
    manual.add_argument("--quantity", default="1")
    manual.add_argument("--expires-minutes", type=int, default=30)
    manual.add_argument("--basis-id")
    manual.add_argument("--at", default=None, help="UTC ISO-8601 timestamp")
    manual.add_argument("--actor", default="user:authorized")
    manual.add_argument("--entry-price", default="100")
    manual.add_argument("--stop-price", default="95")
    manual.add_argument("--exit-price", default="94")
    manual.add_argument("--report", default=None, help="durable shadow replay report path")
    return parser


def _manual_now(value: str | None) -> RecordedAt:
    if value is not None:
        return RecordedAt.parse(value)
    return RecordedAt.from_datetime(datetime.now(UTC))


def _manual_command(args: argparse.Namespace) -> int:
    store = ManualTestApprovalStore(args.state)
    now = _manual_now(args.at)
    if args.action == "request":
        if not args.plan_id or not args.account_id or not args.plan_hash:
            raise ValueError("request requires --plan-id, --account-id, and --plan-hash")
        account_id = EntityId.parse(args.account_id)
        plan_id = EntityId.parse(args.plan_id)
        approval = PlanApproval(
            EntityId.deterministic("plan_approval", f"{args.plan_id}:{args.plan_hash}:{args.actor}"),
            1,
            PlanApprovalStatus.REQUESTED,
            plan_id,
            1,
            args.plan_hash,
            account_id,
            ApprovalScope(
                account_id,
                (args.instrument,),
                (args.strategy,),
                (args.session,),
                frozenset({ApprovalAction.OPEN}),
                Decimal(args.quantity),
                now,
                RecordedAt.from_datetime(now.value + timedelta(minutes=args.expires_minutes)),
            ),
            EntityId.deterministic("approval_token", f"{args.plan_id}:{args.plan_hash}"),
            args.actor,
            RecordedAt.from_datetime(now.value + timedelta(minutes=args.expires_minutes)),
            now,
        )
        result = store.request(approval)
    else:
        if not args.approval_id:
            raise ValueError(f"{args.action} requires --approval-id")
        approval_id = EntityId.parse(args.approval_id)
        if args.action == "grant":
            result = store.decide(approval_id, PlanApprovalStatus.GRANTED, now, actor=args.actor)
        elif args.action == "reject":
            result = store.decide(approval_id, PlanApprovalStatus.REJECTED, now, actor=args.actor)
        elif args.action == "expire":
            result = store.expire(approval_id, now)
        elif args.action == "report":
            persisted_report = store.shadow_report(approval_id)
            if persisted_report is None:
                raise ValueError("no committed shadow report")
            report_path = _export_shadow_report(args, persisted_report)
            print(
                json.dumps(
                    {
                        "status": "REPORT_EXPORTED",
                        "report_path": str(report_path),
                        "report_hash": persisted_report["report_hash"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        elif args.action == "consume":
            if not args.basis_id:
                raise ValueError("consume requires --basis-id")
            persisted_approval = store.get(approval_id)
            if persisted_approval is None:
                raise KeyError(f"unknown approval: {approval_id}")
            result = store.consume(
                approval_id,
                now,
                EntityId.parse(args.basis_id),
                plan_id=persisted_approval.plan_id,
                plan_version=persisted_approval.plan_version,
                plan_hash=persisted_approval.plan_hash,
                account_id=persisted_approval.account_id,
                instrument=args.instrument,
                strategy=args.strategy,
                session=args.session,
                action=ApprovalAction.OPEN,
                quantity=Decimal(args.quantity),
            )
        else:
            shadow_approval = store.get(approval_id)
            if shadow_approval is None or shadow_approval.status is not PlanApprovalStatus.CONSUMED:
                raise ValueError("shadow requires a consumed PlanApproval")
            if not shadow_approval.scope.permits(
                shadow_approval.account_id,
                args.instrument,
                args.strategy,
                args.session,
                ApprovalAction.OPEN,
                Decimal(args.quantity),
                now,
            ):
                raise ValueError("shadow arguments exceed consumed approval scope")
            manual_account = SimulationAccount(Decimal("1000"), account_id=shadow_approval.account_id)
            order = Order(
                EntityId.deterministic("order", str(shadow_approval.plan_id)),
                EntityId.deterministic("execution_plan", str(shadow_approval.plan_id)),
                args.instrument,
                TradeDirection.LONG,
                Decimal(args.quantity),
                OrderStatus.WORKING,
                created_at=now,
            )
            # The runner derives the deterministic lot identity from the open fill.
            probe = SimulationAccount(Decimal("1000"), account_id=shadow_approval.account_id)
            from futures_agent_os.execution_simulation import SimulationEngine

            opened = SimulationEngine().execute_l1(
                order,
                L1Bar(
                    Decimal(args.entry_price),
                    Decimal(args.entry_price),
                    Decimal(args.entry_price),
                    Decimal(args.entry_price),
                    Decimal(args.quantity),
                ),
                probe,
                now=now,
            )
            if opened.fill is None:
                raise ValueError("shadow entry did not fill")
            policy = StopPolicy(
                EntityId.deterministic("stop_policy", str(shadow_approval.plan_id)),
                EntityId.deterministic("position_lot", str(opened.fill.fill_id)),
                Decimal(args.stop_price),
                Decimal(args.stop_price),
            )
            # Claim only after all argument parsing and deterministic setup has
            # succeeded; malformed input must not strand the approval.
            if not store.claim_shadow(approval_id, now):
                raise ValueError("shadow approval has already been consumed")
            try:
                report: Any = run_manual_shadow_episode(
                    order,
                    manual_account,
                    open_bar=L1Bar(
                        Decimal(args.entry_price),
                        Decimal(args.entry_price),
                        Decimal(args.entry_price),
                        Decimal(args.entry_price),
                        Decimal(args.quantity),
                    ),
                    exit_bar=L1Bar(
                        Decimal(args.exit_price),
                        Decimal(args.exit_price),
                        Decimal(args.exit_price),
                        Decimal(args.exit_price),
                        Decimal(args.quantity),
                    ),
                    stop_policy=policy,
                    now=now,
                )
            except Exception:
                # A claimed shadow is deliberately not released here: without
                # a durable owner/lease token, releasing would permit a
                # second process to execute the same approval concurrently.
                raise
            if (
                getattr(report, "status", None) != "SHADOW_COMPLETED"
                or report.protective_action is None
                or report.exit_fill is None
                or report.settlement is None
            ):
                raise ValueError(f"shadow simulation incomplete: {report.status}")
            report_payload: dict[str, Any] = {
                "schema_version": "manual-shadow-report.v1",
                "approval_id": str(approval_id),
                "account_id": str(shadow_approval.account_id),
                "basis_id": str(shadow_approval.consumer_basis_id),
                "execution_origin": ExecutionOrigin.MANUAL_TEST.value,
                "plan_id": str(shadow_approval.plan_id),
                "plan_version": shadow_approval.plan_version,
                "plan_hash": shadow_approval.plan_hash,
                "open_fill_id": str(report.open_result.fill.fill_id),
                "protective_action_id": str(report.protective_action.action_id),
                "exit_fill_id": str(report.exit_fill.fill_id),
                "settlement_id": str(report.settlement.settlement_id),
                "cash": str(report.replay_cash),
                "recorded_at": now.to_dict()["recorded_at"],
                "inputs": {
                    "entry_bar": {
                        "open": args.entry_price,
                        "high": args.entry_price,
                        "low": args.entry_price,
                        "close": args.entry_price,
                        "volume": args.quantity,
                    },
                    "exit_bar": {
                        "open": args.exit_price,
                        "high": args.exit_price,
                        "low": args.exit_price,
                        "close": args.exit_price,
                        "volume": args.quantity,
                    },
                    "stop_price": args.stop_price,
                    "quantity": args.quantity,
                    "instrument": args.instrument,
                    "strategy": args.strategy,
                    "session": args.session,
                },
            }
            report_payload["report_hash"] = canonical_sha256(report_payload)
            if not store.complete_shadow(approval_id, now, report=report_payload):
                raise ValueError("shadow completion claim was lost")
            # The report is already committed with completion. Export failure
            # can be recovered with 'manual-test report', without re-execution.
            report_path = _export_shadow_report(args, report_payload)
            print(
                json.dumps(
                    {
                        "status": "SHADOW_COMPLETED",
                        "approval_id": str(approval_id),
                        "basis_id": str(shadow_approval.consumer_basis_id),
                        "execution_origin": ExecutionOrigin.MANUAL_TEST.value,
                        "fill_id": str(report.open_result.fill.fill_id),
                        "protective_action_id": str(report.protective_action.action_id),
                        "exit_fill_id": str(report.exit_fill.fill_id),
                        "settlement_id": str(report.settlement.settlement_id),
                        "cash": str(report.replay_cash),
                        "report_hash": report_payload["report_hash"],
                        "report_path": str(report_path),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
    payload = {
        "status": result.approval.status.value,
        "approval_id": str(result.approval.approval_id),
        "changed": result.changed,
        "reason": result.reason,
    }
    if result.basis is not None:
        payload["basis_id"] = str(getattr(result.basis, "basis_id"))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _export_shadow_report(args: argparse.Namespace, payload: dict[str, Any]) -> Path:
    report_path = Path(args.report) if args.report else Path(args.state).with_suffix(".shadow.json")
    if report_path.resolve() == Path(args.state).resolve():
        raise ValueError("report must not overwrite approval state")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return report_path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "health":
        print(json.dumps(get_health_status().as_dict(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "manual-test":
        return _manual_command(args)
    return 2
