"""MVP-R-003 synchronous research discovery vertical slice."""

from .contracts import (
    ArtifactRef,
    CriticDecision,
    CriticReview,
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisFamily,
    HypothesisSpec,
    HypothesisValidation,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
    ToolRunResult,
    ValidationStatus,
)
from .experiment_adapter import MvpR003ExperimentAdapter
from .hypothesis_validator import HypothesisValidator, validate_hypothesis_batch
from .model_workloads import (
    ModelWorkloadObservationError,
    ModelWorkloadReceipt,
    MvpR003ModelWorkloads,
    StructuredModelConfig,
)

__all__ = [
    "ArtifactRef",
    "CriticDecision",
    "CriticReview",
    "ExecutableExperimentPlan",
    "ExperimentResultPacket",
    "FinalVerdict",
    "HypothesisFamily",
    "HypothesisSpec",
    "HypothesisValidation",
    "HypothesisValidator",
    "MvpR003ExperimentAdapter",
    "MvpR003ModelWorkloads",
    "ModelWorkloadReceipt",
    "ModelWorkloadObservationError",
    "ResearchEpisodeInput",
    "ResearchFinalVerdict",
    "SignalOperator",
    "StructuredModelConfig",
    "ToolRunResult",
    "ValidationStatus",
    "validate_hypothesis_batch",
]
