"""Immutable, point-in-time exchange calendar truth.

The calendar owns only the attribution of an *explicit session occurrence* to
an exchange TradingDate.  It deliberately does not infer next business days,
weekday rules, dominant contracts, delivery restrictions, or contract rules.
Those facts remain in their respective reference owners and may only be linked
here by an immutable dated reference event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TypeAlias, cast
from zoneinfo import ZoneInfo

from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    ReasonCode,
    RecordedAt,
    ShanghaiTimestamp,
    TradingDate,
    canonical_sha256,
)
from futures_agent_os.shared_kernel.observability import JsonValue

from .instrument_registry import Exchange, ReferenceProvenance, Variety


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RELEASED_AT = RecordedAt.parse("2026-08-01T00:00:00Z")
INITIAL_ACCEPTANCE_CALENDAR_ID = EntityId.parse("trading_calendar_018f9b16-9a00-7abe-8000-000000000017")
INITIAL_ACCEPTANCE_CALENDAR_RELEASE_VERSION = 1
# Fixed independently reviewable release oracle, never calculated by callers.
INITIAL_ACCEPTANCE_CALENDAR_SHA256 = "".join(
    (
        "0bb43a8d",
        "e85a6262",
        "c1e1149e",
        "fdffac91",
        "ab99fbc5",
        "c07b2cf6",
        "d49350df",
        "c7d02e66",
    )
)


class SessionPhase(StrEnum):
    """A market phase that is explicitly represented by a calendar occurrence."""

    CALL_AUCTION = "CALL_AUCTION"
    CONTINUOUS = "CONTINUOUS"
    BREAK = "BREAK"


class ClosureKind(StrEnum):
    HOLIDAY = "HOLIDAY"
    SPECIAL_CLOSURE = "SPECIAL_CLOSURE"


class CalendarReferenceEventKind(StrEnum):
    """Dated pointers to facts owned by other reference services."""

    DOMINANT_CONTRACT_SWITCH = "DOMINANT_CONTRACT_SWITCH"
    NEAR_DELIVERY_WINDOW = "NEAR_DELIVERY_WINDOW"
    CONTRACT_RULE_ADJUSTMENT = "CONTRACT_RULE_ADJUSTMENT"


def _require_version(value: int, field: str = "version") -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _require_reference(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-whitespace text")


def _require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _normalized_supersedes(revision_id: EntityId, supersedes: object) -> tuple[EntityId, ...]:
    if not isinstance(revision_id, EntityId) or revision_id.namespace != "trading_calendar_revision":
        raise ValueError("calendar fact requires a trading_calendar_revision id")
    try:
        predecessors: tuple[object, ...] = tuple(supersedes)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError("calendar supersedes requires an iterable of revision ids") from error
    if any(
        not isinstance(predecessor, EntityId) or predecessor.namespace != "trading_calendar_revision"
        for predecessor in predecessors
    ):
        raise ValueError("calendar supersedes requires trading_calendar_revision ids")
    if revision_id in predecessors or len(set(predecessors)) != len(predecessors):
        raise ValueError("calendar supersedes must be unique and cannot include its own revision")
    return cast("tuple[EntityId, ...]", predecessors)


@dataclass(frozen=True, slots=True)
class SessionPhaseOccurrence:
    """One half-open Asia/Shanghai phase occurrence, never a recurring template."""

    phase: SessionPhase
    starts_at: ShanghaiTimestamp
    ends_at: ShanghaiTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.phase, SessionPhase):
            raise TypeError("session phase occurrence requires a SessionPhase")
        if not isinstance(self.starts_at, ShanghaiTimestamp) or not isinstance(self.ends_at, ShanghaiTimestamp):
            raise TypeError("session phase occurrence requires Asia/Shanghai timestamps")
        if self.ends_at.value <= self.starts_at.value:
            raise ValueError("session phase occurrence must be non-empty")

    def contains(self, market_time: ShanghaiTimestamp) -> bool:
        if not isinstance(market_time, ShanghaiTimestamp):
            raise TypeError("session phase occurrence requires an Asia/Shanghai market_time")
        return self.starts_at.value <= market_time.value < self.ends_at.value

    def touches_calendar_date(self, calendar_date: date) -> bool:
        if isinstance(calendar_date, datetime) or not isinstance(calendar_date, date):
            raise TypeError("calendar_date must be a date")
        # This examines only the explicit timestamp interval; it never derives
        # a TradingDate from the natural date.
        start_date = self.starts_at.value.date()
        end_date = (self.ends_at.value - datetime.resolution).date()
        return start_date <= calendar_date <= end_date


@dataclass(frozen=True, slots=True)
class TradingSessionOccurrence:
    """Named collection of ordered phase occurrences within one TradingDate."""

    name: str
    phases: tuple[SessionPhaseOccurrence, ...]

    def __post_init__(self) -> None:
        _require_reference(self.name, "trading session name")
        phases = tuple(self.phases)
        if not phases or any(not isinstance(phase, SessionPhaseOccurrence) for phase in phases):
            raise TypeError("trading session occurrence requires non-empty SessionPhaseOccurrence values")
        ordered = tuple(sorted(phases, key=lambda phase: phase.starts_at.value))
        if ordered != phases:
            raise ValueError("trading session phase occurrences must be chronologically ordered")
        if any(right.starts_at.value < left.ends_at.value for left, right in zip(phases, phases[1:])):
            raise ValueError("trading session phase occurrences cannot overlap")
        object.__setattr__(self, "phases", phases)


@dataclass(frozen=True, slots=True)
class TradingDaySchedule:
    """Explicit session occurrences attributed to exactly one TradingDate."""

    exchange: Exchange
    variety: Variety
    trading_date: TradingDate
    sessions: tuple[TradingSessionOccurrence, ...]
    event_time: ShanghaiTimestamp
    version: int
    provenance: ReferenceProvenance
    revision_id: EntityId
    adjustment_ref: str | None = None
    supersedes: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.exchange, Exchange)
            or not isinstance(self.variety, Variety)
            or not isinstance(self.trading_date, TradingDate)
        ):
            raise TypeError("trading day schedule requires an Exchange, Variety, and TradingDate")
        if self.variety.exchange is not self.exchange:
            raise ValueError("trading day schedule exchange must match exact Variety scope")
        sessions = tuple(self.sessions)
        if not sessions or any(not isinstance(session, TradingSessionOccurrence) for session in sessions):
            raise TypeError("trading day schedule requires non-empty TradingSessionOccurrence values")
        if len({session.name for session in sessions}) != len(sessions):
            raise ValueError("trading day schedule session names must be unique")
        if not isinstance(self.event_time, ShanghaiTimestamp) or not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("trading day schedule requires event_time and provenance")
        supersedes = _normalized_supersedes(self.revision_id, self.supersedes)
        _require_version(self.version)
        if self.adjustment_ref is not None:
            _require_reference(self.adjustment_ref, "adjustment_ref")
        phases = tuple(phase for session in sessions for phase in session.phases)
        ordered = tuple(sorted(phases, key=lambda phase: phase.starts_at.value))
        if any(right.starts_at.value < left.ends_at.value for left, right in zip(ordered, ordered[1:])):
            raise ValueError("trading day schedule phases cannot overlap")
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "supersedes", supersedes)

    def matching_phase(self, market_time: ShanghaiTimestamp) -> tuple[str, SessionPhaseOccurrence] | None:
        for session in self.sessions:
            for phase in session.phases:
                if phase.contains(market_time):
                    return session.name, phase
        return None

    def touches_calendar_date(self, calendar_date: date) -> bool:
        return any(phase.touches_calendar_date(calendar_date) for session in self.sessions for phase in session.phases)


@dataclass(frozen=True, slots=True)
class CalendarClosure:
    """An explicit full-calendar-date holiday or temporary exchange closure."""

    exchange: Exchange
    calendar_date: date
    kind: ClosureKind
    event_time: ShanghaiTimestamp
    version: int
    provenance: ReferenceProvenance
    revision_id: EntityId
    supersedes: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange) or not isinstance(self.kind, ClosureKind):
            raise TypeError("calendar closure requires an Exchange and ClosureKind")
        if isinstance(self.calendar_date, datetime) or not isinstance(self.calendar_date, date):
            raise TypeError("calendar closure requires a calendar date")
        if not isinstance(self.event_time, ShanghaiTimestamp) or not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("calendar closure requires event_time and provenance")
        supersedes = _normalized_supersedes(self.revision_id, self.supersedes)
        _require_version(self.version)
        object.__setattr__(self, "supersedes", supersedes)

    def applies_to(self, market_time: ShanghaiTimestamp) -> bool:
        if not isinstance(market_time, ShanghaiTimestamp):
            raise TypeError("calendar closure requires an Asia/Shanghai market_time")
        return market_time.value.date() == self.calendar_date


@dataclass(frozen=True, slots=True)
class CalendarReferenceEvent:
    """A dated immutable pointer, with no attempt to interpret another owner's fact."""

    exchange: Exchange
    trading_date: TradingDate
    kind: CalendarReferenceEventKind
    reference_ref: str
    event_time: ShanghaiTimestamp
    version: int
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange) or not isinstance(self.trading_date, TradingDate):
            raise TypeError("calendar reference event requires an Exchange and TradingDate")
        if not isinstance(self.kind, CalendarReferenceEventKind):
            raise TypeError("calendar reference event requires a CalendarReferenceEventKind")
        _require_reference(self.reference_ref, "reference_ref")
        if not isinstance(self.event_time, ShanghaiTimestamp) or not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("calendar reference event requires event_time and provenance")
        _require_version(self.version)


@dataclass(frozen=True, slots=True)
class TradingCalendarRef:
    """Immutable release identity required to replay a TradingDate attribution."""

    calendar_id: EntityId
    release_version: int
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_id, EntityId) or self.calendar_id.namespace != "trading_calendar":
            raise ValueError("trading calendar ref requires a trading_calendar id")
        _require_version(self.release_version, "release_version")
        _require_digest(self.content_sha256, "content_sha256")


@dataclass(frozen=True, slots=True)
class TradingDateResolution:
    """A single visible calendar attribution with phase and release evidence."""

    exchange: Exchange
    trading_date: TradingDate
    market_time: ShanghaiTimestamp
    as_of: RecordedAt
    session_name: str
    phase: SessionPhase
    schedule: TradingDaySchedule
    calendar_ref: TradingCalendarRef


TradingDateOutcome: TypeAlias = TradingDateResolution | Failure
CalendarEventsOutcome: TypeAlias = tuple[CalendarReferenceEvent, ...] | Failure


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """An immutable release of explicit exchange calendar facts."""

    calendar_id: EntityId
    release_version: int
    schedules: tuple[TradingDaySchedule, ...]
    closures: tuple[CalendarClosure, ...]
    reference_events: tuple[CalendarReferenceEvent, ...]
    expected_content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_id, EntityId) or self.calendar_id.namespace != "trading_calendar":
            raise ValueError("trading calendar requires a trading_calendar id")
        _require_version(self.release_version, "release_version")
        schedules, closures, events = tuple(self.schedules), tuple(self.closures), tuple(self.reference_events)
        if not schedules:
            raise ValueError("trading calendar requires explicit trading day schedules")
        if any(not isinstance(schedule, TradingDaySchedule) for schedule in schedules):
            raise TypeError("trading calendar schedules must be TradingDaySchedule values")
        if any(not isinstance(closure, CalendarClosure) for closure in closures):
            raise TypeError("trading calendar closures must be CalendarClosure values")
        if any(not isinstance(event, CalendarReferenceEvent) for event in events):
            raise TypeError("trading calendar reference_events must be CalendarReferenceEvent values")
        _reject_overlaps(schedules, closures, events)
        actual = trading_calendar_content_sha256(schedules, closures, events)
        if self.expected_content_sha256 != actual:
            raise ValueError("trading calendar expected_content_sha256 does not match contents")
        object.__setattr__(self, "schedules", schedules)
        object.__setattr__(self, "closures", closures)
        object.__setattr__(self, "reference_events", events)

    @property
    def ref(self) -> TradingCalendarRef:
        return TradingCalendarRef(self.calendar_id, self.release_version, self.expected_content_sha256)


@dataclass(frozen=True, slots=True)
class TradingDateService:
    """Fail-closed point-in-time resolver; the sole owner of TradingDate attribution."""

    calendar: TradingCalendar

    def __post_init__(self) -> None:
        if not isinstance(self.calendar, TradingCalendar):
            raise TypeError("trading date service requires a TradingCalendar")

    def resolve(self, variety: Variety, market_time: ShanghaiTimestamp, as_of: RecordedAt) -> TradingDateOutcome:
        if not isinstance(variety, Variety):
            raise TypeError("trading date resolution requires an exact Variety")
        if not isinstance(market_time, ShanghaiTimestamp):
            raise TypeError("trading date resolution requires an Asia/Shanghai market_time")
        if not isinstance(as_of, RecordedAt):
            raise TypeError("trading date resolution requires a RecordedAt as_of")

        scoped_schedules = tuple(schedule for schedule in self.calendar.schedules if schedule.variety == variety)
        scoped_closures = tuple(
            closure
            for closure in self.calendar.closures
            if closure.exchange is variety.exchange and closure.applies_to(market_time)
        )
        visible_schedules = tuple(schedule for schedule in scoped_schedules if schedule.provenance.is_visible_at(as_of))
        visible_closures = tuple(closure for closure in scoped_closures if closure.provenance.is_visible_at(as_of))
        base_schedules = tuple(
            schedule
            for schedule in visible_schedules
            if not any(schedule.revision_id in successor.supersedes for successor in visible_schedules)
        )
        base_closures = tuple(
            closure
            for closure in visible_closures
            if not any(closure.revision_id in successor.supersedes for successor in visible_closures)
        )
        active_closures = tuple(
            closure
            for closure in base_closures
            if not any(
                closure.revision_id in schedule.supersedes and schedule.matching_phase(market_time) is not None
                for schedule in base_schedules
            )
        )
        active_schedules = tuple(
            schedule
            for schedule in base_schedules
            if not any(schedule.revision_id in closure.supersedes for closure in active_closures)
        )
        matches = tuple(
            (schedule, matching)
            for schedule in active_schedules
            if (matching := schedule.matching_phase(market_time)) is not None
        )
        if len(matches) > 1 or (matches and active_closures):
            return Failure(ReasonCode.CALENDAR_CONFLICT, "multiple visible calendar phases apply to market_time")
        if len(matches) == 1:
            schedule, (session_name, occurrence) = matches[0]
            return TradingDateResolution(
                variety.exchange,
                schedule.trading_date,
                market_time,
                as_of,
                session_name,
                occurrence.phase,
                schedule,
                self.calendar.ref,
            )
        if len(active_closures) > 1:
            return Failure(ReasonCode.CALENDAR_CONFLICT, "multiple visible calendar closures apply to market_time")
        if len(active_closures) == 1:
            return Failure(ReasonCode.CALENDAR_CLOSED, "exchange is closed by an explicit calendar closure")
        raw_matches = tuple(
            schedule for schedule in scoped_schedules if schedule.matching_phase(market_time) is not None
        )
        if raw_matches and not visible_schedules:
            return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar session was not acquired at as_of")
        if raw_matches and visible_schedules and not active_schedules:
            return Failure(ReasonCode.CALENDAR_CONFLICT, "no unique active calendar phase applies to market_time")
        if scoped_closures and not visible_closures and not active_schedules:
            return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar closure was not acquired at as_of")
        market_date = market_time.value.date()
        represented = tuple(schedule for schedule in active_schedules if schedule.touches_calendar_date(market_date))
        if represented:
            return Failure(ReasonCode.CALENDAR_CLOSED, "market_time is outside explicit exchange session phases")
        raw_represented = tuple(
            schedule for schedule in scoped_schedules if schedule.touches_calendar_date(market_date)
        )
        if raw_represented and not visible_schedules:
            return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar session was not acquired at as_of")
        if raw_represented and visible_schedules and not active_schedules:
            return Failure(ReasonCode.CALENDAR_CONFLICT, "no unique active calendar phase applies to market_time")
        return Failure(ReasonCode.CALENDAR_MISSING, "no explicit calendar fact applies to market_time")

    def events_for(self, exchange: Exchange, trading_date: TradingDate, as_of: RecordedAt) -> CalendarEventsOutcome:
        if not isinstance(exchange, Exchange) or not isinstance(trading_date, TradingDate):
            raise TypeError("calendar event lookup requires an Exchange and TradingDate")
        if not isinstance(as_of, RecordedAt):
            raise TypeError("calendar event lookup requires a RecordedAt as_of")
        events = tuple(
            event
            for event in self.calendar.reference_events
            if event.exchange is exchange and event.trading_date == trading_date
        )
        if any(not event.provenance.is_visible_at(as_of) for event in events):
            return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "calendar reference event was not acquired at as_of")
        return events


def trading_calendar_content_sha256(
    schedules: tuple[TradingDaySchedule, ...],
    closures: tuple[CalendarClosure, ...],
    reference_events: tuple[CalendarReferenceEvent, ...],
) -> str:
    """Hash a calendar release independent of caller ordering and release identity."""
    typed_schedules, typed_closures, typed_events = tuple(schedules), tuple(closures), tuple(reference_events)
    if any(not isinstance(item, TradingDaySchedule) for item in typed_schedules):
        raise TypeError("calendar content requires TradingDaySchedule values")
    if any(not isinstance(item, CalendarClosure) for item in typed_closures):
        raise TypeError("calendar content requires CalendarClosure values")
    if any(not isinstance(item, CalendarReferenceEvent) for item in typed_events):
        raise TypeError("calendar content requires CalendarReferenceEvent values")
    payload = {
        "schedules": tuple(sorted((_schedule_payload(item) for item in typed_schedules), key=repr)),
        "closures": tuple(sorted((_closure_payload(item) for item in typed_closures), key=repr)),
        "reference_events": tuple(sorted((_event_payload(item) for item in typed_events), key=repr)),
    }
    return canonical_sha256(cast("JsonValue", payload))


def _reject_overlaps(
    schedules: tuple[TradingDaySchedule, ...],
    closures: tuple[CalendarClosure, ...],
    events: tuple[CalendarReferenceEvent, ...],
) -> None:
    facts: tuple[TradingDaySchedule | CalendarClosure, ...] = schedules + closures
    fact_by_id = {fact.revision_id: fact for fact in facts}
    if len(fact_by_id) != len(facts):
        raise ValueError("trading calendar revision ids must be unique")
    for successor in facts:
        for predecessor_id in successor.supersedes:
            predecessor = fact_by_id.get(predecessor_id)
            if predecessor is None:
                raise ValueError("calendar supersedes must reference a fact in the same immutable release")
            if predecessor.exchange is not successor.exchange:
                raise ValueError("calendar supersedes cannot cross exchange namespaces")
            if isinstance(successor, TradingDaySchedule) and isinstance(predecessor, TradingDaySchedule):
                if successor.variety != predecessor.variety:
                    raise ValueError("trading day schedule supersedes cannot cross exact Variety scopes")
                if successor.trading_date != predecessor.trading_date or not _schedule_scopes_touch(
                    successor, predecessor
                ):
                    raise ValueError("trading day schedule supersedes must share a touching TradingDate scope")
            if isinstance(successor, CalendarClosure) and isinstance(predecessor, CalendarClosure):
                if successor.calendar_date != predecessor.calendar_date:
                    raise ValueError("calendar closure supersedes must share the same calendar date")
            if isinstance(successor, CalendarClosure) and isinstance(predecessor, TradingDaySchedule):
                if successor.calendar_date not in _schedule_calendar_dates(predecessor):
                    raise ValueError("calendar closure supersedes must share an affected calendar date")
            if isinstance(successor, TradingDaySchedule) and isinstance(predecessor, CalendarClosure):
                if predecessor.calendar_date not in _schedule_calendar_dates(successor):
                    raise ValueError("trading day schedule supersedes must share an affected calendar date")
            if successor.version <= predecessor.version:
                raise ValueError("calendar successor version must exceed its predecessor version")
            if successor.provenance.acquired_at.value <= predecessor.provenance.acquired_at.value:
                raise ValueError("calendar successor must be acquired after its predecessor")
    _reject_revision_cycles(fact_by_id)
    occurrences = tuple(
        (schedule, phase) for schedule in schedules for session in schedule.sessions for phase in session.phases
    )
    for index, (left_schedule, left_phase) in enumerate(occurrences):
        for right_schedule, right_phase in occurrences[index + 1 :]:
            if (
                left_schedule.variety == right_schedule.variety
                and left_phase.starts_at.value < right_phase.ends_at.value
                and right_phase.starts_at.value < left_phase.ends_at.value
                and not _directly_supersedes(left_schedule, right_schedule)
            ):
                raise ValueError("trading calendar cannot publish overlapping exact-Variety phase occurrences")
    for index, left_closure in enumerate(closures):
        for right_closure in closures[index + 1 :]:
            if (
                left_closure.exchange is right_closure.exchange
                and left_closure.calendar_date == right_closure.calendar_date
                and not _directly_supersedes(left_closure, right_closure)
            ):
                raise ValueError("trading calendar cannot publish competing closures without explicit supersession")
    if len({(event.exchange, event.trading_date, event.kind) for event in events}) != len(events):
        raise ValueError("trading calendar cannot publish duplicate reference event kinds")
    for closure in closures:
        if any(
            schedule.exchange is closure.exchange
            and phase.touches_calendar_date(closure.calendar_date)
            and not _directly_supersedes(closure, schedule)
            for schedule, phase in occurrences
        ):
            raise ValueError("calendar closure requires explicit supersession of every overlapping schedule")


def _directly_supersedes(
    left: TradingDaySchedule | CalendarClosure, right: TradingDaySchedule | CalendarClosure
) -> bool:
    return left.revision_id in right.supersedes or right.revision_id in left.supersedes


def _schedule_calendar_dates(schedule: TradingDaySchedule) -> frozenset[date]:
    return frozenset(
        calendar_date
        for session in schedule.sessions
        for phase in session.phases
        for calendar_date in (phase.starts_at.value.date(), (phase.ends_at.value - datetime.resolution).date())
    )


def _schedule_scopes_touch(left: TradingDaySchedule, right: TradingDaySchedule) -> bool:
    return any(
        left_phase.starts_at.value <= right_phase.ends_at.value
        and right_phase.starts_at.value <= left_phase.ends_at.value
        for left_session in left.sessions
        for left_phase in left_session.phases
        for right_session in right.sessions
        for right_phase in right_session.phases
    )


def _reject_revision_cycles(fact_by_id: dict[EntityId, TradingDaySchedule | CalendarClosure]) -> None:
    def has_cycle(revision_id: EntityId, visited: frozenset[EntityId]) -> bool:
        if revision_id in visited:
            return True
        return any(
            has_cycle(predecessor, visited | {revision_id}) for predecessor in fact_by_id[revision_id].supersedes
        )

    if any(has_cycle(revision_id, frozenset()) for revision_id in fact_by_id):
        raise ValueError("calendar supersedes cannot contain a cycle")


def _timestamp(text: str) -> ShanghaiTimestamp:
    return ShanghaiTimestamp(datetime.fromisoformat(text).replace(tzinfo=_SHANGHAI))


def _provenance() -> ReferenceProvenance:
    return ReferenceProvenance(
        "fixtures/v1-003/synthetic-trading-calendar.json",
        _RELEASED_AT,
        _RELEASED_AT,
        "synthetic-calendar-v1.0",
    )


def _revision(number: int) -> EntityId:
    return EntityId.parse(f"trading_calendar_revision_018f9b16-9a00-7abe-8000-{number:012d}")


def _phase(phase: SessionPhase, starts: str, ends: str) -> SessionPhaseOccurrence:
    return SessionPhaseOccurrence(phase, _timestamp(starts), _timestamp(ends))


def _day_session(*phases: SessionPhaseOccurrence) -> TradingSessionOccurrence:
    return TradingSessionOccurrence("DAY", phases)


def _night_session(*phases: SessionPhaseOccurrence) -> TradingSessionOccurrence:
    return TradingSessionOccurrence("NIGHT", phases)


def _standard_day(day: str) -> TradingSessionOccurrence:
    return _day_session(
        _phase(SessionPhase.CALL_AUCTION, f"{day}T08:55:00", f"{day}T09:00:00"),
        _phase(SessionPhase.CONTINUOUS, f"{day}T09:00:00", f"{day}T10:15:00"),
        _phase(SessionPhase.BREAK, f"{day}T10:15:00", f"{day}T10:30:00"),
        _phase(SessionPhase.CONTINUOUS, f"{day}T10:30:00", f"{day}T11:30:00"),
        _phase(SessionPhase.BREAK, f"{day}T11:30:00", f"{day}T13:30:00"),
        _phase(SessionPhase.CONTINUOUS, f"{day}T13:30:00", f"{day}T15:00:00"),
    )


def initial_acceptance_trading_calendar() -> TradingCalendar:
    """Fixed synthetic V1-003 fixtures, not a production exchange calendar.

    Every night/day occurrence, closure, adjustment, and cross-owner event is
    literal.  The fixture therefore proves attribution semantics without
    claiming authoritative exchange session rules.
    """

    provenance = _provenance()
    shfe_ag = Variety(Exchange.SHFE, "AG", "synthetic silver")
    dce_i = Variety(Exchange.DCE, "I", "synthetic iron ore")
    czce_ma = Variety(Exchange.CZCE, "MA", "synthetic methanol")
    cffex_if = Variety(Exchange.CFFEX, "IF", "synthetic index future")
    schedules = (
        TradingDaySchedule(
            Exchange.SHFE,
            shfe_ag,
            TradingDate.parse("2026-08-25"),
            (
                _night_session(
                    _phase(SessionPhase.CALL_AUCTION, "2026-08-24T20:55:00", "2026-08-24T21:00:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-24T21:00:00", "2026-08-25T02:30:00"),
                ),
                _standard_day("2026-08-25"),
            ),
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
            _revision(1),
        ),
        TradingDaySchedule(
            Exchange.DCE,
            dce_i,
            TradingDate.parse("2026-08-25"),
            (
                _night_session(
                    _phase(SessionPhase.CALL_AUCTION, "2026-08-24T20:55:00", "2026-08-24T21:00:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-24T21:00:00", "2026-08-24T23:00:00"),
                ),
                _standard_day("2026-08-25"),
            ),
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
            _revision(2),
        ),
        TradingDaySchedule(
            Exchange.CZCE,
            czce_ma,
            TradingDate.parse("2026-08-25"),
            (
                _night_session(
                    _phase(SessionPhase.CALL_AUCTION, "2026-08-24T20:55:00", "2026-08-24T21:00:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-24T21:00:00", "2026-08-24T23:00:00"),
                ),
                _standard_day("2026-08-25"),
            ),
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
            _revision(3),
        ),
        TradingDaySchedule(
            Exchange.CFFEX,
            cffex_if,
            TradingDate.parse("2026-08-25"),
            (
                _day_session(
                    _phase(SessionPhase.CALL_AUCTION, "2026-08-25T09:25:00", "2026-08-25T09:30:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-25T09:30:00", "2026-08-25T11:30:00"),
                    _phase(SessionPhase.BREAK, "2026-08-25T11:30:00", "2026-08-25T13:00:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-25T13:00:00", "2026-08-25T15:00:00"),
                ),
            ),
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
            _revision(4),
        ),
        TradingDaySchedule(
            Exchange.DCE,
            dce_i,
            TradingDate.parse("2026-08-26"),
            (
                _night_session(
                    _phase(SessionPhase.CALL_AUCTION, "2026-08-25T20:55:00", "2026-08-25T21:00:00"),
                    _phase(SessionPhase.CONTINUOUS, "2026-08-25T21:00:00", "2026-08-25T22:30:00"),
                ),
                _standard_day("2026-08-26"),
            ),
            _timestamp("2026-08-23T12:00:00"),
            2,
            provenance,
            _revision(5),
            "calendar-adjustment://synthetic/dce/2026-08-26/early-close",
        ),
        TradingDaySchedule(
            Exchange.SHFE,
            shfe_ag,
            TradingDate.parse("2026-08-28"),
            (_standard_day("2026-08-28"),),
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
            _revision(6),
        ),
    )
    closures = (
        CalendarClosure(
            Exchange.SHFE,
            date(2026, 10, 1),
            ClosureKind.HOLIDAY,
            _timestamp("2026-09-01T09:00:00"),
            1,
            provenance,
            _revision(7),
        ),
        CalendarClosure(
            Exchange.DCE,
            date(2026, 8, 27),
            ClosureKind.SPECIAL_CLOSURE,
            _timestamp("2026-08-23T12:00:00"),
            1,
            provenance,
            _revision(8),
        ),
    )
    events = (
        CalendarReferenceEvent(
            Exchange.DCE,
            TradingDate.parse("2026-08-26"),
            CalendarReferenceEventKind.DOMINANT_CONTRACT_SWITCH,
            "dominant-contract-reference://DCE.I/2026-08-26/v1",
            _timestamp("2026-08-23T12:00:00"),
            1,
            provenance,
        ),
        CalendarReferenceEvent(
            Exchange.SHFE,
            TradingDate.parse("2026-08-28"),
            CalendarReferenceEventKind.NEAR_DELIVERY_WINDOW,
            "delivery-restriction-reference://SHFE.AG2606/2026-08-28/v1",
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
        ),
        CalendarReferenceEvent(
            Exchange.CZCE,
            TradingDate.parse("2026-08-25"),
            CalendarReferenceEventKind.CONTRACT_RULE_ADJUSTMENT,
            "contract-rule-reference://CZCE.MA605/2026-08-25/v2",
            _timestamp("2026-08-01T08:00:00"),
            1,
            provenance,
        ),
    )
    return TradingCalendar(
        INITIAL_ACCEPTANCE_CALENDAR_ID,
        INITIAL_ACCEPTANCE_CALENDAR_RELEASE_VERSION,
        schedules,
        closures,
        events,
        INITIAL_ACCEPTANCE_CALENDAR_SHA256,
    )


def _phase_payload(phase: SessionPhaseOccurrence) -> dict[str, str]:
    return {
        "phase": phase.phase.value,
        "starts_at": phase.starts_at.to_dict()["market_time"],
        "ends_at": phase.ends_at.to_dict()["market_time"],
    }


def _provenance_payload(provenance: ReferenceProvenance) -> dict[str, str | None]:
    return {
        "source_ref": provenance.source_ref,
        "acquired_at": provenance.acquired_at.to_dict()["recorded_at"],
        "source_published_at": provenance.source_published_at.to_dict()["recorded_at"]
        if provenance.source_published_at
        else None,
        "source_revision": provenance.source_revision,
    }


def _schedule_payload(schedule: TradingDaySchedule) -> dict[str, object]:
    return {
        "exchange": schedule.exchange.value,
        "variety": schedule.variety.reference_id,
        "trading_date": str(schedule.trading_date),
        "sessions": tuple(
            {"name": session.name, "phases": tuple(_phase_payload(phase) for phase in session.phases)}
            for session in schedule.sessions
        ),
        "event_time": schedule.event_time.to_dict()["market_time"],
        "version": schedule.version,
        "provenance": _provenance_payload(schedule.provenance),
        "revision_id": str(schedule.revision_id),
        "adjustment_ref": schedule.adjustment_ref,
        "supersedes": tuple(str(predecessor) for predecessor in schedule.supersedes),
    }


def _closure_payload(closure: CalendarClosure) -> dict[str, object]:
    return {
        "exchange": closure.exchange.value,
        "calendar_date": closure.calendar_date.isoformat(),
        "kind": closure.kind.value,
        "event_time": closure.event_time.to_dict()["market_time"],
        "version": closure.version,
        "provenance": _provenance_payload(closure.provenance),
        "revision_id": str(closure.revision_id),
        "supersedes": tuple(str(predecessor) for predecessor in closure.supersedes),
    }


def _event_payload(event: CalendarReferenceEvent) -> dict[str, object]:
    return {
        "exchange": event.exchange.value,
        "trading_date": str(event.trading_date),
        "kind": event.kind.value,
        "reference_ref": event.reference_ref,
        "event_time": event.event_time.to_dict()["market_time"],
        "version": event.version,
        "provenance": _provenance_payload(event.provenance),
    }
