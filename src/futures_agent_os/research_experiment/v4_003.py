"""V4-003 deterministic validation suite and promotion-evidence gate."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, cast

from futures_agent_os.shared_kernel import EntityId, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .v4_001 import PinnedRef


class ValidationKind(StrEnum):
    WALK_FORWARD = "WALK_FORWARD"
    COST_SLIPPAGE_STRESS = "COST_SLIPPAGE_STRESS"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    MONTE_CARLO = "MONTE_CARLO"
    SCENARIO_REPLAY = "SCENARIO_REPLAY"
    PARAMETER_SWEEP = "PARAMETER_SWEEP"
    STRATEGY_COMPARE = "STRATEGY_COMPARE"


class ArtifactStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class StrategyDirection(StrEnum):
    FOLLOW = "FOLLOW"
    INVERT = "INVERT"


ALL_VALIDATIONS = tuple(ValidationKind)


def _check_decimal(value: Decimal, field: str, *, non_negative: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite() or (non_negative and value < 0):
        raise ValueError(f"{field} requires a finite Decimal")


def _text(value: Decimal) -> str:
    return format(value, "f")


def _freeze(value: object) -> JsonValue:
    if value is None or type(value) in (str, int, bool):
        return cast(JsonValue, value)
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("validation JSON keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    raise ValueError("validation data must be JSON-compatible")


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_ref: PinnedRef
    threshold: Decimal
    direction: StrategyDirection = StrategyDirection.FOLLOW

    def __post_init__(self) -> None:
        if type(self.strategy_ref) is not PinnedRef or type(self.direction) is not StrategyDirection:
            raise TypeError("strategy definition requires pinned identity and typed direction")
        _check_decimal(self.threshold, "strategy threshold", non_negative=True)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "strategy_ref": self.strategy_ref.to_dict(),
            "threshold": _text(self.threshold),
            "direction": self.direction.value,
        }


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    name: str
    start_index: int
    end_index: int
    return_multiplier: Decimal = Decimal("1")
    extra_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.name.strip() or type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("scenario requires identity and integer bounds")
        if self.start_index < 0 or self.end_index <= self.start_index:
            raise ValueError("scenario bounds must be a non-empty half-open range")
        _check_decimal(self.return_multiplier, "scenario return multiplier")
        _check_decimal(self.extra_cost, "scenario extra cost", non_negative=True)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "return_multiplier": _text(self.return_multiplier),
            "extra_cost": _text(self.extra_cost),
        }


@dataclass(frozen=True, slots=True)
class FrozenValidationDataset:
    dataset_ref: PinnedRef
    features: tuple[Decimal, ...]
    forward_returns: tuple[Decimal, ...]
    event_times: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.dataset_ref) is not PinnedRef:
            raise TypeError("validation dataset requires a pinned reference")
        if any(type(values) is not tuple for values in (self.features, self.forward_returns, self.event_times)):
            raise TypeError("validation observations must be immutable tuples")
        if not self.features or len(self.features) != len(self.forward_returns):
            raise ValueError("features and forward returns must be non-empty and aligned")
        if len(self.event_times) != len(self.features) or len(set(self.event_times)) != len(self.event_times):
            raise ValueError("validation event times must be unique and aligned")
        if tuple(sorted(self.event_times)) != self.event_times:
            raise ValueError("validation event times must be chronological")
        for value in (*self.features, *self.forward_returns):
            _check_decimal(value, "validation observation")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "dataset_ref": self.dataset_ref.to_dict(),
                "features": tuple(_text(value) for value in self.features),
                "forward_returns": tuple(_text(value) for value in self.forward_returns),
                "event_times": self.event_times,
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionEvidencePackage:
    package_id: EntityId
    dataset_sha256: str
    strategy_sha256: str
    artifacts: tuple[ValidationArtifact, ...]

    def __post_init__(self) -> None:
        if self.package_id.namespace != "promotion_evidence":
            raise ValueError("promotion evidence requires a promotion_evidence id")
        if tuple(item.kind for item in self.artifacts) != ALL_VALIDATIONS:
            raise ValueError("promotion evidence requires every validation exactly once in canonical order")
        if any(item.status is not ArtifactStatus.COMPLETE for item in self.artifacts):
            raise ValueError("incomplete validation cannot enter promotion evidence")
        if any(
            item.dataset_sha256 != self.dataset_sha256 or item.strategy_sha256 != self.strategy_sha256
            for item in self.artifacts
        ):
            raise ValueError("promotion evidence artifacts must bind one dataset and strategy")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "package_id": str(self.package_id),
                "dataset_sha256": self.dataset_sha256,
                "strategy_sha256": self.strategy_sha256,
                "artifacts": tuple(item.content_sha256 for item in self.artifacts),
            }
        )


@dataclass(frozen=True, slots=True)
class ScaleValidationConfig:
    train_size: int
    test_size: int
    step_size: int
    embargo_size: int
    base_cost: Decimal
    cost_multipliers: tuple[Decimal, ...]
    slippage_values: tuple[Decimal, ...]
    monte_carlo_iterations: int
    monte_carlo_seed: int
    parameter_grid: tuple[Decimal, ...]
    scenarios: tuple[ScenarioDefinition, ...]
    comparison_strategies: tuple[StrategyDefinition, ...]

    def __post_init__(self) -> None:
        grids = (
            self.cost_multipliers,
            self.slippage_values,
            self.parameter_grid,
            self.scenarios,
            self.comparison_strategies,
        )
        if any(type(value) is not tuple for value in grids):
            raise TypeError("validation grids must be immutable tuples")
        sizes = (self.train_size, self.test_size, self.step_size, self.monte_carlo_iterations)
        if any(type(value) is not int or value < 1 for value in sizes):
            raise ValueError("validation sizes and iterations must be positive integers")
        if type(self.embargo_size) is not int or self.embargo_size < 0 or self.step_size < self.test_size:
            raise ValueError("validation embargo/step bounds are invalid")
        if type(self.monte_carlo_seed) is not int or self.monte_carlo_seed < 0:
            raise ValueError("Monte Carlo seed must be a non-negative integer")
        _check_decimal(self.base_cost, "base cost", non_negative=True)
        for value in (*self.cost_multipliers, *self.slippage_values, *self.parameter_grid):
            _check_decimal(value, "validation grid value", non_negative=True)
        if not self.cost_multipliers or self.cost_multipliers[0] != Decimal("1"):
            raise ValueError("cost stress requires a baseline multiplier of one")
        if tuple(sorted(set(self.cost_multipliers))) != self.cost_multipliers:
            raise ValueError("cost multipliers must be unique and ordered")
        if tuple(sorted(set(self.slippage_values))) != self.slippage_values or not self.slippage_values:
            raise ValueError("slippage values must be unique and ordered")
        if tuple(sorted(set(self.parameter_grid))) != self.parameter_grid or not self.parameter_grid:
            raise ValueError("parameter grid must be unique and ordered")
        if not self.scenarios or any(type(item) is not ScenarioDefinition for item in self.scenarios):
            raise ValueError("scenario replay requires typed scenarios")
        if len({item.name for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario names must be unique")
        if len(self.comparison_strategies) < 2 or any(
            type(item) is not StrategyDefinition for item in self.comparison_strategies
        ):
            raise ValueError("strategy comparison requires at least two typed strategies")
        refs = tuple(item.strategy_ref.content_sha256 for item in self.comparison_strategies)
        if len(set(refs)) != len(refs):
            raise ValueError("comparison strategies must be unique")

    def for_kind(self, kind: ValidationKind) -> Mapping[str, JsonValue]:
        if type(kind) is not ValidationKind:
            raise TypeError("validation kind must be typed")
        payload: dict[str, JsonValue] = {
            "kind": kind.value,
            "base_cost": _text(self.base_cost),
            "algorithm_version": "scaled-validation.v1",
        }
        if kind is ValidationKind.WALK_FORWARD:
            payload.update(
                train_size=self.train_size,
                test_size=self.test_size,
                step_size=self.step_size,
                embargo_size=self.embargo_size,
            )
        elif kind is ValidationKind.COST_SLIPPAGE_STRESS:
            payload["cost_multipliers"] = tuple(_text(value) for value in self.cost_multipliers)
            payload["slippage_values"] = tuple(_text(value) for value in self.slippage_values)
        elif kind is ValidationKind.COUNTERFACTUAL:
            payload["variants"] = ("INVERT", "ZERO_SIGNAL")
        elif kind is ValidationKind.MONTE_CARLO:
            payload.update(
                iterations=self.monte_carlo_iterations,
                seed=self.monte_carlo_seed,
                sampling="IID_TRADE_RETURN_BOOTSTRAP",
            )
        elif kind is ValidationKind.SCENARIO_REPLAY:
            payload["scenarios"] = tuple(item.to_dict() for item in self.scenarios)
        elif kind is ValidationKind.PARAMETER_SWEEP:
            payload["parameter_grid"] = tuple(_text(value) for value in self.parameter_grid)
            payload["selection"] = "REPORT_ALL_NO_OPTIMIZATION"
        else:
            payload["strategies"] = tuple(item.to_dict() for item in self.comparison_strategies)
            payload["comparison"] = "SAME_DATA_COST_AND_LEVEL"
        return MappingProxyType(payload)


@dataclass(frozen=True, slots=True)
class ValidationArtifact:
    artifact_id: EntityId
    kind: ValidationKind
    status: ArtifactStatus
    dataset_sha256: str
    strategy_sha256: str
    config: Mapping[str, JsonValue]
    result: Mapping[str, JsonValue]
    warnings: tuple[str, ...]
    source_refs: tuple[PinnedRef, ...]

    def __post_init__(self) -> None:
        if self.artifact_id.namespace != "validation_artifact":
            raise ValueError("validation artifact requires a validation_artifact id")
        if type(self.kind) is not ValidationKind or type(self.status) is not ArtifactStatus:
            raise TypeError("validation artifact requires typed kind and status")
        for digest in (self.dataset_sha256, self.strategy_sha256):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("validation artifact input hashes must be SHA-256")
        frozen_config = _freeze(self.config)
        frozen_result = _freeze(self.result)
        if not isinstance(frozen_config, Mapping) or not isinstance(frozen_result, Mapping):
            raise ValueError("validation artifact config and result must be objects")
        object.__setattr__(self, "config", frozen_config)
        object.__setattr__(self, "result", frozen_result)
        if type(self.warnings) is not tuple or any(type(item) is not str or not item.strip() for item in self.warnings):
            raise ValueError("validation warnings must be non-empty strings")
        if (
            type(self.source_refs) is not tuple
            or not self.source_refs
            or any(type(item) is not PinnedRef for item in self.source_refs)
        ):
            raise ValueError("validation artifact requires pinned source refs")
        if self.status is ArtifactStatus.COMPLETE and not self.result:
            raise ValueError("complete validation artifact requires results")

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(cast(JsonValue, self.config))

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "artifact_id": str(self.artifact_id),
                "kind": self.kind.value,
                "status": self.status.value,
                "dataset_sha256": self.dataset_sha256,
                "strategy_sha256": self.strategy_sha256,
                "config": cast(JsonValue, self.config),
                "result": cast(JsonValue, self.result),
                "warnings": self.warnings,
                "source_refs": tuple(item.to_dict() for item in self.source_refs),
            }
        )


def _signals(dataset: FrozenValidationDataset, strategy: StrategyDefinition) -> tuple[int, ...]:
    direction = 1 if strategy.direction is StrategyDirection.FOLLOW else -1
    return tuple(
        direction * (1 if value > strategy.threshold else -1 if value < -strategy.threshold else 0)
        for value in dataset.features
    )


def _trade_returns(
    dataset: FrozenValidationDataset,
    strategy: StrategyDefinition,
    *,
    cost: Decimal,
    slippage: Decimal = Decimal("0"),
) -> tuple[Decimal, ...]:
    signals = _signals(dataset, strategy)
    return tuple(
        Decimal(signal) * outcome - (cost + slippage if signal else Decimal("0"))
        for signal, outcome in zip(signals, dataset.forward_returns, strict=True)
    )


def _summary(values: tuple[Decimal, ...]) -> dict[str, JsonValue]:
    if not values:
        return {"sample_count": 0, "net_return": "0", "positive_ratio": "0", "max_drawdown": "0"}
    total = sum(values, Decimal("0"))
    positive = Decimal(sum(value > 0 for value in values)) / Decimal(len(values))
    equity = Decimal("0")
    peak = Decimal("0")
    drawdown = Decimal("0")
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {
        "sample_count": len(values),
        "net_return": _text(total),
        "positive_ratio": _text(positive),
        "max_drawdown": _text(drawdown),
    }


class ScaleValidationRunner:
    """Run all seven validations with deterministic, frozen inputs."""

    def run(
        self,
        dataset: FrozenValidationDataset,
        strategy: StrategyDefinition,
        config: ScaleValidationConfig,
    ) -> tuple[ValidationArtifact, ...]:
        if type(dataset) is not FrozenValidationDataset or type(strategy) is not StrategyDefinition:
            raise TypeError("scaled validation requires exact dataset and strategy contracts")
        if type(config) is not ScaleValidationConfig:
            raise TypeError("scaled validation requires ScaleValidationConfig")
        producers = {
            ValidationKind.WALK_FORWARD: self._walk_forward,
            ValidationKind.COST_SLIPPAGE_STRESS: self._stress,
            ValidationKind.COUNTERFACTUAL: self._counterfactual,
            ValidationKind.MONTE_CARLO: self._monte_carlo,
            ValidationKind.SCENARIO_REPLAY: self._scenario,
            ValidationKind.PARAMETER_SWEEP: self._sweep,
            ValidationKind.STRATEGY_COMPARE: self._compare,
        }
        return tuple(
            self._artifact(kind, dataset, strategy, config, *producers[kind](dataset, strategy, config))
            for kind in ALL_VALIDATIONS
        )

    def run_batch(
        self,
        requests: tuple[tuple[FrozenValidationDataset, StrategyDefinition, ScaleValidationConfig], ...],
    ) -> tuple[tuple[ValidationArtifact, ...], ...]:
        if not requests:
            raise ValueError("scaled validation batch cannot be empty")
        return tuple(self.run(*request) for request in requests)

    def _artifact(
        self,
        kind: ValidationKind,
        dataset: FrozenValidationDataset,
        strategy: StrategyDefinition,
        config: ScaleValidationConfig,
        status: ArtifactStatus,
        result: Mapping[str, JsonValue],
        warnings: tuple[str, ...],
    ) -> ValidationArtifact:
        frozen_config = config.for_kind(kind)
        identity = canonical_sha256(
            {
                "kind": kind.value,
                "dataset": dataset.content_sha256,
                "strategy": strategy.to_dict(),
                "config": cast(JsonValue, frozen_config),
            }
        )
        return ValidationArtifact(
            EntityId.deterministic("validation_artifact", identity),
            kind,
            status,
            dataset.content_sha256,
            strategy.strategy_ref.content_sha256,
            frozen_config,
            result,
            warnings,
            (dataset.dataset_ref, strategy.strategy_ref),
        )

    def _walk_forward(
        self, dataset: FrozenValidationDataset, strategy: StrategyDefinition, config: ScaleValidationConfig
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        values = _trade_returns(dataset, strategy, cost=config.base_cost)
        start = config.train_size + config.embargo_size
        folds: list[dict[str, JsonValue]] = []
        while start + config.test_size <= len(values):
            window = values[start : start + config.test_size]
            folds.append({"start": start, "end": start + config.test_size, **_summary(window)})
            start += config.step_size
        if not folds:
            return ArtifactStatus.INCOMPLETE, {}, ("insufficient samples for one chronological OOS fold",)
        return ArtifactStatus.COMPLETE, {"folds": tuple(folds)}, ()

    def _stress(
        self, dataset: FrozenValidationDataset, strategy: StrategyDefinition, config: ScaleValidationConfig
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        rows = tuple(
            {
                "cost_multiplier": _text(multiplier),
                "slippage": _text(slippage),
                **_summary(
                    _trade_returns(
                        dataset,
                        strategy,
                        cost=config.base_cost * multiplier,
                        slippage=slippage,
                    )
                ),
            }
            for multiplier in config.cost_multipliers
            for slippage in config.slippage_values
        )
        return ArtifactStatus.COMPLETE, {"scenarios": rows}, ()

    def _counterfactual(
        self, dataset: FrozenValidationDataset, strategy: StrategyDefinition, config: ScaleValidationConfig
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        opposite = (
            StrategyDirection.INVERT if strategy.direction is StrategyDirection.FOLLOW else StrategyDirection.FOLLOW
        )
        inverted = StrategyDefinition(strategy.strategy_ref, strategy.threshold, opposite)
        return (
            ArtifactStatus.COMPLETE,
            {
                "base": _summary(_trade_returns(dataset, strategy, cost=config.base_cost)),
                "invert": _summary(_trade_returns(dataset, inverted, cost=config.base_cost)),
                "zero_signal": _summary(tuple(Decimal("0") for _ in dataset.features)),
            },
            (),
        )

    def _monte_carlo(
        self, dataset: FrozenValidationDataset, strategy: StrategyDefinition, config: ScaleValidationConfig
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        signals = _signals(dataset, strategy)
        values = tuple(
            value
            for signal, value in zip(
                signals,
                _trade_returns(dataset, strategy, cost=config.base_cost),
                strict=True,
            )
            if signal
        )
        if not values:
            return ArtifactStatus.INCOMPLETE, {}, ("Monte Carlo requires at least one trade return",)
        rng = random.Random(config.monte_carlo_seed)
        totals = tuple(
            sum((values[rng.randrange(len(values))] for _ in values), Decimal("0"))
            for _ in range(config.monte_carlo_iterations)
        )
        ordered = tuple(sorted(totals))
        result: dict[str, JsonValue] = {
            "iterations": config.monte_carlo_iterations,
            "trade_count": len(values),
            "p05_net_return": _text(ordered[max(0, len(ordered) * 5 // 100 - 1)]),
            "median_net_return": _text(ordered[len(ordered) // 2]),
            "p95_net_return": _text(ordered[min(len(ordered) - 1, len(ordered) * 95 // 100)]),
            "distribution_sha256": canonical_sha256(tuple(_text(value) for value in totals)),
        }
        warnings: tuple[str, ...] = ("Monte Carlo trade sample is smaller than 20",) if len(values) < 20 else ()
        return ArtifactStatus.COMPLETE, result, warnings

    def _scenario(
        self, dataset: FrozenValidationDataset, strategy: StrategyDefinition, config: ScaleValidationConfig
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        if any(item.end_index > len(dataset.features) for item in config.scenarios):
            return ArtifactStatus.INCOMPLETE, {}, ("scenario range exceeds the frozen dataset",)
        signals = _signals(dataset, strategy)
        rows = []
        for scenario in config.scenarios:
            values = tuple(
                Decimal(signals[index]) * dataset.forward_returns[index] * scenario.return_multiplier
                - (config.base_cost + scenario.extra_cost if signals[index] else Decimal("0"))
                for index in range(scenario.start_index, scenario.end_index)
            )
            rows.append({"scenario": scenario.name, **_summary(values)})
        return ArtifactStatus.COMPLETE, {"scenarios": tuple(rows)}, ()

    def _sweep(
        self,
        dataset: FrozenValidationDataset,
        strategy: StrategyDefinition,
        config: ScaleValidationConfig,
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        rows: list[dict[str, JsonValue]] = []
        for threshold in config.parameter_grid:
            variant = StrategyDefinition(strategy.strategy_ref, threshold, strategy.direction)
            rows.append(
                {
                    "threshold": _text(threshold),
                    **_summary(_trade_returns(dataset, variant, cost=config.base_cost)),
                }
            )
        return ArtifactStatus.COMPLETE, {"parameters": tuple(rows)}, ()

    def _compare(
        self,
        dataset: FrozenValidationDataset,
        strategy: StrategyDefinition,
        config: ScaleValidationConfig,
    ) -> tuple[ArtifactStatus, Mapping[str, JsonValue], tuple[str, ...]]:
        refs = {item.strategy_ref.content_sha256 for item in config.comparison_strategies}
        includes_primary = strategy.strategy_ref.content_sha256 in refs
        warnings = () if includes_primary else ("primary strategy omitted from comparison",)
        rows = tuple(
            {
                "strategy_ref": item.strategy_ref.to_dict(),
                **_summary(_trade_returns(dataset, item, cost=config.base_cost)),
            }
            for item in config.comparison_strategies
        )
        status = ArtifactStatus.COMPLETE if includes_primary else ArtifactStatus.INCOMPLETE
        return status, {"strategies": rows}, warnings


class CompatibleSource(StrEnum):
    V1 = "V1_RESEARCH_VALIDATION"
    V2 = "V2_SIMULATION_REPLAY"


@dataclass(frozen=True, slots=True)
class CompatibleEvidence:
    source: CompatibleSource
    source_ref: PinnedRef
    kind: ValidationKind
    config: Mapping[str, JsonValue]
    result: Mapping[str, JsonValue]
    warnings: tuple[str, ...]
    complete: bool

    def __post_init__(self) -> None:
        if type(self.source) is not CompatibleSource or type(self.source_ref) is not PinnedRef:
            raise TypeError("compatible evidence requires typed source and pinned reference")
        if self.kind not in {
            ValidationKind.WALK_FORWARD,
            ValidationKind.COST_SLIPPAGE_STRESS,
            ValidationKind.COUNTERFACTUAL,
        }:
            raise ValueError("V1/V2 compatibility is limited to existing foundational validations")
        frozen_config = _freeze(self.config)
        frozen_result = _freeze(self.result)
        if not isinstance(frozen_config, Mapping) or not isinstance(frozen_result, Mapping):
            raise ValueError("compatible evidence config and result must be objects")
        object.__setattr__(self, "config", frozen_config)
        object.__setattr__(self, "result", frozen_result)
        if self.source_ref.content_sha256 != canonical_sha256(cast(JsonValue, frozen_result)):
            raise ValueError("compatible source ref must bind the exact source result payload")
        if type(self.warnings) is not tuple or any(type(item) is not str or not item.strip() for item in self.warnings):
            raise ValueError("compatible warnings must be immutable non-empty strings")
        if type(self.complete) is not bool:
            raise TypeError("compatible evidence completeness must be explicit")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "source": self.source.value,
                "source_ref": self.source_ref.to_dict(),
                "kind": self.kind.value,
                "config": cast(JsonValue, self.config),
                "result": cast(JsonValue, self.result),
                "warnings": self.warnings,
                "complete": self.complete,
            }
        )

    def replay(self, expected_sha256: str) -> CompatibleEvidence:
        if self.content_sha256 != expected_sha256:
            raise ValueError("compatible evidence replay digest mismatch")
        return self

    def to_artifact(self, dataset: FrozenValidationDataset, strategy: StrategyDefinition) -> ValidationArtifact:
        status = ArtifactStatus.COMPLETE if self.complete else ArtifactStatus.INCOMPLETE
        return ValidationArtifact(
            EntityId.deterministic("validation_artifact", self.content_sha256),
            self.kind,
            status,
            dataset.content_sha256,
            strategy.strategy_ref.content_sha256,
            self.config,
            self.result,
            self.warnings,
            (self.source_ref, dataset.dataset_ref, strategy.strategy_ref),
        )


def assemble_promotion_evidence(artifacts: tuple[ValidationArtifact, ...]) -> PromotionEvidencePackage:
    if not artifacts:
        raise ValueError("promotion evidence cannot be empty")
    by_kind = {item.kind: item for item in artifacts}
    if len(by_kind) != len(artifacts):
        raise ValueError("promotion evidence cannot contain duplicate validations")
    ordered = tuple(by_kind[kind] for kind in ALL_VALIDATIONS if kind in by_kind)
    seed = canonical_sha256(tuple(item.content_sha256 for item in ordered))
    return PromotionEvidencePackage(
        EntityId.deterministic("promotion_evidence", seed),
        artifacts[0].dataset_sha256,
        artifacts[0].strategy_sha256,
        ordered,
    )


__all__ = [
    "ALL_VALIDATIONS",
    "ArtifactStatus",
    "CompatibleEvidence",
    "CompatibleSource",
    "FrozenValidationDataset",
    "PromotionEvidencePackage",
    "ScaleValidationConfig",
    "ScaleValidationRunner",
    "ScenarioDefinition",
    "StrategyDefinition",
    "StrategyDirection",
    "ValidationArtifact",
    "ValidationKind",
    "assemble_promotion_evidence",
]
