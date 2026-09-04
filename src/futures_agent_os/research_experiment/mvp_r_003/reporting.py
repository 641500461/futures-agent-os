"""Auditable JSON and concise user-report rendering for one research episode."""

from __future__ import annotations

from dataclasses import dataclass

from futures_agent_os.shared_kernel.observability import JsonValue

from .contracts import (
    CriticReview,
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    HypothesisSpec,
    HypothesisValidation,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
)
from .model_workloads import ModelWorkloadReceipt


@dataclass(frozen=True, slots=True)
class ResearchEpisodeReport:
    execution_mode: str
    episode: ResearchEpisodeInput
    hypotheses: tuple[HypothesisSpec, ...]
    validations: tuple[HypothesisValidation, ...]
    critic_reviews: tuple[CriticReview, ...]
    selected_hypothesis: HypothesisSpec
    experiment_plan: ExecutableExperimentPlan
    experiment_result: ExperimentResultPacket
    final_verdict: ResearchFinalVerdict
    model_receipts: tuple[ModelWorkloadReceipt, ...] = ()

    def __post_init__(self) -> None:
        if self.execution_mode not in {
            "FIXTURE_RENDER_ONLY",
            "FIXTURE_MODEL_SMOKE_NOT_DISCOVERY",
            "DISCOVERY_EXECUTED",
        }:
            raise ValueError("report requires an explicit execution mode")
        if self.selected_hypothesis not in self.hypotheses:
            raise ValueError("selected hypothesis must come from the proposed batch")
        if self.experiment_plan.hypothesis_ref != self.selected_hypothesis.identity:
            raise ValueError("experiment plan must bind the selected hypothesis")
        if self.experiment_result.plan_ref != self.experiment_plan.identity:
            raise ValueError("experiment result must bind the exact plan")
        if self.final_verdict.hypothesis_ref != self.selected_hypothesis.identity:
            raise ValueError("final verdict must bind the selected hypothesis")
        if self.experiment_result.identity not in self.final_verdict.result_refs:
            raise ValueError("final verdict must cite the experiment result")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": "mvp-r-003.episode-report.v1",
            "execution_mode": self.execution_mode,
            "episode": self.episode.to_dict(),
            "hypotheses": tuple(item.to_dict() for item in self.hypotheses),
            "validations": tuple(item.to_dict() for item in self.validations),
            "critic_reviews": tuple(item.to_dict() for item in self.critic_reviews),
            "selected_hypothesis": self.selected_hypothesis.to_dict(),
            "experiment_plan": self.experiment_plan.to_dict(),
            "experiment_result": self.experiment_result.to_dict(),
            "final_verdict": self.final_verdict.to_dict(),
            "model_receipts": tuple(
                {
                    "workload": item.workload,
                    "response_id": item.response_id,
                    "model": item.model,
                    "reasoning_effort": item.reasoning_effort,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "reasoning_tokens": item.reasoning_tokens,
                    "latency_ms": item.latency_ms,
                    "request_sha256": item.request_sha256,
                    "response_sha256": item.response_sha256,
                    "receipt_sha256": item.content_sha256,
                }
                for item in self.model_receipts
            ),
        }

    def render_markdown(self) -> str:
        metrics = "\n".join(
            f"- `{run.tool}`: " + ", ".join(f"`{name}={value}`" for name, value in run.metrics)
            for run in self.experiment_result.tool_runs
        )
        critic = "\n".join(
            f"- `{review.decision.value}`: {', '.join(review.reason_codes)}" for review in self.critic_reviews
        )
        return (
            f"# MVP-R-003 Research Episode {self.episode.episode_id}\n\n"
            f"Execution mode: `{self.execution_mode}`\n\n"
            "This report is research and simulation only. It is not a trade, order, position, "
            "risk decision, fill, or ledger fact.\n\n"
            "## Experiment-pre judgment\n\n"
            f"- Instrument / cutoff: `{self.episode.instrument}` / `{self.episode.market_cutoff}`\n"
            f"- Selected hypothesis: {self.selected_hypothesis.expected_observable}\n"
            f"- Falsification condition: {self.selected_hypothesis.falsification_condition}\n\n"
            "## Independent Critic\n\n"
            f"{critic}\n\n"
            "## Deterministic experiment results\n\n"
            f"{metrics}\n\n"
            "## Experiment-post judgment\n\n"
            f"- Verdict: `{self.final_verdict.verdict.value}`\n"
            f"- Rationale: {self.final_verdict.rationale}\n"
            f"- Result reference: `{self.experiment_result.identity}`\n\n"
            "## Limitations\n\n" + "\n".join(f"- {item}" for item in self.experiment_result.limitations) + "\n"
        )
