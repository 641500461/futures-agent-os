"""MVP-R-004 Discovery measurement repair."""

from .contracts import (
    CONTROL_METRIC_BY_PRIMARY,
    PACKET_CONTROL,
    PACKET_PRIMARY_METRICS,
    GoldHypothesisCase,
    GoldLabel,
    PitBarFact,
    ResearchEvidenceBundle,
    ValidationProtocolDigest,
)
from .evidence import build_research_evidence_bundle
from .gold_labels import gold_cases
from .metrics import packet_metric_map, resolve_registered_metrics
from .protocol import build_validation_protocol_digest
from .scorecard import (
    CanaryEpisodeOutcome,
    DiscoveryEpisodeOutcome,
    LabeledCriticOutcome,
    UserBlindEpisode,
    compute_canary_gate,
    compute_discovery_gate,
    compute_user_blind_gate,
    gold_retention_recall,
)
from .validator import MvpR004HypothesisValidator
from .workloads import MvpR004ModelWorkloads

__all__ = [
    "CONTROL_METRIC_BY_PRIMARY",
    "CanaryEpisodeOutcome",
    "DiscoveryEpisodeOutcome",
    "GoldHypothesisCase",
    "GoldLabel",
    "LabeledCriticOutcome",
    "UserBlindEpisode",
    "MvpR004HypothesisValidator",
    "MvpR004ModelWorkloads",
    "PACKET_CONTROL",
    "PACKET_PRIMARY_METRICS",
    "PitBarFact",
    "ResearchEvidenceBundle",
    "ValidationProtocolDigest",
    "build_research_evidence_bundle",
    "build_validation_protocol_digest",
    "compute_canary_gate",
    "compute_discovery_gate",
    "compute_user_blind_gate",
    "gold_cases",
    "gold_retention_recall",
    "packet_metric_map",
    "resolve_registered_metrics",
]
