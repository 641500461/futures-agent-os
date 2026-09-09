"""V4-002 auditable L0/L1/L2 batch validation funnel.

The scheduler is deliberately an in-process contract boundary. Durable,
large-scale queueing belongs to V4-005. Connector output is evidence input,
never a promotion decision: only locally bound ``LevelEvidence`` can advance
a candidate to the next level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol, cast

from futures_agent_os.agent_orchestration.strategy_agent import StrategyAgentResult, StrategyDecision
from futures_agent_os.shared_kernel import EntityId, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .v4_001 import ArtifactManifest, ExperimentPlan, PinnedRef


class ValidationLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class GateDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    PASSED = "PASSED"
    FAILED = "FAILED"


_LEVEL_ORDER = (ValidationLevel.L0, ValidationLevel.L1, ValidationLevel.L2)


@dataclass(frozen=True, slots=True)
class LevelContract:
    """Frozen meaning and local promotion requirements for one level."""

    level: ValidationLevel
    input_semantics: str
    purpose: str
    limitations: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    required_checks: tuple[str, ...]
    promotion_gate_ref: PinnedRef

    def __post_init__(self) -> None:
        if type(self.level) is not ValidationLevel:
            raise TypeError("level contract requires a typed validation level")
        texts = (self.input_semantics, self.purpose, *self.limitations, *self.required_artifacts, *self.required_checks)
        if any(type(value) is not str or not value.strip() for value in texts):
            raise ValueError("level contract fields must be explicit")
        if not self.limitations or not self.required_artifacts or not self.required_checks:
            raise ValueError("level contract requires limitations, artifacts and checks")
        if len(set(self.required_artifacts)) != len(self.required_artifacts) or len(set(self.required_checks)) != len(
            self.required_checks
        ):
            raise ValueError("level contract requirements must be unique")
        if type(self.promotion_gate_ref) is not PinnedRef:
            raise TypeError("level contract requires a pinned promotion gate")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "level": self.level.value,
            "input_semantics": self.input_semantics,
            "purpose": self.purpose,
            "limitations": self.limitations,
            "required_artifacts": self.required_artifacts,
            "required_checks": self.required_checks,
            "promotion_gate_ref": self.promotion_gate_ref.to_dict(),
        }


def _make_contract(
    level: ValidationLevel,
    inputs: str,
    purpose: str,
    limitations: tuple[str, ...],
    artifacts: tuple[str, ...],
    checks: tuple[str, ...],
) -> LevelContract:
    gate = PinnedRef(
        f"validation-gate-{level.value.lower()}",
        "v4-002.1",
        canonical_sha256({"level": level.value, "artifacts": artifacts, "checks": checks}),
    )
    return LevelContract(level, inputs, purpose, limitations, artifacts, checks, gate)


def standard_level_contracts() -> tuple[LevelContract, ...]:
    """Return the frozen V4-002 meanings of the already shipped levels."""

    definitions = (
        (
            ValidationLevel.L0,
            "PIT signal observations aligned only with forward labels",
            "direction and label sanity checking",
            ("does not claim tradable returns", "does not model fills, margin or portfolio effects"),
            ("l0_metrics", "lineage"),
            ("pit_only", "label_alignment", "direction_only"),
        ),
        (
            ValidationLevel.L1,
            "frozen bar series, rule, costs and chronological split",
            "fast bar-level strategy screening",
            ("fill semantics are approximate", "portfolio margin and event ordering are not authoritative"),
            ("l1_metrics", "cost_breakdown", "lineage"),
            ("pit_only", "chronological_split", "costs_applied", "no_fill_claim"),
        ),
        (
            ValidationLevel.L2,
            "frozen event stream executed through the deterministic simulation and accounting owners",
            "event-driven multi-instrument, margin, portfolio and ledger validation",
            ("not tick/queue fidelity", "not paper or forward validation"),
            ("execution_facts", "accounting_replay", "lineage"),
            ("pit_only", "event_driven", "margin_accounting", "ledger_reconciled"),
        ),
    )
    return tuple(_make_contract(*item) for item in definitions)


def installed_v1_v2_connectors() -> tuple[ConnectorRef, ...]:
    """Pin the shipped V1 L0/L1 suite and V2 event/account replay bridge."""

    research_root = Path(__file__).parent
    package_root = research_root.parent
    v1_sources = {
        name: sha256((research_root / name).read_bytes()).hexdigest()
        for name in ("validation_tools.py", "walk_forward.py", "v4_001.py")
    }
    l2_path = package_root / "execution_simulation" / "strategy_replay.py"
    v1_levels = (ValidationLevel.L0, ValidationLevel.L1)
    l2_levels = (ValidationLevel.L2,)
    return (
        ConnectorRef(
            "v1-deterministic-research-suite",
            "1.5",
            canonical_sha256(v1_sources),
            canonical_sha256({"contract": "V4ExperimentPlan", "levels": ("L0", "L1")}),
            canonical_sha256({"contract": "BacktestRun", "levels": ("L0", "L1")}),
            v1_levels,
        ),
        ConnectorRef(
            "v2-event-account-replay",
            "2.9",
            sha256(l2_path.read_bytes()).hexdigest(),
            canonical_sha256({"contract": "ReplayEpisodeCandidate", "level": "L2"}),
            canonical_sha256({"contract": "L2ReplayMatrix", "level": "L2"}),
            l2_levels,
        ),
    )


@dataclass(frozen=True, slots=True)
class ConnectorRef:
    """A versioned connector and its exact local I/O contracts."""

    connector_id: str
    version: str
    implementation_sha256: str
    input_schema_sha256: str
    output_schema_sha256: str
    levels: tuple[ValidationLevel, ...]
    external: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not str or not value.strip() for value in (self.connector_id, self.version)):
            raise ValueError("connector identity and version are required")
        for value in (self.implementation_sha256, self.input_schema_sha256, self.output_schema_sha256):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("connector hashes require lowercase SHA-256")
        if not self.levels or any(type(level) is not ValidationLevel for level in self.levels):
            raise ValueError("connector requires typed supported levels")
        if tuple(level for level in _LEVEL_ORDER if level in self.levels) != self.levels:
            raise ValueError("connector levels must be unique and ordered")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "connector_id": self.connector_id,
            "version": self.version,
            "implementation_sha256": self.implementation_sha256,
            "input_schema_sha256": self.input_schema_sha256,
            "output_schema_sha256": self.output_schema_sha256,
            "levels": tuple(level.value for level in self.levels),
            "external": self.external,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class FunnelCandidate:
    candidate_ref: PinnedRef
    experiment_plan: ExperimentPlan
    source_lineage: tuple[PinnedRef, ...]
    levels: tuple[ValidationLevel, ...] = _LEVEL_ORDER

    def __post_init__(self) -> None:
        if type(self.candidate_ref) is not PinnedRef or type(self.experiment_plan) is not ExperimentPlan:
            raise TypeError("funnel candidate requires pinned candidate and V4 experiment plan")
        if not self.source_lineage or any(type(item) is not PinnedRef for item in self.source_lineage):
            raise ValueError("funnel candidate requires immutable source lineage")
        if self.levels not in (_LEVEL_ORDER[:1], _LEVEL_ORDER[:2], _LEVEL_ORDER):
            raise ValueError("validation levels must be a contiguous L0-first prefix")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "candidate_ref": self.candidate_ref.to_dict(),
                "experiment_plan_sha256": self.experiment_plan.content_sha256,
                "source_lineage": tuple(item.to_dict() for item in self.source_lineage),
                "levels": tuple(level.value for level in self.levels),
            }
        )

    @classmethod
    def from_v3(cls, result: StrategyAgentResult, plan: ExperimentPlan) -> FunnelCandidate:
        """Preserve one V3 candidate/draft and its exact PIT evidence as one batch item."""

        if type(result) is not StrategyAgentResult or type(plan) is not ExperimentPlan:
            raise TypeError("V3 compatibility adapter requires exact StrategyAgentResult and ExperimentPlan")
        if result.candidate is not None and result.candidate.decision is not StrategyDecision.TRADE:
            raise ValueError("NO_TRADE or DEFER proposals cannot enter the validation funnel")
        digest = result.content_sha256()
        lineage = tuple(
            PinnedRef(str(item.artifact_id), str(item.schema_version), item.content_hash.removeprefix("sha256:"))
            for item in result.source_refs
        )
        return cls(PinnedRef("v3-strategy-result", "3", digest), plan, lineage)


@dataclass(frozen=True, slots=True)
class BatchResearchPlan:
    batch_id: EntityId
    schema_version: SchemaVersion
    candidates: tuple[FunnelCandidate, ...]
    level_contracts: tuple[LevelContract, ...] = field(default_factory=standard_level_contracts)

    def __post_init__(self) -> None:
        if self.batch_id.namespace != "research_batch" or type(self.schema_version) is not SchemaVersion:
            raise ValueError("batch plan requires research_batch identity and schema version")
        if not self.candidates or any(type(item) is not FunnelCandidate for item in self.candidates):
            raise ValueError("batch plan requires typed candidates")
        hashes = tuple(item.content_sha256 for item in self.candidates)
        if len(set(hashes)) != len(hashes):
            raise ValueError("batch candidates must be unique")
        if self.level_contracts != standard_level_contracts():
            raise ValueError("batch plan must use the standard V4-002 level contracts")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "batch_id": str(self.batch_id),
                "schema_version": str(self.schema_version),
                "candidates": tuple(item.content_sha256 for item in self.candidates),
                "level_contracts": tuple(item.to_dict() for item in self.level_contracts),
            }
        )


@dataclass(frozen=True, slots=True)
class ValidationTask:
    task_id: EntityId
    batch_sha256: str
    candidate_sha256: str
    plan_sha256: str
    level: ValidationLevel
    level_contract_sha256: str
    connector: ConnectorRef
    predecessor_evidence_sha256: str | None = None

    @property
    def input_sha256(self) -> str:
        return canonical_sha256(
            {
                "batch": self.batch_sha256,
                "candidate": self.candidate_sha256,
                "plan": self.plan_sha256,
                "level": self.level.value,
                "contract": self.level_contract_sha256,
                "connector": self.connector.content_sha256,
                "predecessor": self.predecessor_evidence_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class ConnectorOutput:
    task_input_sha256: str
    connector_sha256: str
    output_schema_sha256: str
    artifact_manifest: ArtifactManifest
    metrics: Mapping[str, JsonValue]
    warnings: tuple[str, ...] = ()
    external_summary: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.artifact_manifest) is not ArtifactManifest:
            raise TypeError("connector output requires an artifact manifest")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "external_summary", MappingProxyType(dict(self.external_summary)))
        if any(type(item) is not str or not item.strip() for item in self.warnings):
            raise ValueError("connector warnings must be non-empty strings")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "task_input_sha256": self.task_input_sha256,
                "connector_sha256": self.connector_sha256,
                "output_schema_sha256": self.output_schema_sha256,
                "artifact_manifest_sha256": self.artifact_manifest.content_sha256,
                "metrics": cast(JsonValue, self.metrics),
                "warnings": self.warnings,
                "external_summary": cast(JsonValue, self.external_summary),
            }
        )


@dataclass(frozen=True, slots=True)
class LevelEvidence:
    task_input_sha256: str
    connector_output_sha256: str
    verifier_ref: PinnedRef
    verified_artifact_sha256s: tuple[str, ...]
    checks: Mapping[str, bool]
    decision: GateDecision
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.verifier_ref) is not PinnedRef or type(self.decision) is not GateDecision:
            raise TypeError("level evidence requires typed verifier and gate decision")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "task_input_sha256": self.task_input_sha256,
                "connector_output_sha256": self.connector_output_sha256,
                "verifier_ref": self.verifier_ref.to_dict(),
                "verified_artifact_sha256s": self.verified_artifact_sha256s,
                "checks": cast(JsonValue, self.checks),
                "decision": self.decision.value,
                "limitations": self.limitations,
            }
        )


class LocalLevelVerifier(Protocol):
    """Trusted local inspection boundary for connector artifacts and metrics."""

    @property
    def verifier_ref(self) -> PinnedRef: ...

    def verify(self, task: ValidationTask, output: ConnectorOutput, contract: LevelContract) -> LevelEvidence: ...


@dataclass(frozen=True, slots=True)
class DeterministicContractVerifier:
    """Reference verifier used by local adapters and connector integration tests."""

    verifier_ref: PinnedRef

    def verify(self, task: ValidationTask, output: ConnectorOutput, contract: LevelContract) -> LevelEvidence:
        if output.task_input_sha256 != task.input_sha256:
            raise ValueError("connector output does not bind the scheduled input")
        if output.connector_sha256 != task.connector.content_sha256:
            raise ValueError("connector output does not bind the registered connector")
        if output.output_schema_sha256 != task.connector.output_schema_sha256:
            raise ValueError("connector output schema does not match connector registration")
        names = {item.name for item in output.artifact_manifest.entries}
        missing_artifacts = tuple(name for name in contract.required_artifacts if name not in names)
        checks = {name: output.metrics.get(f"contract_check:{name}") is True for name in contract.required_checks}
        decision = GateDecision.PASS if not missing_artifacts and all(checks.values()) else GateDecision.FAIL
        limitations = contract.limitations + tuple(output.warnings)
        if missing_artifacts:
            limitations += tuple(f"missing required artifact: {name}" for name in missing_artifacts)
        return LevelEvidence(
            task.input_sha256,
            output.content_sha256,
            self.verifier_ref,
            tuple(item.content_sha256 for item in output.artifact_manifest.entries),
            checks,
            decision,
            limitations,
        )


class BatchResearchScheduler:
    """Deterministically fan out candidates while keeping each funnel sequential."""

    def __init__(
        self,
        plan: BatchResearchPlan,
        connectors: tuple[ConnectorRef, ...],
        verifier: LocalLevelVerifier,
    ) -> None:
        if type(plan) is not BatchResearchPlan or not connectors:
            raise ValueError("scheduler requires a batch plan and connectors")
        if len({item.connector_id for item in connectors}) != len(connectors):
            raise ValueError("connector identities must be unique")
        self.plan = plan
        self._connectors = connectors
        self._verifier = verifier
        self._tasks: dict[str, ValidationTask] = {}
        self._status: dict[str, TaskStatus] = {}
        self._evidence: dict[str, LevelEvidence] = {}
        for candidate in plan.candidates:
            self._queue(candidate, candidate.levels[0], None)

    def _contract(self, level: ValidationLevel) -> LevelContract:
        return next(item for item in self.plan.level_contracts if item.level is level)

    def _connector(self, level: ValidationLevel) -> ConnectorRef:
        matches = tuple(item for item in self._connectors if level in item.levels)
        if len(matches) != 1:
            raise ValueError(f"level {level.value} requires exactly one registered connector")
        return matches[0]

    def _queue(
        self, candidate: FunnelCandidate, level: ValidationLevel, predecessor: LevelEvidence | None
    ) -> ValidationTask:
        contract = self._contract(level)
        connector = self._connector(level)
        seed = {
            "batch": self.plan.content_sha256,
            "candidate": candidate.content_sha256,
            "level": level.value,
            "predecessor": predecessor.content_sha256 if predecessor else None,
        }
        task = ValidationTask(
            EntityId.deterministic("research_validation_task", canonical_sha256(seed)),
            self.plan.content_sha256,
            candidate.content_sha256,
            candidate.experiment_plan.content_sha256,
            level,
            canonical_sha256(contract.to_dict()),
            connector,
            predecessor.content_sha256 if predecessor else None,
        )
        self._tasks[task.input_sha256] = task
        self._status[task.input_sha256] = TaskStatus.QUEUED
        return task

    def queued(self) -> tuple[ValidationTask, ...]:
        return tuple(task for key, task in self._tasks.items() if self._status[key] is TaskStatus.QUEUED)

    def accept(self, task: ValidationTask, output: ConnectorOutput) -> LevelEvidence:
        registered = self._tasks.get(task.input_sha256)
        if registered != task or self._status.get(task.input_sha256) is not TaskStatus.QUEUED:
            raise ValueError("only an exact queued task can accept connector output")
        contract = self._contract(task.level)
        evidence = self._verifier.verify(task, output, contract)
        if (
            type(evidence) is not LevelEvidence
            or evidence.task_input_sha256 != task.input_sha256
            or evidence.connector_output_sha256 != output.content_sha256
            or evidence.verifier_ref != self._verifier.verifier_ref
            or tuple(evidence.checks) != contract.required_checks
            or evidence.limitations[: len(contract.limitations)] != contract.limitations
        ):
            raise ValueError("local evidence does not satisfy the registered level contract")
        artifact_names = {item.name for item in output.artifact_manifest.entries}
        artifacts_complete = all(name in artifact_names for name in contract.required_artifacts)
        expected = GateDecision.PASS if artifacts_complete and all(evidence.checks.values()) else GateDecision.FAIL
        if evidence.decision is not expected:
            raise ValueError("gate decision does not match local contract checks")
        self._evidence[task.input_sha256] = evidence
        self._status[task.input_sha256] = (
            TaskStatus.PASSED if evidence.decision is GateDecision.PASS else TaskStatus.FAILED
        )
        if evidence.decision is GateDecision.PASS:
            candidate = next(item for item in self.plan.candidates if item.content_sha256 == task.candidate_sha256)
            index = candidate.levels.index(task.level)
            if index + 1 < len(candidate.levels):
                self._queue(candidate, candidate.levels[index + 1], evidence)
        return evidence

    def status(self, task: ValidationTask) -> TaskStatus:
        return self._status[task.input_sha256]

    def evidence(self) -> tuple[LevelEvidence, ...]:
        return tuple(self._evidence[key] for key in self._tasks if key in self._evidence)


__all__ = [
    "BatchResearchPlan",
    "BatchResearchScheduler",
    "ConnectorOutput",
    "ConnectorRef",
    "DeterministicContractVerifier",
    "FunnelCandidate",
    "GateDecision",
    "LevelContract",
    "LevelEvidence",
    "LocalLevelVerifier",
    "TaskStatus",
    "ValidationLevel",
    "ValidationTask",
    "installed_v1_v2_connectors",
    "standard_level_contracts",
]
