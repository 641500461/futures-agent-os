"""Learning & Review-owned, append-only rebuildable source-event projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


class JournalPhase(StrEnum):
    DECISION_TIME = "DECISION_TIME"
    POST_HOC = "POST_HOC"


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """A published fact; its owner stays in the source bounded context."""

    event_id: EntityId
    source_context: str
    source_version: int
    event_type: str
    occurred_at: RecordedAt
    available_at: RecordedAt
    payload_hash: str
    correlation_id: EntityId

    def __post_init__(self) -> None:
        if (
            not self.source_context
            or not self.event_type
            or isinstance(self.source_version, bool)
            or not isinstance(self.source_version, int)
            or self.source_version < 1
        ):
            raise ValueError("source events require context, event type, and positive version")
        if (
            not isinstance(self.event_id, EntityId)
            or not isinstance(self.correlation_id, EntityId)
            or not isinstance(self.occurred_at, RecordedAt)
            or not isinstance(self.available_at, RecordedAt)
        ):
            raise TypeError("source events require typed ids and timestamps")
        if self.available_at.value < self.occurred_at.value:
            raise ValueError("source facts cannot become available before occurring")
        if (
            not isinstance(self.payload_hash, str)
            or len(self.payload_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.payload_hash)
        ):
            raise ValueError("source events require a lowercase SHA-256 payload hash")


def _unique_facts(sources: tuple[SourceEvent, ...]) -> tuple[SourceEvent, ...]:
    """Deduplicate exact replays; reject an event id that names conflicting facts."""
    unique: dict[EntityId, SourceEvent] = {}
    for source in sources:
        existing = unique.get(source.event_id)
        if existing is not None and existing != source:
            raise ValueError("source event id conflicts with a different immutable fact")
        unique[source.event_id] = source
    return tuple(sorted(unique.values(), key=lambda value: (value.available_at.value, str(value.event_id))))


@dataclass(frozen=True, slots=True)
class DecisionJournalEntry:
    entry_id: EntityId
    journal_id: EntityId
    source_event_id: EntityId
    projection_version: int
    phase: JournalPhase
    source_hash: str
    observed_at: RecordedAt
    available_at: RecordedAt
    projected_at: RecordedAt
    decision_cutoff_at: RecordedAt | None = None
    episode_id: EntityId | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.projection_version, bool)
            or not isinstance(self.projection_version, int)
            or self.projection_version < 1
            or not isinstance(self.source_hash, str)
            or len(self.source_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.source_hash)
        ):
            raise ValueError("journal entries require projection version and source hash")
        if not isinstance(self.phase, JournalPhase) or not all(
            isinstance(value, RecordedAt) for value in (self.observed_at, self.available_at, self.projected_at)
        ):
            raise TypeError("journal entries require typed phase and timestamps")
        if self.projected_at.value < self.available_at.value:
            raise ValueError("journal entries must not project unavailable facts")
        if self.phase is JournalPhase.DECISION_TIME and (
            self.decision_cutoff_at is None or self.available_at.value > self.decision_cutoff_at.value
        ):
            raise ValueError("decision-time entries require an authoritative decision cutoff")


class DecisionJournal:
    """Deduplicated append-only projection. Rebuild replaces projection, never facts."""

    def __init__(self, journal_id: EntityId, projection_version: int = 1) -> None:
        if projection_version < 1:
            raise ValueError("projection version must be positive")
        self.journal_id = journal_id
        self.projection_version = projection_version
        self._entries: list[DecisionJournalEntry] = []
        self._entries_by_key: dict[tuple[EntityId, int], DecisionJournalEntry] = {}
        self._sources: dict[EntityId, SourceEvent] = {}
        self._entry_ids: dict[tuple[EntityId, int], EntityId] = {}
        self._lock = RLock()

    def append(
        self,
        source: SourceEvent,
        phase: JournalPhase,
        projected_at: RecordedAt,
        episode_id: EntityId | None = None,
        *,
        decision_cutoff_at: RecordedAt | None = None,
    ) -> DecisionJournalEntry:
        with self._lock:
            key = (source.event_id, self.projection_version)
            existing_source = self._sources.get(source.event_id)
            if existing_source is not None and existing_source != source:
                raise ValueError("source event id conflicts with a different immutable fact")
            existing_entry = self._entries_by_key.get(key)
            if existing_entry is not None:
                requested = DecisionJournalEntry(
                    existing_entry.entry_id,
                    self.journal_id,
                    source.event_id,
                    self.projection_version,
                    phase,
                    source.payload_hash,
                    source.occurred_at,
                    source.available_at,
                    projected_at,
                    decision_cutoff_at,
                    episode_id,
                )
                if requested != existing_entry:
                    raise ValueError("source event already projects a conflicting journal entry")
                return existing_entry
            entry = DecisionJournalEntry(
                self._entry_ids.setdefault(key, EntityId.new("decision_journal_entry")),
                self.journal_id,
                source.event_id,
                self.projection_version,
                phase,
                source.payload_hash,
                source.occurred_at,
                source.available_at,
                projected_at,
                decision_cutoff_at,
                episode_id,
            )
            self._sources[source.event_id] = source
            self._entries_by_key[key] = entry
            self._entries.append(entry)
            return entry

    def rebuild(
        self,
        sources: tuple[SourceEvent, ...],
        projected_at: RecordedAt,
        *,
        phase_for_event: dict[EntityId, JournalPhase] | None = None,
        decision_cutoff_at: RecordedAt | None = None,
    ) -> tuple[DecisionJournalEntry, ...]:
        with self._lock:
            ordered = _unique_facts(sources)
            # Validate the complete replacement projection before touching the
            # current one.  A bad later fact must not leave a partial rebuild.
            staged_entries: list[DecisionJournalEntry] = []
            staged_entries_by_key: dict[tuple[EntityId, int], DecisionJournalEntry] = {}
            staged_sources: dict[EntityId, SourceEvent] = {}
            staged_entry_ids = dict(self._entry_ids)
            for source in ordered:
                key = (source.event_id, self.projection_version)
                entry = DecisionJournalEntry(
                    staged_entry_ids.setdefault(key, EntityId.new("decision_journal_entry")),
                    self.journal_id,
                    source.event_id,
                    self.projection_version,
                    (phase_for_event or {}).get(source.event_id, JournalPhase.DECISION_TIME),
                    source.payload_hash,
                    source.occurred_at,
                    source.available_at,
                    projected_at,
                    decision_cutoff_at,
                )
                staged_sources[source.event_id] = source
                staged_entries_by_key[key] = entry
                staged_entries.append(entry)
            self._entries = staged_entries
            self._entries_by_key = staged_entries_by_key
            self._sources = staged_sources
            self._entry_ids = staged_entry_ids
            return self.entries

    @property
    def entries(self) -> tuple[DecisionJournalEntry, ...]:
        with self._lock:
            return tuple(self._entries)


@dataclass(frozen=True, slots=True)
class TradeEpisode:
    """A derived source-event projection, not a Decision/Execution/Accounting writer."""

    episode_id: EntityId
    decision_episode_id: EntityId
    source_event_ids: tuple[EntityId, ...]
    projection_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.episode_id, EntityId) or not isinstance(self.decision_episode_id, EntityId):
            raise TypeError("trade episodes require typed identities")
        if (
            not isinstance(self.source_event_ids, tuple)
            or not self.source_event_ids
            or any(not isinstance(event_id, EntityId) for event_id in self.source_event_ids)
            or len(self.source_event_ids) != len(set(self.source_event_ids))
        ):
            raise ValueError("trade episodes require unique immutable source event identities")
        if (
            not isinstance(self.projection_hash, str)
            or len(self.projection_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.projection_hash)
        ):
            raise ValueError("trade episodes require a lowercase SHA-256 projection hash")

    @classmethod
    def rebuild(
        cls, episode_id: EntityId, decision_episode_id: EntityId, sources: tuple[SourceEvent, ...]
    ) -> TradeEpisode:
        # _unique_facts and the immutable constructor complete before any
        # projection object is returned, so a conflict cannot partially update one.
        ordered = _unique_facts(sources)
        return cls(
            episode_id,
            decision_episode_id,
            tuple(value.event_id for value in ordered),
            canonical_sha256(
                {
                    "episode": str(decision_episode_id),
                    "facts": tuple(
                        (
                            str(value.event_id),
                            value.source_context,
                            value.event_type,
                            value.occurred_at.to_dict()["recorded_at"],
                            str(value.correlation_id),
                            value.source_version,
                            value.payload_hash,
                        )
                        for value in ordered
                    ),
                }
            ),
        )
