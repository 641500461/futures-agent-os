# MVP-R 正式评测 v2 预注册

文档版本：`2.0-frozen`  
授权日期：2026-09-04  
状态：`AUTHORIZED_FROZEN_NOT_RUN`  
产品边界：研究与模拟；无交易、账户、订单、成交或账本副作用

## 冻结决定

产品负责人确认以 `gpt-5.6-sol / high` 作为本轮 Research、Result feedback、Single-prompt Analyst 和 shadow Critic 的统一产品模型配置。v1 的 `gpt-5.6-terra / xhigh` 预注册、roster、失败和 Evidence 全部保持不变，不重跑、不覆盖。

官方 Codex App Server 当前响应中的 `model_provider` 仅作为宿主观测标签冻结为 `custom`；这不是产品模型名，也不把本轮命名为“custom/high”。正式调用必须同时观察到：`status=completed`、请求模型与响应模型均为 `gpt-5.6-sol`、`reasoning_effort=high`、宿主标签为 `custom`、无 timeout、reroute、dynamic call 或非工具 server request，且只有一个最终 JSON。

## 评测对象与数据

评测对象沿用 v1 的 MVP-R-005 单 Research Agent 闭环与公平 Single-prompt Analyst：PIT evidence bundle → 有界 Hypothesis → deterministic validator → 五项实验 → treatment-relative exact view → typed predicate → 四块 Decision Brief；Critic 只在实验后做非阻断 shadow QA。

数据仍只使用已授权的 SHFE/CZCE 官方日行情 PIT records，品种为 AG、CU、MA、SR，时间范围 `2026-03-01` 至 `2026-08-20`。v2 在任何产品模型调用前冻结 30 条 diagnostic 与 50 条 sealed holdout，排除 R-003/R-004/R-005 及 v1 formal roster，两个 v2 roster 互不重叠；内容、数据 manifest、选择规则、代码和本文件 digest 一并落盘。

## Gate 与停止规则

Diagnostic 必须至少 29/30 完成，且每条完成样本满足 correction-v5 的 exact visible/view、packet→view lineage、typed predicate/FinalVerdict、四块 Markdown、stopped-fold invisibility、无实验前 Critic 门卫、无交易副作用、Critical 4/4、预算与测试要求。否则记录 `FORMAL_DIAGNOSTIC_FAIL`，不启动 holdout。

只有 diagnostic PASS 才运行 50 条 holdout；holdout 至少 49/50 完成并满足同等 exact/边界要求，预算不超 7,000,000 token、6 小时。只有 holdout PASS 才生成 10 条盲评材料；用户 shadow 仍需产品负责人亲自评分，Codex 不代填或推断。

本版本不可在同一预注册内 repair、iterate、修改模型/Prompt/schema/toolset/阈值/roster 或覆盖旧 Evidence。自动 Gate 不能单独产生治理 `GO`；用户价值和最终独立复核仍是必要条件。`V1-011` 在取得明确 `GO` 前保持锁定。

## Evidence

执行器：Codex；implementation/reviewer model profile：`gpt-5.6-sol`；reasoning effort：`high`。每阶段记录请求/响应摘要、usage、latency、失败、人工干预、测试和 predecessor hash。模型正文不作为观测诊断保存。正式运行命令为：

```text
uv run python scripts/run_mvp_r_formal_eval.py --revision v2 --freeze-rosters
uv run python scripts/run_mvp_r_formal_eval.py --revision v2 --phase diagnostic --research-model gpt-5.6-sol --feedback-model gpt-5.6-sol --critic-model gpt-5.6-sol --effort high
uv run python scripts/run_mvp_r_formal_eval.py --revision v2 --phase holdout --research-model gpt-5.6-sol --feedback-model gpt-5.6-sol --critic-model gpt-5.6-sol --effort high
```

v1 结果见 [`MVP-R-FORMAL-EVAL-V1-RESULT.md`](./MVP-R-FORMAL-EVAL-V1-RESULT.md)。
