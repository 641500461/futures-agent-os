"""Render one explicit MVP-R-003 fixture or opt into isolated model smoke turns."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Mapping, cast

from futures_agent_os.adapters import OfficialCodexAppServerTransport
from futures_agent_os.research_experiment import ValidationConfig
from futures_agent_os.research_experiment.mvp_r_003 import (
    ArtifactRef,
    CriticDecision,
    CriticReview,
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisFamily,
    HypothesisSpec,
    HypothesisValidator,
    MvpR003ExperimentAdapter,
    MvpR003ModelWorkloads,
    ModelWorkloadReceipt,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
    StructuredModelConfig,
    ToolRunResult,
)
from futures_agent_os.research_experiment.mvp_r_003.reporting import ResearchEpisodeReport
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evidence" / "mvp-r-003" / "demo")
    parser.add_argument("--execute-model", action="store_true")
    parser.add_argument("--research-model", default="gpt-5.6-terra")
    parser.add_argument("--critic-model", default="gpt-5.6-sol")
    parser.add_argument("--feedback-model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="xhigh")
    args = parser.parse_args()

    payload = _mapping(json.loads(args.fixture.read_text(encoding="utf-8")))
    report = build_report(
        payload,
        execute_model=args.execute_model,
        research_model=args.research_model,
        critic_model=args.critic_model,
        feedback_model=args.feedback_model,
        effort=args.effort,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{report.episode.episode_id}.json"
    markdown_path = args.output_dir / f"{report.episode.episode_id}.md"
    json_path.write_text(canonical_json_text(report.to_dict()) + "\n", encoding="utf-8")
    markdown_path.write_text(report.render_markdown(), encoding="utf-8")
    print(
        canonical_json_text(
            {
                "execution_mode": report.execution_mode,
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
                "verdict": report.final_verdict.verdict.value,
            }
        )
    )


def build_report(
    payload: Mapping[str, object],
    *,
    execute_model: bool,
    research_model: str,
    critic_model: str,
    feedback_model: str,
    effort: str,
) -> ResearchEpisodeReport:
    if payload.get("fixture_notice") != "DETERMINISTIC_RENDER_FIXTURE_ONLY_NOT_DISCOVERY_EVIDENCE":
        raise ValueError("demo input must explicitly identify itself as a non-Discovery fixture")
    episode = _episode(payload)
    config = _validation_config(_text(payload, "threshold"))
    receipts: tuple[ModelWorkloadReceipt, ...] = ()
    if execute_model:
        workloads = MvpR003ModelWorkloads(OfficialCodexAppServerTransport())
        hypotheses, generation_receipt = workloads.generate_hypotheses(
            episode, StructuredModelConfig(research_model, effort)
        )
        selected = hypotheses[0]
        review, critic_receipt = workloads.critique(episode, selected, StructuredModelConfig(critic_model, effort))
        reviews = (review,)
        receipts = (generation_receipt, critic_receipt)
    else:
        selected = _fixture_hypothesis(episode, payload, 1, HypothesisFamily.MOMENTUM_CONTINUATION)
        alternate = _fixture_hypothesis(episode, payload, 2, HypothesisFamily.MEAN_REVERSION)
        alternate = replace(
            alternate,
            parameters=(("direction", "INVERT"), ("threshold", _text(payload, "threshold"))),
        )
        hypotheses = (selected, alternate)
        reviews = (_fixture_review(episode, selected),)
    validations = tuple(HypothesisValidator().validate(episode, item) for item in hypotheses)
    plan = MvpR003ExperimentAdapter().instantiate(episode, selected, config, code_ref="fixture-render-v1")
    result = _fixture_result(plan, payload)
    if execute_model:
        final, feedback_receipt = workloads.final_verdict(
            selected, result, StructuredModelConfig(feedback_model, effort)
        )
        receipts = (*receipts, feedback_receipt)
        mode = "FIXTURE_MODEL_SMOKE_NOT_DISCOVERY"
    else:
        final = _fixture_verdict(selected, result, payload)
        mode = "FIXTURE_RENDER_ONLY"
    return ResearchEpisodeReport(
        mode,
        episode,
        hypotheses,
        validations,
        reviews,
        selected,
        plan,
        result,
        final,
        receipts,
    )


def _episode(payload: Mapping[str, object]) -> ResearchEpisodeInput:
    episode_id = _text(payload, "episode_id")

    def ref(kind: str, uri: str) -> ArtifactRef:
        return ArtifactRef(kind, uri, canonical_sha256({"fixture": episode_id, "kind": kind}))

    evidence = (ref("metric", "metric://1"), ref("metric", "metric://2"))
    return ResearchEpisodeInput(
        episode_id=episode_id,
        instrument=_text(payload, "instrument"),
        as_of=_text(payload, "as_of"),
        market_cutoff=_text(payload, "market_cutoff"),
        acquired_at=_text(payload, "acquired_at"),
        dataset_ref=ref("dataset", f"dataset://{episode_id}"),
        market_snapshot_ref=ref("market_snapshot", f"market-snapshot://{episode_id}"),
        feature_ref=ref("feature", f"feature://{episode_id}"),
        rule_ref=ref("rule", "rule://prior-close-return-threshold"),
        cost_ref=ref("cost", "cost://fixture"),
        toolset_ref=ref("toolset", "toolset://mvp-r-003-v1-010"),
        signal_operators=(SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,),
        allowed_parameter_values=(
            ("direction", ("FOLLOW", "INVERT")),
            ("threshold", (_text(payload, "threshold"),)),
        ),
        market_state=_text(payload, "market_state"),
        warnings=("fixture values are not Discovery Evidence",),
        unknowns=("fixture has no claim of external validity",),
        evidence_refs=evidence,
        tradable=False,
        future_result_present=False,
    )


def _fixture_hypothesis(
    episode: ResearchEpisodeInput,
    payload: Mapping[str, object],
    index: int,
    family: HypothesisFamily,
) -> HypothesisSpec:
    return HypothesisSpec(
        hypothesis_id=f"{episode.episode_id}-h{index}",
        version=1,
        family=family,
        market_condition=episode.market_state,
        signal_operator=SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,
        parameters=(("direction", _text(payload, "direction")), ("threshold", _text(payload, "threshold"))),
        expected_observable="signal accuracy exceeds the inverted-direction control",
        falsification_condition="reject if stressed or counterfactual evidence removes the registered advantage",
        supporting_evidence_refs=("metric://1",),
        strongest_counter_evidence_refs=("metric://2",),
        unknowns=episode.unknowns,
        primary_metric="accuracy",
        control="inverted signal direction",
        cost_assumption_ref=episode.cost_ref.uri,
        tradable=False,
    )


def _fixture_review(episode: ResearchEpisodeInput, hypothesis: HypothesisSpec) -> CriticReview:
    return CriticReview(
        review_id=f"{episode.episode_id}-fixture-critic",
        hypothesis_id=hypothesis.hypothesis_id,
        decision=CriticDecision.SELECT,
        checks=tuple(
            (name, "PASS" if name in {"leakage", "cost", "falsifiability"} else "UNKNOWN")
            for name in ("leakage", "cost", "sample", "regime", "falsifiability", "multiple_testing")
        ),
        reason_codes=("FIXTURE_BOUNDED_BUT_NOT_DISCOVERY_EVIDENCE",),
        source_refs=("metric://1", "metric://2"),
    )


def _validation_config(threshold: str) -> ValidationConfig:
    return ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-003", "fixture": 1}),
        1,
        20,
        5,
        5,
        20,
        Decimal(threshold),
        Decimal("2.00000000"),
        Decimal("1.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )


def _fixture_result(plan: ExecutableExperimentPlan, payload: Mapping[str, object]) -> ExperimentResultPacket:
    metric_map = {
        "l0_signal_test": (
            ("signal_accuracy", _text(payload, "signal_accuracy")),
            ("counterfactual_signal_accuracy", _text(payload, "counterfactual_signal_accuracy")),
        ),
        "l1_bar_backtest": (("proxy_net_return", "0.04000000"),),
        "walk_forward_test": (("positive_fold_ratio", "0.66666667"),),
        "cost_slippage_stress": (("stressed_net_return", _text(payload, "stressed_net_return")),),
        "counterfactual_test": (
            ("counterfactual_stressed_net_return", _text(payload, "counterfactual_stressed_net_return")),
        ),
    }
    return ExperimentResultPacket(
        packet_id=f"{_text(payload, 'episode_id')}-fixture-packet",
        plan_ref=plan.identity,
        tool_runs=tuple(
            ToolRunResult(tool, "SUCCESS", metric_map[tool], (), ("fixture://render-only",))
            for tool in plan.tool_requests
        ),
        limitations=("render fixture; no Discovery experiment was executed",),
        complete=True,
        evaluator_future_data_present=False,
    )


def _fixture_verdict(
    hypothesis: HypothesisSpec,
    result: ExperimentResultPacket,
    payload: Mapping[str, object],
) -> ResearchFinalVerdict:
    supported = Decimal(_text(payload, "signal_accuracy")) > Decimal(
        _text(payload, "counterfactual_signal_accuracy")
    ) and Decimal(_text(payload, "stressed_net_return")) > Decimal(_text(payload, "counterfactual_stressed_net_return"))
    return ResearchFinalVerdict(
        verdict_id=f"{_text(payload, 'episode_id')}-fixture-verdict",
        verdict=FinalVerdict.ACCEPT if supported else FinalVerdict.REJECT,
        hypothesis_ref=hypothesis.identity,
        falsification_condition=hypothesis.falsification_condition,
        result_refs=(result.identity,),
        rationale="Fixture metrics support the registered comparison."
        if supported
        else "Fixture counter-evidence wins.",
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError("fixture requires a JSON object")
    return cast(Mapping[str, object], value)


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if type(item) is not str or not item:
        raise ValueError(f"fixture {key} requires text")
    return item


if __name__ == "__main__":
    main()
