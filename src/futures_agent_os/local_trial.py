"""One-command, simulation-only local end-to-end trial.

The trial uses deterministic synthetic market facts and the existing owner
boundaries.  It is intentionally a smoke path for a local operator, not a
production daemon and it never contacts an exchange or sends an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.agent_orchestration import (
    AutonomyGoldenCycle,
    CycleOutcome,
    DecisionJournalAppender,
)
from futures_agent_os.decision import Order, OrderStatus, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import L1Bar, SimulationEngine, run_manual_shadow_episode
from futures_agent_os.learning_review import DecisionJournal
from futures_agent_os.shared_kernel import EntityId, RecordedAt


@dataclass(frozen=True, slots=True)
class LocalTrialResult:
    """Reviewable output from a complete local simulation journey."""

    status: str
    outcome: str
    steps: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    journal_entries: int
    account_id: str
    open_fill_id: str
    protective_action_id: str
    exit_fill_id: str
    settlement_id: str
    ending_cash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "local-trial.v1",
            "status": self.status,
            "boundary": "RESEARCH_AND_SIMULATION_ONLY",
            "outcome": self.outcome,
            "steps": self.steps,
            "artifact_refs": self.artifact_refs,
            "journal_entries": self.journal_entries,
            "account_id": self.account_id,
            "open_fill_id": self.open_fill_id,
            "protective_action_id": self.protective_action_id,
            "exit_fill_id": self.exit_fill_id,
            "settlement_id": self.settlement_id,
            "ending_cash": self.ending_cash,
        }


def run_local_trial(at: datetime | None = None) -> LocalTrialResult:
    """Run the complete deterministic owner-mediated trial in memory.

    ``at`` is injectable so the result can be repeated byte-for-byte.  The
    default is the current UTC time for an operator-friendly invocation.
    """

    instant = (at or datetime.now(UTC)).astimezone(UTC)
    now = RecordedAt.from_datetime(instant)
    account_id = EntityId.deterministic("simulation_account", "local-trial")
    order = Order(
        EntityId.deterministic("order", "local-trial"),
        EntityId.deterministic("execution_plan", "local-trial"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=now,
    )
    entry = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
    exit_bar = L1Bar(Decimal("94"), Decimal("95"), Decimal("94"), Decimal("94"), Decimal("1"))
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    opened = SimulationEngine().execute_l1(order, entry, probe, now=now)
    if opened.fill is None:
        raise RuntimeError("local trial fixture did not produce an entry fill")
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "local-trial"),
        EntityId.deterministic("position_lot", str(opened.fill.fill_id)),
        Decimal("95"),
        Decimal("95"),
    )
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    holder: dict[str, Any] = {}

    def execute(_: str) -> CycleOutcome:
        report = run_manual_shadow_episode(
            order, account, open_bar=entry, exit_bar=exit_bar, stop_policy=policy, now=now
        )
        if (
            report.status != "SHADOW_COMPLETED"
            or report.protective_action is None
            or report.exit_fill is None
            or report.settlement is None
        ):
            raise RuntimeError(f"local trial simulation incomplete: {report.status}")
        holder["report"] = report
        return CycleOutcome.TRADE

    journal = DecisionJournal(EntityId.deterministic("decision_journal", "local-trial"))
    appender = DecisionJournalAppender(
        journal,
        now=now,
        correlation_id=EntityId.deterministic("autonomy_cycle", "local-trial"),
    )
    cycle = AutonomyGoldenCycle().run_full(
        snapshot=lambda: "snapshot:local-trial:v1",
        opportunity_scan=lambda _: "opportunity:ag-long:v1",
        strategy=lambda _: "trade-plan:local-trial:v1",
        critic=lambda _: "critique:pass:v1",
        authorize=lambda _, __: "authorization-basis:local-trial:v1",
        risk=lambda _, __: "risk-decision:permit:v1",
        execute=execute,
        protect=lambda _: f"protection:{holder['report'].protective_action.action_id}",
        notify=lambda _: "notification:trade-completed:v1",
        review=lambda _: "review:closed-episode:v1",
        journal_append=appender,
    )
    if cycle.outcome is not CycleOutcome.TRADE:
        raise RuntimeError(f"local trial cycle did not complete: {cycle.outcome} ({cycle.reason})")
    report = holder["report"]
    return LocalTrialResult(
        status="LOCAL_TRIAL_COMPLETED",
        outcome=cycle.outcome.value,
        steps=cycle.steps,
        artifact_refs=cycle.artifact_refs,
        journal_entries=len(journal.entries),
        account_id=str(account_id),
        open_fill_id=str(report.open_result.fill.fill_id),
        protective_action_id=str(report.protective_action.action_id),
        exit_fill_id=str(report.exit_fill.fill_id),
        settlement_id=str(report.settlement.settlement_id),
        ending_cash=str(report.replay_cash),
    )


__all__ = ["LocalTrialResult", "run_local_trial"]
