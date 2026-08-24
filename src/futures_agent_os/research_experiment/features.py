"""Research-owned, immutable definitions of deterministic market features.

Definitions describe *what* a feature means.  Market Intelligence owns the
calculation and published observations; this module intentionally has no
market-data, Decision, Risk, or Execution dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.shared_kernel import EntityId, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


class FeatureAlgorithm(StrEnum):
    LAST_PRICE = "LAST_PRICE"
    BID_ASK_SPREAD = "BID_ASK_SPREAD"
    VOLUME = "VOLUME"
    OPEN_INTEREST = "OPEN_INTEREST"
    SIMPLE_RETURN = "SIMPLE_RETURN"
    REALIZED_VOLATILITY = "REALIZED_VOLATILITY"
    QUOTE_LIQUIDITY = "QUOTE_LIQUIDITY"


FEATURE_ALGORITHM_VERSION = "fao.feature.v1"


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """A versioned research meaning, never an observation or code callback."""

    definition_id: EntityId
    name: str
    version: int
    schema_version: SchemaVersion
    algorithm: FeatureAlgorithm
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, EntityId) or self.definition_id.namespace != "feature_definition":
            raise ValueError("feature definition requires a feature_definition id")
        if not isinstance(self.name, str) or not self.name.strip() or self.name != self.name.strip():
            raise ValueError("feature definition requires a canonical non-empty name")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("feature definition version must be positive")
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.algorithm, FeatureAlgorithm):
            raise TypeError("feature definition requires schema and algorithm versions")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("feature definition requires a description")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str | int]:
        return {
            "definition_id": str(self.definition_id),
            "name": self.name,
            "version": self.version,
            "schema_version": str(self.schema_version),
            "algorithm": self.algorithm.value,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class FeatureDefinitionRef:
    definition_id: EntityId
    version: int
    schema_version: SchemaVersion
    content_sha256: str
    algorithm: FeatureAlgorithm

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, EntityId) or self.definition_id.namespace != "feature_definition":
            raise ValueError("feature definition ref requires a feature_definition id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("feature definition ref version must be positive")
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.algorithm, FeatureAlgorithm):
            raise TypeError("feature definition ref requires SchemaVersion and FeatureAlgorithm")
        _digest(self.content_sha256, "feature definition ref")

    @classmethod
    def from_definition(cls, value: FeatureDefinition) -> FeatureDefinitionRef:
        return cls(value.definition_id, value.version, value.schema_version, value.content_sha256, value.algorithm)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "definition_id": str(self.definition_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "content_sha256": self.content_sha256,
            "algorithm": self.algorithm.value,
        }


@dataclass(frozen=True, slots=True)
class FeatureSpecRef:
    spec_id: EntityId
    version: int
    schema_version: SchemaVersion
    content_sha256: str
    definition: FeatureDefinitionRef

    def __post_init__(self) -> None:
        if not isinstance(self.spec_id, EntityId) or self.spec_id.namespace != "feature_spec":
            raise ValueError("feature spec ref requires a feature_spec id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("feature spec ref version must be positive")
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.definition, FeatureDefinitionRef):
            raise TypeError("feature spec ref requires schema and definition")
        _digest(self.content_sha256, "feature spec ref")

    @classmethod
    def from_spec(cls, value: FeatureSpec) -> FeatureSpecRef:
        return cls(
            value.spec_id,
            value.version,
            value.schema_version,
            value.content_sha256,
            FeatureDefinitionRef.from_definition(value.definition),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "spec_id": str(self.spec_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "content_sha256": self.content_sha256,
            "definition": self.definition.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """An immutable calculation contract selected by a research consumer."""

    spec_id: EntityId
    definition: FeatureDefinition
    version: int
    schema_version: SchemaVersion
    algorithm_version: str
    window_size: int
    output_scale: int
    missing_value_policy: str
    state_horizon: str = "WINDOW"
    bar_cadence: str = "SNAPSHOT"
    bar_duration_seconds: int | None = None
    window_kind: str = "COUNT"
    final_only: bool = True
    cross_session_policy: str = "REJECT"
    normalization_policy: str = "NONE"
    observation_kind: str = "QUOTE"

    def __post_init__(self) -> None:
        if not isinstance(self.spec_id, EntityId) or self.spec_id.namespace != "feature_spec":
            raise ValueError("feature spec requires a feature_spec id")
        if not isinstance(self.definition, FeatureDefinition) or not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("feature spec requires a FeatureDefinition and SchemaVersion")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("feature spec version must be positive")
        if self.algorithm_version != FEATURE_ALGORITHM_VERSION:
            raise ValueError("unsupported feature algorithm_version")
        if isinstance(self.window_size, bool) or not isinstance(self.window_size, int) or self.window_size < 1:
            raise ValueError("feature spec window_size must be positive")
        if (
            self.definition.algorithm in (FeatureAlgorithm.SIMPLE_RETURN, FeatureAlgorithm.REALIZED_VOLATILITY)
            and self.window_size < 2
        ):
            raise ValueError("return and volatility feature specs require window_size at least two")
        if (
            isinstance(self.output_scale, bool)
            or not isinstance(self.output_scale, int)
            or not 0 <= self.output_scale <= 18
        ):
            raise ValueError("feature spec output_scale must be between 0 and 18")
        if self.missing_value_policy != "REJECT":
            raise ValueError("V1 feature specs only support fail-closed missing_value_policy REJECT")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.state_horizon,
                self.bar_cadence,
                self.window_kind,
                self.cross_session_policy,
                self.normalization_policy,
            )
        ):
            raise ValueError("feature spec requires explicit window and normalization semantics")
        if self.window_kind != "COUNT" or self.cross_session_policy != "REJECT" or not self.final_only:
            raise ValueError("V1 feature specs require COUNT windows, FINAL-only inputs, and cross-session rejection")
        if self.bar_cadence == "SNAPSHOT" and self.bar_duration_seconds is not None:
            raise ValueError("SNAPSHOT cadence cannot declare bar duration")
        if self.bar_cadence != "SNAPSHOT" and (
            isinstance(self.bar_duration_seconds, bool)
            or not isinstance(self.bar_duration_seconds, int)
            or self.bar_duration_seconds < 60
        ):
            raise ValueError("bar cadence requires explicit duration seconds of at least one minute")
        if self.observation_kind not in {"QUOTE", "BAR", "TRADE", "SETTLEMENT", "OPEN_INTEREST"}:
            raise ValueError("feature spec requires an explicit supported observation_kind")
        if (self.bar_cadence == "SNAPSHOT") == (self.observation_kind == "BAR"):
            raise ValueError("BAR features require bar cadence and non-BAR features require SNAPSHOT cadence")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "spec_id": str(self.spec_id),
            "definition": self.definition.to_dict(),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "algorithm_version": self.algorithm_version,
            "window_size": self.window_size,
            "output_scale": self.output_scale,
            "missing_value_policy": self.missing_value_policy,
            "state_horizon": self.state_horizon,
            "bar_cadence": self.bar_cadence,
            "bar_duration_seconds": self.bar_duration_seconds,
            "window_kind": self.window_kind,
            "final_only": self.final_only,
            "cross_session_policy": self.cross_session_policy,
            "normalization_policy": self.normalization_policy,
            "observation_kind": self.observation_kind,
        }


def _digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} content_sha256 must be a lowercase SHA-256 digest")
