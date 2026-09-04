"""Structured workload fixtures for MVP-R-003 model behavior."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from futures_agent_os.research_experiment.mvp_r_003 import CriticDecision, FinalVerdict
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import (
    MvpR003ModelWorkloads,
    StructuredModelConfig,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "contract"))

from test_mvp_r_003_contracts import episode, hypothesis, result_packet  # noqa: E402


CONFIG = StructuredModelConfig("gpt-5.6-terra", "medium")


def response(value: Mapping[str, object], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "response_id": "response-001",
        "model": CONFIG.model,
        "model_provider": "openai",
        "status": "completed",
        "reasoning_effort": CONFIG.reasoning_effort,
        "usage": {
            "inputTokens": 100,
            "cachedInputTokens": 0,
            "outputTokens": 50,
            "reasoningOutputTokens": 10,
            "cacheWriteInputTokens": 0,
            "totalTokens": 150,
        },
        "final_texts": (json.dumps(value, sort_keys=True, separators=(",", ":")),),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("reasoning", "agentMessage"),
        "reroutes": (),
        "timed_out": False,
        "latencyMs": 25,
    }
    payload.update(overrides)
    return payload


def hypothesis_response() -> dict[str, object]:
    common = {
        "market_condition": "range-bound daily market",
        "threshold": "0.010",
        "expected_observable": "out-of-sample directional accuracy above the inverted control",
        "falsification_condition": "reject if stressed walk-forward evidence does not beat the inverted control",
        "supporting_evidence_refs": ["metric://1"],
        "strongest_counter_evidence_refs": ["metric://2"],
        "unknowns": ["regime persistence"],
        "primary_metric": "accuracy",
        "control": "inverted signal direction",
        "cost_assumption_ref": "cost://e",
    }
    return {
        "hypotheses": [
            {**common, "family": "MOMENTUM_CONTINUATION", "direction": "FOLLOW"},
            {**common, "family": "MEAN_REVERSION", "direction": "INVERT"},
        ]
    }


def critic_response() -> dict[str, object]:
    return {
        "decision": "SELECT",
        "checks": {
            "leakage": "PASS",
            "cost": "PASS",
            "sample": "UNKNOWN",
            "regime": "UNKNOWN",
            "falsifiability": "PASS",
            "multiple_testing": "PASS",
        },
        "reason_codes": ["BOUNDED_BUT_SAMPLE_LIMITED"],
        "source_refs": ["metric://1", "metric://2"],
    }


def test_three_workloads_are_structured_grounded_and_tool_free() -> None:
    outputs = iter(
        (
            response(hypothesis_response()),
            response(critic_response()),
            response(
                {
                    "verdict": "ACCEPT",
                    "rationale": "Observed deterministic results satisfy the registered condition.",
                    "modified_direction": None,
                    "modified_threshold": None,
                }
            ),
        )
    )
    workloads = MvpR003ModelWorkloads(lambda _request: next(outputs))

    hypotheses, generation_receipt = workloads.generate_hypotheses(episode(), CONFIG)
    review, critic_receipt = workloads.critique(episode(), hypotheses[0], CONFIG)
    verdict, verdict_receipt = workloads.final_verdict(hypotheses[0], result_packet(), CONFIG)

    assert len(hypotheses) == 2
    assert review.decision is CriticDecision.SELECT
    assert verdict.verdict is FinalVerdict.ACCEPT
    assert {generation_receipt.workload, critic_receipt.workload, verdict_receipt.workload} == {
        "hypothesis_generation",
        "independent_critic",
        "result_feedback",
    }


def test_final_verdict_receives_results_and_changes_under_counter_evidence() -> None:
    def sensitive_transport(request: Mapping[str, object]) -> Mapping[str, object]:
        model_input = json.loads(str(request["input"]))
        metrics = model_input["experiment_result"]["tool_runs"][0]["metrics"]
        supported = ["accuracy", "0.60000000"] in metrics
        return response(
            {
                "verdict": "ACCEPT" if supported else "REJECT",
                "rationale": "Verdict follows the supplied deterministic result packet.",
                "modified_direction": None,
                "modified_threshold": None,
            }
        )

    workloads = MvpR003ModelWorkloads(sensitive_transport)
    supported, _ = workloads.final_verdict(hypothesis(), result_packet(), CONFIG)
    contradicted_packet = result_packet()
    contradicted_run = contradicted_packet.tool_runs[0]
    contradicted_packet = type(contradicted_packet)(
        packet_id="packet-contradicted",
        plan_ref=contradicted_packet.plan_ref,
        tool_runs=(
            type(contradicted_run)(
                tool=contradicted_run.tool,
                status=contradicted_run.status,
                metrics=(("accuracy", "0.20000000"),),
                warnings=contradicted_run.warnings,
                source_refs=contradicted_run.source_refs,
            ),
            *contradicted_packet.tool_runs[1:],
        ),
        limitations=contradicted_packet.limitations,
        complete=True,
        evaluator_future_data_present=False,
    )
    contradicted, _ = workloads.final_verdict(hypothesis(), contradicted_packet, CONFIG)

    assert supported.verdict is FinalVerdict.ACCEPT
    assert contradicted.verdict is FinalVerdict.REJECT


def test_model_workload_fails_closed_on_tool_activity_or_ungrounded_critic() -> None:
    workloads = MvpR003ModelWorkloads(
        lambda _request: response(hypothesis_response(), dynamic_calls=({"name": "shell"},))
    )
    with pytest.raises(RuntimeError, match="failed closed"):
        workloads.generate_hypotheses(episode(), CONFIG)

    critic = MvpR003ModelWorkloads(
        lambda _request: response({**critic_response(), "source_refs": ["metric://invented"]})
    )
    with pytest.raises(ValueError, match="ungrounded"):
        critic.critique(episode(), hypothesis(), CONFIG)


def test_demo_cli_renders_auditable_json_and_user_report_without_model(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "run_mvp_r_003_demo.py"),
            "--fixture",
            str(root / "tests" / "fixtures" / "mvp_r_003" / "episode-001.json"),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
        cwd=root,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    evidence = json.loads(Path(summary["json_report"]).read_text(encoding="utf-8"))
    report = Path(summary["markdown_report"]).read_text(encoding="utf-8")
    assert evidence["execution_mode"] == "FIXTURE_RENDER_ONLY"
    assert evidence["model_receipts"] == []
    assert "Experiment-pre judgment" in report
    assert "Independent Critic" in report
    assert "Deterministic experiment results" in report
    assert "Experiment-post judgment" in report
