from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
import time
from futures_agent_os.learning_review import DecisionJournal, JournalPhase, SourceEvent
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


class DecisionJournalAppender:
    """Deterministic adapter from cycle refs to the Learning Review journal."""

    def __init__(self, journal: DecisionJournal, *, now: RecordedAt, correlation_id: EntityId) -> None:
        self._journal = journal
        self._now = now
        self._correlation_id = correlation_id

    def __call__(self, reference: str) -> bool:
        if not isinstance(reference, str) or not reference.strip():
            return False
        event_id = EntityId.deterministic("source_event", reference)
        source = SourceEvent(
            event_id,
            "autonomy_cycle",
            1,
            reference.split(":", 1)[0].lower() if ":" in reference else "cycle",
            self._now,
            self._now,
            canonical_sha256({"reference": reference}),
            self._correlation_id,
        )
        try:
            self._journal.append(source, JournalPhase.POST_HOC, self._now)
        except TypeError, ValueError:
            return False
        return True


class CycleOutcome(StrEnum):
    NO_TRADE = "NO_TRADE"
    TRADE = "TRADE"
    DEFER = "DEFER"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class CycleBudget:
    max_steps: int = 16
    max_tool_calls: int = 32
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0
            for v in (self.max_steps, self.max_tool_calls, self.timeout_seconds)
        ):
            raise ValueError("cycle budgets must be positive integers")


@dataclass(frozen=True, slots=True)
class CycleResult:
    outcome: CycleOutcome
    steps: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    reason: str


class BoundedAutonomyCycle:
    """Runs injected deterministic boundaries; it cannot create domain effects itself."""

    def __init__(self, budget: CycleBudget = CycleBudget()) -> None:
        self.budget = budget

    def run(
        self, *, scan: Callable[[], str], decide: Callable[[str], CycleOutcome], artifact_refs: tuple[str, ...] = ()
    ) -> CycleResult:
        started = time.monotonic()
        steps = ["SCAN"]
        if self.budget.max_tool_calls < 1:
            return CycleResult(CycleOutcome.DEFER, tuple(steps), artifact_refs, "tool budget exceeded")
        if len(steps) > self.budget.max_steps:
            return CycleResult(CycleOutcome.DEFER, tuple(steps), artifact_refs, "step budget exceeded")
        candidate = scan()
        if time.monotonic() - started > self.budget.timeout_seconds:
            return CycleResult(CycleOutcome.DEFER, tuple(steps), artifact_refs, "cycle timeout")
        steps.append("DECIDE")
        outcome = decide(candidate)
        if not isinstance(outcome, CycleOutcome):
            return CycleResult(CycleOutcome.REJECT, tuple(steps), artifact_refs, "invalid cycle outcome")
        if outcome is CycleOutcome.TRADE:
            steps.append("HANDOFF_TO_DETERMINISTIC_OWNER")
        return CycleResult(outcome, tuple(steps), artifact_refs, "completed")


class AutonomyGoldenCycle:
    """A no-user-callback composition boundary for injected V2 owner commands."""

    def __init__(self, budget: CycleBudget = CycleBudget()) -> None:
        self.budget = budget

    def run(
        self,
        *,
        snapshot: Callable[[], str],
        opportunity_scan: Callable[[str], str],
        strategy: Callable[[str], str],
        critic: Callable[[str], str],
        submit: Callable[[str, str], CycleOutcome],
    ) -> CycleResult:
        started = time.monotonic()
        steps = ["SNAPSHOT", "OPPORTUNITY_SCAN", "STRATEGY", "CRITIC", "OWNER_SUBMIT"]
        if len(steps) > self.budget.max_steps:
            return CycleResult(CycleOutcome.DEFER, tuple(steps[: self.budget.max_steps]), (), "step budget exceeded")
        if self.budget.max_tool_calls < len(steps):
            return CycleResult(CycleOutcome.DEFER, tuple(steps), (), "tool budget exceeded")
        snap = snapshot()
        if not snap:
            return CycleResult(CycleOutcome.DEFER, tuple(steps[:1]), (), "missing snapshot")
        candidate = opportunity_scan(snap)
        if not candidate:
            return CycleResult(CycleOutcome.NO_TRADE, tuple(steps[:2]), (snap,), "no opportunity")
        draft = strategy(candidate)
        if not draft:
            return CycleResult(CycleOutcome.DEFER, tuple(steps[:3]), (snap, candidate), "strategy produced no draft")
        critique = critic(draft)
        if not critique:
            return CycleResult(CycleOutcome.DEFER, tuple(steps[:4]), (snap, candidate, draft), "missing critique")
        if time.monotonic() - started > self.budget.timeout_seconds:
            return CycleResult(CycleOutcome.DEFER, tuple(steps), (snap, candidate, draft, critique), "cycle timeout")
        outcome = submit(draft, critique)
        if not isinstance(outcome, CycleOutcome):
            return CycleResult(
                CycleOutcome.REJECT, tuple(steps), (snap, candidate, draft, critique), "invalid cycle outcome"
            )
        return CycleResult(outcome, tuple(steps), (snap, candidate, draft, critique), "completed")

    def run_full(
        self,
        *,
        snapshot: Callable[[], str],
        opportunity_scan: Callable[[str], str],
        strategy: Callable[[str], str],
        critic: Callable[[str], str],
        authorize: Callable[[str, str], str],
        risk: Callable[[str, str], str],
        execute: Callable[[str], CycleOutcome],
        protect: Callable[[str], str],
        notify: Callable[[str], str],
        review: Callable[[str], str],
        journal_append: Callable[[str], bool] | None = None,
    ) -> CycleResult:
        """Run the complete owner-mediated V3-014 simulation cycle."""
        steps = [
            "SNAPSHOT",
            "OPPORTUNITY_SCAN",
            "STRATEGY_DELIBERATION",
            "PRE_TRADE_CRITIQUE",
            "AUTHORIZATION_BASIS",
            "RISK_DECISION",
            "SIMULATED_EXECUTION",
            "POSITION_PROTECTION",
            "IMPORTANT_NOTIFICATION",
            "POST_TRADE_REVIEW",
        ]
        if len(steps) > self.budget.max_steps or len(steps) > self.budget.max_tool_calls:
            return CycleResult(CycleOutcome.DEFER, tuple(steps), (), "cycle budget exceeded")
        started = time.monotonic()
        snap = snapshot()
        if not snap:
            return CycleResult(CycleOutcome.DEFER, (steps[0],), (), "missing snapshot")
        if journal_append is not None and not journal_append(snap):
            return CycleResult(CycleOutcome.DEFER, (steps[0],), (snap,), "journal append failed")
        candidate = opportunity_scan(snap)
        if not candidate:
            if journal_append is not None and not journal_append("NO_TRADE"):
                return CycleResult(CycleOutcome.DEFER, tuple(steps[:2]), (snap,), "journal append failed")
            return CycleResult(CycleOutcome.NO_TRADE, tuple(steps[:2]), (snap,), "no opportunity")
        draft = strategy(candidate)
        critique = critic(draft) if draft else ""
        basis = authorize(draft, critique) if critique else ""
        risk_result = risk(draft, basis) if basis else ""
        if not all((draft, critique, basis, risk_result)):
            return CycleResult(
                CycleOutcome.DEFER, tuple(steps[:5]), (snap, candidate, draft, critique), "incomplete owner evidence"
            )
        outcome = execute(risk_result)
        if not isinstance(outcome, CycleOutcome):
            return CycleResult(
                CycleOutcome.REJECT,
                tuple(steps[:7]),
                (snap, candidate, draft, critique, basis, risk_result),
                "invalid execution outcome",
            )
        protection = protect(risk_result)
        notification = notify(risk_result)
        reflection = review(risk_result)
        if not all((protection, notification, reflection)):
            return CycleResult(
                CycleOutcome.DEFER,
                tuple(steps[:8]),
                (snap, candidate, draft, critique, basis, risk_result),
                "incomplete post-trade owner evidence",
            )
        if journal_append is not None:
            for artifact in (candidate, draft, critique, basis, risk_result, protection, notification, reflection):
                if not journal_append(artifact):
                    return CycleResult(CycleOutcome.DEFER, tuple(steps), (), "journal append failed")
        if time.monotonic() - started > self.budget.timeout_seconds:
            return CycleResult(
                CycleOutcome.DEFER,
                tuple(steps),
                (snap, candidate, draft, critique, basis, risk_result),
                "cycle timeout",
            )
        return CycleResult(
            outcome,
            tuple(steps),
            (snap, candidate, draft, critique, basis, risk_result, protection, notification, reflection),
            "completed",
        )
