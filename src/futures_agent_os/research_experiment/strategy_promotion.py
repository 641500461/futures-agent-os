"""Strategy promotion gates with independent human approval and activation."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from futures_agent_os.shared_kernel import canonical_sha256
from .v4_003 import ValidationArtifact, ValidationKind, ArtifactStatus


class PromotionStage(StrEnum):
    HISTORICAL = "HISTORICAL"
    ROBUSTNESS = "ROBUSTNESS"
    OOS = "OOS"
    FORWARD = "FORWARD"
    APPROVED = "APPROVED"
    ACTIVATED = "ACTIVATED"
    REJECTED = "REJECTED"


_REQUIRED = (
    ValidationKind.COST_SLIPPAGE_STRESS,
    ValidationKind.PARAMETER_SWEEP,
    ValidationKind.WALK_FORWARD,
    ValidationKind.SCENARIO_REPLAY,
)


@dataclass(frozen=True, slots=True)
class StrategyPromotionRequest:
    strategy_sha256: str
    artifacts: tuple[ValidationArtifact, ...]
    target_scope: tuple[str, ...]

    def __post_init__(self):
        if len(self.strategy_sha256) != 64 or not self.target_scope:
            raise ValueError("strategy request requires strategy digest and scope")
        if any(
            a.status is not ArtifactStatus.COMPLETE or a.strategy_sha256 != self.strategy_sha256 for a in self.artifacts
        ):
            raise ValueError("promotion artifacts must be complete and strategy-bound")
        kinds = {a.kind for a in self.artifacts}
        if not set(_REQUIRED).issubset(kinds):
            raise ValueError("promotion requires historical, robustness, OOS and forward evidence")

    @property
    def content_sha256(self):
        return canonical_sha256(
            {
                "strategy": self.strategy_sha256,
                "artifacts": tuple(a.content_sha256 for a in self.artifacts),
                "scope": self.target_scope,
            }
        )


@dataclass(frozen=True, slots=True)
class StrategyActivation:
    strategy_sha256: str
    scope: tuple[str, ...]
    approved_by: str
    activated_by: str

    def __post_init__(self):
        if not self.approved_by.startswith("user:") or not self.activated_by.startswith("user:"):
            raise ValueError("strategy activation requires human governance actors")


class StrategyPromotionRegistry:
    def __init__(self):
        self._requests = {}
        self._approvals = {}
        self._activations = {}

    def submit(self, request):
        if type(request) is not StrategyPromotionRequest:
            raise TypeError("typed promotion request required")
        self._requests[request.content_sha256] = request
        return request.content_sha256

    def approve(self, request_sha256: str, actor: str):
        if request_sha256 not in self._requests or not actor.startswith("user:"):
            raise ValueError("human approval required for known request")
        self._approvals[request_sha256] = actor

    def activate(self, request_sha256: str, actor: str) -> StrategyActivation:
        request = self._requests.get(request_sha256)
        if request is None or request_sha256 not in self._approvals:
            raise ValueError("approved promotion required before activation")
        activation = StrategyActivation(
            request.strategy_sha256, request.target_scope, self._approvals[request_sha256], actor
        )
        self._activations[request_sha256] = activation
        return activation

    def resolve(self, request_sha256: str) -> StrategyActivation:
        try:
            return self._activations[request_sha256]
        except KeyError as exc:
            raise ValueError("strategy is not independently activated") from exc


__all__ = ["PromotionStage", "StrategyActivation", "StrategyPromotionRegistry", "StrategyPromotionRequest"]
