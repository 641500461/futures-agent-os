"""Wall-clock stability-run journal and completion gate for V5-011."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, cast

from futures_agent_os.accounting_settlement import DurableAuditLog, SimulationAccount
from futures_agent_os.decision import Order, OrderStatus, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import L1Bar, ProtectionTriggerEvaluator, SimulationEngine
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256


_GENESIS = "0" * 64
_MINIMUM_DURATION = timedelta(days=30)


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical text")


def _digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class StabilityRunPlan:
    run_id: str
    started_at: RecordedAt
    minimum_end_at: RecordedAt
    code_commit: str
    environment: str
    heartbeat_interval_seconds: int = 900
    maximum_single_gap_seconds: int = 3600
    maximum_total_gap_seconds: int = 21600

    def __post_init__(self) -> None:
        for value, label in (
            (self.run_id, "run_id"),
            (self.code_commit, "code_commit"),
            (self.environment, "environment"),
        ):
            _text(value, label)
        if not isinstance(self.started_at, RecordedAt) or not isinstance(self.minimum_end_at, RecordedAt):
            raise TypeError("stability plan requires RecordedAt boundaries")
        if self.minimum_end_at.value - self.started_at.value < _MINIMUM_DURATION:
            raise ValueError("stability plan must cover at least 30 real days")
        values = (self.heartbeat_interval_seconds, self.maximum_single_gap_seconds, self.maximum_total_gap_seconds)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ValueError("stability cadence and gap budgets must be positive integers")
        if self.maximum_single_gap_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("single-gap threshold must exceed the heartbeat interval")
        if self.maximum_total_gap_seconds < self.maximum_single_gap_seconds:
            raise ValueError("total gap budget cannot be below the single-gap threshold")
        if self.environment not in {"local", "test", "staging", "sim-prod"}:
            raise ValueError("stability environment must be a simulation environment")

    @property
    def digest(self) -> str:
        return canonical_sha256(cast(Any, self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.to_dict()["recorded_at"],
            "minimum_end_at": self.minimum_end_at.to_dict()["recorded_at"],
            "code_commit": self.code_commit,
            "environment": self.environment,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "maximum_single_gap_seconds": self.maximum_single_gap_seconds,
            "maximum_total_gap_seconds": self.maximum_total_gap_seconds,
        }

    @classmethod
    def from_payload(cls, value: object) -> StabilityRunPlan:
        if not isinstance(value, dict):
            raise ValueError("stability plan payload must be an object")
        required = {
            "run_id",
            "started_at",
            "minimum_end_at",
            "code_commit",
            "environment",
            "heartbeat_interval_seconds",
            "maximum_single_gap_seconds",
            "maximum_total_gap_seconds",
        }
        if set(value) != required:
            raise ValueError("stability plan payload fields are not exact")
        return cls(
            str(value["run_id"]),
            RecordedAt.parse(str(value["started_at"])),
            RecordedAt.parse(str(value["minimum_end_at"])),
            str(value["code_commit"]),
            str(value["environment"]),
            int(str(value["heartbeat_interval_seconds"])),
            int(str(value["maximum_single_gap_seconds"])),
            int(str(value["maximum_total_gap_seconds"])),
        )


@dataclass(frozen=True, slots=True)
class StabilityIncident:
    incident_id: str
    category: str
    detected_at: RecordedAt
    recovered_at: RecordedAt
    report_ref: str
    downtime_seconds: Decimal

    def __post_init__(self) -> None:
        for value, label in (
            (self.incident_id, "incident_id"),
            (self.category, "category"),
            (self.report_ref, "report_ref"),
        ):
            _text(value, label)
        if not isinstance(self.detected_at, RecordedAt) or not isinstance(self.recovered_at, RecordedAt):
            raise TypeError("incident requires RecordedAt boundaries")
        if self.recovered_at.value <= self.detected_at.value:
            raise ValueError("incident recovery must follow detection")
        if not isinstance(self.downtime_seconds, Decimal) or not self.downtime_seconds.is_finite():
            raise ValueError("incident downtime must be finite")
        if self.downtime_seconds <= 0:
            raise ValueError("incident downtime must be positive")

    def to_payload(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "category": self.category,
            "detected_at": self.detected_at.to_dict()["recorded_at"],
            "recovered_at": self.recovered_at.to_dict()["recorded_at"],
            "report_ref": self.report_ref,
            "downtime_seconds": str(self.downtime_seconds),
        }

    @classmethod
    def from_payload(cls, value: object) -> StabilityIncident:
        if not isinstance(value, dict) or set(value) != {
            "incident_id",
            "category",
            "detected_at",
            "recovered_at",
            "report_ref",
            "downtime_seconds",
        }:
            raise ValueError("incident payload fields are not exact")
        return cls(
            str(value["incident_id"]),
            str(value["category"]),
            RecordedAt.parse(str(value["detected_at"])),
            RecordedAt.parse(str(value["recovered_at"])),
            str(value["report_ref"]),
            Decimal(str(value["downtime_seconds"])),
        )


@dataclass(frozen=True, slots=True)
class StabilityHeartbeat:
    run_id: str
    sequence: int
    bucket: int
    recorded_at: RecordedAt
    code_commit: str
    health_ok: bool
    simulated_trade_count: int
    duplicate_trade_count: int
    unprotected_position_count: int
    audit_chain_break_count: int
    ledger_difference: Decimal
    incidents: tuple[StabilityIncident, ...]
    previous_digest: str
    digest: str

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _text(self.code_commit, "code_commit")
        if self.sequence < 1 or self.bucket < 0:
            raise ValueError("heartbeat sequence must be positive and bucket non-negative")
        if not isinstance(self.recorded_at, RecordedAt) or not isinstance(self.health_ok, bool):
            raise TypeError("heartbeat requires typed timestamp and health")
        counts = (
            self.simulated_trade_count,
            self.duplicate_trade_count,
            self.unprotected_position_count,
            self.audit_chain_break_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("heartbeat invariant counts must be non-negative integers")
        if not isinstance(self.ledger_difference, Decimal) or not self.ledger_difference.is_finite():
            raise ValueError("heartbeat ledger difference must be finite")
        if self.ledger_difference < 0:
            raise ValueError("heartbeat ledger difference cannot be negative")
        if not isinstance(self.incidents, tuple) or any(
            not isinstance(item, StabilityIncident) for item in self.incidents
        ):
            raise TypeError("heartbeat incidents must be immutable typed values")
        _digest(self.previous_digest, "previous_digest")
        _digest(self.digest, "digest")
        if self.digest != canonical_sha256(cast(Any, self.hash_payload())):
            raise ValueError("heartbeat digest does not match its payload")

    @classmethod
    def issue(
        cls,
        *,
        run_id: str,
        sequence: int,
        bucket: int,
        recorded_at: RecordedAt,
        code_commit: str,
        health_ok: bool,
        simulated_trade_count: int,
        duplicate_trade_count: int,
        unprotected_position_count: int,
        audit_chain_break_count: int,
        ledger_difference: Decimal,
        incidents: tuple[StabilityIncident, ...],
        previous_digest: str,
    ) -> StabilityHeartbeat:
        payload: dict[str, object] = {
            "run_id": run_id,
            "sequence": sequence,
            "bucket": bucket,
            "recorded_at": recorded_at.to_dict()["recorded_at"],
            "code_commit": code_commit,
            "health_ok": health_ok,
            "simulated_trade_count": simulated_trade_count,
            "duplicate_trade_count": duplicate_trade_count,
            "unprotected_position_count": unprotected_position_count,
            "audit_chain_break_count": audit_chain_break_count,
            "ledger_difference": str(ledger_difference),
            "incidents": tuple(incident.to_payload() for incident in incidents),
            "previous_digest": previous_digest,
        }
        return cls(
            run_id,
            sequence,
            bucket,
            recorded_at,
            code_commit,
            health_ok,
            simulated_trade_count,
            duplicate_trade_count,
            unprotected_position_count,
            audit_chain_break_count,
            ledger_difference,
            incidents,
            previous_digest,
            canonical_sha256(cast(Any, payload)),
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "bucket": self.bucket,
            "recorded_at": self.recorded_at.to_dict()["recorded_at"],
            "code_commit": self.code_commit,
            "health_ok": self.health_ok,
            "simulated_trade_count": self.simulated_trade_count,
            "duplicate_trade_count": self.duplicate_trade_count,
            "unprotected_position_count": self.unprotected_position_count,
            "audit_chain_break_count": self.audit_chain_break_count,
            "ledger_difference": str(self.ledger_difference),
            "incidents": tuple(incident.to_payload() for incident in self.incidents),
            "previous_digest": self.previous_digest,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.hash_payload(), "digest": self.digest}

    @classmethod
    def from_payload(cls, value: object) -> StabilityHeartbeat:
        if not isinstance(value, dict):
            raise ValueError("heartbeat payload must be an object")
        required = {
            "run_id",
            "sequence",
            "bucket",
            "recorded_at",
            "code_commit",
            "health_ok",
            "simulated_trade_count",
            "duplicate_trade_count",
            "unprotected_position_count",
            "audit_chain_break_count",
            "ledger_difference",
            "incidents",
            "previous_digest",
            "digest",
        }
        if set(value) != required or not isinstance(value["incidents"], (list, tuple)):
            raise ValueError("heartbeat payload fields are not exact")
        return cls(
            str(value["run_id"]),
            int(str(value["sequence"])),
            int(str(value["bucket"])),
            RecordedAt.parse(str(value["recorded_at"])),
            str(value["code_commit"]),
            value["health_ok"],
            int(str(value["simulated_trade_count"])),
            int(str(value["duplicate_trade_count"])),
            int(str(value["unprotected_position_count"])),
            int(str(value["audit_chain_break_count"])),
            Decimal(str(value["ledger_difference"])),
            tuple(StabilityIncident.from_payload(item) for item in value["incidents"]),
            str(value["previous_digest"]),
            str(value["digest"]),
        )


@dataclass(frozen=True, slots=True)
class StabilityEvaluation:
    complete: bool
    reason_codes: tuple[str, ...]
    heartbeat_count: int
    elapsed_seconds: Decimal
    total_gap_seconds: Decimal
    incident_count: int
    final_digest: str | None


@dataclass(frozen=True, slots=True)
class StabilityProbeResult:
    """Measured result of one deterministic, research-only simulation episode."""

    health_ok: bool
    simulated_trade_count: int
    duplicate_trade_count: int
    unprotected_position_count: int
    audit_chain_break_count: int
    ledger_difference: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.health_ok, bool):
            raise TypeError("probe health must be a bool")
        counts = (
            self.simulated_trade_count,
            self.duplicate_trade_count,
            self.unprotected_position_count,
            self.audit_chain_break_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("probe counts must be non-negative integers")
        if (
            not isinstance(self.ledger_difference, Decimal)
            or not self.ledger_difference.is_finite()
            or self.ledger_difference < 0
        ):
            raise ValueError("probe ledger difference must be finite and non-negative")


def run_simulation_stability_probe(*, now: RecordedAt) -> StabilityProbeResult:
    """Execute the production simulation path and measure its critical invariants.

    The episode is isolated and never reaches an external venue.  It exercises
    deterministic fill creation, duplicate-fill suppression, durable audit
    persistence/reload, deterministic ledger replay/reconciliation, and active
    protection coverage for every resulting open lot.
    """
    if not isinstance(now, RecordedAt):
        raise TypeError("stability probe requires RecordedAt")
    seed = now.to_dict()["recorded_at"]
    account_id = EntityId.deterministic("simulation_account", f"v5-011:{seed}")
    order = Order(
        EntityId.deterministic("order", f"v5-011:{seed}"),
        EntityId.deterministic("execution_plan", f"v5-011:{seed}"),
        "SHFE_AG_SIM",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=now,
        source_ref="source:v5-011:stability-probe",
    )
    account = SimulationAccount(Decimal("1000000"), account_id=account_id)
    result = SimulationEngine().execute_l1(
        order,
        L1Bar(Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("10")),
        account,
        now=now,
    )
    if result.fill is None:
        return StabilityProbeResult(False, 0, 0, 0, 0, Decimal("1"))

    before_duplicate = account.state
    account.apply_fill(
        result.fill,
        lot_id=EntityId.deterministic("position_lot", str(result.fill.fill_id)),
        account_id=account_id,
    )
    duplicate_count = 0 if account.state == before_duplicate and len(account.state.lots) == 1 else 1

    policies = tuple(
        StopPolicy(
            EntityId.deterministic("stop_policy", f"v5-011:{lot.lot_id}"),
            lot.lot_id,
            Decimal("95"),
            Decimal("5"),
            created_at=now,
            source_ref="source:v5-011:stability-probe",
        )
        for lot in account.state.lots
    )
    unprotected = sum(
        ProtectionTriggerEvaluator.is_unprotected_open(lot, policy)
        for lot, policy in zip(account.state.lots, policies, strict=True)
    )

    with tempfile.TemporaryDirectory(prefix="fao-v5-011-") as temporary:
        path = Path(temporary) / "audit.json"
        audit = DurableAuditLog(path)
        audit.append("FILL", account_id, result.fill, now, source_ref="source:v5-011:stability-probe")
        reloaded = DurableAuditLog(path)
        audit_breaks = 0 if reloaded.verify() else 1
        replayed = SimulationAccount(Decimal("1000000"), account_id=account_id)
        reloaded.replay(replayed, account_id=account_id)
        reconciliation = reloaded.reconcile(account, account_id=account_id)
    ledger_difference = Decimal("0") if replayed.state == account.state and reconciliation.balanced else Decimal("1")
    healthy = duplicate_count == unprotected == audit_breaks == 0 and ledger_difference == 0
    return StabilityProbeResult(healthy, 1, duplicate_count, unprotected, audit_breaks, ledger_difference)


def evaluate_stability_run(
    plan: StabilityRunPlan, heartbeats: tuple[StabilityHeartbeat, ...], *, now: RecordedAt
) -> StabilityEvaluation:
    if not isinstance(plan, StabilityRunPlan) or not isinstance(now, RecordedAt):
        raise TypeError("stability evaluation requires typed plan and time")
    if not isinstance(heartbeats, tuple) or any(not isinstance(item, StabilityHeartbeat) for item in heartbeats):
        raise TypeError("stability evaluation requires immutable heartbeats")
    reasons: list[str] = []
    previous_digest = _GENESIS
    previous_at = plan.started_at
    previous_bucket = -1
    total_gap = Decimal(0)
    incidents = 0
    for expected_sequence, heartbeat in enumerate(heartbeats, start=1):
        if (
            heartbeat.sequence != expected_sequence
            or heartbeat.run_id != plan.run_id
            or heartbeat.code_commit != plan.code_commit
            or heartbeat.previous_digest != previous_digest
            or heartbeat.bucket <= previous_bucket
            or heartbeat.recorded_at.value < previous_at.value
            or heartbeat.bucket
            != int(
                (heartbeat.recorded_at.value - plan.started_at.value).total_seconds() // plan.heartbeat_interval_seconds
            )
        ):
            reasons.append("INVALID_HEARTBEAT_CHAIN")
            break
        gap = Decimal(str((heartbeat.recorded_at.value - previous_at.value).total_seconds()))
        excess = max(Decimal(0), gap - Decimal(plan.heartbeat_interval_seconds))
        if gap > Decimal(plan.heartbeat_interval_seconds * 2):
            total_gap += excess
            matching = tuple(
                incident
                for incident in heartbeat.incidents
                if incident.category == "HEARTBEAT_GAP"
                and incident.detected_at == previous_at
                and incident.recovered_at == heartbeat.recorded_at
                and incident.downtime_seconds == excess
            )
            if not matching:
                reasons.append("UNREPORTED_HEARTBEAT_GAP")
            if gap > Decimal(plan.maximum_single_gap_seconds):
                reasons.append("SINGLE_GAP_BUDGET_EXCEEDED")
        incidents += len(heartbeat.incidents)
        if not heartbeat.health_ok:
            reasons.append("HEALTH_CHECK_FAILED")
        if heartbeat.simulated_trade_count < 1:
            reasons.append("NO_SIMULATED_TRADE")
        if heartbeat.duplicate_trade_count:
            reasons.append("DUPLICATE_TRADE")
        if heartbeat.unprotected_position_count:
            reasons.append("UNPROTECTED_POSITION")
        if heartbeat.audit_chain_break_count:
            reasons.append("AUDIT_CHAIN_BREAK")
        if heartbeat.ledger_difference:
            reasons.append("LEDGER_DIFFERENCE")
        previous_digest = heartbeat.digest
        previous_at = heartbeat.recorded_at
        previous_bucket = heartbeat.bucket
    if not heartbeats:
        reasons.append("NO_HEARTBEATS")
        elapsed = Decimal(0)
    else:
        elapsed = Decimal(str((heartbeats[-1].recorded_at.value - plan.started_at.value).total_seconds()))
        if heartbeats[-1].recorded_at.value < plan.minimum_end_at.value or now.value < plan.minimum_end_at.value:
            reasons.append("MINIMUM_30_DAYS_NOT_ELAPSED")
    if total_gap > Decimal(plan.maximum_total_gap_seconds):
        reasons.append("TOTAL_GAP_BUDGET_EXCEEDED")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return StabilityEvaluation(
        not unique_reasons,
        unique_reasons,
        len(heartbeats),
        elapsed,
        total_gap,
        incidents,
        heartbeats[-1].digest if heartbeats else None,
    )


class StabilityJournal:
    """File-backed append-only heartbeat chain with process locking and fsync."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.plan_path = self.directory / "plan.json"
        self.heartbeat_path = self.directory / "heartbeats.jsonl"
        self.lock_path = self.directory / ".lock"

    def start(self, plan: StabilityRunPlan) -> None:
        if not isinstance(plan, StabilityRunPlan):
            raise TypeError("stability journal requires StabilityRunPlan")
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if self.plan_path.exists() or self.heartbeat_path.exists():
                raise ValueError("stability run already exists")
            payload = {"schema": "v5-011.stability-plan.v1", "plan": plan.to_payload(), "digest": plan.digest}
            self._atomic_write(self.plan_path, canonical_json_text(cast(Any, payload)) + "\n")
            self._atomic_write(self.heartbeat_path, "")

    def load_plan(self) -> StabilityRunPlan:
        try:
            payload = json.loads(self.plan_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"schema", "plan", "digest"}:
                raise ValueError
            plan = StabilityRunPlan.from_payload(payload["plan"])
            if payload["schema"] != "v5-011.stability-plan.v1" or payload["digest"] != plan.digest:
                raise ValueError
            return plan
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("cannot load stability plan") from error

    def load_heartbeats(self) -> tuple[StabilityHeartbeat, ...]:
        try:
            lines = self.heartbeat_path.read_text(encoding="utf-8").splitlines()
            heartbeats = tuple(StabilityHeartbeat.from_payload(json.loads(line)) for line in lines)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("cannot load stability heartbeat chain") from error
        plan = self.load_plan()
        evaluation = evaluate_stability_run(plan, heartbeats, now=plan.started_at)
        if "INVALID_HEARTBEAT_CHAIN" in evaluation.reason_codes:
            raise ValueError("stability heartbeat chain is invalid")
        return heartbeats

    def append(
        self,
        *,
        now: RecordedAt,
        code_commit: str,
        health_ok: bool,
        simulated_trade_count: int,
        duplicate_trade_count: int,
        unprotected_position_count: int,
        audit_chain_break_count: int,
        ledger_difference: Decimal,
    ) -> StabilityHeartbeat:
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            plan = self.load_plan()
            heartbeats = self.load_heartbeats()
            if code_commit != plan.code_commit:
                raise ValueError("stability heartbeat code commit drifted from frozen plan")
            seconds = (now.value - plan.started_at.value).total_seconds()
            if seconds < 0:
                raise ValueError("stability heartbeat precedes run start")
            bucket = int(seconds // plan.heartbeat_interval_seconds)
            if heartbeats and heartbeats[-1].bucket == bucket:
                return heartbeats[-1]
            previous = heartbeats[-1] if heartbeats else None
            incidents: tuple[StabilityIncident, ...] = ()
            previous_at = previous.recorded_at if previous else plan.started_at
            gap_seconds = Decimal(str((now.value - previous_at.value).total_seconds()))
            if gap_seconds > Decimal(plan.heartbeat_interval_seconds * 2):
                downtime = gap_seconds - Decimal(plan.heartbeat_interval_seconds)
                incident = StabilityIncident(
                    f"incident:{plan.run_id}:heartbeat-gap:{len(heartbeats) + 1}",
                    "HEARTBEAT_GAP",
                    previous_at,
                    now,
                    f"journal://{plan.run_id}/heartbeats#incident-{len(heartbeats) + 1}",
                    downtime,
                )
                incidents = (incident,)
            heartbeat = StabilityHeartbeat.issue(
                run_id=plan.run_id,
                sequence=len(heartbeats) + 1,
                bucket=bucket,
                recorded_at=now,
                code_commit=code_commit,
                health_ok=health_ok,
                simulated_trade_count=simulated_trade_count,
                duplicate_trade_count=duplicate_trade_count,
                unprotected_position_count=unprotected_position_count,
                audit_chain_break_count=audit_chain_break_count,
                ledger_difference=ledger_difference,
                incidents=incidents,
                previous_digest=previous.digest if previous else _GENESIS,
            )
            with self.heartbeat_path.open("a", encoding="utf-8") as stream:
                stream.write(canonical_json_text(cast(Any, heartbeat.to_payload())) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return heartbeat

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


__all__ = [
    "StabilityEvaluation",
    "StabilityHeartbeat",
    "StabilityIncident",
    "StabilityJournal",
    "StabilityProbeResult",
    "StabilityRunPlan",
    "evaluate_stability_run",
    "run_simulation_stability_probe",
]
