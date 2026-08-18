# 跨对话交接

文档版本：`2.1-proposed`  
最后更新：2026-08-18  
当前阶段：V0 绿地项目地基
最近完成：`V0-007` PostgreSQL 持久化地基
当前开发任务：无
建议下一步：执行 `V0-008`，建立行情/研究数据分层与数据集 manifest

开发模型路由：按 `docs/DEVELOPMENT-MODEL-POLICY.md` 自动选择；常规开发使用 Terra/medium，安全关键开发使用 Terra/high，版本验收使用独立 Sol/high 或 xhigh。每项 Evidence 必须记录实际模型与推理强度。

## 给下一段对话的上下文胶囊

本项目是从零建设的 **Agent Quant Research & Simulation OS**，不是 `futures_workflow` 的重构、迁移、兼容升级或替代分支。对用户呈现为一个能独立找机会、模拟交易、盯盘和复盘的 Agent，内部由受限的专业 Agent 与确定性内核协作。

新系统必须拥有独立仓库、独立数据模型、独立数据库、独立配置和独立运行生命周期。`/Users/qiu/futures_workflow` 只是 donor，可供只读审计、算法移植、测试样本和失败案例参考；其代码、测试或数据库状态不构成新项目完成度，也不阻塞 V0 开始。

核心安全边界：

- Agent 对建立/增加/反向暴露只产生结构化 TradePlan；对已有暴露的 REDUCE/CLOSE/收紧保护只提交 RiskReductionRequest。两条路径都不能直接创建 Order、Fill、Position 或 LedgerEntry，降险请求还必须经过 Execution 的 T4-SAFE Validation 才能成为 ProtectiveRiskAction。
- 价格、规则、账户、持仓、PnL、保证金、成交与结算由确定性工具/内核给出。
- Risk Analyst Agent 只分析风险；Risk Constitution 才能产生权威 `RiskDecision`。
- 没有 Thesis、Invalidation、ProtectionIntent、MaxLoss、有效快照、有效 `AuthorizationBasis`（Simulation Autonomy Mandate 或可选 PlanApproval）、原子 RiskBudgetReservation 和单用途 AutonomyGateReceipt 的开仓计划不得进入 Risk Constitution；RiskDecision 才生成 ProtectionMandate，Execution 再把它落地为 StopPolicy。
- Simulation Autonomy Mandate 由 Decision 上下文拥有，是可暂停、恢复、撤销、过期且有明确作用域的长期模拟委托；它不是 RiskDecision、RiskBudget、ToolGrant 或 Strategy Activation。
- 日常自主模拟的必要条件是 `EffectiveAutonomy = ACTIVE Mandate ∧ ACTIVE AUTONOMOUS_SIMULATION Binding ∧ qualified bindings ∧ health permits`；满足后，机会扫描、计划、模拟执行、盯盘和复盘不等待用户逐笔操作。系统主动推送重要信息和完整证据，用户可随时暂停/撤销 Mandate、暂停运行模式或触发 Kill Switch。
- 保护性退出、Kill Switch 和日终结算不依赖 LLM、飞书或 Agent 在线。
- Reflection 不是知识；只有有证据、通过验证且带适用范围和有效期的内容才是 ValidatedLesson。
- 产品只用于研究与模拟；真实资金和真实下单不在范围内。

## 完整目标角色

目标逻辑角色为 Autonomous Quant PM / Main、Market Regime、Research、Strategy、Portfolio、Risk Analyst、Execution Advisor、Pre-trade Critic、Experiment Manager、Post-trade Reviewer、Memory Curator 和 Governance Agent；确定性 Workflow Orchestrator 负责触发、状态推进、重试与恢复，不计入 Agent 角色。Governance Agent 在 V5 可扩展 Model/Policy Steward 工作模式。

这些角色不等于十二个常驻服务。源码可采用模块化 monorepo，物理运行按 Gateway、Agent Worker、Research Worker、Trading Worker、Market Ingest 和 Scheduler/Outbox Sender 等安全与故障边界拆分。Agent 之间只交换版本化 artifact，不自由共享可变业务对象。

## 版本顺序

| 版本 | 结果 |
|---|---|
| V0 地基 | 新仓库、领域/Agent/Tool 契约、PostgreSQL、数据 manifest、安全与 CI |
| V1 自主研究与机会雷达 | Main、Regime、Research、Critic、基础 Experiment Manager 按用户、时间表或市场事件完成只读可复现机会研究 |
| V2 确定性模拟内核 | 原子风险预留、最小 AutonomyGate/Receipt、硬风控、订单、撮合、账本、结算、保护和恢复无需 LLM |
| V3 受约束自治多 Agent 模拟交易 | EffectiveAutonomy 成立时自主找机会、论证、模拟执行、盯盘、复盘和重要信息通知 |
| V4 验证学习 | Experiment 与 V3 Reviewer 扩展、Memory、Lesson 与 Strategy 晋升闭环 |
| V5 高保真/离线增强 | Tick/订单簿/Paper、组合扩展、离线模型增强和运营成熟 |

详细任务、依赖和 Acceptance 只以 `ROADMAP.md` 为准。当前 `V0-001` 至 `V0-007` 已完成，其余任务仍为 `[ ]`。

## 设计资料状态

- PRD、技术方案、上下文地图和 ADR 已作为新仓库的设计基线入库；`docs/adr/0001` 至 `0007` 已由 `V0-002` 接受，后续实现必须遵守。
- `LEGACY-ASSET-REUSE.md` 只记录 donor 资格，不是迁移计划，也不是进度基线。
- 对旧项目执行过的测试仅是 donor 审计证据；新项目必须拥有自己的 CI、契约测试、属性测试、黄金回放和 Agent eval。
- 新项目仓库为 `/Users/qiu/Documents/Codex/2026-08-18/new-chat/work/futures-agent-os`；项目名 `futures-agent-os`，包名 `futures_agent_os`，Python 3.14，uv，MIT License；首个基线 commit 为 `8d00a4331581026175270ae3bfa1414d438dc5df`。
- PostgreSQL 从新项目首个持久版本使用；不存在 SQLite 业务主库迁移阶段。

## 最近完成：V0-001

2026-08-18 完成以下范围：

1. 确认新项目名称和绝对路径。
2. 初始化独立 Git 仓库、许可证、运行时、依赖管理和目录骨架。
3. 建立最小健康检查与测试入口。
4. 证明 clean checkout 不读取旧仓库代码、数据库或配置即可运行。
5. 已把基线 commit 和验证命令作为 Evidence 写回 `ROADMAP.md` 并勾选 `V0-001`。

验证结果：clean clone 执行 `uv sync --locked` 成功，`uv run pytest` 为 `2 passed`，健康检查返回 `legacy_runtime_dependency=false`。未移植 donor 代码、未创建交易能力、未修改旧仓库、未启用外部消息。

## 最近完成：V0-002

2026-08-18 按领域建模门槛审阅并接受 7 项绿地架构决策，建立 `docs/adr/README.md` 索引和 ADR 契约测试。基线 commit 为 `dad8c5802abba56fa285a53ee6b7e436daf093fd`，`uv run pytest` 为 `5 passed`。未实现数据库、交易或 Agent 运行时。

## 最近完成：V0-003

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成领域边界基线，统筹对话复核。9 个核心业务上下文、1 个 supporting context、16 个关键聚合 owner 和 201 个 canonical term 均纳入自动检查；commit 为 `8d53b4b2ae485848b25153d50ff1a0d8fb796412`，`uv run pytest` 为 `10 passed`。未提前实现跨上下文业务功能。

## 最近完成：V0-004

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成共享内核契约，统筹对话补强定点 scale、极端 Decimal 与 Failure 序列化边界。commit 为 `eadb35640365a03759bcedf53446dbbfb8c0fb1e`，`uv run pytest` 为 `19 passed`。`TradingDate` 明确保留给交易日历赋值，夜盘归属不会由共享内核根据自然日猜测。

## 最近完成：V0-005

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成版本化 Agent Catalog、任务信封、不可变 artifact 与有界 handoff 协议，统筹对话补强预算、输入、重复声明和失败结果边界。commit 为 `6070d236f0129de01455001870cdaf2b3f87b66a`，`uv run pytest` 为 `24 passed`。12 个逻辑角色不等于 12 个常驻服务，Catalog 声明也不等于 Tool Grant 或运行启用。

## 最近完成：V0-006

2026-08-18 使用 `gpt-5.6-terra` / `high` 完成 Tool Registry、ToolGrant、ToolScope 与默认拒绝授权判定，统筹对话修正 owner、交易/治理 scope 和受信 Grant 来源边界。commit 为 `2ed377491212de476ec20bc9521fe48f9affba1e`，`uv run pytest` 为 `39 passed`。Registry 与权限判定不执行工具，也不替代业务授权或风险许可。

## 最近完成：V0-007

已使用 `gpt-5.6-terra` / `high` 建立 PostgreSQL 初始 schema、正式 migration、数据库角色、inbox/outbox、任务租约、Mandate/可选批准、调度、监督通知和 durable checkpoint 基础，实现 commit 为 `64ceb630975fa46420875a8e8c383e8bfd9c1906`。已在 Homebrew PostgreSQL `17.11` 的隔离空库执行真实 `upgrade → downgrade → upgrade` 及 integration round-trip；`FAO_DATABASE_URL=postgresql+psycopg://qiu@/futures_agent_os_v0_007?host=/tmp uv run pytest` 为 `48 passed`。业务 schema 与 Agent checkpoint 已验证隔离，且无旧库导入。PostgreSQL 服务已作为本机开发依赖启动。

## 下一任务：V0-008

建立行情/研究数据分层：raw immutable、normalized point-in-time、feature snapshot、dataset manifest 和 artifact store。每份数据集必须具有来源、许可、schema、时间覆盖、`as_of`、摄取时间、hash、质量和修订信息。该任务为常规开发，按模型路由使用 Terra/medium。

## 固定工作流程

本节的“授权/审批”指开发任务、代码合并、数据发布和治理 Activation 权限，不是产品运行中的逐笔模拟交易批准。

1. 先读本文件、`ROADMAP.md` 和任务引用的 PRD/技术章节。
2. 确认任务已获用户授权，且不会扩大到真实交易或外部启用。
3. 在新项目仓库记录 HEAD、工作区、负责人和开始日期；不得把旧仓库状态当成阻塞条件。
4. 先写 Acceptance 对应的测试或检查，再实现最小任务范围。
5. 使用新项目隔离配置、临时数据库和合成/获授权数据；不得读取旧业务数据库作为默认依赖。
6. 运行任务测试、相关集成测试和当时可用的全量回归。
7. 只有 Evidence 可复核时才更新勾选；同时更新本文件的阶段、最近完成、下一任务、风险和验证结果。
8. donor 复用必须单独通过 `LEGACY-ASSET-REUSE.md` 的资格门禁；复制代码不等于功能完成。
9. 合并、发布数据、策略晋升和运行启用分别审批。

## 进度更新模板

```text
Current version:
Current task:
Status: NOT_STARTED | IN_PROGRESS | BLOCKED | COMPLETED
Owner:
Workspace/branch:
Started at:
Completed at:
Acceptance checked:
Evidence:
New risks/open decisions:
Next task:
```

## 新对话可直接使用的提示

> 请先阅读 `/Users/qiu/Documents/Codex/2026-08-18/new-chat/work/futures-agent-os/docs/HANDOFF.md`、`ROADMAP.md`、仓库根 `README.md` 及当前任务引用的 PRD/技术章节。这是完全独立的绿地项目；`/Users/qiu/futures_workflow` 仅是 donor，不继承其运行状态，也不把其能力计作新项目进度。只执行路线图中首个已获授权的未完成任务，保持研究与模拟边界，并用新项目测试证据更新路线图和本交接文件。
