"""Causal collection, commitment, roster, and reveal contracts for the MVP-R Pivot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
import re

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.shared_kernel import EntityId, RecordedAt, TradingDate, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_pivot import screen_hypothesis_families
from .mvp_replay import replay_market_state_scores
from .mvp_roster import EpisodeStratum
from .mvp_validation import PitArtifactRecord


PIVOT_FORWARD_PROTOCOL = "mvp-r.pivot-forward.v1"
PIVOT_FORWARD_SELECTION_RULE = "composite-stratified-causal-hmac-sha256.v1"
PIVOT_FORWARD_PIVOT_DATE = TradingDate(date(2026, 8, 30))
PIVOT_FORWARD_WINDOW_BARS = 40
PIVOT_FORWARD_LABEL_BARS = 5
PIVOT_FORWARD_ROSTER_SIZE = 50
PIVOT_FORWARD_UNIVERSE = (
    "CZCE.MA.DOMINANT_OI",
    "CZCE.SR.DOMINANT_OI",
    "SHFE.AG.DOMINANT_OI",
    "SHFE.CU.DOMINANT_OI",
)
PIVOT_FORWARD_SIGNAL_THRESHOLD = Decimal("0.00010000")
PIVOT_FORWARD_PER_SIGNAL_COST = Decimal("0.00030000")

_GENESIS_SHA256 = "0" * 64
_CANONICAL_AUTHORITY = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")


@dataclass(frozen=True, slots=True)
class ForwardAcquiredRecord:
    instrument_id: str
    dataset_manifest_sha256: str
    record_sha256: str
    event_time: RecordedAt
    available_time: RecordedAt

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("forward acquired record requires an instrument")
        _digest(self.dataset_manifest_sha256)
        _digest(self.record_sha256)
        if type(self.event_time) is not RecordedAt or type(self.available_time) is not RecordedAt:
            raise TypeError("forward acquired record requires typed timestamps")
        if self.available_time.value < self.event_time.value:
            raise ValueError("forward acquired record cannot be available before its event")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "instrument_id": self.instrument_id,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "record_sha256": self.record_sha256,
            "event_time": self.event_time.to_dict()["recorded_at"],
            "available_time": self.available_time.to_dict()["recorded_at"],
        }


@dataclass(frozen=True, slots=True)
class ForwardDailyAcquisition:
    collection_authority_id: str
    protocol: str
    sequence_number: int
    trading_date: TradingDate
    recorded_at: RecordedAt
    previous_acquisition_sha256: str
    records: tuple[ForwardAcquiredRecord, ...]
    signature_sha256: str

    def __post_init__(self) -> None:
        _authority(self.collection_authority_id)
        if self.protocol != PIVOT_FORWARD_PROTOCOL:
            raise ValueError("forward acquisition requires the frozen Pivot protocol")
        if type(self.sequence_number) is not int or self.sequence_number < 1:
            raise ValueError("forward acquisition sequence must be positive")
        if type(self.trading_date) is not TradingDate or self.trading_date.value <= PIVOT_FORWARD_PIVOT_DATE.value:
            raise ValueError("forward acquisition trading date must follow the Pivot decision")
        if type(self.recorded_at) is not RecordedAt:
            raise TypeError("forward acquisition requires a typed recording time")
        _digest(self.previous_acquisition_sha256)
        _digest(self.signature_sha256)
        if tuple(item.instrument_id for item in self.records) != PIVOT_FORWARD_UNIVERSE:
            raise ValueError("forward acquisition requires the complete frozen instrument universe")
        if any(item.available_time.value > self.recorded_at.value for item in self.records):
            raise PermissionError("forward acquisition cannot include a record not yet available")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "collection_authority_id": self.collection_authority_id,
            "protocol": self.protocol,
            "sequence_number": self.sequence_number,
            "trading_date": str(self.trading_date),
            "recorded_at": self.recorded_at.to_dict()["recorded_at"],
            "previous_acquisition_sha256": self.previous_acquisition_sha256,
            "records": tuple(item.payload() for item in self.records),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())


@dataclass(frozen=True, slots=True)
class ForwardStratumScore:
    stratum: EpisodeStratum
    score: str

    def __post_init__(self) -> None:
        if type(self.stratum) is not EpisodeStratum:
            raise TypeError("forward stratum score requires an exact stratum")
        _decimal(self.score, "forward stratum score")

    def payload(self) -> dict[str, JsonValue]:
        return {"stratum": self.stratum.value, "score": self.score}


@dataclass(frozen=True, slots=True)
class ForwardEpisodeCommitment:
    collection_authority_id: str
    protocol: str
    episode_id: EntityId
    instrument_id: str
    cutoff_trading_date: TradingDate
    cutoff_event_time: RecordedAt
    committed_at: RecordedAt
    acquisition_sha256: str
    input_manifest_sha256s: tuple[str, ...]
    input_record_sha256s: tuple[str, ...]
    family_screen_sha256s: tuple[str, ...]
    stratum_scores: tuple[ForwardStratumScore, ...]
    signature_sha256: str

    def __post_init__(self) -> None:
        _authority(self.collection_authority_id)
        if self.protocol != PIVOT_FORWARD_PROTOCOL:
            raise ValueError("forward commitment requires the frozen Pivot protocol")
        if type(self.episode_id) is not EntityId or self.episode_id.namespace != "evaluation_episode":
            raise ValueError("forward commitment requires an evaluation_episode identity")
        if self.instrument_id not in PIVOT_FORWARD_UNIVERSE:
            raise ValueError("forward commitment instrument is outside the frozen universe")
        if (
            type(self.cutoff_trading_date) is not TradingDate
            or self.cutoff_trading_date.value <= PIVOT_FORWARD_PIVOT_DATE.value
        ):
            raise ValueError("forward commitment cutoff must follow the Pivot decision")
        if type(self.cutoff_event_time) is not RecordedAt or type(self.committed_at) is not RecordedAt:
            raise TypeError("forward commitment requires typed timestamps")
        if self.committed_at.value < self.cutoff_event_time.value:
            raise ValueError("forward commitment cannot precede its market cutoff")
        _digest(self.acquisition_sha256)
        _digest(self.signature_sha256)
        if len(self.input_manifest_sha256s) != PIVOT_FORWARD_WINDOW_BARS:
            raise ValueError("forward commitment requires forty input manifest references")
        if len(self.input_record_sha256s) != PIVOT_FORWARD_WINDOW_BARS or len(set(self.input_record_sha256s)) != len(
            self.input_record_sha256s
        ):
            raise ValueError("forward commitment requires forty unique input record references")
        if len(self.family_screen_sha256s) != 6:
            raise ValueError("forward commitment requires the complete six-family screen")
        for digest in (*self.input_manifest_sha256s, *self.input_record_sha256s, *self.family_screen_sha256s):
            _digest(digest)
        if tuple(item.stratum for item in self.stratum_scores) != tuple(EpisodeStratum):
            raise ValueError("forward commitment requires all market-state scores in canonical order")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "collection_authority_id": self.collection_authority_id,
            "protocol": self.protocol,
            "episode_id": str(self.episode_id),
            "instrument_id": self.instrument_id,
            "cutoff_trading_date": str(self.cutoff_trading_date),
            "cutoff_event_time": self.cutoff_event_time.to_dict()["recorded_at"],
            "committed_at": self.committed_at.to_dict()["recorded_at"],
            "acquisition_sha256": self.acquisition_sha256,
            "input_manifest_sha256s": self.input_manifest_sha256s,
            "input_record_sha256s": self.input_record_sha256s,
            "family_screen_sha256s": self.family_screen_sha256s,
            "stratum_scores": tuple(item.payload() for item in self.stratum_scores),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())

    def score(self, stratum: EpisodeStratum) -> Decimal:
        return _decimal(next(item.score for item in self.stratum_scores if item.stratum is stratum), "stratum score")


class ForwardCollectionAuthority:
    """Sign complete daily acquisitions and future-blind cutoff commitments."""

    def __init__(self, authority_id: str, signing_key: bytes) -> None:
        _authority(authority_id)
        _key(signing_key)
        self._authority_id = authority_id
        self._signing_key = signing_key

    @property
    def authority_id(self) -> str:
        return self._authority_id

    def record_day(
        self,
        *,
        previous: ForwardDailyAcquisition | None,
        trading_date: TradingDate,
        recorded_at: RecordedAt,
        artifacts: tuple[PitArtifactRecord, ...],
    ) -> ForwardDailyAcquisition:
        if type(trading_date) is not TradingDate or type(recorded_at) is not RecordedAt:
            raise TypeError("forward daily recording requires typed date and time")
        if len(artifacts) != len(PIVOT_FORWARD_UNIVERSE) or any(
            type(item) is not PitArtifactRecord for item in artifacts
        ):
            raise ValueError("forward daily recording requires four authorized PIT artifacts")
        by_instrument = {item.instrument_id: item for item in artifacts}
        if set(by_instrument) != set(PIVOT_FORWARD_UNIVERSE):
            raise ValueError("forward daily recording requires the complete frozen instrument universe")
        if previous is None:
            sequence_number = 1
            previous_sha256 = _GENESIS_SHA256
        else:
            self.verify_acquisition(previous)
            if trading_date.value <= previous.trading_date.value or recorded_at.value <= previous.recorded_at.value:
                raise ValueError("forward acquisition chain must advance date and recording time")
            sequence_number = previous.sequence_number + 1
            previous_sha256 = previous.content_sha256
        records = tuple(
            ForwardAcquiredRecord(
                instrument,
                by_instrument[instrument].dataset_manifest_sha256,
                by_instrument[instrument].content_sha256,
                by_instrument[instrument].record.event_time,
                by_instrument[instrument].record.available_time,
            )
            for instrument in PIVOT_FORWARD_UNIVERSE
        )
        for artifact in artifacts:
            if artifact.record.values.get("trading_date") != str(trading_date):
                raise ValueError("forward artifact trading date does not match its acquisition event")
        unsigned: dict[str, JsonValue] = {
            "collection_authority_id": self._authority_id,
            "protocol": PIVOT_FORWARD_PROTOCOL,
            "sequence_number": sequence_number,
            "trading_date": str(trading_date),
            "recorded_at": recorded_at.to_dict()["recorded_at"],
            "previous_acquisition_sha256": previous_sha256,
            "records": tuple(item.payload() for item in records),
        }
        return ForwardDailyAcquisition(
            self._authority_id,
            PIVOT_FORWARD_PROTOCOL,
            sequence_number,
            trading_date,
            recorded_at,
            previous_sha256,
            records,
            self._sign(unsigned),
        )

    def issue_commitment(
        self,
        *,
        episode_id: EntityId,
        acquisition: ForwardDailyAcquisition,
        artifacts: tuple[PitArtifactRecord, ...],
        committed_at: RecordedAt,
    ) -> ForwardEpisodeCommitment:
        self.verify_acquisition(acquisition)
        if type(committed_at) is not RecordedAt or committed_at.value < acquisition.recorded_at.value:
            raise ValueError("forward commitment must follow its signed daily acquisition")
        if len(artifacts) != PIVOT_FORWARD_WINDOW_BARS or any(
            type(item) is not PitArtifactRecord for item in artifacts
        ):
            raise ValueError("forward commitment requires forty authorized PIT artifacts")
        instrument_id = artifacts[0].instrument_id
        if instrument_id not in PIVOT_FORWARD_UNIVERSE or any(
            item.instrument_id != instrument_id for item in artifacts
        ):
            raise PermissionError("forward commitment cannot cross instruments")
        records = tuple(item.record for item in artifacts)
        if tuple(sorted(records, key=lambda item: item.event_time.value)) != records or len(
            {item.event_time for item in records}
        ) != len(records):
            raise ValueError("forward commitment inputs must be unique and chronological")
        if any(item.available_time.value > committed_at.value for item in records):
            raise PermissionError("forward commitment cannot include data unavailable at commitment time")
        acquired_cutoff = next(item for item in acquisition.records if item.instrument_id == instrument_id)
        if (
            artifacts[-1].content_sha256 != acquired_cutoff.record_sha256
            or records[-1].event_time != acquired_cutoff.event_time
        ):
            raise PermissionError("forward commitment cutoff is not the signed current-day record")
        screens = screen_hypothesis_families(
            records,
            signal_threshold=PIVOT_FORWARD_SIGNAL_THRESHOLD,
            per_signal_cost=PIVOT_FORWARD_PER_SIGNAL_COST,
        )
        stratum_scores = tuple(
            ForwardStratumScore(stratum, _decimal_text(score)) for stratum, score in replay_market_state_scores(records)
        )
        input_manifest_sha256s = tuple(item.dataset_manifest_sha256 for item in artifacts)
        input_record_sha256s = tuple(item.content_sha256 for item in artifacts)
        screen_sha256s = tuple(item.content_sha256 for item in screens)
        unsigned: dict[str, JsonValue] = {
            "collection_authority_id": self._authority_id,
            "protocol": PIVOT_FORWARD_PROTOCOL,
            "episode_id": str(episode_id),
            "instrument_id": instrument_id,
            "cutoff_trading_date": str(acquisition.trading_date),
            "cutoff_event_time": records[-1].event_time.to_dict()["recorded_at"],
            "committed_at": committed_at.to_dict()["recorded_at"],
            "acquisition_sha256": acquisition.content_sha256,
            "input_manifest_sha256s": input_manifest_sha256s,
            "input_record_sha256s": input_record_sha256s,
            "family_screen_sha256s": screen_sha256s,
            "stratum_scores": tuple(item.payload() for item in stratum_scores),
        }
        return ForwardEpisodeCommitment(
            self._authority_id,
            PIVOT_FORWARD_PROTOCOL,
            episode_id,
            instrument_id,
            acquisition.trading_date,
            records[-1].event_time,
            committed_at,
            acquisition.content_sha256,
            input_manifest_sha256s,
            input_record_sha256s,
            screen_sha256s,
            stratum_scores,
            self._sign(unsigned),
        )

    def verify_acquisition(self, acquisition: ForwardDailyAcquisition) -> None:
        if (
            type(acquisition) is not ForwardDailyAcquisition
            or acquisition.collection_authority_id != self._authority_id
        ):
            raise PermissionError("forward acquisition authority is not trusted")
        if not compare_digest(acquisition.signature_sha256, self._sign(acquisition.unsigned_payload())):
            raise PermissionError("forward acquisition signature is invalid")

    def verify_commitment(self, commitment: ForwardEpisodeCommitment) -> None:
        if type(commitment) is not ForwardEpisodeCommitment or commitment.collection_authority_id != self._authority_id:
            raise PermissionError("forward commitment authority is not trusted")
        if not compare_digest(commitment.signature_sha256, self._sign(commitment.unsigned_payload())):
            raise PermissionError("forward commitment signature is invalid")

    def _sign(self, payload: dict[str, JsonValue]) -> str:
        return hmac_new(self._signing_key, canonical_json_text(payload).encode(), sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ForwardRosterEntry:
    commitment: ForwardEpisodeCommitment
    stratum: EpisodeStratum

    def __post_init__(self) -> None:
        if type(self.commitment) is not ForwardEpisodeCommitment or type(self.stratum) is not EpisodeStratum:
            raise TypeError("forward roster entry requires a commitment and stratum")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "commitment_sha256": self.commitment.content_sha256,
            "commitment_signature_sha256": self.commitment.signature_sha256,
            "episode_id": str(self.commitment.episode_id),
            "instrument_id": self.commitment.instrument_id,
            "cutoff_trading_date": str(self.commitment.cutoff_trading_date),
            "stratum": self.stratum.value,
        }


@dataclass(frozen=True, slots=True)
class FrozenForwardRoster:
    roster_authority_id: str
    collection_authority_id: str
    protocol: str
    selection_rule: str
    candidate_pool_sha256: str
    frozen_at: RecordedAt
    entries: tuple[ForwardRosterEntry, ...]
    signature_sha256: str

    def __post_init__(self) -> None:
        _authority(self.roster_authority_id)
        _authority(self.collection_authority_id)
        if self.protocol != PIVOT_FORWARD_PROTOCOL or self.selection_rule != PIVOT_FORWARD_SELECTION_RULE:
            raise ValueError("forward roster requires the frozen protocol and selection rule")
        _digest(self.candidate_pool_sha256)
        _digest(self.signature_sha256)
        if type(self.frozen_at) is not RecordedAt or len(self.entries) != PIVOT_FORWARD_ROSTER_SIZE:
            raise ValueError("forward roster requires exactly fifty entries and a typed freeze time")
        if len({entry.commitment.episode_id for entry in self.entries}) != len(self.entries):
            raise ValueError("forward roster episode identities must be unique")
        if any(entry.commitment.committed_at.value > self.frozen_at.value for entry in self.entries):
            raise ValueError("forward roster cannot predate a selected commitment")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "roster_authority_id": self.roster_authority_id,
            "collection_authority_id": self.collection_authority_id,
            "protocol": self.protocol,
            "selection_rule": self.selection_rule,
            "candidate_pool_sha256": self.candidate_pool_sha256,
            "frozen_at": self.frozen_at.to_dict()["recorded_at"],
            "entries": tuple(item.payload() for item in self.entries),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())

    def entry(self, episode_id: EntityId) -> ForwardRosterEntry:
        matches = tuple(item for item in self.entries if item.commitment.episode_id == episode_id)
        if len(matches) != 1:
            raise KeyError("forward episode is absent from the frozen roster")
        return matches[0]


class ForwardRosterAuthority:
    """Freeze fifty commitments without accepting or inspecting any future reveal."""

    def __init__(
        self,
        authority_id: str,
        selection_key: bytes,
        collection_authority: ForwardCollectionAuthority,
    ) -> None:
        _authority(authority_id)
        _key(selection_key)
        if type(collection_authority) is not ForwardCollectionAuthority:
            raise TypeError("forward roster authority requires the trusted collection authority")
        self._authority_id = authority_id
        self._selection_key = selection_key
        self._collection_authority = collection_authority

    def freeze(
        self,
        commitments: tuple[ForwardEpisodeCommitment, ...],
        *,
        frozen_at: RecordedAt,
    ) -> FrozenForwardRoster:
        if type(commitments) is not tuple or len(commitments) < PIVOT_FORWARD_ROSTER_SIZE:
            raise ValueError("forward roster cannot freeze before fifty commitments exist")
        if type(frozen_at) is not RecordedAt:
            raise TypeError("forward roster freeze requires a typed timestamp")
        if any(type(item) is not ForwardEpisodeCommitment for item in commitments):
            raise TypeError("forward roster requires exact commitment contracts")
        for commitment in commitments:
            self._collection_authority.verify_commitment(commitment)
        if len({item.episode_id for item in commitments}) != len(commitments):
            raise ValueError("forward candidate commitment identities must be unique")
        if {item.instrument_id for item in commitments} != set(PIVOT_FORWARD_UNIVERSE):
            raise ValueError("forward candidate pool must cover the frozen universe")
        if any(item.committed_at.value > frozen_at.value for item in commitments):
            raise ValueError("forward roster cannot include a not-yet-committed episode")

        cells = tuple((instrument, stratum) for instrument in PIVOT_FORWARD_UNIVERSE for stratum in EpisodeStratum)
        instrument_base, instrument_extra = divmod(PIVOT_FORWARD_ROSTER_SIZE, len(PIVOT_FORWARD_UNIVERSE))
        ordered_instruments = tuple(sorted(PIVOT_FORWARD_UNIVERSE, key=lambda item: self._instrument_score(item)))
        instrument_quotas = {
            instrument: instrument_base + (1 if index < instrument_extra else 0)
            for index, instrument in enumerate(ordered_instruments)
        }
        quotas: dict[tuple[str, EpisodeStratum], int] = {}
        for instrument in PIVOT_FORWARD_UNIVERSE:
            stratum_base, stratum_extra = divmod(instrument_quotas[instrument], len(EpisodeStratum))
            ordered_strata = tuple(sorted(EpisodeStratum, key=lambda stratum: self._cell_score((instrument, stratum))))
            quotas.update(
                {
                    (instrument, stratum): stratum_base + (1 if index < stratum_extra else 0)
                    for index, stratum in enumerate(ordered_strata)
                }
            )
        selected: list[ForwardRosterEntry] = []
        used: set[EntityId] = set()
        for instrument, stratum in cells:
            eligible = tuple(
                item for item in commitments if item.instrument_id == instrument and item.episode_id not in used
            )
            quota = quotas[(instrument, stratum)]
            ranked = sorted(
                eligible,
                key=lambda item: (-item.score(stratum), self._commitment_score(item, stratum)),
            )
            if len(ranked) < quota:
                raise ValueError("forward candidate pool lacks a required instrument/stratum quota")
            for commitment in ranked[:quota]:
                used.add(commitment.episode_id)
                selected.append(ForwardRosterEntry(commitment, stratum))
        entries = tuple(sorted(selected, key=lambda item: self._entry_score(item)))
        pool_payload = tuple(
            {
                "commitment_sha256": item.content_sha256,
                "commitment_signature_sha256": item.signature_sha256,
            }
            for item in sorted(commitments, key=lambda value: value.content_sha256)
        )
        candidate_pool_sha256 = canonical_sha256(pool_payload)
        unsigned: dict[str, JsonValue] = {
            "roster_authority_id": self._authority_id,
            "collection_authority_id": self._collection_authority.authority_id,
            "protocol": PIVOT_FORWARD_PROTOCOL,
            "selection_rule": PIVOT_FORWARD_SELECTION_RULE,
            "candidate_pool_sha256": candidate_pool_sha256,
            "frozen_at": frozen_at.to_dict()["recorded_at"],
            "entries": tuple(item.payload() for item in entries),
        }
        return FrozenForwardRoster(
            self._authority_id,
            self._collection_authority.authority_id,
            PIVOT_FORWARD_PROTOCOL,
            PIVOT_FORWARD_SELECTION_RULE,
            candidate_pool_sha256,
            frozen_at,
            entries,
            self._sign(unsigned),
        )

    def verify(self, roster: FrozenForwardRoster) -> None:
        if type(roster) is not FrozenForwardRoster or roster.roster_authority_id != self._authority_id:
            raise PermissionError("forward roster authority is not trusted")
        if roster.collection_authority_id != self._collection_authority.authority_id:
            raise PermissionError("forward roster collection authority is not trusted")
        if not compare_digest(roster.signature_sha256, self._sign(roster.unsigned_payload())):
            raise PermissionError("forward roster signature is invalid")
        for entry in roster.entries:
            self._collection_authority.verify_commitment(entry.commitment)

    def _cell_score(self, cell: tuple[str, EpisodeStratum]) -> str:
        return hmac_new(self._selection_key, f"{cell[0]}:{cell[1].value}".encode(), sha256).hexdigest()

    def _instrument_score(self, instrument: str) -> str:
        return hmac_new(self._selection_key, instrument.encode(), sha256).hexdigest()

    def _commitment_score(self, commitment: ForwardEpisodeCommitment, stratum: EpisodeStratum) -> str:
        return hmac_new(
            self._selection_key,
            f"{commitment.content_sha256}:{stratum.value}".encode(),
            sha256,
        ).hexdigest()

    def _entry_score(self, entry: ForwardRosterEntry) -> str:
        return hmac_new(self._selection_key, canonical_json_text(entry.payload()).encode(), sha256).hexdigest()

    def _sign(self, payload: dict[str, JsonValue]) -> str:
        return hmac_new(self._selection_key, canonical_json_text(payload).encode(), sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ForwardLabelReveal:
    evaluator_authority_id: str
    protocol: str
    roster_sha256: str
    commitment_sha256: str
    instrument_id: str
    cutoff_event_time: RecordedAt
    revealed_at: RecordedAt
    acquisition_chain_sha256: str
    label_record_sha256s: tuple[str, ...]
    terminal_event_time: RecordedAt
    terminal_return: str
    terminal_direction: int
    signature_sha256: str

    def __post_init__(self) -> None:
        _authority(self.evaluator_authority_id)
        if self.protocol != PIVOT_FORWARD_PROTOCOL or self.instrument_id not in PIVOT_FORWARD_UNIVERSE:
            raise ValueError("forward reveal requires the frozen protocol and universe")
        for digest in (
            self.roster_sha256,
            self.commitment_sha256,
            self.acquisition_chain_sha256,
            self.signature_sha256,
            *self.label_record_sha256s,
        ):
            _digest(digest)
        if len(self.label_record_sha256s) != PIVOT_FORWARD_LABEL_BARS:
            raise ValueError("forward reveal requires the exact five-bar label path")
        if any(
            type(item) is not RecordedAt
            for item in (self.cutoff_event_time, self.revealed_at, self.terminal_event_time)
        ):
            raise TypeError("forward reveal requires typed timestamps")
        if not self.cutoff_event_time.value < self.terminal_event_time.value <= self.revealed_at.value:
            raise ValueError("forward reveal terminal time must follow cutoff and be available at reveal")
        terminal_return = _decimal(self.terminal_return, "forward terminal return")
        if self.terminal_direction != _sign(terminal_return):
            raise ValueError("forward reveal direction does not match terminal return")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "evaluator_authority_id": self.evaluator_authority_id,
            "protocol": self.protocol,
            "roster_sha256": self.roster_sha256,
            "commitment_sha256": self.commitment_sha256,
            "instrument_id": self.instrument_id,
            "cutoff_event_time": self.cutoff_event_time.to_dict()["recorded_at"],
            "revealed_at": self.revealed_at.to_dict()["recorded_at"],
            "acquisition_chain_sha256": self.acquisition_chain_sha256,
            "label_record_sha256s": self.label_record_sha256s,
            "terminal_event_time": self.terminal_event_time.to_dict()["recorded_at"],
            "terminal_return": self.terminal_return,
            "terminal_direction": self.terminal_direction,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())


class ForwardRevealAuthority:
    """Reveal only the next five signed acquisitions after a fifty-entry roster freeze."""

    def __init__(
        self,
        authority_id: str,
        signing_key: bytes,
        collection_authority: ForwardCollectionAuthority,
        roster_authority: ForwardRosterAuthority,
    ) -> None:
        _authority(authority_id)
        _key(signing_key)
        if (
            type(collection_authority) is not ForwardCollectionAuthority
            or type(roster_authority) is not ForwardRosterAuthority
        ):
            raise TypeError("forward evaluator requires trusted collection and roster authorities")
        self._authority_id = authority_id
        self._signing_key = signing_key
        self._collection_authority = collection_authority
        self._roster_authority = roster_authority

    def reveal(
        self,
        *,
        roster: FrozenForwardRoster,
        episode_id: EntityId,
        acquisition_chain: tuple[ForwardDailyAcquisition, ...],
        cutoff_artifact: PitArtifactRecord,
        label_artifacts: tuple[PitArtifactRecord, ...],
        revealed_at: RecordedAt,
    ) -> ForwardLabelReveal:
        self._roster_authority.verify(roster)
        entry = roster.entry(episode_id)
        commitment = entry.commitment
        if len(acquisition_chain) != PIVOT_FORWARD_LABEL_BARS + 1:
            raise ValueError("forward reveal requires cutoff acquisition plus the next five signed acquisitions")
        for acquisition in acquisition_chain:
            self._collection_authority.verify_acquisition(acquisition)
        if acquisition_chain[0].content_sha256 != commitment.acquisition_sha256:
            raise PermissionError("forward reveal chain does not start at the committed cutoff")
        if commitment.committed_at.value >= acquisition_chain[1].recorded_at.value:
            raise PermissionError("forward commitment was not frozen before the first label acquisition")
        for previous, current in zip(acquisition_chain, acquisition_chain[1:]):
            if (
                current.sequence_number != previous.sequence_number + 1
                or current.previous_acquisition_sha256 != previous.content_sha256
            ):
                raise PermissionError("forward reveal acquisition chain is not contiguous")
        if type(cutoff_artifact) is not PitArtifactRecord or cutoff_artifact.instrument_id != commitment.instrument_id:
            raise TypeError("forward reveal requires the exact cutoff artifact")
        if cutoff_artifact.content_sha256 != commitment.input_record_sha256s[-1]:
            raise PermissionError("forward reveal cutoff artifact does not match the commitment")
        if len(label_artifacts) != PIVOT_FORWARD_LABEL_BARS or any(
            type(item) is not PitArtifactRecord for item in label_artifacts
        ):
            raise ValueError("forward reveal requires five authorized label artifacts")
        if any(item.instrument_id != commitment.instrument_id for item in label_artifacts):
            raise PermissionError("forward label path cannot cross instruments")
        records = tuple(item.record for item in label_artifacts)
        if tuple(sorted(records, key=lambda item: item.event_time.value)) != records or len(
            {item.event_time for item in records}
        ) != len(records):
            raise ValueError("forward label path must be unique and chronological")
        if records[0].event_time.value <= commitment.cutoff_event_time.value:
            raise ValueError("forward label path must follow the committed cutoff")
        if type(revealed_at) is not RecordedAt or any(
            item.available_time.value > revealed_at.value for item in records
        ):
            raise PermissionError("forward label path is not fully available at reveal time")
        for acquisition, artifact in zip(acquisition_chain[1:], label_artifacts, strict=True):
            acquired = next(item for item in acquisition.records if item.instrument_id == commitment.instrument_id)
            if (
                acquired.record_sha256 != artifact.content_sha256
                or acquired.dataset_manifest_sha256 != artifact.dataset_manifest_sha256
                or acquired.event_time != artifact.record.event_time
                or acquired.available_time != artifact.record.available_time
            ):
                raise PermissionError("forward label artifact does not match the next signed acquisition")
        cutoff_close = _close(cutoff_artifact.record)
        terminal_return = (_close(records[-1]) / cutoff_close - 1).quantize(Decimal("0.00000001"))
        chain_sha256 = canonical_sha256(tuple(item.content_sha256 for item in acquisition_chain))
        record_sha256s = tuple(item.content_sha256 for item in label_artifacts)
        unsigned: dict[str, JsonValue] = {
            "evaluator_authority_id": self._authority_id,
            "protocol": PIVOT_FORWARD_PROTOCOL,
            "roster_sha256": roster.content_sha256,
            "commitment_sha256": commitment.content_sha256,
            "instrument_id": commitment.instrument_id,
            "cutoff_event_time": commitment.cutoff_event_time.to_dict()["recorded_at"],
            "revealed_at": revealed_at.to_dict()["recorded_at"],
            "acquisition_chain_sha256": chain_sha256,
            "label_record_sha256s": record_sha256s,
            "terminal_event_time": records[-1].event_time.to_dict()["recorded_at"],
            "terminal_return": _decimal_text(terminal_return),
            "terminal_direction": _sign(terminal_return),
        }
        return ForwardLabelReveal(
            self._authority_id,
            PIVOT_FORWARD_PROTOCOL,
            roster.content_sha256,
            commitment.content_sha256,
            commitment.instrument_id,
            commitment.cutoff_event_time,
            revealed_at,
            chain_sha256,
            record_sha256s,
            records[-1].event_time,
            _decimal_text(terminal_return),
            _sign(terminal_return),
            self._sign(unsigned),
        )

    def verify(self, reveal: ForwardLabelReveal) -> None:
        if type(reveal) is not ForwardLabelReveal or reveal.evaluator_authority_id != self._authority_id:
            raise PermissionError("forward reveal authority is not trusted")
        if not compare_digest(reveal.signature_sha256, self._sign(reveal.unsigned_payload())):
            raise PermissionError("forward reveal signature is invalid")

    def _sign(self, payload: dict[str, JsonValue]) -> str:
        return hmac_new(self._signing_key, canonical_json_text(payload).encode(), sha256).hexdigest()


def _close(record: PointInTimeRecord) -> Decimal:
    value = record.values.get("close")
    if type(value) is not str:
        raise ValueError("forward scoring requires canonical close text")
    return _decimal(value, "forward close")


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _decimal(value: str, name: str) -> Decimal:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be canonical decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be canonical decimal text") from error
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise ValueError(f"{name} must be finite canonical decimal text")
    return parsed


def _authority(value: str) -> None:
    if type(value) is not str or not _CANONICAL_AUTHORITY.fullmatch(value):
        raise ValueError("forward authority requires a canonical identity")


def _key(value: bytes) -> None:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError("forward authority requires at least 256 bits of key material")


def _digest(value: str) -> None:
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("forward digest must be 64 lowercase hexadecimal characters")
