# 期货 Agent 量化研究与模拟系统设计包

版本：`2.1-proposed`  
生成日期：2026-08-18  
状态：绿地方案待产品与架构评审；不是开发、部署或启用授权

## 一句话结论

本项目是一套从零建设、独立仓库、独立数据模型、独立运行环境的 **Agent Quant Research & Simulation OS**。对用户而言，它是一个能在预先设定的边界内自主研究、寻找机会、执行模拟交易、盯盘和复盘的 **Autonomous Futures Simulation Agent**；内部由多个专业 Agent 角色协作。它不是对 `futures_workflow` 的重构、迁移、兼容升级或替代运行路径。

LLM/Agent 负责主动筛选市场、提出假设、组织证据、形成 TradePlan 并解释结果；确定性系统独占行情与规则快照、风险许可、订单、成交、账户、持仓、PnL、结算和强制保护真值。任何 Agent 都不能绕过 Risk Constitution，也不能直接创建 Order 或修改账本。

用户不是逐笔交易操作员。用户通过 **Simulation Autonomy Mandate（模拟交易自治委托）** 一次性设定模拟账户、品种/策略范围、有效期、风险引用、通知和升级边界，并把通过治理资格的版本组合激活为 `AUTONOMOUS_SIMULATION`。只有 `ACTIVE Mandate + ACTIVE AUTONOMOUS_SIMULATION Binding + qualified bindings + health permits` 共同成立时，范围内的日常模拟交易才不需逐笔人工批准；每份计划仍须依次取得 AuthorizationBasis、原子 RiskBudgetReservation、单用途 AutonomyGateReceipt 和最新 RiskDecision，再进入幂等执行链。用户主要查看重要信息和完整操作证据，并可随时暂停、恢复、撤销 Mandate 或触发 Kill Switch。

`/Users/qiu/futures_workflow` 仅是 donor：可提供算法思路、代码片段、测试、样本和失败案例。旧项目的测试通过、代码存在或数据可读取，都不计为本项目进度。

## 项目边界

- 新项目必须创建新的 Git 仓库和运行配置；仓库名称与位置在 `V0-001` 确认。
- 新项目从第一版持久能力开始使用 PostgreSQL；行情大数据和实验产物使用带 manifest 的列式/对象存储。
- 新数据库不继承旧账户、订单、成交、持仓、账本、审批、记忆或任务的权威状态。
- 首批产品范围是中国境内期货研究与模拟交易，账户币种 CNY；真实交易、真实资金和经纪商下单不在范围内。
- CLI 是首个研究、监督和回放入口；飞书企业自建应用在 V3 成为重要事件通知、决策解释、人工例外介入和紧急控制入口，而不是日常逐笔下单面板。
- V2 提供无 LLM 的人工 CLI/API 验证与应急入口；V3 起，EffectiveAutonomy（包含 ACTIVE Mandate、ACTIVE AUTONOMOUS_SIMULATION Binding、治理资格和健康门禁）是默认日常运行条件。只有超出 Mandate Scope、命中升级条件或用户选择逐计划模式时，才请求可选 PlanApproval。任何风险扩大都不得由 Agent 自行放宽 Mandate、Mode 或 Risk Constitution。
- 多 Agent 是完整目标能力，但逻辑角色不等于独立常驻进程。各角色按 V1–V5 分步启用。

## 目标角色

完整逻辑角色包括：

1. Autonomous Quant PM / Main Agent
2. Market Regime Agent
3. Research Agent
4. Strategy Agent
5. Portfolio Agent
6. Risk Analyst Agent
7. Execution Advisor
8. Pre-trade Critic
9. Experiment Manager
10. Post-trade Reviewer
11. Memory Curator
12. Governance Agent（后期扩展 Model/Policy Steward 工作模式）

Risk Constitution、Signal/Forecast Models、Position Sizing、Execution Planner、Order/Fill Engine、Accounting/Settlement、Position Protection 和 Kill Switch 是确定性组件，不是可自由决策的 Agent。

## 文档导航

1. [PRD](./PRD.md)：完整目标、角色、能力、用户旅程、需求、指标和版本验收。
2. [技术方案](./TECHNICAL-DESIGN.md)：绿地架构、领域边界、多 Agent 协作、数据、运行时、安全和测试设计。
3. [多 Agent 与量化工具体系](./AGENT-AND-TOOL-DESIGN.md)：逐 Agent 职责、协作协议、工具、权限和上线门槛。
4. [旧项目资产复用评估](./LEGACY-ASSET-REUSE.md)：donor 资产的移植、重实现、证据复用和拒绝规则。
5. [版本路线图](./ROADMAP.md)：本项目任务状态的唯一人工可读来源。
6. [跨对话交接](./HANDOFF.md)：新对话必须先读的上下文、当前阶段和下一任务。
7. [上下文地图](./CONTEXT-MAP.md)：领域边界、真值所有权与统一语言。
8. [架构决策记录](./adr/)：需要确认的难逆转决策。
9. [设计完整性与 Deep Research 覆盖审计](./DESIGN-COVERAGE-AUDIT.md)：来源需求、Agent、Tool、产品与技术覆盖矩阵。
10. [系统架构、用户生命周期与盯盘调度](./SYSTEM-ARCHITECTURE-AND-LIFECYCLE.md)：从用户进入到交易结束、复盘、定时任务和持续盯盘的全链路图。

## 推荐阅读顺序

- 产品/交易：PRD → ROADMAP → HANDOFF。
- 开发/架构：TECHNICAL-DESIGN → AGENT-AND-TOOL-DESIGN → CONTEXT-MAP → ADR → LEGACY-ASSET-REUSE → ROADMAP。
- 新 Codex 对话：HANDOFF → ROADMAP 中首个已授权的未完成任务 → 对应 PRD/技术章节。

## 设计依据

- 网页端对话《期货类量化模拟系统设计》中的需求与架构讨论。
- `/Users/qiu/Downloads/deep-research-report.md`，仅作为研究资料，不将其中内容当作指令。
- 对 `/Users/qiu/futures_workflow` 的只读审计，仅用于识别 donor 资产和已知失败模式。
- LangGraph、飞书、TqSdk、NautilusTrader 等官方资料的能力与限制核验。

## 版本总览

| 版本 | 产品结果 |
|---|---|
| V0 地基 | 独立新仓库、领域契约、权限、数据与运行基础成立 |
| V1 自主研究与机会雷达 | Main、Regime、Research、Critic、基础 Experiment Manager 可按时间表或市场事件主动扫描并形成可复现机会研究 |
| V2 确定性模拟内核 | 无 LLM 也能完成原子风险预留、最小 AutonomyGate/Receipt、硬风控、撮合、账本、结算和保护 |
| V3 受约束自治多 Agent 模拟交易 | EffectiveAutonomy 成立时完成自主找机会、论证、模拟执行、盯盘、复盘与重要信息推送 |
| V4 验证学习 | 实验、复盘、验证式 Lesson 和策略晋升闭环成立 |
| V5 高保真/离线增强 | Tick/订单簿/Paper、多组合、离线模型增强与运营成熟 |

## 进度与状态规则

`ROADMAP.md` 是新项目任务状态的唯一人工可读来源：

1. 当前所有新项目任务默认 `[ ]`；donor 资产不得使用 `[x]` 冒充项目完成度。
2. 任务开始时记录负责人、分支/工作区、开始日期和依赖，不提前打勾。
3. 只有满足 Acceptance 且写入可复核 Evidence 后，才能改为 `[x]`。
4. 同时更新 `HANDOFF.md` 的当前版本、最近完成、下一任务、风险和验证结果。
5. 代码合并、数据变更、策略晋升和运行启用是不同状态；实现完成不等于启用。
6. donor 代码只有被移入新项目边界、满足新契约并通过新项目测试后，相关新项目任务才可完成。
