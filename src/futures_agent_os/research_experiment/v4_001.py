"""V4-001 frozen experiment and deterministic backtest contracts.

The V1 ``ExperimentPlan`` remains available from :mod:`experiment_manager`.
This module owns the richer V4 plan used to pin every input that can affect a
backtest and to derive a reproducible run identity from those inputs.
"""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Mapping, cast

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: str, field: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} requires a lowercase SHA-256 digest")


def _freeze(value: object) -> JsonValue:
    """Detach caller-owned JSON values and reject mutable/non-JSON inputs."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("mapping keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    raise ValueError("value must be finite JSON-compatible data")


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError("serialized value requires a JSON object")
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("serialized value requires text")
    return value


def _items(value: object) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("serialized value requires an array")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class PinnedRef:
    """A versioned, content-addressed input reference."""

    identity: str
    revision: str
    content_sha256: str
    kind: ClassVar[str] = "artifact"

    def __post_init__(self) -> None:
        if not isinstance(self.identity, str) or not self.identity.strip():
            raise ValueError(f"{self.kind} reference requires an identity")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError(f"{self.kind} reference requires a revision")
        _digest(self.content_sha256, f"{self.kind} reference")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "revision": self.revision,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class DatasetRef(PinnedRef):
    kind: ClassVar[str] = "dataset"


@dataclass(frozen=True, slots=True)
class RuleRef(PinnedRef):
    kind: ClassVar[str] = "rule"


@dataclass(frozen=True, slots=True)
class CostRef(PinnedRef):
    kind: ClassVar[str] = "cost"


@dataclass(frozen=True, slots=True)
class EngineRef(PinnedRef):
    kind: ClassVar[str] = "engine"


def current_engine_ref() -> EngineRef:
    """Pin the shipped deterministic algorithms, including fold planning.

    This is a reproducibility fingerprint, not an integrity/security boundary.
    The V1 suite does not use a PRNG; seeds remain frozen experiment provenance.
    """
    root = Path(__file__).parent
    sources = {
        name: sha256((root / name).read_bytes()).hexdigest()
        for name in ("validation_tools.py", "walk_forward.py", "v4_001.py")
    }
    return EngineRef("v1-deterministic-research-suite", "1.5", canonical_sha256(sources))


@dataclass(frozen=True, slots=True)
class ModelRef(PinnedRef):
    kind: ClassVar[str] = "model"


@dataclass(frozen=True, slots=True)
class PromptRef(PinnedRef):
    kind: ClassVar[str] = "prompt"


@dataclass(frozen=True, slots=True)
class StrategyRef(PinnedRef):
    kind: ClassVar[str] = "strategy"


@dataclass(frozen=True, slots=True)
class SeedBundle:
    """Named deterministic seeds.  Names and values are part of plan identity."""

    values: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("at least one deterministic seed is required")
        if any(not isinstance(key, str) or not key.strip() for key in self.values):
            raise ValueError("seed names must be non-empty strings")
        if any(type(value) is not int or value < 0 for value in self.values.values()):
            raise ValueError("seed values must be non-negative integers")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def to_dict(self) -> dict[str, int]:
        return dict(sorted(self.values.items()))


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    name: str
    content_sha256: str
    uri: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.uri.strip():
            raise ValueError("artifact entry requires name and uri")
        _digest(self.content_sha256, "artifact entry")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "content_sha256": self.content_sha256, "uri": self.uri}


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable inventory of concrete outputs produced by a run."""

    entries: tuple[ArtifactEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries or any(type(item) is not ArtifactEntry for item in self.entries):
            raise ValueError("artifact manifest requires typed entries")
        object.__setattr__(self, "entries", tuple(self.entries))
        names = tuple(item.name for item in self.entries)
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ValueError("artifact entries must be unique and canonically ordered")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"entries": tuple(item.to_dict() for item in self.entries)}

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ArtifactManifest:
        entries = tuple(_object(item) for item in _items(value["entries"]))
        return cls(
            tuple(
                ArtifactEntry(_text(item["name"]), _text(item["content_sha256"]), _text(item["uri"]))
                for item in entries
            )
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """A frozen V4 experiment definition with all replay-relevant inputs."""

    experiment_id: EntityId
    schema_version: SchemaVersion
    dataset_ref: DatasetRef
    rule_ref: RuleRef
    cost_ref: CostRef
    engine_ref: EngineRef
    model_ref: ModelRef
    prompt_ref: PromptRef
    seeds: SeedBundle
    config: Mapping[str, JsonValue]
    strategy_ref: StrategyRef | None = None
    hypothesis_ref: PinnedRef | None = None
    universe_ref: PinnedRef | None = None
    feature_graph_ref: PinnedRef | None = None
    split_ref: PinnedRef | None = None
    created_at: RecordedAt | None = None
    environment: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.experiment_id.namespace != "experiment":
            raise ValueError("V4 experiment requires an experiment id")
        expected_refs = (
            (self.dataset_ref, DatasetRef),
            (self.rule_ref, RuleRef),
            (self.cost_ref, CostRef),
            (self.engine_ref, EngineRef),
            (self.model_ref, ModelRef),
            (self.prompt_ref, PromptRef),
        )
        if any(type(ref) is not expected for ref, expected in expected_refs):
            raise TypeError("experiment inputs require their exact typed reference")
        if self.strategy_ref is not None and type(self.strategy_ref) is not StrategyRef:
            raise TypeError("strategy_ref requires a StrategyRef")
        for name in ("hypothesis_ref", "universe_ref", "feature_graph_ref", "split_ref"):
            value = getattr(self, name)
            if value is not None and type(value) is not PinnedRef:
                raise TypeError(f"{name} requires a PinnedRef")
        frozen = _freeze(self.config)
        if not isinstance(frozen, Mapping):
            raise ValueError("experiment config must be a JSON object")
        object.__setattr__(self, "config", frozen)
        environment = _freeze(self.environment)
        if not isinstance(environment, Mapping):
            raise ValueError("environment must be an object")
        object.__setattr__(self, "environment", environment)
        if type(self.seeds) is not SeedBundle:
            raise TypeError("plan requires a SeedBundle")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "experiment_id": str(self.experiment_id),
            "schema_version": str(self.schema_version),
            "dataset_ref": self.dataset_ref.to_dict(),
            "rule_ref": self.rule_ref.to_dict(),
            "cost_ref": self.cost_ref.to_dict(),
            "engine_ref": self.engine_ref.to_dict(),
            "model_ref": self.model_ref.to_dict(),
            "prompt_ref": self.prompt_ref.to_dict(),
            "strategy_ref": self.strategy_ref.to_dict() if self.strategy_ref else None,
            "hypothesis_ref": self.hypothesis_ref.to_dict() if self.hypothesis_ref else None,
            "universe_ref": self.universe_ref.to_dict() if self.universe_ref else None,
            "feature_graph_ref": self.feature_graph_ref.to_dict() if self.feature_graph_ref else None,
            "split_ref": self.split_ref.to_dict() if self.split_ref else None,
            "seeds": self.seeds.to_dict(),
            "config": cast(JsonValue, self.config),
            "environment": cast(JsonValue, self.environment),
            "created_at": self.created_at.to_dict()["recorded_at"] if self.created_at else None,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExperimentPlan:
        def ref(key: str, ref_type: type[PinnedRef]) -> PinnedRef:
            item = _object(value[key])
            if item.get("kind") != ref_type.kind:
                raise ValueError("serialized reference kind mismatch")
            return ref_type(_text(item["identity"]), _text(item["revision"]), _text(item["content_sha256"]))

        seeds = _object(value["seeds"])
        if any(type(item) is not int for item in seeds.values()):
            raise ValueError("serialized seeds require integers")
        return cls(
            experiment_id=EntityId.parse(_text(value["experiment_id"])),
            schema_version=SchemaVersion.parse(_text(value["schema_version"])),
            dataset_ref=cast(DatasetRef, ref("dataset_ref", DatasetRef)),
            rule_ref=cast(RuleRef, ref("rule_ref", RuleRef)),
            cost_ref=cast(CostRef, ref("cost_ref", CostRef)),
            engine_ref=cast(EngineRef, ref("engine_ref", EngineRef)),
            model_ref=cast(ModelRef, ref("model_ref", ModelRef)),
            prompt_ref=cast(PromptRef, ref("prompt_ref", PromptRef)),
            strategy_ref=cast(StrategyRef, ref("strategy_ref", StrategyRef))
            if value["strategy_ref"] is not None
            else None,
            seeds=SeedBundle(cast(Mapping[str, int], seeds)),
            config=cast(Mapping[str, JsonValue], _object(value["config"])),
            environment=cast(Mapping[str, JsonValue], _object(value["environment"])),
            created_at=RecordedAt.parse(_text(value["created_at"])) if value["created_at"] is not None else None,
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def reproducibility_envelope(self) -> dict[str, JsonValue]:
        return {"plan": self.to_dict(), "plan_sha256": self.content_sha256}


@dataclass(frozen=True, slots=True)
class BacktestRun:
    """A deterministic execution result and its output artifact inventory."""

    run_id: EntityId
    plan_sha256: str
    input_sha256: str
    result: Mapping[str, JsonValue]
    artifact_manifest: ArtifactManifest
    replay_count: int = 0

    def __post_init__(self) -> None:
        if self.run_id.namespace != "backtest_run":
            raise ValueError("backtest run requires a backtest_run id")
        _digest(self.plan_sha256, "plan")
        _digest(self.input_sha256, "input")
        if type(self.replay_count) is not int or self.replay_count < 0:
            raise ValueError("replay_count must be non-negative")
        if type(self.artifact_manifest) is not ArtifactManifest:
            raise TypeError("artifact_manifest requires ArtifactManifest")
        frozen = _freeze(self.result)
        if not isinstance(frozen, Mapping):
            raise ValueError("backtest result must be an object")
        object.__setattr__(self, "result", frozen)

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> BacktestRun:
        manifest = ArtifactManifest.hydrate(_object(value["artifact_manifest"]))
        if manifest.content_sha256 != value["artifact_manifest_sha256"]:
            raise ValueError("serialized manifest digest mismatch")
        return cls(
            EntityId.parse(_text(value["run_id"])),
            _text(value["plan_sha256"]),
            _text(value["input_sha256"]),
            cast(Mapping[str, JsonValue], _object(value["result"])),
            manifest,
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def reproducibility_envelope(self) -> dict[str, JsonValue]:
        return {"run": self.to_dict(), "run_sha256": self.content_sha256}

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "run_id": str(self.run_id),
            "plan_sha256": self.plan_sha256,
            "input_sha256": self.input_sha256,
            "result": cast(JsonValue, self.result),
            "artifact_manifest": self.artifact_manifest.to_dict(),
            "artifact_manifest_sha256": self.artifact_manifest.content_sha256,
        }


def execute_backtest(plan: ExperimentPlan, inputs: object) -> BacktestRun:
    """Run the pinned V1 deterministic research suite.

    Inputs must be the explicit ``(MarketSnapshot, ValidationRunRequest, DeterministicResearchTools)``
    adapter tuple; no dynamic callables or synthetic observations are accepted.
    """
    from futures_agent_os.reference_market_data import MarketSnapshot
    from .validation_tools import DeterministicResearchTools, ValidationRunRequest

    if type(inputs) is not tuple or len(inputs) != 3:
        raise TypeError("inputs require (MarketSnapshot, ValidationRunRequest, DeterministicResearchTools)")
    snapshot, request, tools = inputs
    if (
        type(snapshot) is not MarketSnapshot
        or type(request) is not ValidationRunRequest
        or type(tools) is not DeterministicResearchTools
    ):
        raise TypeError("inputs require exact V1 typed adapter")
    if type(plan) is not ExperimentPlan:
        raise TypeError("plan requires ExperimentPlan")
    for key in ("code_commit", "runtime_image"):
        value = plan.environment.get(key)
        if value is not None and (type(value) is not str or not value.strip()):
            raise ValueError("environment provenance requires non-empty string code_commit/runtime_image")
    if "resource_spec" in plan.environment and not isinstance(plan.environment.get("resource_spec"), Mapping):
        raise ValueError("environment provenance requires resource_spec object")
    if plan.engine_ref != current_engine_ref():
        raise ValueError("engine reference does not match installed implementation")
    if plan.config != request.config.payload():
        raise ValueError("plan config must bind exact validation parameters")
    if plan.dataset_ref.content_sha256 != snapshot.expected_content_sha256:
        raise ValueError("dataset reference must bind exact snapshot")
    if plan.rule_ref.content_sha256 != snapshot.rule_resolution.rule_content_sha256:
        raise ValueError("rule reference must bind resolved rule")
    costs = {
        key: request.config.payload()[key] for key in ("round_trip_cost_bps", "slippage_bps", "stress_multipliers")
    }
    if plan.cost_ref.content_sha256 != canonical_sha256(costs):
        raise ValueError("cost reference must bind exact cost assumptions")
    results = tools.run_snapshot_suite(snapshot, request)
    required_environment = ("code_commit", "runtime_image", "resource_spec")
    missing = tuple(key for key in required_environment if not plan.environment.get(key))
    if plan.strategy_ref is None:
        missing += ("strategy_ref",)
    payload: dict[str, JsonValue] = {
        "reproducibility": "NON_REPRODUCIBLE" if missing else "REPRODUCIBLE",
        "missing_references": missing,
        "seed_policy": "V1_NO_PRNG",
        "plan": plan.to_dict(),
        "results": tuple(result.to_dict() for result in results),
        "request_sha256": request.content_sha256,
        "toolset_version": "research-validation.v1",
        "authority_ids": (
            "market_intelligence.feature_observation_store.v1",
            "learning_review.validated_lesson_store.v1",
            "research_experiment.result_store.v1",
            "research_experiment.deterministic_tools.v1",
        ),
    }
    input_sha = canonical_sha256(
        {
            "snapshot": snapshot.expected_content_sha256,
            "request": request.content_sha256,
            "plan_config": cast(JsonValue, plan.config),
            "toolset_version": "research-validation.v1",
            "authority_ids": (
                "market_intelligence.feature_observation_store.v1",
                "learning_review.validated_lesson_store.v1",
                "research_experiment.result_store.v1",
                "research_experiment.deterministic_tools.v1",
            ),
        }
    )
    result_sha = canonical_sha256(payload)
    artifacts = ArtifactManifest((ArtifactEntry("results", result_sha, f"artifact://backtest/{result_sha}"),))
    run_id = EntityId.deterministic("backtest_run", f"{plan.content_sha256}:{input_sha}:{artifacts.content_sha256}")
    return BacktestRun(run_id, plan.content_sha256, input_sha, payload, artifacts)


def replay_backtest(plan: ExperimentPlan, run: BacktestRun, inputs: object) -> BacktestRun:
    """Re-execute a run and fail closed if any frozen input or output changed."""

    if type(run) is not BacktestRun:
        raise TypeError("run requires BacktestRun")
    if run.plan_sha256 != plan.content_sha256:
        raise ValueError("backtest plan does not match the recorded run")
    replayed = execute_backtest(plan, inputs)
    if (
        replayed.run_id != run.run_id
        or replayed.plan_sha256 != run.plan_sha256
        or replayed.input_sha256 != run.input_sha256
        or replayed.result != run.result
        or replayed.artifact_manifest != run.artifact_manifest
    ):
        raise ValueError("backtest replay diverged from the recorded run")
    return BacktestRun(
        replayed.run_id,
        replayed.plan_sha256,
        replayed.input_sha256,
        replayed.result,
        replayed.artifact_manifest,
        replay_count=run.replay_count + 1,
    )


UnifiedExperimentPlan = ExperimentPlan
V4ExperimentPlan = ExperimentPlan


__all__ = [
    "ArtifactEntry",
    "ArtifactManifest",
    "BacktestRun",
    "CostRef",
    "DatasetRef",
    "EngineRef",
    "ExperimentPlan",
    "ModelRef",
    "PinnedRef",
    "PromptRef",
    "RuleRef",
    "StrategyRef",
    "SeedBundle",
    "UnifiedExperimentPlan",
    "V4ExperimentPlan",
    "current_engine_ref",
    "execute_backtest",
    "replay_backtest",
]
