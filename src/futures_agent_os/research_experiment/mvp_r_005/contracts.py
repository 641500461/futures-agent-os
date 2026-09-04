"""Contracts for the MVP-R-005 research decision brief. Does not mutate R-003/R-004 Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from futures_agent_os.research_experiment.mvp_r_003.contracts import FinalVerdict
from futures_agent_os.shared_kernel.observability import JsonValue

FOLD_SIGNAL_ACCURACY_FIELDS = (
    "fold_1_signal_accuracy",
    "fold_2_signal_accuracy",
    "fold_3_signal_accuracy",
)
FOLD_SIGNAL_COUNT_FIELDS = (
    "fold_1_signal_count",
    "fold_2_signal_count",
    "fold_3_signal_count",
)
AGENT_LOOP_ARM = "research_agent_loop"
SINGLE_PROMPT_ARM = "single_prompt_analyst"
FALSIFICATION_REQUIRES_FOLD_ACCURACY = (
    "reject if signal_accuracy does not beat counterfactual_signal_accuracy, "
    "or stressed_net_return does not beat counterfactual_stressed_net_return, "
    "or any of fold_1_signal_accuracy, fold_2_signal_accuracy, fold_3_signal_accuracy "
    "is missing, has fold signal_count 0, or is at or below 0.50. "
    "positive_fold_ratio is net-positive fold share and must not substitute per-fold signal_accuracy"
)


@dataclass(frozen=True, slots=True)
class DecisionBrief:
    what_was_tested: str
    results: str
    current_judgment: str
    next_action: str
    verdict: FinalVerdict

    def __post_init__(self) -> None:
        values = (self.what_was_tested, self.results, self.current_judgment, self.next_action)
        if any(type(value) is not str or not value.strip() for value in values):
            raise ValueError("decision brief requires four non-empty text blocks")
        if type(self.verdict) is not FinalVerdict:
            raise TypeError("decision brief requires a typed final verdict")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "what_was_tested": self.what_was_tested,
            "results": self.results,
            "current_judgment": self.current_judgment,
            "next_action": self.next_action,
            "verdict": self.verdict.value,
        }

    @classmethod
    def hydrate(cls, value: object) -> DecisionBrief:
        if type(value) is not dict:
            raise TypeError("decision brief must be an object")
        expected = {"what_was_tested", "results", "current_judgment", "next_action", "verdict"}
        if set(value) != expected:
            raise ValueError("decision brief fields must match the closed schema")
        fields = tuple(value[name] for name in ("what_was_tested", "results", "current_judgment", "next_action"))
        if any(type(item) is not str for item in fields) or type(value["verdict"]) is not str:
            raise TypeError("decision brief fields must be strings")
        return cls(
            cast(str, value["what_was_tested"]),
            cast(str, value["results"]),
            cast(str, value["current_judgment"]),
            cast(str, value["next_action"]),
            FinalVerdict(value["verdict"]),
        )


@dataclass(frozen=True, slots=True)
class ShadowCritique:
    risk_notes: tuple[str, ...]
    would_have_blocked_experiment: bool

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "risk_notes": self.risk_notes,
            "would_have_blocked_experiment": self.would_have_blocked_experiment,
            "blocked_experiment": False,
        }
