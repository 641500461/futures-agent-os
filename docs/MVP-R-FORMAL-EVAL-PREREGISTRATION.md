# MVP-R 正式评测预注册

文档版本：`1.0-frozen`  
Roadmap Gate：V1 研究可用性 Gate（不新增 Roadmap 任务编号）  
状态：`AUTHORIZED_FROZEN_NOT_RUN`  
授权日期：2026-09-02  
产品边界：研究与模拟；无 StrategyCandidate、TradePlan、Order、Fill、Position、账户或账本副作用

## 1. 决定

产品负责人于 2026-09-02 明确授权：“现在直接预注册并执行正式 eval，不另造 `MVP-R-006` 编号”。本文件因此直接冻结 `MVP-R-005` 完成后的 V1 研究可用性 Gate，不创建新的 Roadmap 功能任务。

本 Gate 只回答：

> 单 Research Agent 提出有界假设、确定性 validator/工具执行实验、Agent 根据结果形成四块决策简报，是否在全新样本上可靠运行，并相对获得相同事实与工具结果的 Single-prompt Analyst 为真实用户提供足够增量？

`MVP-R-005` correction-v5 是实现资格证据，不计入本次正式评测样本。`MVP-R-003` v1、`MVP-R-004` 和 `MVP-R-005` 的所有既有窗口与结果均排除。Critic 只在实验完成后作为非阻断 shadow QA；它的意见不改变实验选择、结果或最终判定。

## 2. 冻结评测对象

### 2.1 产品臂

`Research Agent loop`：

```text
PIT evidence bundle
→ Research Agent 提出 2–3 个有界 Hypothesis
→ deterministic validator
→ 第一个 EXECUTABLE Hypothesis
→ deterministic L0/L1/walk-forward/stress/counterfactual
→ treatment-relative exact view
→ typed falsification predicate
→ Research Agent 四块 Decision Brief
→ optional post-experiment shadow Critic
```

### 2.2 公平基线

`Single-prompt Analyst` 获得相同 Episode、PIT evidence bundle、validation protocol、注册 fallback Hypothesis、确定性实验结果和 treatment-relative exact view。它不得获得更少的数据，也必须服从相同 typed predicate 的确定性结果。

Deterministic Template 不是产品，不进入用户 A/B。

### 2.3 冻结运行配置

- Research/Hypothesis：`gpt-5.6-terra` / `xhigh`。
- Result feedback：`gpt-5.6-terra` / `xhigh`。
- Single-prompt baseline：`gpt-5.6-terra` / `xhigh`。
- Shadow Critic：`gpt-5.6-sol` / `xhigh`。
- 每次模型调用 timeout：180 秒；结构化 schema fail closed。
- 每个 Episode 最多四次产品模型调用；不做人工输出修复。
- 全部自动评测总 token 上限 11,000,000；diagnostic 上限 4,000,000，holdout 上限 7,000,000。
- diagnostic 自动运行墙钟预算 4 小时；holdout 自动运行墙钟预算 6 小时。环境或用户中断造成的暂停不计入模型运行墙钟，但恢复时只能跳过已完整落盘 Episode。

若宿主不暴露某项 executor/model/reasoning 字段，Evidence 必须写 `NOT_EXPOSED`，不得猜测。

## 3. 数据与 roster 冻结

数据只使用已授权的 SHFE/CZCE 官方日行情 PIT records，四个品种为 AG、CU、MA、SR，时间范围为 2026-03-01 至 2026-08-20。Episode 输入只含 `available_time <= as_of` 的 40-bar 窗口，不含 future reveal。

在任何正式模型调用前一次性冻结两个互不重叠的 roster：

- diagnostic：30 条；
- sealed holdout：50 条。

选择器对四个品种和已有 market-state strata 做确定性分层轮转，从每个 cell 的最多 10 个候选中选择；排除所有 R-003/R-004/R-005 roster 三元组 `(instrument, stratum, market_cutoff)`。两个正式 roster 之间也不得重叠。roster 内容、选择规则、数据 manifest 和 SHA-256 在运行前落盘；已有 roster 不得覆盖。

本产品 Gate 衡量研究决策简报质量，不使用 Episode 之后的价格、PnL、Sharpe、胜率或方向准确率宣布产品成立。

## 4. Diagnostic Gate（30 条）

Diagnostic 只验证冻结产品能否进入 sealed holdout，不用于用户价值结论。必须同时满足：

1. 至少 29/30 条无需人工修复完成两条臂；失败必须显式保留且不得重跑为成功。
2. 每个完成 Episode 的 Agent 臂均提出至少一个 `EXECUTABLE` Hypothesis，确定性实验实际运行。
3. 每个完成 Episode 的两条臂全部通过 correction-v5 同等级 exact checks：visible/view、packet→view lineage、typed predicate/FinalVerdict、DecisionBrief/Markdown exact binding、stopped-fold invisibility。
4. 实验前 Critic gate 为 0；Critic 阻断实验为 0。
5. predecessor 与正式 roster overlap 为 0。
6. future leak、无来源数字、未授权工具、交易或账务副作用为 0；四类 Critical 合成反例 4/4 fail closed。
7. diagnostic token 总量不超过 4,000,000，模型运行墙钟不超过 4 小时。
8. 定向 contract tests、全量 `uv run pytest`、`make check`、`git diff --check` 与 health 通过。

任一项失败即记录 `FORMAL_DIAGNOSTIC_FAIL`，不运行 holdout，不在同一预注册版本内 repair/iterate。

## 5. Sealed Holdout Gate（50 条）

只有 Diagnostic Gate 通过才可启动。Holdout 开始后不得修改 Prompt、schema、toolset、模型、阈值、roster、选择器或评分代码。

必须同时满足：

1. 至少 49/50 条无需人工修复完成两条臂；失败显式保留且不得重跑为成功。
2. 所有完成 Episode 满足 Diagnostic 第 2–6 项 exact/边界要求。
3. holdout token 总量不超过 7,000,000，模型运行墙钟不超过 6 小时。
4. 自动 scorecard 由冻结 predicate 计算，禁止写死 PASS。

任一项失败即记录 `FORMAL_HOLDOUT_FAIL`，不进入用户 shadow，不得把 holdout 修补或重跑为通过。

## 6. 独立真实用户 Shadow（10 条）

只有自动 Holdout Gate 通过后，评分器才从完成 holdout 中按冻结 seed 确定性选择 10 条，并对 Research Agent loop 与 Single-prompt Analyst 做 A/B 随机映射。用户评分前不得打开映射。

产品负责人本人逐例回答：

- 更偏好 A、B 或无偏好；
- 是否无需额外解释即可理解；
- 是否明显节省人工研究时间；
- 是否促成“继续实验、加入观察、排除想法或明确暂缓”之一；
- 可选自由文本原因。

揭盲后必须同时满足：

- Research Agent loop 被偏好至少 7/10；
- 至少 7/10 无需额外解释即可理解；
- 至少 5/10 明显节省人工研究时间；
- 至少 3/10 促成明确研究动作。

Codex 可以主持和记录，但不得推断、代填、美化或把协助评分冒充独立真实用户反馈。

## 7. Gate 决定

- `GO`：Diagnostic、sealed Holdout、用户 Shadow 全部通过，且由未主导实现的 reviewer 完成最终功能复核，产品负责人明确记录治理 `GO`。随后立即解锁 `V1-011`。
- `STOP`：任一自动硬门槛或用户价值门槛失败。
- `PIVOT`：产品负责人明确更改产品任务、基线或成功标准；必须先更新 Roadmap 和新预注册，不能改写本次结果。

本次没有 holdout 后 repair/iterate 路径。模型输出不是 authority；typed predicate、确定性工具和冻结 Gate 决定机器结论。

## 8. Evidence 与执行顺序

1. 写入用户授权 Evidence 与本文件 digest。
2. 在任何正式模型调用前同时冻结 diagnostic/holdout rosters、评分配置和 predecessor hash baseline。
3. 运行 30 diagnostic；生成 scorecard。
4. 仅在 diagnostic PASS 后运行 50 sealed holdout；生成 scorecard。
5. 仅在 holdout PASS 后生成 10 条盲评材料，由产品负责人评分。
6. 独立 reviewer 复核实际产物、评分器和用户反馈。
7. 写入治理决定并同步 `docs/ROADMAP.md`、`docs/HANDOFF.md`。

每阶段 Evidence 至少记录实际 executor/model/effort、Prompt/schema/toolset/runtime/data/roster digests、每条模型 usage/latency、失败、人工干预、测试命令和结果。禁止覆盖 R-003/R-004/R-005 历史 Evidence。
