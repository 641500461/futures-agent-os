"""MVP-R-005 correction-v4: symmetric view rebuild and honest packet lineage."""

from __future__ import annotations

from dataclasses import replace

from futures_agent_os.research_experiment.mvp_r_005 import (
    R005CorrectionV3EpisodeOutcome,
    build_treatment_metric_view,
    compute_r005_correction_v4_gate,
)
from futures_agent_os.research_experiment.mvp_r_005.artifact_checks import assess_correction_v3_episode

from test_mvp_r_003_contracts import plan
from test_mvp_r_005_correction_v3_contracts import (
    _arm_payload,
    _raw_three_fold_packet,
    _typed_hypothesis,
    _validation_config,
)


def _case():
    hypothesis = replace(
        _typed_hypothesis(),
        parameters=(("direction", "INVERT"), ("threshold", "0.010")),
    )
    config = _validation_config()
    bound_plan = replace(
        plan(),
        hypothesis_ref=hypothesis.identity,
        primary_metric="signal_accuracy",
        config_ref=f"validation-config://{config.content_sha256}",
    )
    packet = _raw_three_fold_packet(bound_plan.identity)
    view = build_treatment_metric_view(packet, hypothesis=hypothesis, plan=bound_plan, config=config)
    payload = _arm_payload(hypothesis, bound_plan, packet, view, "REJECT")
    roster = {
        "episode_id": "r005-ag-noise",
        "instrument": "SHFE.AG.DOMINANT_OI",
        "stratum": "NOISE",
        "market_cutoff": "2026-08-06T07:00:00Z",
    }
    markdown = (
        "# 研究决策简报 r005-ag-noise\n\n研究与模拟，不是交易指令。\n\n"
        "## 测了什么\n\n测了假设\n\n## 结果怎样\n\n失败\n\n"
        "## 当前判断\n\n`REJECT` 拒绝\n\n## 下一步动作\n\n停止\n"
    )
    return hypothesis, config, bound_plan, packet, view, payload, roster, markdown


def _assess(agent, single, roster, markdown, config):
    return assess_correction_v3_episode(
        roster_item=roster,
        agent_payload=agent,
        single_payload=single,
        agent_markdown=markdown,
        overlapping_predecessor=False,
        config=config,
    )


def test_validly_rehashed_single_prompt_view_tamper_fails_gate() -> None:
    _, config, _, _, view, agent, roster, markdown = _case()
    metrics = tuple((name, "0.10000000" if name == "fold_1_signal_accuracy" else value) for name, value in view.metrics)
    tampered = replace(view, metrics=metrics)
    assert tampered.content_sha256 != view.content_sha256
    single = {**agent, "treatment_metric_view": tampered.to_dict(), "agent_visible_experiment": tampered.to_dict()}

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.treatment_view_bound is False
    assert outcome.raw_packet_to_view_lineage is False


def test_agent_visible_payload_must_equal_bound_view_for_both_arms() -> None:
    _, config, _, _, view, agent, roster, markdown = _case()
    visible_metrics = tuple(
        (name, "0.10000000" if name == "fold_1_signal_accuracy" else value) for name, value in view.metrics
    )
    single = {**agent, "agent_visible_experiment": {**view.to_dict(), "metrics": visible_metrics}}

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.treatment_view_bound is False


def test_validly_rehashed_lineage_value_tamper_fails_gate() -> None:
    _, config, _, _, view, agent, roster, markdown = _case()
    lineage = tuple(
        replace(item, value="0.10000000") if item.metric == "fold_1_signal_accuracy" else item for item in view.lineage
    )
    tampered = replace(view, lineage=lineage)
    assert tampered.content_sha256 != view.content_sha256
    single = {**agent, "treatment_metric_view": tampered.to_dict(), "agent_visible_experiment": tampered.to_dict()}

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.treatment_view_bound is False
    assert outcome.raw_packet_to_view_lineage is False


def _passing(index: int) -> R005CorrectionV3EpisodeOutcome:
    return R005CorrectionV3EpisodeOutcome(
        f"r005-e{index}",
        "AG",
        "NOISE",
        f"2026-08-{index:02d}T07:00:00Z",
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        True,
        "REJECT",
        "REJECT",
        "REJECT",
        "REJECT",
    )


def test_correction_v4_gate_is_computed_and_uses_honest_lineage_name() -> None:
    passing = tuple(_passing(index) for index in range(1, 9))
    gate = compute_r005_correction_v4_gate(passing, v4_predecessor_hashes_match=True)
    assert gate["decision"] == "R005_CORRECTION_V4_PASS"
    assert gate["raw_packet_to_view_lineage"] == "8/8"
    assert "raw_tool_result_lineage" not in gate
    failed = compute_r005_correction_v4_gate(
        (*passing[:-1], replace(passing[-1], treatment_view_bound=False)),
        v4_predecessor_hashes_match=True,
    )
    assert failed["decision"] == "R005_CORRECTION_V4_FAIL"
    assert failed["hardcoded"] is False
