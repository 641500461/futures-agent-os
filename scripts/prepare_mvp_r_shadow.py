"""Prepare ten future-blind Chinese shadow reports for user review."""

from __future__ import annotations

import argparse
import json
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256

import run_mvp_r_replay as runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-sha256", required=True)
    args = parser.parse_args()
    source_dir = runner.DATA_ROOT / "runs" / args.suite_sha256 / "holdout" / "official"
    artifacts = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(source_dir.glob("evaluation_episode_*.json"))
    ]
    eligible = [
        item
        for item in artifacts
        if item["status"] == "COMPLETED"
        and not item.get("critical_scenario")
        and item.get("critique", {}).get("accepted") is True
    ]
    selected = _select(eligible)
    if len(selected) != 10:
        raise SystemExit("could not construct ten diverse future-blind shadow reports")

    output_dir = runner.DATA_ROOT / "runs" / args.suite_sha256 / "shadow"
    output_dir.mkdir(parents=True, exist_ok=True)
    roster = {
        "task": "MVP-R-001",
        "suite_sha256": args.suite_sha256,
        "selection": "critic-accepted-diverse-instrument-state-outcome.v1",
        "future_reveal_included": False,
        "items": tuple(
            {
                "shadow_index": index,
                "episode_id": item["episode_id"],
                "instrument_id": item["instrument_id"],
                "stratum": item["stratum"],
                "conclusion_kind": item["conclusion"]["kind"],
                "run_replay_sha256": item["semantic_replay_sha256"],
            }
            for index, item in enumerate(selected, start=1)
        ),
    }
    roster = {**roster, "roster_sha256": canonical_sha256(roster)}
    (output_dir / "roster.json").write_text(canonical_json_text(roster) + "\n", encoding="utf-8")
    (output_dir / "SHADOW-REVIEW.md").write_text(_markdown(args.suite_sha256, selected), encoding="utf-8")
    print(json.dumps(roster, ensure_ascii=False, indent=2))


def _select(items: list[dict[str, object]]) -> list[dict[str, object]]:
    opportunities = [item for item in items if item["conclusion"]["kind"] == "OPPORTUNITY_CANDIDATE"]
    no_opportunities = [item for item in items if item["conclusion"]["kind"] == "NO_OPPORTUNITY"]
    selected = list(opportunities)
    seen = {(item["instrument_id"], item["stratum"]) for item in selected}
    for item in no_opportunities:
        identity = (item["instrument_id"], item["stratum"])
        if identity not in seen and len(selected) < 10:
            selected.append(item)
            seen.add(identity)
    for item in no_opportunities:
        if item not in selected and len(selected) < 10:
            selected.append(item)
    return selected[:10]


def _markdown(suite_sha256: str, items: list[dict[str, object]]) -> str:
    lines = [
        "# MVP-R 用户 Shadow 验收",
        "",
        f"Suite：`{suite_sha256}`  ",
        "说明：以下报告只使用当时可见的历史证据，不包含后来行情答案，也不构成交易建议。",
        "",
        "请阅读每份报告后，用文末的紧凑格式回复。不要根据后来的涨跌评价，只判断它是否帮助你做研究决定。",
        "",
    ]
    for index, item in enumerate(items, start=1):
        conclusion = item["conclusion"]
        hypothesis = conclusion["hypothesis"]
        outcome = "值得继续做下一步验证" if conclusion["kind"] == "OPPORTUNITY_CANDIDATE" else "当前不值得继续投入"
        family = {
            "MOMENTUM_CONTINUATION": "趋势延续",
            "MEAN_REVERSION": "均值回归",
            "NONE": "没有成立的方向假设",
        }[hypothesis["family"]]
        lines.extend(
            [
                f"## {index}. {_instrument_text(item['instrument_id'])} · {_state_text(item['stratum'])}",
                "",
                f"- 系统结论：**{outcome}**",
                f"- 研究思路：{family}",
                f"- 人话解释：{_plain_explanation(hypothesis['family'], conclusion['kind'])}",
                f"- 如何推翻它：{_falsification_text(hypothesis['family'], conclusion['kind'])}",
                f"- 建议下一步：{_next_test_text(hypothesis['family'], conclusion['kind'])}",
                "- 关键证据：",
                "",
                *[f"  - {_claim_text(claim['statement'])}" for claim in conclusion["claims"]],
            ]
        )
        if conclusion["warnings"]:
            lines.extend(["", *[f"- 注意：{_warning_text(value)}" for value in conclusion["warnings"]]])
        lines.extend(
            [
                "",
                "你的评价：`价值=是/否；省时=是/否；行动=继续验证/加入观察/排除/保持暂缓/无；无系统需手工=是/否`",
                "",
            ]
        )
    lines.extend(
        [
            "## 回复格式",
            "",
            "例如：",
            "",
            "`1 是 是 加入观察 是`  ",
            "`2 否 否 无 是`",
            "",
            "请按相同格式回复十行；我会自动汇总是否达到至少七次有价值、五次省时、三次促成行动。",
            "",
        ]
    )
    return "\n".join(lines)


def _plain_explanation(family: str, kind: str) -> str:
    if kind == "NO_OPPORTUNITY":
        return "现有证据经成本和反向检验后不够扎实，继续投入的优先级较低。"
    if family == "MOMENTUM_CONTINUATION":
        return "近期方向可能延续，但这里只建议继续验证，不代表可以下单。"
    return "近期方向可能反转，但这里只建议继续验证，不代表可以下单。"


def _instrument_text(value: str) -> str:
    names = {
        "CZCE.SR.DOMINANT_OI": "白糖主力连续（郑商所）",
        "CZCE.MA.DOMINANT_OI": "甲醇主力连续（郑商所）",
        "SHFE.AG.DOMINANT_OI": "白银主力连续（上期所）",
        "SHFE.CU.DOMINANT_OI": "铜主力连续（上期所）",
    }
    return names.get(value, value)


def _state_text(value: str) -> str:
    states = {
        "RANGE": "区间震荡",
        "EXTREME_VOLATILITY": "极端波动",
        "UP_TREND": "上升趋势",
        "DOWN_TREND": "下降趋势",
        "FALSE_BREAKOUT": "假突破",
        "NOISE": "噪声行情",
    }
    return states.get(value, value)


def _falsification_text(family: str, kind: str) -> str:
    if kind == "NO_OPPORTUNITY":
        return "若另一段独立、按时间顺序封存的数据在提高成本后仍稳定为正，当前“暂不投入”的结论就应被推翻。"
    if family == "MOMENTUM_CONTINUATION":
        return "若另一段独立、按时间顺序封存的数据在提高成本后收益不再为正，趋势延续假设就不成立。"
    return "若另一段独立、按时间顺序封存的数据在提高成本后反向策略收益不再为正，均值回归假设就不成立。"


def _next_test_text(family: str, kind: str) -> str:
    if kind == "NO_OPPORTUNITY":
        return "换一段独立封存的历史窗口，继续比较顺势与反向两种方案；只有压力后结果稳定为正且分段一致，才重新考虑。"
    if family == "MOMENTUM_CONTINUATION":
        return "换一段独立封存的历史窗口做顺势检验，并检查提高成本后是否仍为正、不同时间分段是否一致。"
    return "换一段独立封存的历史窗口做反向检验，并检查提高成本后是否仍为正、不同时间分段是否一致。"


def _claim_text(value: str) -> str:
    replacements = {
        "The directional signal accuracy": "方向信号准确率",
        "The signal accuracy": "信号准确率",
        "Directional signal accuracy": "方向信号准确率",
        "Signal accuracy": "信号准确率",
        "The positive-fold ratio": "正收益时间分段占比",
        "Positive-fold ratio": "正向分段比例",
        "The momentum proxy net return": "顺势方案近似净收益",
        "Momentum proxy net return": "动量近似净收益",
        "The momentum stressed net return": "顺势方案提高成本后的近似净收益",
        "Momentum stressed net return": "动量压力后近似净收益",
        "The counterfactual net return": "反向方案近似净收益",
        "Counterfactual net return": "反向假设近似净收益",
        "The counterfactual stressed net return": "反向方案提高成本后的近似净收益",
        "Counterfactual stressed net return": "反向假设压力后近似净收益",
        "The continuation proxy net return": "顺势方案近似净收益",
        "The continuation stressed net return": "顺势方案提高成本后的近似净收益",
        "The directional proxy net return": "当前方向方案近似净收益",
        "Directional proxy net return": "当前方向方案近似净收益",
        "The directional stressed net return": "当前方向方案提高成本后的近似净收益",
        "Directional stressed net return": "当前方向方案提高成本后的近似净收益",
        "The opposite-direction net return": "反向方案近似净收益",
        "The opposite-direction stressed net return": "反向方案提高成本后的近似净收益",
        "Opposite-direction stressed net return": "反向方案提高成本后的近似净收益",
        "The opposing-direction net return": "反向方案近似净收益",
        "The opposing-direction stressed net return": "反向方案提高成本后的近似净收益",
        "The proxy net return": "近似净收益",
        "Proxy net return": "近似净收益",
        "The stressed net return": "提高成本后的近似净收益",
        "Stressed net return": "压力后近似净收益",
        "The historical window contained": "历史窗口包含",
        "The market window contained": "市场窗口包含",
        "The final sample contains": "最终样本包含",
        "The recorded market state is": "记录的行情状态为",
        "The market state was": "行情状态为",
        "The roll count is": "换月次数为",
        "Roll count is": "换月次数为",
        "The window contains": "窗口包含",
    }
    for source, target in replacements.items():
        if value.startswith(source):
            value = target + value[len(source) :]
            break
    return (
        value.replace(" was ", "为 ")
        .replace(" is ", "为 ")
        .replace(" bars", " 根日线")
        .replace(" rolls", " 次")
        .replace(" roll", " 次换月")
        .replace(" ratio", "（比例）")
        .replace("NOISE", "噪声行情")
        .replace("FALSE_BREAKOUT", "假突破")
    )


def _warning_text(value: str) -> str:
    normalized = value.casefold()
    if "unadjusted component roll" in normalized:
        return "连续序列包含未复权换月，结论需要谨慎解释。"
    if "no roll warnings" in normalized:
        return "没有发现换月相关警告。"
    if "positive-fold evidence is weak" in normalized or "fold consistency is weak" in normalized:
        return "不同时间分段的一致性偏弱。"
    if "continuation results are adverse" in normalized:
        return "顺势方案的结果为负。"
    if "extreme volatility" in normalized:
        return "该历史窗口属于极端波动行情。"
    if "stressed continuation result is negative" in normalized:
        return "顺势方案在提高成本后的结果为负。"
    if "lacks sufficient cross-fold support" in normalized:
        return "反向方案在不同时间分段中的支持还不够。"
    if "signal accuracy and positive-fold breadth" in normalized:
        return "信号准确率和正收益分段覆盖度不足以支持稳健的顺势假设。"
    if "directional and opposite-direction stressed results are adverse" in normalized:
        return "当前方向和反向方案在提高成本后的结果都不理想。"
    return value


if __name__ == "__main__":
    main()
