# Agent Quant Research & Futures Simulation OS — 产品需求文档

文档版本：`2.2-proposed`<br>
日期：2026-08-25<br>
项目性质：Greenfield，全新独立项目  
工作名称：`Futures Agent OS`  
目标市场：中国境内商品期货与金融期货模拟研究  
产品边界：研究、回测、模拟交易与纸面验证；不包含真实下单  
文档状态：完整评审稿，待产品和架构确认  

## 0. 文档控制

### 0.1 本 PRD 回答的问题

- 为什么要建设这个产品，而不是给现有脚本加一个聊天入口？
- 产品最终包含哪些 Agent、工具、决策和安全边界？
- 系统如何在用户不参与日常操作时自主运行，用户又如何监督、学习和随时干预？
- 期货模拟、回测、复盘和自我优化分别需要做到什么程度？
- 每个版本交付什么、明确不交付什么、怎样算验收通过？
- 现有 `futures_workflow` 能复用什么，但为什么不是本项目的代码基座？

### 0.2 相关文档

- [多 Agent 与工具体系](./AGENT-AND-TOOL-DESIGN.md)
- [技术方案](./TECHNICAL-DESIGN.md)
- [旧项目资产复用评估](./LEGACY-ASSET-REUSE.md)
- [版本路线图](./ROADMAP.md)
- [MVP-R 研究可用性验证](./MVP-RESEARCH-VALIDATION.md)
- [领域上下文地图](./CONTEXT-MAP.md)
- [跨对话交接](./HANDOFF.md)
- [系统架构、用户生命周期与盯盘调度](./SYSTEM-ARCHITECTURE-AND-LIFECYCLE.md)

### 0.3 术语强制区分

- “全新项目”指新仓库、新包结构、新数据模型和新运行时，不继承旧数据库为系统真值。
- “复用”指选择性移植算法、adapter 思路、测试样本和业务规则；不等于在旧项目中重构。
- “Agent”指有独立使命、输入输出、工具权限和评测的 LLM 角色；确定性引擎不是 Agent。
- “模拟交易”指系统自有撮合和账本产生的交易事实；TradePlan、信号或价格触发都不等于成交。
- `Simulation Autonomy Mandate`（模拟交易自治委托，以下简称 `Mandate`）是 Decision 上下文拥有的、版本化、可过期、可暂停和可撤销的模拟交易授权边界。
- `AuthorizationBasis` 是 TradePlan 进入 Policy/Risk Gate 的授权依据，只能是有效 Mandate，或显式启用的可选逐 Plan Approval；默认产品路径使用有效 Mandate。
- `AutonomyGateReceipt` 是确定性 AutonomyGate 针对某个 Plan、AuthorizationBasis、源授权（Mandate 或 PlanApproval）与快照组合签发的短期、单用途许可凭证；它不是 AuthorizationBasis 或 RiskDecision，也不能绕过硬风控。
- `RiskBudgetReservation` 是 Portfolio & Risk 为候选计划原子预留的临时风险额度，用于防止多个并发计划各自合规、合计却超限；它不是最终仓位或风险许可。
- `AUTONOMOUS_SIMULATION` 是默认目标运行模式：只有 EffectiveAutonomy 成立时，Agent 才能自主寻找机会并完成模拟交易闭环；用户处于 human-on-the-loop，主要观察、学习、接收重要通知和执行例外控制。

## 1. 执行摘要

本产品是一套由 Autonomous Quant PM Agent 持续负责机会发现和完整 Trade Episode、由专业 Agent 提供研究与反证、并由确定性量化内核负责真值计算和安全执行的期货研究与自主模拟交易操作系统。系统的默认目标不是等待用户逐笔发起和审批，而是在用户预先授予的模拟交易自治边界内独立运行，让用户通过重要通知、决策日志和复盘学习其操作。

核心闭环：

```text
市场与账户真值
→ Regime 判断
→ 研究假设
→ 策略/交易计划
→ 独立反证
→ 组合与风险分析
→ AuthorizationBasis 校验
→ 原子风险预算预留
→ AutonomyGateReceipt
→ 硬风险裁决
→ 订单/撮合/账本/保护
→ 归因与复盘
→ 实验验证
→ 有效期内的经验与策略新版本
```

本产品不是：

- 一个只回答“涨还是跌”的预测机器人；
- 一个让 LLM 直接调用 `place_order()` 的系统；
- 一个把回测指标包装成对话的报表工具；
- 一个亏损后自动修改 Prompt 的自我强化循环；
- 一个把日常机会筛选、下单判断和盯盘操作重新丢给用户的人工工作流；
- 一个以现有 `futures_workflow` 为目录继续扩建的重构项目。

## 2. 产品愿景与定位

### 2.1 愿景

培养一个可持续评测和改进的 Autonomous Quant PM Agent：它能在预授权模拟边界内主动寻找机会、形成并执行模拟交易计划、持续盯盘、退出和复盘；用户不用承担日常基本操作，却能从完整证据链中学习它如何观察、判断、控制风险和认错。

### 2.2 产品定位

| 维度 | 定位 |
|---|---|
| 核心用户 | 单一系统拥有者/观察学习者起步，未来支持研究与治理团队 |
| 主要入口 | 飞书 + CLI；后续可增加 Web Console |
| 核心价值 | 自主机会发现、受约束模拟交易、风险纪律、可学习的决策证据闭环 |
| 交易模式 | 模拟交易与纸面验证 |
| Agent 模式 | Autonomous Quant PM 持续负责，专业 Agent 按需协作 |
| 真值模式 | 确定性数据、风险、订单、账本和结算 |
| 学习模式 | Reflection → Experiment → Validated Lesson |
| 系统演进 | 版本化、Shadow 评测、自治委托、人在环上监督、可回滚 |

### 2.3 产品护城河

长期壁垒不是某一个 LLM 或开源回测库，而是以下组合：

1. point-in-time 统一数据与交易规则；
2. 可验证的多 Agent 协作协议；
3. 回测、模拟和纸面交易共享的执行语义；
4. 实验注册、失败保留和策略晋升体系；
5. 带证据、适用域和有效期的经验记忆；
6. 不可绕过的权限、风险和审计体系。

## 3. 背景与机会

### 3.1 传统量化的局限

传统量化擅长重复执行明确定义的规则，但在跨来源证据整合、非结构化事件、假设生成、反证搜索和自然语言协作上成本较高。

### 3.2 通用 LLM 交易助手的局限

- 容易把推理流畅度误当数值正确性。
- 无法天然保证行情、仓位、保证金和 PnL 是最新真值。
- 对同一输入可能给出不稳定决策。
- 容易在亏损后产生事后解释，并把解释自我强化为经验。
- 缺少订单、成交、部分成交、涨跌停和结算等现实约束。

### 3.3 产品机会

把 LLM 用在“不确定且需要综合判断”的部分，把所有可精确计算、可审计和必须强制执行的部分交给量化工具，可以形成比单一模型或单一策略框架更可靠的系统。

## 4. 目标、约束与非目标

### 4.1 产品目标

- `G-001` 建立一个对完整 Trade Episode 负责的 Autonomous Quant PM Agent，并由专业 Agent 提供独立研究、反证、组合、风险和执行建议。
- `G-002` 在用户离线且 EffectiveAutonomy 成立时，系统可完成“扫描 → 研究 → 计划 → Policy/Risk Gate → 模拟成交 → 盯盘 → 退出 → 复盘”。
- `G-003` 每个关键判断都有数据、规则、实验或记忆证据引用。
- `G-004` 所有模拟暴露都经过确定性仓位、保证金和风险裁决。
- `G-005` LLM 全部离线时，已有仓位仍受保护并可结算。
- `G-006` 回测、模拟与纸面交易使用一致的 Strategy Spec 和执行语义。
- `G-007` 系统能够主动提出研究问题、寻找交易机会和运行实验，而不是只响应用户。
- `G-008` 复盘能区分过程质量、结果质量和执行质量。
- `G-009` 未经验证的 Reflection 永远不能成为默认交易知识。
- `G-010` 每项产品能力、Agent、Tool、策略、Prompt 和风险规则都可版本化、评测和回滚。
- `G-011` 用户无需承担日常筛选、逐笔许可和盯盘操作，只接收重要通知并可随时暂停、撤销或降低风险。
- `G-012` 每笔自主决策形成按时间还原的 Decision Journal，使用户能学习 Agent 当时看到了什么、为什么行动、如何管理和何时认错。
- `G-013` 自主执行与自主改权严格分离；Agent 不得自行启用新策略、模型、Prompt、工具、风险规则或更大 Mandate。

### 4.2 硬约束

- `C-001` 真实交易不在项目范围。
- `C-002` Agent 不拥有数据库交易写权限。
- `C-003` Agent 不能绕过 Risk Constitution。
- `C-004` 价格、PnL、保证金、持仓、成交和结算必须来自确定性工具。
- `C-005` 没有完整 ProtectionIntent 和 MaxLoss 的 TradePlan 不能进入风险链；没有 Risk Decision 生成的 ProtectionMandate 及 Execution 落地的全量 StopPolicy 不能建立暴露。
- `C-006` Mandate/Risk Policy 已授权的风险只可由普通运行路径降低，不能由 Agent 或普通管理指令扩大。
- `C-007` 历史证据、失败实验和审计记录不可由 Agent 删除或改写。
- `C-008` 没有有效 AuthorizationBasis 的 TradePlan 不能进入风险裁决；默认 AuthorizationBasis 必须引用 ACTIVE Mandate。
- `C-009` 用户、飞书或通知通道离线不得阻塞已有仓位保护、结算和对账。

### 4.3 非目标

- 首期不做 PPO/RL 主 Agent。
- 首期不做模型微调平台。
- 首期不做常驻多 Agent 群聊或投票系统。
- 首期不承诺全品种 Tick/Order Book 数据。
- 首期不建设复杂移动端/Web 交易终端。
- 不把用户逐笔审批作为默认模拟交易运行方式；逐 Plan Approval 仅是可选兼容模式。
- 不以 Sharpe、胜率或单次盈利作为自动晋升依据。
- 不把旧项目数据库迁入新项目作为强制启动条件。

## 5. 用户、Persona 与 Jobs-to-be-Done

### 5.1 系统拥有者 / 观察学习者

目标：让系统在受控边界内独立完成模拟交易日常工作，自己通过重要信息和完整操作日志监督并学习。

核心 JTBD：

- 当我不在线时，持续筛选期货机会并在我授予的模拟边界内安全完成交易闭环。
- 当系统决定交易或不交易时，保留当时的证据、反证、风险与观察重点，让我可以事后学习。
- 当建立、调整或退出模拟仓位时，只把重要信息及时告诉我，不等待我替系统完成日常判断。
- 当风险、数据或系统状态异常时，主动降级、暂停新仓并告诉我发生了什么。
- 当我需要干预时，让我能立即暂停新仓、撤销 Mandate、减仓或全部退出。
- 当交易结束时，分别评价 Agent 的过程、结果与执行，并说明可迁移和不可迁移的经验。
- 当策略退化时，主动发起研究而不是事后找理由。

可选 JTBD：

- 当我观察到一个市场现象时，把观点转成可证伪假设并验证。
- 当我提问时，用当时的 Decision Journal 解释系统为何采取或放弃某项操作。

### 5.2 量化研究者

目标：高吞吐地产生、筛选、诊断和比较策略假设。

核心 JTBD：

- 统一使用数据、成本、规则和回测级别。
- 快速淘汰没有预测力或不稳健的想法。
- 查看收益来自哪里、在哪些状态失效。
- 保存失败实验，防止重复踩坑。

### 5.3 风险/系统维护者

目标：证明系统没有越权、无保护仓位、重复副作用或审计缺口。

核心 JTBD：

- 查询每笔交易完整因果链。
- 查看风险规则版本、拒绝原因、Kill Switch 和异常。
- 评估 Agent/Prompt/Tool 版本是否可以启用。
- 演练故障恢复和回滚。

## 6. 产品能力地图

```text
Futures Agent OS
│
├── Interaction & Orchestration
│   ├── Feishu / CLI
│   ├── Autonomous Quant PM Agent
│   ├── Delegation / Mandate / Escalation
│   └── Long-running Tasks
│
├── Market Intelligence
│   ├── Market Snapshot / Data Quality
│   ├── Regime / Term Structure
│   ├── Macro / News / Cross-market
│   └── Contract Rules / Trading Calendar
│
├── Alpha Research
│   ├── Hypothesis / Feature / Signal
│   ├── Strategy Generation
│   ├── Backtest / Walk-forward
│   └── Stress / Counterfactual / Robustness
│
├── Trading Decision
│   ├── No Trade / Defer
│   ├── Strategy / Direction
│   ├── Target Exposure
│   ├── Entry / Exit / Invalidation
│   ├── Critic / AuthorizationBasis
│   └── Simulation Autonomy Mandate / AutonomyGateReceipt
│
├── Portfolio & Risk
│   ├── Account / Position / PnL
│   ├── Exposure / Correlation
│   ├── Risk Budget / Atomic Reservation / Sizing
│   └── Risk Constitution / Kill Switch
│
├── Execution & Simulation
│   ├── Order / Fill / Position / Settlement
│   ├── Market / Limit / Stop / TWAP / VWAP
│   ├── Partial Fill / Liquidity / Slippage
│   └── Position Protection
│
├── Learning
│   ├── Trade Replay / Attribution
│   ├── Reflection / Lesson Validation
│   ├── Episodic Memory
│   └── Experience Replay
│
└── Governance & Operations
    ├── Strategy / Experiment / Model Registry
    ├── Agent / Prompt / Tool Eval
    ├── Audit / Version / Governance Approval
    └── Deployment / Rollback / SLO
```

## 7. 多 Agent 产品模型

### 7.1 Agent 名录

| Agent | 产品责任 | 主要产物 | 是否可触发交易副作用 |
|---|---|---|---|
| Autonomous Quant PM / Main Agent | 持续机会发现、完整 Trade Episode 责任、用户意图理解与认知决策综合 | OpportunityDecision、TradePlan、DecisionJournal 输入 | 仅在 EffectiveAutonomy 成立时自主提交 Plan；不能创建 Order，不拥有 durable 编排状态 |
| Market Regime Agent | 市场状态解释 | MarketStateAssessment | 否 |
| Research Agent | 未知问题与实验假设 | Hypothesis、ResearchPlan | 否 |
| Strategy Agent | 策略/交易计划形成 | StrategyCandidate、TradePlanDraft | 否 |
| Critic Agent | 独立反证 | Critique | 否 |
| Portfolio Agent | 组合与资本分配建议 | PortfolioProposal | 否 |
| Risk Analyst Agent | 尾部风险解释 | RiskAssessment | 否 |
| Execution Advisor Agent | 执行方式比较 | ExecutionRecommendation | 否 |
| Post-trade Reviewer Agent | 交易复盘 | TradeReview、Reflection | 否 |
| Experiment Manager Agent | 预注册与实验推进 | ExperimentPlan | 仅创建研究任务 |
| Memory Curator Agent | 经验验证与过期 | LessonCandidate | 否 |
| Governance Agent（V5 扩展 Model/Policy Steward 工作模式） | 变更提案与证据检查 | ChangeProposal | 否 |

逐 Agent 的输入、输出、工具、权限、失败降级和评测见 [AGENT-AND-TOOL-DESIGN.md](./AGENT-AND-TOOL-DESIGN.md)。

### 7.2 为什么需要多个 Agent

- Strategy Agent 有提出方案的目标，Critic 必须具有独立反证目标。
- Portfolio 与单笔 Strategy 的最优目标不同，必须单独审视组合暴露。
- Risk Analyst 负责解释不确定风险，Risk Engine 负责硬执行，二者不可混淆。
- Reviewer 不能由原 Strategy Agent 自评，否则容易维护原叙事。
- Memory Curator 必须阻断“反思直接变知识”。

### 7.3 为什么不全部常驻

完整逻辑角色从第一天定义，但按场景调用：

- 普通行情问答不需要启动 Experiment Manager。
- 没有候选计划不启动 Portfolio/Risk/Execution 专家。
- 交易结束前不启动 Reviewer。
- 未启用的角色保持明确不可用；Main Agent 不静默冒充专业 Agent，只能显示降级状态或改走确定性流程。

这是一种版本裁剪，不是删除目标 Agent 架构。

## 8. Agent 可决策与不可决策范围

### 8.1 可决策

- 是否需要研究或补充证据。
- 当前市场状态的解释与候选分类。
- 是否存在交易机会或应 `NO_TRADE`。
- 选择候选策略、方向和目标风险意图。
- Entry/Exit/Invalidation/ProtectionIntent 草案。
- 在 EffectiveAutonomy 内是否提交 OPEN TradePlan、输出 HOLD 决定，或对已有暴露提交 REDUCE/CLOSE/收紧止损的 `RiskReductionRequest`。
- 是否启动 backtest、stress、counterfactual 或 walk-forward。
- 是否提出 Lesson/Strategy/System improvement candidate。

### 8.2 不可决策

- 当前真实价格、持仓、余额、PnL、保证金和成交。
- 绕过、关闭或修改硬风险规则。
- 在普通运行中扩大 Mandate/Risk Policy 已授权风险。
- 直接创建 Order 或 Fill。
- 修改历史实验、交易和审计记录。
- 创建、扩大、延长、激活或恢复自己的 Mandate。
- 把逐 Plan Approval 当作绕过 Mandate 或风险限制的例外许可。
- 自动把 Reflection 升级为 Validated Lesson。
- 自动晋升策略、Prompt、Agent 或模型版本。
- 开启真实交易权限。

## 9. 核心产品对象与生命周期

### 9.1 Hypothesis

状态：`DRAFT → READY_FOR_TEST → TESTING → SUPPORTED/PARTIAL/REJECTED/STALE`。

必须包含：主张、适用市场、可观察结果、反证条件、所需数据和提出来源。

### 9.2 Strategy Candidate

归属 Research & Experiment 的 StrategyCandidate 唯一状态集为：`DRAFT` → `HISTORICAL_SCREENING` → `OOS_VALIDATION` → `PAPER_EXPERIMENT` → `PROMOTION_CANDIDATE` → `SUBMITTED`。任一阶段都可进入 `REJECTED/ARCHIVED`。Candidate 不得进入 ACTIVE；SUBMITTED 后由 Governance & Registry 创建独立 Governed StrategyVersion，其资格/启用状态为 `CANDIDATE → EVALUATED → QUALIFIED → APPROVED → ACTIVE → QUARANTINED/RETIRED`。被 QUARANTINED 的版本不可回退，修复从新 StrategyCandidate DRAFT 开始。

任一行为规则改变即产生新版本，旧证据保留但不再覆盖新版本。

### 9.3 TradePlan

默认自治路径状态：`DRAFT → CRITIC_REVIEW → VALIDATED → AUTHORIZATION_PENDING → SIZING_PENDING → RISK_BUDGET_RESERVED → AUTONOMY_GATE_PENDING → AUTONOMY_PERMITTED → RISK_PENDING → RISK_APPROVED/RISK_MODIFIED → EXECUTION_ACTIVE`；RiskDecision 的 REJECT、PROTECT_ONLY、HALT 分别进入 `RISK_REJECTED`、`PROTECT_ONLY`、`HALTED`，其他校验也可进入 `REJECTED/STALE`。任何 RISK_REJECTED、PROTECT_ONLY、HALTED、REJECTED、STALE 或超时分支都必须幂等释放未消费的 RiskBudgetReservation。

可选逐 Plan Approval 路径：`AUTHORIZATION_PENDING → ESCALATION_REQUIRED → SIZING_PENDING/REJECTED/STALE`；只有 GRANTED Approval 被原子标为 CONSUMED 并为原 Plan Version 创建唯一 `basis_kind=PLAN_APPROVAL` AuthorizationBasis 后才进入 sizing。编辑产生新 Plan Version 并回到 DRAFT；等待例外审批时不占用 RiskBudgetReservation，最终仍须签发新 Receipt 并进入 RISK_PENDING。

TradePlan 不是 Order；无论 AuthorizationBasis 来自 Mandate 还是逐 Plan Approval，Risk Engine 都可修改数量或拒绝。

### 9.4 Order / Fill / Position

- Order 有 accepted/working/partial/filled/cancelled/expired/rejected 生命周期。
- Fill 是不可变成交事实。
- Position 只能由 Fill 和 Settlement 改变。
- Stop trigger 产生 Order，不直接产生 Fill。

### 9.5 Reflection / Lesson

这是多对象派生流水线，而不是共享一个状态写者：`Reflection → LessonCandidate → LessonValidation + ValidationEvidence → ValidatedLesson`。`LessonCandidate` 独立经历 `DRAFT → READY_FOR_VALIDATION → VALIDATING → REJECTED/LOW_CONFIDENCE/VALIDATED`；验证通过后才创建新的 `ValidatedLesson`，其生命周期为 `VALIDATED → EXPIRED/SUPERSEDED/REVOKED`。Governance 的资格与 Activation 是独立事实；只有尚有效且具有当前适用 Activation 的 ValidatedLesson 才进入默认决策检索。

### 9.6 Simulation Autonomy Mandate

归属 Decision 上下文，主路径为 `DRAFT → VALIDATED → APPROVED → ACTIVE`；ACTIVE 可进入 `SUSPENDED/HALTED`，HALTED 只能经 `RECOVERING` 与规定恢复门禁回到 ACTIVE。`EXPIRED/REVOKED` 是不可恢复终态：除 `DRAFT` 外的任一非终态都必须在 `expires_at` 到达时进入 EXPIRED；`APPROVED/ACTIVE/SUSPENDED/HALTED/RECOVERING` 都可被有权主体撤销。任何 activate/resume/recover 都必须重新校验 expiry 与 revocation。

必须包含：账户、品种池、交易时段、允许动作、Strategy/Agent/Prompt/Model/Tool 版本范围、单笔/组合/日风险、保证金与并发仓位限制、交易和计算预算、通知策略、有效期、降级与 Kill 条件。普通 TradePlan 只能引用一个在决策时与提交时均为 ACTIVE 的 Mandate。

Mandate 的 `SUSPENDED` 仅表达业务授权暂停（如 `USER_PAUSE/AUTHORITY_SCOPE_DISABLED`），只能由用户或有权主体显式恢复；运行健康降级和策略/版本隔离由 AutonomyMode 的 `PAUSED` 及 Watch Health 管理，不静默改写 Mandate。`HALTED` 必须根因处理、对账和人工恢复门禁。Agent 永远不能自行恢复、扩大或续期 Mandate。

### 9.7 Autonomy Mode Binding

`AutonomyMode` 是 Decision 上下文中针对“Simulation Account + 研究/交易作用域 + 精确 Strategy/Agent/Model/Prompt/Tool 版本”的运行级别绑定，支持 `OBSERVE`、`SHADOW`、`AUTONOMOUS_SIMULATION`、`PAUSED`。OBSERVE/SHADOW 可使用只读 ScanPolicy/UniversePolicy，`mandate_ref` 可空且不得提交交易；只有 AUTONOMOUS_SIMULATION 必须绑定 ACTIVE Mandate。Binding 另有 `ACTIVE/EXPIRED/SUPERSEDED` 生命周期；到期或被新 Binding 替代会立即使 EffectiveAutonomy 为 false，并使未消费 Basis/Receipt stale、释放 reservation，但不停止已有仓位保护。它与 Mandate 状态不是同一对象：Mandate 回答“边界内是否有委托”，AutonomyMode 回答“当前允许运行到哪一级”。

- `OBSERVE` 只生成市场观察与 OpportunityDecision；`SHADOW` 在 TradePlan 能力启用后可形成完整但不可提交的 TradePlan；`AUTONOMOUS_SIMULATION` 是 Agent 产生模拟副作用的必要 Mode，但仍须与 ACTIVE Mandate、qualified bindings 和健康门禁共同形成 EffectiveAutonomy；`PAUSED` 禁止新增风险但不停止已有仓位保护。
- `OBSERVE → SHADOW → AUTONOMOUS_SIMULATION` 是权限升级，需通过相应评测、治理资格与有权主体激活；Agent 不能自行升级。
- 运行健康、策略/版本隔离或运营者可把任一运行模式降级为 `PAUSED`。`PAUSED` 保留 `previous_mode`、reason 和 evidence；恢复只能回到先前已获资格的模式，不得借恢复扩权。
- 任一 Mandate、策略或运行版本变化都使旧绑定失效并触发重新校验。

有效自治的合成判定唯一为：`EffectiveAutonomy = ACTIVE Mandate ∧ ACTIVE AUTONOMOUS_SIMULATION Binding ∧ qualified bindings ∧ health permits`。优先级为 `HALT/PROTECT_ONLY > Mandate/Mode Binding 无效 > Mode PAUSED > 授权链`，任一不成立均禁止新增风险。用户的“暂停自治”是一个组合命令：同一事务将 Mandate 记为 `SUSPENDED(USER_PAUSE)`、Mode 记为 `PAUSED`，并使未消费的 Basis/Receipt 失效、释放 reservation；恢复时两个对象的门禁都必须通过。Watch Health 只提供独立硬阻断/保护事实，不授权任何恢复。

AutonomyMode 只治理 Agent-initiated 路径。V2 的显式 CLI/API 验收使用 `execution_origin=MANUAL_TEST + PlanApproval + 模拟环境权限`，可不绑定 AutonomyMode，仍必须经过 AuthorizationBasis、reservation、Final Gate 和 RiskDecision；V3 中由 Agent 发起的例外 PlanApproval 仍必须有 AUTONOMOUS_SIMULATION Mode。

### 9.8 Decision Journal

Decision Journal 是面向审计和用户学习的不可改写时间线，连接 opportunity、snapshot、Evidence、Counter Evidence、Agent runs、TradePlan、AuthorizationBasis、RiskBudgetReservation、AutonomyGateReceipt、RiskDecision、Order/Fill、Position monitoring、exit、Review 和当时的 Unknowns。事后复盘可以追加，但不能重写当时理由。

## 10. 核心使用旅程

### J-001 首次启用自治

1. 用户选择模拟账户、品种池、交易时段、允许策略和通知偏好。
2. 系统生成 Simulation Autonomy Mandate 草案，展示单笔、组合、日损失、保证金、并发仓位、交易频率、预算和 Kill 条件。
3. 系统校验 Mandate 所引用的 Strategy/Agent/Prompt/Model/Tool 与 Risk Policy 版本。
4. 用户在治理界面激活 Mandate；该动作是运行范围授权，不是逐笔交易审批。
5. 新能力先进入 `OBSERVE` 或 `SHADOW`，通过启用门槛后进入 `AUTONOMOUS_SIMULATION`。

验收：没有 ACTIVE Mandate 不能建立新暴露；激活记录绑定用户、版本、范围、时间、有效期与不可重放 token。

### J-002 自主机会发现与模拟开仓

1. Trading Calendar Scheduler 在适用交易时段触发扫描，Market/Signal 服务先做低成本候选过滤。
2. Autonomous Quant PM 对高价值候选启动 Regime、Research/Strategy、Critic、Portfolio 和 Risk Analyst 的最小充分协作。
3. Agent 选择 `NO_TRADE`、`DEFER` 或生成带完整失效与退出条件的 TradePlan。
4. Authorization Preflight 先解析授权：范围内创建绑定 ACTIVE Mandate 的 AuthorizationBasis；只有 Mandate 允许的例外才发起 PlanApproval，GRANTED Approval 原子消费后创建唯一新 Basis；无回复、拒绝、超时或重复消费不交易。
5. 已有效授权依据后，Position Sizing 计算候选数量与最坏风险，Portfolio & Risk 原子预留候选风险预算；等待例外审批时不占预算。
6. Final AutonomyGate 使用 Plan、AuthorizationBasis、源授权（Mandate 或 PlanApproval）hash、AutonomyMode、最新快照、运行版本和 RiskBudgetReservation 签发短期单用途 Receipt；此阶段越界、过期或冲突只能拒绝或 PROTECT_ONLY，不再发起升级。
7. Risk Constitution 使用最新快照裁决允许数量，并消费、缩小或释放预留。
8. 通过后由 Execution Core 自动建立模拟 Order；Agent 不能创建 Order 或 Fill。
9. 用户收到重要决策/成交说明，但常规路径不等待用户回复。

验收：用户离线时可完成全链路；重复扫描合并；任一 Policy/Risk Gate 拒绝都不产生 Order。

### J-003 自主盯盘与持仓管理

1. Market、Order、Position、Portfolio Risk、Thesis 和 System Health watcher 持续处理事件。
2. 确定性 Protection 执行硬止损、trailing、time stop、portfolio stop 和 Kill Switch。
3. Autonomous Quant PM 根据新证据选择 HOLD，或对已有暴露提交 `RiskReductionRequest`（REDUCE/CLOSE/收紧止损）。
4. 确定性 T4-SAFE Validator 必须证明该请求只减少现有暴露、不反向、不放宽 ProtectionMandate/StopPolicy，才可生成 `ProtectiveRiskAction`；否则拒绝或作为新 TradePlan 重走全链。
5. 重要变化、保护触发、未成交风险和异常即时通知用户；普通噪声进入摘要。

验收：用户、飞书或 LLM 离线不影响确定性保护；Agent 不能删除保护、放宽止损或借调整扩大风险。

### J-004 自主退出、结算与复盘

1. Thesis 失效、目标完成、时间到期、风险事件或 Protection 触发退出。
2. Agent 无需用户回复即可提交针对已有 Position 的 REDUCE/CLOSE `RiskReductionRequest`；确定性 Core 只在单调降险证明通过后创建 ProtectiveRiskAction/Order。
3. Accounting 完成费用、PnL、保证金、结算和对账。
4. Reviewer 读取完整 Trade Episode，分别评价 Process、Outcome 和 Execution。
5. 系统生成 Decision Journal 终章和用户可读教学复盘。
6. Reflection 保持 UNVALIDATED，不能直接改变下一笔交易。

验收：退出原因、当时证据、实际 Fill、未成交路径和结果归因可重放；事后数据不改写开仓理由。

### J-005 用户观察与学习

1. 用户查看开盘前范围、当日机会、Agent 操作、当前持仓和风险摘要。
2. 每笔重要操作卡展示“看到了什么、为何行动、什么会证明错误、风险多少、接下来盯什么”。
3. 用户可追问任一 Trade Episode 的当时信息与反事实，不需要参与该笔操作才能理解。
4. 收盘/结算后收到日报，周/月收到行为模式、错误复发和策略退化报告。

验收：所有解释引用当时 snapshot 与版本；报告明确区分当时判断和事后复盘。

### J-006 用户例外干预

1. 用户可随时执行“暂停新仓”“撤销 Mandate”“减仓”“全部退出”“收紧止损”或 Kill Switch。
2. 降低风险的命令直接进入确定性校验与执行，不等待 Agent 同意。
3. 扩大风险、放宽止损、启用新版本或解除 Kill Switch 不能走普通交易指令。
4. 恢复自治必须重新检查 Mandate、系统健康、数据和风险状态。

验收：暂停新仓不破坏已有保护；撤销后不再新增暴露；重复控制命令不产生重复副作用。

### J-007 市场问答（可选旁路）

用户：“铁矿石现在怎么看？”

1. Autonomous Quant PM 确认目标合约/品种与时间范围。
2. Data Quality 检查可用数据。
3. Market Regime Agent 读取 Market State、期限结构和模型结果。
4. 返回状态、证据、反证、不确定项和有效期，并说明这与当前自治决策有何关系。
5. 问答本身不扩大 Mandate，也不自动成为交易授权。

验收：所有数字引用 snapshot；数据不完整时明确降级。

### J-008 用户观点研究（可选旁路）

用户：“我觉得周线箱体上沿可以试空。”

1. Research Agent 把观点转为可证伪 Hypothesis。
2. 查询相似场景、Regime、成本和当前合约风险。
3. 必要时创建 quick backtest，由 Critic 检查反证与成本覆盖。
4. 若形成 TradePlan，仍必须独立满足 EffectiveAutonomy 与完整 Policy/Risk Gate；用户观点不是授权。

验收：不自动补造用户未定义的关键规则；所有假设和反证可追溯。

### J-009 策略退化研究

1. 监控发现 OOS、成本或 Regime 表现退化。
2. 系统根据门槛降级、暂停相关策略或停止新仓。
3. Research Agent 分解可能原因，Experiment Manager 预注册实验。
4. 通过分阶段测试形成继续、修订或退休提案。

### J-010 经验晋升

1. 多个 Review 产生同类 Reflection。
2. Memory Curator 合并冲突、保留反例。
3. Experiment Manager 执行验证。
4. 符合门槛才形成 Validated Lesson，并设置适用域与过期时间。
5. Lesson 或 Strategy Candidate 的运行启用仍需治理批准，不能由交易 Agent 自行激活。

### J-011 系统能力改进

1. Governance Agent 汇总证据并形成 ChangeProposal；V5 可由 Model/Policy Steward 工作模式扩展模型与政策类提案。
2. 用户批准设计、开发和运行启用中的相应阶段。
3. 未启用版本不能影响运行 Agent、Mandate 或 Risk Policy。

### J-012 调度、错过任务与恢复

1. Trading Calendar 与 SchedulePolicy 生成开盘前、盘中、bar-close、收盘、结算和周期研究任务。
2. 每项任务使用 lease、idempotency key、deadline 和 missed-run policy。
3. 重启后系统恢复 watcher 与未完成状态，按策略补跑或明确跳过过期扫描。
4. 恢复前禁止在不确定状态下建立新暴露，已有仓位进入 protect-only。

验收：任务不能无声丢失；补跑不使用未来数据、不重复下单。

## 11. 详细产品需求

## 11.1 Epic A — Market Intelligence

- `FR-MKT-001` 支持 Instrument、Variety、主力合约、次主力和 Continuous Series 的严格区分。
- `FR-MKT-002` Market Snapshot 必须包含 `as_of`、trading date、source、freshness、quality、schema version 和 immutable ID。
- `FR-MKT-003` 支持价格、成交量、持仓量、bid/ask、期限结构、基差、波动和流动性。
- `FR-MKT-004` 支持日/周/月与多种盘中周期，并标记未完成 bar。
- `FR-MKT-005` 支持 Regime 候选：Trend、Mean-Reversion、High/Low Vol、Liquidity Stress、Event、Limit Risk、Rollover。
- `FR-MKT-006` Regime 必须输出候选状态与冲突，不强迫唯一标签。
- `FR-MKT-007` 宏观和新闻只作为带来源与发布时间的 Evidence，不能覆盖行情真值。
- `FR-MKT-008` 数据质量必须区分“可展示”“可研究”“可回测”“可执行”。
- `FR-MKT-009` 缺失、陈旧、冲突、跳点、断层和 source fallback 产生稳定 error/warning code。
- `FR-MKT-010` 所有派生特征记录窗口、计算版本和所用数据快照。

Acceptance：给定同一 snapshot 和 feature version，确定性特征一致；陈旧数据可展示但不能执行；Continuous Series 永远不能成为 Order instrument。

## 11.2 Epic B — Futures Rules & Calendar

- `FR-RULE-001` 规则按交易所、品种、合约和有效区间管理。
- `FR-RULE-002` 支持 multiplier、tick、最小下单量、保证金、手续费、平今费、涨跌停、限仓和交易限额。
- `FR-RULE-003` 支持 calendar date 与 trading date、夜盘、节假日、集合竞价和休市。
- `FR-RULE-004` 支持最后交易日、交割月限制和临近交割风险。
- `FR-RULE-005` 支持主力切换、连续合约拼接/复权、换月事件和换月成本。
- `FR-RULE-006` 规则缺失时金额回测和交易 fail closed，不使用永久默认值冒充。

Acceptance：能还原指定历史日期的适用规则；规则变化不改写旧 BacktestRun；夜盘正确归属 trading date。

## 11.3 Epic C — Agent Orchestration

- `FR-AGT-001` 每个 Agent 具有 role version、prompt version、tool allowlist、输入/输出 schema 和 eval suite。
- `FR-AGT-002` Autonomous Quant PM 能按市场事件、调度任务、持仓变化或用户意图选择最小充分专家集合。
- `FR-AGT-003` 每次委托保存 task、parent run、预算、deadline、evidence scope 和结果状态。
- `FR-AGT-004` 专家结果必须包含 Evidence、Counter Evidence、Unknowns、Warnings、Confidence 和 expiry。
- `FR-AGT-005` Agent 冲突不得靠多数投票解决，必须按职责边界或补证据。
- `FR-AGT-006` Agent 失败必须显示 Partial/Deferred/Failed，不能静默由 Main Agent伪造结果。
- `FR-AGT-007` 长任务可暂停、恢复、取消和查询进度。
- `FR-AGT-008` 只有 Mandate 激活/扩大、治理变更、异常恢复或显式逐 Plan Approval 才使用持久 interrupt；默认自治交易不得等待用户响应。
- `FR-AGT-009` 每个 Agent run 可关联 tool calls、输入快照、输出和用户反馈。
- `FR-AGT-010` 任何 Agent 不得拥有直接交易数据库写权限。

Acceptance：重复恢复不会重复调用有副作用工具；禁用某专家时 Main Agent 明确降级；越权 tool call 被拒绝并记录。

## 11.4 Epic D — Research & Strategy

- `FR-RES-001` Research Agent 能把用户观点、市场候选或 Agent 观察转为可证伪 Hypothesis。
- `FR-RES-002` ResearchPlan 明确数据、对照、窗口、指标、停止条件和潜在偏差。
- `FR-RES-003` 保存支持和反对 Hypothesis 的全部重要实验。
- `FR-RES-004` Strategy Spec 明确筛选、入场、退出、失效、仓位、保护、适用市场和非适用市场。
- `FR-RES-005` Strategy Agent 必须支持 `NO_TRADE` 与 `DEFER`。
- `FR-RES-006` confidence 只表达模型意见，不直接决定数量。
- `FR-RES-007` Critic 独立检查泄漏、成本、集中度、参数稳定和历史失效 Regime。
- `FR-RES-008` 任一策略行为变化产生新 Strategy Spec version。
- `FR-RES-009` 失败实验可检索并阻止无意义重复。
- `FR-RES-010` 研究任务有资源预算，避免 Agent 无限回测。

Acceptance：不完整策略保持 DRAFT；不能因为回测失败而删除 Run；Critic REJECT 后原版本不能进入 Authorization/Risk Gate。

## 11.5 Epic E — Trade Decision, Authorization & Mandate

- `FR-DEC-001` TradePlan 必须包含 instrument、intent、direction、Thesis、Invalidation、target risk、entry、ProtectionIntent、max loss、exit、snapshot refs 和 expiry；Risk 随后把 ProtectionIntent 固化为 ProtectionMandate，Execution 再转化为 StopPolicy。
- `FR-DEC-002` 使用 Target Exposure/Target Position，不允许 Agent 连续发 Buy/Sell 指令。
- `FR-DEC-003` 决策结果支持 OPEN、REDUCE、CLOSE、HOLD、NO_TRADE、DEFER，但对象映射必须固定：OPEN 或任何可能新增/反向风险的变化使用 TradePlan 全链；已有暴露的 REDUCE/CLOSE/收紧保护使用 `RiskReductionRequest → T4-SAFE Validator → ProtectiveRiskAction`，只有无法证明风险单调下降时才按新 TradePlan 重走全链；HOLD/NO_TRADE/DEFER 不产生交易命令。第一阶段不支持反手原子指令。
- `FR-DEC-004` 显示支持证据、反面证据、未知、Regime 和成本。
- `FR-DEC-005` 每个可提交 TradePlan 必须具有 AuthorizationBasis：引用一个有效 Mandate，或在显式启用时引用逐 Plan Approval。
- `FR-DEC-006` Mandate 归属 Decision 上下文，并绑定账户、品种池、时段、允许动作、策略与运行版本、风险和预算边界、通知政策、有效期及 Kill 条件。
- `FR-DEC-007` 价格、账户、规则或风险变化超过阈值后 Plan stale。
- `FR-DEC-008` Risk Engine 拒绝后必须展示稳定 reason code 和可行修订方向。
- `FR-DEC-009` AuthorizationBasis 只允许提交风险裁决，不承诺 Risk APPROVE、Order 或 Fill。
- `FR-DEC-010` 默认 Agent 路径只在 EffectiveAutonomy 成立时无需逐 Plan Approval；可选 Approval 模式不得成为扩大 Mandate、绕过运行健康门禁或绕过 Risk Constitution 的例外通道。
- `FR-DEC-011` Mandate 状态至少包含 DRAFT、VALIDATED、APPROVED、ACTIVE、SUSPENDED、EXPIRED、REVOKED、HALTED、RECOVERING，只有 ACTIVE 可授权新增暴露。
- `FR-DEC-012` Mandate 激活、扩大、延长、`USER_PAUSE` 恢复和 `HALTED` 恢复必须经过相应的人类权限门禁；`HEALTH_DEGRADED` 与 `POLICY_OR_VERSION_QUARANTINE` 将 AutonomyMode 置为 PAUSED，前者仅可在显式 policy 与健康稳定窗口通过后自动回到 previous_mode，后者需要已批准 fallback 或新版本；Agent 只能请求暂停或缩小范围，不能执行任何恢复或扩权。
- `FR-DEC-013` TradePlan 提交前必须二次校验 Mandate 状态、绑定版本、剩余预算和策略适用域。
- `FR-DEC-014` 用户执行“暂停自治”时必须事务性联动 Mandate SUSPENDED 与 AutonomyMode PAUSED；任一者无效都立即禁止新 OPEN，使未消费 Receipt 失效并释放 reservation；已有 Position 继续保护并按退出政策管理。
- `FR-DEC-015` 逐 Plan Approval 如被启用，必须绑定用户、Plan version/hash、时间、范围、有效期和一次性 token，状态为 REQUESTED/GRANTED/REJECTED/EXPIRED/CONSUMED；GRANTED 只能在原子创建唯一 PLAN_APPROVAL AuthorizationBasis 时转为 CONSUMED 并记录 consumer basis，数据库唯一约束禁止同一 Approval 生成第二个 Basis，且执行前仍重新检查 staleness。
- `FR-DEC-016` 确定性 AutonomyGate 包含两阶段：Authorization Preflight 可输出 AUTHORIZED、ESCALATE、REJECT 或 PROTECT_ONLY，完成可选单次升级后必须创建新 AuthorizationBasis；随后的 Final Gate 只能输出 PERMIT、REJECT 或 PROTECT_ONLY。只有 Final PERMIT 才能签发绑定 Plan、AuthorizationBasis、源授权（Mandate 或 PlanApproval）hash、快照、AutonomyMode、运行版本、预算预留、有效期和单次消费 nonce 的 AutonomyGateReceipt。

Acceptance：过期/暂停/撤销 Mandate、非 AUTONOMOUS_SIMULATION Mode、越界 Plan、旧 Approval、重复授权和被修改 Plan 均不能产生订单；EffectiveAutonomy 成立时，用户离线不阻塞合法计划。

## 11.6 Epic F — Portfolio & Risk

- `FR-RSK-001` Portfolio Snapshot 统一呈现资金、持仓、保证金、已实现/未实现 PnL 和风险暴露。
- `FR-RSK-002` 支持品种、行业、期限、方向、策略和 Regime 暴露。
- `FR-RSK-003` Position Sizing 同时受 max loss、stop distance、margin、集中度和 liquidity 约束。
- `FR-RSK-004` RiskDecision 统一为 APPROVE、MODIFY、REJECT、PROTECT_ONLY 或 HALT，并保存逐规则证据；MODIFY 只能单调缩小风险。
- `FR-RSK-005` Risk Constitution 至少覆盖数据、规则、单笔、组合、日损失、交割、流动性和 Kill Switch。
- `FR-RSK-006` 每个 Position 的全部剩余数量必须有保护覆盖。
- `FR-RSK-007` Mandate/Risk Policy 给定的 immutable risk ceiling 只能降低；逐 Plan Approval 也不能突破该 ceiling。
- `FR-RSK-008` Risk Analyst 的文字不能替代 RiskDecision。
- `FR-RSK-009` 实验账户可以不用固定本金，但必须有绝对风险/保证金/并发限额。
- `FR-RSK-010` 未知 multiplier、margin rule、stop risk 或 account state 时拒绝建立暴露。
- `FR-RSK-011` 对所有可能新增风险的并发计划使用原子 RiskBudgetReservation；预留必须支持超时、释放、缩小、消费和对账，任何时点的已用风险与有效预留之和不得突破预算。

Acceptance：多空、部分成交、部分止盈、加仓、跨夜和规则变化下风险计算可重现；扩大止损请求 100% 拒绝。

## 11.7 Epic G — Execution, Simulation & Accounting

- `FR-EXE-001` 显式区分 ExecutionPlan、Order、Fill、Position、PositionLot 和 LedgerEntry。
- `FR-EXE-002` 支持 Market、Limit、Stop；TWAP/VWAP/分批按版本加入。
- `FR-EXE-003` 支持 accepted、working、partial、filled、cancelled、expired、rejected。
- `FR-EXE-004` Stop trigger 只生成 Order，不假设在 trigger price 成交。
- `FR-EXE-005` 支持无对手盘、涨跌停、无流动性、撤单和部分成交。
- `FR-EXE-006` 每个 Fill 使用适用 tick、费用、滑点和规则版本。
- `FR-EXE-007` 支持开仓、平仓、平今和多 lot 归属。
- `FR-EXE-008` 支持每日盯市、保证金变化和 Settlement。
- `FR-EXE-009` Accounting 是 PnL/余额/费用唯一来源。
- `FR-EXE-010` 每个命令有 idempotency key，外部至少一次投递只产生一次业务效果。
- `FR-EXE-011` 每个模拟结果显示当前真实性级别和 FillModel。
- `FR-EXE-012` 不允许将 Bar 级模拟描述为 Order Book 级结果。

Acceptance：账本守恒；Position 可由 Fill/Settlement 重建；同一事件重放不重复成交。

## 11.8 Epic H — Position Protection

- `FR-PRO-001` P1 初始硬止损在开仓前注册。
- `FR-PRO-002` P2 Thesis Invalidated 可建议提前退出，但不延迟 P1。
- `FR-PRO-003` P3 ATR/Trailing 为确定性规则。
- `FR-PRO-004` P4 Time Stop 按 Strategy Spec 执行。
- `FR-PRO-005` P5 Portfolio Stop 根据账户/组合状态执行。
- `FR-PRO-006` P6 Kill Switch 具有最高优先级。
- `FR-PRO-007` 保护订单未成交时持续显示剩余未保护/未退出风险并升级。
- `FR-PRO-008` 对已有暴露，Agent 可提交减仓、退出和收紧保护的 `RiskReductionRequest`；即使 Mandate/Mode 已失效，确定性 T4-SAFE Validator 仍可在证明风险单调下降后生成 `ProtectiveRiskAction`，但 Agent 不能删除保护、反向持仓或扩大风险。
- `FR-PRO-009` 模型、飞书和 Agent worker 离线时保护仍运行。
- `FR-PRO-010` 无保护 Position 是最高级系统事故。

## 11.9 Epic I — Backtest & Validation

- `FR-BT-001` 支持 L0 Signal、L1 Bar、L2 Event、L3 Tick、L4 Order Book、L5 Paper 分级。
- `FR-BT-002` Agent 根据问题选择最低充分级别，不默认最慢级别。
- `FR-BT-003` Run 固定 Strategy、Dataset、Rule、Cost、Engine、Model/Prompt、seed 和 code version。
- `FR-BT-004` 输出 performance、year/month、symbol、Regime、long/short、cost、drawdown、worst trades 和 robustness。
- `FR-BT-005` 自动检测 return concentration、parameter instability、cost sensitivity、data gap、rollover concentration 和 sample shortage。
- `FR-BT-006` 支持 walk-forward、Monte Carlo、stress、counterfactual 和 scenario replay。
- `FR-BT-007` 回测与模拟在同级数据下复用 Order/Fill/Accounting 语义。
- `FR-BT-008` 缺数据或规则时 Run 为 INCOMPLETE，不进入晋升。
- `FR-BT-009` 报告同时提供机器 JSON 和人类 HTML。
- `FR-BT-010` 大规模 Hypothesis funnel 支持异步、取消、预算和优先级。

## 11.10 Epic J — Review, Learning & Memory

- `FR-LRN-001` 每笔交易具有由 Learning & Review 基于源事件与 Decision Journal 构建、可重建的完整 Trade Episode；Accounting 只发布结算/持仓事实，不拥有该跨链投影。
- `FR-LRN-002` Review 分 Process、Outcome、Execution 三类质量。
- `FR-LRN-003` 保存计划遵守、机会成本、T+N 和未执行候选证据。
- `FR-LRN-004` Reflection 默认 UNVALIDATED。
- `FR-LRN-005` LessonCandidate 明确验证方法与所需样本。
- `FR-LRN-006` ValidatedLesson 包含证据、反例、置信度、适用市场/Regime、created/expiry。
- `FR-LRN-007` Lesson 冲突时并存或降权，不静默覆盖。
- `FR-LRN-008` 过期 Lesson 不进入默认高权重检索。
- `FR-LRN-009` Memory Search 区分 raw episode、reflection 和 validated lesson。
- `FR-LRN-010` 经验可以提出 Strategy Candidate，但不能自动启用。
- `FR-LRN-011` 每笔自主 Trade Episode 生成 Decision Journal，记录当时观察、证据、反证、Unknowns、决策、AuthorizationBasis、风险、执行和后续监控。
- `FR-LRN-012` Decision Journal 必须区分 decision-time fact 与 post-hoc analysis，后者只能追加而不能改写前者。
- `FR-LRN-013` 面向用户的教学复盘解释“为何交易/不交易、什么会证明错误、实际如何执行、下一次应观察什么”，并引用原始证据。
- `FR-LRN-014` 系统支持按品种、策略、Regime、错误类型和 Agent 版本查询操作案例，使用户可以学习和比较 Agent 行为。

## 11.11 Epic K — Registry & Governance

- `FR-GOV-001` Strategy、Experiment、Agent、Prompt、Tool、Model、Risk Policy 均有 Registry 与版本状态。
- `FR-GOV-002` 变更分为缺陷、系统能力、策略、Prompt/Agent、模型、风险规则和数据规则。
- `FR-GOV-003` 不同风险等级走不同审批路径。
- `FR-GOV-004` 设计批准、开发批准、合并验收和运行启用独立。
- `FR-GOV-005` 交易行为、风险、模型或数据语义变化必须有离线评测和受限启用。
- `FR-GOV-006` 失败版本和回滚版本保持可用。
- `FR-GOV-007` Governance Agent 及其 V5 Model/Policy Steward 工作模式只能提案，不能执行 Registry 变更。
- `FR-GOV-008` 审计查询可以从用户消息追踪到最终系统状态。

## 11.12 Epic L — Interaction & Notifications

- `FR-UX-001` 支持飞书单聊/指定群和 CLI。
- `FR-UX-002` 飞书入站快速去重入箱，耗时工作异步执行。
- `FR-UX-003` 支持运行、进度、完成、失败、降级、暂停、等待治理操作和取消状态；默认交易不显示等待逐笔审批。
- `FR-UX-004` 卡片显示数据时间、Agent 状态、计划、风险、证据和按钮。
- `FR-UX-005` 所有价格、PnL、保证金和持仓数字引用工具快照。
- `FR-UX-006` 通知等级统一为 INFO、TRADE、ACTION_REQUIRED、RISK、CRITICAL；TRADE 用于无需回复的关键交易生命周期说明，ACTION_REQUIRED 仅用于 Mandate/治理/恢复等确需用户动作的事项，不用于常规逐笔交易。
- `FR-UX-007` 可订阅品种、策略、风险和实验事件，支持静默时段但 CRITICAL 不静默。
- `FR-UX-008` 用户可查询“系统为什么这样做”和完整证据链。
- `FR-UX-009` 所有界面明显标记模拟环境。
- `FR-UX-010` 入口不可直接传入任意数据库 ID 或篡改数量/价格。
- `FR-UX-011` 重要操作通知说明“发生了什么、Agent 为什么这样做、风险多少、接下来盯什么”，但不把通知送达作为交易前置条件。
- `FR-UX-012` 用户可一键暂停新仓、撤销 Mandate、减仓、全部退出和查看自治状态；降低风险命令优先于 Agent 计划。
- `FR-UX-013` 提供开盘前范围、盘中重要事件、收盘/结算日报和周/月教学复盘，普通扫描与 `NO_TRADE` 默认聚合。

## 11.13 Epic M — Operations & Administration

- `FR-OPS-001` 提供 Data、Agent、Tool、Queue、Risk、Order、Protection、Backtest 健康面板。
- `FR-OPS-002` 提供 Kill Switch、暂停新计划、暂停 Agent、暂停某策略/账户的独立控制。
- `FR-OPS-003` 配置通过版本化 policy 管理，不把 secrets 写入代码或日志。
- `FR-OPS-004` 支持备份、恢复、重放、对账和灾难演练。
- `FR-OPS-005` 提供 Agent/Model token、费用、延迟和质量报表。
- `FR-OPS-006` 提供数据授权、保留和删除政策。
- `FR-OPS-007` Trading Calendar Scheduler 支持开盘前、盘中、bar-close、收盘、结算、日/周/月任务，并为每项任务配置 lease、deadline、retry 和 missed-run policy。
- `FR-OPS-008` 提供 Mandate、AutonomyMode、扫描覆盖、漏扫、干预、通知和无人值守运行健康面板。
- `FR-OPS-009` 系统恢复时已有仓位优先进入 protect-only；在状态、数据、Mandate 和风险均确认前禁止新 OPEN。

## 11.14 Epic N — Autonomous Operation & Supervision

- `FR-AUT-001` 支持 `OBSERVE`、`SHADOW`、`AUTONOMOUS_SIMULATION`、`PAUSED` 四种运行模式及可审计状态转换；AutonomyModeBinding 的 `ACTIVE/EXPIRED/SUPERSEDED` 生命周期独立记录，expiry/supersession 原子失效相关 Basis/Receipt 并释放 reservation。
- `FR-AUT-002` `OBSERVE` 只生成市场观察；`SHADOW` 生成但不提交 TradePlan；只有 `AUTONOMOUS_SIMULATION` 与 ACTIVE Mandate、qualified bindings、健康门禁共同形成 EffectiveAutonomy 时，Agent 才能产生模拟交易副作用。
- `FR-AUT-003` Scheduler、market event、position event、risk event 和 system recovery 均可触发 Autonomous Quant PM；用户消息不是必需触发源。
- `FR-AUT-004` 系统先用确定性筛选合并低价值和重复候选，再为高价值候选调用最小充分 Agent 图。
- `FR-AUT-005` Autonomous Quant PM 对每个候选明确输出 TRADE、NO_TRADE 或 DEFER，并记录未交易机会。
- `FR-AUT-006` 满足 AuthorizationBasis、原子 RiskBudgetReservation、有效 AutonomyGateReceipt 和 Risk Gate 后，系统无需用户回复即可把 TradePlan 交给 Execution Core。
- `FR-AUT-007` 自主循环覆盖 scan、plan、critic、authorize、risk、execute、watch、exit、settle、review；任一阶段失败都产生显式状态。
- `FR-AUT-008` Agent 可在 EffectiveAutonomy 内提交 OPEN TradePlan、输出 HOLD，并对已有暴露提交 REDUCE/CLOSE/收紧止损的 RiskReductionRequest；只有被确定性证明单调降险的请求可不创建新 TradePlan/Receipt/Reservation，任何反向、增加暴露或放宽保护的请求必须走新暴露全链；Agent 不能直接创建 Order/Fill。
- `FR-AUT-009` 支持每品种/策略 cooldown、每日交易次数、连续亏损、回撤、token/tool/compute budget 和重复入场限制。
- `FR-AUT-010` 数据陈旧、规则缺失、预算耗尽、Agent/Tool 异常、策略退化或版本漂移触发 fail-closed、degraded、protect-only 或 pause。
- `FR-AUT-011` 用户可在任何时候暂停新仓、撤销 Mandate、降低暴露或触发 Kill Switch；Agent 无权阻止或自动恢复。
- `FR-AUT-012` 重要通知至少覆盖新仓、加减仓、退出、保护触发、未成交风险、Mandate 变化、降级、Kill Switch 和日终结果。
- `FR-AUT-013` INFO/普通 NO_TRADE 可聚合，RISK/CRITICAL 不得因静默时段而抑制；通知失败不阻塞交易保护。
- `FR-AUT-014` 自主运行不得自动启用新的 Strategy、Agent、Prompt、Model、Tool、Risk Policy 或 Validated Lesson 版本。
- `FR-AUT-015` 每个自治周期和 Trade Episode 都可从 Decision Journal 重放，并能回答用户“为何行动、为何未行动、何时认错”。

Acceptance：用户离线一个完整交易时段时，系统能在 Mandate 内安全完成至少一次 `NO_TRADE` 或完整模拟 Trade Episode；零越权、零重复副作用、零无保护仓位，且重要操作可解释。

## 12. Tool 产品面

目标 Tool surface（V0 定义契约，V1–V5 按路线启用实现）：

```text
market_snapshot        historical_data       feature_query
contract_info          term_structure        regime_analysis
portfolio_state        pnl_calculator        margin_calculator
position_sizing        exposure_analysis     risk_check
signal_test            backtest              walk_forward_test
stress_test            scenario_replay       counterfactual_test
parameter_sweep        strategy_compare      trade_replay
attribution            execution_simulator   memory_search
experiment_search      submit_trade_plan      get_trade_status
request_close_position tighten_stop           submit_review
get_autonomy_mandate   get_autonomy_status    pause_new_positions
revoke_mandate         request_reduce_all     request_close_all
```

完整分类、权限和 Agent allowlist 见 [AGENT-AND-TOOL-DESIGN.md](./AGENT-AND-TOOL-DESIGN.md)。

## 13. 权限矩阵

| 动作 | Agent | 确定性系统 | 用户 |
|---|---|---|---|
| 查询市场/账户 | 按角色允许 | 提供真值 | 允许 |
| 提出 Hypothesis/Strategy | 允许 | 校验 schema | 允许 |
| 创建 Backtest/Experiment | 允许，受预算 | 执行并记录 | 允许/取消 |
| 生成 TradePlan | Autonomous Quant PM/Strategy 提案 | schema/Policy 校验 | 可观察、追问；可选 Approval 模式下编辑/批准/拒绝 |
| 激活/扩大/延长 Mandate | 只能提案 | 校验并持久化授权 | 有权限用户批准 |
| 暂停/缩小 Mandate | 可因风险请求 | Policy Engine 立即生效 | 允许 |
| 撤销 Mandate/暂停新仓 | 不可阻止 | 立即禁止新 OPEN | 允许 |
| 决定允许数量 | 禁止 | Risk Engine 独占 | 不能绕过 |
| 创建 Order | 禁止 | Execution Core 独占 | 只能经具有 AuthorizationBasis 的 Plan 流程 |
| 提前退出/减仓 | 可请求 | 校验并执行 | 允许 |
| 收紧止损 | 可请求 | 验证风险下降 | 允许 |
| 放宽止损/提高 Mandate 风险 | 禁止普通路径 | 拒绝 | 新 Mandate version + 治理批准 + 硬上限 |
| 修改 PnL/Fill/历史 | 禁止 | 仅追加更正 | 禁止直接修改 |
| 晋升 Lesson/Strategy/Agent | 只能提案 | Registry 执行批准结果 | 最终批准 |
| 解除 Kill Switch | 禁止 | 高权限流程 | 强认证/双确认 |

## 14. 飞书产品体验

### 14.1 市场卡片

- 品种/合约、数据时间和质量。
- Regime、趋势、波动、流动性和期限结构。
- Main Agent 结论、支持/反对证据和未知。
- 当前账户暴露和风险摘要。
- 操作：详细研究、历史案例、快速回测、查看最近决策；不会把“创建计划”作为用户日常必需操作。

### 14.2 自主决策与成交说明卡

- Thesis / Invalidation。
- Entry / Target Exposure / Exit / ProtectionIntent，以及随后生成的 ProtectionMandate / StopPolicy。
- Mandate/AuthorizationBasis、RiskDecision、实际 Order/Fill、保证金和最大损失。
- Critic、Portfolio 和 Risk Analyst 摘要。
- 发生时间、所用 snapshot、Agent/Strategy/Prompt/Model 版本和接下来监控项。
- 操作：查看证据、追问原因、暂停新仓、减仓、退出、收紧止损；默认不提供逐笔批准按钮。

### 14.3 持仓卡

- Position、Fill、均价、PnL、保证金。
- 当前保护层、剩余最大风险、未成交保护订单。
- Agent 当前 Thesis 状态、下一观察点和最近自主操作。
- 操作：详细路径、暂停新仓、减仓、退出、收紧止损。

### 14.4 复盘卡

- Process / Outcome / Execution 三类评分。
- 主要证据、反事实和待验证 Reflection。
- 操作：启动研究、创建实验、仅记录、不采纳。

### 14.5 自治状态与学习日报

- 当前 AutonomyMode、Mandate version/expiry、账户/品种/策略范围和剩余风险预算。
- 当日扫描覆盖、TRADE/NO_TRADE/DEFER、Risk Reject、成交、持仓和漏扫情况。
- Agent 做对/做错/尚不能判断的过程行为，以及对应 Decision Journal。
- 重要事件即时发送，普通机会与未交易原因聚合；用户可按事件展开完整证据链。
- 操作：暂停/恢复申请、撤销 Mandate、全部退出、调整通知偏好；恢复或扩大范围走治理授权。

## 15. 数据、证据与报告

### 15.1 数据要求

- 所有研究和交易数据 point-in-time。
- 原始数据、清洗数据、特征、快照和报告有 lineage。
- 规则、费用和合约信息同样 point-in-time。
- 连续合约与可交易合约分开。
- 数据质量结论按用途输出。

### 15.2 证据要求

每项 Agent 结论至少具有：

- Evidence refs。
- Counter Evidence refs 或明确“未找到”。
- snapshot/time/version。
- Unknowns 与 expiry。
- 结论来源 Agent/Tool/Model/Prompt。

### 15.3 标准报告

- 市场状态报告。
- TradePlan 与 RiskDecision 报告。
- 订单/成交/持仓路径报告。
- Backtest diagnostic HTML + JSON。
- 日/周组合与策略复盘。
- Agent 质量/费用/越权报告。
- Autonomous Run、Mandate、机会漏斗、人工干预和通知质量报告。
- Decision Journal、用户教学日报与周/月行为复盘。
- Experiment/Strategy/Memory 生命周期报告。
- 系统审计和健康报告。

## 16. 非功能需求

### 16.1 正确性与一致性

- `NFR-COR-001` 金额、费用、保证金和 PnL 使用 Decimal/定点精度。
- `NFR-COR-002` Position 只能由 Fill/Settlement 改变。
- `NFR-COR-003` 同一输入、版本和 seed 的确定性计算一致。
- `NFR-COR-004` 状态投影、审计事件和 outbox 原子提交。
- `NFR-COR-005` 相同 idempotency key 最多一次业务效果。

### 16.2 安全

- `NFR-SEC-001` 最小权限和服务身份分离。
- `NFR-SEC-002` secrets 不进入 Git、Prompt、artifact 或普通日志。
- `NFR-SEC-003` 外部网页/新闻/用户附件均视为不可信数据。
- `NFR-SEC-004` Tool Gateway 在 Agent 之外再次鉴权和校验。
- `NFR-SEC-005` Mandate 激活/变更、可选逐 Plan Approval、恢复自治和解除 Kill Switch 等 Critical action 使用一次性 token、过期和重放防护。

### 16.3 可用性与恢复

- `NFR-AVL-001` 已接受交易命令 RPO=0。
- `NFR-AVL-002` 单节点重启 60 秒内恢复保护状态和未完成任务。
- `NFR-AVL-003` LLM 不可用不影响已存在保护。
- `NFR-AVL-004` Gateway、Agent、Research 和 Trading worker 可独立降级。
- `NFR-AVL-005` 每季度至少一次恢复演练；V4 提升为每月。
- `NFR-AVL-006` 用户、飞书或通知通道离线时，EffectiveAutonomy 范围内的自治流程不等待人工响应；已有保护无论 Mandate/Mode 是否有效都继续运行，通知进入可靠 outbox 并补发。
- `NFR-AVL-007` 重启后 60 秒内恢复 watcher、Mandate 状态和未完成交易任务；新开仓在一致性确认前保持禁用。

### 16.4 性能

- `NFR-PERF-001` 飞书事件 2 秒内完成验证、去重和入箱。
- `NFR-PERF-002` 热数据 RiskDecision P99 < 100ms。
- `NFR-PERF-003` 行情进入保护引擎到生成 Order 的目标 P99 < 1s。
- `NFR-PERF-004` 普通市场问答 10 秒内给首个进度，完整回答目标 60 秒内。
- `NFR-PERF-005` 长回测 5 秒内返回 task handle 和估计阶段，不阻塞会话。
- `NFR-PERF-006` bar-close 扫描在该周期可用数据确认后 60 秒内完成确定性候选筛选，超时任务显式标记 MISSED/DEFERRED。
- `NFR-PERF-007` 新仓、退出和 RISK/CRITICAL 事件进入通知 outbox 的目标 P99 < 5s；通知发送失败不回滚交易事实。

### 16.5 可观测与审计

- `NFR-OBS-001` correlation ID 贯穿 message → agent → tool → plan → order → review。
- `NFR-OBS-002` 100% 模拟交易具备完整 Evidence Chain。
- `NFR-OBS-003` 每个 Agent 输出可定位到 Agent/Prompt/Model/Tool 版本。
- `NFR-OBS-004` 外部 tracing 是副本，本地审计是长期真值。
- `NFR-OBS-005` 告警含 runbook 和用户影响范围。
- `NFR-OBS-006` 100% 自主 Trade Episode 可追溯到 Mandate、Strategy、Agent、Prompt、Model、Tool、Risk Policy、数据和规则版本。
- `NFR-OBS-007` Decision Journal 永久区分 decision-time evidence 与 post-hoc analysis，禁止复盘覆盖原始决策记录。

### 16.6 成本

- `NFR-COST-001` 每个 Agent task 有 token、时间和 Tool budget。
- `NFR-COST-002` 确定性筛选先过滤低价值候选。
- `NFR-COST-003` 相同 snapshot/问题允许安全缓存只读分析。
- `NFR-COST-004` 用户可查询日/周 Agent 与研究成本。

### 16.7 自治运行与人在环上监督

- `NFR-AUT-001` `AUTONOMOUS_SIMULATION` 的常规 scan-to-trade-to-review 路径不得依赖用户在线、点击卡片或回复消息。
- `NFR-AUT-002` 每个调度任务具有 stable schedule ID、lease、幂等键、deadline、retry policy 和 missed-run policy；任务不能无声丢失。
- `NFR-AUT-003` 对同一市场事件、Mandate、Strategy 和 snapshot 的重复触发最多产生一次业务效果。
- `NFR-AUT-004` Mandate/Policy/Risk 任一不确定时 fail closed；已有仓位进入 protect-only，不以“等用户回复”替代安全状态。
- `NFR-AUT-005` Agent、Prompt、Model、Tool、Strategy 或 Risk Policy 版本漂移时，相关 Mandate 必须暂停或经过重新验证。
- `NFR-AUT-006` 用户的暂停新仓、撤销 Mandate、减仓、全部退出和 Kill Switch 命令优先于 Agent 新计划并满足幂等要求。
- `NFR-AUT-007` 系统需支持夜盘跨日和至少一个完整交易日无人值守运行，且零孤儿仓位、零无保护暴露、零静默漏扫。
- `NFR-AUT-008` 教学说明只能引用当时可用数据；事后信息必须显式标记，不得制造“Agent 当时已经知道”的叙事。
- `NFR-AUT-009` 新仓、减仓、退出、保护触发、未成交风险和降级事件的通知送达率可度量；CRITICAL 不受静默时段影响。
- `NFR-AUT-010` 自主运行不允许在线修改自己的权限、Mandate、默认 Memory、Prompt、模型或风险规则。

## 17. 成功指标与 Guardrail

### 17.1 自主运行与产品价值

- Mandate 有效时段内机会扫描覆盖率、漏扫率和重复触发率。
- 自主 `scan → decision → risk → execute/protect → review` 端到端完成率。
- 用户离线时安全完成的 `NO_TRADE` 或 Trade Episode 比例。
- 候选到 TRADE、NO_TRADE、DEFER、Policy Reject、Risk Reject 和 Fill 的分布。
- 用户逐笔人工干预率、强制接管率及其原因；目标是减少日常基本操作，而不是压低必要安全干预。
- 重要通知送达率、无效打扰率、聚合率和用户展开证据链的比例。
- 每周有效自主研究/交易 Episode 和用户主动查询的价值反馈。

### 17.2 Agent 质量

- 输出 schema 有效率 ≥ 99%。
- 数字真值工具引用率 100%。
- Tool 权限越权成功率 0%。
- Critical scenario 正确拒绝率 100%。
- Critic 高严重度缺陷召回率目标 ≥ 95%。
- 用户纠正率、相同错误复发率和 confidence calibration。
- Agent 在不同 Regime、策略和风险状态下的 TRADE/NO_TRADE 校准与过程一致性。

### 17.3 交易系统正确性

- 重复业务副作用 0。
- 无保护 OPEN Position 0。
- 风险扩大成功次数 0。
- 账本不平衡 0。
- Trade Episode 完整率 100%。
- 未说明 FillModel 的模拟报告 0。
- Mandate 越权成功次数 0。
- 孤儿仓位、孤儿订单和静默漏扫 0。

### 17.4 研究质量

- BacktestRun 可复现率 100%。
- 未经 OOS/Forward 验证的 Strategy 晋升次数 0。
- 未经验证的 Reflection 进入默认 Memory 次数 0。
- 失败实验登记率 100%。
- Return concentration/parameter/cost warnings 覆盖率 100%。

### 17.5 用户学习与可解释性

- Decision Journal 完整率 100%。
- 自主交易说明对 Thesis、Invalidation、AuthorizationBasis、最大风险和后续观察项的覆盖率 100%。
- decision-time evidence 与 post-hoc analysis 混淆次数 0。
- 用户能从复盘正确复述入场理由、失效条件与退出原因的抽样通过率。
- 同类错误复发率、用户标记“解释不足”的比例和教学日报有效反馈。

### 17.6 非收益 Guardrail

系统成功不能只按 PnL 定义。即使模拟盈利，以下任一发生仍视为产品失败：

- 绕过风险；
- 数据泄漏；
- 审计断链；
- 未经验证自动学习；
- 把不可成交状态伪造成成交；
- 超出 Mandate、在用户未知情下扩大风险，或绕过 `USER_PAUSE`/`HALTED` 所要求的人类恢复门禁；
- 用户无法理解关键风险。

## 18. 关键验收场景

### AC-001 数据陈旧

Given 行情超过执行 freshness 阈值，When 自治 Agent 提交 OPEN Plan，Then Plan 进入 STALE 或 Policy/Risk REJECT，不创建 Order。

### AC-002 重复消息

Given 飞书重复推送同一 message/action，When worker 重试，Then 只存在一个业务任务和零或一个获批 Order 链。

### AC-003 止损放宽

Given Long Position 的权威 ProtectionMandate/StopPolicy 止损为 95，When Agent 请求放宽为 92，Then T4-SAFE 校验拒绝，原 StopPolicy 保持 ACTIVE，并记录越界原因。

### AC-004 LLM 离线

Given 已有 Position 且所有 Agent worker 停止，When 市场触发硬止损，Then Protection 仍创建 Order 并持续处理成交。

### AC-005 涨跌停无对手盘

Given Stop trigger 成立但没有可成交对手价，When matcher 处理，Then Order 保持未完全成交并升级剩余风险，不按 stop price 伪造 Fill。

### AC-006 部分成交

Given Order quantity 5、可用流动性 2，When 撮合，Then 产生 Fill 2、Position 2、Order PARTIALLY_FILLED，剩余 3 继续管理。

### AC-007 规则历史

Given 历史日期规则与当前规则不同，When 回测该日期，Then 使用历史 ContractRuleVersion，当前规则变化不改写结果。

### AC-008 Critic 拒绝

Given Strategy edge 低于成本，When Critic REJECT，Then 原 Plan 不能进入 Authorization/Risk Gate；必须生成新版本或终止。

### AC-009 Risk Analyst 与 Engine 冲突

Given Risk Analyst 判断可接受但 Risk Engine REJECT，Then 系统拒绝交易并向用户解释硬规则。

### AC-010 未验证 Reflection

Given 单笔亏损产生 Reflection，When 下一次 Memory Search，Then 默认结果不把它作为 Validated Lesson。

### AC-011 Lesson 过期

Given Lesson 超过 expiry，When Strategy Agent 检索，Then 它被标记过期并不获得默认高权重。

### AC-012 回测数据缺失

Given 12 品种研究缺失 2 个，When Run 完成，Then 状态为 INCOMPLETE/PENDING_UNIVERSE，不能进入晋升。

### AC-013 旧授权或可选审批

Given Mandate 已过期/撤销，或可选逐 Plan Approval 所绑定 Plan 已过期/被编辑，When 系统尝试提交交易，Then 请求被拒绝并展示当前 AuthorizationBasis。

### AC-014 进程崩溃

Given Order 已 ACCEPTED 但事件消费前崩溃，When 系统恢复，Then 不重复创建 Order，继续处理原状态。

### AC-015 Continuous Series 误用

Given Strategy 使用连续合约研究，When 提交交易，Then 系统要求解析为可交易 Instrument，否则拒绝。

### AC-016 用户离线的自治闭环

Given ACTIVE Mandate、ACTIVE AUTONOMOUS_SIMULATION Binding、qualified bindings 与健康门禁共同使 EffectiveAutonomy 成立，且用户与飞书均离线，When 交易时段出现合格机会，Then 系统独立完成扫描、计划、反证、Policy/Risk Gate、模拟成交、保护、退出和复盘；通知进入 outbox 等待补发。

### AC-017 Mandate 外品种

Given Mandate 仅允许铁矿石，When Agent 为螺纹钢提交 OPEN Plan，Then Policy Gate REJECT，零 Order，并记录稳定 reason code。

### AC-018 Mandate 过期

Given Mandate 在夜盘中到期且已有 Position，When 下一扫描和保护事件到达，Then 禁止新 OPEN，已有 Position 继续保护并按退出策略管理。

### AC-019 Mandate 撤销与暂停新仓

Given 用户撤销 Mandate 或点击暂停自治，When Agent 已有未提交 OPEN Plan，Then 暂停命令在同一事务联动 Mandate SUSPENDED 与 Mode PAUSED，使 Basis/Receipt 失效并释放 reservation，Plan 不能创建 Order；重复控制命令不产生重复副作用。

### AC-020 运行版本漂移

Given ACTIVE Mandate 和 AUTONOMOUS_SIMULATION Mode 绑定 Agent/Prompt/Model/Strategy 版本集合，When 其中任一运行版本被替换或隔离，Then Mode 自动 PAUSED、旧 Basis/Receipt 失效，Mandate 作为业务委托不被静默改写，且不继续开仓。

### AC-021 重复 bar-close

Given 同一 instrument、bar、Strategy、Mandate 的 close event 被投递两次，When 自治循环执行，Then 最多产生一个 OpportunityDecision 和一条 Order 业务链。

### AC-022 自主 Thesis 失效退出

Given 已有 Position 的 Thesis Invalidation 成立，When Autonomous Quant PM 生成 `RiskReductionRequest(REDUCE/CLOSE)`，Then 无论 Mandate/Mode 是否仍有效，确定性 T4-SAFE Validator 在证明目标暴露单调下降、不反向且不放宽保护后生成幂等 `ProtectiveRiskAction`，无需用户回复即可减仓或退出并通知原因；无法证明时必须拒绝，或把可能新增风险的变化作为新 TradePlan 重走完整授权链。

### AC-023 用户降低风险优先

Given Agent 正准备 OPEN 且用户同时发送“全部退出”，When 命令竞争，Then 降低风险命令优先，新 OPEN 被拒绝，已有仓位进入退出流程。

### AC-024 决策教学日志

Given 任一自主 Fill，When 用户查询“为什么这样做”，Then 系统展示当时 snapshot、证据/反证、Thesis、Invalidation、Mandate、RiskDecision、执行路径和后续观察，且事后信息单独标记。

### AC-025 LLM 离线降级

Given LLM worker 离线，When 新自由判断候选和已有 Position 的硬止损同时发生，Then 新候选 DEFER/暂停，硬止损、撮合、结算和对账继续。

### AC-026 漏扫与补跑

Given 一次 bar-close 扫描因进程重启错过，When Scheduler 恢复，Then 按 missed-run policy 补跑或显式 SKIPPED；补跑不使用当时尚不可见数据且不重复下单。

### AC-027 自主风险扩大请求

Given Mandate/Risk ceiling 为 1% 且 Agent 请求 1.5% 或放宽止损，When Policy/Risk Gate 校验，Then 100% REJECT，Agent 不得通过逐 Plan Approval 绕过。

### AC-028 通知失败不阻塞保护

Given 飞书通知持续失败，When Position 触发保护和退出，Then 交易保护正常执行，通知可靠重试并产生告警，但不回滚 Fill。

### AC-029 未验证学习隔离

Given 自主亏损交易产生 Reflection，When 下一自治周期检索 Memory，Then Reflection 只作为未验证证据，不自动改变已激活 Strategy/Prompt/Agent 行为。

### AC-030 Shadow 到 Autonomous 晋升

Given Agent 仅处于 SHADOW 且生成合格 TradePlan，When 计划通过所有分析，Then 不创建 Order；只有完成治理资格与 Activation、具有 ACTIVE Mandate 且健康门禁通过，使 EffectiveAutonomy 成立后，才能产生模拟交易副作用。

### AC-031 并发计划合计超限

Given 两个并发 TradePlan 单独计算均在风险上限内、但合计会突破组合预算，When 两者竞争 RiskBudgetReservation，Then 原子预留至多允许安全组合继续，另一个计划必须缩小、等待或拒绝，且不得签发可建立超额风险的 AutonomyGateReceipt。

## 19. 版本规划

### V0 — Greenfield Foundation

用户价值：一个完全独立、可构建、可测试、可观测的新项目地基。

包含：

- 新仓库、工程规范、CI、secrets 和环境分层。
- 九个业务上下文和 Agent Orchestration supporting context。
- PostgreSQL、Schema、inbox/outbox、审计、checkpoint 与 Registry 骨架。
- Parquet/对象存储 manifest、synthetic golden datasets。
- 全部 Agent artifact、Tool、权限、Simulation Autonomy Mandate、AuthorizationBasis、AutonomyGateReceipt、RiskBudgetReservation、Decision Journal 和 NotificationPolicy 契约。
- donor 资产资格评估；只有在新契约下重新验收的资产才可移植。

不包含：启用 LLM Agent、模拟开仓、飞书正式接入。

Exit：旧仓库和旧数据库完全离线时，新项目仍可独立启动和通过 V0 验收。

### V1 — 自主研究与机会雷达

用户价值：系统无需等待用户提问即可按计划扫描市场、形成可证伪假设、运行可复现研究并输出带独立反证的机会雷达。

包含：

- Instrument、Contract Rule、Trading Calendar 与 point-in-time Market Snapshot。
- Main、Market Regime、Research、Critic、Experiment Manager 研究子图。
- L0/L1、walk-forward、stress、counterfactual 基础。
- Hypothesis、Experiment、Evidence、OpportunityCandidate 研究记录与研究报告；StrategyCandidate 等 V3 Strategy Agent 启用后才创建。
- Trading Calendar Scheduler、确定性候选过滤、Decision Journal 基础和 `OBSERVE` 模式。
- 开盘前范围、机会摘要、NO_TRADE/DEFER 原因和研究教学报告。

不包含：TradePlan 提交、Order/Fill、账户模拟或 Validated Lesson 自动使用。

Exit：连续覆盖约定扫描时段，完成可重放的 OBSERVE scan → hypothesis → experiment → critique → candidate/NO_TRADE 链路，不产生 TradePlan 或交易副作用。

阶段性产品门槛：`V1-010` 完成后先执行 [`MVP-R-001`](./MVP-RESEARCH-VALIDATION.md)，用真实模型、授权真实 PIT 数据、Replay/基线/Critic ablation 和真实用户 shadow 使用验证研究价值。`V1-010` 只是试验起跑线；只有取得用户/产品治理 `GO` 才可声明 MVP-R，并继续 Experiment Manager 和 Opportunity Radar 的工业化建设。

### V2 — Deterministic Simulation Core

用户价值：不依赖 LLM 也能用固定 Strategy Spec 完成安全、可重放的期货模拟。

包含：

- TradePlan schema/validator、position sizing、原子 RiskBudgetReservation、最小 AutonomyGate/Receipt 与 Risk Constitution。
- 固定 Strategy Spec 的 `SHADOW` 模式，以及显式 `MANUAL_TEST + PlanApproval` 模拟验收路径；二者都不代表 Agent 自治已启用。
- Order/Fill/Position/Accounting、PnL、margin、settlement。
- L1/L2 matcher、部分成交、规则有效期与六层保护/Kill Switch；P2 在 V2 仅使用 Strategy Spec 的显式确定性失效谓词。
- 一个冻结 StrategySpec fixture 可在 L2 事件语义下重跑 V1 基础 walk-forward、stress 与 counterfactual，证明验证引擎能力；V3 Strategy Agent 创建 StrategyCandidate 后复用同一引擎形成最小 qualification 证据，规模化调度仍在 V4。
- 固定 Strategy Spec + 测试/回放/CLI 显式触发、审计、幂等、故障恢复与对账。

不包含：完整 Autonomous Quant PM 多 Agent 自由判断；只验证确定性策略自动模拟和安全内核。

Exit：同一数据、规则、策略、时钟和随机种子产生一致交易事实；LLM 离线时保护与结算正常。

### V3 — 受约束自治多 Agent 模拟交易

用户价值：Autonomous Quant PM 在用户预先授予的 Mandate 内持续筛选、模拟交易、盯盘、退出和复盘；用户主要观察学习、接收重要通知和例外干预。

包含：

- Strategy、Portfolio、Risk Analyst、Execution Advisor、Post-trade Reviewer。
- typed handoff、并行 fan-out、冲突、预算、超时、取消与 durable checkpoint。
- Simulation Autonomy Mandate、AuthorizationBasis、原子 RiskBudgetReservation、AutonomyGate/Receipt、自治模式晋升和 staleness 复核。
- 在 V2 确定性 P2 基线上增加可降级的 Agent Thesis Watch 语义复核。
- 飞书 Gateway、自主决策说明卡、重要事件通知、学习日报和用户风险控制。
- activate mandate → autonomous scan → plan/critique → policy/risk → simulate → watch/exit → notify → review 黄金旅程。

Exit：用户离线一个完整交易日时，系统可安全完成自治循环；同一 EvidenceBundle 可重放全部 Agent runs，每项主张可归因，Policy/Risk Engine 仍是唯一交易许可。

### V4 — Governed Learning & Scaled Research

用户价值：系统从交易与实验中形成经过验证、会过期、可回滚的经验和策略版本。

包含：

- Memory Curator 与 Governance Agent。
- Reflection → LessonCandidate → validation → ValidatedLesson。
- L2 规模化验证、parameter sweep、attribution、研究 sandbox 与 compute scheduler；L3 Tick 延后到 V5。
- Agent/Prompt/Tool/Model/Strategy Registry、离线 eval、晋升与回滚。
- Agent 自主行为的长期校准、错误复发和 Mandate 适配评测；任何新版本仍需人类治理启用。

Exit：至少一个 episode → review → experiment → governed activation 全链路通过；未验证记忆无法进入默认检索。

### V5 — High-Fidelity & Offline Enhancement

用户价值：在数据和运营成熟时提高执行、流动性、组合和模型研究的真实性。

包含：

- L3 Tick/Quote replay 与成交路径重建。
- L4 Order Book、L5 paper connector、队列/冲击与部分成交。
- TWAP/VWAP/iceberg、分批进出、换月、多账户与高级相关性/资本配置。
- HA/DR、正式容量阈值与 30 天稳定运行。
- 多账户/多 Mandate 自治调度、通知聚合和更高保真无人值守演练。
- Governance Agent 的 Model/Policy Steward 工作模式。
- 可选 SFT、offline preference learning 或低维执行研究，必须单独批准。

不包含：自动启用模型、在线 RL 主路径或绕过 Risk Constitution；真实交易仍不在范围。

详细任务见 [ROADMAP.md](./ROADMAP.md)。

## 20. 版本发布门槛

每个版本必须同时满足：

- 功能验收场景通过。
- 回归、故障、恢复、安全和权限测试通过。
- 新项目 Schema 演进（如有）演练通过。
- Agent/Prompt/Tool eval 达到门槛。
- 运行 SLO、成本和告警已建立。
- 回滚版本可用。
- 用户明确批准启用范围。

代码完成、合并或部署成功中的任何一个都不单独等于产品版本已启用。

## 21. 极端与边界场景清单

- 夜盘跨日、节前提前结束、临时休市。
- 主力切换日与连续合约跳点。
- 保证金、手续费、涨跌停临时调整。
- 最后交易日/交割月错误开仓。
- 行情源冲突、延迟、回退、缺口和乱序。
- bid/ask 缺失、单边市、涨跌停无对手盘。
- 部分成交、重复成交回报、撤单与成交竞态。
- 多 Agent 结论冲突、专家超时、模型切换。
- Mandate 到期/撤销、自治暂停、运行版本漂移、重复市场事件和可选旧 Approval。
- 用户暂停新仓/全部退出与 Agent OPEN Plan 的并发竞态。
- 调度漏扫、跨夜补跑、重启后的过期候选和 notification outbox 堆积。
- 交易中 Agent/数据库/Gateway/网络任一故障。
- 同策略多合约、同品种反向候选、组合相关性突变。
- 止盈后剩余仓位、加仓后风险、隔夜结算后保护。
- 回测样本太少、年份集中、参数脆弱、数据泄漏。
- Reflection 与已有 Lesson 冲突、Lesson 过期。
- Prompt injection 试图改变权限或风险规则。

## 22. 风险与缓解

| 风险 | 后果 | 缓解 |
|---|---|---|
| 多 Agent 复杂度过早 | 成本、延迟和冲突 | 完整定义、按版本启用、最小充分委托 |
| LLM 数值幻觉 | 错误风险和计划 | 所有数字由工具提供、schema 与引用校验 |
| 模拟过度乐观 | 错误策略晋升 | 分级真实性、保守 FillModel、warnings |
| 数据/规则历史缺失 | 制度偏差 | point-in-time rule/data、INCOMPLETE 状态 |
| 自我强化记忆 | 错误 Lesson 污染 | Memory Curator、实验门禁、过期与反例 |
| 研究多重检验 | 虚假发现 | 预注册、holdout、失败保留、预算 |
| 权限漂移 | Agent 越权 | Tool allowlist、服务身份、硬门禁 |
| 自治循环过度交易 | 成本、噪声与回撤放大 | Mandate、cooldown、频率/损失预算、Critic、Policy/Risk Gate |
| 无人值守故障 | 漏扫、孤儿仓位或静默风险 | 调度 lease、protect-only 恢复、告警、日常对账与演练 |
| 通知过载 | 用户忽略真正风险 | 事件分级、聚合、静默策略与 CRITICAL 直达 |
| 事后叙事污染教学 | 用户学到错误因果 | Decision Journal 固化 decision-time evidence，复盘仅追加 |
| 新项目范围膨胀 | 长期无可用版本 | V0-V5 明确用户旅程和 exit criteria |
| 旧代码直接搬运 | 带入耦合与错误语义 | 只移植经审计资产，新契约/新测试 |

## 23. 已确定默认值

- 全新独立项目，不在 `futures_workflow` 内建设。
- 旧项目只作为需求、算法、adapter、测试和历史经验来源。
- Autonomous Quant PM / Main Agent 是完整 Trade Episode 的单一责任主体和用户入口，专业 Agent 按需启动。
- 最终目标保留完整 Agent 组织；早期版本只裁剪运行角色。
- 默认目标运行模式是 `AUTONOMOUS_SIMULATION`，用户处于 human-on-the-loop，不承担日常筛选、逐笔许可和盯盘操作。
- V3 起，EffectiveAutonomy 范围内的 Agent TradePlan 默认无需逐 Plan Approval；Approval 只作为可选例外路径。
- 用户批准的是 Mandate、AutonomyMode 升级、Strategy/Agent/Prompt/Model/Tool/Risk Policy 的启用范围与版本；Mandate 扩大、延长、`USER_PAUSE` 或 `HALTED` 恢复仍需人类动作，`HEALTH_DEGRADED` 只能在显式 policy 和健康稳定窗口内恢复 Mode。
- 新能力先经过 `OBSERVE → SHADOW → AUTONOMOUS_SIMULATION` 受控启用，不能由 Agent 自行晋升。
- 重要交易/风险事件即时通知，普通扫描和 `NO_TRADE` 聚合到摘要；通知不是交易许可。
- Agent 对新建/增加/反向暴露只能提交 TradePlan；对已有暴露降险只能提交 RiskReductionRequest；两者都不能提交 Order。
- Risk Engine、Execution、Accounting 和 Protection 均为确定性系统。
- PostgreSQL 作为业务状态与 Agent checkpoint 主库；市场历史数据使用列式文件/对象存储。
- V2 先做 L1/L2 matcher，L3/L4 需要相应数据和验证门槛才能启用。
- 真实交易不在本 PRD。

## 24. 待产品确认但不阻塞设计的问题

- 首批正式支持的交易所、品种和数据授权范围。
- 新项目最终仓库名和部署位置。
- V1 是否只运行本机，还是直接部署常驻服务器。
- 飞书允许接入的用户/群范围，以及谁能激活、暂停、扩大、撤销 Mandate 和解除 Kill Switch。
- V2 模拟账户初始资金、绝对风险和日损失阈值。
- 宏观/新闻数据源与保留政策。
- V1/V4 Research Run 的日/月成本预算。
- 是否需要从旧数据库导入历史交易作为只读 Episode；这不是启动依赖。
- 首批自治扫描的品种池、bar 周期、日/夜盘时段与 missed-run 补跑策略。
- `SHADOW` 最短观察期、晋升门槛、回退门槛和谁批准进入 `AUTONOMOUS_SIMULATION`。
- Mandate 的单笔、每日、组合、保证金、并发仓位、交易次数、连续亏损和最大回撤默认值。
- Agent 只在已激活 Strategy Spec 内选择机会，还是允许在 Mandate 中授权一次性自由裁量 TradePlan。
- 同品种/同 Thesis 的 cooldown、用户手动退出后的再入场规则和反向信号处理。
- 哪些事件即时通知，哪些进入盘中聚合、日终或周/月教学报告。
- 版本漂移使 Mode PAUSED、旧 Basis/Receipt 失效后的最短稳定窗口、已批准 fallback 顺序与重新评测 SLA。
- 用户学习效果的评测方法，以及教学日志应保留到何种粒度和时长。
- 恢复 AUTONOMOUS 模式、扩大 Mandate 和解除 Kill Switch 的单人/双人确认规则。

在用户未另行指定前，技术方案使用保守默认值，并保持这些参数可配置、可版本化。

## 25. Definition of Done

一个产品需求只有同时满足以下条件才可标为完成：

1. 代码、Schema、文档和权限边界实现一致。
2. 正常、边界、失败和重复执行测试通过。
3. 有可点击/可查询的验收证据。
4. Agent 能力有离线 eval，确定性能力有不变量/重放测试。
5. 监控、告警、runbook 和回滚存在。
6. 不改变真实交易权限。
7. `ROADMAP.md` 更新负责人、证据、版本和启用状态。
8. `HANDOFF.md` 更新下一任务和已知风险。
9. 涉及自治交易的能力已分别通过 OBSERVE、SHADOW 和受限 AUTONOMOUS_SIMULATION 验收，且 Mandate、Policy/Risk Gate、用户暂停/撤销和 Decision Journal 证据齐全。
