"""Deterministic market-state interpretation; never a trade permission boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from enum import StrEnum

from futures_agent_os.market_intelligence.feature_engine import FeatureObservation, MarketSnapshotRef
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


class RegimeKind(StrEnum):
    UNKNOWN = "UNKNOWN"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"
    EVENT = "EVENT"
    LIMIT_RISK = "LIMIT_RISK"
    ROLLOVER = "ROLLOVER"


REGIME_ALGORITHM_VERSION = "fao.regime.v1"


def canonical_decimal(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(Decimal("0.00000001"))


@dataclass(frozen=True, slots=True)
class RegimeModelSpec:
    model_id: EntityId
    name: str
    version: int
    schema_version: SchemaVersion
    algorithm_version: str
    return_threshold: Decimal
    volatility_threshold: Decimal
    return_feature: FeatureSpecRef | None = None
    volatility_feature: FeatureSpecRef | None = None
    liquidity_feature: FeatureSpecRef | None = None
    liquidity_stress_below: Decimal | None = None
    state_horizon: str = "WINDOW"

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, EntityId) or self.model_id.namespace != "regime_model_spec":
            raise ValueError("regime model spec requires a regime_model_spec id")
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or not isinstance(self.schema_version, SchemaVersion)
        ):
            raise TypeError("regime model spec requires name and SchemaVersion")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("regime model spec version must be positive")
        if self.algorithm_version != REGIME_ALGORITHM_VERSION:
            raise ValueError("unsupported regime algorithm_version")
        for value in (self.return_threshold, self.volatility_threshold):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("regime model thresholds must be non-negative finite Decimal values")
            try:
                with localcontext() as context:
                    context.prec = 50
                    context.rounding = ROUND_HALF_EVEN
                    canonical = value.quantize(Decimal("0.00000001"))
            except InvalidOperation as error:
                raise ValueError("regime thresholds must fit fixed scale 8") from error
            if canonical != value:
                raise ValueError("regime thresholds exceed fixed scale 8")
        object.__setattr__(self, "return_threshold", canonical_decimal(self.return_threshold))
        object.__setattr__(self, "volatility_threshold", canonical_decimal(self.volatility_threshold))
        if not isinstance(self.state_horizon, str) or not self.state_horizon.strip():
            raise ValueError("regime model spec requires state_horizon")
        if (
            not isinstance(self.return_feature, FeatureSpecRef)
            or self.return_feature.definition.algorithm is not FeatureAlgorithm.SIMPLE_RETURN
        ):
            raise ValueError("regime model spec requires a SIMPLE_RETURN FeatureSpecRef")
        if (
            self.volatility_feature is not None
            and self.volatility_feature.definition.algorithm is not FeatureAlgorithm.REALIZED_VOLATILITY
        ):
            raise ValueError("regime volatility feature must be REALIZED_VOLATILITY")
        if (
            self.liquidity_feature is not None
            and self.liquidity_feature.definition.algorithm is not FeatureAlgorithm.QUOTE_LIQUIDITY
        ):
            raise ValueError("regime liquidity feature must be QUOTE_LIQUIDITY")
        if self.liquidity_stress_below is not None:
            if (
                not isinstance(self.liquidity_stress_below, Decimal)
                or not self.liquidity_stress_below.is_finite()
                or self.liquidity_stress_below < 0
            ):
                raise ValueError("liquidity stress threshold must be finite non-negative Decimal")
            canonical_liquidity = canonical_decimal(self.liquidity_stress_below)
            if canonical_liquidity != self.liquidity_stress_below:
                raise ValueError("liquidity stress threshold exceeds fixed scale 8")
            object.__setattr__(self, "liquidity_stress_below", canonical_liquidity)

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "model_id": str(self.model_id),
            "name": self.name,
            "version": self.version,
            "schema_version": str(self.schema_version),
            "algorithm_version": self.algorithm_version,
            "return_threshold": str(self.return_threshold),
            "volatility_threshold": str(self.volatility_threshold),
            "state_horizon": self.state_horizon,
            "return_feature": self.return_feature.to_dict() if self.return_feature else None,
            "volatility_feature": self.volatility_feature.to_dict() if self.volatility_feature else None,
            "liquidity_feature": self.liquidity_feature.to_dict() if self.liquidity_feature else None,
            "liquidity_stress_below": str(self.liquidity_stress_below)
            if self.liquidity_stress_below is not None
            else None,
        }


@dataclass(frozen=True, slots=True)
class RegimeCandidate:
    kind: RegimeKind
    score: Decimal
    support: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RegimeKind) or not isinstance(self.score, Decimal) or not self.score.is_finite():
            raise TypeError("regime candidates require a kind and finite Decimal score")
        if not 0 <= self.score <= 1:
            raise ValueError("regime candidate score must be between zero and one")
        for values in (self.support, self.counter_evidence, self.unknowns):
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError("regime evidence strings must be non-empty")
        object.__setattr__(self, "support", tuple(sorted(self.support)))
        object.__setattr__(self, "counter_evidence", tuple(sorted(self.counter_evidence)))
        object.__setattr__(self, "unknowns", tuple(sorted(self.unknowns)))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "score": str(self.score),
            "support": self.support,
            "counter_evidence": self.counter_evidence,
            "unknowns": self.unknowns,
        }


@dataclass(frozen=True, slots=True)
class FeatureArtifactRef:
    observation_id: EntityId
    content_sha256: str

    @classmethod
    def from_observation(cls, value: FeatureObservation) -> FeatureArtifactRef:
        return cls(value.observation_id, value.content_sha256)

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "feature_observation":
            raise ValueError("regime feature ref requires feature_observation id")
        if len(self.content_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.content_sha256):
            raise ValueError("regime feature ref requires lowercase SHA-256")

    def to_dict(self) -> dict[str, str]:
        return {"observation_id": str(self.observation_id), "content_sha256": self.content_sha256}

    def to_content_dict(self) -> dict[str, str]:
        return {"content_sha256": self.content_sha256}


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    assessment_id: EntityId
    model_spec: RegimeModelSpec
    as_of: RecordedAt
    state_horizon: str
    terminal_market_snapshot_ref: MarketSnapshotRef
    feature_observation_refs: tuple[FeatureArtifactRef, ...]
    candidates: tuple[RegimeCandidate, ...]
    conflicts: tuple[tuple[RegimeKind, RegimeKind], ...]
    unknowns: tuple[str, ...]
    authority: ModelOutputAuthority
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.assessment_id, EntityId) or self.assessment_id.namespace != "regime_assessment":
            raise ValueError("regime assessment requires a regime_assessment id")
        if (
            not isinstance(self.model_spec, RegimeModelSpec)
            or not isinstance(self.as_of, RecordedAt)
            or not isinstance(self.terminal_market_snapshot_ref, MarketSnapshotRef)
        ):
            raise TypeError("regime assessment requires model spec and as_of")
        refs = tuple(
            sorted(self.feature_observation_refs, key=lambda item: (item.content_sha256, str(item.observation_id)))
        )
        candidates = tuple(sorted(self.candidates, key=lambda item: item.kind.value))
        conflicts = tuple(sorted(self.conflicts, key=lambda item: (item[0].value, item[1].value)))
        unknowns = tuple(sorted(self.unknowns))
        if any(not isinstance(item, FeatureArtifactRef) for item in refs) or len(
            {(item.observation_id, item.content_sha256) for item in refs}
        ) != len(refs):
            raise ValueError("regime assessment requires unique typed feature refs")
        if not candidates or any(not isinstance(item, RegimeCandidate) for item in candidates):
            raise ValueError("regime assessment requires candidates")
        if self.authority is not ModelOutputAuthority.NON_TRADING:
            raise ValueError("regime assessment is never trading authority")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(kind, RegimeKind) for kind in pair)
            or pair[0] == pair[1]
            for pair in conflicts
        ) or len(set(conflicts)) != len(conflicts):
            raise ValueError("regime conflicts must be unique pairs of distinct RegimeKind values")
        if any(not isinstance(item, str) or not item for item in unknowns):
            raise ValueError("regime unknowns must be non-empty strings")
        feature_hashes = {item.content_sha256 for item in refs}
        for candidate in candidates:
            for evidence in (*candidate.support, *candidate.counter_evidence):
                if (
                    len(evidence) == 64
                    and all(char in "0123456789abcdef" for char in evidence)
                    and evidence not in feature_hashes
                ):
                    raise ValueError("regime feature evidence hash must belong to assessment refs")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "feature_observation_refs", refs)
        object.__setattr__(self, "conflicts", conflicts)
        object.__setattr__(self, "unknowns", unknowns)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("regime assessment content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "model_spec": self.model_spec.to_dict(),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "state_horizon": self.state_horizon,
            "terminal_market_snapshot_ref": self.terminal_market_snapshot_ref.to_dict(),
            "feature_observation_refs": tuple(item.to_content_dict() for item in self.feature_observation_refs),
            "candidates": tuple(item.to_dict() for item in sorted(self.candidates, key=lambda item: item.kind.value)),
            "conflicts": tuple((left.value, right.value) for left, right in self.conflicts),
            "unknowns": tuple(sorted(self.unknowns)),
            "authority": self.authority.value,
        }

    def trading_authorization(self) -> Failure:
        return Failure(
            ReasonCode.MODEL_OUTPUT_NOT_AUTHORIZATION,
            "regime assessment is market interpretation, never trading permission",
        )


class RegimeModelService:
    def evaluate(self, spec: RegimeModelSpec, features: tuple[FeatureObservation, ...]) -> RegimeAssessment:
        if (
            not isinstance(spec, RegimeModelSpec)
            or not features
            or any(not isinstance(item, FeatureObservation) for item in features)
        ):
            raise ValueError("regime model service requires immutable feature observations")
        ordered = tuple(sorted(features, key=lambda item: item.content_sha256))
        as_ofs = {item.as_of for item in ordered}
        if len(as_ofs) != 1:
            raise ValueError("regime model features must share exactly one as_of")
        terminal_refs = {item.market_snapshot_refs[-1] for item in ordered}
        if len(terminal_refs) != 1:
            raise ValueError("regime model features must share exactly one terminal MarketSnapshotRef")
        returns = tuple(item for item in ordered if item.feature_spec == spec.return_feature)
        volatilities = tuple(item for item in ordered if item.feature_spec == spec.volatility_feature)
        liquidities = tuple(item for item in ordered if item.feature_spec == spec.liquidity_feature)
        if len(returns) > 1 or len(volatilities) > 1 or len(liquidities) > 1:
            raise ValueError("regime model requires at most one FeatureObservation for each bound FeatureSpecRef")
        unknowns: list[str] = [
            "EVENT: no point-in-time event evidence in V1-005",
            "ROLLOVER: no cross-component derived dataset in V1-005",
        ]
        candidates: list[RegimeCandidate] = []
        if returns:
            value = returns[-1].value.amount.copy_abs()
            evidence = (returns[-1].content_sha256,)
            if value >= spec.return_threshold:
                candidates.extend(
                    (
                        RegimeCandidate(RegimeKind.TREND, Decimal("0.70"), evidence, (), ()),
                        RegimeCandidate(
                            RegimeKind.MEAN_REVERSION, Decimal("0.30"), evidence, ("same return supports trend",), ()
                        ),
                    )
                )
            else:
                candidates.extend(
                    (
                        RegimeCandidate(RegimeKind.MEAN_REVERSION, Decimal("0.55"), evidence, (), ()),
                        RegimeCandidate(
                            RegimeKind.TREND, Decimal("0.10"), evidence, ("return below trend threshold",), ()
                        ),
                    )
                )
        else:
            unknowns.append("no bound SIMPLE_RETURN FeatureObservation was supplied")
        if volatilities:
            volatility = volatilities[0]
            if volatility.value.unit != "ratio" or volatility.value.currency is not None:
                raise ValueError("regime volatility feature must be a currency-free ratio")
            if volatility.value.amount >= spec.volatility_threshold:
                candidates.append(
                    RegimeCandidate(RegimeKind.HIGH_VOLATILITY, Decimal("0.60"), (volatility.content_sha256,), (), ())
                )
            else:
                candidates.append(
                    RegimeCandidate(RegimeKind.LOW_VOLATILITY, Decimal("0.60"), (volatility.content_sha256,), (), ())
                )
        elif spec.volatility_feature is not None:
            unknowns.append("bound REALIZED_VOLATILITY FeatureObservation is absent")
        if spec.liquidity_feature is None:
            unknowns.append("no QUOTE_LIQUIDITY feature is bound")
        elif not liquidities:
            unknowns.append("bound QUOTE_LIQUIDITY FeatureObservation is absent")
        elif spec.liquidity_stress_below is None:
            unknowns.append("QUOTE_LIQUIDITY has no bound stress threshold")
        else:
            liquidity = liquidities[-1]
            if liquidity.value.currency is not None or liquidity.value.unit == "ratio":
                raise ValueError("regime liquidity feature must be a currency-free quantity")
            if liquidity.value.amount <= spec.liquidity_stress_below:
                candidates.append(
                    RegimeCandidate(RegimeKind.LIQUIDITY_STRESS, Decimal("0.60"), (liquidity.content_sha256,), (), ())
                )
            else:
                candidates.append(
                    RegimeCandidate(RegimeKind.LIQUIDITY_STRESS, Decimal("0.10"), (), (liquidity.content_sha256,), ())
                )
        unknowns.append("LIMIT_RISK: no bound typed limit-risk feature in V1-005")
        if not candidates:
            candidates.append(RegimeCandidate(RegimeKind.UNKNOWN, Decimal("0.00"), (), (), tuple(unknowns)))
        conflicts = (
            ((RegimeKind.MEAN_REVERSION, RegimeKind.TREND),)
            if any(item.kind is RegimeKind.TREND for item in candidates)
            else ()
        )
        as_of = next(iter(as_ofs))
        terminal_ref = next(iter(terminal_refs))
        refs = tuple(FeatureArtifactRef.from_observation(item) for item in ordered)
        canonical_candidates = tuple(sorted(candidates, key=lambda item: item.kind.value))
        payload: dict[str, JsonValue] = {
            "model_spec": spec.to_dict(),
            "as_of": as_of.to_dict()["recorded_at"],
            "state_horizon": spec.state_horizon,
            "terminal_market_snapshot_ref": terminal_ref.to_dict(),
            "feature_observation_refs": tuple(
                item.to_content_dict()
                for item in sorted(refs, key=lambda item: (item.content_sha256, str(item.observation_id)))
            ),
            "candidates": tuple(item.to_dict() for item in canonical_candidates),
            "conflicts": tuple((left.value, right.value) for left, right in conflicts),
            "unknowns": tuple(sorted(unknowns)),
            "authority": ModelOutputAuthority.NON_TRADING.value,
        }
        return RegimeAssessment(
            EntityId.new("regime_assessment"),
            spec,
            as_of,
            spec.state_horizon,
            terminal_ref,
            refs,
            canonical_candidates,
            conflicts,
            tuple(unknowns),
            ModelOutputAuthority.NON_TRADING,
            canonical_sha256(payload),
        )
