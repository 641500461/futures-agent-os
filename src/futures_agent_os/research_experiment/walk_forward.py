"""Single deterministic walk-forward fold planner shared by V1-010 tools and replay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.shared_kernel import canonical_json_text
from futures_agent_os.shared_kernel.observability import JsonValue

WALK_FORWARD_PLANNER_VERSION = "mvp-r.walk-forward-fold-planner.v1"
WALK_FORWARD_ACCURACY_SOURCE = "walk_forward_oos_test_window.v1"


@dataclass(frozen=True, slots=True)
class WalkForwardFoldWindow:
    fold_index: int
    train_start: int
    train_end: int
    embargo_start: int
    embargo_end: int
    test_start: int
    test_end: int

    def __post_init__(self) -> None:
        bounds = (
            self.fold_index,
            self.train_start,
            self.train_end,
            self.embargo_start,
            self.embargo_end,
            self.test_start,
            self.test_end,
        )
        if any(type(value) is not int for value in bounds):
            raise TypeError("walk-forward windows require exact integer indices")
        if self.fold_index < 1 or self.train_start < 0:
            raise ValueError("walk-forward window indices are invalid")
        if not (
            self.train_start
            < self.train_end
            == self.embargo_start
            < self.embargo_end
            == self.test_start
            < self.test_end
        ):
            raise ValueError("walk-forward train, embargo and test windows must be contiguous")

    @property
    def test_bars(self) -> int:
        return self.test_end - self.test_start


@dataclass(frozen=True, slots=True)
class OosFoldEvaluation:
    window: WalkForwardFoldWindow
    signal_count: int
    follow_accuracy: Decimal
    invert_accuracy: Decimal
    follow_net: Decimal
    invert_net: Decimal
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    config_sha256: str
    embargo_bars: int

    def manifest_entry(self) -> dict[str, JsonValue]:
        return {
            "fold_index": self.window.fold_index,
            "train_start_index": self.window.train_start,
            "train_end_index": self.window.train_end,
            "embargo_start_index": self.window.embargo_start,
            "embargo_end_index": self.window.embargo_end,
            "test_start_index": self.window.test_start,
            "test_end_index": self.window.test_end,
            "test_bars": self.window.test_bars,
            "signal_count": self.signal_count,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "embargo_bars": self.embargo_bars,
            "config_sha256": self.config_sha256,
            "planner_version": WALK_FORWARD_PLANNER_VERSION,
        }


def plan_walk_forward_fold_windows(
    sample_count: int,
    *,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    embargo_bars: int,
) -> tuple[WalkForwardFoldWindow, ...]:
    """Plan every OOS test window. Stop-after-failure is applied by the evaluator, not here."""

    bounds = (sample_count, train_bars, test_bars, step_bars, embargo_bars)
    if any(type(value) is not int or value < 1 for value in bounds[1:]) or type(sample_count) is not int:
        raise ValueError("walk-forward planner requires positive integer bounds")
    if sample_count < 0 or test_bars < 1 or step_bars < test_bars:
        raise ValueError("walk-forward planner requires non-overlapping chronological tests")
    windows: list[WalkForwardFoldWindow] = []
    cursor = train_bars + embargo_bars
    fold_index = 1
    while cursor + test_bars <= sample_count:
        train_end = cursor - embargo_bars
        train_start = train_end - train_bars
        if train_start < 0:
            raise ValueError("walk-forward train window underflow")
        windows.append(
            WalkForwardFoldWindow(
                fold_index=fold_index,
                train_start=train_start,
                train_end=train_end,
                embargo_start=train_end,
                embargo_end=cursor,
                test_start=cursor,
                test_end=cursor + test_bars,
            )
        )
        fold_index += 1
        cursor += step_bars
    return tuple(windows)


def equal_length_partition_counts(signal_count: int, *, folds: int) -> tuple[int, ...]:
    """The forbidden 12/13/13-style partition. Not an OOS walk-forward."""

    if folds < 2 or signal_count < 0:
        raise ValueError("equal-length partition requires a non-negative sample and at least two folds")
    return tuple(signal_count * (fold + 1) // folds - signal_count * fold // folds for fold in range(folds))


def evaluate_oos_folds(
    *,
    signals: tuple[int, ...],
    labels: tuple[int, ...],
    forward_returns: tuple[Decimal, ...],
    per_signal_cost: Decimal,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    embargo_bars: int,
    signal_times: tuple[str, ...],
    label_times: tuple[str, ...],
    config_sha256: str,
) -> tuple[OosFoldEvaluation, ...]:
    if len(signals) != len(labels) or len(signals) != len(forward_returns):
        raise ValueError("OOS fold evaluation requires aligned signals, labels and forward returns")
    if len(signal_times) != len(signals) or len(label_times) != len(signals):
        raise ValueError("OOS fold evaluation requires per-sample signal and label times")
    if type(per_signal_cost) is not Decimal or type(config_sha256) is not str or not config_sha256.strip():
        raise TypeError("OOS fold evaluation requires a Decimal cost and config digest")
    windows = plan_walk_forward_fold_windows(
        len(signals),
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        embargo_bars=embargo_bars,
    )
    evaluated: list[OosFoldEvaluation] = []
    for window in windows:
        test_indices = tuple(range(window.test_start, window.test_end))
        if len(test_indices) > test_bars:
            raise ValueError("OOS test window exceeded test_bars")
        signalled = tuple(index for index in test_indices if signals[index])
        if len(signalled) > test_bars:
            raise ValueError("OOS fold signal_count cannot exceed test_bars")
        follow_hits = sum(signals[index] == labels[index] for index in signalled)
        invert_hits = sum(-signals[index] == labels[index] for index in signalled)
        gross = sum((Decimal(signals[index]) * forward_returns[index] for index in signalled), Decimal(0))
        count = len(signalled)
        evaluated.append(
            OosFoldEvaluation(
                window=window,
                signal_count=count,
                follow_accuracy=_ratio(follow_hits, count),
                invert_accuracy=_ratio(invert_hits, count),
                follow_net=gross - per_signal_cost * count,
                invert_net=-gross - per_signal_cost * count,
                train_start=signal_times[window.train_start],
                train_end=label_times[window.train_end - 1],
                test_start=signal_times[window.test_start],
                test_end=label_times[window.test_end - 1],
                config_sha256=config_sha256,
                embargo_bars=embargo_bars,
            )
        )
    return tuple(evaluated)


def fold_manifest_json(folds: tuple[OosFoldEvaluation, ...]) -> str:
    return canonical_json_text(tuple(item.manifest_entry() for item in folds))


def _ratio(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)


__all__ = [
    "OosFoldEvaluation",
    "WALK_FORWARD_ACCURACY_SOURCE",
    "WALK_FORWARD_PLANNER_VERSION",
    "WalkForwardFoldWindow",
    "equal_length_partition_counts",
    "evaluate_oos_folds",
    "fold_manifest_json",
    "plan_walk_forward_fold_windows",
]
