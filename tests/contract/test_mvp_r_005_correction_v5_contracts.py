"""MVP-R-005 correction-v5: explicit visible payload and exact four-block report binding."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from futures_agent_os.research_experiment.mvp_r_005 import (
    DecisionBrief,
    assess_correction_v5_episode,
    compute_r005_correction_v5_gate,
    render_decision_brief_markdown,
)

from test_mvp_r_005_correction_v4_contracts import _case, _passing


def _strict_case():
    _, config, _, _, _, payload, roster, _ = _case()
    brief = DecisionBrief.hydrate(payload["decision_brief"])
    markdown = render_decision_brief_markdown(roster["episode_id"], brief)
    return config, payload, roster, markdown


def _assess(agent, single, roster, markdown, config, *, single_markdown=None):
    return assess_correction_v5_episode(
        roster_item=roster,
        agent_payload=agent,
        single_payload=single,
        agent_markdown=markdown,
        single_markdown=markdown if single_markdown is None else single_markdown,
        overlapping_predecessor=False,
        config=config,
    )


@pytest.mark.parametrize("replacement", [None, {}, [], ()])
def test_missing_null_or_empty_visible_payload_fails_closed(replacement) -> None:
    config, agent, roster, markdown = _strict_case()
    single = deepcopy(agent)
    if replacement is None:
        single.pop("agent_visible_experiment")
    else:
        single["agent_visible_experiment"] = replacement

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.treatment_view_bound is False


def test_null_visible_payload_fails_closed() -> None:
    config, agent, roster, markdown = _strict_case()
    single = {**agent, "agent_visible_experiment": None}

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.treatment_view_bound is False


def test_extra_h2_or_contradictory_markdown_fails_report_gate() -> None:
    config, agent, roster, markdown = _strict_case()
    extra = markdown + "\n## 额外说明\n\n不应存在。\n"
    contradictory = markdown.replace("`REJECT`", "`ACCEPT`")

    extra_outcome = _assess(agent, agent, roster, extra, config)
    contradictory_outcome = _assess(agent, agent, roster, contradictory, config)

    assert extra_outcome.four_block_report is False
    assert extra_outcome.complete is False
    assert contradictory_outcome.four_block_report is False
    assert contradictory_outcome.complete is False


def test_structured_brief_verdict_must_match_final_verdict() -> None:
    config, agent, roster, markdown = _strict_case()
    single = deepcopy(agent)
    single["decision_brief"] = {**single["decision_brief"], "verdict": "ACCEPT"}

    outcome = _assess(agent, single, roster, markdown, config)

    assert outcome.four_block_report is False
    assert outcome.complete is False


def test_exact_existing_report_and_visible_payload_pass() -> None:
    config, agent, roster, markdown = _strict_case()

    outcome = _assess(agent, agent, roster, markdown, config)

    assert outcome.treatment_view_bound is True
    assert outcome.four_block_report is True
    assert outcome.complete is True


def test_correction_v5_gate_is_computed() -> None:
    passing = tuple(_passing(index) for index in range(1, 9))
    gate = compute_r005_correction_v5_gate(passing, v5_predecessor_hashes_match=True)
    assert gate["decision"] == "R005_CORRECTION_V5_PASS"
    assert gate["schema_version"] == "mvp-r-005.correction-v5-gate.v1"
    assert gate["v5_predecessor_hashes_match"] is True
    failed = compute_r005_correction_v5_gate(
        (*passing[:-1], replace(passing[-1], four_block_report=False)),
        v5_predecessor_hashes_match=True,
    )
    assert failed["decision"] == "R005_CORRECTION_V5_FAIL"
