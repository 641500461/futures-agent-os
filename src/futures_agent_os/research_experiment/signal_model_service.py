"""Research-owned deterministic Signals; intentionally incapable of trade authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from typing import Mapping, Protocol
from types import MappingProxyType

from futures_agent_os.research_experiment.features import FeatureAlgorithm, FeatureSpecRef
from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    ModelOutputAuthority,
    ReasonCode,
    RecordedAt,
    SchemaVersion,
    canonical_sha256,
)
from futures_agent_os.shared_kernel.observability import JsonValue


class SignalKind(StrEnum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"


class SignalDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


SIGNAL_ALGORITHM_VERSION = "fao.signal.v1"


class FeatureObservationPort(Protocol):
    observation_id: EntityId
    feature_algorithm: FeatureAlgorithm
    feature_spec: FeatureSpecRef
    as_of: RecordedAt
    content_sha256: str

    def payload(self) -> Mapping[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class FeatureEvidenceRef:
    """R&E's immutable anti-corruption reference to a published MI feature."""

    observation_id: EntityId
    content_sha256: str
    feature_spec: FeatureSpecRef
    as_of: RecordedAt
    source_payload: Mapping[str, JsonValue]

    @classmethod
    def from_published(cls, value: FeatureObservationPort) -> FeatureEvidenceRef:
        if (
            not isinstance(value.observation_id, EntityId)
            or not isinstance(value.content_sha256, str)
            or not isinstance(value.feature_spec, FeatureSpecRef)
            or not isinstance(value.as_of, RecordedAt)
            or not callable(value.payload)
        ):
            raise TypeError("published feature must satisfy the immutable FeatureObservation port")
        payload = value.payload()
        if not isinstance(payload, Mapping):
            raise TypeError("published feature payload must be a mapping")
        frozen = _freeze_json(payload)
        assert isinstance(frozen, Mapping)
        return cls(
            value.observation_id,
            value.content_sha256,
            value.feature_spec,
            value.as_of,
            frozen,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "feature_observation":
            raise ValueError("feature evidence requires feature_observation id")
        if len(self.content_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.content_sha256):
            raise ValueError("feature evidence requires lowercase SHA-256")
        if not isinstance(self.feature_spec, FeatureSpecRef) or not isinstance(self.as_of, RecordedAt):
            raise TypeError("feature evidence requires immutable feature spec and as_of")
        payload = _freeze_json(self.source_payload)
        assert isinstance(payload, Mapping)
        if canonical_sha256(payload) != self.content_sha256:
            raise ValueError("feature evidence payload must match published feature content_sha256")
        if (
            payload.get("feature_spec") != self.feature_spec.to_dict()
            or payload.get("as_of") != self.as_of.to_dict()["recorded_at"]
        ):
            raise ValueError("feature evidence fields must agree with published payload")
        value = payload.get("value")
        if (
            not isinstance(value, Mapping)
            or not isinstance(value.get("amount"), str)
            or not isinstance(value.get("unit"), str)
        ):
            raise TypeError("feature evidence payload requires typed value")
        if self.feature_spec.definition.algorithm is FeatureAlgorithm.SIMPLE_RETURN and (
            value["unit"] != "ratio" or "currency" in value
        ):
            raise ValueError("return evidence requires currency-free ratio")
        object.__setattr__(self, "source_payload", payload)

    @property
    def amount(self) -> Decimal:
        value = self.source_payload["value"]
        assert isinstance(value, Mapping)
        amount = Decimal(str(value["amount"]))
        if not amount.is_finite():
            raise ValueError("feature evidence amount must be finite")
        return amount

    @property
    def unit(self) -> str:
        value = self.source_payload["value"]
        assert isinstance(value, Mapping)
        return str(value["unit"])

    @property
    def currency(self) -> str | None:
        value = self.source_payload["value"]
        assert isinstance(value, Mapping)
        currency = value.get("currency")
        return currency if isinstance(currency, str) else None


def _freeze_json(value: JsonValue) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("feature evidence payload keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    raise TypeError("feature evidence payload must be JSON-compatible")


@dataclass(frozen=True, slots=True)
class SignalDefinition:
    definition_id: EntityId
    name: str
    version: int
    schema_version: SchemaVersion
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, EntityId) or self.definition_id.namespace != "signal_definition":
            raise ValueError("signal definition requires a signal_definition id")
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or not isinstance(self.schema_version, SchemaVersion)
        ):
            raise TypeError("signal definition requires name and schema version")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("signal definition version must be positive")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("signal definition requires description")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "definition_id": str(self.definition_id),
            "name": self.name,
            "version": self.version,
            "schema_version": str(self.schema_version),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SignalModelSpec:
    model_id: EntityId
    definition: SignalDefinition
    version: int
    schema_version: SchemaVersion
    algorithm_version: str
    threshold: Decimal
    input_feature: FeatureSpecRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, EntityId) or self.model_id.namespace != "signal_model_spec":
            raise ValueError("signal model spec requires a signal_model_spec id")
        if not isinstance(self.definition, SignalDefinition) or not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("signal model spec requires SignalDefinition and SchemaVersion")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("signal model spec version must be positive")
        if self.algorithm_version != SIGNAL_ALGORITHM_VERSION:
            raise ValueError("unsupported signal algorithm_version")
        if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite() or self.threshold < 0:
            raise ValueError("signal model threshold must be finite non-negative Decimal")
        try:
            with localcontext() as context:
                context.prec = 50
                context.rounding = ROUND_HALF_EVEN
                canonical = self.threshold.quantize(Decimal("0.00000001"))
        except InvalidOperation as error:
            raise ValueError("signal threshold must fit fixed scale 8") from error
        if canonical != self.threshold:
            raise ValueError("signal threshold exceeds fixed scale 8")
        object.__setattr__(self, "threshold", canonical)
        if (
            not isinstance(self.input_feature, FeatureSpecRef)
            or self.input_feature.definition.algorithm is not FeatureAlgorithm.SIMPLE_RETURN
        ):
            raise ValueError("signal model requires a SIMPLE_RETURN input_feature FeatureSpecRef")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "model_id": str(self.model_id),
            "definition": self.definition.to_dict(),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "algorithm_version": self.algorithm_version,
            "threshold": str(self.threshold),
            "input_feature": self.input_feature.to_dict() if self.input_feature else None,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class Signal:
    kind: SignalKind
    direction: SignalDirection
    strength: Decimal
    feature_observation_ref: str
    feature_observation_id: EntityId

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SignalKind) or not isinstance(self.direction, SignalDirection):
            raise TypeError("signals require a kind and direction")
        if not isinstance(self.strength, Decimal) or not self.strength.is_finite() or not 0 <= self.strength <= 1:
            raise ValueError("signal strength must be a finite Decimal from zero through one")
        if (
            not isinstance(self.feature_observation_id, EntityId)
            or self.feature_observation_id.namespace != "feature_observation"
        ):
            raise ValueError("signal requires feature_observation id")
        if len(self.feature_observation_ref) != 64 or any(
            char not in "0123456789abcdef" for char in self.feature_observation_ref
        ):
            raise ValueError("signal requires immutable feature observation hash")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "direction": self.direction.value,
            "strength": str(self.strength),
            "feature_observation_ref": self.feature_observation_ref,
            "feature_observation_id": str(self.feature_observation_id),
        }

    def to_content_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "direction": self.direction.value,
            "strength": str(self.strength),
            "feature_observation_ref": self.feature_observation_ref,
        }


@dataclass(frozen=True, slots=True)
class SignalResult:
    result_id: EntityId
    model_spec: SignalModelSpec
    as_of: RecordedAt
    signals: tuple[Signal, ...]
    conflicts: tuple[tuple[SignalKind, SignalKind], ...]
    authority: ModelOutputAuthority
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, EntityId) or self.result_id.namespace != "signal_result":
            raise ValueError("signal result requires a signal_result id")
        if not isinstance(self.model_spec, SignalModelSpec) or not isinstance(self.as_of, RecordedAt):
            raise TypeError("signal result requires model spec and as_of")
        signals = tuple(sorted(tuple(self.signals), key=lambda item: item.kind.value))
        conflicts = tuple(sorted(tuple(self.conflicts), key=lambda item: (item[0].value, item[1].value)))
        if not signals or any(not isinstance(item, Signal) for item in signals):
            raise ValueError("signal result requires Signals")
        if self.authority is not ModelOutputAuthority.NON_TRADING:
            raise ValueError("signals are never trading authority")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(kind, SignalKind) for kind in pair)
            or pair[0] == pair[1]
            for pair in conflicts
        ) or len(set(conflicts)) != len(conflicts):
            raise ValueError("signal conflicts must be unique pairs of distinct SignalKind values")
        object.__setattr__(self, "conflicts", conflicts)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("signal result content_sha256 does not match immutable content")
        object.__setattr__(self, "signals", signals)

    def payload(self) -> dict[str, JsonValue]:
        return {
            "model_spec": self.model_spec.to_dict(),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "signals": tuple(item.to_content_dict() for item in sorted(self.signals, key=lambda item: item.kind.value)),
            "conflicts": tuple((left.value, right.value) for left, right in self.conflicts),
            "authority": self.authority.value,
        }

    def trading_authorization(self) -> Failure:
        return Failure(ReasonCode.MODEL_OUTPUT_NOT_AUTHORIZATION, "signal is research output, never trading permission")


class SignalModelService:
    def evaluate(self, spec: SignalModelSpec, features: tuple[FeatureEvidenceRef, ...]) -> SignalResult:
        if (
            not isinstance(spec, SignalModelSpec)
            or not features
            or any(not isinstance(item, FeatureEvidenceRef) for item in features)
        ):
            raise ValueError("signal model service requires immutable feature observations")
        ordered = tuple(sorted(features, key=lambda item: item.content_sha256))
        as_ofs = {item.as_of for item in ordered}
        if len(as_ofs) != 1:
            raise ValueError("signal model features must share exactly one as_of")
        selected = tuple(item for item in ordered if item.feature_spec == spec.input_feature)
        if len(selected) != 1:
            raise ValueError("signal model requires exactly one bound input FeatureEvidenceRef")
        feature = selected[0]
        amount = feature.amount
        direction = SignalDirection.BULLISH if amount >= 0 else SignalDirection.BEARISH
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            strength = min(Decimal(1), amount.copy_abs() / max(spec.threshold, Decimal("0.00000001")))
        opposite = SignalDirection.BEARISH if direction is SignalDirection.BULLISH else SignalDirection.BULLISH
        signals = (
            Signal(SignalKind.MOMENTUM, direction, strength, feature.content_sha256, feature.observation_id),
            Signal(SignalKind.MEAN_REVERSION, opposite, strength, feature.content_sha256, feature.observation_id),
        )
        conflicts = ((SignalKind.MEAN_REVERSION, SignalKind.MOMENTUM),)
        as_of = next(iter(as_ofs))
        payload: dict[str, JsonValue] = {
            "model_spec": spec.to_dict(),
            "as_of": as_of.to_dict()["recorded_at"],
            "signals": tuple(item.to_content_dict() for item in sorted(signals, key=lambda item: item.kind.value)),
            "conflicts": tuple((left.value, right.value) for left, right in conflicts),
            "authority": ModelOutputAuthority.NON_TRADING.value,
        }
        return SignalResult(
            EntityId.new("signal_result"),
            spec,
            as_of,
            signals,
            conflicts,
            ModelOutputAuthority.NON_TRADING,
            canonical_sha256(payload),
        )
