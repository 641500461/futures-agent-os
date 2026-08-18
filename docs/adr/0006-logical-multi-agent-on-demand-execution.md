---
status: accepted
---

# 定义逻辑多 Agent，按需执行专门角色

## Context

目标系统需要研究、交易计划、反证审查、复盘、实验和后续组合分析等不同认知职责。把所有职责塞入一个 Main Agent 会导致上下文、权限和评测混杂；让七个以上 LLM Agent 常驻并自由辩论，又会增加延迟、成本、冲突与不可预测的协调循环。逻辑职责是否独立，与是否部署成常驻进程或使用不同模型是两个问题。

## Decision

目标架构显式定义十二个逻辑 Agent：Autonomous Quant PM / Main、Market Regime、Research、Strategy、Portfolio、Risk Analyst、Execution Advisor、Pre-trade Critic、Experiment Manager、Post-trade Reviewer、Memory Curator，以及 Governance Agent；后者在 V5 扩展 Model/Policy Steward 工作模式。除 Main 外均作为短生命周期、按用户请求、时间表或市场/账户/系统事件启动的专门子图，并按 V1–V5 的产品门槛启用。Main 对机会与 Trade Episode 的认知决策负责；非 LLM 的确定性 Workflow Orchestrator 负责触发、状态推进、重试、恢复和终止。每个 Autonomy Cycle 必须具有明确 Trigger、适用边界、预算与终止状态：OBSERVE/SHADOW 研究周期使用版本化 ScanPolicy/UniversePolicy，只有交易自治周期才要求 EffectiveAutonomy 与 Mandate Scope。每个角色拥有独立职责/非职责、触发条件、输入输出 schema、AgentState、工具 allowlist、预算、超时、失败策略、评测集和版本。角色通过结构化 `AgentTaskEnvelope` 与不可变 artifact 引用协作，由 Workflow Orchestrator 推进、Main 进行决策协调，不进行无界 peer-to-peer 聊天。Market State Builder、Regime/Signal 模型、Portfolio Optimizer、Risk Constitution、Execution Planner、Matching、Accounting、Settlement 和 Protection 保持确定性组件，不包装成 LLM Agent。

## Consequences

- 目标角色在 PRD 和技术设计中从第一天可见，同时首版可以让多个角色共用 worker、模型和运行时，按证据再拆部署。
- Critic 与 Reviewer 必须分开：前者交易前寻找反证，后者交易后评价过程与结果；即使复用模型也使用不同契约和权限。
- 每次委派都有明确成本、截止时间、最大迭代和终止状态；未解决的高严重度异议必须导向 `NO_TRADE` 或 `DEFER`。
- 时间表与事件触发可以在无用户消息时发起工作，但不会扩大 Simulation Autonomy Mandate 或变成无界自循环。
- 需要额外维护多套 prompt、schema、状态、评测和观测，但可以独立演进权限与质量，并避免 Main Agent 自问自答形成确认偏差。

## Considered Options

- 单一万能 Main Agent：拒绝作为长期目标，因为无法清晰隔离职责、权限和评测。
- 多个常驻 Agent 自由辩论：拒绝，因为成本和行为难以约束。
- 每个逻辑角色立即拆成独立服务：暂不采用；先按需执行并允许同进程部署，达到隔离或吞吐门槛后再拆分。
