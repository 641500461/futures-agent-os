# 架构决策索引

接受日期：2026-08-18

本目录记录难以逆转、存在真实权衡且仅从代码中无法理解原因的系统级决策。`accepted` 表示后续实现必须遵守；变更已接受决策时，不直接改写其历史结论，而是新增 ADR 并将旧决策标记为 `superseded by ADR-NNNN`。

| ADR | 已接受的决策 |
|---|---|
| [0001](0001-independent-greenfield-project.md) | 建设独立绿地项目，运行时零依赖旧系统 |
| [0002](0002-deterministic-core-owns-trading-truth.md) | 确定性内核独占交易真值 |
| [0003](0003-agent-submits-trade-plans-not-orders.md) | Agent 以 TradePlan 或 RiskReductionRequest 表达意图，不直接提交 Order |
| [0004](0004-relational-current-state-plus-append-only-audit.md) | 采用关系型当前态加追加式审计 |
| [0005](0005-postgresql-from-first-persistent-release.md) | 从首个持久化版本开始使用 PostgreSQL |
| [0006](0006-logical-multi-agent-on-demand-execution.md) | 定义逻辑多 Agent，按需执行专门角色 |
| [0007](0007-revocable-simulation-autonomy-mandate.md) | 采用可撤销的 Simulation Autonomy Mandate，而非默认逐笔批准 |

这些决策共同约束实现：旧项目只能作为 donor；Agent 只表达意图；新增风险必须通过授权、预算预留、最终门禁和硬风控；保护性降险走独立的确定性安全路径；PostgreSQL 同时承载关系当前态与追加审计；逻辑多 Agent 不意味着常驻服务或自由聊天；模拟自治始终受可撤销委托、运行模式、治理资格和健康门禁共同约束。

