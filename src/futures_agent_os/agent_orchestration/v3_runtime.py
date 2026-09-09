"""Deterministic V3 qualification, watch and bounded-cycle contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, cast
import math
import hashlib
import json
from decimal import Decimal

from futures_agent_os.execution_simulation.protection import (
    ProtectionTriggerEvaluator,
)
from futures_agent_os.decision import PositionLot, StopPolicy
from futures_agent_os.decision.risk_reduction import (
    ProtectionTriggerKind,
    RiskReductionRequest as _CanonicalRiskReductionRequest,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


class QualificationStatus(StrEnum):
    REGISTERED = "REGISTERED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class AgentVersion:
    role: str
    version: str
    prompt_ref: str
    model_ref: str
    toolset_ref: str
    baseline_ref: str = "baseline:unspecified"
    status: QualificationStatus = QualificationStatus.REGISTERED

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.role, self.version, self.prompt_ref, self.model_ref, self.toolset_ref, self.baseline_ref)
        ):
            raise ValueError("agent version requires role, version and immutable refs")


@dataclass(frozen=True, slots=True)
class EvaluationScorecard:
    metrics: dict[str, float]
    thresholds: dict[str, float]

    REQUIRED = frozenset(
        {
            "opportunity_coverage",
            "opportunity_precision",
            "no_trade_discipline",
            "unnecessary_trade_rate",
            "mandate_adherence",
            "notification_precision",
            "delegation",
            "handoff",
            "conflict_handling",
            "budget_exhaustion",
            "timeout_handling",
            "tool_scope_errors",
            "model_degradation",
        }
    )

    def __post_init__(self) -> None:
        if set(self.metrics) != set(self.thresholds) or set(self.metrics) != self.REQUIRED:
            raise ValueError("scorecard must cover every registered evaluation dimension")
        if any(not math.isfinite(float(v)) for values in (self.metrics, self.thresholds) for v in values.values()):
            raise ValueError("scorecard values must be finite")

    @property
    def digest(self) -> str:
        payload = json.dumps({"metrics": self.metrics, "thresholds": self.thresholds}, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()


class QualificationRegistry:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], AgentVersion] = {}
        self._events: list[str] = []

    def register(self, version: AgentVersion) -> AgentVersion:
        key = (version.role, version.version)
        if key in self._versions:
            raise ValueError("agent version already registered")
        self._versions[key] = version
        self._events.append(f"REGISTER:{version.role}:{version.version}:{version.baseline_ref}")
        return version

    def qualify(
        self, role: str, version: str, *, metrics: dict[str, float], thresholds: dict[str, float]
    ) -> AgentVersion:
        current = self._versions[(role, version)]
        if (
            not metrics
            or not thresholds
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for values in (metrics, thresholds)
                for value in values.values()
            )
        ):
            raise ValueError("qualification requires finite metrics and thresholds")
        if any(metrics.get(name, float("-inf")) < limit for name, limit in thresholds.items()):
            updated = AgentVersion(
                current.role,
                current.version,
                current.prompt_ref,
                current.model_ref,
                current.toolset_ref,
                current.baseline_ref,
                QualificationStatus.REJECTED,
            )
        else:
            updated = AgentVersion(
                current.role,
                current.version,
                current.prompt_ref,
                current.model_ref,
                current.toolset_ref,
                current.baseline_ref,
                QualificationStatus.QUALIFIED,
            )
        self._versions[(role, version)] = updated
        self._events.append(f"QUALIFY:{role}:{version}:{updated.status.value}")
        return updated

    def qualify_scorecard(self, role: str, version: str, scorecard: EvaluationScorecard) -> AgentVersion:
        """Qualify only from the complete, frozen evaluation dimension set."""
        if not isinstance(scorecard, EvaluationScorecard):
            raise TypeError("qualification requires an EvaluationScorecard")
        return self.qualify(role, version, metrics=scorecard.metrics, thresholds=scorecard.thresholds)

    def activate(self, role: str, version: str, *, actor: str = "user:operator") -> AgentVersion:
        current = self._versions[(role, version)]
        if current.status is not QualificationStatus.QUALIFIED:
            raise ValueError("only qualified versions may activate")
        if not actor.startswith("user:"):
            raise PermissionError("activation requires a human governance actor")
        updated = AgentVersion(
            current.role,
            current.version,
            current.prompt_ref,
            current.model_ref,
            current.toolset_ref,
            current.baseline_ref,
            QualificationStatus.ACTIVE,
        )
        self._versions[(role, version)] = updated
        self._events.append(f"ACTIVATE:{role}:{version}:{actor}")
        return updated

    def get(self, role: str, version: str) -> AgentVersion:
        return self._versions[(role, version)]

    @property
    def events(self) -> tuple[str, ...]:
        """Append-only lifecycle evidence; callers receive an immutable view."""
        return tuple(self._events)

    def snapshot(self) -> tuple[dict[str, str], ...]:
        """Export registry state as immutable, deterministic records."""
        return tuple(
            {
                "role": version.role,
                "version": version.version,
                "prompt_ref": version.prompt_ref,
                "model_ref": version.model_ref,
                "toolset_ref": version.toolset_ref,
                "baseline_ref": version.baseline_ref,
                "status": version.status.value,
            }
            for version in sorted(self._versions.values(), key=lambda value: (value.role, value.version))
        )

    @classmethod
    def from_snapshot(cls, records: tuple[dict[str, str], ...], events: tuple[str, ...]) -> "QualificationRegistry":
        registry = cls()
        for record in records:
            registry.register(
                AgentVersion(
                    record["role"],
                    record["version"],
                    record["prompt_ref"],
                    record["model_ref"],
                    record["toolset_ref"],
                    record["baseline_ref"],
                    QualificationStatus(record["status"]),
                )
            )
        registry._events = list(events)
        return registry


class WatchTrigger(StrEnum):
    MARKET = "MARKET"
    ORDER = "ORDER"
    POSITION = "POSITION"
    PORTFOLIO = "PORTFOLIO"
    SYSTEM = "SYSTEM"


class RiskReductionRequest(_CanonicalRiskReductionRequest):
    """Compatibility constructor for the canonical execution-owned request.

    Older V3 contract tests used a six-string shorthand.  It is translated to
    a typed, zero-target canonical request so the watch boundary never emits a
    second orchestration-owned risk intent type.
    """

    __slots__ = ()

    def __init__(self, *args: object, **kwargs: object) -> None:
        if len(args) == 6 and not kwargs:
            request_id, position_id, version, _target, reason, idempotency = args
            if not all(
                isinstance(value, str) and value.strip() for value in (request_id, position_id, reason, idempotency)
            ):
                raise ValueError("risk reduction request shorthand requires non-empty text")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("position version must be positive")
            now = RecordedAt.from_datetime(datetime.now(UTC))
            super().__init__(
                EntityId.deterministic("reduction_request", cast(str, request_id)),
                EntityId.deterministic("position_lot", cast(str, position_id)),
                version,
                Decimal("0"),
                None,
                ProtectionTriggerKind.THESIS_INVALIDATION,
                cast(str, idempotency),
                now,
            )
            return
        super().__init__(*cast(Any, args), **cast(Any, kwargs))


@dataclass(frozen=True, slots=True)
class WatchEvent:
    event_id: str
    trigger: WatchTrigger
    occurred_at: datetime
    payload_ref: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.payload_ref or self.occurred_at.tzinfo is None:
            raise ValueError("watch event requires id, timestamp and payload reference")


class DeterministicWatch:
    """Bounded lease/idempotency watch; only the injected owner creates reductions."""

    def __init__(
        self,
        owner: Callable[[WatchEvent], _CanonicalRiskReductionRequest | None],
        *,
        max_inflight: int = 1,
        cooldown_seconds: int = 0,
    ) -> None:
        if (
            isinstance(max_inflight, bool)
            or max_inflight < 1
            or isinstance(cooldown_seconds, bool)
            or cooldown_seconds < 0
        ):
            raise ValueError("watch bounds must be non-negative and max_inflight must be positive")
        self._owner = owner
        self._max_inflight = max_inflight
        self._cooldown_seconds = cooldown_seconds
        self._seen: set[str] = set()
        self._leases: set[str] = set()
        self._last_processed: dict[str, datetime] = {}

    def process(self, event: WatchEvent) -> _CanonicalRiskReductionRequest | None:
        if event.event_id in self._seen:
            return None
        if event.event_id in self._leases:
            return None
        if len(self._leases) >= self._max_inflight:
            return None
        prior = self._last_processed.get(event.payload_ref)
        if prior is not None and (event.occurred_at - prior).total_seconds() < self._cooldown_seconds:
            return None
        self._leases.add(event.event_id)
        try:
            result = self._owner(event)
            if result is not None and not isinstance(result, _CanonicalRiskReductionRequest):
                raise TypeError("watch owner must return RiskReductionRequest or None")
            self._seen.add(event.event_id)
            self._last_processed[event.payload_ref] = event.occurred_at
            return result
        finally:
            self._leases.discard(event.event_id)

    def process_with_retry(self, event: WatchEvent, *, max_attempts: int = 2) -> _CanonicalRiskReductionRequest | None:
        """Retry transient owner failure with the same idempotent event key."""
        if isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        for _ in range(max_attempts):
            try:
                return self.process(event)
            except RuntimeError, TimeoutError, ConnectionError:
                continue
        return None


class WatchCoordinator:
    """Routes continuous watch events to isolated domain watches."""

    def __init__(self, *, max_inflight: int = 1, cooldown_seconds: int = 0) -> None:
        self._max_inflight = max_inflight
        self._cooldown_seconds = cooldown_seconds
        self._watches: dict[WatchTrigger, DeterministicWatch] = {}
        self._degraded: set[WatchTrigger] = set()

    @classmethod
    def with_deterministic_protection(
        cls,
        facts_provider: Callable[[str], tuple[PositionLot, StopPolicy | None, RecordedAt, dict[str, object]]],
        *,
        agent_thesis_owner: Callable[[WatchEvent], _CanonicalRiskReductionRequest | None] | None = None,
        max_inflight: int = 1,
        cooldown_seconds: int = 0,
    ) -> "WatchCoordinator":
        """Build all five continuous domains on the hard protection owner.

        This is the production default: Agent Thesis Watch may be layered on
        top, while every domain still has an owner that can run from durable
        facts when LLM, Feishu, or research workers are unavailable.
        """
        coordinator = cls(max_inflight=max_inflight, cooldown_seconds=cooldown_seconds)
        owner = DeterministicProtectionWatchOwner(facts_provider)
        for trigger in WatchTrigger:
            if trigger is WatchTrigger.POSITION and agent_thesis_owner is not None:
                coordinator.register(trigger, agent_thesis_owner, fallback_owner=owner)
            else:
                coordinator.register(trigger, owner)
        return coordinator

    def register(
        self,
        trigger: WatchTrigger,
        owner: Callable[[WatchEvent], _CanonicalRiskReductionRequest | None],
        *,
        fallback_owner: Callable[[WatchEvent], _CanonicalRiskReductionRequest | None] | None = None,
    ) -> None:
        if not isinstance(trigger, WatchTrigger):
            raise TypeError("watch trigger must be typed")
        if trigger in self._watches:
            raise ValueError("watch trigger already registered")
        selected_owner = owner
        if fallback_owner is not None:

            def guarded_owner(event: WatchEvent) -> _CanonicalRiskReductionRequest | None:
                try:
                    result = owner(event)
                    if result is not None:
                        return result
                except RuntimeError, TimeoutError, ConnectionError, TypeError, ValueError:
                    pass
                return fallback_owner(event)

            selected_owner = guarded_owner
        self._watches[trigger] = DeterministicWatch(
            selected_owner, max_inflight=self._max_inflight, cooldown_seconds=self._cooldown_seconds
        )

    def process(self, event: WatchEvent) -> _CanonicalRiskReductionRequest | None:
        watch = self._watches.get(event.trigger)
        if watch is None:
            return None
        try:
            result = watch.process(event)
            self._degraded.discard(event.trigger)
            return result
        except TypeError, ValueError, RuntimeError:
            self._degraded.add(event.trigger)
            return None

    def process_with_retry(self, event: WatchEvent, *, max_attempts: int = 2) -> _CanonicalRiskReductionRequest | None:
        watch = self._watches.get(event.trigger)
        if watch is None:
            return None
        try:
            result = watch.process_with_retry(event, max_attempts=max_attempts)
            self._degraded.discard(event.trigger)
            return result
        except TypeError, ValueError, RuntimeError:
            self._degraded.add(event.trigger)
            return None

    @property
    def degraded_triggers(self) -> frozenset[WatchTrigger]:
        return frozenset(self._degraded)


class DeterministicProtectionWatchOwner:
    """Agent-independent protection owner for the hard reduction path.

    ``facts_provider`` reads the latest position/policy facts by immutable
    payload reference.  The provider may be backed by PostgreSQL or a replay
    snapshot; no LLM, channel adapter, or research worker is involved.
    """

    def __init__(
        self,
        facts_provider: Callable[[str], tuple[PositionLot, StopPolicy | None, RecordedAt, dict[str, object]]],
    ) -> None:
        self._facts_provider = facts_provider
        self._evaluator = ProtectionTriggerEvaluator()

    def __call__(self, event: WatchEvent) -> _CanonicalRiskReductionRequest | None:
        lot, policy, now, facts = self._facts_provider(event.payload_ref)
        if not isinstance(lot, PositionLot) or (policy is not None and not isinstance(policy, StopPolicy)):
            raise TypeError("protection watch facts must contain typed position and policy")
        if not isinstance(now, RecordedAt) or not isinstance(facts, dict):
            raise TypeError("protection watch facts are invalid")
        # An unprotected open position is always the highest-priority
        # deterministic fallback, regardless of Agent/Thesis availability.
        if self._evaluator.is_unprotected_open(lot, policy):
            return self._evaluator.kill_switch(lot, now)
        trigger = facts.get("trigger")
        if trigger is not None:
            if not isinstance(trigger, ProtectionTriggerKind):
                trigger = ProtectionTriggerKind(str(trigger))
            if trigger is ProtectionTriggerKind.INITIAL_STOP:
                if policy is None or "price" not in facts:
                    raise ValueError("initial stop requires policy and price")
                return self._evaluator.price_stop(lot, policy, Decimal(str(facts["price"])), now)
            if trigger is ProtectionTriggerKind.TRAILING_STOP:
                if policy is None or "price" not in facts:
                    raise ValueError("trailing stop requires policy and price")
                return self._evaluator.trailing_stop(lot, policy, Decimal(str(facts["price"])), now)
            if trigger is ProtectionTriggerKind.THESIS_INVALIDATION:
                return self._evaluator.thesis_invalidation(lot, now)
            return self._evaluator.trigger(lot, trigger, now)
        if policy is not None and "price" in facts:
            return self._evaluator.price_stop(lot, policy, Decimal(str(facts["price"])), now)
        return None
