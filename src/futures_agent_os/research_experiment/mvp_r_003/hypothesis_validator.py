"""Deterministic executability validation for bounded MVP-R-003 hypotheses."""

from __future__ import annotations

from .contracts import (
    HypothesisSpec,
    HypothesisValidation,
    ResearchEpisodeInput,
    SignalOperator,
    ValidationStatus,
)


_SUPPORTED_OPERATORS = {SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD}
_SUPPORTED_METRICS = {
    "accuracy",
    "net_directional_mean",
    "positive_fold_ratio",
    "signal_accuracy",
    "proxy_net_return",
    "stressed_net_return",
}
_SUPPORTED_CONTROLS = {"inverted signal direction"}


def validate_hypothesis_batch(hypotheses: tuple[HypothesisSpec, ...]) -> None:
    if type(hypotheses) is not tuple or len(hypotheses) not in (2, 3):
        raise ValueError("Research Agent must propose exactly 2 or 3 hypotheses")
    if any(type(item) is not HypothesisSpec for item in hypotheses):
        raise TypeError("hypothesis batch requires exact HypothesisSpec values")
    semantic_keys = {
        (
            item.family,
            item.market_condition,
            item.signal_operator,
            item.parameters,
            item.expected_observable,
            item.falsification_condition,
        )
        for item in hypotheses
    }
    if len(semantic_keys) != len(hypotheses):
        raise ValueError("Research Agent hypotheses must be semantically distinct")
    identities = {item.identity for item in hypotheses}
    if len(identities) != len(hypotheses):
        raise ValueError("Research Agent hypothesis identities must be distinct")


class HypothesisValidator:
    """Checks only whether a proposal can be executed against the frozen episode."""

    def validate(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        *,
        duplicate_detected: bool = False,
    ) -> HypothesisValidation:
        if type(episode) is not ResearchEpisodeInput or type(hypothesis) is not HypothesisSpec:
            raise TypeError("validator requires exact episode and hypothesis contracts")

        allowed_parameters = dict(episode.allowed_parameter_values)
        parameters = dict(hypothesis.parameters)
        parameters_resolved = set(parameters) == {"direction", "threshold"} and all(
            name in allowed_parameters and value in allowed_parameters[name] for name, value in parameters.items()
        )
        operator_resolved = (
            hypothesis.signal_operator in _SUPPORTED_OPERATORS
            and hypothesis.signal_operator in episode.signal_operators
        )
        evidence_resolved = (
            set((*hypothesis.supporting_evidence_refs, *hypothesis.strongest_counter_evidence_refs))
            <= episode.available_ref_uris
        )
        data_resolved = (
            hypothesis.cost_assumption_ref == episode.cost_ref.uri
            and evidence_resolved
            and episode.dataset_ref.uri in episode.available_ref_uris
        )
        window_resolved = bool(episode.market_cutoff and episode.as_of)
        metric_resolved = hypothesis.primary_metric in _SUPPORTED_METRICS
        control_resolved = hypothesis.control in _SUPPORTED_CONTROLS
        cost_resolved = hypothesis.cost_assumption_ref == episode.cost_ref.uri
        future_leak_detected = episode.future_result_present

        reasons: list[str] = []
        if not operator_resolved:
            reasons.append("UNSUPPORTED_SIGNAL_OPERATOR")
        if not parameters_resolved:
            reasons.append("UNRESOLVED_PARAMETER")
        if not evidence_resolved:
            reasons.append("UNGROUNDED_EVIDENCE_REF")
        if not data_resolved:
            reasons.append("UNRESOLVED_DATA")
        if not metric_resolved:
            reasons.append("UNSUPPORTED_PRIMARY_METRIC")
        if not control_resolved:
            reasons.append("UNSUPPORTED_CONTROL")
        if not cost_resolved:
            reasons.append("UNRESOLVED_COST_ASSUMPTION")
        if future_leak_detected:
            reasons.append("FUTURE_LEAK")
        if duplicate_detected:
            reasons.append("DUPLICATE_HYPOTHESIS")

        status = ValidationStatus.EXECUTABLE if not reasons else ValidationStatus.UNSUPPORTED
        return HypothesisValidation(
            hypothesis_ref=hypothesis.identity,
            status=status,
            reason_codes=("EXECUTABLE",) if not reasons else tuple(sorted(reasons)),
            parameters_resolved=parameters_resolved and operator_resolved,
            data_resolved=data_resolved,
            window_resolved=window_resolved,
            metric_resolved=metric_resolved,
            control_resolved=control_resolved,
            cost_resolved=cost_resolved,
            future_leak_detected=future_leak_detected,
            duplicate_detected=duplicate_detected,
        )
