"""Machine-consumable non-trading handoff for the MVP-R multi-family Pivot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_handoff import ResearchHandoffDecision
from .mvp_pivot import (
    PIVOT_HYPOTHESIS_FAMILIES,
    HypothesisFamilyScreen,
    PivotDeterministicCritique,
)
from .mvp_pivot_critic import PivotCriticDecision, PivotCriticRequest, PivotCriticReview
from .mvp_validation import AgentEpisodeView, HypothesisFamily, ModelRunRecord, ResearchConclusionKind


PIVOT_HANDOFF_SCHEMA = "mvp-r.pivot-machine-handoff.v1"


@dataclass(frozen=True, slots=True)
class PivotNextExperimentRequest:
    request_status: str
    hypothesis_family: HypothesisFamily
    cutoff_direction: int
    algorithm_revision: str
    window_bars: int
    embargo_bars: int
    evaluator_reveal_bars: int
    independent_forward_data_required: bool

    def __post_init__(self) -> None:
        if self.request_status not in {"READY", "NOT_REQUESTED"}:
            raise ValueError("Pivot next experiment requires a closed request status")
        if type(self.hypothesis_family) is not HypothesisFamily or self.cutoff_direction not in {-1, 0, 1}:
            raise ValueError("Pivot next experiment requires family and direction")
        if (
            not self.algorithm_revision.strip()
            or min(self.window_bars, self.embargo_bars, self.evaluator_reveal_bars) < 1
        ):
            raise ValueError("Pivot next experiment requires frozen positive horizons")
        if type(self.independent_forward_data_required) is not bool:
            raise TypeError("Pivot next experiment forward-data flag must be exact boolean")
        if self.request_status == "READY" and (
            self.hypothesis_family not in PIVOT_HYPOTHESIS_FAMILIES
            or not self.cutoff_direction
            or not self.independent_forward_data_required
        ):
            raise ValueError("ready Pivot experiments require a directional family and new forward data")
        if self.request_status == "NOT_REQUESTED" and (
            self.hypothesis_family is not HypothesisFamily.NONE or self.cutoff_direction
        ):
            raise ValueError("non-requested Pivot experiments cannot retain a direction")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "request_status": self.request_status,
            "hypothesis_family": self.hypothesis_family.value,
            "cutoff_direction": self.cutoff_direction,
            "algorithm_revision": self.algorithm_revision,
            "window_bars": self.window_bars,
            "embargo_bars": self.embargo_bars,
            "evaluator_reveal_bars": self.evaluator_reveal_bars,
            "independent_forward_data_required": self.independent_forward_data_required,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> PivotNextExperimentRequest:
        expected = {
            "request_status",
            "hypothesis_family",
            "cutoff_direction",
            "algorithm_revision",
            "window_bars",
            "embargo_bars",
            "evaluator_reveal_bars",
            "independent_forward_data_required",
        }
        if set(value) != expected:
            raise ValueError("Pivot next experiment has unexpected fields")
        return cls(
            _text(value["request_status"]),
            HypothesisFamily(_text(value["hypothesis_family"])),
            _integer(value["cutoff_direction"]),
            _text(value["algorithm_revision"]),
            _integer(value["window_bars"]),
            _integer(value["embargo_bars"]),
            _integer(value["evaluator_reveal_bars"]),
            _boolean(value["independent_forward_data_required"]),
        )


@dataclass(frozen=True, slots=True)
class PivotMachineResearchHandoff:
    schema_version: str
    episode_id: str
    run_id: str
    instrument_id: str
    proposal_sha256: str
    feature_evidence_sha256: str
    deterministic_critique_sha256: str
    independent_critic_review_sha256: str | None
    decision: ResearchHandoffDecision
    selected_family: HypothesisFamily
    cutoff_direction: int
    family_screens: tuple[HypothesisFamilyScreen, ...]
    tradable: bool
    approximate_backtest_only: bool
    next_experiment: PivotNextExperimentRequest
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != PIVOT_HANDOFF_SCHEMA:
            raise ValueError("Pivot handoff requires its exact schema")
        if not self.episode_id.strip() or not self.run_id.strip() or not self.instrument_id.strip():
            raise ValueError("Pivot handoff requires episode, run, and instrument")
        for digest in (
            self.proposal_sha256,
            self.feature_evidence_sha256,
            self.deterministic_critique_sha256,
        ):
            _digest(digest)
        if self.independent_critic_review_sha256 is not None:
            _digest(self.independent_critic_review_sha256)
        if type(self.decision) is not ResearchHandoffDecision or type(self.selected_family) is not HypothesisFamily:
            raise TypeError("Pivot handoff requires closed decision and family types")
        if tuple(screen.family for screen in self.family_screens) != PIVOT_HYPOTHESIS_FAMILIES:
            raise ValueError("Pivot handoff requires the complete frozen family roster")
        if self.tradable or not self.approximate_backtest_only:
            raise PermissionError("Pivot handoff is research-only and approximate")
        if self.decision is ResearchHandoffDecision.CONTINUE_TEST:
            if (
                self.selected_family not in PIVOT_HYPOTHESIS_FAMILIES
                or not self.cutoff_direction
                or self.independent_critic_review_sha256 is None
                or self.next_experiment.request_status != "READY"
            ):
                raise ValueError("advancing Pivot handoffs require both critics and a ready experiment")
        elif self.next_experiment.request_status != "NOT_REQUESTED":
            raise ValueError("non-advancing Pivot handoffs cannot schedule an experiment")
        if canonical_sha256(self.payload()) != self.content_sha256:
            raise ValueError("Pivot handoff digest must bind the exact payload")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "proposal_sha256": self.proposal_sha256,
            "feature_evidence_sha256": self.feature_evidence_sha256,
            "deterministic_critique_sha256": self.deterministic_critique_sha256,
            "independent_critic_review_sha256": self.independent_critic_review_sha256,
            "decision": self.decision.value,
            "selected_family": self.selected_family.value,
            "cutoff_direction": self.cutoff_direction,
            "family_screens": tuple(screen.payload() for screen in self.family_screens),
            "tradable": self.tradable,
            "approximate_backtest_only": self.approximate_backtest_only,
            "next_experiment": self.next_experiment.payload(),
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {**self.payload(), "content_sha256": self.content_sha256}

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> PivotMachineResearchHandoff:
        expected = {
            "schema_version",
            "episode_id",
            "run_id",
            "instrument_id",
            "proposal_sha256",
            "feature_evidence_sha256",
            "deterministic_critique_sha256",
            "independent_critic_review_sha256",
            "decision",
            "selected_family",
            "cutoff_direction",
            "family_screens",
            "tradable",
            "approximate_backtest_only",
            "next_experiment",
            "content_sha256",
        }
        if set(value) != expected:
            raise ValueError("Pivot handoff has unexpected fields")
        screens = value["family_screens"]
        if type(screens) not in {tuple, list}:
            raise TypeError("Pivot handoff screens must be a sequence")
        return cls(
            _text(value["schema_version"]),
            _text(value["episode_id"]),
            _text(value["run_id"]),
            _text(value["instrument_id"]),
            _text(value["proposal_sha256"]),
            _text(value["feature_evidence_sha256"]),
            _text(value["deterministic_critique_sha256"]),
            _optional_text(value["independent_critic_review_sha256"]),
            ResearchHandoffDecision(_text(value["decision"])),
            HypothesisFamily(_text(value["selected_family"])),
            _integer(value["cutoff_direction"]),
            tuple(_screen(_mapping(item)) for item in cast(tuple[object, ...] | list[object], screens)),
            _boolean(value["tradable"]),
            _boolean(value["approximate_backtest_only"]),
            PivotNextExperimentRequest.hydrate(_mapping(value["next_experiment"])),
            _text(value["content_sha256"]),
        )


def build_pivot_machine_handoff(
    *,
    episode: AgentEpisodeView,
    run: ModelRunRecord,
    screens: tuple[HypothesisFamilyScreen, ...],
    feature_evidence_sha256: str,
    deterministic_critique: PivotDeterministicCritique,
    critic_request: PivotCriticRequest | None,
    critic_review: PivotCriticReview | None,
) -> PivotMachineResearchHandoff:
    if run.conclusion is None or run.conclusion.hypothesis is None:
        raise ValueError("Pivot handoff requires a completed hypothesis proposal")
    if run.episode_id != episode.episode_id:
        raise PermissionError("Pivot handoff cannot cross episodes")
    _digest(feature_evidence_sha256)
    family = run.conclusion.hypothesis.family
    selected = next((screen for screen in screens if screen.family is family), None)
    independent_accepted = False
    if critic_request is not None or critic_review is not None:
        if type(critic_request) is not PivotCriticRequest or type(critic_review) is not PivotCriticReview:
            raise ValueError("Pivot handoff requires both independent Critic request and review")
        critic_review.verify_request(critic_request)
        if critic_request.episode_id != str(episode.episode_id):
            raise PermissionError("Pivot handoff Critic request crossed episodes")
        independent_accepted = critic_review.decision is PivotCriticDecision.ACCEPT
    advance = bool(
        run.conclusion.kind is ResearchConclusionKind.OPPORTUNITY_CANDIDATE
        and deterministic_critique.accepted
        and independent_accepted
        and selected is not None
        and selected.cutoff_direction
    )
    decision = (
        ResearchHandoffDecision.CONTINUE_TEST
        if advance
        else ResearchHandoffDecision.DEFER
        if run.conclusion.kind is ResearchConclusionKind.DEFER
        else ResearchHandoffDecision.DO_NOT_ADVANCE
    )
    experiment = PivotNextExperimentRequest(
        "READY" if advance else "NOT_REQUESTED",
        family if advance else HypothesisFamily.NONE,
        selected.cutoff_direction if advance and selected is not None else 0,
        "mvp-r.multi-family-screen.v1",
        40,
        5,
        5,
        True,
    )
    payload: dict[str, JsonValue] = {
        "schema_version": PIVOT_HANDOFF_SCHEMA,
        "episode_id": str(episode.episode_id),
        "run_id": str(run.run_id),
        "instrument_id": episode.instrument_id,
        "proposal_sha256": canonical_sha256(run.conclusion.to_dict()),
        "feature_evidence_sha256": feature_evidence_sha256,
        "deterministic_critique_sha256": deterministic_critique.content_sha256,
        "independent_critic_review_sha256": critic_review.content_sha256 if critic_review is not None else None,
        "decision": decision.value,
        "selected_family": family.value if advance else HypothesisFamily.NONE.value,
        "cutoff_direction": selected.cutoff_direction if advance and selected is not None else 0,
        "family_screens": tuple(screen.payload() for screen in screens),
        "tradable": False,
        "approximate_backtest_only": True,
        "next_experiment": experiment.payload(),
    }
    return PivotMachineResearchHandoff(
        PIVOT_HANDOFF_SCHEMA,
        str(episode.episode_id),
        str(run.run_id),
        episode.instrument_id,
        canonical_sha256(run.conclusion.to_dict()),
        feature_evidence_sha256,
        deterministic_critique.content_sha256,
        critic_review.content_sha256 if critic_review is not None else None,
        decision,
        family if advance else HypothesisFamily.NONE,
        selected.cutoff_direction if advance and selected is not None else 0,
        screens,
        False,
        True,
        experiment,
        canonical_sha256(payload),
    )


def _screen(value: Mapping[str, object]) -> HypothesisFamilyScreen:
    expected = {
        "family",
        "cutoff_direction",
        "signal_count",
        "signal_accuracy",
        "net_return",
        "stressed_net_return",
        "positive_fold_ratio",
    }
    if set(value) != expected:
        raise ValueError("Pivot family screen has unexpected fields")
    from decimal import Decimal

    return HypothesisFamilyScreen(
        HypothesisFamily(_text(value["family"])),
        _integer(value["cutoff_direction"]),
        _integer(value["signal_count"]),
        Decimal(_text(value["signal_accuracy"])),
        Decimal(_text(value["net_return"])),
        Decimal(_text(value["stressed_net_return"])),
        Decimal(_text(value["positive_fold_ratio"])),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("Pivot handoff object must be string-keyed")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise TypeError("Pivot handoff value must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError("Pivot handoff integer must be exact")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("Pivot handoff boolean must be exact")
    return value


def _digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Pivot handoff digest must be lowercase SHA-256")


__all__ = [
    "PIVOT_HANDOFF_SCHEMA",
    "PivotMachineResearchHandoff",
    "PivotNextExperimentRequest",
    "build_pivot_machine_handoff",
]
