# Agent Orchestration

本支持上下文组织用户请求或时间表、市场、账户、系统事件触发的自治工作，协调专业 Agent、确定性工具和人工例外介入。它负责推进与恢复任务，但不拥有 Simulation Autonomy Mandate，所有业务事实仍由对应核心上下文拥有。

## Language

### Agent roles and work

**Agent Role**:
一组明确目标、输入、输出、工具权限和禁止事项所定义的 Agent 责任边界。
_Avoid_: 模型实例、Prompt、服务进程

**Main Agent**:
协调用户请求与自治周期、组织端到端工作并向用户报告重要信息的 Agent Role，不替代专业裁决或任何核心上下文真值。
_Avoid_: Trading System、万能 Agent、唯一模型

**Specialist Agent**:
只在特定专业边界内形成分析或候选对象、并把结果交回 Main Agent 或核心上下文的 Agent Role。
_Avoid_: 子进程、工具、独立真值服务

**Orchestration Session**:
围绕一个用户目标或有效 Simulation Autonomy Mandate 下的持续职责，组织 Agent Task、工具结果、例外决定和后续恢复的工作边界。
_Avoid_: Chat Thread、Decision Episode、Simulation Account

**Agent Task**:
分配给一个 Agent Role、具有明确输入和预期产物的有限工作单元。
_Avoid_: Development Task、Tool Call、用户消息

**Agent Run**:
某个 Agent Role 对一个 Agent Task 的单次执行经历，允许以新 Run 重试但不覆盖既有轨迹。
_Avoid_: Orchestration Session、Experiment Run、模型响应

**Delegation**:
Main Agent 把明确范围的 Agent Task 交给 Specialist Agent，并保留任务来源和期望产物的关系。
_Avoid_: Tool Call、权限转让、并行线程

**Agent Handoff**:
在 Agent Role 之间传递任务、已知事实、未决问题和授权边界的显式交接。
_Avoid_: Prompt 拼接、聊天摘要、Delegation

### Tools and authority

**Tool**:
核心上下文向 Agent 提供的结构化查询、提案或命令能力，具有明确业务语义和权限边界。
_Avoid_: 任意函数、Agent Role、直接数据库访问

**Tool Grant**:
允许某个 Agent Role 在指定范围内调用某类 Tool 的可撤销权限。
_Avoid_: 用户权限、API Key、默认信任

**Tool Call**:
Agent Run 在 Tool Grant 范围内发出的结构化能力请求。
_Avoid_: 自然语言建议、业务事实、函数日志

**Tool Result**:
核心上下文对 Tool Call 返回的结构化结果或业务引用，并保留其来源与适用边界。
_Avoid_: Agent 结论、聊天文本、未经验证真值

**Agent Proposal**:
Agent 向核心上下文提交的候选分析、计划或变更对象，必须由拥有该事实的上下文独立验证。
_Avoid_: Command Success、Approval、业务真值

**Agent Authority**:
Agent Role 在当前 Tool Grant、Orchestration Session 与适用的 ScanPolicy/UniversePolicy（只读研究周期）或 Mandate Scope + AutonomyMode（交易自治周期）交集内允许读取、提议或请求执行的边界；它不能创建或放宽 Mandate、Mode 或治理资格。
_Avoid_: 模型能力、用户信任、系统管理员权限

**Agent Budget**:
Orchestration Session 或 Agent Task 可消耗的时间、模型调用、工具调用和实验资源上限。
_Avoid_: Risk Budget、账户资金、系统容量

### Context and oversight

**Autonomy Trigger**:
由用户、Trading Calendar、市场、数据、账户或系统状态产生、用于启动一次有界自治工作的可追溯原因。
_Avoid_: Signal、Schedule 实现、Trade Plan

**Autonomy Cycle**:
在一个 Autonomy Trigger 下，依据版本化 ScanPolicy/UniversePolicy（OBSERVE/SHADOW）或有效 EffectiveAutonomy 范围（交易自治）完成机会扫描、专业委派、结果处置与重要信息报告的有界工作单元；无机会是正常终止结果。
_Avoid_: Orchestration Session、无界自循环、Trade Episode

**Supervision Notification**:
向用户传达重要机会、决策、成交、持仓、风险、异常或复盘事实的可追溯消息，默认用于知情和学习而非等待批准。
_Avoid_: Plan Approval、普通日志、不可操作告警

**Context Pack**:
为 Agent Task 组装的带来源、时点、版本和可信等级的业务引用集合。
_Avoid_: Prompt、聊天记录、Experience Memory

**Working Memory**:
只服务于当前 Orchestration Session 的暂时推理与任务状态，不自动成为 Validated Lesson。
_Avoid_: Experience Memory、聊天历史、长期知识

**Human Intervention**:
工作流因超出 Mandate Scope、命中升级条件、关键不确定性或用户主动要求而暂停，等待有权用户提供判断、补充信息或可选批准的明确状态；它不是每次模拟交易的默认步骤。
_Avoid_: Agent Failure、普通回复、Plan Approval 本身

**Escalation**:
因权限、冲突、不确定性或风险超出 Agent Authority，而把未决问题交给更高权限角色的动作。
_Avoid_: Delegation、告警通知、Risk Reject

**Agent Trace**:
连接 Agent Task、Agent Run、Context Pack、Tool Call、Tool Result、Handoff 和人工决定的可追溯工作记录。
_Avoid_: Governance Audit、交易审计、原始日志
