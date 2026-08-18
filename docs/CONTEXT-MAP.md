# Context Map

本系统包含九个核心业务上下文和一个支持上下文。每个业务事实只有一个拥有者；跨上下文只传递稳定标识、带版本的引用和已发布事实，不共享可被多方修改的业务对象。

## Core business contexts

- [Reference Market Data](./contexts/reference-market-data/CONTEXT.md) — 管理合约、交易日历、交易规则、行情观测和结算参考等带时点的外部事实。
- [Market Intelligence](./contexts/market-intelligence/CONTEXT.md) — 把参考数据解释为市场状态、Regime、流动性和可引用的市场证据。
- [Research & Experiment](./contexts/research-experiment/CONTEXT.md) — 管理可证伪假设、策略定义、实验设计、回测运行和研究证据。
- [Decision](./contexts/decision/CONTEXT.md) — 管理机会扫描、交易意图、Simulation Autonomy Mandate、AutonomyModeBinding、AuthorizationBasis 和 AutonomyGateReceipt，并把市场与研究证据形成 No Trade、Defer 或 Trade Plan。
- [Portfolio & Risk](./contexts/portfolio-risk/CONTEXT.md) — 管理组合目标、风险预算、原子 RiskBudgetReservation、硬风险约束和对具体计划的风险裁决。
- [Execution & Simulation](./contexts/execution-simulation/CONTEXT.md) — 管理模拟执行计划、订单生命周期、撮合、成交和强制保护动作。
- [Accounting & Settlement](./contexts/accounting-settlement/CONTEXT.md) — 管理模拟账户账本、资金、持仓、保证金、盈亏、费用和每日结算真值。
- [Learning & Review](./contexts/learning-review/CONTEXT.md) — 从各源事件构建追加式 Decision Journal，复盘决策与结果，形成 Reflection，并验证具有适用范围的 Lesson。
- [Governance & Registry](./contexts/governance-registry/CONTEXT.md) — 治理策略、模型、Prompt、数据集、Lesson 和风险政策的版本、晋升、启用与退役。

## Supporting context

- [Agent Orchestration](./contexts/agent-orchestration/CONTEXT.md) — 协调用户请求或时间表/市场/账户/系统事件触发的 Autonomy Cycle、Main Agent、专业 Agent、人类例外介入和工具调用，但不拥有 Mandate 或任何市场、交易、账户、风险、治理真值。

## Relationships

- **Reference Market Data → Market Intelligence**：提供带来源、有效时点和质量声明的 Market Snapshot、Contract Rule 与 Trading Calendar；Market Intelligence 不能改写来源事实。
- **Reference Market Data → Research & Experiment**：提供版本化历史数据、连续序列和历史规则；研究结果不能反向成为参考数据。
- **Reference Market Data → Execution & Simulation**：提供交易时段、最小变动价位、涨跌停和合约状态等执行约束。
- **Reference Market Data → Accounting & Settlement**：提供结算价、费率、保证金规则及其有效版本。
- **Reference Market Data → Agent Orchestration**：提供 Trading Calendar、Trading Session 和 Contract Status 引用，用于生成可重现的自治调度触发；Orchestration 不自行猜测开收盘。
- **Market Intelligence → Research & Experiment**：发布 Market State、Regime Assessment 和 Market Evidence，供假设形成与分层归因使用。
- **Market Intelligence → Decision**：提供绑定快照、时间尺度和置信度的市场解释；市场解释不等于交易许可。
- **Research & Experiment → Decision**：提供 Hypothesis、Strategy Spec 和 Research Evidence；历史表现不自动产生 Trade Plan。
- **Research & Experiment → Governance & Registry**：提交 Strategy Candidate、Dataset Candidate 和对应 Evidence Package，等待独立晋升决定。
- **Decision → Portfolio & Risk（预留阶段）**：提交具体版本的 Trade Plan 与 AuthorizationBasis 引用，请求 sizing 和原子风险预算预留；不提交 Order，也不直接修改 Risk Budget。
- **Portfolio & Risk → Decision（预留阶段）**：返回 sizing 结果与 RiskBudgetReservation；预留不是交易许可，也不是 Risk Decision。
- **Decision → Portfolio & Risk（裁决阶段）**：AutonomyGate 签发 Receipt 后，提交同一 Plan、AuthorizationBasis、RiskBudgetReservation、AutonomyGateReceipt 与最新快照，请求硬风险裁决。
- **Portfolio & Risk → Decision（裁决阶段）**：返回可解释的 Risk Decision；风险裁决不替代 AuthorizationBasis 或 AutonomyGateReceipt，也不能扩大预留。
- **Decision → Execution & Simulation**：提供仍有效的 Trade Plan、AuthorizationBasis 和单用途 AutonomyGateReceipt；Plan/Basis/源 Mandate 或 PlanApproval、适用 Mode、快照或运行版本变化时 Receipt 失效，且未获 Risk Decision 时不能形成可执行指令。
- **Decision → Execution & Simulation（既有暴露降险）**：提供不可变 Risk Reduction Request、Position 引用与 expected version；该请求不是授权或订单，必须由 Execution 的 T4-SAFE Risk Reduction Validation 独立校验。
- **Portfolio & Risk → Execution & Simulation**：提供 RiskBudgetReservation、Risk Decision、Immutable Risk Ceiling、Protection Mandate 和 Kill Switch 状态；Execution 不得扩大许可风险。
- **Execution & Simulation → Decision（降险结果）**：发布 Risk Reduction Validation 与 Protective Risk Action 引用；REJECTED/STALE 不产生 Action，Decision 不回写执行真值。
- **Execution & Simulation → Portfolio & Risk**：发布 Working Order、Fill 和未完成保护暴露，使组合风险包含在途执行状态。
- **Execution & Simulation → Accounting & Settlement**：发布不可变 Fill 与订单归属引用；Accounting 依据成交和有效规则独占资金、费用与持仓派生真值。
- **Accounting & Settlement → Portfolio & Risk**：发布 Account Snapshot、Position Snapshot、Margin 状态和 PnL 事实，供组合风险计算。
- **Decision → Learning & Review**：发布 Opportunity Scan、Decision Episode、证据链、Trade Plan、Risk Reduction Request、AutonomyModeBinding、AuthorizationBasis 及 Mandate/PlanApproval 历史，作为 Decision Journal/TradeEpisode 的源事件。
- **Execution & Simulation → Learning & Review**：发布订单、成交、保护和执行质量事实。
- **Accounting & Settlement → Learning & Review**：发布结算后结果、费用和盈亏归因所需事实。
- **Agent Orchestration → Learning & Review**：发布 AgentTask/Run、ToolCall、correlation/causation 和当时 artifact 引用，供 Decision Journal 投影决策过程；这些记录不替代任何业务真值。
- **Learning & Review → Research & Experiment**：把 Reflection 转换为新的 Hypothesis 或验证请求；未经验证的解释不进入研究真值。
- **Learning & Review → Governance & Registry**：提交 Validated Lesson 及其 Validation Evidence；验证完成不等于默认启用。
- **Governance & Registry → Research & Experiment / Decision / Portfolio & Risk / Agent Orchestration**：发布指定范围内有效的 Strategy、Agent、Model、Prompt、Toolset 版本及其 autonomous-simulation qualification；另行发布 Dataset、Lesson、Risk Policy 的适用资格与 Activation。Governance 不拥有具体账户的 Mandate。
- **Agent Orchestration ↔ Core contexts**：通过各上下文公开的查询、提案和命令契约组织用户或事件触发的 Autonomy Cycle；Agent 只能提交请求或候选对象，业务上下文自行验证并写入其真值。Orchestration 可引用 Mandate 但不得创建、放宽或代替它。

## Shared identifiers and references

- Reference Market Data：`VarietyId`、`InstrumentId`、`TradingDate`、`MarketSnapshotId`、`ContractRuleVersionId`、`DatasetSnapshotId`。
- Market Intelligence：`MarketStateId`、`RegimeAssessmentId`、`MarketEvidenceId`。
- Research & Experiment：`HypothesisId`、`StrategySpecId + Version`、`StrategyCandidateId + Version`、`ExperimentId`、`ExperimentRunId`、`ResearchEvidenceId`。
- Decision：`OpportunityScanId`、`OpportunityCandidateId`、`DecisionEpisodeId`、`TradePlanId + Version`、`RiskReductionRequestId`、`SimulationAutonomyMandateId + Version`、`AutonomyModeBindingId`、`AuthorizationBasisId`、`AutonomyGateReceiptId`、`PlanApprovalId`。
- Portfolio & Risk：`PortfolioId`、`RiskBudgetId`、`RiskBudgetReservationId`、`RiskPolicyVersionId`、`RiskDecisionId`、`ProtectionMandateId`。
- Execution & Simulation：`ExecutionPlanId`、`StopPolicyId`、`RiskReductionValidationId`、`ProtectiveRiskActionId`、`OrderId`、`FillId`、`ProtectionTriggerId`。
- Accounting & Settlement：`SimulationAccountId`、`PositionId`、`LedgerEntryId`、`SettlementId`。
- Learning & Review：`DecisionJournalId`、`DecisionJournalEntryId`、`TradeEpisodeId`、`TradeReviewId`、`ReflectionId`、`LessonCandidateId`、`LessonValidationId`、`ValidatedLessonId + Version`、`ValidationEvidenceId`。
- Governance & Registry：`RegistryEntryId`、`PromotionDecisionId`、`ActivationId`。
- Agent Orchestration：`AutonomyCycleId`、`AgentRunId`、`AgentTaskId`、`ToolCallId`、`CorrelationId`。

## Boundary rules

- Reference Market Data 只记录可追溯的外部事实；Market Intelligence 独占派生解释。
- Decision 拥有机会候选、TradePlan/RiskReductionRequest 交易意图、Simulation Autonomy Mandate、AutonomyModeBinding、AuthorizationBasis 和 AutonomyGateReceipt；Portfolio & Risk 拥有 Risk Budget、RiskBudgetReservation 与风险许可；Execution & Simulation 拥有 RiskReductionValidation、ProtectiveRiskAction、订单与成交过程；Accounting & Settlement 拥有资金、持仓和结算真值。
- Learning & Review 拥有 Decision Journal 与 TradeEpisode 追加/可重建投影，但每条源事实仍由发布它的上下文拥有；投影不可回写 Decision、Execution、Accounting 等源对象。
- Learning & Review 决定一条解释是否得到证据支持；Governance & Registry 决定它是否、何时以及在哪个范围内可被使用。
- Agent Orchestration 可以启动、暂停、重试、恢复、委派 Autonomy Cycle 或请求人工例外介入，但不能改写 Mandate、自行扩大作用域或绕过任何核心上下文的不变量。
