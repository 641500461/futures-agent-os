from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from futures_agent_os.research_experiment.mvp_r_003.model_workloads import (
    ModelWorkloadObservationError,
    MvpR003ModelWorkloads,
    StructuredModelConfig,
)
from futures_agent_os.research_experiment.mvp_r_005 import R005CorrectionV3EpisodeOutcome
from futures_agent_os.research_experiment.mvp_r_005.formal_eval import (
    FormalEvalPhase,
    compute_formal_automated_gate,
    freeze_blind_selection,
)


def _passing_outcome(index: int) -> R005CorrectionV3EpisodeOutcome:
    return R005CorrectionV3EpisodeOutcome(
        episode_id=f"formal-{index:03d}",
        instrument="SHFE.AG.DOMINANT_OI",
        stratum="UP_TREND",
        market_cutoff=f"2026-06-{(index % 28) + 1:02d}T07:00:00Z",
        complete=True,
        agent_loop_complete=True,
        agent_experiment_complete=True,
        single_prompt_complete=True,
        raw_tool_result_lineage=True,
        predicate_metric_binding=True,
        verdict_predicate_congruent=True,
        four_block_report=True,
        pre_experiment_critic_gate=False,
        critic_blocked_experiment=False,
        overlapping_predecessor=False,
        stopped_folds_invisible=True,
        treatment_view_bound=True,
        agent_verdict="REJECT",
        single_prompt_verdict="REJECT",
        deterministic_agent_outcome="REJECT",
        deterministic_single_outcome="REJECT",
    )


@pytest.mark.parametrize(
    ("phase", "count", "token_limit", "decision"),
    (
        (FormalEvalPhase.DIAGNOSTIC, 30, 4_000_000, "FORMAL_DIAGNOSTIC_PASS"),
        (FormalEvalPhase.HOLDOUT, 50, 7_000_000, "FORMAL_HOLDOUT_PASS"),
    ),
)
def test_formal_gate_passes_only_frozen_phase_size(
    phase: FormalEvalPhase,
    count: int,
    token_limit: int,
    decision: str,
) -> None:
    gate = compute_formal_automated_gate(
        tuple(_passing_outcome(index) for index in range(count)),
        phase=phase,
        total_tokens=token_limit,
        model_wall_time_ms=1,
        critical_fail_closed=4,
        predecessor_hashes_match=True,
    )

    assert gate["decision"] == decision
    assert gate["hardcoded"] is False
    assert gate["go"] is False


def test_formal_gate_allows_one_explicit_failed_episode_but_not_bad_completed_artifact() -> None:
    outcomes = tuple(_passing_outcome(index) for index in range(30))
    one_failed = replace(
        outcomes[-1],
        complete=False,
        agent_loop_complete=False,
        agent_experiment_complete=False,
        single_prompt_complete=False,
        raw_tool_result_lineage=False,
        predicate_metric_binding=False,
        verdict_predicate_congruent=False,
        four_block_report=False,
        stopped_folds_invisible=False,
        treatment_view_bound=False,
        agent_verdict=None,
        single_prompt_verdict=None,
        deterministic_agent_outcome=None,
        deterministic_single_outcome=None,
    )
    gate = compute_formal_automated_gate(
        (*outcomes[:-1], one_failed),
        phase=FormalEvalPhase.DIAGNOSTIC,
        total_tokens=1,
        model_wall_time_ms=1,
        critical_fail_closed=4,
        predecessor_hashes_match=True,
    )
    assert gate["decision"] == "FORMAL_DIAGNOSTIC_PASS"

    bad_completed = replace(outcomes[-1], treatment_view_bound=False)
    gate = compute_formal_automated_gate(
        (*outcomes[:-1], bad_completed),
        phase=FormalEvalPhase.DIAGNOSTIC,
        total_tokens=1,
        model_wall_time_ms=1,
        critical_fail_closed=4,
        predecessor_hashes_match=True,
    )
    assert gate["decision"] == "FORMAL_DIAGNOSTIC_FAIL"


@pytest.mark.parametrize(
    "changes",
    (
        {"pre_experiment_critic_gate": True},
        {"critic_blocked_experiment": True},
        {"overlapping_predecessor": True},
    ),
)
def test_formal_gate_fails_closed_on_product_boundary_violation(changes: dict[str, bool]) -> None:
    outcomes = tuple(_passing_outcome(index) for index in range(30))
    gate = compute_formal_automated_gate(
        (replace(outcomes[0], **changes), *outcomes[1:]),
        phase=FormalEvalPhase.DIAGNOSTIC,
        total_tokens=1,
        model_wall_time_ms=1,
        critical_fail_closed=4,
        predecessor_hashes_match=True,
    )
    assert gate["decision"] == "FORMAL_DIAGNOSTIC_FAIL"


def test_formal_gate_rejects_wrong_size_or_budget() -> None:
    with pytest.raises(ValueError, match="exactly 50"):
        compute_formal_automated_gate(
            tuple(_passing_outcome(index) for index in range(49)),
            phase=FormalEvalPhase.HOLDOUT,
            total_tokens=1,
            model_wall_time_ms=1,
            critical_fail_closed=4,
            predecessor_hashes_match=True,
        )
    gate = compute_formal_automated_gate(
        tuple(_passing_outcome(index) for index in range(50)),
        phase=FormalEvalPhase.HOLDOUT,
        total_tokens=7_000_001,
        model_wall_time_ms=1,
        critical_fail_closed=4,
        predecessor_hashes_match=True,
    )
    assert gate["decision"] == "FORMAL_HOLDOUT_FAIL"


def test_blind_selection_is_deterministic_balanced_and_requires_completed_holdout() -> None:
    ids = tuple(f"formal-holdout-{index:03d}" for index in range(50))
    first = freeze_blind_selection(ids, seed="mvp-r-formal-shadow-v1")
    second = freeze_blind_selection(tuple(reversed(ids)), seed="mvp-r-formal-shadow-v1")

    assert first == second
    assert len(first) == 10
    assert len({item.episode_id for item in first}) == 10
    assert sum(item.agent_label == "A" for item in first) == 5
    with pytest.raises(ValueError, match="at least 10"):
        freeze_blind_selection(ids[:9], seed="mvp-r-formal-shadow-v1")


def test_workload_observation_failure_preserves_safe_reason_codes_without_model_text() -> None:
    response = {
        "response_id": "response-one",
        "status": "completed",
        "model_provider": "openai",
        "model": "gpt-5.6-terra",
        "timed_out": False,
        "reroutes": (),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("agentMessage",),
        "final_texts": ('{"secret_model_text":"must-not-be-persisted"}',),
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
    }
    workloads = MvpR003ModelWorkloads(lambda _request: response)

    with pytest.raises(ModelWorkloadObservationError) as raised:
        workloads._invoke(
            "probe",
            "instructions",
            {"input": "value"},
            {"type": "object"},
            StructuredModelConfig("gpt-5.6-terra", "xhigh"),
        )

    evidence = raised.value.evidence_payload()
    assert evidence["reason_codes"] == ("EFFORT_NOT_OBSERVED",)
    observation = cast(dict[str, object], evidence["observation"])
    assert observation["reasoning_effort"] is None
    assert observation["final_text_count"] == 1
    assert "secret_model_text" not in json.dumps(evidence)


def test_workload_observation_accepts_explicit_app_server_provider_label() -> None:
    response = {
        "response_id": "response-sol",
        "status": "completed",
        "model_provider": "custom",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "timed_out": False,
        "reroutes": (),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("agentMessage",),
        "final_texts": ('{"ok":true}',),
        "usage": {
            "inputTokens": 1,
            "outputTokens": 1,
            "reasoningOutputTokens": 0,
            "totalTokens": 2,
        },
        "latencyMs": 1,
    }
    value, receipt = MvpR003ModelWorkloads(lambda _request: response)._invoke(
        "probe",
        "instructions",
        {"input": "value"},
        {"type": "object"},
        StructuredModelConfig("gpt-5.6-sol", "high", expected_provider="custom"),
    )
    assert value == {"ok": True}
    assert receipt.model == "gpt-5.6-sol"


def test_failure_writer_includes_structured_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "scripts"))
    import run_mvp_r_005 as r005

    monkeypatch.setattr(r005, "EVIDENCE_ROOT", tmp_path)
    error = ModelWorkloadObservationError(
        ("EFFORT_NOT_OBSERVED",),
        {"response_id": "response-one", "raw_response_sha256": "a" * 64},
    )
    r005._write_failure("formal-diagnostic-probe", error)

    payload = json.loads((tmp_path / "formal-diagnostic-probe-attempt-1-failure.json").read_text())
    assert payload["schema_version"] == "mvp-r-005.discovery-failure.v2"
    assert payload["diagnostics"]["reason_codes"] == ["EFFORT_NOT_OBSERVED"]
    assert payload["counts_as_completed_episode"] is False
