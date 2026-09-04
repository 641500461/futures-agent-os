"""Build a numeric PIT evidence bundle shared by Research and Critic."""

from __future__ import annotations

from decimal import Decimal

from futures_agent_os.reference_market_data import PointInTimeRecord

from .contracts import PitBarFact, ResearchEvidenceBundle


def build_research_evidence_bundle(
    *,
    episode_id: str,
    instrument: str,
    market_cutoff: str,
    as_of: str,
    market_state: str,
    records: tuple[PointInTimeRecord, ...],
) -> ResearchEvidenceBundle:
    if not records:
        raise ValueError("evidence bundle requires PIT-visible bars")
    bars: list[PitBarFact] = []
    closes: list[Decimal] = []
    previous_close: Decimal | None = None
    previous_component: str | None = None
    rolls = 0
    for record in records:
        close = _decimal(record.values.get("close"), "close")
        component = _text_value(record.values.get("component_instrument"), "component instrument")
        if previous_component is not None and component != previous_component:
            rolls += 1
        previous_component = component
        prior = None if previous_close is None else format(close / previous_close - 1, "f")
        previous_close = close
        closes.append(close)
        bars.append(
            PitBarFact(
                record.event_time.to_dict()["recorded_at"],
                record.available_time.to_dict()["recorded_at"],
                format(close, "f"),
                prior,
                str(record.values.get("volume", "0")),
                str(record.values.get("open_interest", "0")),
                component,
            )
        )
    abs_returns = tuple(abs(closes[index] / closes[index - 1] - 1) for index in range(1, len(closes)))
    summary = (
        ("bar_count", str(len(bars))),
        ("last_close", format(closes[-1], "f")),
        ("return_5", format(closes[-1] / closes[-6] - 1, "f") if len(closes) >= 6 else "0"),
        ("return_20", format(closes[-1] / closes[-21] - 1, "f") if len(closes) >= 21 else "0"),
        (
            "mean_abs_return_20",
            format(sum(abs_returns[-20:]) / Decimal(min(20, len(abs_returns))), "f") if abs_returns else "0",
        ),
        ("unadjusted_roll_count", str(rolls)),
    )
    return ResearchEvidenceBundle(
        episode_id=episode_id,
        instrument=instrument,
        market_cutoff=market_cutoff,
        as_of=as_of,
        market_state=market_state,
        bars=tuple(bars),
        summary=summary,
        future_bars_included=False,
    )


def _decimal(value: object, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required")
    return Decimal(str(value))


def _text_value(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} requires non-empty text")
    return value
