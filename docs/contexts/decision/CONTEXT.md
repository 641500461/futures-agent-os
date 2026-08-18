# Decision

本上下文把用户目标或自治扫描触发、市场解释和研究证据形成明确的 No Trade、Defer、Trade Plan 或针对已有暴露的 Risk Reduction Request，并管理一份 Trade Plan 进入模拟风险/执行链的授权依据与自治运行级别。它拥有机会候选、Trade Plan、Risk Reduction Request、Simulation Autonomy Mandate、Autonomy Mode Binding、Authorization Basis 和 Autonomy Gate Receipt，但不分配风险预算、不产生订单，也不修改账户事实。

## Language

### Decision framing

**Opportunity Scan**:
对明确市场宇宙、时点和时间尺度进行的一次交易机会筛选，允许以没有合格机会为正常结果。
_Avoid_: Market Scan 任务、Watchlist、Backtest Run

**Opportunity Candidate**:
Opportunity Scan 中值得进一步论证的 Instrument、策略方向与时间尺度组合，带支持、反对证据和未知项，尚不是交易意图。
_Avoid_: Signal、Trade Plan、保证会交易的推荐

**Decision Episode**:
从一个用户交易问题或 Opportunity Candidate 开始，到形成 Trade Plan、No Trade 或 Defer 为止的一次完整决策过程。
_Avoid_: 对话、Agent Run、Trade Episode

**Decision Context**:
某次 Decision Episode 可采用的市场、研究、组合和治理引用集合，全部带时点或版本。
_Avoid_: Prompt Context、Market Snapshot、聊天历史

**Trade Thesis**:
一笔候选交易为何应在当前环境成立的可证伪说明。
_Avoid_: 入场理由、Prediction、Validated Lesson

**Invalidation**:
足以否定 Trade Thesis 的可观察市场条件或事实变化。
_Avoid_: 止损价、最大亏损、低置信度

**Counter Evidence**:
与 Trade Thesis 冲突或显著降低其适用性的证据。
_Avoid_: 普通风险提示、负面新闻、Reviewer 意见

**Decision Confidence**:
对 Trade Thesis 在当前 Decision Context 下证据充分性的表达，不直接决定手数或风险预算。
_Avoid_: 胜率、仓位比例、模型置信度

### Decision outcomes

**Trade Plan**:
将 Trade Thesis、Invalidation、入场、目标暴露、保护与退出意图绑定到具体证据、版本和有效期的结构化交易意图。
_Avoid_: Order、Position、Signal

**Plan Version**:
一份 Trade Plan 在内容或依赖证据发生实质变化后形成的不可混用版本。
_Avoid_: 文档修订、Approval、Strategy Version

**Target Exposure**:
Trade Plan 希望达到的方向和风险暴露，由 Portfolio & Risk 决定是否允许以及允许多少。
_Avoid_: 买几手、Order Quantity、Position

**Entry Intent**:
Trade Plan 对何时、在何种市场条件下开始建立目标暴露的表达。
_Avoid_: Order Type、成交价、Signal

**Exit Intent**:
Trade Plan 对获利、失效、时间或其他条件下减少至目标暴露的表达。
_Avoid_: Stop Policy、Close Order、Protection Trigger

**Protection Intent**:
Trade Plan 对必须限制的最坏风险与保护方向的声明，需由风险与执行上下文转化为强制约束。
_Avoid_: Stop Policy、止损订单、风险许可

**Risk Reduction Request**:
针对一个既有 Position 与 expected version，提出 REDUCE、CLOSE 或收紧保护目标的不可变决策请求，绑定原因、证据、目标暴露和幂等键；它只表达降险意图，不证明风险单调下降，也不直接产生订单。
_Avoid_: Trade Plan、Protective Risk Action、Close Order

**No Trade**:
系统在证据充分的情况下，基于机会质量或适用性主动决定不提出 Trade Plan。
_Avoid_: Hold、Defer、Reject

**Defer**:
当前因缺证据、授权边界不清、必要的例外人工输入缺失或条件尚未满足而无法完成交易决定的结果。
_Avoid_: No Trade、Risk Reject、系统失败

### Authority and supervision

**Autonomy Mode Binding**:
针对一个研究/交易作用域与精确运行版本指定 `OBSERVE`、`SHADOW`、`AUTONOMOUS_SIMULATION` 或 `PAUSED` 的可审计绑定，并独立记录 `ACTIVE/EXPIRED/SUPERSEDED` Binding 生命周期。OBSERVE 的 Simulation Account 和 Mandate 引用可空；SHADOW 需要模拟账户但不可提交；只有 ACTIVE 的 AUTONOMOUS_SIMULATION Binding 才能参与 EffectiveAutonomy，且必须引用 Simulation Account 与 ACTIVE Mandate。expiry/supersession 会失效未消费授权但不停止已有保护。
_Avoid_: Mandate Status、System Health State、Agent Task State、Strategy Activation

**Simulation Autonomy Mandate**:
有权用户对指定 Simulation Account 授予系统的可暂停、可撤销、带版本与有效期的长期业务委托，允许 Agent 在 Mandate Scope 内自主发现机会、形成 Trade Plan 并请求模拟执行。
_Avoid_: Plan Approval、Risk Decision、Risk Budget、Tool Grant、Strategy Activation

**Mandate Scope**:
Simulation Autonomy Mandate 明确允许的 Simulation Account、品种、策略、时段、有效期、风险引用、通知和升级边界。
_Avoid_: Risk Budget、Activation Scope、Tool Grant

**Mandate Pause**:
保留 Simulation Autonomy Mandate 及其历史，但暂时不允许它授权新增模拟风险的用户决定。
_Avoid_: Revocation、Kill Switch、暂停 Agent Run

**Mandate Revocation**:
终止 Simulation Autonomy Mandate 对之后新增模拟风险的授权，同时保留既有决策与执行历史的用户决定。
_Avoid_: Mandate Pause、删除历史、Kill Switch

**Authorization Basis**:
一份具体 Plan Version 请求进入模拟风险/执行链的有效授权依据，必须绑定当前有效且范围匹配的 Simulation Autonomy Mandate，或一份可选 Plan Approval。
_Avoid_: Risk Decision、Tool Grant、用户身份、Agent Authority

**Autonomy Gate Receipt**:
确定性 Autonomy Gate 针对一个具体 Plan Version、Authorization Basis、源授权（Mandate 或 Plan Approval）、最新快照、运行版本与 Risk Budget Reservation 签发的短期、单用途许可凭证；它绑定 Plan/Basis/源授权 hash、`execution_origin`，且 `AUTONOMOUS_AGENT` 路径还必须绑定 AutonomyModeBinding ID/Version/hash，证明该请求通过最终自治边界校验。
_Avoid_: Authorization Basis、Plan Approval、Risk Decision、Tool Grant

**Plan Review**:
在用户选择逐计划模式或某计划命中人工升级条件时，有权用户对一个具体 Plan Version 作出批准、要求修改或拒绝的判断过程与结果。
_Avoid_: Plan Approval、Risk Decision、代码评审

**Plan Approval**:
在手动或例外路径下，有权用户在明确 Approval Scope 内对一个具体 Plan Version 作出的单次肯定许可；状态为 `REQUESTED/GRANTED/REJECTED/EXPIRED/CONSUMED`。GRANTED 只能在原子创建唯一 `basis_kind=PLAN_APPROVAL` Authorization Basis 时转为 CONSUMED，并记录 consumer basis 与 consumed_at；它不是自治运行的默认要求。
_Avoid_: Plan Review、Risk Decision、口头同意

**Approval Scope**:
Plan Approval 明确允许的账户、数量上限、有效时段和其他不可外推边界。
_Avoid_: Risk Budget、用户角色、默认授权

**Stale Plan**:
因有效期、价格、市场状态、规则或关键证据变化而不能继续使用原 Authorization Basis 的 Trade Plan。
_Avoid_: Rejected Plan、旧策略、低置信度计划
