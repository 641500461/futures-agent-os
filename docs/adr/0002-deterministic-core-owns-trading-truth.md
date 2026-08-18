---
status: proposed
---

# 确定性内核独占交易真值

## Context

LLM 擅长整合不确定证据、提出假设和解释决策，但无法稳定承担价格、账户、PnL、保证金、风险、订单、成交、持仓、结算与强制退出等必须精确、可重放的计算。若模型文本或 Agent 状态可以直接成为这些事实，模型超时、幻觉、重复调用或 Prompt 注入都会转化为交易状态错误。

## Decision

行情快照、合约规则、账户、风险裁决、订单、成交、持仓、账本、结算和 Position Protection 的权威状态与计算全部由可测试、可重放的确定性内核拥有。Agent 只能通过版本化工具读取这些事实并提交结构化提案；Agent checkpoint、对话历史、模型输出和外部 tracing 均不是交易真值，也无权覆盖内核状态。Risk Constitution、Execution/Matching、Accounting/Settlement 与强制保护在 LLM、Agent Runtime 和交互入口不可用时仍独立运行。

## Consequences

- 所有资金和仓位变化都有确定性命令、规则版本、事件和账本证据，可进行故障恢复与历史重放。
- Agent 可以解释风险，但不能批准风险；Simulation Autonomy Mandate 只提供执行授权依据，不放宽 Risk Constitution；Agent 可以建议提前退出，但不能延迟或取消强制保护。
- 需要维护严格的领域对象、精度、时间、幂等、状态机和工具契约，工程成本高于直接让模型调用业务函数。
- Agent 响应中的数字必须引用工具结果；无法获得有效真值时只能 `DEFER`、`NO_TRADE` 或拒绝副作用。

## Considered Options

- 让 LLM 直接计算并写入交易状态：拒绝，因为无法证明正确性和风险边界。
- 由 Agent 与内核共同拥有状态：拒绝，因为会产生冲突写入和不可判定真值。
