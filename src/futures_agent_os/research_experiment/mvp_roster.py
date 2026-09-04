"""Keyed, stratified pre-run episode roster freezing for MVP-R."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest, new as hmac_new

from futures_agent_os.research_experiment.mvp_validation import EpisodeDefinition, EpisodePhase, EvaluationSuite
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


MVP_R_EPISODE_SELECTION_RULE = "composite-stratified-hmac-sha256.v1"


class EpisodeStratum(StrEnum):
    UP_TREND = "UP_TREND"
    DOWN_TREND = "DOWN_TREND"
    RANGE = "RANGE"
    REVERSAL = "REVERSAL"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    NOISE = "NOISE"


@dataclass(frozen=True, slots=True)
class EpisodeRosterCandidate:
    episode: EpisodeDefinition
    stratum: EpisodeStratum

    def __post_init__(self) -> None:
        if type(self.episode) is not EpisodeDefinition or type(self.stratum) is not EpisodeStratum:
            raise TypeError("roster candidate requires an exact episode and stratum")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "episode_id": str(self.episode.episode_id),
            "suite_sha256": self.episode.suite_sha256,
            "phase": self.episode.phase.value,
            "mode": self.episode.mode.value,
            "instrument_id": self.episode.instrument_id,
            "as_of": self.episode.as_of.to_dict()["recorded_at"],
            "market_cutoff": self.episode.market_cutoff.to_dict()["recorded_at"],
            "future_reveal_at": self.episode.future_reveal_at.to_dict()["recorded_at"],
            "input_artifact_sha256s": self.episode.input_artifact_sha256s,
            "stratum": self.stratum.value,
        }


@dataclass(frozen=True, slots=True)
class FrozenEpisodeRoster:
    authority_id: str
    suite_sha256: str
    phase: EpisodePhase
    selection_rule: str
    candidate_pool_sha256: str
    selected: tuple[EpisodeRosterCandidate, ...]
    signature_sha256: str

    def __post_init__(self) -> None:
        if not self.authority_id.strip() or self.selection_rule != MVP_R_EPISODE_SELECTION_RULE:
            raise ValueError("frozen episode roster requires authority and the pinned selection rule")
        if type(self.phase) is not EpisodePhase or not self.selected:
            raise ValueError("frozen episode roster requires phase and selected episodes")
        _digest(self.suite_sha256)
        _digest(self.candidate_pool_sha256)
        _digest(self.signature_sha256)
        if len({candidate.episode.episode_id for candidate in self.selected}) != len(self.selected):
            raise ValueError("frozen episode roster episodes must be unique")
        if any(
            candidate.episode.suite_sha256 != self.suite_sha256 or candidate.episode.phase is not self.phase
            for candidate in self.selected
        ):
            raise ValueError("frozen episode roster contains a mismatched episode")

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "suite_sha256": self.suite_sha256,
            "phase": self.phase.value,
            "selection_rule": self.selection_rule,
            "candidate_pool_sha256": self.candidate_pool_sha256,
            "selected": tuple(candidate.payload() for candidate in self.selected),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())

    def episode(self, episode_id: str) -> EpisodeDefinition:
        matches = tuple(
            candidate.episode for candidate in self.selected if str(candidate.episode.episode_id) == episode_id
        )
        if len(matches) != 1:
            raise KeyError("episode is absent from the frozen roster")
        return matches[0]


class EpisodeRosterAuthority:
    """Select and sign a balanced roster without exposing the selection key."""

    def __init__(self, authority_id: str, selection_key: bytes) -> None:
        if not authority_id.strip() or len(selection_key) < 32:
            raise ValueError("roster authority requires identity and a 256-bit selection key")
        self._authority_id = authority_id
        self._selection_key = selection_key

    def freeze(
        self,
        suite: EvaluationSuite,
        phase: EpisodePhase,
        candidates: tuple[EpisodeRosterCandidate, ...],
    ) -> FrozenEpisodeRoster:
        if type(suite) is not EvaluationSuite or type(phase) is not EpisodePhase or type(candidates) is not tuple:
            raise TypeError("roster freeze requires exact suite, phase, and tuple candidates")
        if phase not in {EpisodePhase.DIAGNOSTIC, EpisodePhase.HOLDOUT}:
            raise ValueError("only diagnostic and holdout episodes can be pre-run rosters")
        if suite.episode_selection_rule != MVP_R_EPISODE_SELECTION_RULE:
            raise ValueError("suite episode selection rule does not match the roster implementation")
        if not candidates or any(type(candidate) is not EpisodeRosterCandidate for candidate in candidates):
            raise ValueError("roster freeze requires typed candidates")
        if len({candidate.episode.episode_id for candidate in candidates}) != len(candidates):
            raise ValueError("roster candidate episode identities must be unique")
        for candidate in candidates:
            if candidate.episode.suite_sha256 != suite.content_sha256 or candidate.episode.phase is not phase:
                raise PermissionError("roster candidate is outside the frozen suite or phase")
        if {candidate.episode.instrument_id for candidate in candidates} != set(suite.instrument_universe):
            raise ValueError("roster candidate pool must cover the complete suite universe")

        count = suite.diagnostic_episode_count if phase is EpisodePhase.DIAGNOSTIC else suite.holdout_episode_count
        cells = tuple(
            (instrument, stratum) for instrument in sorted(suite.instrument_universe) for stratum in EpisodeStratum
        )
        base, extra = divmod(count, len(cells))
        ordered_cells = tuple(sorted(cells, key=self._cell_score))
        quotas = {cell: base + (1 if index < extra else 0) for index, cell in enumerate(ordered_cells)}
        selected: list[EpisodeRosterCandidate] = []
        for cell in cells:
            eligible = tuple(
                candidate for candidate in candidates if (candidate.episode.instrument_id, candidate.stratum) == cell
            )
            quota = quotas[cell]
            if len(eligible) < quota:
                raise ValueError("roster candidate pool lacks a required instrument/stratum quota")
            selected.extend(sorted(eligible, key=self._candidate_score)[:quota])
        selected_tuple = tuple(sorted(selected, key=self._candidate_score))
        pool_payload = tuple(candidate.payload() for candidate in sorted(candidates, key=_canonical_candidate_key))
        unsigned: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "suite_sha256": suite.content_sha256,
            "phase": phase.value,
            "selection_rule": MVP_R_EPISODE_SELECTION_RULE,
            "candidate_pool_sha256": canonical_sha256(pool_payload),
            "selected": tuple(candidate.payload() for candidate in selected_tuple),
        }
        return FrozenEpisodeRoster(
            self._authority_id,
            suite.content_sha256,
            phase,
            MVP_R_EPISODE_SELECTION_RULE,
            canonical_sha256(pool_payload),
            selected_tuple,
            self._sign(unsigned),
        )

    def verify(self, roster: FrozenEpisodeRoster) -> None:
        if type(roster) is not FrozenEpisodeRoster or roster.authority_id != self._authority_id:
            raise PermissionError("episode roster authority is not trusted")
        if not compare_digest(roster.signature_sha256, self._sign(roster.unsigned_payload())):
            raise PermissionError("episode roster signature is invalid")

    def _candidate_score(self, candidate: EpisodeRosterCandidate) -> str:
        return hmac_new(
            self._selection_key,
            canonical_json_text(candidate.payload()).encode(),
            sha256,
        ).hexdigest()

    def _cell_score(self, cell: tuple[str, EpisodeStratum]) -> str:
        return hmac_new(
            self._selection_key,
            f"{cell[0]}:{cell[1].value}".encode(),
            sha256,
        ).hexdigest()

    def _sign(self, payload: dict[str, JsonValue]) -> str:
        return hmac_new(self._selection_key, canonical_json_text(payload).encode(), sha256).hexdigest()


def _canonical_candidate_key(candidate: EpisodeRosterCandidate) -> str:
    return canonical_json_text(candidate.payload())


def _digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("roster digest must be 64 lowercase hexadecimal characters")
