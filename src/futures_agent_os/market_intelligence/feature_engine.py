"""Deterministic, point-in-time feature computation owned by Market Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import json
from typing import Mapping, cast

from futures_agent_os.reference_market_data import BarStatus, MarketObservation, MarketSnapshot, SnapshotPurpose
from futures_agent_os.research_experiment.features import (
    FeatureAlgorithm,
    FeatureDefinitionRef,
    FeatureSpec,
    FeatureSpecRef,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class MarketSnapshotRef:
    snapshot_id: EntityId
    content_sha256: str
    as_of: RecordedAt
    schema_version: SchemaVersion
    purpose: SnapshotPurpose

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, EntityId) or self.snapshot_id.namespace != "market_snapshot":
            raise ValueError("market snapshot ref requires market_snapshot id")
        _digest(self.content_sha256, "market snapshot ref")
        if (
            not isinstance(self.as_of, RecordedAt)
            or not isinstance(self.schema_version, SchemaVersion)
            or not isinstance(self.purpose, SnapshotPurpose)
        ):
            raise TypeError("market snapshot ref requires typed as_of/schema/purpose")

    @classmethod
    def from_snapshot(cls, snapshot: MarketSnapshot) -> MarketSnapshotRef:
        return cls(
            snapshot.snapshot_id,
            snapshot.expected_content_sha256,
            snapshot.as_of,
            snapshot.schema_version,
            snapshot.intended_purpose,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "content_sha256": self.content_sha256,
            "as_of": self.as_of.to_dict()["recorded_at"],
            "schema_version": str(self.schema_version),
            "purpose": self.purpose.value,
        }


@dataclass(frozen=True, slots=True)
class FeatureInputWindow:
    """Ordered frozen snapshots; all source time checks are repeated at the boundary."""

    snapshots: tuple[MarketSnapshot, ...]
    as_of: RecordedAt

    def __post_init__(self) -> None:
        snapshots = tuple(self.snapshots)
        if not snapshots or any(not isinstance(item, MarketSnapshot) for item in snapshots):
            raise ValueError("feature input window requires MarketSnapshot values")
        if not isinstance(self.as_of, RecordedAt):
            raise TypeError("feature input window requires RecordedAt as_of")
        ordered = tuple(sorted(snapshots, key=lambda item: (item.as_of.value, str(item.snapshot_id))))
        if ordered != snapshots:
            raise ValueError("feature input window snapshots must be in strict point-in-time order")
        if any(left.as_of.value >= right.as_of.value for left, right in zip(snapshots, snapshots[1:])):
            raise ValueError("feature input window snapshot as_of values must be strictly increasing")
        if len({item.snapshot_id for item in snapshots}) != len(snapshots):
            raise ValueError("feature input window cannot repeat a snapshot")
        if snapshots[-1].as_of != self.as_of or any(item.as_of.value > self.as_of.value for item in snapshots):
            raise ValueError("feature input window as_of must equal its latest snapshot as_of")
        if any(item.intended_purpose not in (SnapshotPurpose.RESEARCH, SnapshotPurpose.BACKTEST) for item in snapshots):
            raise ValueError("feature input window only permits RESEARCH or BACKTEST snapshots")
        if len({item.intended_purpose for item in snapshots}) != 1:
            raise ValueError("feature input window cannot mix RESEARCH and BACKTEST snapshots")
        if any(item.eligible_for(item.intended_purpose) is not None for item in snapshots):
            raise ValueError("feature input window requires purpose-eligible snapshots")
        refs = {observation.reference_id for snapshot in snapshots for observation in snapshot.active_observations}
        if len(refs) != 1:
            raise ValueError("feature input window cannot mix market references")
        components = {
            item.component_instrument.reference_id
            for snapshot in snapshots
            for item in snapshot.active_observations
            if item.component_instrument is not None
        }
        if len(components) > 1:
            raise ValueError("feature input window cannot cross continuous-series components")
        rule_refs = {item.rule_resolution.rule_set_ref for item in snapshots}
        if len(rule_refs) != 1:
            raise ValueError("feature input window cannot mix contract rule revisions")
        calendar_refs = {
            (
                item.trading_date_resolution.trading_date,
                item.trading_date_resolution.session_name,
                item.trading_date_resolution.calendar_ref,
            )
            for item in snapshots
        }
        if len(calendar_refs) != 1:
            raise ValueError(
                "feature input window cross_session_policy REJECT forbids crossing trading date or session"
            )
        for snapshot in snapshots:
            if any(
                obs.available_time.value > self.as_of.value or obs.ingested_at.value > self.as_of.value
                for obs in snapshot.active_observations
            ):
                raise ValueError("feature input window contains observations unavailable at as_of")
        object.__setattr__(self, "snapshots", snapshots)


@dataclass(frozen=True, slots=True)
class FeatureValue:
    amount: Decimal
    unit: str
    scale: int
    currency: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise TypeError("feature values require finite Decimal amounts")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("feature values require a unit")
        if isinstance(self.scale, bool) or not isinstance(self.scale, int) or not 0 <= self.scale <= 18:
            raise ValueError("feature value scale must be between 0 and 18")
        try:
            with localcontext() as context:
                context.prec = 50
                context.rounding = ROUND_HALF_EVEN
                quantized = self.amount.quantize(Decimal(1).scaleb(-self.scale), rounding=ROUND_HALF_EVEN)
        except InvalidOperation as error:
            raise ValueError("feature value cannot be represented at declared fixed-point scale") from error
        if self.amount != quantized:
            raise ValueError("feature value exceeds its declared fixed-point scale")
        object.__setattr__(self, "amount", quantized)
        if self.unit == "ratio" and self.currency is not None:
            raise ValueError("ratio feature values cannot have currency")
        if (
            self.unit != "ratio"
            and self.currency is not None
            and (
                len(self.currency) != 3 or not self.currency.isupper() or not self.unit.startswith(self.currency + "/")
            )
        ):
            raise ValueError("price feature values require ISO currency and canonical currency/unit")

    def to_dict(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "amount": f"{self.amount:.{self.scale}f}",
            "unit": self.unit,
            "scale": self.scale,
        }
        if self.currency is not None:
            payload["currency"] = self.currency
        return payload


@dataclass(frozen=True, slots=True)
class InputObservationRef:
    observation_id: EntityId
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "market_observation":
            raise ValueError("input observation ref requires market_observation id")
        _digest(self.content_sha256, "input observation ref")

    def to_dict(self) -> dict[str, str]:
        return {"observation_id": str(self.observation_id), "content_sha256": self.content_sha256}


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """A published value, with every selection and input bound into its hash."""

    observation_id: EntityId
    feature_spec_id: EntityId
    feature_spec_content_sha256: str
    feature_spec: FeatureSpecRef
    feature_definition: FeatureDefinitionRef
    feature_algorithm: FeatureAlgorithm
    target_reference_id: str
    as_of: RecordedAt
    input_window_size: int
    market_snapshot_refs: tuple[MarketSnapshotRef, ...]
    observation_ids: tuple[EntityId, ...]
    input_observation_refs: tuple[InputObservationRef, ...]
    value: FeatureValue
    schema_version: SchemaVersion
    content_sha256: str

    def __post_init__(self) -> None:
        snapshots = tuple(self.market_snapshot_refs)
        observation_ids = tuple(self.observation_ids)
        input_refs = tuple(self.input_observation_refs)
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "feature_observation":
            raise ValueError("feature observation requires a feature_observation id")
        if not isinstance(self.feature_spec_id, EntityId) or self.feature_spec_id.namespace != "feature_spec":
            raise ValueError("feature observation requires a feature_spec id")
        if (
            not isinstance(self.feature_definition, FeatureDefinitionRef)
            or not isinstance(self.feature_spec, FeatureSpecRef)
            or not isinstance(self.feature_algorithm, FeatureAlgorithm)
            or not isinstance(self.as_of, RecordedAt)
        ):
            raise TypeError("feature observation requires typed definition and as_of")
        if not isinstance(self.target_reference_id, str) or not self.target_reference_id.strip():
            raise ValueError("feature observation requires target market reference id")
        if (
            self.feature_spec.spec_id != self.feature_spec_id
            or self.feature_spec.content_sha256 != self.feature_spec_content_sha256
            or self.feature_spec.definition != self.feature_definition
            or self.feature_definition.algorithm is not self.feature_algorithm
        ):
            raise ValueError("feature observation feature spec/definition/algorithm refs must agree")
        if self.input_window_size != len(snapshots) or self.input_window_size < 1:
            raise ValueError("feature observation window must exactly name its snapshot refs")
        if any(not isinstance(item, MarketSnapshotRef) for item in snapshots) or any(
            not isinstance(item, EntityId) or item.namespace != "market_observation" for item in observation_ids
        ):
            raise TypeError("feature observation requires typed immutable input refs")
        if (
            any(not isinstance(item, InputObservationRef) for item in input_refs)
            or len(input_refs) != len(observation_ids)
            or observation_ids != tuple(item.observation_id for item in input_refs)
        ):
            raise TypeError("feature observation requires immutable per-observation refs")
        if len({item.snapshot_id for item in snapshots}) != len(snapshots):
            raise ValueError("feature observation cannot repeat a market snapshot")
        if any(left.as_of.value >= right.as_of.value for left, right in zip(snapshots, snapshots[1:])):
            raise ValueError("feature observation snapshot refs must be in strict point-in-time order")
        if snapshots[-1].as_of != self.as_of or any(item.as_of.value > self.as_of.value for item in snapshots):
            raise ValueError("feature observation as_of must equal its latest snapshot ref")
        if len({item.purpose for item in snapshots}) != 1:
            raise ValueError("feature observation cannot mix snapshot purposes")
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("feature observation cannot repeat an input observation")
        if not isinstance(self.value, FeatureValue) or not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("feature observation requires FeatureValue and SchemaVersion")
        if self.schema_version != self.feature_spec.schema_version:
            raise ValueError("feature observation schema must match its feature spec")
        if self.feature_algorithm in (FeatureAlgorithm.SIMPLE_RETURN, FeatureAlgorithm.REALIZED_VOLATILITY):
            if self.value.unit != "ratio" or self.value.currency is not None:
                raise ValueError("return and volatility observations require currency-free ratio FeatureValue")
        elif self.feature_algorithm in (FeatureAlgorithm.LAST_PRICE, FeatureAlgorithm.BID_ASK_SPREAD):
            if self.value.currency is None or not self.value.unit.startswith(self.value.currency + "/"):
                raise ValueError("price observations require currency-bearing canonical FeatureValue")
        elif self.value.currency is not None or self.value.unit == "ratio":
            raise ValueError("quantity observations require currency-free non-ratio FeatureValue")
        object.__setattr__(self, "market_snapshot_refs", snapshots)
        object.__setattr__(self, "observation_ids", observation_ids)
        object.__setattr__(self, "input_observation_refs", input_refs)
        actual = canonical_sha256(self.payload())
        if self.content_sha256 != actual:
            raise ValueError("feature observation content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "feature_spec_id": str(self.feature_spec_id),
            "feature_spec_content_sha256": self.feature_spec_content_sha256,
            "feature_spec": self.feature_spec.to_dict(),
            "feature_definition": self.feature_definition.to_dict(),
            "feature_algorithm": self.feature_algorithm.value,
            "target_reference_id": self.target_reference_id,
            "as_of": self.as_of.to_dict()["recorded_at"],
            "input_window_size": self.input_window_size,
            "market_snapshot_refs": tuple(item.to_dict() for item in self.market_snapshot_refs),
            "observation_ids": tuple(str(item) for item in self.observation_ids),
            "input_observation_refs": tuple(item.to_dict() for item in self.input_observation_refs),
            "value": self.value.to_dict(),
            "schema_version": str(self.schema_version),
        }

    @classmethod
    def hydrate(cls, observation_id: EntityId, value: Mapping[str, object]) -> FeatureObservation:
        """Recover the real owner type from its exact canonical payload."""

        _exact_keys(
            value,
            {
                "feature_spec_id",
                "feature_spec_content_sha256",
                "feature_spec",
                "feature_definition",
                "feature_algorithm",
                "target_reference_id",
                "as_of",
                "input_window_size",
                "market_snapshot_refs",
                "observation_ids",
                "input_observation_refs",
                "value",
                "schema_version",
            },
            "feature observation",
        )
        definition_payload = _mapping(value["feature_definition"], "feature definition ref")
        _exact_keys(
            definition_payload,
            {"definition_id", "version", "schema_version", "content_sha256", "algorithm"},
            "feature definition ref",
        )
        definition = FeatureDefinitionRef(
            EntityId.parse(_text(definition_payload["definition_id"], "definition_id")),
            _integer(definition_payload["version"], "definition version"),
            SchemaVersion.parse(_text(definition_payload["schema_version"], "definition schema_version")),
            _text(definition_payload["content_sha256"], "definition content_sha256"),
            FeatureAlgorithm(_text(definition_payload["algorithm"], "definition algorithm")),
        )
        spec_payload = _mapping(value["feature_spec"], "feature spec ref")
        _exact_keys(
            spec_payload,
            {"spec_id", "version", "schema_version", "content_sha256", "definition"},
            "feature spec ref",
        )
        nested_definition_payload = _mapping(spec_payload["definition"], "feature spec definition ref")
        _exact_keys(
            nested_definition_payload,
            {"definition_id", "version", "schema_version", "content_sha256", "algorithm"},
            "feature spec definition ref",
        )
        nested_definition = FeatureDefinitionRef(
            EntityId.parse(_text(nested_definition_payload["definition_id"], "definition_id")),
            _integer(nested_definition_payload["version"], "definition version"),
            SchemaVersion.parse(_text(nested_definition_payload["schema_version"], "definition schema_version")),
            _text(nested_definition_payload["content_sha256"], "definition content_sha256"),
            FeatureAlgorithm(_text(nested_definition_payload["algorithm"], "definition algorithm")),
        )
        spec = FeatureSpecRef(
            EntityId.parse(_text(spec_payload["spec_id"], "spec_id")),
            _integer(spec_payload["version"], "spec version"),
            SchemaVersion.parse(_text(spec_payload["schema_version"], "spec schema_version")),
            _text(spec_payload["content_sha256"], "spec content_sha256"),
            nested_definition,
        )
        snapshot_refs = tuple(
            _hydrate_snapshot_ref(item) for item in _sequence(value["market_snapshot_refs"], "snapshot refs")
        )
        observation_ids = tuple(
            EntityId.parse(_text(item, "observation_id"))
            for item in _sequence(value["observation_ids"], "observation ids")
        )
        input_refs = tuple(
            _hydrate_input_ref(item) for item in _sequence(value["input_observation_refs"], "input observation refs")
        )
        feature_value_payload = _mapping(value["value"], "feature value")
        allowed_value_keys = {"amount", "unit", "scale"}
        if "currency" in feature_value_payload:
            allowed_value_keys.add("currency")
        _exact_keys(feature_value_payload, allowed_value_keys, "feature value")
        currency_value = feature_value_payload.get("currency")
        currency = None if currency_value is None else _text(currency_value, "feature value currency")
        feature_value = FeatureValue(
            Decimal(_text(feature_value_payload["amount"], "feature value amount")),
            _text(feature_value_payload["unit"], "feature value unit"),
            _integer(feature_value_payload["scale"], "feature value scale"),
            currency,
        )
        canonical_payload: dict[str, JsonValue] = {
            "feature_spec_id": _text(value["feature_spec_id"], "feature_spec_id"),
            "feature_spec_content_sha256": _text(value["feature_spec_content_sha256"], "feature_spec_content_sha256"),
            "feature_spec": spec.to_dict(),
            "feature_definition": definition.to_dict(),
            "feature_algorithm": _text(value["feature_algorithm"], "feature_algorithm"),
            "target_reference_id": _text(value["target_reference_id"], "target_reference_id"),
            "as_of": _text(value["as_of"], "as_of"),
            "input_window_size": _integer(value["input_window_size"], "input_window_size"),
            "market_snapshot_refs": tuple(item.to_dict() for item in snapshot_refs),
            "observation_ids": tuple(str(item) for item in observation_ids),
            "input_observation_refs": tuple(item.to_dict() for item in input_refs),
            "value": feature_value.to_dict(),
            "schema_version": _text(value["schema_version"], "schema_version"),
        }
        try:
            supplied_json = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("feature observation payload must be finite canonical JSON data") from error
        if supplied_json != canonical_json_text(canonical_payload):
            raise ValueError("feature observation payload does not match its typed owner representation")
        return cls(
            observation_id,
            EntityId.parse(_text(value["feature_spec_id"], "feature_spec_id")),
            _text(value["feature_spec_content_sha256"], "feature_spec_content_sha256"),
            spec,
            definition,
            FeatureAlgorithm(_text(value["feature_algorithm"], "feature_algorithm")),
            _text(value["target_reference_id"], "target_reference_id"),
            RecordedAt.parse(_text(value["as_of"], "as_of")),
            _integer(value["input_window_size"], "input_window_size"),
            snapshot_refs,
            observation_ids,
            input_refs,
            feature_value,
            SchemaVersion.parse(_text(value["schema_version"], "schema_version")),
            canonical_sha256(canonical_payload),
        )


FeatureSnapshot = FeatureObservation


class FeatureEngine:
    def compute(self, spec: FeatureSpec, window: FeatureInputWindow) -> FeatureObservation:
        if not isinstance(spec, FeatureSpec) or not isinstance(window, FeatureInputWindow):
            raise TypeError("feature engine requires FeatureSpec and FeatureInputWindow")
        if len(window.snapshots) < spec.window_size:
            raise ValueError("feature input window has fewer snapshots than feature spec requires")
        selected = window.snapshots[-spec.window_size :]
        values, used = _values(spec.definition.algorithm, selected, spec.output_scale, spec.observation_kind)
        target_reference_id = used[0].reference_id
        if any(item.reference_id != target_reference_id for item in used):
            raise ValueError("feature selected observations cannot mix market references")
        if spec.final_only and any(
            item.bar_status is not None and item.bar_status is not BarStatus.FINAL for item in used
        ):
            raise ValueError("feature input window rejects non-final selected bars")
        if spec.bar_cadence != "SNAPSHOT":
            duration = spec.bar_duration_seconds
            assert duration is not None
            if any(
                item.bar_interval is None
                or item.bar_interval.label != spec.bar_cadence
                or int(item.bar_interval.duration.total_seconds()) != spec.bar_duration_seconds
                for item in used
            ):
                raise ValueError("feature spec bar_cadence requires matching BarInterval observations")
            if any(
                right.event_time.value - left.event_time.value != timedelta(seconds=duration)
                for left, right in zip(used, used[1:])
            ):
                raise ValueError("feature bar cadence REJECT requires contiguous event_time intervals")
        if any(left.event_time.value >= right.event_time.value for left, right in zip(used, used[1:])):
            raise ValueError("feature input observations must have strictly increasing event_time")
        unit, currency = _economic_dimension(spec.definition.algorithm, selected, spec.observation_kind)
        feature = FeatureValue(values, unit, spec.output_scale, currency)
        refs = tuple(MarketSnapshotRef.from_snapshot(item) for item in selected)
        input_refs = tuple(InputObservationRef(item.observation_id, _observation_hash(item)) for item in used)
        payload = {
            "feature_spec_id": str(spec.spec_id),
            "feature_spec_content_sha256": spec.content_sha256,
            "feature_spec": FeatureSpecRef.from_spec(spec).to_dict(),
            "feature_definition": FeatureDefinitionRef.from_definition(spec.definition).to_dict(),
            "feature_algorithm": spec.definition.algorithm.value,
            "target_reference_id": target_reference_id,
            "as_of": window.as_of.to_dict()["recorded_at"],
            "input_window_size": len(selected),
            "market_snapshot_refs": tuple(item.to_dict() for item in refs),
            "observation_ids": tuple(str(item.observation_id) for item in used),
            "input_observation_refs": tuple(item.to_dict() for item in input_refs),
            "value": feature.to_dict(),
            "schema_version": str(spec.schema_version),
        }
        result_hash = canonical_sha256(cast("JsonValue", payload))
        return FeatureObservation(
            EntityId.new("feature_observation"),
            spec.spec_id,
            spec.content_sha256,
            FeatureSpecRef.from_spec(spec),
            FeatureDefinitionRef.from_definition(spec.definition),
            spec.definition.algorithm,
            target_reference_id,
            window.as_of,
            len(selected),
            refs,
            tuple(item.observation_id for item in used),
            input_refs,
            feature,
            spec.schema_version,
            result_hash,
        )


def _values(
    algorithm: FeatureAlgorithm, snapshots: tuple[MarketSnapshot, ...], scale: int, observation_kind: str
) -> tuple[Decimal, tuple[MarketObservation, ...]]:
    if algorithm in (FeatureAlgorithm.LAST_PRICE, FeatureAlgorithm.SIMPLE_RETURN, FeatureAlgorithm.REALIZED_VOLATILITY):
        series = tuple(_price(item, observation_kind) for item in snapshots)
        observations = tuple(item[1] for item in series)
        numbers = tuple(item[0] for item in series)
        if algorithm is FeatureAlgorithm.LAST_PRICE:
            return _fixed(numbers[-1], scale), observations
        _same_price_dimension(series)
        if any(value == 0 for value in numbers[:-1]):
            raise ValueError("feature return input price cannot be zero")
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            returns = tuple((right / left) - Decimal(1) for left, right in zip(numbers, numbers[1:]))
            if algorithm is FeatureAlgorithm.SIMPLE_RETURN:
                return _fixed(returns[-1], scale), observations
            if not returns:
                raise ValueError("realized volatility requires at least two price snapshots")
            variance = sum((value * value for value in returns), _ZERO) / Decimal(len(returns))
            return _fixed(variance.sqrt(), scale), observations
    series = tuple(_quote_or_quantity(item, algorithm, observation_kind) for item in snapshots)
    return _fixed(series[-1][0], scale), tuple(item[1] for item in series)


def _price(snapshot: MarketSnapshot, observation_kind: str) -> tuple[Decimal, MarketObservation]:
    options = tuple(
        obs
        for obs in snapshot.active_observations
        if obs.kind.value == observation_kind and (obs.last_price is not None or obs.close_price is not None)
    )
    if not options:
        raise ValueError("feature input snapshot has no price observation")
    picked = max(options, key=lambda item: (item.event_time.value, item.source_sequence, str(item.observation_id)))
    value = picked.last_price or picked.close_price
    assert value is not None
    return Decimal(value.amount), picked


def _quote_or_quantity(
    snapshot: MarketSnapshot, algorithm: FeatureAlgorithm, observation_kind: str
) -> tuple[Decimal, MarketObservation]:
    if algorithm is FeatureAlgorithm.BID_ASK_SPREAD:
        options = tuple(
            obs
            for obs in snapshot.active_observations
            if obs.kind.value == observation_kind and obs.bid_price is not None and obs.ask_price is not None
        )
        if not options:
            raise ValueError("feature input snapshot has no two-sided quote")
        picked = max(options, key=lambda item: (item.event_time.value, item.source_sequence, str(item.observation_id)))
        assert picked.bid_price is not None and picked.ask_price is not None
        return Decimal(picked.ask_price.amount) - Decimal(picked.bid_price.amount), picked
    field = "open_interest" if algorithm is FeatureAlgorithm.OPEN_INTEREST else "volume"
    if algorithm is FeatureAlgorithm.QUOTE_LIQUIDITY:
        options = tuple(
            obs
            for obs in snapshot.active_observations
            if obs.kind.value == observation_kind and obs.bid_size is not None and obs.ask_size is not None
        )
        if not options:
            raise ValueError("feature input snapshot has no two-sided quote depth")
        picked = max(options, key=lambda item: (item.event_time.value, item.source_sequence, str(item.observation_id)))
        assert picked.bid_size is not None and picked.ask_size is not None
        return min(Decimal(picked.bid_size.amount), Decimal(picked.ask_size.amount)), picked
    options = tuple(
        obs
        for obs in snapshot.active_observations
        if obs.kind.value == observation_kind and getattr(obs, field) is not None
    )
    if not options:
        raise ValueError(f"feature input snapshot has no {field}")
    picked = max(options, key=lambda item: (item.event_time.value, item.source_sequence, str(item.observation_id)))
    quantity = getattr(picked, field)
    assert quantity is not None
    return Decimal(quantity.amount), picked


def _economic_dimension(
    algorithm: FeatureAlgorithm, snapshots: tuple[MarketSnapshot, ...], observation_kind: str
) -> tuple[str, str | None]:
    if algorithm in (FeatureAlgorithm.SIMPLE_RETURN, FeatureAlgorithm.REALIZED_VOLATILITY):
        return "ratio", None
    if algorithm in (FeatureAlgorithm.LAST_PRICE, FeatureAlgorithm.BID_ASK_SPREAD):
        _, observation = (
            _price(snapshots[-1], observation_kind)
            if algorithm is FeatureAlgorithm.LAST_PRICE
            else _quote_or_quantity(snapshots[-1], algorithm, observation_kind)
        )
        price = observation.last_price or observation.close_price or observation.ask_price
        assert price is not None
        return price.unit, price.currency
    _, observation = _quote_or_quantity(snapshots[-1], algorithm, observation_kind)
    if algorithm is FeatureAlgorithm.QUOTE_LIQUIDITY:
        assert observation.bid_size is not None
        return observation.bid_size.unit, None
    quantity = observation.open_interest if algorithm is FeatureAlgorithm.OPEN_INTEREST else observation.volume
    assert quantity is not None
    return quantity.unit, None


def _same_price_dimension(series: tuple[tuple[Decimal, MarketObservation], ...]) -> None:
    dimensions = set()
    for _, observation in series:
        price = observation.last_price or observation.close_price
        assert price is not None
        dimensions.add((price.currency, price.unit, price.scale))
    if len(dimensions) != 1:
        raise ValueError("feature input window cannot mix price currency, unit, or scale")


def _observation_hash(observation: MarketObservation) -> str:
    # `MarketObservation` is frozen; its canonical repr contains all its typed
    # source fields and makes every exact input record explicit in lineage.
    return canonical_sha256({"observation": repr(observation)})


def _fixed(value: Decimal, scale: int) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)


def _digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} content_sha256 must be a lowercase SHA-256 digest")


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields are not exact")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{label} must be an array")
    return tuple(value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _hydrate_snapshot_ref(value: object) -> MarketSnapshotRef:
    payload = _mapping(value, "market snapshot ref")
    _exact_keys(
        payload,
        {"snapshot_id", "content_sha256", "as_of", "schema_version", "purpose"},
        "market snapshot ref",
    )
    return MarketSnapshotRef(
        EntityId.parse(_text(payload["snapshot_id"], "snapshot_id")),
        _text(payload["content_sha256"], "snapshot content_sha256"),
        RecordedAt.parse(_text(payload["as_of"], "snapshot as_of")),
        SchemaVersion.parse(_text(payload["schema_version"], "snapshot schema_version")),
        SnapshotPurpose(_text(payload["purpose"], "snapshot purpose")),
    )


def _hydrate_input_ref(value: object) -> InputObservationRef:
    payload = _mapping(value, "input observation ref")
    _exact_keys(payload, {"observation_id", "content_sha256"}, "input observation ref")
    return InputObservationRef(
        EntityId.parse(_text(payload["observation_id"], "observation_id")),
        _text(payload["content_sha256"], "observation content_sha256"),
    )
