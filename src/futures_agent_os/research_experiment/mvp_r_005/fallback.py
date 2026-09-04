"""Single-prompt fallback hypothesis. Template is not a product arm."""

from __future__ import annotations

from dataclasses import replace

from futures_agent_os.research_experiment.mvp_r_003.contracts import HypothesisSpec, ResearchEpisodeInput
from futures_agent_os.research_experiment.mvp_r_004.gold_labels import gold_cases

from .predicate import bind_falsification_condition, default_fallback_predicate


def fallback_hypothesis(episode: ResearchEpisodeInput, threshold: str) -> HypothesisSpec:
    clean, _unused = gold_cases(episode, threshold)
    return replace(
        clean.hypothesis,
        hypothesis_id=f"{episode.episode_id}-fallback",
        falsification_condition=bind_falsification_condition(default_fallback_predicate()),
    )
