"""Bounded independent Critic contracts for the MVP-R multi-family Pivot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from typing import Mapping, cast

from futures_agent_os.shared_kernel import canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .mvp_pivot import PivotDeterministicCritique
from .mvp_validation import HypothesisFamily, ModelUsage, ResearchConclusion, ResearchConclusionKind


class PivotCriticDecision(StrEnum):
    ACCEPT = "ACCEPT"
    VETO = "VETO"


def requires_independent_pivot_critic(
    proposal: ResearchConclusion,
    deterministic_critique: PivotDeterministicCritique,
) -> bool:
    """Route only deterministically admissible opportunities to the costly Critic."""

    if type(proposal) is not ResearchConclusion or type(deterministic_critique) is not PivotDeterministicCritique:
        raise TypeError("Pivot Critic routing requires exact proposal and deterministic critique types")
    return bool(proposal.kind is ResearchConclusionKind.OPPORTUNITY_CANDIDATE and deterministic_critique.accepted)


@dataclass(frozen=True, slots=True)
class PivotCriticRequest:
    episode_id: str
    instrument_id: str
    market_state: str
    proposal: ResearchConclusion
    feature_evidence_sha256: str
    family_screens: tuple[dict[str, JsonValue], ...]

    def __post_init__(self) -> None:
        if not self.episode_id.strip() or not self.instrument_id.strip() or not self.market_state.strip():
            raise ValueError("Pivot Critic request requires episode, instrument, and market state")
        if type(self.proposal) is not ResearchConclusion or not self.family_screens:
            raise TypeError("Pivot Critic request requires a typed proposal and family screens")
        _digest(self.feature_evidence_sha256)
        if any(type(screen) is not dict for screen in self.family_screens):
            raise TypeError("Pivot Critic family screens must be frozen mappings")

    @property
    def proposal_sha256(self) -> str:
        return canonical_sha256(self.proposal.to_dict())

    def payload(self) -> dict[str, JsonValue]:
        return {
            "episode_id": self.episode_id,
            "instrument_id": self.instrument_id,
            "market_state": self.market_state,
            "proposal": self.proposal.to_dict(),
            "proposal_sha256": self.proposal_sha256,
            "feature_evidence_sha256": self.feature_evidence_sha256,
            "family_screens": self.family_screens,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class PivotCriticReview:
    decision: PivotCriticDecision
    proposal_sha256: str
    feature_evidence_sha256: str
    high_severity_defects: tuple[str, ...]
    counter_hypothesis_family: HypothesisFamily
    summary: str

    def __post_init__(self) -> None:
        if (
            type(self.decision) is not PivotCriticDecision
            or type(self.counter_hypothesis_family) is not HypothesisFamily
        ):
            raise TypeError("Pivot Critic review requires closed decision and family types")
        _digest(self.proposal_sha256)
        _digest(self.feature_evidence_sha256)
        if (
            not self.summary.strip()
            or self.high_severity_defects != tuple(sorted(set(self.high_severity_defects)))
            or any(not defect.strip() for defect in self.high_severity_defects)
        ):
            raise ValueError("Pivot Critic review requires canonical defects and summary")
        if self.decision is PivotCriticDecision.ACCEPT and (
            self.high_severity_defects or self.counter_hypothesis_family is not HypothesisFamily.NONE
        ):
            raise ValueError("accepted Pivot proposals cannot contain defects or a counter-family")
        if self.decision is PivotCriticDecision.VETO and not self.high_severity_defects:
            raise ValueError("vetoed Pivot proposals require at least one high-severity defect")

    def verify_request(self, request: PivotCriticRequest) -> None:
        if type(request) is not PivotCriticRequest:
            raise TypeError("Pivot Critic review verification requires an exact request")
        if self.proposal_sha256 != request.proposal_sha256:
            raise PermissionError("Pivot Critic review is bound to a different proposal")
        if self.feature_evidence_sha256 != request.feature_evidence_sha256:
            raise PermissionError("Pivot Critic review is bound to different family evidence")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "decision": self.decision.value,
            "proposal_sha256": self.proposal_sha256,
            "feature_evidence_sha256": self.feature_evidence_sha256,
            "high_severity_defects": self.high_severity_defects,
            "counter_hypothesis_family": self.counter_hypothesis_family.value,
            "summary": self.summary,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> PivotCriticReview:
        expected = {
            "decision",
            "proposal_sha256",
            "feature_evidence_sha256",
            "high_severity_defects",
            "counter_hypothesis_family",
            "summary",
        }
        if set(value) != expected:
            raise ValueError("Pivot Critic review has unexpected fields")
        defects = value["high_severity_defects"]
        if type(defects) not in {tuple, list}:
            raise TypeError("Pivot Critic defects must be text")
        typed_defects = cast(tuple[object, ...] | list[object], defects)
        if any(type(item) is not str for item in typed_defects):
            raise TypeError("Pivot Critic defects must be text")
        return cls(
            PivotCriticDecision(_text(value["decision"])),
            _text(value["proposal_sha256"]),
            _text(value["feature_evidence_sha256"]),
            tuple(cast(tuple[str, ...] | list[str], typed_defects)),
            HypothesisFamily(_text(value["counter_hypothesis_family"])),
            _text(value["summary"]),
        )


@dataclass(frozen=True, slots=True)
class PivotCriticModelTurn:
    response_id: str
    provider_model_id: str
    usage: ModelUsage
    review: PivotCriticReview | None
    failure_code: str | None

    def __post_init__(self) -> None:
        if not self.response_id.strip() or not self.provider_model_id.strip() or type(self.usage) is not ModelUsage:
            raise ValueError("Pivot Critic turn requires response, model, and usage")
        if (self.review is None) == (self.failure_code is None):
            raise ValueError("Pivot Critic turn requires exactly one review or failure")
        if self.failure_code is not None and not self.failure_code.strip():
            raise ValueError("Pivot Critic failure code cannot be empty")


@dataclass(frozen=True, slots=True)
class FrozenPivotCriticAuthorization:
    authority_id: str
    request_sha256: str
    model_id: str
    prompt_sha256: str
    runtime_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if not self.authority_id.strip() or not self.model_id.strip():
            raise ValueError("Pivot Critic authorization requires authority and model")
        for digest in (self.request_sha256, self.prompt_sha256, self.runtime_sha256, self.signature_sha256):
            _digest(digest)

    def unsigned_payload(self) -> dict[str, JsonValue]:
        return {
            "authority_id": self.authority_id,
            "request_sha256": self.request_sha256,
            "model_id": self.model_id,
            "prompt_sha256": self.prompt_sha256,
            "runtime_sha256": self.runtime_sha256,
        }


class PivotCriticAuthorizationAuthority:
    def __init__(self, authority_id: str, secret: bytes) -> None:
        if not authority_id.strip() or type(secret) is not bytes or len(secret) < 32:
            raise ValueError("Pivot Critic authority requires identity and a protected key")
        self._authority_id = authority_id
        self._secret = secret

    def issue(
        self,
        request: PivotCriticRequest,
        *,
        model_id: str,
        prompt_sha256: str,
        runtime_sha256: str,
    ) -> FrozenPivotCriticAuthorization:
        if type(request) is not PivotCriticRequest or not model_id.strip():
            raise TypeError("Pivot Critic authorization requires exact request and model")
        _digest(prompt_sha256)
        _digest(runtime_sha256)
        unsigned: dict[str, JsonValue] = {
            "authority_id": self._authority_id,
            "request_sha256": request.content_sha256,
            "model_id": model_id,
            "prompt_sha256": prompt_sha256,
            "runtime_sha256": runtime_sha256,
        }
        return FrozenPivotCriticAuthorization(
            self._authority_id,
            request.content_sha256,
            model_id,
            prompt_sha256,
            runtime_sha256,
            self._sign(unsigned),
        )

    def verify(
        self,
        authorization: FrozenPivotCriticAuthorization,
        request: PivotCriticRequest,
        *,
        model_id: str,
        prompt_sha256: str,
        runtime_sha256: str,
    ) -> None:
        if type(authorization) is not FrozenPivotCriticAuthorization or type(request) is not PivotCriticRequest:
            raise TypeError("Pivot Critic verification requires exact authorization and request")
        expected = self.issue(
            request,
            model_id=model_id,
            prompt_sha256=prompt_sha256,
            runtime_sha256=runtime_sha256,
        )
        if authorization.unsigned_payload() != expected.unsigned_payload() or not compare_digest(
            authorization.signature_sha256, expected.signature_sha256
        ):
            raise PermissionError("Pivot Critic authorization does not bind the exact frozen invocation")

    def _sign(self, payload: dict[str, JsonValue]) -> str:
        from futures_agent_os.shared_kernel import canonical_json_text

        return hmac_new(self._secret, canonical_json_text(payload).encode(), sha256).hexdigest()


def _digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Pivot Critic digest must be lowercase SHA-256")


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise TypeError("Pivot Critic value must be non-empty text")
    return value


__all__ = [
    "PivotCriticDecision",
    "PivotCriticAuthorizationAuthority",
    "PivotCriticModelTurn",
    "PivotCriticRequest",
    "PivotCriticReview",
    "FrozenPivotCriticAuthorization",
    "requires_independent_pivot_critic",
]
