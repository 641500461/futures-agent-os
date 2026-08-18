---
status: proposed
---

# 采用可撤销的 Simulation Autonomy Mandate，而非默认逐笔批准

## Context

产品目标是培养一个能自主寻找机会、模拟交易、持续盯盘和复盘的 Agent，用户通过它的证据、操作与结果学习，而不是担任逐笔操作员。默认要求用户批准每个模拟开仓会把机会选择与操作负担转回用户，也使无人值守时的定时扫描与盯盘无法形成完整周期；但无边界自治又会让 Agent 自行扩大品种、策略、账户或风险范围。

## Decision

在模拟交易中采用 **Simulation Autonomy Mandate（模拟交易自治委托）** 作为默认日常运行的预授权机制。该 Mandate 由 Decision 上下文拥有，必须由有权用户显式激活，并绑定 Simulation Account、品种、策略、时段、有效期、风险引用、通知和升级边界。用户可暂停、恢复或撤销 Mandate，任何范围扩大都必须形成新版本并由用户重新确认。

Mandate 与运行模式是两个独立门禁。只有 `EffectiveAutonomy = ACTIVE Mandate ∧ ACTIVE AUTONOMOUS_SIMULATION Binding ∧ qualified bindings ∧ health permits` 成立时，Agent 才可按时间表或市场、账户、系统事件自主扫描机会、形成 TradePlan 并请求模拟执行，无需用户逐笔批准；OBSERVE/SHADOW 或 EXPIRED/SUPERSEDED Binding 不产生交易副作用。

AutonomyGate 采用两阶段协议。第一阶段 Authorization Preflight 先验证范围、版本和运行模式：范围内创建 `basis_kind=MANDATE` 的 `AuthorizationBasis`；允许升级的范围外计划可在此请求可选 PlanApproval，GRANTED Approval 只能原子转为 CONSUMED 并为同一 Plan Version 创建唯一 `basis_kind=PLAN_APPROVAL` Basis，等待期间不预留风险。得到有效 Basis 后，确定性 Position Sizing 才计算候选数量与最坏风险，Portfolio & Risk 原子创建 `RiskBudgetReservation`；第二阶段 Final Receipt Gate 再校验 Basis、源授权、Mode、快照、版本与 reservation，仅在 `PERMIT` 时签发绑定 Plan、AuthorizationBasis、源 Mandate/PlanApproval、可选 Mode binding 的 hash、有效期与单次消费 nonce 的 `AutonomyGateReceipt`。随后仍须通过 Risk Constitution、Execution Planner 与幂等命令链。数据库唯一约束保证同一 Approval 不能生成第二个 Basis，PLAN_APPROVAL Basis 与 Receipt 最多成功消费一次；任一 Plan、授权、Mode、快照或版本变化都使旧 Basis/Receipt 失效，不得复用旧 reservation。

Mandate 不能放宽 Risk Constitution、不能使 Agent 直接创建 Order、也不替代 AutonomyMode、Strategy/Agent/Model/Prompt/Toolset 的治理资格和 Activation。用户“暂停自治”由应用服务事务性地把 Mandate 置为 `SUSPENDED(USER_PAUSE)`、Mode 置为 `PAUSED`，使未消费 Basis/Receipt 失效并释放 reservation；健康或版本问题只暂停 Mode/Health Gate，不静默改写业务 Mandate。Mandate 或 Mode 无效后不得新增风险，但已有持仓的确定性保护、减风险退出、结算和 Kill Switch 不得因等待用户而停止。系统主动向用户推送重要机会、计划依据、成交、持仓、风险、异常和复盘，并保留完整决策与操作证据供学习和追责。

## Consequences

- 用户从逐笔批准者变为目标与边界设定者、监督者和学习者，常规自治周期可在无人回调时完成。
- 系统必须维护 Mandate 与 AutonomyMode 版本、作用域、有效性、竞态、暂停/撤销、AuthorizationBasis、PlanApproval、RiskBudgetReservation、AutonomyGateReceipt、升级与通知的完整审计链。
- Agent 仍可能在允许范围内作出质量不佳的模拟决定，因此 `NO_TRADE` 纪律、不必要交易率、Mandate 遵循、通知精度和事后回放成为发布门槛。
- 任何模式从模拟扩展到真实资金都必须另立产品、风险、法务与架构决策；本 ADR 不授权或预留任何真实下单路径。

## Considered Options

- 默认逐笔 PlanApproval：拒绝作为主路径，因为会把筛选和日常操作转回用户，只保留为手动或例外模式。
- 无范围、无有效期的长期授权：拒绝，因为无法防止 Agent 自行扩大权限与无法审计的风险漂移。
- 只给推荐、从不自动模拟执行：拒绝作为目标态，因为无法验证 Agent 的真实操作、盯盘和完整交易周期。
