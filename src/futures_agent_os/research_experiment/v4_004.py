"""Deterministic research return attribution, never an accounting writer.

All amounts are additive return contributions on one fixed capital base. Dates
use UTC close time. Drawdown is closed-observation equity, not intraday MTM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
import json
from typing import TYPE_CHECKING, Mapping, cast

from futures_agent_os.shared_kernel.observability import JsonValue
from .v4_003 import (
    ArtifactStatus,
    FrozenValidationDataset,
    StrategyDefinition,
    StrategyDirection,
    ValidationArtifact,
    ValidationKind,
)

if TYPE_CHECKING:
    from futures_agent_os.execution_simulation.strategy_replay import FrozenStrategySpecFixture

ZERO = Decimal("0")


def _finite(value: Decimal, name: str, *, positive: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite() or (positive and value < 0):
        raise ValueError(f"{name} requires a finite {'non-negative ' if positive else ''}Decimal")


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("close time must be timezone aware")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class AttributionTrade:
    source_id: str
    closed_at: str
    instrument: str
    regime: str
    side: str
    gross_return: Decimal
    costs: tuple[tuple[str, Decimal], ...]
    rollover: bool = False

    def __post_init__(self) -> None:
        if any(type(x) is not str or not x.strip() for x in (self.source_id, self.instrument, self.regime)):
            raise ValueError("trade classifications and source identity are required")
        _time(self.closed_at)
        if self.side not in ("LONG", "SHORT") or type(self.rollover) is not bool:
            raise ValueError("trade direction/rollover must be explicit")
        _finite(self.gross_return, "gross return")
        if type(self.costs) is not tuple or any(type(x) is not tuple or len(x) != 2 for x in self.costs):
            raise ValueError("cost components must be immutable pairs")
        if len({x[0] for x in self.costs}) != len(self.costs):
            raise ValueError("duplicate cost component")
        for name, amount in self.costs:
            if type(name) is not str or not name.strip():
                raise ValueError("cost component needs a name")
            _finite(amount, "cost", positive=True)

    @property
    def cost(self) -> Decimal:
        return sum((amount for _, amount in self.costs), ZERO)

    @property
    def net_return(self) -> Decimal:
        return self.gross_return - self.cost


@dataclass(frozen=True)
class AttributionSource:
    trades: tuple[AttributionTrade, ...]
    source_ref: str
    dataset_sha256: str
    strategy_sha256: str
    complete: bool = True
    data_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.trades) is not tuple or any(type(x) is not AttributionTrade for x in self.trades):
            raise ValueError("source requires immutable typed trades")
        if not self.source_ref or not self.dataset_sha256 or not self.strategy_sha256:
            raise ValueError("source and input references are required")
        if len({x.source_id for x in self.trades}) != len(self.trades):
            raise ValueError("duplicate source trade")
        if type(self.complete) is not bool or type(self.data_gaps) is not tuple:
            raise ValueError("completeness and gaps must be explicit")
        if any(type(x) is not str or not x.strip() for x in self.data_gaps):
            raise ValueError("gap descriptions must be non-empty")

    @classmethod
    def from_validation(
        cls,
        dataset: FrozenValidationDataset,
        strategy: StrategyDefinition,
        *,
        base_cost: Decimal,
        instruments: tuple[str, ...],
        regimes: tuple[str, ...],
    ) -> AttributionSource:
        """Read the same frozen observations/signal/cost semantics as V4-003."""
        _finite(base_cost, "base cost", positive=True)
        if len(instruments) != len(dataset.features) or len(regimes) != len(dataset.features):
            raise ValueError("classifications must align with every observation")
        direction = 1 if strategy.direction is StrategyDirection.FOLLOW else -1
        trades = []
        for i, feature in enumerate(dataset.features):
            signal = direction * (1 if feature > strategy.threshold else -1 if feature < -strategy.threshold else 0)
            if signal:
                trades.append(
                    AttributionTrade(
                        f"{dataset.dataset_ref.identity}:{i}",
                        dataset.event_times[i],
                        instruments[i],
                        regimes[i],
                        "LONG" if signal > 0 else "SHORT",
                        Decimal(signal) * dataset.forward_returns[i],
                        (("modeled_cost", base_cost),),
                    )
                )
        return cls(
            tuple(trades), dataset.dataset_ref.identity, dataset.content_sha256, strategy.strategy_ref.content_sha256
        )

    @classmethod
    def from_fixture(
        cls,
        fixture: FrozenStrategySpecFixture,
        *,
        instrument: str,
        regimes: tuple[str, ...],
    ) -> AttributionSource:
        """Read V2's shared replay fixture; these are return proxies, not L2 fills."""
        if len(regimes) != len(fixture.signals):
            raise ValueError("regimes must align with fixture observations")
        trades = tuple(
            AttributionTrade(
                f"{fixture.fixture_id}:{i}",
                fixture.label_times[i],
                instrument,
                regimes[i],
                "LONG" if signal > 0 else "SHORT",
                Decimal(signal) * fixture.forward_returns[i],
                (("modeled_cost", fixture.per_signal_cost),),
            )
            for i, signal in enumerate(fixture.signals)
            if signal
        )
        if any(signal not in (-1, 0, 1) for signal in fixture.signals):
            raise ValueError("fixture signals must be unit directions")
        return cls(trades, fixture.fixture_id, fixture.fixture_hash, fixture.fixture_hash)


@dataclass(frozen=True)
class AttributionPolicy:
    min_samples: int = 20
    concentration_share: Decimal = Decimal("0.60")
    parameter_spread: Decimal = Decimal("0.50")
    cost_share: Decimal = Decimal("0.50")
    tolerance: Decimal = Decimal("0.00000001")
    worst_count: int = 5

    def __post_init__(self) -> None:
        for n in (self.min_samples, self.worst_count):
            if type(n) is not int or n < 1:
                raise ValueError("sample and ranking bounds must be positive integers")
        for name in ("concentration_share", "parameter_spread", "cost_share", "tolerance"):
            _finite(getattr(self, name), name, positive=True)
        if not ZERO < self.concentration_share <= 1:
            raise ValueError("concentration share must be in (0, 1]")


@dataclass(frozen=True)
class AttributionWarning:
    code: str
    scope: str
    detail: str


@dataclass(frozen=True)
class AttributionBucket:
    key: str
    count: int
    gross: Decimal
    cost: Decimal
    net: Decimal


def _bucket(key: str, trades: tuple[AttributionTrade, ...]) -> AttributionBucket:
    return AttributionBucket(
        key,
        len(trades),
        sum((x.gross_return for x in trades), ZERO),
        sum((x.cost for x in trades), ZERO),
        sum((x.net_return for x in trades), ZERO),
    )


@dataclass(frozen=True)
class DrawdownEvent:
    peak_at: str | None
    trough_at: str
    recovered_at: str | None
    depth: Decimal


@dataclass(frozen=True)
class AttributionReport:
    source: AttributionSource
    policy: AttributionPolicy
    total: AttributionBucket
    tables: tuple[tuple[str, tuple[AttributionBucket, ...]], ...]
    cost_components: tuple[tuple[str, Decimal], ...]
    drawdowns: tuple[DrawdownEvent, ...]
    worst_trades: tuple[AttributionTrade, ...]
    parameter_results: tuple[tuple[Decimal, Decimal], ...]
    parameter_artifact_ref: str | None
    warnings: tuple[AttributionWarning, ...]

    @property
    def complete(self) -> bool:
        return self.source.complete and not self.source.data_gaps and bool(self.source.trades)

    def to_dict(self) -> dict[str, JsonValue]:
        from dataclasses import fields, is_dataclass

        def encode(value: object) -> JsonValue:
            if isinstance(value, Decimal):
                return format(value, "f")
            if is_dataclass(value) and not isinstance(value, type):
                return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
            if isinstance(value, tuple):
                return tuple(encode(x) for x in value)
            if value is None or type(value) in (str, bool, int):
                return cast(JsonValue, value)
            raise TypeError("unsupported report value")

        result = cast(dict[str, JsonValue], encode(self))
        result.update(
            schema_version="v4-004.v1",
            complete=self.complete,
            units="additive_return_on_fixed_capital",
            calendar="UTC close time",
            drawdown_semantics="closed-observation equity; no intraday MTM",
            parameter_use="diagnostic only; no parameter selection or qualification",
        )
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2)

    def to_html(self) -> str:
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Research attribution</title>'
            "<body><h1>Research attribution</h1><p>Additive returns on fixed capital; closed-observation "
            "drawdown. Research and simulation only.</p><pre>" + escape(self.to_json()) + "</pre></body></html>"
        )


class AttributionAnalyzer:
    def analyze(
        self,
        source: AttributionSource,
        *,
        policy: AttributionPolicy = AttributionPolicy(),
        parameter_sweep: ValidationArtifact | None = None,
        expected_net: Decimal | None = None,
        expected_cost: Decimal | None = None,
    ) -> AttributionReport:
        trades = tuple(sorted(source.trades, key=lambda x: (_time(x.closed_at), x.source_id)))
        total = _bucket("TOTAL", trades)
        for actual, expected in ((total.net, expected_net), (total.cost, expected_cost)):
            if expected is not None:
                _finite(expected, "expected total")
                if abs(actual - expected) > policy.tolerance:
                    raise ValueError("attribution does not reconcile with expected source total")
        warnings = []
        tables = []
        for dimension in ("year", "month", "instrument", "regime", "side"):
            groups: dict[str, list[AttributionTrade]] = {}
            for trade in trades:
                key = (
                    _time(trade.closed_at).strftime("%Y" if dimension == "year" else "%Y-%m")
                    if dimension in ("year", "month")
                    else getattr(trade, dimension)
                )
                groups.setdefault(key, []).append(trade)
            rows = tuple(_bucket(k, tuple(v)) for k, v in sorted(groups.items()))
            for field in ("gross", "cost", "net"):
                if abs(sum((getattr(x, field) for x in rows), ZERO) - getattr(total, field)) > policy.tolerance:
                    raise ValueError("dimension attribution does not reconcile")
            tables.append((dimension, rows))
            absolute_total = sum((abs(t.net_return) for t in trades), ZERO)
            for key, values in sorted(groups.items()):
                share = sum((abs(t.net_return) for t in values), ZERO) / absolute_total if absolute_total else ZERO
                if share >= policy.concentration_share:
                    warnings.append(
                        AttributionWarning(
                            "RETURN_CONCENTRATION", f"{dimension}:{key}", f"absolute net contribution share={share}"
                        )
                    )
                if len(values) < policy.min_samples:
                    warnings.append(AttributionWarning("SAMPLE_SHORTAGE", f"{dimension}:{key}", f"count={len(values)}"))
        if len(trades) < policy.min_samples:
            warnings.append(AttributionWarning("SAMPLE_SHORTAGE", "total", f"count={len(trades)}"))
        components: dict[str, Decimal] = {}
        for trade in trades:
            for name, amount in trade.costs:
                components[name] = components.get(name, ZERO) + amount
        if abs(sum(components.values(), ZERO) - total.cost) > policy.tolerance:
            raise ValueError("cost attribution does not reconcile")
        gross_magnitude = sum((abs(x.gross_return) for x in trades), ZERO)
        if total.cost > 0 and (gross_magnitude == 0 or total.cost >= gross_magnitude * policy.cost_share):
            warnings.append(
                AttributionWarning(
                    "COST_SENSITIVITY", "total", "cost consumes configured share of absolute gross returns"
                )
            )
        if source.data_gaps or not source.complete:
            warnings.append(
                AttributionWarning("DATA_GAP", "source", "; ".join(source.data_gaps) or "source incomplete")
            )
        absolute_total = sum((abs(t.net_return) for t in trades), ZERO)
        rollover_total = sum((abs(t.net_return) for t in trades if t.rollover), ZERO)
        if absolute_total and rollover_total / absolute_total >= policy.concentration_share:
            warnings.append(
                AttributionWarning("ROLLOVER_CONCENTRATION", "total", "rollover share exceeds configured threshold")
            )
        parameters: tuple[tuple[Decimal, Decimal], ...] = ()
        if parameter_sweep is None:
            warnings.append(AttributionWarning("PARAMETER_EVIDENCE_MISSING", "parameters", "no sweep supplied"))
        else:
            if parameter_sweep.kind is not ValidationKind.PARAMETER_SWEEP:
                raise ValueError("parameter diagnostic requires a parameter sweep")
            if (
                parameter_sweep.dataset_sha256 != source.dataset_sha256
                or parameter_sweep.strategy_sha256 != source.strategy_sha256
            ):
                raise ValueError("parameter evidence does not bind source dataset/strategy")
            if parameter_sweep.status is not ArtifactStatus.COMPLETE:
                warnings.append(AttributionWarning("PARAMETER_EVIDENCE_INCOMPLETE", "parameters", "sweep incomplete"))
            else:
                rows_raw = parameter_sweep.result.get("parameters")
                if not isinstance(rows_raw, (tuple, list)):
                    raise ValueError("sweep requires parameter rows")
                parsed = []
                for row in rows_raw:
                    if not isinstance(row, Mapping):
                        raise ValueError("sweep row requires an object")
                    threshold, net = Decimal(str(row.get("threshold"))), Decimal(str(row.get("net_return")))
                    _finite(threshold, "threshold", positive=True)
                    _finite(net, "parameter return")
                    parsed.append((threshold, net))
                parameters = tuple(parsed)
                if len({x[0] for x in parameters}) != len(parameters):
                    raise ValueError("duplicate parameter rows")
                if len(parameters) < 2:
                    warnings.append(
                        AttributionWarning("SAMPLE_SHORTAGE", "parameters", "fewer than two parameter points")
                    )
                else:
                    parameter_values = tuple(x[1] for x in parameters)
                    scale: Decimal = max((abs(x) for x in parameter_values), default=ZERO)
                    spread = (max(parameter_values) - min(parameter_values)) / scale if scale else ZERO
                    if spread > policy.parameter_spread:
                        warnings.append(
                            AttributionWarning("PARAMETER_INSTABILITY", "parameters", f"normalized spread={spread}")
                        )
        # Aggregate simultaneous closes before drawing the equity curve.
        closes: dict[datetime, Decimal] = {}
        for trade in trades:
            time = _time(trade.closed_at)
            closes[time] = closes.get(time, ZERO) + trade.net_return
        equity = peak = ZERO
        peak_at = None
        trough_at = None
        depth = ZERO
        drawdowns = []
        for time, amount in sorted(closes.items()):
            equity += amount
            if equity >= peak:
                if trough_at is not None:
                    drawdowns.append(DrawdownEvent(peak_at, trough_at, time.isoformat(), depth))
                peak, peak_at, trough_at, depth = equity, time.isoformat(), None, ZERO
            elif equity - peak < depth:
                depth, trough_at = equity - peak, time.isoformat()
        if trough_at is not None:
            drawdowns.append(DrawdownEvent(peak_at, trough_at, None, depth))
        return AttributionReport(
            source,
            policy,
            total,
            tuple(tables),
            tuple(sorted(components.items())),
            tuple(drawdowns),
            tuple(sorted(trades, key=lambda x: (x.net_return, x.source_id))[: policy.worst_count]),
            parameters,
            str(parameter_sweep.artifact_id) if parameter_sweep else None,
            tuple(warnings),
        )
