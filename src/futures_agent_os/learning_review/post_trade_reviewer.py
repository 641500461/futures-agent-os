"""Independent post-trade review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .projection_contracts import SourceEvent, TradeEpisode


class ReviewQuality(StrEnum):
    GOOD = "GOOD"
    MIXED = "MIXED"
    POOR = "POOR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TradeReview:
    episode_id: str
    process_quality: ReviewQuality
    outcome_quality: ReviewQuality
    execution_quality: ReviewQuality
    evidence_refs: tuple[str, ...]
    findings: tuple[str, ...]
    market_path_quality: ReviewQuality = ReviewQuality.UNKNOWN
    verifiable_cause_hypotheses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.episode_id or not self.evidence_refs or not self.findings:
            raise ValueError("trade review requires a closed episode, evidence and findings")
        if type(self.market_path_quality) is not ReviewQuality or any(
            type(x) is not str or not x.strip() for x in self.verifiable_cause_hypotheses
        ):
            raise ValueError("review hypotheses must be typed, non-empty strings")


@dataclass(frozen=True, slots=True)
class Reflection:
    episode_id: str
    observation: str
    lesson_candidate: str | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.episode_id or not self.observation or not self.evidence_refs:
            raise ValueError("reflection requires episode, observation and evidence")


class PostTradeReviewer:
    @staticmethod
    def _validate_sources(source_event_refs: tuple[str, ...]) -> None:
        required = {"decision", "execution", "accounting"}
        kinds = {ref.split(":", 1)[0].lower() for ref in source_event_refs}
        if not required.issubset(kinds):
            raise ValueError("review requires decision, execution and accounting source events")

    def review_episode(
        self,
        *,
        episode_id: str,
        closed: bool,
        process_quality: ReviewQuality,
        outcome_quality: ReviewQuality,
        execution_quality: ReviewQuality,
        source_event_refs: tuple[str, ...],
        findings: tuple[str, ...],
        market_path_quality: ReviewQuality = ReviewQuality.UNKNOWN,
        verifiable_cause_hypotheses: tuple[str, ...] = (),
    ) -> TradeReview:
        """Build a review only from a closed, reconstructible episode."""
        if not closed:
            raise ValueError("review requires a closed trade episode")
        self._validate_sources(source_event_refs)
        return self.review(
            episode_id=episode_id,
            closed=True,
            process_quality=process_quality,
            outcome_quality=outcome_quality,
            execution_quality=execution_quality,
            evidence_refs=source_event_refs,
            findings=findings,
            market_path_quality=market_path_quality,
            verifiable_cause_hypotheses=verifiable_cause_hypotheses,
        )

    def review_trade_episode(
        self,
        *,
        episode: TradeEpisode,
        sources: tuple[SourceEvent, ...],
        closed: bool,
        process_quality: ReviewQuality,
        outcome_quality: ReviewQuality,
        execution_quality: ReviewQuality,
        findings: tuple[str, ...],
        market_path_quality: ReviewQuality = ReviewQuality.UNKNOWN,
    ) -> TradeReview:
        """Review only a closed projection whose complete source set matches."""
        if not closed:
            raise ValueError("review requires a closed trade episode")
        source_by_id = {source.event_id: source for source in sources}
        if set(source_by_id) != set(episode.source_event_ids):
            raise ValueError("trade episode sources do not match the episode projection")
        refs = tuple(f"{source.event_type.lower()}:{source.event_id.value}" for source in sources)
        return self.review_episode(
            episode_id=episode.episode_id.value.__str__(),
            closed=True,
            process_quality=process_quality,
            outcome_quality=outcome_quality,
            execution_quality=execution_quality,
            source_event_refs=refs,
            findings=findings,
            market_path_quality=market_path_quality,
        )

    def review(
        self,
        *,
        episode_id: str,
        closed: bool,
        process_quality: ReviewQuality,
        outcome_quality: ReviewQuality,
        execution_quality: ReviewQuality,
        evidence_refs: tuple[str, ...],
        findings: tuple[str, ...],
        market_path_quality: ReviewQuality = ReviewQuality.UNKNOWN,
        verifiable_cause_hypotheses: tuple[str, ...] = (),
    ) -> TradeReview:
        if not closed:
            raise ValueError("review requires a closed trade episode")
        self._validate_sources(evidence_refs)
        return TradeReview(
            episode_id,
            process_quality,
            outcome_quality,
            execution_quality,
            evidence_refs,
            findings,
            market_path_quality,
            verifiable_cause_hypotheses,
        )

    def reflect(self, *, review: TradeReview, observation: str, lesson_candidate: str | None = None) -> Reflection:
        return Reflection(review.episode_id, observation, lesson_candidate, review.evidence_refs)
