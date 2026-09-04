"""Four-block Chinese user report. No Independent Critic section."""

from __future__ import annotations

from .contracts import DecisionBrief


def render_decision_brief_markdown(episode_id: str, brief: DecisionBrief) -> str:
    if type(episode_id) is not str or not episode_id.strip():
        raise ValueError("decision brief requires an episode id")
    if type(brief) is not DecisionBrief:
        raise TypeError("decision brief render requires an exact DecisionBrief")
    return (
        f"# 研究决策简报 {episode_id}\n\n"
        "研究与模拟，不是交易指令。\n\n"
        f"## 测了什么\n\n{brief.what_was_tested.strip()}\n\n"
        f"## 结果怎样\n\n{brief.results.strip()}\n\n"
        f"## 当前判断\n\n`{brief.verdict.value}` {brief.current_judgment.strip()}\n\n"
        f"## 下一步动作\n\n{brief.next_action.strip()}\n"
    )
