---
status: proposed
---

# Agent 以 TradePlan 或 RiskReductionRequest 表达意图，不直接提交 Order

## Context

直接向 Agent 暴露 `place_order` 或 broker/matcher 句柄虽然接口简单，但会让重复工具调用、畸形参数或越权推理绕过假设完整性、Authorization Basis、仓位计算、风险裁决和幂等控制。交易意图与可执行订单属于不同领域语义：前者表达为什么交易及愿意承担什么风险，后者必须服从当前授权、账户、规则与市场约束。

## Decision

建立、增加或反向暴露时，Agent 只能生成并提交版本化 `TradePlan`，其中包含 Thesis、可证伪 Invalidation、快照引用、目标风险暴露、入场意图、ProtectionIntent、最大损失、退出计划、有效期和 Agent provenance；TradePlan 不拥有 Execution 上下文的 StopPolicy。确定性 AutonomyGate 采用两阶段协议：Authorization Preflight 先验证范围、运行模式和版本，并为范围匹配的 Simulation Autonomy Mandate 创建 AuthorizationBasis；可选例外必须先取得只对该 Plan Version 有效的 PlanApproval，GRANTED Approval 原子转为 CONSUMED 并创建唯一新 Basis，等待期间不得预留风险。只有有效 Basis 成立后，系统才执行仓位计算与原子 RiskBudgetReservation；Final Receipt Gate 随后校验 Basis、源授权、适用 Mode、快照、版本和 reservation，仅 PERMIT 签发单用途 AutonomyGateReceipt。Risk Constitution 再生成 RiskDecision/ProtectionMandate，Execution Plan 落地 StopPolicy，最后才创建 Order 并进入 Matching。

对于已有暴露的 REDUCE、CLOSE 或收紧保护，Agent 只能提交绑定 Position expected version 的 `RiskReductionRequest`。Execution 的确定性 T4-SAFE RiskReductionValidation 证明风险单调下降、不反向且不放宽保护后，才创建幂等 `ProtectiveRiskAction`；无法证明时拒绝，或将可能新增风险的变化改为新 TradePlan 重走完整链。Agent 在任何路径都不获得直接创建或修改 Order、Fill、Position、LedgerEntry 的工具。

## Consequences

- 模型权限停留在可审计、受有效委托或可选批准约束的业务意图层，无法用工具参数绕过交易宪法。
- 相同计划可在当前快照失效时被明确标记为 `STALE`，而不是沿用旧价格静默执行。
- 系统需要额外维护 TradePlan schema、AuthorizationBasis、Mandate/PlanApproval 版本、RiskBudgetReservation、AutonomyGateReceipt、有效期和从计划到订单的转换链。
- Simulation Autonomy Mandate 可对后续多份 Plan 提供长期但有界、可撤销的授权；它不会授权范围外订单，也不会放宽 Risk Constitution。PlanApproval 仍只对一个具体 Plan Version 有效。

## Considered Options

- 向 Agent 暴露通用下单工具：拒绝，因为授权面过宽且难以保证重复调用安全。
- 让 Agent 直接输出目标 Order JSON：拒绝，因为会把仓位、风险和执行约束泄漏到模型职责中。
