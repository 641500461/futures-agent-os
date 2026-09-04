"""Structured workloads that share numeric evidence and the protocol digest."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    CriticDecision,
    CriticReview,
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisSpec,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
)
from futures_agent_os.research_experiment.mvp_r_003.hypothesis_validator import validate_hypothesis_batch
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import (
    CRITIC_SCHEMA,
    FINAL_VERDICT_SCHEMA,
    HYPOTHESIS_SCHEMA,
    ModelWorkloadReceipt,
    MvpR003ModelWorkloads,
    StructuredModelConfig,
    StructuredModelTransport,
    _CHECKS,
    _exact_keys,
    _mapping,
    _sequence,
    _strings,
    _text,
)

from .contracts import PACKET_CONTROL, PACKET_PRIMARY_METRICS, ResearchEvidenceBundle, ValidationProtocolDigest
from .metrics import resolve_registered_metrics
from .validator import MvpR004HypothesisValidator

HYPOTHESIS_INSTRUCTIONS = (
    "Propose exactly two or three distinct, bounded, executable and falsifiable research hypotheses. "
    "Use the shared ResearchEvidenceBundle numeric bars and summary, not just hashes or market_state. "
    "Primary metric and control must be ResultPacket field names from the protocol digest. "
    "This is research-only: never propose trades, orders, positions or business facts."
)
CRITIC_INSTRUCTIONS = (
    "Independently challenge the hypothesis using the shared ResearchEvidenceBundle and "
    "ValidationProtocolDigest. Sample size, folds, costs, embargo, PIT rules and the multiple-testing "
    "budget are already in the protocol digest; do not treat those disclosed facts as missing. "
    "Known limitations listed in the protocol are disclosed, not automatic REJECT or DEFER. "
    "SELECT a grounded, executable, falsifiable hypothesis that respects the protocol. "
    "REJECT ungrounded refs, trading requests, unsupported operators, or primary metrics that are not "
    "ResultPacket fields. DEFER only when a required numeric fact is actually absent from the supplied bundle."
)
FINAL_VERDICT_INSTRUCTIONS = (
    "Judge the registered hypothesis only from the complete deterministic experiment result packet and "
    "the resolved primary/control metric pair. Return ACCEPT, REJECT, MODIFY, or NEED_MORE_DATA. "
    "Treat the mapped counterfactual control as first-class counter-evidence. "
    "MODIFY creates one new version and is never auto-executed."
)
SINGLE_PROMPT_INSTRUCTIONS = (
    "Act as a strong single-prompt research analyst. Read the shared ResearchEvidenceBundle, "
    "ValidationProtocolDigest, registered hypothesis and complete ResultPacket, then return the best "
    "direct research-only verdict. Use actual ResultPacket metric fields and the mapped control. "
    "Do not create trading actions."
)


class MvpR004ModelWorkloads:
    """Same transport and fail-closed checks, with shared numeric evidence."""

    def __init__(self, transport: StructuredModelTransport) -> None:
        self._base = MvpR003ModelWorkloads(transport)

    def generate_hypotheses(
        self,
        episode: ResearchEpisodeInput,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[tuple[HypothesisSpec, ...], ModelWorkloadReceipt]:
        schema = deepcopy(HYPOTHESIS_SCHEMA)
        root_properties = cast(dict[str, object], schema["properties"])
        hypotheses_schema = cast(dict[str, object], root_properties["hypotheses"])
        hypothesis_schema = cast(dict[str, object], hypotheses_schema["items"])
        properties = cast(dict[str, object], hypothesis_schema["properties"])
        allowed = dict(episode.allowed_parameter_values)
        cast(dict[str, object], properties["direction"])["enum"] = list(allowed["direction"])
        cast(dict[str, object], properties["threshold"])["enum"] = list(allowed["threshold"])
        for field in ("supporting_evidence_refs", "strongest_counter_evidence_refs"):
            references = cast(dict[str, object], properties[field])
            cast(dict[str, object], references["items"])["enum"] = sorted(episode.available_ref_uris)
        cast(dict[str, object], properties["cost_assumption_ref"])["enum"] = [episode.cost_ref.uri]
        cast(dict[str, object], properties["primary_metric"])["enum"] = list(PACKET_PRIMARY_METRICS)
        cast(dict[str, object], properties["control"])["enum"] = [PACKET_CONTROL]
        value, receipt = self._base._invoke(
            "hypothesis_generation",
            HYPOTHESIS_INSTRUCTIONS,
            {
                "episode": episode.to_dict(),
                "evidence_bundle": bundle.to_dict(),
                "validation_protocol": protocol.to_dict(),
            },
            schema,
            config,
        )
        _exact_keys(value, {"hypotheses"}, "hypothesis response")
        hypotheses = tuple(
            self._base._hypothesis(episode, _mapping(item, "hypothesis"), index)
            for index, item in enumerate(_sequence(value["hypotheses"], "hypotheses"), start=1)
        )
        validate_hypothesis_batch(hypotheses)
        validator = MvpR004HypothesisValidator()
        if any(validator.validate(episode, item).status.value != "EXECUTABLE" for item in hypotheses):
            raise ValueError("Research Agent emitted a hypothesis that is not R-004 executable")
        return hypotheses, receipt

    def critique(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[CriticReview, ModelWorkloadReceipt]:
        artifact_refs = (
            episode.dataset_ref,
            episode.market_snapshot_ref,
            episode.feature_ref,
            episode.rule_ref,
            episode.cost_ref,
            episode.toolset_ref,
            *episode.evidence_refs,
        )
        grounded_refs = episode.available_ref_uris | {
            *(item.content_sha256 for item in artifact_refs),
            hypothesis.identity,
            hypothesis.content_sha256,
            bundle.identity,
            bundle.content_sha256,
            protocol.identity,
            protocol.content_sha256,
        }
        schema = deepcopy(CRITIC_SCHEMA)
        properties = cast(dict[str, object], schema["properties"])
        source_refs = cast(dict[str, object], properties["source_refs"])
        items = cast(dict[str, object], source_refs["items"])
        items["enum"] = sorted(grounded_refs)
        value, receipt = self._base._invoke(
            "independent_critic",
            CRITIC_INSTRUCTIONS,
            {
                "episode": episode.to_dict(),
                "hypothesis": hypothesis.to_dict(),
                "evidence_bundle": bundle.to_dict(),
                "validation_protocol": protocol.to_dict(),
            },
            schema,
            config,
        )
        _exact_keys(value, {"decision", "checks", "reason_codes", "source_refs"}, "critic response")
        checks = _mapping(value["checks"], "critic checks")
        _exact_keys(checks, set(_CHECKS), "critic checks")
        review = CriticReview(
            review_id=f"{episode.episode_id}-{hypothesis.hypothesis_id}-critic",
            hypothesis_id=hypothesis.hypothesis_id,
            decision=CriticDecision(_text(value["decision"], "critic decision")),
            checks=tuple((name, _text(checks[name], name)) for name in _CHECKS),
            reason_codes=_strings(value["reason_codes"], "reason codes"),
            source_refs=_strings(value["source_refs"], "source refs"),
        )
        if not set(review.source_refs) <= grounded_refs:
            raise ValueError("Critic emitted an ungrounded source reference")
        return review, receipt

    def final_verdict(
        self,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        config: StructuredModelConfig,
    ) -> tuple[ResearchFinalVerdict, ModelWorkloadReceipt]:
        resolved = resolve_registered_metrics(hypothesis, result)
        value, receipt = self._base._invoke(
            "result_feedback",
            FINAL_VERDICT_INSTRUCTIONS,
            {
                "hypothesis": hypothesis.to_dict(),
                "experiment_result": result.to_dict(),
                "resolved_metrics": resolved,
            },
            FINAL_VERDICT_SCHEMA,
            config,
        )
        return self._base._build_verdict(hypothesis, result, value), receipt

    def single_prompt_verdict(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[ResearchFinalVerdict, ModelWorkloadReceipt]:
        resolved = resolve_registered_metrics(hypothesis, result)
        schema = deepcopy(FINAL_VERDICT_SCHEMA)
        properties = cast(dict[str, object], schema["properties"])
        cast(dict[str, object], properties["verdict"])["enum"] = [
            FinalVerdict.ACCEPT.value,
            FinalVerdict.REJECT.value,
            FinalVerdict.NEED_MORE_DATA.value,
        ]
        properties["modified_direction"] = {"type": "null"}
        properties["modified_threshold"] = {"type": "null"}
        value, receipt = self._base._invoke(
            "single_prompt_analyst",
            SINGLE_PROMPT_INSTRUCTIONS,
            {
                "episode": episode.to_dict(),
                "evidence_bundle": bundle.to_dict(),
                "validation_protocol": protocol.to_dict(),
                "registered_hypothesis": hypothesis.to_dict(),
                "experiment_result": result.to_dict(),
                "resolved_metrics": resolved,
            },
            schema,
            config,
        )
        return self._base._build_verdict(hypothesis, result, value), receipt
