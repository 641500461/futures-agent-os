"""R-004 executability checks that require ResultPacket metric names."""

from __future__ import annotations

from dataclasses import replace

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    HypothesisSpec,
    HypothesisValidation,
    ResearchEpisodeInput,
    ValidationStatus,
)
from futures_agent_os.research_experiment.mvp_r_003.hypothesis_validator import HypothesisValidator

from .contracts import PACKET_CONTROL, PACKET_PRIMARY_METRICS


class MvpR004HypothesisValidator:
    """Rejects v1 aliases that do not exist on the replay ResultPacket."""

    def validate(self, episode: ResearchEpisodeInput, hypothesis: HypothesisSpec) -> HypothesisValidation:
        base = HypothesisValidator().validate(episode, hypothesis)
        extra: list[str] = []
        metric_resolved = hypothesis.primary_metric in PACKET_PRIMARY_METRICS
        control_resolved = hypothesis.control == PACKET_CONTROL
        if not metric_resolved:
            extra.append("PRIMARY_METRIC_NOT_IN_RESULT_PACKET")
        if not control_resolved:
            extra.append("UNSUPPORTED_CONTROL")
        if not extra:
            return replace(base, metric_resolved=True, control_resolved=True)
        reasons = tuple(sorted({code for code in base.reason_codes if code != "EXECUTABLE"} | set(extra)))
        return replace(
            base,
            status=ValidationStatus.UNSUPPORTED,
            reason_codes=reasons,
            metric_resolved=metric_resolved,
            control_resolved=control_resolved,
        )
