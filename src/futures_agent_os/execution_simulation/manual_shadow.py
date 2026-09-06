"""Deterministic MANUAL_TEST shadow episode runner."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any
from decimal import Decimal

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Order, OrderStatus, Settlement, StopPolicy, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from .engine import EngineResult, SimulationEngine
from .fill_model import FillOrderType, L1Bar, L1FillModel
from .protection import (
    ProtectionTriggerEvaluator,
    ProtectionValidator,
    ValidationOutcome,
    ProtectiveRiskAction,
    RiskReductionValidation,
)


@dataclass(frozen=True, slots=True)
class ManualShadowReport:
    open_result: EngineResult
    protection_validation: RiskReductionValidation | None
    protective_action: ProtectiveRiskAction | None
    exit_fill: Fill | None
    settlement: Settlement | None
    replay_cash: Decimal
    status: str = "SHADOW_COMPLETED"
    exit_order: Order | None = None


def verify_manual_shadow_report(path: str | Path) -> dict[str, Any]:
    """Load and verify a CLI shadow report without executing a trade."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "manual-shadow-report.v1":
        raise ValueError("invalid manual shadow report schema")
    recorded = payload.get("report_hash")
    if not isinstance(recorded, str):
        raise ValueError("manual shadow report hash missing")
    unsigned = dict(payload)
    del unsigned["report_hash"]
    if canonical_sha256(unsigned) != recorded:
        raise ValueError("manual shadow report hash mismatch")
    required = (
        "approval_id",
        "account_id",
        "basis_id",
        "plan_id",
        "plan_hash",
        "open_fill_id",
        "protective_action_id",
        "exit_fill_id",
        "settlement_id",
    )
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
        raise ValueError("manual shadow report has incomplete bindings")
    if payload.get("execution_origin") != "MANUAL_TEST":
        raise ValueError("manual shadow report origin mismatch")
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict) or any(
        not isinstance(inputs.get(key), str) for key in ("stop_price", "quantity", "instrument", "strategy", "session")
    ):
        raise ValueError("manual shadow report inputs missing")
    return payload


def replay_manual_shadow_report(path: str | Path) -> dict[str, Any]:
    """Deterministically replay a completed report's recorded inputs.

    This is intentionally simulation-only and does not consume authorization.
    """
    payload = verify_manual_shadow_report(path)
    inputs = payload["inputs"]

    def dec_bar(key: str) -> L1Bar:
        bar = inputs[key]
        if not isinstance(bar, dict):
            raise ValueError("report bar is invalid")
        return L1Bar(*(Decimal(str(bar[name])) for name in ("open", "high", "low", "close", "volume")))

    now = RecordedAt.parse(str(payload["recorded_at"]))
    account_id = EntityId.parse(str(payload["account_id"]))
    order = Order(
        EntityId.deterministic("order", str(payload["plan_id"])),
        EntityId.deterministic("execution_plan", str(payload["plan_id"])),
        str(inputs["instrument"]),
        TradeDirection.LONG,
        Decimal(str(inputs["quantity"])),
        OrderStatus.WORKING,
        created_at=now,
    )
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    opened = SimulationEngine().execute_l1(order, dec_bar("entry_bar"), probe, now=now)
    if opened.fill is None:
        raise ValueError("report replay has no entry fill")
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", str(payload["plan_id"])),
        EntityId.deterministic("position_lot", str(opened.fill.fill_id)),
        Decimal(str(inputs["stop_price"])),
        Decimal(str(inputs["stop_price"])),
    )
    replay = run_manual_shadow_episode(
        order,
        SimulationAccount(Decimal("1000"), account_id=account_id),
        open_bar=dec_bar("entry_bar"),
        exit_bar=dec_bar("exit_bar"),
        stop_policy=policy,
        now=now,
    )
    if (
        replay.open_result.fill is None
        or replay.protective_action is None
        or replay.exit_fill is None
        or replay.settlement is None
    ):
        raise ValueError("report replay did not complete")
    checks = {
        "open_fill_id": str(replay.open_result.fill.fill_id),
        "protective_action_id": str(replay.protective_action.action_id),
        "exit_fill_id": str(replay.exit_fill.fill_id),
        "settlement_id": str(replay.settlement.settlement_id),
        "cash": str(replay.replay_cash),
    }
    if any(payload[key] != value for key, value in checks.items()):
        raise ValueError("manual shadow replay mismatch")
    return payload


def run_manual_shadow_episode(
    order: Order,
    account: SimulationAccount,
    *,
    open_bar: L1Bar,
    exit_bar: L1Bar,
    stop_policy: StopPolicy,
    now: RecordedAt,
) -> ManualShadowReport:
    """Simulate an already-authorized order; this helper grants no authority.

    A triggered stop can remain pending or only partially fill. Settlement is
    emitted only after the episode is flat. Callers own authorization and
    durable orchestration; this function is not a durable submission endpoint.
    """
    if account.account_id is None or account.state.lots:
        raise ValueError("shadow episode requires an identified, flat account")
    if not stop_policy.active:
        raise ValueError("manual shadow requires active protection")
    # Validate the prospective lot binding before making any caller state change.
    candidate = SimulationAccount.restore(account.snapshot())
    preview = SimulationEngine().execute_l1(order, open_bar, candidate, now=now)
    if preview.fill is None:
        return ManualShadowReport(preview, None, None, None, None, account.state.cash, "NO_ENTRY_FILL")
    prospective_lot = candidate.state.lots[-1]
    if prospective_lot.lot_id != stop_policy.position_id:
        raise ValueError("manual shadow protection position mismatch")
    if (order.direction is TradeDirection.LONG and stop_policy.stop_price >= preview.fill.price) or (
        order.direction is TradeDirection.SHORT and stop_policy.stop_price <= preview.fill.price
    ):
        raise ValueError("manual shadow stop must be adverse to entry")
    opened = SimulationEngine().execute_l1(order, open_bar, account, now=now, order_type=FillOrderType.MARKET)
    if opened.fill is None:
        raise ValueError("manual shadow open did not fill")
    lot = account.state.lots[-1]
    trigger_price = exit_bar.low if lot.direction is TradeDirection.LONG else exit_bar.high
    request = ProtectionTriggerEvaluator().price_stop(lot, stop_policy, trigger_price, now)
    if request is None:
        return ManualShadowReport(opened, None, None, None, None, account.state.cash, "PROTECTED_OPEN")
    validation = ProtectionValidator().validate(request, lot, stop_policy, position_version=lot.version, now=now)
    validation = replace(
        validation, validation_id=EntityId.deterministic("reduction_validation", str(request.request_id))
    )
    if validation.outcome is not ValidationOutcome.VALIDATED:
        raise ValueError("manual shadow protection rejected")
    action = ProtectionValidator().action(request, validation, now=now)
    close_direction = TradeDirection.SHORT if lot.direction is TradeDirection.LONG else TradeDirection.LONG
    close_order = Order(
        EntityId.deterministic("order", f"protective-exit:{action.action_id}"),
        EntityId.deterministic("execution_plan", f"protective-exit:{action.action_id}"),
        order.instrument,
        close_direction,
        lot.quantity,
        OrderStatus.WORKING,
        stop_price=stop_policy.stop_price,
        created_at=now,
    )
    decision = L1FillModel().simulate(
        close_order, exit_bar, order_type=FillOrderType.STOP, stop_price=stop_policy.stop_price
    )
    if decision.price is None or decision.filled_quantity == 0:
        return ManualShadowReport(
            opened, validation, action, None, None, account.state.cash, "EXIT_PENDING", close_order
        )
    fill_seed = canonical_sha256(
        {
            "order": str(close_order.order_id),
            "price": str(decision.price),
            "quantity": str(decision.filled_quantity),
            "at": now.to_dict()["recorded_at"],
        }
    )
    exit_fill = Fill(
        EntityId.deterministic("fill", fill_seed),
        close_order.order_id,
        order.instrument,
        close_direction,
        decision.filled_quantity,
        decision.price,
        Decimal("0"),
        now,
    )
    account.close(exit_fill)
    close_order = close_order.apply_fill(exit_fill.quantity)
    if account.state.lots:
        return ManualShadowReport(
            opened, validation, action, exit_fill, None, account.state.cash, "EXIT_PARTIAL", close_order
        )
    settlement = account.mark_to_market(
        EntityId.deterministic("settlement", f"manual-shadow:{order.order_id}"),
        now.value.date().isoformat(),
        stop_policy.stop_price,
        now,
    )
    account.settle(settlement)
    account.assert_conservation()
    return ManualShadowReport(
        opened, validation, action, exit_fill, settlement, account.state.cash, exit_order=close_order
    )


__all__ = [
    "ManualShadowReport",
    "run_manual_shadow_episode",
    "verify_manual_shadow_report",
    "replay_manual_shadow_report",
]
