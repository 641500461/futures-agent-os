"""Governed recommendations and deterministic V5 advanced execution plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import RecordedAt, canonical_sha256


def _positive(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{label} must be a positive finite Decimal")


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError(f"{label} must be canonical text")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class ExecutionAlgorithm(StrEnum):
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"
    BATCHED_ENTRY = "BATCHED_ENTRY"
    BATCHED_EXIT = "BATCHED_EXIT"


class ExecutionIntent(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"


@dataclass(frozen=True, slots=True)
class ChildSlice:
    index: int
    quantity: Decimal
    participation: Decimal
    scheduled_at: RecordedAt | None = None
    display_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("slice index must be non-negative")
        _positive(self.quantity, "slice quantity")
        _positive(self.participation, "slice participation")
        if self.participation > 1:
            raise ValueError("slice participation cannot exceed one")
        if self.scheduled_at is not None and not isinstance(self.scheduled_at, RecordedAt):
            raise TypeError("scheduled_at must be RecordedAt")
        if self.display_quantity is not None:
            _positive(self.display_quantity, "display quantity")
            if self.display_quantity > self.quantity:
                raise ValueError("display quantity cannot exceed slice quantity")


def _weighted_allocations(quantity: Decimal, weights: tuple[Decimal, ...], lot_size: Decimal) -> tuple[Decimal, ...]:
    _positive(quantity, "quantity")
    _positive(lot_size, "lot_size")
    total_lots = quantity / lot_size
    if total_lots != total_lots.to_integral_value():
        raise ValueError("quantity must be an exact multiple of lot_size")
    if not weights or any(not weight.is_finite() or weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError("schedule weights must be finite, non-negative, and non-zero")
    normalized = tuple(weight / sum(weights) for weight in weights)
    raw_lots = tuple(total_lots * weight for weight in normalized)
    allocated_lots = [value.to_integral_value(rounding=ROUND_FLOOR) for value in raw_lots]
    remainder = int(total_lots - sum(allocated_lots))
    priority = sorted(range(len(weights)), key=lambda index: (-(raw_lots[index] - allocated_lots[index]), index))
    for index in priority[:remainder]:
        allocated_lots[index] += 1
    return tuple(lots * lot_size for lots in allocated_lots)


def schedule(
    algorithm: ExecutionAlgorithm,
    quantity: Decimal,
    slices: int,
    *,
    volumes: tuple[Decimal, ...] = (),
    display_quantity: Decimal | None = None,
    batch_weights: tuple[Decimal, ...] = (),
    lot_size: Decimal = Decimal("0.00000001"),
    start_at: RecordedAt | None = None,
    end_at: RecordedAt | None = None,
) -> tuple[ChildSlice, ...]:
    """Create a deterministic child schedule whose quantities exactly conserve the parent."""

    if not isinstance(algorithm, ExecutionAlgorithm):
        raise TypeError("algorithm must be ExecutionAlgorithm")
    _positive(quantity, "quantity")
    _positive(lot_size, "lot_size")
    if isinstance(slices, bool) or not isinstance(slices, int) or slices <= 0:
        raise ValueError("slices must be positive")
    if (start_at is None) != (end_at is None):
        raise ValueError("schedule time window requires both start_at and end_at")
    if start_at is not None:
        if not isinstance(start_at, RecordedAt) or not isinstance(end_at, RecordedAt):
            raise TypeError("schedule time window must use RecordedAt")
        if end_at.value <= start_at.value:
            raise ValueError("schedule end must follow start")

    displays: tuple[Decimal | None, ...]
    if algorithm is ExecutionAlgorithm.VWAP:
        if len(volumes) != slices or any(not volume.is_finite() or volume <= 0 for volume in volumes):
            raise ValueError("VWAP requires positive volume for every slice")
        allocations = _weighted_allocations(quantity, volumes, lot_size)
        displays = (None,) * slices
    elif algorithm is ExecutionAlgorithm.ICEBERG:
        if display_quantity is None:
            raise ValueError("ICEBERG requires display_quantity")
        _positive(display_quantity, "display_quantity")
        if (
            display_quantity < lot_size
            or display_quantity / lot_size != (display_quantity / lot_size).to_integral_value()
        ):
            raise ValueError("display_quantity must be an exact positive lot multiple")
        remaining = quantity
        chunks: list[Decimal] = []
        while remaining > 0 and len(chunks) < slices:
            child = min(display_quantity, remaining)
            chunks.append(child)
            remaining -= child
        if remaining > 0:
            raise ValueError("ICEBERG slice capacity cannot cover parent quantity")
        allocations = tuple(chunks)
        displays = tuple(chunks)
    elif algorithm in {ExecutionAlgorithm.BATCHED_ENTRY, ExecutionAlgorithm.BATCHED_EXIT}:
        if len(batch_weights) != slices:
            raise ValueError("batched execution requires one weight per slice")
        allocations = _weighted_allocations(quantity, batch_weights, lot_size)
        displays = (None,) * slices
    else:
        allocations = _weighted_allocations(quantity, (Decimal("1"),) * slices, lot_size)
        displays = (None,) * slices

    nonzero = tuple((amount, displays[index]) for index, amount in enumerate(allocations) if amount > 0)
    if not nonzero or sum((amount for amount, _ in nonzero), Decimal("0")) != quantity:
        raise ValueError("execution schedule must exactly conserve parent quantity")
    result: list[ChildSlice] = []
    for index, (amount, displayed) in enumerate(nonzero):
        scheduled_at: RecordedAt | None = None
        if start_at is not None and end_at is not None:
            total_microseconds = int((end_at.value - start_at.value).total_seconds() * 1_000_000)
            scheduled_at = RecordedAt.from_datetime(
                start_at.value + timedelta(microseconds=(total_microseconds * index) // len(nonzero))
            )
        result.append(ChildSlice(index, amount, amount / quantity, scheduled_at, displayed))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AlgorithmSpec:
    algorithm: ExecutionAlgorithm
    version: str
    supported_intents: tuple[ExecutionIntent, ...]
    min_slices: int
    max_slices: int

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, ExecutionAlgorithm):
            raise TypeError("algorithm spec requires ExecutionAlgorithm")
        _text(self.version, "algorithm version")
        if (
            not isinstance(self.supported_intents, tuple)
            or not self.supported_intents
            or any(not isinstance(intent, ExecutionIntent) for intent in self.supported_intents)
            or len(set(self.supported_intents)) != len(self.supported_intents)
        ):
            raise ValueError("algorithm spec requires unique supported intents")
        if self.min_slices < 1 or self.max_slices < self.min_slices:
            raise ValueError("algorithm spec requires valid slice bounds")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "algorithm": self.algorithm.value,
                    "version": self.version,
                    "supported_intents": tuple(intent.value for intent in self.supported_intents),
                    "min_slices": self.min_slices,
                    "max_slices": self.max_slices,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class AlgorithmActivation:
    specs: tuple[AlgorithmSpec, ...]
    activated_by: str
    activation_digest: str


class ExecutionAlgorithmRegistry:
    """Governance-owned registry; recommendations cannot mutate it."""

    def __init__(self) -> None:
        self._registered: dict[tuple[ExecutionAlgorithm, str], AlgorithmSpec] = {}
        self._active: dict[ExecutionAlgorithm, AlgorithmSpec] = {}
        self._active_actor = ""

    def register(self, spec: AlgorithmSpec) -> None:
        if not isinstance(spec, AlgorithmSpec):
            raise TypeError("registry requires AlgorithmSpec")
        key = (spec.algorithm, spec.version)
        if key in self._registered and self._registered[key] != spec:
            raise ValueError("algorithm version already registered with different content")
        self._registered[key] = spec

    def activate(self, algorithms: tuple[tuple[ExecutionAlgorithm, str], ...], *, actor: str) -> AlgorithmActivation:
        if not actor.startswith("user:"):
            raise ValueError("only a human governance actor may activate execution algorithms")
        if not algorithms or len({algorithm for algorithm, _ in algorithms}) != len(algorithms):
            raise ValueError("activation requires unique algorithms")
        specs: list[AlgorithmSpec] = []
        for key in algorithms:
            spec = self._registered.get(key)
            if spec is None:
                raise ValueError("cannot activate an unregistered algorithm version")
            specs.append(spec)
        payload = {"actor": actor, "specs": tuple(spec.digest for spec in specs)}
        activation = AlgorithmActivation(tuple(specs), actor, canonical_sha256(cast(Any, payload)))
        self._active = {spec.algorithm: spec for spec in specs}
        self._active_actor = actor
        return activation

    def require_active(self, algorithm: ExecutionAlgorithm, version: str, activation_digest: str) -> AlgorithmSpec:
        spec = self._active.get(algorithm)
        if spec is None or spec.version != version:
            raise ValueError("recommended algorithm version is not active")
        current = canonical_sha256(
            cast(
                Any,
                {
                    "actor": self._active_actor,
                    "specs": tuple(item.digest for item in self._active.values()),
                },
            )
        )
        if current != activation_digest:
            raise ValueError("algorithm activation is stale")
        return spec


@dataclass(frozen=True, slots=True)
class AdvancedExecutionRecommendation:
    """Proposal-only Agent output; it contains no child quantities or orders."""

    algorithm: ExecutionAlgorithm
    algorithm_version: str
    activation_digest: str
    intent: ExecutionIntent
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, ExecutionAlgorithm) or not isinstance(self.intent, ExecutionIntent):
            raise TypeError("recommendation requires typed algorithm and intent")
        _text(self.algorithm_version, "algorithm version")
        if len(self.activation_digest) != 64:
            raise ValueError("recommendation requires activation digest")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("recommendation requires rationale")


@dataclass(frozen=True, slots=True)
class DeterministicExecutionPlan:
    recommendation: AdvancedExecutionRecommendation
    parent_quantity: Decimal
    children: tuple[ChildSlice, ...]
    plan_digest: str


class AdvancedExecutionPlanner:
    def __init__(self, registry: ExecutionAlgorithmRegistry) -> None:
        self._registry = registry

    def plan(
        self,
        recommendation: AdvancedExecutionRecommendation,
        quantity: Decimal,
        slices: int,
        **schedule_options: Any,
    ) -> DeterministicExecutionPlan:
        if not isinstance(recommendation, AdvancedExecutionRecommendation):
            raise TypeError("planner requires AdvancedExecutionRecommendation")
        spec = self._registry.require_active(
            recommendation.algorithm, recommendation.algorithm_version, recommendation.activation_digest
        )
        if recommendation.intent not in spec.supported_intents:
            raise ValueError("algorithm is not active for the recommended intent")
        if not spec.min_slices <= slices <= spec.max_slices:
            raise ValueError("slice count is outside active algorithm bounds")
        children = schedule(recommendation.algorithm, quantity, slices, **schedule_options)
        digest = canonical_sha256(
            cast(
                Any,
                {
                    "algorithm": recommendation.algorithm.value,
                    "version": recommendation.algorithm_version,
                    "activation": recommendation.activation_digest,
                    "intent": recommendation.intent.value,
                    "quantity": _decimal_text(quantity),
                    "children": tuple(
                        {
                            "index": child.index,
                            "quantity": _decimal_text(child.quantity),
                            "participation": _decimal_text(child.participation),
                        }
                        for child in children
                    ),
                },
            )
        )
        return DeterministicExecutionPlan(recommendation, quantity, children, digest)


def recommend(
    activation: AlgorithmActivation,
    algorithm: ExecutionAlgorithm,
    *,
    intent: ExecutionIntent,
    rationale: str,
) -> AdvancedExecutionRecommendation:
    """Create a proposal only when the exact algorithm is in the activation snapshot."""

    if not isinstance(activation, AlgorithmActivation):
        raise TypeError("recommendation requires AlgorithmActivation")
    spec = next((item for item in activation.specs if item.algorithm is algorithm), None)
    if spec is None:
        raise ValueError("Agent may recommend only an active registered algorithm")
    if intent not in spec.supported_intents:
        raise ValueError("Agent may recommend only an algorithm active for this intent")
    return AdvancedExecutionRecommendation(algorithm, spec.version, activation.activation_digest, intent, rationale)


__all__ = [
    "AdvancedExecutionPlanner",
    "AdvancedExecutionRecommendation",
    "AlgorithmActivation",
    "AlgorithmSpec",
    "ChildSlice",
    "DeterministicExecutionPlan",
    "ExecutionAlgorithm",
    "ExecutionAlgorithmRegistry",
    "ExecutionIntent",
    "recommend",
    "schedule",
]
