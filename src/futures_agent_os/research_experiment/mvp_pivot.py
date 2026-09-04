"""Deterministic point-in-time hypothesis-family screening for the MVP-R Pivot."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_validation import HypothesisFamily, ResearchConclusion, ResearchConclusionKind


PIVOT_HYPOTHESIS_FAMILIES = (
    HypothesisFamily.MOMENTUM_CONTINUATION,
    HypothesisFamily.MEAN_REVERSION,
    HypothesisFamily.BREAKOUT_CONTINUATION,
    HypothesisFamily.FALSE_BREAKOUT_REVERSAL,
    HypothesisFamily.PARTICIPATION_CONFIRMED_TREND,
    HypothesisFamily.VOLATILITY_COMPRESSION_BREAKOUT,
)


@dataclass(frozen=True, slots=True)
class HypothesisFamilyScreen:
    family: HypothesisFamily
    cutoff_direction: int
    signal_count: int
    signal_accuracy: Decimal
    net_return: Decimal
    stressed_net_return: Decimal
    positive_fold_ratio: Decimal

    def __post_init__(self) -> None:
        for field in ("signal_accuracy", "net_return", "stressed_net_return", "positive_fold_ratio"):
            value = getattr(self, field)
            if type(value) is not Decimal or not value.is_finite():
                raise TypeError("Pivot screen metrics must be finite Decimals")
            object.__setattr__(self, field, value.quantize(Decimal("0.00000001")))
        if self.family not in PIVOT_HYPOTHESIS_FAMILIES:
            raise ValueError("Pivot screen requires a registered directional family")
        if (
            type(self.cutoff_direction) is not int
            or self.cutoff_direction not in {-1, 0, 1}
            or type(self.signal_count) is not int
            or self.signal_count < 0
        ):
            raise ValueError("Pivot screen requires a bounded direction and signal count")
        if not Decimal(0) <= self.signal_accuracy <= Decimal(1):
            raise ValueError("Pivot screen accuracy must be a ratio")
        if not Decimal(0) <= self.positive_fold_ratio <= Decimal(1):
            raise ValueError("Pivot screen fold breadth must be a ratio")
        if self.signal_count == 0 and any(
            value != 0
            for value in (self.signal_accuracy, self.net_return, self.stressed_net_return, self.positive_fold_ratio)
        ):
            raise ValueError("empty Pivot screens cannot claim performance")

    def qualifies(
        self,
        *,
        minimum_signal_count: int,
        minimum_accuracy: Decimal,
        minimum_positive_fold_ratio: Decimal,
    ) -> bool:
        if minimum_signal_count < 1:
            raise ValueError("Pivot qualification requires a positive sample floor")
        return bool(
            self.cutoff_direction
            and self.signal_count >= minimum_signal_count
            and self.signal_accuracy >= minimum_accuracy
            and self.net_return > 0
            and self.stressed_net_return > 0
            and self.positive_fold_ratio >= minimum_positive_fold_ratio
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "family": self.family.value,
            "cutoff_direction": self.cutoff_direction,
            "signal_count": self.signal_count,
            "signal_accuracy": _text(self.signal_accuracy),
            "net_return": _text(self.net_return),
            "stressed_net_return": _text(self.stressed_net_return),
            "positive_fold_ratio": _text(self.positive_fold_ratio),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class PivotDeterministicCritique:
    accepted: bool
    high_severity_defects: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool or self.high_severity_defects != tuple(
            sorted(set(self.high_severity_defects))
        ):
            raise ValueError("Pivot critique requires canonical defect facts")
        if self.accepted == bool(self.high_severity_defects):
            raise ValueError("accepted Pivot critiques cannot contain high-severity defects")
        if canonical_sha256(self.payload()) != self.content_sha256:
            raise ValueError("Pivot critique digest must bind its payload")

    def payload(self) -> dict[str, JsonValue]:
        return {"accepted": self.accepted, "high_severity_defects": self.high_severity_defects}


def screen_hypothesis_families(
    records: tuple[PointInTimeRecord, ...],
    *,
    signal_threshold: Decimal,
    per_signal_cost: Decimal,
    folds: int = 3,
) -> tuple[HypothesisFamilyScreen, ...]:
    """Screen fixed families using only the supplied chronological PIT window."""

    if len(records) != 40 or any(type(record) is not PointInTimeRecord for record in records):
        raise ValueError("Pivot family screen requires exactly forty typed PIT bars")
    if tuple(sorted(records, key=lambda item: item.event_time.value)) != records:
        raise ValueError("Pivot family screen requires chronological records")
    instruments = {record.values.get("instrument_id") for record in records}
    if len(instruments) != 1 or None in instruments:
        raise PermissionError("Pivot family screen cannot cross instruments")
    if signal_threshold <= 0 or per_signal_cost < 0 or folds < 2:
        raise ValueError("Pivot family screen requires positive thresholds and multiple folds")
    _validate_fields(records)

    results = []
    for family in PIVOT_HYPOTHESIS_FAMILIES:
        observations = tuple(
            (index, signal)
            for index in range(len(records) - 1)
            for signal in (_family_signal(family, records, index, signal_threshold),)
            if signal
        )
        if observations:
            correct = sum(
                signal == _sign(_close(records[index + 1]) / _close(records[index]) - 1)
                for index, signal in observations
            )
            gross = sum(
                (
                    Decimal(signal) * (_close(records[index + 1]) / _close(records[index]) - 1)
                    for index, signal in observations
                ),
                Decimal(0),
            )
            count = len(observations)
            net = gross - per_signal_cost * count
            stressed = net - per_signal_cost * count
            accuracy = Decimal(correct) / count
            positive_fold_ratio = _positive_fold_ratio(records, observations, per_signal_cost, folds)
        else:
            count = 0
            accuracy = net = stressed = positive_fold_ratio = Decimal(0)
        results.append(
            HypothesisFamilyScreen(
                family,
                _family_signal(family, records, len(records) - 1, signal_threshold),
                count,
                accuracy,
                net,
                stressed,
                positive_fold_ratio,
            )
        )
    return tuple(results)


def strongest_deterministic_family(
    screens: tuple[HypothesisFamilyScreen, ...],
    *,
    minimum_signal_count: int,
    minimum_accuracy: Decimal,
    minimum_positive_fold_ratio: Decimal,
) -> HypothesisFamilyScreen | None:
    if tuple(screen.family for screen in screens) != PIVOT_HYPOTHESIS_FAMILIES:
        raise ValueError("deterministic Pivot baseline requires the complete frozen family roster")
    eligible = tuple(
        screen
        for screen in screens
        if screen.qualifies(
            minimum_signal_count=minimum_signal_count,
            minimum_accuracy=minimum_accuracy,
            minimum_positive_fold_ratio=minimum_positive_fold_ratio,
        )
    )
    return max(
        eligible, key=lambda item: (item.stressed_net_return, item.signal_accuracy, item.family.value), default=None
    )


def critique_pivot_conclusion(
    conclusion: ResearchConclusion,
    screens: tuple[HypothesisFamilyScreen, ...],
    *,
    feature_evidence_sha256: str,
    minimum_signal_count: int,
    minimum_accuracy: Decimal,
    minimum_positive_fold_ratio: Decimal,
) -> PivotDeterministicCritique:
    if type(conclusion) is not ResearchConclusion:
        raise TypeError("Pivot Critic requires an exact research conclusion")
    if tuple(screen.family for screen in screens) != PIVOT_HYPOTHESIS_FAMILIES:
        raise ValueError("Pivot Critic requires the complete frozen family roster")
    if len(feature_evidence_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in feature_evidence_sha256
    ):
        raise ValueError("Pivot Critic requires content-addressed feature evidence")
    defects: list[str] = []
    hypothesis = conclusion.hypothesis
    if hypothesis is None:
        defects.append("hypothesis_missing")
    elif conclusion.kind is ResearchConclusionKind.OPPORTUNITY_CANDIDATE:
        if hypothesis.family not in PIVOT_HYPOTHESIS_FAMILIES:
            defects.append("opportunity_without_registered_pivot_family")
        else:
            selected = next(screen for screen in screens if screen.family is hypothesis.family)
            if not selected.qualifies(
                minimum_signal_count=minimum_signal_count,
                minimum_accuracy=minimum_accuracy,
                minimum_positive_fold_ratio=minimum_positive_fold_ratio,
            ):
                defects.append("selected_family_failed_deterministic_evidence_floor")
        if not any(claim.evidence_sha256 == feature_evidence_sha256 for claim in conclusion.claims):
            defects.append("selected_family_feature_claim_missing")
        if feature_evidence_sha256 not in conclusion.counter_evidence_sha256s:
            defects.append("competing_family_counter_evidence_missing")
    canonical_defects = tuple(sorted(set(defects)))
    payload: dict[str, JsonValue] = {
        "accepted": not canonical_defects,
        "high_severity_defects": canonical_defects,
    }
    return PivotDeterministicCritique(not canonical_defects, canonical_defects, canonical_sha256(payload))


def family_screen_metrics(screens: tuple[HypothesisFamilyScreen, ...]) -> tuple[tuple[str, str], ...]:
    if tuple(screen.family for screen in screens) != PIVOT_HYPOTHESIS_FAMILIES:
        raise ValueError("Pivot metrics require the complete frozen family roster")
    values: list[tuple[str, str]] = []
    for screen in screens:
        prefix = screen.family.value.lower()
        values.extend(
            (
                (f"{prefix}.cutoff_direction", str(screen.cutoff_direction)),
                (f"{prefix}.cutoff_direction_unit", "sign"),
                (f"{prefix}.net_return", _text(screen.net_return)),
                (f"{prefix}.net_return_unit", "ratio"),
                (f"{prefix}.positive_fold_ratio", _text(screen.positive_fold_ratio)),
                (f"{prefix}.positive_fold_ratio_unit", "ratio"),
                (f"{prefix}.signal_accuracy", _text(screen.signal_accuracy)),
                (f"{prefix}.signal_accuracy_unit", "ratio"),
                (f"{prefix}.signal_count", str(screen.signal_count)),
                (f"{prefix}.signal_count_unit", "signals"),
                (f"{prefix}.stressed_net_return", _text(screen.stressed_net_return)),
                (f"{prefix}.stressed_net_return_unit", "ratio"),
            )
        )
    return tuple(sorted(values))


def _family_signal(
    family: HypothesisFamily,
    records: tuple[PointInTimeRecord, ...],
    index: int,
    threshold: Decimal,
) -> int:
    if index < 1:
        return 0
    return_signal = _sign(_close(records[index]) / _close(records[index - 1]) - 1, threshold)
    if family is HypothesisFamily.MOMENTUM_CONTINUATION:
        return return_signal
    if family is HypothesisFamily.MEAN_REVERSION:
        return -return_signal
    if index < 10:
        return 0
    prior = records[index - 10 : index]
    prior_high = max(_decimal(record, "high") for record in prior)
    prior_low = min(_decimal(record, "low") for record in prior)
    close = _close(records[index])
    if family is HypothesisFamily.BREAKOUT_CONTINUATION:
        return 1 if close > prior_high else -1 if close < prior_low else 0
    if family is HypothesisFamily.FALSE_BREAKOUT_REVERSAL:
        high = _decimal(records[index], "high")
        low = _decimal(records[index], "low")
        return -1 if high > prior_high and close <= prior_high else 1 if low < prior_low and close >= prior_low else 0
    if family is HypothesisFamily.PARTICIPATION_CONFIRMED_TREND:
        open_interest_rising = _integer(records[index], "open_interest") > _integer(records[index - 1], "open_interest")
        volume_expanded = _integer(records[index], "volume") > median(_integer(record, "volume") for record in prior)
        return return_signal if open_interest_rising and volume_expanded else 0
    if family is HypothesisFamily.VOLATILITY_COMPRESSION_BREAKOUT:
        if index < 20:
            return 0
        short_range = sum((_normalized_range(record) for record in records[index - 5 : index]), Decimal(0)) / 5
        long_range = sum((_normalized_range(record) for record in records[index - 20 : index]), Decimal(0)) / 20
        prior_closes = tuple(_close(record) for record in records[index - 5 : index])
        compressed = short_range <= long_range * Decimal("0.75")
        return 1 if compressed and close > max(prior_closes) else -1 if compressed and close < min(prior_closes) else 0
    raise ValueError("unknown Pivot hypothesis family")


def _positive_fold_ratio(
    records: tuple[PointInTimeRecord, ...],
    observations: tuple[tuple[int, int], ...],
    cost: Decimal,
    folds: int,
) -> Decimal:
    positive = 0
    populated = 0
    for fold in range(folds):
        start = (len(records) - 1) * fold // folds
        end = (len(records) - 1) * (fold + 1) // folds
        selected = tuple((index, signal) for index, signal in observations if start <= index < end)
        if not selected:
            continue
        populated += 1
        gross = sum(
            (Decimal(signal) * (_close(records[index + 1]) / _close(records[index]) - 1) for index, signal in selected),
            Decimal(0),
        )
        positive += gross - cost * len(selected) > 0
    return Decimal(positive) / populated if populated else Decimal(0)


def _validate_fields(records: tuple[PointInTimeRecord, ...]) -> None:
    for record in records:
        for field in ("open", "high", "low", "close", "volume", "open_interest"):
            _decimal(record, field)
        if not _decimal(record, "low") <= min(_decimal(record, "open"), _decimal(record, "close")):
            raise ValueError("Pivot OHLC records have an invalid low")
        if not _decimal(record, "high") >= max(_decimal(record, "open"), _decimal(record, "close")):
            raise ValueError("Pivot OHLC records have an invalid high")


def _normalized_range(record: PointInTimeRecord) -> Decimal:
    close = _close(record)
    return (_decimal(record, "high") - _decimal(record, "low")) / close if close else Decimal(0)


def _close(record: PointInTimeRecord) -> Decimal:
    return _decimal(record, "close")


def _integer(record: PointInTimeRecord, field: str) -> int:
    value = record.values.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"Pivot record requires non-negative integer {field}")
    return value


def _decimal(record: PointInTimeRecord, field: str) -> Decimal:
    value = record.values.get(field)
    try:
        decimal = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Pivot record requires numeric {field}") from error
    if not decimal.is_finite() or decimal < 0:
        raise ValueError(f"Pivot record requires finite non-negative {field}")
    return decimal


def _sign(value: Decimal, threshold: Decimal = Decimal(0)) -> int:
    return 1 if value > threshold else -1 if value < -threshold else 0


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001")), "f")


__all__ = [
    "PIVOT_HYPOTHESIS_FAMILIES",
    "HypothesisFamilyScreen",
    "PivotDeterministicCritique",
    "critique_pivot_conclusion",
    "family_screen_metrics",
    "screen_hypothesis_families",
    "strongest_deterministic_family",
]
