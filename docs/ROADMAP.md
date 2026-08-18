# 绿地版本路线图与可勾选任务

版本：`2.1-proposed`  
最后更新：2026-08-18  
任务状态唯一来源：本文件

## 状态约定

- `[ ]`：新项目任务尚未满足验收条件。
- `[x]`：Acceptance 已满足，且任务后附有可复核 Evidence。
- 进行中：保留 `[ ]`，追加 `Status: IN_PROGRESS`、负责人、工作区和开始日期。
- 阻塞：保留 `[ ]`，追加 `Status: BLOCKED`、日期、阻塞原因和所需决定。
- 代码完成、合并、数据发布、策略晋升和运行启用必须分别记录。
- donor 资产的可用性记录在 `LEGACY-ASSET-REUSE.md`，不在本文件中作为完成项打勾。

当前状态：`V0-001`、`V0-002` 已完成；下一任务为 `V0-003`。

## 全局依赖原则

- 新系统必须独立于 `/Users/qiu/futures_workflow` 启动、测试、部署和恢复。
- Agent 对新增/增加/反向暴露只提交版本化 TradePlan，不直接提交 Order；该路径必须具有有效 `AuthorizationBasis`（有效 Simulation Autonomy Mandate 或可选 PlanApproval）、RiskBudgetReservation、AutonomyGateReceipt 与 RiskDecision。对已有暴露的 REDUCE/CLOSE/收紧保护只提交 RiskReductionRequest，并经 T4-SAFE RiskReductionValidation 后成为 ProtectiveRiskAction。
- Agent checkpoint 不是业务真值；业务状态、审计事件和 outbox 使用新项目数据库。
- 低粒度数据不得宣称高粒度成交真实性。
- Reflection 未经验证不得成为默认检索的 Lesson。

## V0：绿地项目地基

目标：建立独立仓库、完整领域边界、Agent/Tool 契约、数据底座、安全边界和工程质量门槛，不承接任何旧运行状态。

- [x] `V0-001` 创建独立新仓库，确定项目名称、Python/runtime 版本、许可证、目录结构和本地开发入口。
  Acceptance: 不修改或依赖旧仓库即可完成 clean checkout、安装、启动和测试；记录新仓库 commit。  
  Evidence: 2026-08-18 在 `/Users/qiu/Documents/Codex/2026-08-18/new-chat/work/futures-agent-os` 创建独立 Git 仓库；项目名 `futures-agent-os`，包名 `futures_agent_os`，Python 3.14，uv 锁定依赖，MIT License；基线 commit `8d00a4331581026175270ae3bfa1414d438dc5df`。从该 commit 执行 clean clone 后，`uv sync --locked` 成功，`uv run pytest` 为 `2 passed`，`uv run futures-agent-os health` 返回 `status=ok` 与 `legacy_runtime_dependency=false`；契约测试通过 AST 检查禁止 `futures_workflow` 运行时 import。
- [x] `V0-002` 确认绿地 ADR 集：项目独立性、确定性内核真值、Agent 以 TradePlan/RiskReductionRequest 表达交易意图但不直接提交 Order、Simulation Autonomy Mandate、模块化 monorepo、PostgreSQL、审计模型和队列策略。
  Acceptance: 所有难逆转决策有状态、理由、替代项和后果；不使用旧 ADR 编号暗示继承。  
  Evidence: 2026-08-18 按领域建模 ADR 门槛复核并接受 `docs/adr/0001` 至 `0007`，索引见 `docs/adr/README.md`；commit `dad8c5802abba56fa285a53ee6b7e436daf093fd`。7 项决策均使用新项目连续编号，状态为 `accepted`，并包含 Context、Decision、Consequences 与 Considered Options；`tests/contract/test_adr_baseline.py` 自动检查编号连续、状态合法、V0 基线已接受及权衡/后果章节，`uv run pytest` 为 `5 passed`。
- [ ] `V0-003` 建立领域上下文与统一语言：Reference/Market Data、Market Intelligence、Research & Experiment、Decision、Portfolio & Risk、Execution Simulation、Accounting & Settlement、Learning & Review、Governance & Registry。  
  Acceptance: 每个聚合只有一个权威上下文；Agent Orchestration 明确为 supporting context；Simulation Autonomy Mandate、AutonomyModeBinding 与 AuthorizationBasis 由 Decision 拥有，DecisionJournal 追加投影由 Learning & Review 拥有。  
  Evidence: 待补。
- [ ] `V0-004` 定义跨上下文 ID、Money/Price/Quantity、时区、`trading_date`、版本和错误码规范。  
  Acceptance: Decimal/定点、Asia/Shanghai、UTC 记录时间、schema version 和 reason code 均有契约测试。  
  Evidence: 待补。
- [ ] `V0-005` 定义完整 Agent Catalog、`AgentTaskEnvelope`、结构化交接 artifact 和有界协作协议。  
  Acceptance: 12 个目标逻辑角色均写明职责、非职责、用户/时间表/市场/账户/系统事件触发、输入、输出、工具、权限、预算、失败策略、指标和启用版本。  
  Evidence: 待补。
- [ ] `V0-006` 建立 Tool Registry 与权限模型：细分只读、研究请求、提案、Mandate Scope 内自治模拟变更、可选逐计划批准、晋升和启用权限，并支持账户/策略/品种/环境作用域。  
  Acceptance: 默认拒绝；未授权 Agent、节点或作用域无法调用工具；权限矩阵有自动化测试。  
  Evidence: 待补。
- [ ] `V0-007` 建立 PostgreSQL 初始 schema、正式 schema migration、数据库角色、inbox/outbox、任务租约、Mandate/可选批准、调度、监督通知和 durable checkpoint 基础。  
  Acceptance: 空库可重复建库、升级、降级演练；业务表与 Agent checkpoint schema 隔离；不包含旧表导入。  
  Evidence: 待补。
- [ ] `V0-008` 建立行情/研究数据分层：raw immutable、normalized point-in-time、feature snapshot、dataset manifest 和 artifact store。  
  Acceptance: 每份数据集具有来源、许可、schema、时间覆盖、`as_of`、摄取时间、hash、质量和修订信息。  
  Evidence: 待补。
- [ ] `V0-009` 建立身份、密钥、日志脱敏、Prompt Injection、代码执行沙箱、网络出口和供应链威胁模型。  
  Acceptance: Git/日志无凭据；不可信文本不能改变权限；研究执行有 CPU/内存/时间/文件/网络上限。  
  Evidence: 待补。
- [ ] `V0-010` 建立统一 correlation/causation、命令幂等、追加审计、metrics/logs/traces 和最小告警框架。  
  Acceptance: 从请求到工具调用和领域事件可关联；重复命令最多产生一个业务效果。  
  Evidence: 待补。
- [ ] `V0-011` 建立 CI、依赖锁、类型/静态检查、单元/属性/契约测试、schema 兼容检查和敏感信息扫描。  
  Acceptance: 新仓库主分支保护启用；本地与 CI 使用相同锁定环境。  
  Evidence: 待补。
- [ ] `V0-012` 建立新项目 synthetic/golden 数据集与边界案例库；首批验收宇宙明确选择 AG、CU、RB、JM、I、MA、SA、M、P、SR、SC、JD。  
  Acceptance: 品种选择有产品理由；夜盘、规则变更、涨跌停、跳空、无流动性、乱序和缺失数据均有样本。  
  Evidence: 待补。
- [ ] `V0-013` 按 `LEGACY-ASSET-REUSE.md` 对 donor 候选逐项做资格评估，不迁移运行状态。  
  Acceptance: 每个采用项有 provenance、新接口、隔离性、安全扫描和新项目测试；拒绝项有理由。  
  Evidence: 待补。
- [ ] `V0-014` 定义 Simulation Autonomy Mandate、Mandate Scope、AutonomyModeBinding、AuthorizationBasis/PlanApproval、两阶段 AutonomyGate、AutonomyGateReceipt、RiskBudgetReservation、DecisionJournal、TradeEpisode 投影与监督控制契约。  
  Acceptance: Mandate 必须版本化并绑定模拟账户、品种/策略/时段范围、有效期、风险引用、通知和升级规则；Mandate 九态 `DRAFT/VALIDATED/APPROVED/ACTIVE/SUSPENDED/EXPIRED/REVOKED/HALTED/RECOVERING` 完整，除 DRAFT 外所有非终态受 expiry 约束，APPROVED/ACTIVE/SUSPENDED/HALTED/RECOVERING 可 revoke；Mode 四态、Binding ACTIVE/EXPIRED/SUPERSEDED、EffectiveAutonomy、composite pause 与 V1 可空 account/mandate 语义明确；PlanApproval 五态和“GRANTED 原子消费为唯一 Basis”契约完整；Receipt 绑定 Plan/AuthorizationBasis/源授权 hash、`execution_origin`、快照、运行版本、预算预留、有效期、单次 nonce 及 AUTONOMOUS_AGENT 必需的 Mode id/version/hash；Reservation 归属 Portfolio & Risk；DecisionJournal 区分 DECISION_TIME/POST_HOC 且可重建，TradeEpisode 明确归 Learning & Review 且只投影源事件；并发与竞态契约测试通过；任何对象都不能放宽 Risk Constitution。  
  Evidence: 待补。

Exit：新仓库可独立启动和恢复；领域、Agent、Tool、数据、安全、存储和测试基础全部有证据；旧项目不可用不会影响新项目。

## V1：自主研究与机会雷达

目标：Main、Market Regime、Research、Critic 和基础 Experiment Manager 除了回答用户问题，还能按 Trading Calendar、行情收盘、数据更新或市场事件主动扫描授权研究宇宙，形成可复现的机会候选与研究结果；本版本不产生交易副作用。

- [ ] `V1-001` 实现 Instrument/Variety/Exchange/Continuous Series 注册和解析，严格区分研究连续序列与可交易合约。  
  Depends: V0。  
  Acceptance: 首批验收宇宙的别名、交易所和合约解析契约通过；Continuous Series 不能进入交易计划。  
  Evidence: 待补。
- [ ] `V1-002` 实现带有效期的 `ContractRuleVersion` 和来源追踪：乘数、tick、保证金、手续费、涨跌停、交易时段、最后交易日、限仓、开平今。  
  Acceptance: 指定 Instrument 与 trading date 只能命中一个适用版本；缺失或冲突时返回稳定失败码。  
  Evidence: 待补。
- [ ] `V1-003` 实现交易日历与 `trading_date` 服务，覆盖夜盘、节假日、主力切换、临近交割和规则临时调整。  
  Acceptance: 上期所、大商所、郑商所和中金所代表性夜盘/节假日边界测试通过。  
  Evidence: 待补。
- [ ] `V1-004` 实现 point-in-time `MarketSnapshot`、数据新鲜度/完整性/冲突检测和稳定 reason code。  
  Acceptance: 缺失、陈旧、乱序或未来泄漏数据不会被静默采用。  
  Evidence: 待补。
- [ ] `V1-005` 实现版本化 Feature Engine 和确定性 Regime/Signal Model Service。  
  Acceptance: 特征输入、窗口、版本和快照可重现；模型输出不被当作交易许可。  
  Evidence: 待补。
- [ ] `V1-006` 实现 Market Regime Agent，输出带正反证据和不确定性的 `MarketStateAssessment`。  
  Acceptance: 输出通过 schema，引用不可变快照和特征版本；不能生成 TradePlan、RiskDecision 或 Order。  
  Evidence: 待补。
- [ ] `V1-007` 实现 Research Agent，输出可证伪 `Hypothesis`、未知项、证据缺口和 `ExperimentRequest`。  
  Acceptance: Research Agent 没有交易、审批、晋升或账本权限。  
  Evidence: 待补。
- [ ] `V1-008` 实现只读 Autonomous Quant PM / Main Agent、确定性持久 Workflow Orchestrator、`AutonomyCycle/DecisionEpisode` 与 DecisionJournal 基础投影，支持用户、时间表与市场/数据事件触发，以及 typed DelegationPlan、fan-out/fan-in、取消、超时和预算。  
  Acceptance: 同一 cycle/episode 可跨进程恢复；重复触发最多产生一个有效周期；Main 不拥有 durable 调度状态；DecisionJournal 可从源事件重建，不覆盖当时事实。  
  Evidence: 待补。
- [ ] `V1-009` 实现研究版 Pre-trade Critic，检查反证、数据泄漏、成本覆盖、样本适用性和结论强度。  
  Acceptance: 高严重度未解决项强制 `DEFER`，迭代次数有上限。  
  Evidence: 待补。
- [ ] `V1-010` 实现研究工具：market/historical/feature/contract 查询、memory/experiment search、L0 Signal Test、L1 Bar Backtest，以及单策略基础 walk-forward、成本/滑点 stress 与 counterfactual。  
  Acceptance: 工具结果包含版本、`as_of`、source refs、warnings、artifact refs 和失败码；基础验证固定样本切分、成本假设、停止规则与可复现配置，供后续 L2 资格证据复用。  
  Evidence: 待补。
- [ ] `V1-011` 实现基础 Experiment Manager 与异步 Research Job 状态机：预注册实验、排队、运行、部分完成、失败、取消、超时和恢复。  
  Acceptance: 每个任务有算力/时间预算；结果可回流原对话；Experiment Manager 不能交易或晋升策略。  
  Evidence: 待补。
- [ ] `V1-012` 建立 Agent 研究评测集：工具选择、引用正确性、数字 grounding、反证覆盖、`NO_TRADE/DEFER` 和相同证据重放。  
  Acceptance: 评测集、评分规则和版本已冻结；每次模型/Prompt/Toolset 变更都会生成可比较报告。  
  Evidence: 待补。
- [ ] `V1-013` 实现 `OBSERVE` Opportunity Radar：按 ScanPolicy/UniversePolicy 或事件扫描品种宇宙，产出 `OpportunityScan` 与 `OpportunityCandidate`，并形成重要研究摘要。  
  Acceptance: 每次扫描绑定宇宙、时点、数据/特征版本和预算；OBSERVE 的 account/mandate 可空；候选有支持与反对证据、时间尺度、去重/冷却信息和 `NO_OPPORTUNITY`结果；漏跑可补跑，且不能创建 TradePlan、Order 或账务副作用。  
  Evidence: 待补。

Exit：从用户问题或时间表/市场事件到 OpportunityCandidate、Hypothesis、实验结果、Critique 和证据化答复可完整重放；没有任何 Order、Fill、Position 或账本副作用。

## V2：确定性模拟交易内核

目标：不依赖 LLM、飞书或 Agent 在线，系统也能安全地校验计划、裁决风险、模拟成交、记账、结算、保护和恢复。

- [ ] `V2-001` 定义 `TradePlan`、`ProtectionIntent`、`RiskReductionRequest`、`RiskReductionValidation`、`ProtectiveRiskAction`、`AuthorizationBasis`、`SimulationAutonomyMandate`、可选 `PlanApproval`、`RiskDecision`、`ProtectionMandate`、`ExecutionPlan`、`StopPolicy`、`Order`、`Fill`、`PositionLot`、`LedgerEntry` 和 `Settlement` 契约。  
  Depends: V0；复用 V1 市场/规则快照。  
  Acceptance: 所有对象具有 schema/version/ID/时间/来源；跨对象引用和非法状态有契约测试。  
  Evidence: 待补。
- [ ] `V2-002` 实现仓位计算、风险预算、原子 `RiskBudgetReservation` 和 `immutable_risk_ceiling`；风险修订只能单调收紧。  
  Acceptance: 多空、部分止盈、加仓、并发修订和跳空场景的最坏损失属性测试通过；两个并发计划合计超限时至多允许安全组合预留，且预留可幂等缩小、消费、释放、超时与对账。  
  Evidence: 待补。
- [ ] `V2-003` 实现 Risk Constitution：数据质量、单笔风险、保证金、品种/方向/组合集中度、日回撤、临近交割和 Kill Switch。  
  Acceptance: 风险不可算时 fail closed；每条检查返回规则版本和稳定 code。  
  Evidence: 待补。
- [ ] `V2-004` 实现订单状态机和幂等应用命令，覆盖接受、拒绝、工作、部分成交、成交、撤单、过期和 cancel/fill race。  
  Acceptance: 非法状态转换被拒绝；任何 Fill 总量不超过 Order；重复命令不重复产生业务效果。  
  Evidence: 待补。
- [ ] `V2-005` 实现 L1 Bar/Quote 和 L2 Event FillModel：市价、限价、止损触发、滑点、无对手价、涨跌停和部分成交。  
  Acceptance: 触发不等于成交；同 Bar 止盈止损歧义采用声明的保守规则。  
  Evidence: 待补。
- [ ] `V2-006` 实现账户、持仓批次和统一账本：开仓、平仓、平今、手续费、保证金、冻结、逐日盯市、PnL 和每日结算。  
  Acceptance: 资金与账本不变量通过；Position 只能由 Fill/Settlement 改变。  
  Evidence: 待补。
- [ ] `V2-007` 实现 Position Protection：初始止损、Strategy Spec 显式且可重放的确定性 Thesis 失效谓词、追踪止损、时间止损、组合止损、Kill Switch，以及 RiskReductionRequest/ProtectionTrigger 到 RiskReductionValidation/ProtectiveRiskAction 的 T4-SAFE 链。  
  Acceptance: 六层保护在无 Agent/模型/交互服务时仍运行；V2 P2 不依赖自由文本或语义推理；每个降险请求绑定 Position expected version 和幂等键，REJECTED/STALE 零 Action，VALIDATED Action 只能单调降险且可跨崩溃恢复；无保护 OPEN Position 为最高级故障。  
  Evidence: 待补。
- [ ] `V2-008` 实现 `submit_trade_plan` 最小两阶段安全链：计划硬校验 → Authorization Preflight/AuthorizationBasis → 仓位计算 → 原子 RiskBudgetReservation → Final Receipt Gate → 风险裁决/ProtectionMandate → ExecutionPlan/StopPolicy → Order。  
  Acceptance: MANUAL_TEST 的 PlanApproval/AuthorizationBasis 缺失、失效、过期或范围不匹配时 fail closed；每次增加风险都同时要求有效 Receipt 与 RiskDecision；Receipt 绑定 Plan/AuthorizationBasis/源授权 hash、execution_origin、快照/预留、过期且只消费一次；等待授权时不占 reservation；API 不向调用方暴露 matcher、数据库或账本写句柄。  
  Evidence: 待补。
- [ ] `V2-009` 实现回测与模拟共享的规则、订单、FillModel、账本和结算接口，并支持冻结 StrategySpec fixture 的 L2 事件驱动验证。  
  Acceptance: 相同事件和 FillModel 产生相同订单/账本结果；V1 的基础 walk-forward/stress/counterfactual 可在 L2 语义下重跑以证明引擎能力；V3 Strategy Agent 创建 StrategyCandidate 后可复用同一引擎形成资格证据。  
  Evidence: 待补。
- [ ] `V2-010` 实现追加式审计、当前态投影、历史重放、日终对账和更正事件。  
  Acceptance: 任一模拟交易可重建完整链路，重放结果与当前投影和账本校验一致。  
  Evidence: 待补。
- [ ] `V2-011` 建立故障注入：进程崩溃、重复命令、乱序/断档行情、数据库重启、时钟偏移、规则缺失和无流动性。  
  Acceptance: 已提交命令 RPO=0，恢复后无重复业务副作用。  
  Evidence: 待补。
- [ ] `V2-012` 实现授权操作者的短期 `MANUAL_TEST PlanApproval` request/grant/reject/expire/consume 状态机，并提供人工 CLI/API 验收、应急模拟入口与确定性回放报告。  
  Acceptance: GRANTED PlanApproval 仅能在原子创建唯一 PLAN_APPROVAL AuthorizationBasis 时转为 CONSUMED，记录 consumer_basis_id/consumed_at；数据库唯一约束、并发与重放测试证明同一 Approval 不能生成第二个 Basis/成功交易。用户可在无 LLM 环境以 `execution_origin=MANUAL_TEST`、被该 Basis 消费一次的 PlanApproval 完成一笔 SHADOW 校验后的计划、成交、保护退出和结算；本入口标记为测试/应急 fallback，不需伪装 AUTONOMOUS_SIMULATION，也不是 V3 日常操作模式。  
  Evidence: 待补。

Exit：确定性黄金链路可在固定数据集上完全重放；任何新增风险都具有有效 RiskBudgetReservation、AutonomyGateReceipt 与 RiskDecision；无重复交易、无无保护持仓、无不可解释账本差异。

## V3：受约束自治多 Agent 模拟交易

目标：用户激活 Simulation Autonomy Mandate，并为通过资格的版本组合激活 AUTONOMOUS_SIMULATION Mode、健康门禁通过后，系统可在 EffectiveAutonomy 范围内按时间表与市场/账户/系统事件自主找机会、研究、质疑、形成 TradePlan、调用 V2 内核模拟执行、持续盯盘与复盘；用户主要接收重要信息、学习决策证据并在异常时介入。

- [ ] `V3-001` 实现飞书长连接 Gateway、用户/群映射、快速去重入箱、异步通知和监督控制回调防重放。  
  Depends: V1、V2。  
  Acceptance: 入站事件在目标时限内去重入箱；重复消息/回调不会重复创建任务或交易效果；飞书定位为通知、解释、例外介入与紧急控制台，常规周期无需用户回调。  
  Evidence: 待补。
- [ ] `V3-002` 实现由确定性 Workflow Orchestrator 推进、Autonomous Quant PM / Main 负责决策的 durable 自治图：用户/时间表/市场/账户/系统事件触发 → 快照固化 → 机会扫描 → 委派与质疑 → TradePlan → Authorization Preflight/AuthorizationBasis → sizing/RiskBudgetReservation → Final Receipt Gate → Risk/Execution → 盯盘 → 通知/复盘。  
  Acceptance: 图可在任一 checkpoint 或例外 interrupt 后跨重启恢复；恢复前重新校验计划、AuthorizationBasis、AutonomyGateReceipt、RiskDecision 和快照有效性；范围内常规周期不等待用户输入。  
  Evidence: 待补。
- [ ] `V3-003` 实现 Strategy Agent，输出 `StrategyCandidate` 或 `TradePlanDraft`，不输出 Order。  
  Acceptance: 输出包含 Thesis、Invalidation、证据、目标风险和退出意图；无订单或账本写权限。  
  Evidence: 待补。
- [ ] `V3-004` 实现 Portfolio Agent，基于账户、相关性、策略预算和现有暴露提出 `TargetExposure/PortfolioProposal`。  
  Acceptance: 最终手数仍由确定性 Position Sizing 和 Risk Constitution 产生。  
  Evidence: 待补。
- [ ] `V3-005` 实现 Risk Analyst Agent，输出非权威 `RiskAssessment`、情景和反面证据。  
  Acceptance: Risk Analyst 不能产生或覆盖 `RiskDecision`。  
  Evidence: 待补。
- [ ] `V3-006` 实现 Execution Advisor，调用成本/成交仿真比较 V2 已注册的 Market、Limit、Stop 执行意图；分批、TWAP/VWAP/Iceberg 等高级算法延至 V5。  
  Acceptance: 输出仅为 `ExecutionRecommendation`，且只能选择当前已实现并已激活的执行算法；Order 仍由确定性 Execution Planner 创建。  
  Evidence: 待补。
- [ ] `V3-007` 实现独立 Pre-trade Critic，审查 Thesis、反证、泄漏、成本、Regime、风险收益和历史失效。  
  Acceptance: Critic 与 Post-trade Reviewer 是不同角色、状态和 schema。  
  Evidence: 待补。
- [ ] `V3-008` 实现结构化并行协作：Regime/Portfolio、Risk/Critic/Execution 可并行，由确定性 Workflow Orchestrator 完成 fan-out/fan-in，Autonomous Quant PM 负责冲突呈现与决策综合。  
  Acceptance: Agent 不自由互聊；冲突显式展示；循环、token、时间、工具和算力预算有硬上限。  
  Evidence: 待补。
- [ ] `V3-009` 实现 Simulation Autonomy Mandate 与 AutonomyModeBinding 生命周期、EffectiveAutonomy 合成门禁和 composite pause/resume，并扩展 V2 PlanApproval 为 Mandate 允许的 Agent 例外路径。  
  Acceptance: Mandate 的账户、品种/策略/时段、风险引用、有效期、通知和升级范围可精确校验；除 DRAFT 外所有非终态支持 expiry，APPROVED/ACTIVE/SUSPENDED/HALTED/RECOVERING 可 revoke；Mode Binding expiry/supersession 立即令 EffectiveAutonomy 为 false、使 Basis/Receipt stale 并释放 reservation；USER_PAUSE 仅人类恢复，HEALTH_DEGRADED/版本隔离只暂停 Mode/Health 而不改写 Mandate，HALTED 必须人工恢复门禁；用户 pause 事务性联动 Mandate SUSPENDED + Mode PAUSED + Basis/Receipt 失效 + reservation 释放；Agent 例外 PlanApproval 仍要求 AUTONOMOUS_SIMULATION Mode。  
  Evidence: 待补。
- [ ] `V3-010` 在 V2 最小门禁上扩展完整两阶段自治 AutonomyGate、Preflight ESCALATE/PROTECT_ONLY、Final Gate、单用途 `AutonomyGateReceipt` 与精细工具权限。  
  Acceptance: Preflight 返回 AUTHORIZED/ESCALATE/REJECT/PROTECT_ONLY，只有获得 Basis 后才 sizing/reserve；GRANTED PlanApproval 原子消费为唯一 Basis，不能重复签发；Final Gate 只返回 PERMIT/REJECT/PROTECT_ONLY 并签发 Receipt；最终 `submit_trade_plan` 才同事务检查 Receipt 和随后签发的当前 RiskDecision。Agent 越权、跨 scope、伪造/重复 Approval/Receipt、旧 Plan/Basis/source/Mode hash、过期快照和失效 RiskDecision 全部被拒绝并审计；等待 PlanApproval 不占 reservation。  
  Evidence: 待补。
- [ ] `V3-011` 实现飞书监督卡片：Mandate 状态、机会与反面证据、TradePlan、RiskDecision、成交/持仓/保护、保证金、最坏损失、复盘和暂停/恢复/撤销/Kill Switch。  
  Acceptance: 所有数字来自工具引用，不由模型自由生成；通知统一按 INFO/TRADE/ACTION_REQUIRED/RISK/CRITICAL 分级、去重且可追溯；TRADE 只解释关键交易生命周期，常规信息不要求用户操作。  
  Evidence: 待补。
- [ ] `V3-012` 实现基础 Post-trade Reviewer，输出独立的 `TradeReview` 与 `Reflection`，区分过程质量、结果质量和执行质量。  
  Acceptance: Learning & Review 从 Decision/Execution/Accounting 源事件构建并关闭可重建 TradeEpisode 后才触发 Reviewer；Reviewer 不能发布 Lesson，也不能由原 Strategy Agent 自评替代。  
  Evidence: 待补。
- [ ] `V3-013` 建立多 Agent 自治评测与 V3 最小人工治理 Registry：机会覆盖/精度、`NO_TRADE` 纪律、不必要交易率、Mandate 遵循、通知精度、委派、handoff、冲突、预算耗尽、超时、越权、Prompt Injection 和模型降级。  
  Acceptance: 每个已启用 Strategy/Agent/Prompt/Model/Toolset 版本都有独立基准集和发布门槛，并经人工分离的 qualification + Activation 后才能绑定 AUTONOMOUS_SIMULATION；关键越权、Mandate 遵循、数字引用和不必要交易指标达到硬门槛。  
  Evidence: 待补。
- [ ] `V3-014` 实现有界自治机会到交易周期：扫描、候选排名、专家论证、TradePlan、AuthorizationBasis、RiskBudgetReservation、AutonomyGateReceipt、风险裁决、模拟执行和交易后触发。  
  Acceptance: 在固定数据与 EffectiveAutonomy 下，无任何用户回调也能完成一次 `NO_TRADE` 周期与一次完整模拟交易周期；全链追加进 DecisionJournal 并可重建；超范围、证据不足或风险不可算时必须 `DEFER` 或拒绝。  
  Evidence: 待补。
- [ ] `V3-015` 实现 Market/Order/Position/Portfolio/System 持续盯盘，并在 V2 确定性 P2 基线上增加可降级的 Agent Thesis Watch，包括 lease、幂等触发、漏跑补跑、冷却、背压、降级和重要事件通知。  
  Acceptance: Agent Thesis Watch 只能提交 Decision 所有的 RiskReductionRequest，Execution 独立执行 T4-SAFE Validation 并拥有 ProtectiveRiskAction；LLM、飞书或研究 worker 不可用时，确定性 Position Protection、Risk Watch 和 Kill Switch 仍运行；重复/补跑不重复交易；TRADE/ACTION_REQUIRED/RISK/CRITICAL 事件在目标时限内送达或升级。  
  Evidence: 待补。

Exit：EffectiveAutonomy 成立时，系统可在无用户日常操作下跨重启完成“自主扫描 → 多 Agent 研究/质疑 → TradePlan → 两阶段授权 → Risk Constitution → 模拟执行 → 持续保护 → 重要通知 → 复盘”；用户可查看全部证据、暂停/撤销 Mandate、暂停 Mode 或触发 Kill Switch，且业务真值不在 AgentState。

## V4：实验、复盘与验证式学习

目标：形成“发现未知 → 提出假设 → 分级验证 → 前向实验 → 交易复盘 → 验证 Lesson → 策略晋升”的证据闭环。

- [ ] `V4-001` 定义统一 `ExperimentPlan`、`BacktestRun`、Dataset/Rule/Cost/Engine/Model/Prompt refs 和 artifact manifest。  
  Depends: V1–V3。  
  Acceptance: 固定所有 refs 与随机种子可复现实验；任一输入变化都会生成新 run/digest。  
  Evidence: 待补。
- [ ] `V4-002` 将 V1/V2 已可运行的 L0/L1/L2 验证漏斗扩展为标准化批量研究调度；外部回测工具仅通过版本化 connector 接入。  
  Acceptance: V3 单候选证据保持兼容；每级输入、语义、用途、限制和晋级门槛可审计；外部摘要不能绕过本地契约。  
  Evidence: 待补。
- [ ] `V4-003` 将 V1 基础 walk-forward、成本/滑点 stress、counterfactual 扩展为规模化验证，并新增 Monte Carlo、scenario replay、parameter sweep 和 strategy compare。  
  Acceptance: V1/V2 基础证据可按兼容契约重放；每类验证产生独立 artifact、warnings 和可复现配置；不完整运行不能进入晋升证据。  
  Evidence: 待补。
- [ ] `V4-004` 实现年度/月度/品种/Regime/多空/成本归因、回撤事件、最差交易、参数稳健性和自动 warnings。  
  Acceptance: 归因合计与总收益/成本在容差内一致；集中、样本不足和参数不稳定自动告警。  
  Evidence: 待补。
- [ ] `V4-005` 扩展 Experiment Manager，支持规模化实验计划、优先级、预算、取消、父子运行、证据汇总和失败恢复。  
  Acceptance: Experiment Manager 不能交易、晋升策略或修改风险规则。  
  Evidence: 待补。
- [ ] `V4-006` 扩展 Post-trade Reviewer，分别评价 Process Quality、Outcome Quality、执行质量、后续市场路径和可验证原因假设。  
  Acceptance: 每项评价引用 episode、行情、订单、账本和规则事实；原因解释默认仅为 Reflection。  
  Evidence: 待补。
- [ ] `V4-007` 实现 Memory Curator，将 Reflection 变为有验证计划的 `LessonCandidate`，不自行发布 Lesson。  
  Acceptance: 缺证据需求、适用范围、置信度或过期策略的候选不能提交治理。  
  Evidence: 待补。
- [ ] `V4-008` 建立 `Reflection → LessonCandidate → LessonValidation/ValidationEvidence → ValidatedLesson` 派生流水线及各对象独立生命周期，处理冲突、衰减、撤销和再验证。  
  Acceptance: 未验证内容与决策检索隔离；LessonCandidate 与 ValidatedLesson 不共享状态写者；ValidatedLesson 的验证生命周期与 Governance Activation 分离；每次 Lesson 使用可追踪其影响。  
  Evidence: 待补。
- [ ] `V4-009` 扩展 V3 基础 Strategy Registry 与晋升门禁：历史初筛、稳健性、样本外、前向模拟、人工批准和独立 Activation，并明确更高阶自治模拟资格。  
  Acceptance: 跳过任一强制证据阶段的晋升请求被拒绝；只有获得 autonomous-simulation qualification 且在目标范围激活的 Strategy Version 才可被 Mandate 引用；批准、注册和启用是独立审计事件，不是逐笔 PlanApproval。  
  Evidence: 待补。
- [ ] `V4-010` 扩展 V3 基础 Agent/Prompt/Model/Toolset Registry：候选、规模化离线评测、批准、启用、回滚、废弃和兼容矩阵。  
  Acceptance: 任一运行可解析完整版本组合；不兼容、未激活或未取得 autonomous-simulation qualification 的版本不能进入 Mandate 下的自治运行。  
  Evidence: 待补。
- [ ] `V4-011` 接入宏观、新闻、库存、期限结构、拥挤度和历史相似案例的 point-in-time Evidence；明确授权与不可信内容边界。  
  Acceptance: 每条证据有来源、许可、发布时间/有效时点和质量；非结构化内容不能改变系统指令或权限。  
  Evidence: 待补。
- [ ] `V4-012` 建立衰减/漂移触发器：策略 OOS 衰减、Regime 变化、规则变化、Lesson 过期自动创建 Research/Experiment Request。  
  Acceptance: 触发器幂等、可解释、可暂停；只创建研究任务，不自动修改策略或交易。  
  Evidence: 待补。
- [ ] `V4-013` 实现 Governance Agent，只能检查证据完整性并提出 `ChangeProposal/ActivationProposal`。  
  Acceptance: Governance Agent 无晋升、启用、回滚或风险政策修改权限；最终决定属于治理服务和用户。  
  Evidence: 待补。

Exit：至少一个 Hypothesis 完成历史、稳健性、样本外和前向验证，并产生可审计的 Review、Lesson 或 StrategyCandidate；任何晋升均无绕过。

## V5：高保真、组合扩展与离线增强

目标：在数据允许时提高成交与组合真实性，建设受控离线模型增强和长期运营能力；仍不接真实交易。

- [ ] `V5-001` 实现 L3 Quote/Trade Tick 顺序回放、成交序列和可校准滑点模型。  
  Acceptance: 相同 tick 序列和配置产生相同 Fill；乱序、缺口和时钟异常有明确处理结果。  
  Evidence: 待补。
- [ ] `V5-002` 实现 L4（Level-2/Level-3 order book）回放、队列位置、流动性消耗、部分成交和市场冲击。  
  Acceptance: 队列/深度守恒、成交不超可用流动性，并用带真值样本验证队列与部分成交。  
  Evidence: 待补。
- [ ] `V5-003` 实现 L5 Paper Trading adapter，包括 TqSim/其他外部模拟源，并显式标注模型限制。  
  Acceptance: 外部订单/成交与本地状态可双向对账；未知或不支持行为不会伪装为成功。  
  Evidence: 待补。
- [ ] `V5-004` 实现 TWAP、VWAP、Iceberg、分批建仓/退出和执行算法对比。  
  Acceptance: Agent 只选择或建议已注册算法；确定性系统执行。  
  Evidence: 待补。
- [ ] `V5-005` 实现多账户、多策略、相关性簇、板块/方向/期限暴露、跨期、换月成本和资本分配。  
  Acceptance: 子账户/策略暴露可汇总到组合；净额、相关性、换月和集中度边界有属性测试。  
  Evidence: 待补。
- [ ] `V5-006` 建立高保真校准：Backtest/Replay 与 Paper 的成交、滑点、PnL 和容量偏差评估。  
  Acceptance: 每个 FillModel 有校准数据、误差区间、适用范围和禁止外推范围。  
  Evidence: 待补。
- [ ] `V5-007` 扩展 Governance Agent 的 Model/Policy Steward 工作模式，只能基于评测提出 Prompt/Model/Strategy `ChangeProposal`。  
  Acceptance: Steward 无合并、晋升、启用或风险规则修改权限。  
  Evidence: 待补。
- [ ] `V5-008` 建立 shadow/canary/offline evaluation 流水线，并评估受控监督微调；模型变更与 Activation 分离。  
  Acceptance: 候选模型不能自动进入活动流量；评测、人工批准、canary 和回滚证据完整。  
  Evidence: 待补。
- [ ] `V5-009` 将 Offline RL 限定为低维、可重复模块的独立研究项，例如执行、组合配置或仓位调整；不得替代高层 Agent。  
  Acceptance: 未经单独研究评审和治理批准，不进入默认运行路径。  
  Evidence: 待补。
- [ ] `V5-010` 完成 SLO、容量、背压、限流、熔断、备份、恢复、权限审计、灾难演练和 runbook。  
  Acceptance: 关键 SLO 有测量与告警；RTO/RPO、备份恢复和主要故障 runbook 均完成演练。  
  Evidence: 待补。
- [ ] `V5-011` 完成 30 天稳定性运行和故障演练。  
  Acceptance: 无未解释重复交易、无无保护持仓、无审计链断点；全部事故可恢复并有报告。  
  Evidence: 待补。
- [ ] `V5-012` 形成模拟系统上线评审包：能力边界、真实性级别、剩余风险、数据授权、运行成本、回滚和 Kill Switch 演练。  
  Acceptance: 产品、架构、风险、数据和运营评审结论已记录；未解决阻断项不得启用。  
  Evidence: 待补。

Exit：高保真与 Paper 偏差被量化；组合风险、离线增强和运营控制可审计；系统仍明确标识为研究与模拟产品。

## 明确不在本路线图内

- 真实 CTP/经纪商下单、真实资金授权和自动实盘。
- Agent、模型或外部内容直接修改 Risk Constitution、账本、历史审计或已发布策略。
- 未经新项目验收而把 donor 代码、数据或测试标记为完成能力。
- 低粒度数据伪装成 Tick/订单簿成交真实性。
- 以收益、胜率、单次盈利或 LLM 复盘文本替代系统正确性和验证门禁。
