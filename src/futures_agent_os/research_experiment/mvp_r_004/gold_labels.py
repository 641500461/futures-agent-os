"""Gold-label clean/bad hypotheses used for Critic retention and recall."""

from __future__ import annotations

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    HypothesisFamily,
    HypothesisSpec,
    ResearchEpisodeInput,
    SignalOperator,
)
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum

from .contracts import GoldHypothesisCase, GoldLabel, PACKET_CONTROL


_TREND_STATES = {EpisodeStratum.UP_TREND.value, EpisodeStratum.DOWN_TREND.value}


def gold_cases(episode: ResearchEpisodeInput, threshold: str) -> tuple[GoldHypothesisCase, GoldHypothesisCase]:
    continuation = episode.market_state in _TREND_STATES
    clean = HypothesisSpec(
        hypothesis_id=f"{episode.episode_id}-gold-clean",
        version=1,
        family=HypothesisFamily.MOMENTUM_CONTINUATION if continuation else HypothesisFamily.FALSE_BREAKOUT_REVERSAL,
        market_condition=episode.market_state,
        signal_operator=SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,
        parameters=(
            ("direction", "FOLLOW" if continuation else "INVERT"),
            ("threshold", threshold),
        ),
        expected_observable="registered direction beats the inverted-direction control on ResultPacket metrics",
        falsification_condition=(
            "reject if signal_accuracy does not beat counterfactual_signal_accuracy, "
            "or stressed_net_return does not beat counterfactual_stressed_net_return, "
            "or positive_fold_ratio is below 0.5"
        ),
        supporting_evidence_refs=(episode.feature_ref.uri, episode.market_snapshot_ref.uri),
        strongest_counter_evidence_refs=(episode.market_snapshot_ref.uri,),
        unknowns=episode.unknowns,
        primary_metric="signal_accuracy",
        control=PACKET_CONTROL,
        cost_assumption_ref=episode.cost_ref.uri,
        tradable=False,
    )
    bad = HypothesisSpec(
        hypothesis_id=f"{episode.episode_id}-gold-bad",
        version=1,
        family=HypothesisFamily.VOLATILITY_COMPRESSION_BREAKOUT,
        market_condition=episode.market_state,
        signal_operator=SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,
        parameters=(("direction", "FOLLOW"), ("threshold", threshold)),
        expected_observable="ungrounded future-path claim that must not enter an experiment",
        falsification_condition="any experiment would be invalid because the evidence ref is not on the episode",
        supporting_evidence_refs=("metric://ungrounded-canary",),
        strongest_counter_evidence_refs=(episode.market_snapshot_ref.uri,),
        unknowns=episode.unknowns,
        primary_metric="net_directional_mean",
        control=PACKET_CONTROL,
        cost_assumption_ref=episode.cost_ref.uri,
        tradable=False,
    )
    return (
        GoldHypothesisCase(episode.episode_id, GoldLabel.CLEAN, "SELECT", clean),
        GoldHypothesisCase(episode.episode_id, GoldLabel.BAD, "REJECT", bad),
    )
