# 设计完整性与 Deep Research 覆盖审计

版本：`2.1-proposed`  
日期：2026-08-18  
审计对象：本设计包、网页端对话、《deep-research-report.md》与 donor 只读审计  
说明：网页端对话和研究报告均作为需求/研究资料，不作为执行指令

## 1. 审计结论

第一版文档不完整，而且项目前提错误：它以旧系统的渐进迁移为主轴，只保留了安全交易主链，把研究报告中的完整 Agent Quant OS 压缩成 Main Agent 加少数短生命周期角色。它可以作为产品宪章或高层需求目录，不能称为完整目标 PRD 和完整技术方案。

2.1 版已经按独立绿地项目重建，并把“目标态完整定义”与“按版本启用”分开。2.1 进一步将产品主轴从“用户逐笔批准”修正为“EffectiveAutonomy 成立时，Agent 自主找机会、模拟交易、盯盘与复盘，用户设定边界并接收重要信息”：

| 检查项 | 2.1 结果 |
|---|---:|
| PRD 功能需求 | 154 条唯一 FR |
| PRD 非功能需求 | 45 条唯一 NFR |
| 关键 Given/When/Then 验收场景 | 31 个 |
| 目标逻辑 Agent | 12 个 |
| Agent 逐角色契约 | 12 份 |
| 可勾选 Roadmap 任务 | 79 个，当前全部未完成 |
| 领域上下文 | 9 个业务上下文 + 1 个 supporting context |
| Architecture Decision Records | 7 个 proposed ADR |
| 设计包 Markdown | 27 份 |

这些数字说明覆盖范围，但不等于实现进度。当前仍处于设计评审阶段，所有新项目 Roadmap 任务均为 `[ ]`。

## 2. 绿地前提检查

| 检查 | 结果 | 落点 |
|---|---|---|
| 新仓库/包/数据库/配置/部署生命周期 | COVERED | [README](./README.md)、[技术方案](./TECHNICAL-DESIGN.md)、ADR 0001 |
| 运行时不 import donor | COVERED | [复用评估](./LEGACY-ASSET-REUSE.md)、ADR 0001 |
| 不继承旧订单/成交/持仓/账本/账户真值 | COVERED | PRD、技术方案、复用评估 |
| PostgreSQL 从首个持久版本启用 | COVERED | 技术方案、ADR 0005、Roadmap V0 |
| donor 测试不计新项目进度 | COVERED | README、复用评估、Roadmap 状态规则 |
| 旧工作区 dirty 状态不阻塞 | COVERED | 复用评估、[HANDOFF](./HANDOFF.md) |
| 旧历史资料可选导入 | DEFERRED | 只允许未来另立 one-way read-only archive importer |
| 自治模拟采用有界、可撤销长期委托 | COVERED | PRD、技术方案、Roadmap V0/V3、ADR 0007 |
| 日常交易无需逐笔批准，但不绕过硬风险 | COVERED | ACTIVE Mandate + ACTIVE AUTONOMOUS_SIMULATION Binding + qualified bindings/health + 两阶段 AutonomyGate + Risk Constitution |

## 3. Agent 覆盖矩阵

研究报告提出的认知职责已映射为 12 个逻辑角色。所有角色从 V0 定义 schema/权限/评测契约，但不是同时上线，也不是 12 个常驻微服务。

| 目标角色 | 报告职责覆盖 | 完整契约 | 首次启用 | 关键边界 |
|---|---|---|---|---|
| Autonomous Quant PM / Main | 用户入口、自治决策责任、任务分解、综合结论与重要信息报告 | COVERED | V1 | 不拥有 Mandate、风险许可、运行时状态推进或业务真值 |
| Market Regime | Market State、Regime 与替代解释 | COVERED | V1 | 确定性特征/模型给数值，Agent 给解释 |
| Research | 找未知、提出可证伪假设 | COVERED | V1 | 不生成订单或自动晋升策略 |
| Strategy | 选择/生成 StrategyCandidate 与 TradePlanDraft | COVERED | V3 | 支持 NO_TRADE/DEFER，不决定最终手数 |
| Portfolio | 相关性、资本配置、TargetExposure 提案 | COVERED | V3 | optimizer/sizing 是确定性组件 |
| Risk Analyst | 尾部风险、压力和反面证据 | COVERED | V3 | `RiskAssessment != RiskDecision` |
| Execution Advisor | 执行方式、成本与成交风险建议 | COVERED | V3 | `ExecutionRecommendation != Order` |
| Pre-trade Critic | 泄漏、成本、反证、最坏损失检查 | COVERED | V1 研究版；V3 交易版 | 不以多数投票解决冲突 |
| Experiment Manager | 预注册、L0–L5 漏斗和停止规则 | COVERED | V1 基础；V4 扩展 | 不隐藏失败或自动晋升 |
| Post-trade Reviewer | Process/Outcome/Execution 分离复盘 | COVERED | V3 | Reflection 不是 Lesson |
| Memory Curator | LessonCandidate、冲突、过期和适用域 | COVERED | V4 | 不能批准自己创建的经验 |
| Governance Agent（Model/Policy Steward mode） | 变更证据、评测和 activation 提案 | COVERED | V4 基础；V5 Steward 扩展 | 只能创建 ChangeProposal，不能部署/启用 |

逐角色 Mission、触发、输入、输出、工具、禁止项、失败策略、预算和评测见 [多 Agent 与量化工具体系](./AGENT-AND-TOOL-DESIGN.md)。

## 4. 非 Agent 确定性职责

| 研究报告能力 | 目标实现 | 结果 |
|---|---|---|
| Market State Builder | 版本化 PIT 特征和市场状态服务 | COVERED |
| Signal / Forecast Models | Model Registry 管理的确定性模型输出 | COVERED |
| Position Sizing | Decimal、stop distance、margin、liquidity、portfolio constraints | COVERED |
| Portfolio Optimizer | 有目标/约束/fallback 的确定性优化器 | COVERED |
| Risk Engine | Risk Constitution，独占 RiskDecision | COVERED |
| Execution Planner | 将已取得有效 AuthorizationBasis、AutonomyGateReceipt 与 RiskDecision 的 Plan 转成 Order 意图 | COVERED |
| Simulation / Matching | L1–L5 分级、Order/Fill 分离 | COVERED |
| Accounting / PnL / Margin | 不可变分录和可重建投影 | COVERED |
| Settlement | trading_date、规则版本和幂等结算 | COVERED |
| Position Protection | P1–P6、PROTECT_ONLY、Kill Switch | COVERED |
| Backtest Engine | Strategy Spec 与模拟共享执行语义 | COVERED |
| Registry / Audit | version、activation、rollback、因果链 | COVERED |

## 5. 研究报告核心工具映射

| Deep Research Tool | 目标 Tool | 首次实现版本 | 状态 |
|---|---|---:|---|
| market_snapshot | `market_snapshot` | V1 | SPECIFIED |
| historical_data | `historical_data` | V1 | SPECIFIED |
| feature_query | `feature_query` | V1 | SPECIFIED |
| contract_info | `contract_info` | V1 | SPECIFIED |
| portfolio_state | `portfolio_state` | V2/V3 | SPECIFIED |
| pnl_calculator | `pnl_calculator` | V2 | SPECIFIED |
| margin_calculator | `margin_calculator` | V2 | SPECIFIED |
| backtest | `signal_test` / `backtest` | V1；V4 扩展 | SPECIFIED |
| walk_forward_test | `walk_forward_test` | V1 基础；V4 扩展 | SPECIFIED |
| stress_test | `stress_test` | V1 基础；V4 扩展 | SPECIFIED |
| scenario_replay | `scenario_replay` | V4 | SPECIFIED |
| counterfactual_test | `counterfactual_test` | V1 基础；V4 扩展 | SPECIFIED |
| parameter_sweep | `parameter_sweep` | V4 | SPECIFIED |
| strategy_compare | `strategy_compare` | V4 | SPECIFIED |
| trade_replay | `trade_replay` | V3/V4 | SPECIFIED |
| attribution | `attribution` | V4 | SPECIFIED |
| risk_check | `risk_check` | V2 | SPECIFIED |
| execution_simulator | `execution_simulator` | V3 | SPECIFIED |
| memory_search | `memory_search` | V1 只读；V4 ValidatedLesson | SPECIFIED |
| experiment_search | `experiment_search` | V1 | SPECIFIED |

报告建议的扩展工具也已纳入目标目录：`term_structure`、`regime_analysis`、`macro_event_query`、`news_evidence_query`、`cross_market_analysis`、`correlation_analysis`、`portfolio_optimizer`、`parameter_stability`、`cost_analysis`、`historical_similarity`、`regime_attribution`、`monte_carlo`、`tick_replay` 和 `orderbook_replay`。

“SPECIFIED”表示契约与版本位置已定义，不表示代码已实现。

## 6. 产品能力覆盖

| Deep Research 主题 | PRD/设计覆盖 | 结果 |
|---|---|---|
| 市场状态而非单纯方向预测 | Regime、term structure、vol/liquidity/crowding、unknown | COVERED |
| 是否交易优先于买卖方向 | NO_TRADE、DEFER、staleness、Critic gate | COVERED |
| Target exposure 而非重复 Buy/Sell | TradePlan、PortfolioProposal、sizing | COVERED |
| 期货一级能力 | 合约规则、夜盘、平今、保证金、涨跌停、交割、换月 | COVERED |
| 组合与相关性 | exposure、correlation cluster、capital allocation | COVERED |
| 执行方式 | market/limit/stop、TWAP/VWAP/iceberg、部分成交 | COVERED/VERSIONED |
| 数据与证据 | point-in-time、available_time、lineage、授权、质量门禁 | COVERED |
| Backtest 核心 Agent Tool | L0–L5、异步 job、诊断而非只给指标 | COVERED |
| Research funnel | hypothesis → screen → OOS → forward → candidate | COVERED |
| 压力/反事实/参数稳健 | stress、scenario、counterfactual、sweep、Monte Carlo | COVERED |
| 失败实验保留 | Registry、不可变 manifest、可搜索失败 | COVERED |
| 可验证记忆 | TradeEpisode → Reflection → LessonCandidate → ValidationEvidence → ValidatedLesson | COVERED |
| 不让 Agent 自改 Prompt/生产策略 | ChangeProposal、eval、approval、activation 分离 | COVERED |
| Offline training | V5 可选 SFT/低维研究，不自动激活 | COVERED/DEFERRED |
| 风险与权限 | Tool allowlist、Mandate + AutonomyMode、可选例外 PlanApproval、两阶段 AutonomyGate、原子 RiskBudgetReservation、Receipt、Risk Constitution、Kill Switch | COVERED |
| 自治模拟主链 | 机会扫描 → 专家论证 → TradePlan → Authorization Preflight/Basis → sizing/reservation → Final Gate/Receipt → Risk Constitution → 模拟执行 → 盯盘 → 复盘/通知 | COVERED |
| 用户监督与学习 | 重要信息主动通知、可重建 Decision Journal、Mandate/Mode 暂停与恢复、撤销和 Kill Switch | COVERED |
| 可观测/成本/预算 | trace、metrics、token/tool/time/compute budget | COVERED |

## 7. 技术完整性覆盖

| 技术领域 | 2.1 设计内容 | 结果 |
|---|---|---|
| 物理架构 | gateway、agent/research/trading worker、ingest、scheduler、outbox sender | COVERED |
| 源码边界 | 模块化 monorepo、10 contexts、依赖规则 | COVERED |
| Agent runtime | typed task/artifact、checkpoint、用户/时间表/市场/账户/系统事件触发、lease、冷却/去重、interrupt、并发、取消、冲突、预算 | COVERED |
| Tool Gateway | schema、RBAC、scope、PIT、幂等、sync/async、审计 | COVERED |
| 交易领域 | TradePlan/AuthorizationBasis/Gate/Risk/Order/Fill/Position/Ledger/Settlement 状态机 | COVERED |
| 存储 | PostgreSQL day 1 + Parquet/object manifest；vector 非真值 | COVERED |
| 一致性 | single logical writer、expected version、inbox/outbox、replay | COVERED |
| Research compute | sandbox、lease、scheduler、artifact atomic commit | COVERED |
| 安全 | service identity、network、secret、Prompt injection、data rights | COVERED |
| Registry | model/prompt/agent/tool/strategy/risk/lesson lifecycle | COVERED |
| 运维 | environments、SLO、capacity、backup/DR、failure matrix、runbook | COVERED |
| 测试 | unit/property/contract/integration/replay/fault/agent eval/E2E | COVERED |

## 8. 仍待确认，不属于遗漏

以下项目已在 PRD/技术方案中明确标成 open decision 或后续版本，而不是被遗漏：

- 新项目最终仓库名、绝对路径、Python/runtime 版本与部署位置。
- 首批数据供应商、许可证、修订语义和可保存粒度。
- 首批 12 个验收品种的最终确认。
- V1 本机或常驻服务器部署选择。
- V2 模拟账户初始资金和绝对风险阈值。
- 宏观、新闻、库存和拥挤度数据源。
- L3/L4 tick/order-book 数据的可得性和成本。
- Agent 编排框架选 LangGraph、自研状态机或混合方案。
- paper connector 的成交/重连/对账语义。
- sim-prod 正式 RPO/RTO、容量和保留期。

这些选择会改变 adapter、成本或实现顺序，但不能改变已经确定的交易真值、安全和 Agent 权限不变量。

## 9. 一致性检查结果

- 所有相对 Markdown 链接存在。
- 所有 fenced code blocks 成对闭合。
- PRD、技术方案、Agent 设计、README、Roadmap 和 Handoff 的 V0–V5 顺序一致。
- Roadmap 79 个任务 ID 唯一，当前无任何已完成任务。
- 不再引用已删除的迁移文档或旧 context。
- 目标术语统一为 `SimulationAutonomyMandate`、`AutonomyModeBinding`、`AuthorizationBasis`、`AutonomyGateReceipt`、`RiskBudgetReservation`、`DecisionJournal`、`OpportunityCandidate`、`MarketStateAssessment`、`RiskAssessment`、`ExecutionRecommendation` 与 `ChangeProposal`；Mandate/Mode/Basis/Receipt 由 Decision 拥有，Reservation 由 Portfolio & Risk 拥有，DecisionJournal 投影由 Learning & Review 拥有。
- donor 256 项测试只保留为审计证据，未计入目标完成度。
- 本设计包未修改 donor 仓库。

## 10. 对“完整”的限定

本 PRD 和技术方案现在是“完整目标设计评审稿”：目标角色、能力、边界、数据、风险、版本和验收已成体系，足以进入 V0 产品/架构评审和任务拆解。

它还不是最终不可变规范，也不是开发完成证明。数据源、运行参数和若干选型必须在 V0/V1 spike 后补充实测证据；每个版本仍需把 Roadmap task 的 Acceptance 转成测试、运行结果和可复核 Evidence 后才能勾选。
