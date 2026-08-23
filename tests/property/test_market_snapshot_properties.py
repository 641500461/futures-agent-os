"""Property checks for point-in-time observation time and value boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, strategies as st

from futures_agent_os.reference_market_data import (
    Exchange,
    Instrument,
    MarketObservation,
    ObservationKind,
    ReferenceProvenance,
    SourceTrust,
    Variety,
    select_active_observations,
)
from futures_agent_os.shared_kernel import EntityId, Price, RecordedAt, SchemaVersion


def _at(minutes: int) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 25, 1, tzinfo=UTC) + timedelta(minutes=minutes))


def _instrument() -> Instrument:
    return Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2606")


@given(available_delay=st.integers(min_value=0, max_value=120), ingestion_delay=st.integers(min_value=0, max_value=120))
def test_observation_preserves_every_valid_pit_time_chain(available_delay: int, ingestion_delay: int) -> None:
    event = _at(0)
    available = _at(available_delay)
    ingested = _at(available_delay + ingestion_delay)
    observation = MarketObservation(
        EntityId.new("market_observation"),
        _instrument(),
        ObservationKind.TRADE,
        event,
        available,
        ingested,
        ReferenceProvenance("dataset://property", event, event, "v1"),
        SourceTrust.PRIMARY,
        SchemaVersion(1, 0),
        1,
        last_price=Price("6000.0", "CNY", "CNY/tonne", 1),
    )

    assert observation.event_time.value <= observation.available_time.value <= observation.ingested_at.value


@given(available_delay=st.integers(min_value=1, max_value=120))
def test_observation_rejects_availability_before_its_event(available_delay: int) -> None:
    with pytest.raises(ValueError, match="event_time <= available_time <= ingested_at"):
        MarketObservation(
            EntityId.new("market_observation"),
            _instrument(),
            ObservationKind.TRADE,
            _at(available_delay),
            _at(0),
            _at(available_delay),
            ReferenceProvenance("dataset://property", _at(0), _at(0), "v1"),
            SourceTrust.PRIMARY,
            SchemaVersion(1, 0),
            1,
            last_price=Price("6000.0", "CNY", "CNY/tonne", 1),
        )


@given(first_visible=st.integers(min_value=1, max_value=60), correction_delay=st.integers(min_value=1, max_value=60))
def test_revision_leaf_selection_is_pit_stable_and_independent_of_history_order(
    first_visible: int, correction_delay: int
) -> None:
    original = MarketObservation(
        EntityId.new("market_observation"),
        _instrument(),
        ObservationKind.TRADE,
        _at(0),
        _at(first_visible),
        _at(first_visible),
        ReferenceProvenance("dataset://property", _at(0), _at(0), "v1"),
        SourceTrust.PRIMARY,
        SchemaVersion(1, 0),
        1,
        last_price=Price("6000.0", "CNY", "CNY/tonne", 1),
    )
    correction_visible = first_visible + correction_delay
    correction = replace(
        original,
        observation_id=EntityId.new("market_observation"),
        available_time=_at(correction_visible),
        ingested_at=_at(correction_visible),
        last_price=Price("6100.0", "CNY", "CNY/tonne", 1),
        revision=2,
        supersedes_observation_id=original.observation_id,
    )

    assert select_active_observations((original, correction), _at(first_visible)) == (original,)
    assert select_active_observations((correction, original), _at(correction_visible)) == (correction,)
