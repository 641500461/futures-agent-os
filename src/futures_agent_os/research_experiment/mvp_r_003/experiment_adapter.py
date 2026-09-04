"""Thin adapter from one selected hypothesis to the existing V1-010 replay tools."""

from __future__ import annotations

from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment.mvp_replay import issue_replay_tool_results
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.mvp_validation import AgentEpisodeView, RetrospectiveMarketWindow
from futures_agent_os.research_experiment.validation_tools import (
    ResearchToolName,
    ToolFailureCode,
    TrustedResearchToolsPort,
    ValidationConfig,
    semantic_entity_id,
)

from .contracts import (
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    HypothesisSpec,
    ResearchEpisodeInput,
    ToolRunResult,
    ValidationStatus,
)
from .hypothesis_validator import HypothesisValidator
from .treatment_binding import bind_tool_runs_to_hypothesis, hypothesis_direction


_EXPERIMENT_TOOLS = (
    ResearchToolName.L0_SIGNAL_TEST,
    ResearchToolName.L1_BAR_BACKTEST,
    ResearchToolName.WALK_FORWARD,
    ResearchToolName.COST_STRESS,
    ResearchToolName.COUNTERFACTUAL,
)


class MvpR003ExperimentAdapter:
    """Instantiates and executes one bounded, synchronous, non-trading experiment."""

    def instantiate(
        self,
        episode: ResearchEpisodeInput,
        hypothesis: HypothesisSpec,
        config: ValidationConfig,
        *,
        code_ref: str,
    ) -> ExecutableExperimentPlan:
        if type(config) is not ValidationConfig:
            raise TypeError("experiment adapter requires the existing V1-010 ValidationConfig")
        validation = HypothesisValidator().validate(episode, hypothesis)
        if validation.status is not ValidationStatus.EXECUTABLE:
            raise ValueError(f"hypothesis is not executable: {','.join(validation.reason_codes)}")
        threshold = dict(hypothesis.parameters)["threshold"]
        if threshold != format(config.signal_threshold, "f"):
            raise ValueError("hypothesis threshold must exactly match the frozen V1-010 config")
        plan_seed = {
            "episode": episode.content_sha256,
            "hypothesis": hypothesis.content_sha256,
            "config": config.content_sha256,
            "code_ref": code_ref,
        }
        plan_id = f"mvp-r-003-{semantic_entity_id('experiment_plan', plan_seed).value}"
        return ExecutableExperimentPlan(
            plan_id=plan_id,
            hypothesis_ref=hypothesis.identity,
            dataset_ref=episode.dataset_ref.uri,
            window="all PIT-visible final daily bars through market_cutoff",
            train_bars=config.train_bars,
            test_bars=config.test_bars,
            step_bars=config.step_bars,
            embargo_bars=1,
            tool_requests=tuple(item.value for item in _EXPERIMENT_TOOLS),
            primary_metric=hypothesis.primary_metric,
            control=hypothesis.control,
            stop_rule=(
                f"stop after {config.stop_after_failures} consecutive OOS folds below "
                f"minimum_signal_accuracy; folds are authentic walk-forward test windows, "
                f"not equal-length partitions of full-window signals"
            ),
            config_ref=f"validation-config://{config.content_sha256}",
            code_ref=code_ref,
            tradable=False,
        )

    def execute_replay(
        self,
        *,
        plan: ExecutableExperimentPlan,
        episode: AgentEpisodeView,
        window: RetrospectiveMarketWindow,
        records: tuple[PointInTimeRecord, ...],
        market_state: EpisodeStratum,
        config: ValidationConfig,
        result_authority: TrustedResearchToolsPort,
        hypothesis: HypothesisSpec,
    ) -> ExperimentResultPacket:
        if plan.config_ref != f"validation-config://{config.content_sha256}":
            raise ValueError("experiment plan does not bind the supplied V1-010 config")
        if plan.dataset_ref == "" or episode.market_cutoff != window.market_cutoff:
            raise ValueError("experiment plan and replay episode are inconsistent")
        if hypothesis.identity != plan.hypothesis_ref:
            raise ValueError("experiment plan does not bind the supplied hypothesis")
        if (plan.train_bars, plan.test_bars, plan.step_bars) != (
            config.train_bars,
            config.test_bars,
            config.step_bars,
        ):
            raise ValueError("experiment plan walk-forward bounds do not bind ValidationConfig")
        direction = hypothesis_direction(hypothesis)
        results = issue_replay_tool_results(
            episode=episode,
            window=window,
            records=records,
            market_state=market_state,
            request_sha256=plan.content_sha256,
            config=config,
            run_id=semantic_entity_id("research_validation_run", {"plan": plan.content_sha256}),
            result_authority=result_authority,
            embargo_bars=plan.embargo_bars,
        )
        by_tool = {result.tool: result for result in results}
        selected = tuple(by_tool[tool] for tool in _EXPERIMENT_TOOLS)
        raw_runs = tuple(
            ToolRunResult(
                tool=result.tool.value,
                status="SUCCESS" if result.failure_code is ToolFailureCode.NONE else "FAILED",
                metrics=result.metrics,
                warnings=result.warnings,
                source_refs=(
                    f"research-tool-result://{result.content_sha256}",
                    *(f"artifact://{source.content_sha256}" for source in result.source_refs),
                ),
            )
            for result in selected
        )
        tool_runs = bind_tool_runs_to_hypothesis(
            raw_runs,
            hypothesis=hypothesis,
            plan_hypothesis_ref=plan.hypothesis_ref,
            config=config,
        )
        packet_id = f"mvp-r-003-{semantic_entity_id('experiment_result', {'plan': plan.content_sha256, 'direction': direction}).value}"
        return ExperimentResultPacket(
            packet_id=packet_id,
            plan_ref=plan.identity,
            tool_runs=tool_runs,
            limitations=(
                "L0 direction sanity check is not a trading claim",
                "L1 uses daily-bar directional approximation without fill semantics",
                "component rolls are unadjusted when present",
                "raw deterministic tools compute FOLLOW prior-close signals and remain untransformed",
                "treatment-relative metrics live on mvp-r-005.treatment-metric-view.v1, not raw ToolRunResult",
                "walk-forward fold_N metrics are authentic OOS test windows from the frozen planner",
                "minimum_samples constrains train_bars/full-window eligibility, not OOS sample count",
            ),
            complete=all(run.status == "SUCCESS" for run in tool_runs),
            evaluator_future_data_present=False,
        )
