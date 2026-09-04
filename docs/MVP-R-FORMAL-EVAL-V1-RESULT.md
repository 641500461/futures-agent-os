# MVP-R 正式评测 v1 结果

状态：`FORMAL_DIAGNOSTIC_FAIL`  
评测日期：2026-09-02  
根因复核日期：2026-09-04  
产品边界：研究与模拟；无交易、账户、订单或账本副作用

## 结论

正式评测 v1 已终止，不进入 sealed holdout 或真实用户 shadow，也不解锁 `V1-011`。

冻结 Diagnostic 要求至少 29/30 完成。前三条 Episode 均在任何产品结果产物落盘前因同一 model workload observation contract 失败而 fail closed；三条失败保留且禁止重跑后，Gate 已不可能通过。自动 scorecard 因而正式记录 `FORMAL_DIAGNOSTIC_FAIL`。

原 [`MVP-R-FORMAL-EVAL-PREREGISTRATION.md`](./MVP-R-FORMAL-EVAL-PREREGISTRATION.md) 保持冻结时的原始字节和 digest，不通过修改其中的旧状态文字来回写结果。

## 已证明与未证明

已证明：

- 30 条 diagnostic 与 50 条 holdout roster 在首个正式模型调用前冻结且互不重叠；
- Critical 合成反例 4/4 fail closed；
- 三条失败都没有人工修复、重跑、工具或交易副作用；
- holdout 与用户 shadow 均未启动。

未证明：

- Research Agent loop 在正式新样本上的完成率和 exact artifact binding；
- 相对 Single-prompt Analyst 的用户价值增量；
- MVP-R `GO` 或 `V1-011` 解锁条件。

## 根因

旧 workload adapter 把 status/provider/model/effort/timeout/reroute/tool-surface 的任一不匹配合并为同一个 `RuntimeError`，失败 Evidence 没有保留具体 observation 摘要，因此 2026-09-02 只能记录 `OBSERVATION_CONTRACT_FAILURE_UNDIFFERENTIATED`。

2026-09-04 增加非敏感、无模型正文的结构化 observation diagnosis，并执行一次不属于 roster、也不计入正式 eval 的最小 probe。Probe 请求 `gpt-5.6-terra / xhigh`；官方 Codex App Server 返回：

- status=`completed`；唯一 final text；无 dynamic call、server request、reroute 或 timeout；
- model=`gpt-5.6-terra`；
- SDK model_provider=`custom`，而冻结契约要求 `openai`；
- 实际 reasoning effort=`high`，而冻结契约要求 `xhigh`。

因此明确 reason codes 为 `PROVIDER_MISMATCH` 与 `EFFORT_MISMATCH`。这是冻结运行配置与宿主实际 observation contract 不一致，不是产品 JSON/Decision Brief 不合格。严格拒绝是正确行为。

## 恢复边界

正式 v1 不得修补或重跑。若继续正式评测，必须：

1. 先选择能被运行时精确观察的 provider/model/effort 契约；
2. 创建新的冻结预注册版本，不覆盖 v1 文档或 Evidence；
3. 冻结全新且排除 v1 diagnostic/holdout 与所有 R-003/R-004/R-005 样本的 roster；
4. 先用 roster 外的 observation preflight 证明宿主配置精确匹配；
5. 再按新版本运行 30 diagnostic；只有 PASS 才能进入 50 holdout 与 10 条真实用户 shadow。

新的预注册不得借基础设施失败降低完成率、exact binding、Critical、预算或用户价值门槛。

## Evidence

- `evidence/mvp-r-formal-eval/diagnostic/scorecard.json`
- `evidence/mvp-r-formal-eval/diagnostic/termination-2026-09-02.json`
- `evidence/mvp-r-formal-eval/recovery/observation-probe-2026-09-04.json`

基础设施修复与复核执行器为 Codex，model=`gpt-5.6-sol`，reasoning effort=`high`。产品 probe model=`gpt-5.6-terra`，请求 effort=`xhigh`，实际 observation effort=`high`。
