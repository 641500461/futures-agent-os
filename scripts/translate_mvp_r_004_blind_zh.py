"""Write Chinese companions for R-004 Discovery blind reports. Does not change English originals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "datasets" / "mvp-r-001" / "runs" / "mvp-r-004-discovery"

HEADER = {
    "# Research Option ": "# 研究选项 ",
    "Execution mode:": "执行模式：",
    "This report is research and simulation only. It is not a trade, order, position, risk decision, fill, or ledger fact.": "本报告只用于研究和模拟。它不是交易、订单、持仓、风险裁决、成交或账本事实。",
    "## Experiment-pre judgment": "## 实验前判断",
    "- Instrument / cutoff:": "- 品种 / 截止时点：",
    "- Selected hypothesis:": "- 入选假设：",
    "- Falsification condition:": "- 证伪条件：",
    "## Independent Critic": "## 独立 Critic",
    "## Deterministic experiment results": "## 确定性实验结果",
    "## Experiment-post judgment": "## 实验后判断",
    "- Verdict:": "- 结论：",
    "- Rationale:": "- 理由：",
    "- Result reference:": "- 结果引用：",
    "## Limitations": "## 限制",
}

PHRASES = (
    (
        "registered direction beats the inverted-direction control on ResultPacket metrics",
        "登记方向在结果包指标上优于反向对照",
    ),
    (
        "reject if signal_accuracy does not beat counterfactual_signal_accuracy, or stressed_net_return does not beat counterfactual_stressed_net_return, or positive_fold_ratio is below 0.5",
        "若 `signal_accuracy` 不优于 `counterfactual_signal_accuracy`，或 `stressed_net_return` 不优于 `counterfactual_stressed_net_return`，或 `positive_fold_ratio` 低于 0.5，则拒绝",
    ),
    (
        "Under the frozen three chronological 5-bar out-of-sample folds with a one-bar embargo, FOLLOW has higher aggregate signal_accuracy than the inverted signal direction.",
        "在冻结的三段按时间顺序、每段 5 根样本外 fold、中间隔 1 根 embargo 的协议下，顺势（FOLLOW）的合计 `signal_accuracy` 高于反向信号。",
    ),
    (
        "Falsified if eligible observations are below the protocol minimum or aggregate signal_accuracy is less than or equal to counterfactual_signal_accuracy for the inverted direction.",
        "若合格观测数低于协议最低要求，或合计 `signal_accuracy` 小于等于反向对照的 `counterfactual_signal_accuracy`，则被证伪。",
    ),
    (
        "Using the fixed PRIOR_CLOSE_RETURN_THRESHOLD signal and frozen three chronological walk-forward folds, FOLLOW produces stressed_net_return greater than counterfactual_stressed_net_return under the stated cost and stress assumptions.",
        "使用固定的昨收涨跌阈值信号和冻结的三段按时间顺序的 walk-forward fold，在给定成本和压力假设下，顺势（FOLLOW）的 `stressed_net_return` 高于 `counterfactual_stressed_net_return`。",
    ),
    (
        "Falsified if stressed_net_return is less than or equal to counterfactual_stressed_net_return, or is non-positive in at least two of the three frozen test folds.",
        "若 `stressed_net_return` 小于等于 `counterfactual_stressed_net_return`，或在三段冻结测试 fold 中至少两段非正，则被证伪。",
    ),
    (
        "Across the three chronological walk-forward folds, the inverted prior-close-return signal has stressed_net_return greater than zero, greater than counterfactual_stressed_net_return, and positive stressed results in at least two folds.",
        "在三段按时间顺序的 walk-forward fold 上，反向昨收涨跌信号的 `stressed_net_return` 大于 0、大于 `counterfactual_stressed_net_return`，且至少两段压力结果为正。",
    ),
    (
        "Falsify if fewer than 20 eligible observations are available, stressed_net_return is non-positive, does not exceed counterfactual_stressed_net_return, or fewer than two folds are positive.",
        "若合格观测不足 20、`stressed_net_return` 非正、不超过 `counterfactual_stressed_net_return`，或为正的 fold 少于两段，则证伪。",
    ),
    (
        "A registered comparison failed.",
        "一项预先登记的对照比较未通过。",
    ),
    (
        "All registered deterministic comparisons pass.",
        "全部预先登记的确定性对照均通过。",
    ),
    (
        "For each eligible bar, the next-bar close-return sign matches the eligible bar's prior_close_return sign more often than the inverted signal. This tests participation-supported persistence despite the 40-bar sample's modest return_20 of 0.0012396300 relative to mean_abs_return_20 of 0.0070376803.",
        "对每根合格 K 线，下一根收盘涨跌符号与该根昨收涨跌符号同向的次数，应多于反向信号。这是在检验参与度支持的延续；尽管 40 根样本的 `return_20` 只有 0.0012396300，相对 `mean_abs_return_20` 0.0070376803 并不大。",
    ),
    (
        "Using the frozen three chronological folds, one-bar embargo, and five-bar test windows, signal_accuracy is not greater than counterfactual_signal_accuracy, or fewer than two folds favor the stated direction.",
        "在冻结的三段按时间顺序 fold、隔 1 根 embargo、每段 5 根测试窗口下，若 `signal_accuracy` 不大于 `counterfactual_signal_accuracy`，或少于两段 fold 支持该方向，则证伪。",
    ),
    (
        "Under the frozen three-fold chronological walk-forward protocol, FOLLOW has signal_accuracy strictly above counterfactual_signal_accuracy and is directionally correct in at least two of three held-out folds.",
        "在冻结的三段按时间顺序 walk-forward 协议下，顺势 FOLLOW 的 `signal_accuracy` 严格高于 `counterfactual_signal_accuracy`，且至少两段留出 fold 方向正确。",
    ),
    (
        "Falsified if fewer than 20 eligible observations remain, or if aggregate signal_accuracy is less than or equal to counterfactual_signal_accuracy, or fewer than two held-out folds have positive directional accuracy advantage.",
        "若合格观测不足 20，或合计 `signal_accuracy` 小于等于 `counterfactual_signal_accuracy`，或少于两段留出 fold 有正的方向准确率优势，则被证伪。",
    ),
    (
        "Across the locked three chronological folds, proxy_net_return is positive and exceeds counterfactual_net_return for the inverted-direction control.",
        "在锁定的三段按时间顺序 fold 上，`proxy_net_return` 为正，且高于反向对照的 `counterfactual_net_return`。",
    ),
    (
        "Falsified if locked-fold proxy_net_return is non-positive or does not exceed counterfactual_net_return.",
        "若锁定 fold 的 `proxy_net_return` 非正，或不高于 `counterfactual_net_return`，则被证伪。",
    ),
    (
        "Over the three chronological 5-bar walk-forward test folds with the one-bar embargo, FOLLOW signal_accuracy exceeds the inverted-direction control and exceeds 0.50 in at least two folds.",
        "在三段按时间顺序、每段 5 根的 walk-forward 测试 fold、中间隔 1 根 embargo 下，顺势 FOLLOW 的 `signal_accuracy` 高于反向对照，且至少两段超过 0.50。",
    ),
    (
        "Falsified if FOLLOW signal_accuracy is no greater than the inverted-direction control, or it exceeds 0.50 in fewer than two of the three test folds.",
        "若顺势 FOLLOW 的 `signal_accuracy` 不高于反向对照，或在三段测试 fold 中超过 0.50 的不足两段，则被证伪。",
    ),
    (
        "In the frozen three-fold chronological walk-forward evaluation, INVERT outputs for PRIOR_CLOSE_RETURN_THRESHOLD observations will have stressed_net_return greater than counterfactual_stressed_net_return for FOLLOW, with positive stressed_net_return in at least two of three folds.",
        "在冻结的三段按时间顺序 walk-forward 评估中，昨收涨跌阈值信号取反向 INVERT 后的 `stressed_net_return`，应高于顺势 FOLLOW 对照的 `counterfactual_stressed_net_return`，且至少两段 `stressed_net_return` 为正。",
    ),
    (
        "Falsified if INVERT stressed_net_return is not greater than its FOLLOW counterfactual_stressed_net_return, or if fewer than two of the three folds have positive stressed_net_return.",
        "若反向 INVERT 的 `stressed_net_return` 不高于顺势 FOLLOW 对照的 `counterfactual_stressed_net_return`，或三段中 `stressed_net_return` 为正的不足两段，则被证伪。",
    ),
    (
        "L0 direction sanity check is not a trading claim",
        "L0 方向检查不是交易主张",
    ),
    (
        "L1 uses daily-bar directional approximation without fill semantics",
        "L1 使用日线方向近似，没有成交语义",
    ),
    (
        "component rolls are unadjusted when present",
        "若存在换月成分，未做复权",
    ),
)

CODES = (
    ("GROUNDED_IN_SUPPLIED_PIT_EVIDENCE", "依据所提供的 PIT 证据"),
    ("SUPPORTED_SIGNAL_OPERATOR_AND_ALLOWED_PARAMETERS", "信号算子与参数在允许范围内"),
    ("SAMPLE_COUNT_40_MEETS_MINIMUM_20", "样本 40 满足最低 20"),
    ("PRIMARY_METRIC_AND_INVERTED_CONTROL_ARE_RESULT_PACKET_FIELDS", "主指标与反向对照都是结果包字段"),
    ("CHRONOLOGICAL_FOLDS_AND_EMBARGO_SPECIFIED", "已写明按时间顺序的 fold 与 embargo"),
    ("COST_AND_STRESS_ASSUMPTIONS_SPECIFIED", "已写明成本与压力假设"),
    ("UP_TREND_REGIME_SUPPORTED_BY_POSITIVE_5_AND_20_BAR_RETURNS", "5 根与 20 根收益为正，支持上涨状态"),
    ("EXPLICIT_FALSIFICATION_CONDITION", "证伪条件明确"),
    ("MULTIPLE_TESTING_BUDGET_RESPECTED", "遵守多重检验预算"),
    ("NON_TRADABLE_RESEARCH_HYPOTHESIS", "不可交易的研究假设"),
    ("UNADJUSTED_ROLL_LIMITATION_DISCLOSED", "已披露未复权换月限制"),
    ("PIT_RULES_SATISFIED", "满足 PIT 规则"),
    ("SUPPORTED_SIGNAL_OPERATOR_AND_FROZEN_PARAMETERS", "信号算子与冻结参数被支持"),
    ("ELIGIBLE_COUNT_20_MEETS_MINIMUM", "合格数量达到最低 20"),
    ("PRIMARY_AND_CONTROL_METRICS_ARE_FROZEN_RESULTPACKET_FIELDS", "主指标与对照都是冻结结果包字段"),
    ("COST_AND_SLIPPAGE_ASSUMPTIONS_REFERENCED", "已引用成本与滑点假设"),
    ("THREE_FOLD_OOS_COMPARISON_IS_EXECUTABLE_AND_FALSIFIABLE", "三段样本外比较可执行且可证伪"),
    ("UNADJUSTED_ROLL_RISK_DISCLOSED", "已披露未复权换月风险"),
    ("GROUNDED_EVIDENCE_REFS", "证据引用有来源"),
    ("SUPPORTED_SIGNAL_OPERATOR", "信号算子被支持"),
    ("ALLOWED_PARAMETERS", "参数在允许范围内"),
    ("VALID_RESULTPACKET_PRIMARY_METRIC", "主指标是合法结果包字段"),
    ("PRESPECIFIED_EXECUTABLE_REGIME_FILTER", "预先指定且可执行的状态过滤"),
    ("MINIMUM_SAMPLE_MET", "满足最低样本"),
    ("PIT_RULES_RESPECTED", "遵守 PIT 规则"),
    ("COST_AND_STRESS_ASSUMPTIONS_FROZEN", "成本与压力假设已冻结"),
    ("INVERTED_DIRECTION_CONTROL_SPECIFIED", "已指定反向对照"),
    ("FALSIFICATION_THRESHOLD_EXPLICIT", "证伪阈值明确"),
    ("KNOWN_ROLL_LIMITATION_DISCLOSED", "已披露已知换月限制"),
    ("GROUNDED_IN_SUPPLIED_BARS_AND_FEATURES", "依据所提供的 K 线与特征"),
    ("SUPPORTED_OPERATOR_AND_ALLOWED_PARAMETERS", "算子与参数在允许范围内"),
    ("FROZEN_INVERTED_DIRECTION_CONTROL", "反向对照已冻结"),
    ("NUMERIC_COST_AND_STRESS_ASSUMPTIONS_PRESENT", "已给出数值化成本与压力假设"),
    ("MINIMUM_SAMPLE_AND_FOLD_REQUIREMENTS_MET", "满足最低样本与 fold 要求"),
    ("PIT_AND_EMBARGO_RULES_SPECIFIED", "已写明 PIT 与 embargo 规则"),
    ("EXPLICIT_PRE_RESULT_FALSIFICATION_CONDITION", "实验结果前已写明证伪条件"),
    ("WITHIN_MULTIPLE_TESTING_BUDGET", "在多重检验预算内"),
    ("NONTRADABLE_RESEARCH_HYPOTHESIS", "不可交易的研究假设"),
    ("PIT_COMPLIANT_NO_FUTURE_BARS", "符合 PIT，不含未来 K 线"),
    ("SUPPORTED_OPERATOR_AND_FROZEN_PARAMETERS", "算子与冻结参数被支持"),
    ("PRIMARY_METRIC_IS_RESULTPACKET_FIELD", "主指标是结果包字段"),
    ("SAMPLE_AND_FOLDS_MEET_PROTOCOL", "样本与 fold 满足协议"),
    ("CHOPPY_REGIME_GROUNDED_IN_OBSERVED_RETURNS", "震荡状态有观测收益依据"),
    ("FROZEN_CONTROL_AND_EXPLICIT_FALSIFICATION", "对照已冻结且证伪条件明确"),
    ("COSTS_EMBARGO_AND_STRESS_ASSUMPTIONS_SPECIFIED", "已写明成本、embargo 与压力假设"),
    ("KNOWN_LIMITATIONS_DISCLOSED_NOT_FATAL", "已披露已知限制，不构成自动否决"),
    ("SAMPLE_AND_FOLDS_PROTOCOL_SUFFICIENT", "样本与 fold 达到协议要求"),
    ("REGIME_GROUNDED_IN_SUPPLIED_BARS", "状态判断依据所提供 K 线"),
    ("EXPLICIT_DIRECTIONAL_CONTROL_AND_FALSIFICATION", "方向对照与证伪条件明确"),
    ("DISCLOSED_ROLL_LIMITATION_NOT_DISQUALIFYING", "已披露换月限制，不因此取消资格"),
    ("GROUNDED_IN_SUPPLIED_EVIDENCE", "依据所提供证据"),
    ("SUPPORTED_SIGNAL_OPERATOR_AND_PARAMETERS", "信号算子与参数被支持"),
    ("PIT_AND_EMBARGO_RULES_SATISFIED", "满足 PIT 与 embargo 规则"),
    ("SAMPLE_AND_FOLDS_DISCLOSED", "已披露样本与 fold"),
    ("EXECUTABLE_FALSIFICATION_CRITERIA", "证伪标准可执行"),
    ("KNOWN_LIMITATIONS_DISCLOSED", "已披露已知限制"),
)


def translate_body(text: str) -> str:
    for english, chinese in sorted(PHRASES, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(english, chinese)
    for english, chinese in HEADER.items():
        text = text.replace(english, chinese)
    for code, chinese in sorted(CODES, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(code, chinese)
    text = translate_rationales(text)
    return text


def translate_rationales(text: str) -> str:
    replacements = (
        (
            "Falsified: FOLLOW signal_accuracy (0.44736842) is below the inverted-direction control (0.55263158). The mapped control also outperforms in net return and fold positivity.",
            "被证伪：顺势 FOLLOW 的 `signal_accuracy`（0.44736842）低于反向对照（0.55263158）。对照在净收益和为正 fold 比例上也更好。",
        ),
        (
            "Registered FOLLOW fails all falsification checks: signal_accuracy 0.44736842 is below inverted-direction control counterfactual_signal_accuracy 0.55263158; stressed_net_return -0.10654094 is below counterfactual_stressed_net_return 0.06094094; and positive_fold_ratio 0.33333333 is below 0.5.",
            "登记的顺势 FOLLOW 未通过全部证伪检查：`signal_accuracy` 0.44736842 低于反向对照 `counterfactual_signal_accuracy` 0.55263158；`stressed_net_return` -0.10654094 低于 `counterfactual_stressed_net_return` 0.06094094；`positive_fold_ratio` 0.33333333 低于 0.5。",
        ),
        (
            "Falsified: FOLLOW signal_accuracy (0.44736842) is below the inverted-direction control (0.55263158).",
            "被证伪：顺势 FOLLOW 的 `signal_accuracy`（0.44736842）低于反向对照（0.55263158）。",
        ),
        (
            "signal_accuracy 0.44736842 is below inverted-direction control 0.55263158; positive_fold_ratio 0.33333333 is below 0.5. Although stressed_net_return 0.01397253 exceeds control -0.05957253, falsification conditions are met.",
            "`signal_accuracy` 0.44736842 低于反向对照 0.55263158；`positive_fold_ratio` 0.33333333 低于 0.5。虽然 `stressed_net_return` 0.01397253 高于对照 -0.05957253，证伪条件已经满足。",
        ),
        (
            "Although stressed_net_return (0.01397253) exceeds the inverted-control value (-0.05957253), only 1 of 3 frozen walk-forward folds is positive, so the hypothesis's fold-based falsification condition is met.",
            "虽然 `stressed_net_return`（0.01397253）高于反向对照（-0.05957253），但三段冻结 walk-forward 中只有 1 段为正，因此假设自己写的 fold 证伪条件已经满足。",
        ),
        (
            "Although stressed_net_return is positive and exceeds the inverted-control result (0.01397253 > -0.05957253), only 1 of 3 frozen test folds is positive. The hypothesis’s stated falsification condition is therefore met.",
            "虽然 `stressed_net_return` 为正且高于反向对照（0.01397253 > -0.05957253），但三段冻结测试 fold 中只有 1 段为正。因此假设自己写明的证伪条件已经满足。",
        ),
        (
            "Registered INVERT direction fails all falsification checks: signal_accuracy 0.50000000 does not beat inverted-control counterfactual_signal_accuracy 0.50000000; stressed_net_return -0.06465536 is below counterfactual_stressed_net_return 0.01905536; and positive_fold_ratio 0.00000000 is below 0.5.",
            "登记的反向 INVERT 未通过全部证伪检查：`signal_accuracy` 0.50000000 没有优于对照 `counterfactual_signal_accuracy` 0.50000000；`stressed_net_return` -0.06465536 低于 `counterfactual_stressed_net_return` 0.01905536；`positive_fold_ratio` 0.00000000 低于 0.5。",
        ),
        (
            "Primary stressed_net_return is -0.06465536, below zero and below the mapped counterfactual control (+0.01905536); positive-fold ratio is 0/3. The falsification conditions are met.",
            "主指标 `stressed_net_return` 为 -0.06465536，低于 0，也低于对照（+0.01905536）；为正 fold 比例是 0/3。证伪条件已满足。",
        ),
        (
            "Primary stressed_net_return is -0.06465536, below zero and below mapped counterfactual control 0.01905536; walk-forward positive-fold ratio is 0/3, failing the stated falsification conditions.",
            "主指标 `stressed_net_return` 为 -0.06465536，低于 0，也低于对照 0.01905536；walk-forward 为正 fold 比例是 0/3，未通过写明的证伪条件。",
        ),
        (
            "Registered INVERT fails its primary control: signal_accuracy 0.43243243 is below counterfactual_signal_accuracy 0.56756757. It also fails positive_fold_ratio 0.33333333 < 0.5, despite stressed_net_return -0.01700526 exceeding the control's -0.02739474.",
            "登记的反向 INVERT 未通过主对照：`signal_accuracy` 0.43243243 低于 `counterfactual_signal_accuracy` 0.56756757。`positive_fold_ratio` 0.33333333 也低于 0.5。尽管 `stressed_net_return` -0.01700526 高于对照 -0.02739474。",
        ),
        (
            "The primary signal accuracy (0.43243243) is below the inverted-direction control (0.56756757), directly meeting the falsification condition. Returns are also negative under stress.",
            "主指标信号准确率（0.43243243）低于反向对照（0.56756757），直接满足证伪条件。压力下的收益也为负。",
        ),
        (
            "Primary signal_accuracy (0.43243243) is below mapped counterfactual_signal_accuracy (0.56756757), directly satisfying the falsification condition.",
            "主指标 `signal_accuracy`（0.43243243）低于对照 `counterfactual_signal_accuracy`（0.56756757），直接满足证伪条件。",
        ),
        (
            "Primary signal_accuracy (0.55263158) exceeds mapped inverted-direction control (0.44736842); all three held-out folds favor FOLLOW, with 38 signals.",
            "主指标 `signal_accuracy`（0.55263158）高于反向对照（0.44736842）；三段留出 fold 都支持顺势 FOLLOW，共 38 个信号。",
        ),
        (
            "All falsification checks pass: 38 eligible signals, primary accuracy 0.55263158 exceeds counterfactual accuracy 0.44736842, and all 3 held-out folds show positive advantage versus 0 counterfactual-positive folds.",
            "全部证伪检查通过：38 个合格信号，主准确率 0.55263158 高于对照 0.44736842，三段留出 fold 都有正优势，对照为正的 fold 为 0。",
        ),
        (
            "Registered FOLLOW beats its inverted-direction control on signal_accuracy (0.55263158 vs 0.44736842), stressed_net_return (0.23455239 vs -0.28015239), and positive_fold_ratio is 1.00000000 (3 folds).",
            "登记的顺势 FOLLOW 在 `signal_accuracy`（0.55263158 对 0.44736842）和 `stressed_net_return`（0.23455239 对 -0.28015239）上优于反向对照，`positive_fold_ratio` 为 1.00000000（3 段）。",
        ),
        (
            "Registered INVERT direction beats its inverted-direction control on signal_accuracy (0.55263158 vs 0.44736842) and stressed_net_return (0.19661208 vs -0.24221208); positive_fold_ratio is 1.00000000, above 0.5.",
            "登记的反向 INVERT 在 `signal_accuracy`（0.55263158 对 0.44736842）和 `stressed_net_return`（0.19661208 对 -0.24221208）上优于对照；`positive_fold_ratio` 为 1.00000000，高于 0.5。",
        ),
        (
            "Primary proxy_net_return is positive (0.20801208) and exceeds the inverted-direction control (-0.23081208); all three locked folds are positive, including under stress.",
            "主指标 `proxy_net_return` 为正（0.20801208），且高于反向对照（-0.23081208）；三段锁定 fold 都为正，压力下也是。",
        ),
        (
            "The complete packet satisfies the falsification test: proxy_net_return is positive (0.20801208) and exceeds the inverted-direction control (-0.23081208); all locked folds are positive while all control folds are negative.",
            "完整结果包通过证伪检验：`proxy_net_return` 为正（0.20801208），高于反向对照（-0.23081208）；锁定 fold 全部为正，对照 fold 全部为负。",
        ),
        (
            "FOLLOW accuracy is 0.60526316, exceeding both the inverted-direction control (0.39473684) and 0.50; the walk-forward positive-fold ratio is 0.66666667, satisfying the required two of three folds.",
            "顺势 FOLLOW 准确率为 0.60526316，高于反向对照（0.39473684）也高于 0.50；walk-forward 为正 fold 比例 0.66666667，满足三段中至少两段。",
        ),
        (
            "FOLLOW accuracy (0.60526316) exceeds inverted control (0.39473684), but the packet does not report per-fold signal_accuracy needed to verify it exceeded 0.50 in at least two of three folds.",
            "顺势 FOLLOW 准确率（0.60526316）高于反向对照（0.39473684），但结果包没有给出分段 `signal_accuracy`，无法核对是否至少两段超过 0.50。",
        ),
        (
            "The registered INVERT direction beats its inverted-direction control on signal_accuracy (0.60526316 vs 0.39473684) and stressed_net_return (0.04557421 vs -0.09117421); positive_fold_ratio is 0.66666667, above the 0.5 falsification threshold.",
            "登记的反向 INVERT 在 `signal_accuracy`（0.60526316 对 0.39473684）和 `stressed_net_return`（0.04557421 对 -0.09117421）上优于对照；`positive_fold_ratio` 为 0.66666667，高于 0.5 的证伪门槛。",
        ),
        (
            "Primary stressed_net_return (0.05867444) exceeds the mapped FOLLOW control (-0.10427444), and all three folds are positive. The control is strongly negative, supporting the specified INVERT direction.",
            "主指标 `stressed_net_return`（0.05867444）高于顺势 FOLLOW 对照（-0.10427444），三段都为正。对照明显为负，支持所指定的反向 INVERT。",
        ),
        (
            "INVERT stressed_net_return (0.05867444) exceeds FOLLOW counterfactual stressed_net_return (-0.10427444), and all 3/3 walk-forward folds are positive. The mapped counterfactual is strongly adverse, supporting directional specificity.",
            "反向 INVERT 的 `stressed_net_return`（0.05867444）高于顺势 FOLLOW 对照（-0.10427444），walk-forward 3/3 段为正。对照明显不利，支持该方向设定。",
        ),
        (
            "Registered INVERT beats its mapped inverted-direction control: signal_accuracy 0.60526316 vs counterfactual_signal_accuracy 0.39473684. Stressed net return is 0.05867444 vs counterfactual -0.10427444, and positive_fold_ratio is 1.00000000 (3 folds), above 0.5.",
            "登记的反向 INVERT 优于对照：`signal_accuracy` 0.60526316 对 `counterfactual_signal_accuracy` 0.39473684。压力净收益 0.05867444 对对照 -0.10427444，`positive_fold_ratio` 为 1.00000000（3 段），高于 0.5。",
        ),
    )
    for english, chinese in replacements:
        text = text.replace(english, chinese)
    return text


def remaining_english(text: str) -> tuple[str, ...]:
    leftover = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- `"):
            continue
        if stripped.startswith("- 结论：") or stripped.startswith("- 结果引用："):
            continue
        letters = [ch for ch in stripped if ("A" <= ch <= "Z" or "a" <= ch <= "z")]
        if len(letters) >= 24 and "SELECT" not in stripped:
            leftover.append(stripped)
    return tuple(leftover)


def main() -> None:
    written = 0
    leftover: list[str] = []
    for path in sorted(RUN_ROOT.glob("*/blind/option-*.md")):
        if path.name.endswith(".zh.md"):
            continue
        chinese = translate_body(path.read_text(encoding="utf-8"))
        target = path.with_name(path.stem + ".zh.md")
        target.write_text(chinese, encoding="utf-8")
        written += 1
        leftover.extend(f"{target}: {item}" for item in remaining_english(chinese))
    print(f"wrote {written}")
    for item in leftover:
        print(item)


if __name__ == "__main__":
    main()
