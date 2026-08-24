"""Research-owned feature definitions and deterministic signals."""

from .features import FeatureAlgorithm, FeatureDefinition, FeatureDefinitionRef, FeatureSpec, FeatureSpecRef
from .research_hypothesis import (
    EvidenceGap,
    EvidenceSynthesis,
    ExperimentRequest,
    ExperimentRequestSpec,
    FalsifiableHypothesis,
    FalsifiableHypothesisSpec,
    HypothesisLifecycle,
    HypothesisProposalSource,
    MarketStateAssessmentRef,
    ResearchSynthesis,
    ResearchSynthesisComposer,
    ResearchSynthesisInput,
)

__all__ = [
    "EvidenceGap",
    "EvidenceSynthesis",
    "ExperimentRequest",
    "ExperimentRequestSpec",
    "FalsifiableHypothesis",
    "FalsifiableHypothesisSpec",
    "HypothesisLifecycle",
    "HypothesisProposalSource",
    "FeatureAlgorithm",
    "FeatureDefinition",
    "FeatureDefinitionRef",
    "FeatureSpec",
    "FeatureSpecRef",
    "MarketStateAssessmentRef",
    "ResearchSynthesis",
    "ResearchSynthesisComposer",
    "ResearchSynthesisInput",
]
