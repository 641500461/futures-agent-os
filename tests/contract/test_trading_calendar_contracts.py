"""Contracts for immutable, point-in-time TradingDate attribution."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from futures_agent_os.reference_market_data import (
    CalendarClosure,
    CalendarReferenceEventKind,
    ClosureKind,
    Exchange,
    INITIAL_ACCEPTANCE_CALENDAR_SHA256,
    ReferenceProvenance,
    SessionPhase,
    SessionPhaseOccurrence,
    TradingCalendar,
    TradingDateService,
    TradingDaySchedule,
    TradingSessionOccurrence,
    Instrument,
    Variety,
    initial_acceptance_trading_calendar,
    trading_calendar_content_sha256,
)
from futures_agent_os.shared_kernel import EntityId, Failure, ReasonCode, RecordedAt, ShanghaiTimestamp, TradingDate


def market_time(text: str) -> ShanghaiTimestamp:
    return ShanghaiTimestamp.from_iso(text)


def observed(hour: int = 1) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 2, hour, tzinfo=UTC))


def scoped_variety(exchange: Exchange) -> Variety:
    return next(
        schedule.variety
        for schedule in initial_acceptance_trading_calendar().schedules
        if schedule.exchange is exchange
    )


def test_representative_night_day_auction_and_break_occurrences_resolve_for_all_four_exchanges() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())
    cases = (
        (Exchange.SHFE, "2026-08-24T21:00:00+08:00", SessionPhase.CONTINUOUS),
        (Exchange.DCE, "2026-08-24T21:00:00+08:00", SessionPhase.CONTINUOUS),
        (Exchange.CZCE, "2026-08-24T21:00:00+08:00", SessionPhase.CONTINUOUS),
        (Exchange.CFFEX, "2026-08-25T09:25:00+08:00", SessionPhase.CALL_AUCTION),
        (Exchange.SHFE, "2026-08-25T10:15:00+08:00", SessionPhase.BREAK),
    )

    for exchange, timestamp, expected_phase in cases:
        outcome = service.resolve(scoped_variety(exchange), market_time(timestamp), observed())
        assert not isinstance(outcome, Failure)
        assert outcome.trading_date == TradingDate.parse("2026-08-25")
        assert outcome.phase is expected_phase
        assert outcome.calendar_ref.content_sha256 == INITIAL_ACCEPTANCE_CALENDAR_SHA256


def test_cffex_is_an_explicit_exchange_namespace_with_four_digit_delivery_codes() -> None:
    contract = Instrument(Variety(Exchange.CFFEX, "IF", "synthetic index future"), "2609")
    assert contract.reference_id == "CFFEX.IF2609"
    with pytest.raises(ValueError, match="exchange-specific"):
        Instrument(contract.variety, "609")


def test_calendar_uses_explicit_occurrences_not_weekday_or_next_business_day_inference() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())

    friday = service.resolve(scoped_variety(Exchange.SHFE), market_time("2026-08-28T14:00:00+08:00"), observed())
    assert not isinstance(friday, Failure)
    assert friday.trading_date == TradingDate.parse("2026-08-28")

    # Saturday has neither an explicit session nor a closure fact: the service
    # must fail closed rather than derive a following Monday trading date.
    assert service.resolve(
        scoped_variety(Exchange.SHFE), market_time("2026-08-29T14:00:00+08:00"), observed()
    ) == Failure(ReasonCode.CALENDAR_MISSING, "no explicit calendar fact applies to market_time")


def test_exact_variety_scope_never_implies_another_same_exchange_contract_is_open() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())
    unscheduled_copper = Variety(Exchange.SHFE, "CU", "synthetic copper")

    assert service.resolve(unscheduled_copper, market_time("2026-08-24T21:00:00+08:00"), observed()) == Failure(
        ReasonCode.CALENDAR_MISSING, "no explicit calendar fact applies to market_time"
    )
    assert service.resolve(unscheduled_copper, market_time("2026-10-01T10:00:00+08:00"), observed()) == Failure(
        ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure"
    )


def test_holiday_special_closure_and_temporary_early_close_are_explicit_facts() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())

    assert service.resolve(
        scoped_variety(Exchange.SHFE), market_time("2026-10-01T10:00:00+08:00"), observed()
    ) == Failure(ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure")
    assert service.resolve(
        scoped_variety(Exchange.DCE), market_time("2026-08-27T10:00:00+08:00"), observed()
    ) == Failure(ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure")

    before_close = service.resolve(scoped_variety(Exchange.DCE), market_time("2026-08-25T22:29:59+08:00"), observed())
    assert not isinstance(before_close, Failure)
    assert before_close.trading_date == TradingDate.parse("2026-08-26")
    assert before_close.schedule.adjustment_ref == "calendar-adjustment://synthetic/dce/2026-08-26/early-close"
    assert service.resolve(
        scoped_variety(Exchange.DCE), market_time("2026-08-25T22:30:00+08:00"), observed()
    ) == Failure(ReasonCode.CALENDAR_CLOSED, "market_time is outside explicit exchange session phases")


def test_reference_events_link_but_do_not_duplicate_main_switch_delivery_or_rule_owners() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())

    dce_events = service.events_for(Exchange.DCE, TradingDate.parse("2026-08-26"), observed())
    assert not isinstance(dce_events, Failure)
    assert [(event.kind, event.reference_ref) for event in dce_events] == [
        (CalendarReferenceEventKind.DOMINANT_CONTRACT_SWITCH, "dominant-contract-reference://DCE.I/2026-08-26/v1")
    ]
    shfe_events = service.events_for(Exchange.SHFE, TradingDate.parse("2026-08-28"), observed())
    assert not isinstance(shfe_events, Failure)
    assert shfe_events[0].kind is CalendarReferenceEventKind.NEAR_DELIVERY_WINDOW
    assert not hasattr(shfe_events[0], "instrument")
    assert not hasattr(shfe_events[0], "fees")
    assert not hasattr(shfe_events[0], "margin")


def test_pit_visibility_and_half_open_boundaries_fail_closed_without_latest_wins() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())

    assert service.resolve(
        scoped_variety(Exchange.SHFE),
        market_time("2026-08-24T21:00:00+08:00"),
        RecordedAt.parse("2026-07-31T23:59:59Z"),
    ) == Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar session was not acquired at as_of")
    assert service.events_for(
        Exchange.DCE, TradingDate.parse("2026-08-26"), RecordedAt.parse("2026-07-31T23:59:59Z")
    ) == Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar reference event was not acquired at as_of")
    assert service.resolve(
        scoped_variety(Exchange.SHFE), market_time("2026-08-25T02:30:00+08:00"), observed()
    ) == Failure(ReasonCode.CALENDAR_CLOSED, "market_time is outside explicit exchange session phases")


def test_calendar_release_is_immutable_versioned_order_independent_and_oracle_locked() -> None:
    calendar = initial_acceptance_trading_calendar()
    assert calendar.expected_content_sha256 == INITIAL_ACCEPTANCE_CALENDAR_SHA256
    assert calendar.ref.calendar_id == calendar.calendar_id
    assert calendar.ref.release_version == 1
    assert (
        trading_calendar_content_sha256(
            calendar.schedules[::-1], calendar.closures[::-1], calendar.reference_events[::-1]
        )
        == calendar.expected_content_sha256
    )
    with pytest.raises(FrozenInstanceError):
        calendar.release_version = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="expected_content_sha256"):
        replace(calendar, schedules=calendar.schedules[:-1])


def test_market_time_must_use_asia_shanghai_iana_zone_and_inputs_are_typed() -> None:
    service = TradingDateService(initial_acceptance_trading_calendar())
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        ShanghaiTimestamp(datetime(2026, 8, 25, 9, tzinfo=UTC))
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        ShanghaiTimestamp(datetime(2026, 8, 25, 9, tzinfo=timezone(timedelta(hours=8))))
    with pytest.raises(ValueError, match="timezone-aware"):
        ShanghaiTimestamp.from_iso("2026-08-25T09:00:00")
    with pytest.raises(TypeError, match="exact Variety"):
        service.resolve(Exchange.SHFE, datetime(2026, 8, 25, 9, tzinfo=UTC), observed())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Asia/Shanghai"):
        service.resolve(scoped_variety(Exchange.SHFE), datetime(2026, 8, 25, 9, tzinfo=UTC), observed())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RecordedAt"):
        service.resolve(scoped_variety(Exchange.SHFE), market_time("2026-08-25T09:00:00+08:00"), datetime.now(UTC))  # type: ignore[arg-type]


def _revision(number: int) -> EntityId:
    return EntityId.parse(f"trading_calendar_revision_018f9b16-9a00-7abe-8000-{number:012d}")


def _custom_schedule(
    exchange: Exchange,
    starts: str,
    ends: str,
    *,
    version: int = 1,
    revision: int = 50,
    acquired_at: RecordedAt | None = None,
    supersedes: tuple[EntityId, ...] = (),
) -> TradingDaySchedule:
    recorded = acquired_at or RecordedAt.parse("2026-08-01T00:00:00Z")
    provenance = ReferenceProvenance("test://calendar", recorded, recorded, "v1")
    return TradingDaySchedule(
        exchange,
        Variety(exchange, "AG" if exchange is Exchange.SHFE else "I", "test variety"),
        TradingDate.parse("2026-08-25"),
        (
            TradingSessionOccurrence(
                "TEST",
                (SessionPhaseOccurrence(SessionPhase.CONTINUOUS, market_time(starts), market_time(ends)),),
            ),
        ),
        market_time("2026-08-01T08:00:00+08:00"),
        version,
        provenance,
        _revision(revision),
        supersedes=supersedes,
    )


def test_overlap_and_closure_conflicts_are_rejected_at_release_construction() -> None:
    first = _custom_schedule(Exchange.SHFE, "2026-08-25T09:00:00+08:00", "2026-08-25T10:00:00+08:00")
    second = _custom_schedule(
        Exchange.SHFE, "2026-08-25T09:30:00+08:00", "2026-08-25T10:30:00+08:00", version=2, revision=51
    )
    with pytest.raises(ValueError, match="overlapping"):
        TradingCalendar(
            EntityId.new("trading_calendar"),
            1,
            (first, second),
            (),
            (),
            trading_calendar_content_sha256((first, second), (), ()),
        )
    closure = CalendarClosure(
        Exchange.SHFE,
        date(2026, 8, 25),
        ClosureKind.SPECIAL_CLOSURE,
        market_time("2026-08-01T08:00:00+08:00"),
        1,
        first.provenance,
        _revision(52),
    )
    with pytest.raises(ValueError, match="requires explicit supersession"):
        TradingCalendar(
            EntityId.new("trading_calendar"),
            1,
            (first,),
            (closure,),
            (),
            trading_calendar_content_sha256((first,), (closure,), ()),
        )


def test_explicit_pit_revision_chain_replays_open_then_closed_then_reopened_without_list_order() -> None:
    first = _custom_schedule(Exchange.SHFE, "2026-08-25T09:00:00+08:00", "2026-08-25T10:00:00+08:00", revision=60)
    closure_provenance = ReferenceProvenance(
        "test://calendar",
        RecordedAt.parse("2026-08-20T00:00:00Z"),
        RecordedAt.parse("2026-08-20T00:00:00Z"),
        "v2",
    )
    closure = CalendarClosure(
        Exchange.SHFE,
        date(2026, 8, 25),
        ClosureKind.SPECIAL_CLOSURE,
        market_time("2026-08-20T08:00:00+08:00"),
        2,
        closure_provenance,
        _revision(61),
        (first.revision_id,),
    )
    reopen_provenance = ReferenceProvenance(
        "test://calendar",
        RecordedAt.parse("2026-08-30T00:00:00Z"),
        RecordedAt.parse("2026-08-30T00:00:00Z"),
        "v3",
    )
    reopened = TradingDaySchedule(
        first.exchange,
        first.variety,
        first.trading_date,
        first.sessions,
        market_time("2026-08-30T08:00:00+08:00"),
        3,
        reopen_provenance,
        _revision(62),
        supersedes=(first.revision_id, closure.revision_id),
    )
    calendar = TradingCalendar(
        EntityId.new("trading_calendar"),
        1,
        (reopened, first),
        (closure,),
        (),
        trading_calendar_content_sha256((reopened, first), (closure,), ()),
    )
    service = TradingDateService(calendar)
    query_time = market_time("2026-08-25T09:30:00+08:00")

    old = service.resolve(first.variety, query_time, RecordedAt.parse("2026-08-10T00:00:00Z"))
    assert not isinstance(old, Failure)
    assert old.schedule.revision_id == first.revision_id
    assert service.resolve(first.variety, query_time, RecordedAt.parse("2026-08-21T00:00:00Z")) == Failure(
        ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure"
    )
    latest = service.resolve(first.variety, query_time, RecordedAt.parse("2026-08-31T00:00:00Z"))
    assert not isinstance(latest, Failure)
    assert latest.schedule.revision_id == reopened.revision_id


def test_schedule_supersession_requires_the_same_touching_trading_date_scope() -> None:
    first = _custom_schedule(Exchange.SHFE, "2026-08-25T09:00:00+08:00", "2026-08-25T10:00:00+08:00", revision=65)
    unrelated = _custom_schedule(
        Exchange.SHFE,
        "2026-08-25T11:00:00+08:00",
        "2026-08-25T12:00:00+08:00",
        version=2,
        revision=66,
        acquired_at=RecordedAt.parse("2026-08-20T00:00:00Z"),
        supersedes=(first.revision_id,),
    )
    with pytest.raises(ValueError, match="touching TradingDate scope"):
        TradingCalendar(
            EntityId.new("trading_calendar"),
            1,
            (first, unrelated),
            (),
            (),
            trading_calendar_content_sha256((first, unrelated), (), ()),
        )
    cross_date_closure = CalendarClosure(
        Exchange.SHFE,
        date(2026, 8, 26),
        ClosureKind.SPECIAL_CLOSURE,
        market_time("2026-08-20T08:00:00+08:00"),
        2,
        ReferenceProvenance(
            "test://calendar", RecordedAt.parse("2026-08-20T00:00:00Z"), RecordedAt.parse("2026-08-20T00:00:00Z"), "v2"
        ),
        _revision(67),
        (first.revision_id,),
    )
    with pytest.raises(ValueError, match="share an affected calendar date"):
        TradingCalendar(
            EntityId.new("trading_calendar"),
            1,
            (first,),
            (cross_date_closure,),
            (),
            trading_calendar_content_sha256((first,), (cross_date_closure,), ()),
        )


def test_future_shortened_or_extended_schedule_correction_cannot_leak_into_prior_as_of() -> None:
    def replay(end_v1: str, end_v2: str, query: str, expected_after_correction_open: bool) -> None:
        first = _custom_schedule(Exchange.SHFE, "2026-08-25T09:00:00+08:00", end_v1, revision=70)
        corrected = _custom_schedule(
            Exchange.SHFE,
            "2026-08-25T09:00:00+08:00",
            end_v2,
            version=2,
            revision=71,
            acquired_at=RecordedAt.parse("2026-08-20T00:00:00Z"),
            supersedes=(first.revision_id,),
        )
        calendar = TradingCalendar(
            EntityId.new("trading_calendar"),
            1,
            (corrected, first),
            (),
            (),
            trading_calendar_content_sha256((corrected, first), (), ()),
        )
        service = TradingDateService(calendar)
        query_time = market_time(query)

        before = service.resolve(first.variety, query_time, RecordedAt.parse("2026-08-10T00:00:00Z"))
        assert (not isinstance(before, Failure)) is (query < end_v1)
        after = service.resolve(first.variety, query_time, RecordedAt.parse("2026-08-21T00:00:00Z"))
        assert (not isinstance(after, Failure)) is expected_after_correction_open

    # A later shortened schedule must not render 14:30 invisible before the
    # correction existed; a later extension must not make 15:30 visible early.
    replay("2026-08-25T15:00:00+08:00", "2026-08-25T14:00:00+08:00", "2026-08-25T14:30:00+08:00", False)
    replay("2026-08-25T14:00:00+08:00", "2026-08-25T16:00:00+08:00", "2026-08-25T15:30:00+08:00", True)


def test_supersedes_is_copied_from_caller_owned_list_before_hash_or_resolution() -> None:
    first = _custom_schedule(Exchange.SHFE, "2026-08-25T09:00:00+08:00", "2026-08-25T10:00:00+08:00", revision=80)
    caller_owned = [first.revision_id]
    successor = TradingDaySchedule(
        first.exchange,
        first.variety,
        first.trading_date,
        first.sessions,
        market_time("2026-08-20T08:00:00+08:00"),
        2,
        ReferenceProvenance(
            "test://calendar", RecordedAt.parse("2026-08-20T00:00:00Z"), RecordedAt.parse("2026-08-20T00:00:00Z"), "v2"
        ),
        _revision(81),
        supersedes=caller_owned,  # type: ignore[arg-type]
    )
    content_before = trading_calendar_content_sha256((first, successor), (), ())
    calendar = TradingCalendar(EntityId.new("trading_calendar"), 1, (first, successor), (), (), content_before)
    caller_owned.clear()
    assert successor.supersedes == (first.revision_id,)
    assert trading_calendar_content_sha256((first, successor), (), ()) == content_before
    outcome = TradingDateService(calendar).resolve(
        first.variety, market_time("2026-08-25T09:30:00+08:00"), RecordedAt.parse("2026-08-21T00:00:00Z")
    )
    assert not isinstance(outcome, Failure)
    assert outcome.schedule.revision_id == successor.revision_id

    closure_predecessors = [first.revision_id]
    closure = CalendarClosure(
        Exchange.SHFE,
        date(2026, 8, 25),
        ClosureKind.SPECIAL_CLOSURE,
        market_time("2026-08-20T08:00:00+08:00"),
        2,
        ReferenceProvenance(
            "test://calendar", RecordedAt.parse("2026-08-20T00:00:00Z"), RecordedAt.parse("2026-08-20T00:00:00Z"), "v2"
        ),
        _revision(82),
        closure_predecessors,  # type: ignore[arg-type]
    )
    closure_content = trading_calendar_content_sha256((first,), (closure,), ())
    closure_calendar = TradingCalendar(EntityId.new("trading_calendar"), 1, (first,), (closure,), (), closure_content)
    closure_predecessors.clear()
    assert closure.supersedes == (first.revision_id,)
    assert trading_calendar_content_sha256((first,), (closure,), ()) == closure_content
    assert TradingDateService(closure_calendar).resolve(
        first.variety, market_time("2026-08-25T09:30:00+08:00"), RecordedAt.parse("2026-08-21T00:00:00Z")
    ) == Failure(ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure")


def test_calendar_values_and_parallel_resolution_are_immutable() -> None:
    calendar = initial_acceptance_trading_calendar()
    for value in calendar.schedules + calendar.closures + calendar.reference_events:
        for field in fields(value):
            with pytest.raises((FrozenInstanceError, AttributeError)):
                setattr(value, field.name, getattr(value, field.name))
    service = TradingDateService(calendar)
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(
            executor.map(
                lambda _: service.resolve(
                    scoped_variety(Exchange.SHFE), market_time("2026-08-24T21:00:00+08:00"), observed()
                ),
                range(32),
            )
        )
    assert len(set(outcomes)) == 1
