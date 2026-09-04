"""Structured workloads for the single-agent loop and Single-prompt baseline."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import cast

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisFamily,
    HypothesisSpec,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
)
from futures_agent_os.research_experiment.mvp_r_003.hypothesis_validator import validate_hypothesis_batch
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import (
    FINAL_VERDICT_SCHEMA,
    HYPOTHESIS_SCHEMA,
    ModelWorkloadReceipt,
    MvpR003ModelWorkloads,
    StructuredModelConfig,
    StructuredModelTransport,
    _exact_keys,
    _mapping,
    _sequence,
    _strings,
    _text,
)
from futures_agent_os.research_experiment.mvp_r_004.contracts import (
    PACKET_CONTROL,
    PACKET_PRIMARY_METRICS,
    ResearchEvidenceBundle,
    ValidationProtocolDigest,
)

from .contracts import DecisionBrief, ShadowCritique
from .packet import (
    apply_need_more_data_guard,
    resolve_treatment_relative_metrics,
)
from .predicate import (
    PREDICATE_SCHEMA,
    bind_falsification_condition,
    enforce_verdict_predicate_congruence,
    evaluate_falsification_predicate,
    parse_falsification_condition,
    parse_predicate_mapping,
)
from .treatment_view import TreatmentMetricView

LOGGER = logging.getLogger("mvp-r-005.workloads")

HYPOTHESIS_INSTRUCTIONS = (
    "Propose exactly two or three distinct, bounded, falsifiable research hypotheses. "
    "Prefer executable PRIOR_CLOSE_RETURN_THRESHOLD hypotheses with FOLLOW or INVERT and a "
    "ResultPacket primary metric. The deterministic validator will intercept VOLUME_CONFIRMATION, "
    "HOLD, or net_directional_mean. At least one hypothesis must remain executable. "
    "You must emit a typed falsification_predicate. The human-readable falsification_condition "
    "will be rendered from that predicate. Register only the comparisons you actually want: "
    "aggregate primary > control, primary > 0 and > control, each OOS fold primary > control, "
    "at least N OOS folds above a threshold, required OOS fold count, or full-window minimum sample. "
    "Fold clauses may use only signal_accuracy or proxy_net_return. stressed_net_return has no per-fold "
    "fields and is illegal on each_oos_fold_primary_beats_control and at_least_n_oos_folds_above_threshold. "
    "Unused clause fields must be JSON null: do not put a threshold on aggregate or primary-positive "
    "clauses, and do not put fold_n on clauses that do not require it. "
    "Do not treat positive_fold_ratio as per-fold accuracy. "
    "fold_N_signal_accuracy is authentic walk-forward OOS, not an equal split of the full window. "
    "Use the shared ResearchEvidenceBundle numeric bars. This is research-only: never propose trades."
)
FINAL_VERDICT_INSTRUCTIONS = (
    "Judge the registered hypothesis only from the treatment_metric_view, resolved treatment-relative "
    "metrics, and the supplied deterministic_predicate_outcome. "
    "Your verdict MUST equal deterministic_predicate_outcome.outcome. "
    "Stopped OOS folds are omitted from the view; do not mention their values or ask to fill them "
    "on the same frozen plan. If the deterministic outcome is REJECT, do not request the next fold. "
    "NEED_MORE_DATA is allowed only when no clause has already FAILed and missing data could still "
    "change the conclusion. You cannot add unregistered fold or sample conditions. "
    "positive_fold_ratio is OOS net-positive fold share, not per-fold hit rate. "
    "MODIFY is allowed only when the deterministic outcome is REJECT, must create one new hypothesis "
    "version, and is never auto-executed; it cannot rewrite the original predicate result. "
    "Write what_was_tested, results, current_judgment and next_action in Simplified Chinese. "
    "This is research and simulation only, not a trading authorization or product GO. "
    "Do not create trading actions."
)
SINGLE_PROMPT_INSTRUCTIONS = (
    "Act as a strong single-prompt research analyst on the same frozen episode, protocol, registered "
    "fallback hypothesis and treatment_metric_view. Your verdict MUST equal "
    "deterministic_predicate_outcome.outcome. Do not add unregistered conditions. "
    "Stopped OOS folds are omitted; do not ask to fill them on the same frozen plan when the "
    "outcome is already REJECT. Write what_was_tested, results, current_judgment and next_action "
    "in Simplified Chinese. This is research and simulation only. Do not create trading actions."
)
SHADOW_INSTRUCTIONS = (
    "You are optional shadow QA after the experiment has already run. Record risk notes only. "
    "You cannot block, stop, select or reject the experiment. If you believe you would have blocked "
    "it beforehand, set would_have_blocked_experiment true; the runner will still not block. "
    "Do not invent facts or trading actions."
)
_BRIEF_KEYS = {
    "verdict",
    "rationale",
    "modified_direction",
    "modified_threshold",
    "what_was_tested",
    "results",
    "current_judgment",
    "next_action",
}
DECISION_BRIEF_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_BRIEF_KEYS),
    "properties": {
        **cast(dict[str, object], deepcopy(FINAL_VERDICT_SCHEMA)["properties"]),
        "what_was_tested": {"type": "string", "minLength": 1},
        "results": {"type": "string", "minLength": 1},
        "current_judgment": {"type": "string", "minLength": 1},
        "next_action": {"type": "string", "minLength": 1},
    },
}
SHADOW_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["risk_notes", "would_have_blocked_experiment"],
    "properties": {
        "risk_notes": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "would_have_blocked_experiment": {"type": "boolean"},
    },
}


class MvpR005ModelWorkloads:
    """Compose R-004 transport; Critic is shadow-only after the experiment."""

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
        required = cast(list[str], hypothesis_schema["required"])
        if "signal_operator" not in required:
            required.append("signal_operator")
        if "falsification_predicate" not in required:
            required.append("falsification_predicate")
        properties["signal_operator"] = {
            "type": "string",
            "enum": [
                SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD.value,
                SignalOperator.VOLUME_CONFIRMATION.value,
            ],
        }
        properties["falsification_predicate"] = PREDICATE_SCHEMA
        allowed = dict(episode.allowed_parameter_values)
        cast(dict[str, object], properties["direction"])["enum"] = ["FOLLOW", "INVERT", "HOLD"]
        cast(dict[str, object], properties["threshold"])["enum"] = list(allowed["threshold"])
        for field in ("supporting_evidence_refs", "strongest_counter_evidence_refs"):
            references = cast(dict[str, object], properties[field])
            cast(dict[str, object], references["items"])["enum"] = sorted(episode.available_ref_uris)
        cast(dict[str, object], properties["cost_assumption_ref"])["enum"] = [episode.cost_ref.uri]
        cast(dict[str, object], properties["primary_metric"])["enum"] = [
            *PACKET_PRIMARY_METRICS,
            "net_directional_mean",
        ]
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
        parsed: list[HypothesisSpec] = []
        for index, item in enumerate(_sequence(value["hypotheses"], "hypotheses"), start=1):
            try:
                parsed.append(self._hypothesis(episode, _mapping(item, "hypothesis"), index))
            except (TypeError, ValueError) as error:
                LOGGER.info("dropping ill-typed generated hypothesis %s: %s", index, error)
        hypotheses = tuple(parsed)
        if len(hypotheses) not in (2, 3):
            raise ValueError("Research Agent must propose exactly 2 or 3 well-typed hypotheses")
        validate_hypothesis_batch(hypotheses)
        return hypotheses, receipt

    def final_verdict(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        view: TreatmentMetricView,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[ResearchFinalVerdict, DecisionBrief, ModelWorkloadReceipt]:
        value, receipt = self._base._invoke(
            "result_feedback",
            FINAL_VERDICT_INSTRUCTIONS,
            result_feedback_model_input(episode, hypothesis, view, bundle, protocol),
            DECISION_BRIEF_SCHEMA,
            config,
        )
        verdict, brief = self._brief_verdict(hypothesis, result, view, value)
        return verdict, brief, receipt

    def single_prompt_verdict(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        view: TreatmentMetricView,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[ResearchFinalVerdict, DecisionBrief, ModelWorkloadReceipt]:
        schema = deepcopy(DECISION_BRIEF_SCHEMA)
        properties = cast(dict[str, object], schema["properties"])
        cast(dict[str, object], properties["verdict"])["enum"] = [
            FinalVerdict.ACCEPT.value,
            FinalVerdict.REJECT.value,
            FinalVerdict.NEED_MORE_DATA.value,
        ]
        properties["modified_direction"] = {"type": "null"}
        properties["modified_threshold"] = {"type": "null"}
        payload = result_feedback_model_input(episode, hypothesis, view, bundle, protocol)
        payload["registered_hypothesis"] = payload.pop("hypothesis")
        value, receipt = self._base._invoke(
            "single_prompt_analyst",
            SINGLE_PROMPT_INSTRUCTIONS,
            payload,
            schema,
            config,
        )
        verdict, brief = self._brief_verdict(hypothesis, result, view, value)
        return verdict, brief, receipt

    def shadow_critique(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        view: TreatmentMetricView,
        bundle: ResearchEvidenceBundle,
        protocol: ValidationProtocolDigest,
        config: StructuredModelConfig,
    ) -> tuple[ShadowCritique, ModelWorkloadReceipt]:
        del result
        value, receipt = self._base._invoke(
            "shadow_critic",
            SHADOW_INSTRUCTIONS,
            {
                "episode": episode.to_dict(),
                "hypothesis": hypothesis.to_dict(),
                "treatment_metric_view": view.agent_visible_dict(),
                "evidence_bundle": bundle.to_dict(),
                "validation_protocol": protocol.to_dict(),
                "experiment_already_ran": True,
                "must_not_block": True,
            },
            SHADOW_SCHEMA,
            config,
        )
        _exact_keys(value, {"risk_notes", "would_have_blocked_experiment"}, "shadow critic response")
        blocked = value["would_have_blocked_experiment"]
        if type(blocked) is not bool:
            raise ValueError("shadow critic would_have_blocked_experiment must be boolean")
        return (
            ShadowCritique(
                risk_notes=_strings(value["risk_notes"], "shadow risk notes"),
                would_have_blocked_experiment=blocked,
            ),
            receipt,
        )

    def _brief_verdict(
        self,
        hypothesis: HypothesisSpec,
        result: ExperimentResultPacket,
        view: TreatmentMetricView,
        value: object,
    ) -> tuple[ResearchFinalVerdict, DecisionBrief]:
        payload = _mapping(value, "decision brief")
        _exact_keys(payload, _BRIEF_KEYS, "decision brief response")
        verdict = MvpR003ModelWorkloads._build_verdict(
            hypothesis,
            result,
            {
                "verdict": payload["verdict"],
                "rationale": payload["rationale"],
                "modified_direction": payload["modified_direction"],
                "modified_threshold": payload["modified_threshold"],
            },
        )
        brief = DecisionBrief(
            what_was_tested=_text(payload["what_was_tested"], "what was tested"),
            results=_text(payload["results"], "results"),
            current_judgment=_text(payload["current_judgment"], "current judgment"),
            next_action=_text(payload["next_action"], "next action"),
            verdict=verdict.verdict,
        )
        if parse_falsification_condition(hypothesis.falsification_condition) is None:
            guarded, guarded_brief, _forced = apply_need_more_data_guard(verdict, brief, hypothesis, result)
            return guarded, guarded_brief
        bound, bound_brief, _evaluation = enforce_verdict_predicate_congruence(
            verdict,
            brief,
            hypothesis,
            view,
        )
        return bound, bound_brief

    def _hypothesis(self, episode: ResearchEpisodeInput, value: object, index: int) -> HypothesisSpec:
        payload = _mapping(value, "hypothesis")
        expected = {
            "family",
            "market_condition",
            "signal_operator",
            "direction",
            "threshold",
            "expected_observable",
            "falsification_condition",
            "supporting_evidence_refs",
            "strongest_counter_evidence_refs",
            "unknowns",
            "primary_metric",
            "control",
            "cost_assumption_ref",
            "falsification_predicate",
        }
        _exact_keys(payload, expected, "hypothesis")
        predicate = parse_predicate_mapping(payload["falsification_predicate"])
        return HypothesisSpec(
            hypothesis_id=f"{episode.episode_id}-h{index}",
            version=1,
            family=HypothesisFamily(_text(payload["family"], "family")),
            market_condition=_text(payload["market_condition"], "market condition"),
            signal_operator=SignalOperator(_text(payload["signal_operator"], "signal operator")),
            parameters=(
                ("direction", _text(payload["direction"], "direction")),
                ("threshold", _text(payload["threshold"], "threshold")),
            ),
            expected_observable=_text(payload["expected_observable"], "expected observable"),
            falsification_condition=bind_falsification_condition(predicate),
            supporting_evidence_refs=_strings(payload["supporting_evidence_refs"], "supporting refs"),
            strongest_counter_evidence_refs=_strings(payload["strongest_counter_evidence_refs"], "counter refs"),
            unknowns=_strings(payload["unknowns"], "unknowns", allow_empty=True),
            primary_metric=_text(payload["primary_metric"], "primary metric"),
            control=_text(payload["control"], "control"),
            cost_assumption_ref=_text(payload["cost_assumption_ref"], "cost ref"),
            tradable=False,
        )


def result_feedback_model_input(
    episode: ResearchEpisodeInput,
    hypothesis: HypothesisSpec,
    view: TreatmentMetricView,
    bundle: ResearchEvidenceBundle,
    protocol: ValidationProtocolDigest,
) -> dict[str, object]:
    if type(view) is not TreatmentMetricView:
        raise TypeError("result feedback requires an exact TreatmentMetricView")
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        raise ValueError("R-005 correction-v3 result feedback requires a typed falsification predicate")
    evaluation = evaluate_falsification_predicate(predicate, view)
    resolved = resolve_treatment_relative_metrics(hypothesis, view)
    return {
        "episode": episode.to_dict(),
        "evidence_bundle": bundle.to_dict(),
        "validation_protocol": protocol.to_dict(),
        "hypothesis": hypothesis.to_dict(),
        "treatment_metric_view": view.agent_visible_dict(),
        "agent_visible_experiment": view.agent_visible_dict(),
        "raw_packet_ref": view.raw_packet_ref,
        "raw_packet_digest": view.raw_packet_digest,
        "resolved_metrics": resolved,
        "falsification_predicate": predicate.to_dict(),
        "deterministic_predicate_outcome": evaluation.to_dict(),
    }
