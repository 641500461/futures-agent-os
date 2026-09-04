# 绿地版本路线图与可勾选任务

版本：`3.0-proposed`<br>
最后更新：2026-09-04
任务状态唯一来源：本文件

## 状态约定

- `[ ]`：新项目任务尚未满足验收条件。
- `[x]`：Acceptance 已满足，且任务后附有可复核 Evidence。
- 进行中：保留 `[ ]`，追加 `Status: IN_PROGRESS`、负责人、工作区和开始日期。
- 阻塞：保留 `[ ]`，追加 `Status: BLOCKED`、日期、阻塞原因和所需决定。
- 代码完成、合并、数据发布、策略晋升和运行启用必须分别记录。
- donor 资产的可用性记录在 `LEGACY-ASSET-REUSE.md`，不在本文件中作为完成项打勾。

当前状态：V0 已完成（`V0-001` 至 `V0-014`），V1 已完成 `V1-001` 至 `V1-010`；`MVP-R-001` 与 `MVP-R-002` 均已在 Gate 停止。`MVP-R-003` v1 记为测量方案失败，Evidence 不得改写成通过。`MVP-R-004` 已 `STOP/PIVOT`。`MVP-R-005` Research Decision Brief 已通过 correction-v5 独立功能复核并完成。正式 MVP-R eval v1 与 v2 均保留 `FORMAL_DIAGNOSTIC_FAIL`，holdout/shadow 未启动；v2 采用产品模型 `gpt-5.6-sol/high`，诊断 13/30 完成后因 3 条失败达到停止条件。2026-09-04 最小 MVP Closure Acceptance 得出 `MVP_ACCEPTED`：核心 end-to-end 闭环成立，关键安全边界成立，没有明确产品 blocker。Formal Eval 不再阻塞 MVP 结束；formal evaluation reliability / quality improvement 转入后续 backlog。没有 `MVP-R-006`；`V1-011` 是下一项 Roadmap 任务，但等待用户确认后开始。

## MVP Closure：`MVP_ACCEPTED`（2026-09-04）

本次 Closure 只复用既有 Evidence 与测试，不恢复 30 diagnostic / 50 holdout / shadow，不修改 v1/v2 旧 Evidence。最小 acceptance 覆盖 8 个 correction-v5 代表性 Episode（AG/CU/MA/SR、趋势/噪声/极端/区间/反转/假突破）和 3 组关键安全反例：核心组件可串联完成研究 Agent → 确定性实验 → 结果反馈 → 决策简报；Agent 能完成有界研究任务；future leak、无来源数字、非法 operator、交易请求、报告/lineage 篡改与 runtime authority 越权均保持 fail closed。v2 的 013 为 `NON_BLOCKING_PRODUCT_QUALITY`，015/016 为 `EVAL_OR_RUNTIME_FAILURE`，没有 `BLOCKING_PRODUCT_FAILURE`。

可复核记录：[`evidence/mvp-closure/acceptance-2026-09-04.json`](../evidence/mvp-closure/acceptance-2026-09-04.json)。Formal Eval v1/v2 的失败结论原样保留，不再作为 MVP 结束的必要条件。

## 全局依赖原则

- 新系统必须独立于 `/Users/qiu/futures_workflow` 启动、测试、部署和恢复。
- 默认部署前提是个人自用、单用户、本机受控且操作者可信。对抗性本地篡改防护、Evidence 签名或合法重哈希防篡改、多用户 RBAC、租户隔离、零信任基础设施和同类安全加固默认不进入 Roadmap、Acceptance 或阻断性 review；只有用户明确重新授权，或部署变为公网、多用户、非可信操作者/数据执行环境、真实资金时才重新建模。
- 上述安全降级不等于降低交易与研究正确性：研究/仿真边界、确定性业务真值、风险上限、订单/成交/账本不变量、幂等/并发/恢复、实验可复现性仍是硬要求；密钥不得进入 Git/日志，不可信代码不得获得不受限的宿主机执行能力。
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
- [x] `V0-003` 建立领域上下文与统一语言：Reference/Market Data、Market Intelligence、Research & Experiment、Decision、Portfolio & Risk、Execution Simulation、Accounting & Settlement、Learning & Review、Governance & Registry。
  Acceptance: 每个聚合只有一个权威上下文；Agent Orchestration 明确为 supporting context；Simulation Autonomy Mandate、AutonomyModeBinding 与 AuthorizationBasis 由 Decision 拥有，DecisionJournal 追加投影由 Learning & Review 拥有。  
  Evidence: 2026-08-18 使用 `gpt-5.6-terra` / `medium` 实现，统筹对话复核；commit `8d53b4b2ae485848b25153d50ff1a0d8fb796412`。`docs/DOMAIN-BOUNDARY-BASELINE.md` 固化 9 个核心业务上下文、1 个 supporting context 和 16 个关键聚合的唯一 owner；Decision 词汇补齐 Autonomy Gate Receipt 所有权。`tests/contract/test_domain_boundary_baseline.py` 自动验证上下文数量/分类、关键 owner、projection/T4-SAFE 边界，以及全部 201 个 canonical term 跨上下文唯一且具有 `_Avoid_`；`uv run pytest` 为 `10 passed`，健康检查为 `status=ok`、`legacy_runtime_dependency=false`。模型路由规则另见 commit `8f4f63fa8c3a4b88c39ed342812c82f5f2671d60`。
- [x] `V0-004` 定义跨上下文 ID、Money/Price/Quantity、时区、`trading_date`、版本和错误码规范。
  Acceptance: Decimal/定点、Asia/Shanghai、UTC 记录时间、schema version 和 reason code 均有契约测试。  
  Evidence: 2026-08-18 使用 `gpt-5.6-terra` / `medium` 实现，统筹对话复核并补强极端定点数与 Failure 序列化边界；commit `eadb35640365a03759bcedf53446dbbfb8c0fb1e`。`shared_kernel` 提供不可变 UUIDv7 `EntityId`、拒绝 float 且绑定 unit/currency/scale 的 Money/Price/Quantity、UTC `RecordedAt`、Asia/Shanghai `ShanghaiTimestamp`、由交易日历显式赋值而不从自然日猜测的 `TradingDate`、`SchemaVersion`、稳定 `ReasonCode` 与 `Failure`。scale 限制为 0–18，异常 Decimal 统一为稳定 ValueError；`tests/contract/test_shared_kernel_contracts.py` 覆盖序列化、精度、时区和失败边界，全量 `uv run pytest` 为 `19 passed`，健康检查为 `status=ok`、`legacy_runtime_dependency=false`。
- [x] `V0-005` 定义完整 Agent Catalog、`AgentTaskEnvelope`、结构化交接 artifact 和有界协作协议。
  Acceptance: 12 个目标逻辑角色均写明职责、非职责、用户/时间表/市场/账户/系统事件触发、输入、输出、工具、权限、预算、失败策略、指标和启用版本。  
  Evidence: 2026-08-18 使用 `gpt-5.6-terra` / `medium` 实现，统筹对话复核并收紧预算、输入和失败结果边界；commit `6070d236f0129de01455001870cdaf2b3f87b66a`。版本化 `AGENT_CATALOG` 机器可检查 12 个逻辑角色的职责/非职责、五类触发、输入输出、工具声明、权限边界、预算、失败策略、指标与启用版本；`AgentTaskEnvelope` 拒绝角色版本、输入、工具、输出或预算越界及重复声明。`ArtifactRef`/`StructuredArtifact`/`AgentHandoff` 只传递带 SHA-256、schema、as_of/expiry 的不可变引用，不转移权限；Main 与确定性 Workflow Orchestrator 保持分离。全量 `uv run pytest` 为 `24 passed`，compileall、健康检查与 diff check 通过；未实现模型调用、Tool Grant 或交易副作用。
- [x] `V0-006` 建立 Tool Registry 与权限模型：细分只读、研究请求、提案、Mandate Scope 内自治模拟变更、可选逐计划批准、晋升和启用权限，并支持账户/策略/品种/环境作用域。
  Acceptance: 默认拒绝；未授权 Agent、节点或作用域无法调用工具；权限矩阵有自动化测试。  
  Evidence: 2026-08-18 按安全关键路由使用 `gpt-5.6-terra` / `high` 实现，统筹对话复核并修正工具 owner、交易/治理 scope 与受信 Grant 来源边界；commit `2ed377491212de476ec20bc9521fe48f9affba1e`。版本化 Tool Registry 仅精确解析 `tool_id@major.minor`，覆盖 READ_ONLY、RESEARCH_REQUEST、PROPOSAL、MANDATE_SCOPED_SIMULATION、PLAN_APPROVAL、PROMOTION、ACTIVATION 七类权限；确定性 ToolAuthorizer 默认拒绝，并校验 Agent Catalog、节点、工具版本、Grant 状态/有效期、账户/策略/品种/政策/环境或 governed artifact scope。每次判定产生稳定 reason code、request hash、call/correlation ID 与匹配 Grant 引用；ToolGrant 不替代 Mandate/Basis/Receipt/RiskDecision/Activation。`risk_check` 仅是非权威预检；正式 RiskDecision 仍归 Portfolio & Risk。全量 `uv run pytest` 为 `39 passed`，compileall、健康检查和 diff check 通过。
- [x] `V0-007` 建立 PostgreSQL 初始 schema、正式 schema migration、数据库角色、inbox/outbox、任务租约、Mandate/可选批准、调度、监督通知和 durable checkpoint 基础。
  Acceptance: 空库可重复建库、升级、降级演练；业务表与 Agent checkpoint schema 隔离；不包含旧表导入。  
  Evidence: 2026-08-18 按安全关键路由使用 `gpt-5.6-terra` / `high` 完成实现，统筹对话复核并修正 checkpoint 跨 schema 外键权限与 URL 编码凭据边界；实现 commit `64ceb630975fa46420875a8e8c383e8bfd9c1906`。已建立 PostgreSQL-only Alembic baseline、NOLOGIN 最小权限角色、`fao`/`agent_checkpoint` schema 隔离、inbox/outbox/dead-letter、命令/事件/审计、任务租约、schedule、监督通知、Mandate/PlanApproval 基础和 durable checkpoint；CI 与本地 runbook 均定义真实 PostgreSQL `upgrade → downgrade → upgrade` 验收。已通过 Homebrew PostgreSQL `17.11` 在隔离空库 `futures_agent_os_v0_007` 执行真实 `upgrade → downgrade → upgrade` 及 integration round-trip；随后 `FAO_DATABASE_URL=postgresql+psycopg://qiu@/futures_agent_os_v0_007?host=/tmp uv run pytest` 为 `48 passed`，health、compileall、离线 migration SQL、shell 语法和 diff check 通过。无旧表导入。
- [x] `V0-008` 建立行情/研究数据分层：raw immutable、normalized point-in-time、feature snapshot、dataset manifest 和 artifact store。
  Acceptance: 每份数据集具有来源、许可、schema、时间覆盖、`as_of`、摄取时间、hash、质量和修订信息。  
  Evidence: 2026-08-18 按常规开发路由使用 `gpt-5.6-terra` / `medium` 实现，统筹对话使用 domain-modeling 审核并修正“内容 hash 与 manifest identity 必须分离”的数据所有权边界；commit `87bc6416eb367d6f9f754134eba5fac3205ea6b4`。Reference & Market Data 提供不可变 `DatasetManifest`、Provenance、License、Schema、Coverage、`as_of`/ingested time、Quality 与 Revision 契约；raw/normalized PIT/features/datasets/artifacts 分层，PIT 记录以 `available_time` 拒绝未来数据泄漏。内容按 SHA-256 去重，manifest 按 Dataset ID 独立不可变保存，读取时复验 hash；同内容可对应不同修订 manifest，冲突 identity 不可覆盖。`uv run pytest` 为 `53 passed, 1 skipped`，compileall 与 diff check 通过；未下载外部数据、未引入 donor 运行时依赖。
- [x] `V0-009` 建立身份、密钥、日志脱敏、Prompt Injection、代码执行沙箱、网络出口和供应链威胁模型。
  Acceptance: Git/日志无凭据；不可信文本不能改变权限；研究执行有 CPU/内存/时间/文件/网络上限。  
  Evidence: 2026-08-18 按安全关键路由使用 `gpt-5.6-terra` / `high` 实现，统筹对话发现并修正“冻结对象接受可变 collection”的授权/沙箱 TOCTOU 漏洞；commit `4810527f049f1d0bc5c82b4b9a5d05035064dea6`。已提供 ServiceIdentity、只允许 `secret://` reference 的 credential binding、递归结构化日志脱敏、不可信内容与 AuthorityContext 隔离、资源/文件/精确出口 allowlist 的 default-deny 研究沙箱 validator，以及供应链威胁模型。V0 不解析 secret、不运行代码、不读取外部数据或联网；未来 executor 仍需独立 OS/container 强制隔离。`uv run pytest` 为 `60 passed, 1 skipped`，compileall、health 与 diff check 通过。
- [x] `V0-010` 建立统一 correlation/causation、命令幂等、追加审计、metrics/logs/traces 和最小告警框架。
  Acceptance: 从请求到工具调用和领域事件可关联；重复命令最多产生一个业务效果。  
  Evidence: 2026-08-19 按安全关键路由使用 `gpt-5.6-terra` / `high` 加固并完成实现，统筹对话两轮复核修正 caller-owned mutable payload、迁移测试混线、ToolCall trace 断点以及告警缺少 runbook/影响范围；commit `50cd1b756ea301a5d4b4ea59a821956b08eb1df4`。已实现统一 `TraceContext` 与真实 AgentTask/ToolCall/ToolAuthorization correlation/causation 传播、稳定 canonical request hash、并发安全的单效果幂等参考模型、深度不可变追加审计 hash chain、递归脱敏且不可变的本地 metrics/logs/traces、threshold/absence 告警及 `runbook_ref/impact_scope`。PostgreSQL migration `0002_v0_010` 增加全局 idempotency-effect 唯一约束、audit append-only trigger、telemetry 与 alert 表；在隔离 PostgreSQL 17 数据库强制 `downgrade base → upgrade head` 后，全量 `FAO_DATABASE_URL=postgresql+psycopg://qiu@/futures_agent_os_v0_007?host=/tmp uv run pytest` 为 `74 passed`，compileall、health、migration history 与 diff check 通过。
- [x] `V0-011` 建立 CI、依赖锁、类型/静态检查、单元/属性/契约测试、schema 兼容检查和敏感信息扫描。
  Acceptance: 新仓库主分支保护启用；本地与 CI 使用相同锁定环境。  
  Evidence: 2026-08-19 按常规开发路由使用 `gpt-5.6-terra` / `medium` 完成实现，统筹对话复核并将无密码本地 PostgreSQL 限定到 loopback、把 GitHub Actions 固定到官方仓库 commit SHA；基础实现 commit `a2aaeeaba6ab102c3d55213005d0bb67604c4efb`。uv.lock 已锁定 Ruff、mypy、Hypothesis、detect-secrets 与测试依赖；`Makefile` 是本地/CI 统一入口，覆盖 lock/format/lint/type/secret scan/schema compatibility/unit/property/contract/integration/health，workflow 使用相同 targets 与临时 PostgreSQL。`make check` 通过（mypy 29 source files、schema 2、unit 1、property 1、contract 76）；真实 PostgreSQL integration 为 `2 passed`，DB-backed 全量为 `80 passed`，diff check 通过。公开 GitHub 仓库 `641500461/futures-agent-os` 的远端 Quality gate 五个 job 均通过；`main` branch protection 已由 API 回读证明启用，strict required checks 为 `quality/unit/property/contract/integration`，要求 PR，管理员同样受约束，禁止 force push/delete，并要求线性历史与会话解决。
- [x] `V0-012` 建立新项目 synthetic/golden 数据集与边界案例库；首批验收宇宙明确选择 AG、CU、RB、JM、I、MA、SA、M、P、SR、SC、JD。
  Acceptance: 品种选择有产品理由；夜盘、规则变更、涨跌停、跳空、无流动性、乱序和缺失数据均有样本。  
  Evidence: 2026-08-19 按常规开发路由使用 `gpt-5.6-terra` / `medium` 实现，统筹对话使用独立 `gpt-5.6-sol` / `high` 三轮验收并修正版本身份漂移、全局到达顺序、bundle lineage 和语义伪阳性。已建立 AG/CU/RB/JM/I/MA/SA/M/P/SR/SC/JD 的可复现 Q2 synthetic 低频数据、非冗余产品选择理由和案例目录；夜盘交易日归属、历史规则变更、上/下涨跌停、Decimal 跳空、无 OHLCV/报价流动性、按 `available_time` 有序但事件时间逆序的迟到数据、显式缺失区间均有严格契约。事件、事件 manifest、catalog 和 bundle 四份资产由 bundle hash 与独立 release oracle 锁定，manifest-only 篡改也 fail closed；Dataset 与 Bundle 分别使用首版 revision 1 且无虚构 predecessor。`make check` 通过（contract `89 passed`），全量 `uv run pytest` 为 `91 passed, 2 skipped`，Ruff、mypy、secret scan 与 diff check 通过；Sol/high 最终复核无 P0–P3。数据明确不声称 tick、订单簿、成交或执行保真度。
- [x] `V0-013` 按 `LEGACY-ASSET-REUSE.md` 对 donor 候选逐项做资格评估，不迁移运行状态。
  Acceptance: 每个采用项有 provenance、新接口、隔离性、安全扫描和新项目测试；拒绝项有理由。  
  Evidence: 2026-08-19 按常规开发路由使用 `gpt-5.6-terra` / `medium` 实现，统筹对话使用独立 `gpt-5.6-terra` / `high` 安全复核并修正两项 SQLite/绝对路径/DB 写入扫描误报、自洽假阳性与 `ABSENT` 未验真。机器可校验清单完整覆盖 `LEGACY-ASSET-REUSE.md` 的 34 个候选，固定 donor commit `b9f3bb9d185a6d659e096d615b5afb435769134d`、34 项 ID→R1/R2/R3/R4→source 基准、manifest digest、license 门禁和全部 provenance/gate/next-action。结果为 20 `CANDIDATE`、3 `DEFERRED`、9 `EVIDENCE_ONLY`、2 `REJECTED`、0 `QUALIFIED`；`futures_sim_trade_bridge` 与 `db_manager` 的 R4 拒绝理由已记录，未验证许可证阻断任何后续 qualification。显式人工参数脚本仅使用 `git rev-parse/cat-file/ls-tree` 对 `/Users/qiu/futures_workflow` 固定 commit 做只读复验，38 个 blob 与 1 个 `ABSENT` 均通过；29 个 tracked 修改和 3 个 untracked 工作树项不影响 Git object snapshot。未运行 donor 代码/测试，未读取数据库或运行状态，无 donor 运行时依赖。`make check` 通过（contract `98 passed`），全量 `uv run pytest` 为 `100 passed, 2 skipped`，diff check 通过；Terra/high 最终复核无 P0–P3。
- [x] `V0-014` 定义 Simulation Autonomy Mandate、Mandate Scope、AutonomyModeBinding、AuthorizationBasis/PlanApproval、两阶段 AutonomyGate、AutonomyGateReceipt、RiskBudgetReservation、DecisionJournal、TradeEpisode 投影与监督控制契约。
  Acceptance: Mandate 必须版本化并绑定模拟账户、品种/策略/时段范围、有效期、风险引用、通知和升级规则；Mandate 九态 `DRAFT/VALIDATED/APPROVED/ACTIVE/SUSPENDED/EXPIRED/REVOKED/HALTED/RECOVERING` 完整，除 DRAFT 外所有非终态受 expiry 约束，APPROVED/ACTIVE/SUSPENDED/HALTED/RECOVERING 可 revoke；Mode 四态、Binding ACTIVE/EXPIRED/SUPERSEDED、EffectiveAutonomy、composite pause 与 V1 可空 account/mandate 语义明确；PlanApproval 五态和“GRANTED 原子消费为唯一 Basis”契约完整；Receipt 绑定 Plan/AuthorizationBasis/源授权 hash、`execution_origin`、快照、运行版本、预算预留、有效期、单次 nonce 及 AUTONOMOUS_AGENT 必需的 Mode id/version/hash；Reservation 归属 Portfolio & Risk；DecisionJournal 区分 DECISION_TIME/POST_HOC 且可重建，TradeEpisode 明确归 Learning & Review 且只投影源事件；并发与竞态契约测试通过；任何对象都不能放宽 Risk Constitution。  
  Evidence: 2026-08-21 按安全关键路由使用 `gpt-5.6-terra` / `high` 实现并多轮收紧，独立 `gpt-5.6-sol` / `high` 对每个失败反例重现和回归，最终无 P0–P3。新增内存参考契约与 PostgreSQL migrations `0003/0004`，覆盖 Mandate/Mode/Basis/Approval/两阶段 Gate/Receipt、原子风险预留、监督暂停/恢复/到期/撤销、DecisionJournal 与 TradeEpisode 确定性投影。真实 PostgreSQL 17.11 验证了 DB 权威时钟、最小权限角色、并发预算不超卖、单用途与幂等授权、scope/health/snapshot/actor 边界、源事件身份、旧数据 fail-closed 归一化、populated `0002 → head → 0002 → head` 及 legacy `0003` 往返。`make check` 通过（contract `118 passed`）；连接隔离 PostgreSQL 的全量测试为 `145 passed`；Ruff、mypy、secret scan、health 与 diff check 通过。未实现真实交易、Order/Fill/Ledger 或 LLM 运行时。

Exit：新仓库可独立启动和恢复；领域、Agent、Tool、数据、安全、存储和测试基础全部有证据；旧项目不可用不会影响新项目。

## V1：自主研究与机会雷达

目标：Main、Market Regime、Research、Critic 和基础 Experiment Manager 除了回答用户问题，还能按 Trading Calendar、行情收盘、数据更新或市场事件主动扫描授权研究宇宙，形成可复现的机会候选与研究结果；本版本不产生交易副作用。

- [x] `V1-001` 实现 Instrument/Variety/Exchange/Continuous Series 注册和解析，严格区分研究连续序列与可交易合约。
  Depends: V0。  
  Acceptance: 首批验收宇宙的别名、交易所和合约解析契约通过；Continuous Series 不能进入交易计划。  
  Evidence: 2026-08-23 使用 `gpt-5.6-terra` / `medium` 实现不可变、版本化 Instrument Registry，并由独立 `gpt-5.6-terra` / `high` 反例审查至无 P0–P3。首批 AG/CU/RB/JM/I/MA/SA/M/P/SR/SC/JD 12 个 synthetic contract 均可按交易所规则解析；Alias 与 Dominant target 同时受 `acquired_at` PIT 门禁；SHFE/DCE/INE 四位、CZCE 三位交割码显式校验且不猜年代；Variety、Dominant、Continuous、8888/9999 均不能成为可交易目标。固定 registry id/version/content hash oracle、半开生效区间、重叠拒绝、Unicode/空白/畸形输入、不可变 snapshot 与并发读取均有契约/属性测试。`make check` 通过（contract `137 passed`），连接 PostgreSQL 的全量测试为 `165 passed`，health、Ruff、mypy、secret scan 与 diff check 通过；未接入外部行情、真实交易或 donor 运行时。
- [x] `V1-002` 实现带有效期的 `ContractRuleVersion` 和来源追踪：乘数、tick、保证金、手续费、涨跌停、交易时段、最后交易日、限仓、开平今。
  Acceptance: 指定 Instrument 与 trading date 只能命中一个适用版本；缺失或冲突时返回稳定失败码。  
  Evidence: 2026-08-23 按规则真值安全边界使用 `gpt-5.6-terra` / `high` 实现，并由独立 `gpt-5.6-terra` / `high` 对抗验收至无 P0–P3。新增不可变、Instrument 精确作用域的完整 `ContractRuleVersion`、双时维 `resolve(instrument, trading_date, as_of)`、release/rule content hash 与历史 `RuleSetRef`；明确不做 Exchange/Variety 字段继承或跨版本拼接。乘数、tick、最小量、保证金、开/平/平今费、涨跌停、sessions、最后交易日、交割限制、持仓/交易限额和 offset 规则均为完整显式事实；Decimal、scale、`<underlying>/lot` 与 `<currency>/<underlying>` 单位维度严格校验。缺失、冲突、未来不可见分别稳定返回 `RULE_MISSING/RULE_CONFLICT/REFERENCE_NOT_YET_VISIBLE`，半开区间、provenance、不可变并发和畸形输入有契约/属性回归。`make check` 通过（contract `146 passed`），连接 PostgreSQL 的全量测试为 `176 passed`，Ruff、mypy、secret scan、health 与 diff check 通过；未实现交易日推导、资金计算、外部规则源或交易副作用。
- [x] `V1-003` 实现交易日历与 `trading_date` 服务，覆盖夜盘、节假日、主力切换、临近交割和规则临时调整。
  Acceptance: 上期所、大商所、郑商所和中金所代表性夜盘/节假日边界测试通过。  
  Evidence: 2026-08-23 按时间归属安全边界使用 `gpt-5.6-terra` / `high` 实现，并由独立 `gpt-5.6-terra` / `high` 多轮对抗验收至无 P0–P3。新增不可变、版本化、Variety 精确作用域的 PIT `TradingCalendar/TradingDateService`，补齐 CFFEX；SHFE/DCE/CZCE 的代表性夜盘与四所日盘、集合竞价、午休、节假日、临时休市和提前收市均由显式 Asia/Shanghai session occurrence 绑定 TradingDate，不使用自然日或下一个工作日猜测。日历 revision 以不可变 ID 和显式 supersedes 建模，可按 `as_of` 重放 open→closure→reopen；future correction、可变集合、跨品种/跨日期 supersession、半开边界、错误时区、冲突和并发均 fail closed。主力切换、近交割和规则调整只保存跨 owner 引用，不在日历内解释或改变交易对象。固定 synthetic release id/version/hash oracle 已锁定。`make check` 通过（contract `161 passed`），连接 PostgreSQL 的全量测试为 `193 passed`，Ruff、mypy、secret scan、health 与 diff check 通过；未接入官方日历源、调度器或交易副作用。
- [x] `V1-004` 实现 point-in-time `MarketSnapshot`、数据新鲜度/完整性/冲突检测和稳定 reason code。
  Acceptance: 缺失、陈旧、乱序或未来泄漏数据不会被静默采用。  
  Evidence: 2026-08-23 按市场数据安全边界使用 `gpt-5.6-terra` / `high` 实现，并由独立 `gpt-5.6-terra` / `high` 多轮对抗验收至无 P0–P3。新增不可变、用途专属、内容寻址的 PIT `MarketObservation/MarketSnapshot`；快照只接受实际 Instrument Registry Resolution、ContractRuleRegistry/RuleResolution、TradingCalendar/TradingDateResolution、DatasetManifest 及逐记录 `DatasetRecordRef`，并将完整证据、policy/schema 版本和目的纳入哈希。支持 Quote/Bar/Trade/Settlement/Open Interest；缺失、陈旧、到达乱序、重复、冲突、未来可见、未完成 Bar、缺口、异常跳变、fallback 和不可信时间戳均产生结构化质量事实与稳定失败码。Observation 修订图验证前序、自然键、来源谱系、版本/时间单调、无环无分叉，并按 `as_of` 选择唯一 active leaf；完整历史仍进入快照哈希。DISPLAY/RESEARCH/BACKTEST/EXECUTION 独立准入，零深度或非主源报价、连续合约、跨合约规则、闭市/旧日历、过期规则均不能获得执行资格；精确触及规则涨跌停与未解释跳变分开处理。`make check` 通过（contract `175 passed`、property `9 passed`），连接 PostgreSQL 的全量测试为 `210 passed`，Ruff、mypy、secret scan、health 与 diff check 通过；未接入外部行情、特征模型、Agent 或交易副作用。
- [x] `V1-005` 实现版本化 Feature Engine 和确定性 Regime/Signal Model Service。
  Acceptance: 特征输入、窗口、版本和快照可重现；模型输出不被当作交易许可。  
  Evidence: 2026-08-24 按 point-in-time 与模型完整性边界使用 `gpt-5.6-terra` / `high` 实现，并由独立 `gpt-5.6-sol` / `high` 以 15 组真实反例多轮验收至无 P0–P3。Research & Experiment 拥有版本化 `FeatureDefinition/FeatureSpec` 与 `SignalDefinition/SignalModelSpec/Signal`，Market Intelligence 拥有不可变 `FeatureObservation` 与确定性 `RegimeAssessment`；所有计算绑定用途、唯一市场引用、精确 ObservationKind、快照/记录 hash、窗口、cadence、session、scale、算法和模型版本，使用固定 Decimal context，拒绝未来、跨 session、跨 reference、缺口、未完成 Bar、未知版本、重复证据和伪造 lineage。Regime 分别记录 return/volatility/liquidity 正反证据与未知项；Signal 通过深冻结 anti-corruption evidence ref 消费特征，重放 content hash 不依赖随机实体 ID。所有模型产物固定为 `NON_TRADING`，静态契约禁止依赖 Decision/Risk/Execution/Accounting 权威对象。`make check` 通过（contract `184 passed`、property `9 passed`），连接隔离 PostgreSQL 的全量测试为 `219 passed`，Ruff、mypy、secret scan、health 与 diff check 通过。当前单 component `MarketSnapshot` 无法安全表达跨换月连续历史、期限结构和基差，相关能力显式 fail closed 并留待其 PIT 证据模型任务，不虚构完成；未接入外部行情、Agent 或交易副作用。
- [x] `V1-006` 实现 Market Regime Agent，输出带正反证据和不确定性的 `MarketStateAssessment`。
  Acceptance: 输出通过 schema，引用不可变快照和特征版本；不能生成 TradePlan、RiskDecision 或 Order。  
  Evidence: 2026-08-24 按 Agent/市场解释边界使用 `gpt-5.6-terra` / `high` 实现，并由独立 `gpt-5.6-sol` / `high` 多轮反例验收至无 P0–P3。Market Intelligence 以纯、版本化 Composer 消费 V1-005 的不可变 `MarketSnapshotRef`、完整 `FeatureObservation` lineage 与确定性 `RegimeAssessment`，输出 `MarketStateAssessment`：保留全部候选、冲突、正反证据、未知项、替代解释、有效期和转换风险；只有具备正向证据的唯一最高候选可成为主状态，反证-only/unknown-only 明确无主状态且风险为 `UNKNOWN`。Agent Orchestration 仅依赖 task/artifact ports，Catalog 显式升级至 `1.1` 并新增三类只读输入 artifact；adapter 将裸 hash 严格转换为 `sha256:`、逐项核验角色/版本/工具/输出/时间/快照/特征/Regime 谱系，深冻结并独立复算 payload hash，再生成每条 claim 均有 source refs 的 `StructuredArtifact`，不完整输入只可 `DEFERRED`。重复 lineage、错快照、额外特征、过期或变异 payload、证据语义漂移及 caller-owned mutable duck 均 fail closed。输出固定 `NON_TRADING`，静态契约禁止依赖 Decision/Portfolio & Risk/Execution/Accounting 交易权威对象。`make check` 通过（contract `187 passed`、property `9 passed`、mypy `45` source files），连接隔离 PostgreSQL 的全量测试为 `222 passed`，Ruff、secret scan、health 与 diff check 通过；未实现外部新闻/期限结构、LLM 调度、持久 AgentRun、Research Agent 或交易副作用。
- [x] `V1-007` 实现 Research Agent，输出可证伪 `Hypothesis`、未知项、证据缺口和 `ExperimentRequest`。
  Acceptance: Research Agent 没有交易、审批、晋升或账本权限。  
  Evidence: 2026-08-24 按研究产物与 Agent 权限边界使用 `gpt-5.6-terra` / `high` 实现，独立 `gpt-5.6-sol` / `high` 四轮对抗验收最终无 P0–P3。Research & Experiment 新增不可变、内容寻址且绑定精确 PIT `MarketStateAssessment` 的 `Hypothesis`、`EvidenceSynthesis` 与非执行 `ExperimentRequest`；Hypothesis 完整表达适用市场、可观察结果、反证、所需数据、提出来源和七态生命周期，但本任务只允许创建/封装 `DRAFT`。实验请求固定数据、对照、评估窗口、方法、指标、预期诊断、停止条件和潜在偏差；known/unknown/conflict/gap 可显式为空而不诱导伪造。Agent Catalog 升至 1.2，仅声明已实现的 MarketStateAssessment 输入和三个研究输出；Research 无 TradePlan/StrategyCandidate 输出，也无交易、审批、晋升或账本工具。封闭 payload key set、严格 schema/type/time/identity、深冻结、spec/source identity hash、跨 artifact 数据一致性与重放由 authority-injection、READY_FOR_TEST 越权、bool-as-int、mutable duck、数据漂移等真实重哈希反例证明。实现 commit `5ee47cb`；`make check` 通过（contract `208 passed`、property `9 passed`、mypy `47` source files），连接隔离 PostgreSQL 的全量测试为 `243 passed`，Ruff、secret scan、schema compatibility、health 与 diff check 均通过。未发生模型升级；实现模型未覆盖的 lifecycle owner、空冲突语义和封闭 port 攻击由确定性测试与 Sol/high reviewer 裁决。未实现实验执行、LLM/持久 AgentRun、用户观点/Reflection adapter、StrategyCandidate 或交易副作用。
- [x] `V1-008` 实现只读 Autonomous Quant PM / Main Agent、确定性持久 Workflow Orchestrator、`AutonomyCycle/DecisionEpisode` 与 DecisionJournal 基础投影，支持用户、时间表与市场/数据事件触发，以及 typed DelegationPlan、fan-out/fan-in、取消、超时和预算。
  Acceptance: 同一 cycle/episode 可跨进程恢复；重复触发最多产生一个有效周期；Main 不拥有 durable 调度状态；DecisionJournal 可从源事件重建，不覆盖当时事实。  
  Evidence: 2026-08-25 按跨上下文持久编排与幂等边界使用 `gpt-5.6-terra` / `high` 实现并多轮加固，独立 `gpt-5.6-sol` / `high` 以并发和故障反例最终验收无 P0–P3；实现 commit `8be2e36`。新增 Catalog 1.3 只读 Main、不可变 typed `DelegationPlan`、确定性 fan-out/fan-in、预算/超时/取消、租约 fencing 与 PostgreSQL 持久 checkpoint；用户、时间表及市场/数据事件触发以规范 payload/hash 和幂等键最多创建一个有效 `AutonomyCycle`，Main 只提出计划且不拥有 durable schedule state。`AutonomyCycle/DecisionEpisode` 生命周期、task definition/execution/binding 均不可覆盖，可跨新连接恢复；并发首次精确持久化收敛到相同稳定任务 identity，非精确重试 fail closed；下游只消费上游实际产出的唯一 artifact identity。DecisionJournal 按 episode 绑定追加式源事件 identity，可重建 DECISION_TIME/POST_HOC 历史而不改写当时事实。`make check` 通过（contract `215 passed`、property `9 passed`、mypy `48` source files），连接隔离 PostgreSQL 的全量测试为 `266 passed`，迁移 `0004 → head` 与 8 项 downgrade/upgrade round-trip 通过；Ruff、secret/schema、health 与 diff check 通过。未发生模型升级；未实现 LLM 调用、实验执行、TradePlan、RiskDecision、Order 或任何交易副作用。
- [x] `V1-009` 实现研究版 Pre-trade Critic，检查反证、数据泄漏、成本覆盖、样本适用性和结论强度。
  Acceptance: 高严重度未解决项强制 `DEFER`，迭代次数有上限。  
  Evidence: 2026-08-25 初始实现按常规研究契约路由使用 `gpt-5.6-terra` / `medium`，在独立验收发现持久化、权限和 SQL/Python 一致性风险后升级为 `gpt-5.6-terra` / `high` 加固；独立 `gpt-5.6-sol` / `high` 多轮对抗复验最终无 P0–P3。实现 commit `efd832a`。Catalog 升至 1.4；新增不可变、内容寻址的 `Critique`、固定 policy/revision 上限、Pre-trade Critic artifact-only adapter，以及跨进程可恢复的 Research 三产物 fan-in、专用 fenced completion、sidecar hydration 与最小权限 migration `0006`。因 V1-010 的确定性诊断生产者尚未实现，V1-009 不接受调用方自报诊断，八类检查固定产生完整 `GAP/UNRESOLVED`，其中 `DATA_LEAKAGE=HIGH`，唯一合法结论为 `DEFER` 且 `max_iterations=1`；generic/legacy completion、过期来源、非规范嵌套快照、错误 hypothesis/revision、越权字段、直接 sidecar 读取及不精确重试均 fail closed。`make check` 通过（contract `224 passed`、property `9 passed`、mypy `50` source files），全新 PostgreSQL 全量测试为 `276 passed`，Critic integration `1 passed`，8 项 migration round-trip 通过；空库 `head → 0005 → head` 正确恢复 V1-008 worker 权限，有 durable Critique 事实时 downgrade 在任何 schema 变更前原子拒绝并保留 `0006` 数据。未实现模型调用、V1-010 诊断工具、StrategyCandidate、TradePlan、Order 或任何交易副作用。
- [x] `V1-010` 实现研究工具：market/historical/feature/contract 查询、memory/experiment search、L0 Signal Test、L1 Bar Backtest，以及单策略基础 walk-forward、成本/滑点 stress 与 counterfactual。
  Acceptance: 工具结果包含版本、`as_of`、source refs、warnings、artifact refs 和失败码；基础验证固定样本切分、成本假设、停止规则与可复现配置，供后续 L2 资格证据复用；至少一条冻结 `MarketSnapshot → research diagnostics → Critic` 垂直链路可重放，且工具不能产生交易副作用。V1-010 完成只触发 `MVP-R-001`，不等于 MVP 已成立。<br>
  Evidence: 2026-08-27 按 PIT、可重放与工具权限边界使用 `gpt-5.6-terra` / `high` 实现，独立 `gpt-5.6-sol` / `high` 经六轮对抗复验最终无 P0–P3；实现 commit `67faddf`。Catalog/Tool Registry 升至 1.5/1.1 并仅授权 11 个精确版本新工具；旧 Catalog 1.4 语义保留，1.5 对 legacy research grants 稳定拒绝。L0 仅验证 signal/forward label，L1 固定 close-to-next-open 方向近似、成本与滑点且无 fill 语义；walk-forward 使用固定时序 train/embargo/test、不调参和停止规则，stress 逐项只改成本或滑点，counterfactual 只反转 signal direction。完整 `MarketSnapshot → 11 tool results → 8 diagnostics → Critic → AgentTaskEnvelope/StructuredArtifact` 链路具有确定 logical identity、JSON hydration 和跨 worker recovery；composition-root trusted ports、真实 V1-005 `FeatureObservation`、owner-issued memory/experiment batches、tool-result proof 及 deterministic rerun 阻断伪造来源、metrics、失败实验或 diagnostics，缺失/重复/过期/篡改不会产生 PASS artifact。`make check` 通过（contract `232 passed`、property `9 passed`、mypy `53` source files）；全新 PostgreSQL `alembic upgrade head` 后全量 `284 passed`，8 项 migration round-trip 通过，Ruff、secret scan、schema compatibility、health 与 diff check 均通过。未实现真实模型调用、V1-011/V2、StrategyCandidate、TradePlan、Order/Fill/Position 或任何交易副作用；本任务完成只触发 `MVP-R-001`，不等于 MVP 已成立。
- [ ] `MVP-R-001` 在 `V1-010` 后运行研究可用性试验：补齐最小真实模型调用、受限串行工具循环、少量授权真实 PIT 数据、Replay/Evaluation Harness、诊断/封存 Episode、基线与 Critic ablation，以及真实用户 shadow 使用。
  Status: STOPPED_AT_GATE；负责人：Codex + 用户/产品治理；工作区：`/Users/qiu/work/futures-agent-os`；开始日期：2026-08-27；停止日期：2026-08-31。<br>
  Depends: `V1-010`。<br>
  Acceptance: 严格执行 [`MVP-RESEARCH-VALIDATION.md`](./MVP-RESEARCH-VALIDATION.md)；30 个诊断 Episode 只用于开发和冻结门槛，至少 50 个新封存 holdout Episode 用于最终评分，随后完成至少 10 次真实 shadow 研究；future leakage、无来源数字、越权工具和交易副作用均为零，Critical scenario 正确拒绝率 100%，Critic 高严重度缺陷召回率至少 95%；只有真实性与安全、智能有效性和用户价值三类门槛全部通过并记录用户/产品治理 `GO`，才可声明 MVP-R 并开始 `V1-011`。<br>
  Evidence: 2026-08-27 已使用 `gpt-5.6-terra` / `high` 完成 Phase 0 最小运行与评估契约，独立复核使用 `gpt-5.6-sol` / `high`；reviewer 多轮反例已修正，最终独立签字因 usage limit 尚未取得。任务仍为 `IN_PROGRESS`，本 Evidence 不代表 Acceptance 或 `GO`。已加入 stateless OpenAI Responses adapter、冻结 prompt、`gpt-5.6-terra` medium/high 候选配置、串行单工具循环、预算/超时/model-drift fail-closed、完整 11 工具闭合 schema、内容寻址 grounding 与 Replay。治理签名分别绑定真实数据 exact bytes/manifest/provider contract、单 Episode preflight 输入、suite/runtime 和 evaluator 事件/冻结 roster；Episode 只能从 typed PIT record 生成，逐记录强制 `available_time <= as_of`；summary/warnings 禁止数字，每个数值 claim 独立绑定 value/unit 两个 JSON Pointer；V1-010 owner authority 必须通过真实 trusted port 验证完整结果；循环只接收其签发的无副作用冻结 executor；hard-gate roster 只能从真实运行及对应签名授权生成，失败运行也必须进入失败计数，事件同时绑定 run semantic/audit digest。provider usage 强制完整 token 合计并计入 cache-write。2026-08-28 继续使用 `gpt-5.6-terra` / `high` 实现 provider-neutral 路由和 ChatGPT-session Codex App Server runner，固定官方 SDK/CLI `0.147.0`。真实探针证明 thread model `gpt-5.6-terra`、provider `openai`、零 reroute、完整 conclusion schema、精确 token usage、ephemeral/read-only/deny-all，以及 11 个冻结动态工具同时注册；唯一 server request 为 `item/tool/call`，任何内置工具 item、未知 request、多工具调用或 reroute 均 fail closed。动态 handler 只记录 typed request，工具执行仍由确定性串行 loop 与 V1-010 owner executor 掌握。订阅费用显式为 `SUBSCRIPTION_UNAVAILABLE`，以 token/turn/time 控制预算，不伪造逐调用美元成本。可复现证据见 [`MVP-R-001-CODEX-RUNNER-EVIDENCE.md`](./MVP-R-001-CODEX-RUNNER-EVIDENCE.md)。同日实现 SHFE/CZCE 官方 HTTPS 日行情与问财辅助查询的独立只读 adapter，真实探针验证 AG/CU/MA/SR 数据存在、exact raw hash、规范化与问财两个 `1.0.0` Skill；DCE 412/WAF 和 CFFEX 仅 HTTP 均未降级绕过。数据证据见 [`MVP-R-001-DATA-SOURCE-EVIDENCE.md`](./MVP-R-001-DATA-SOURCE-EVIDENCE.md)。`make check` 通过（contract `268 passed`、property `9 passed`、mypy `61` source files）。尚无冻结真实 PIT manifest/contract、30 diagnostic、50 holdout、10 shadow、冻结智能阈值或产品治理决定，因此不得勾选任务、不得声称 MVP-R、不得开始 `V1-011`。
  Latest verification: 2026-08-28 按用户批准的 retrospective sealed replay 路线，Codex `gpt-5.6-terra` / `high` 完成官方 AG/CU/MA/SR 批量数据、显式 acquisition/cutoff 分离、40-bar window、5-day sealed future、真实 V1-010 result binding 和 diagnostic runner；产品运行使用 `gpt-5.6-terra` / `medium`。正式 suite `3f8a57fcd57b3b0b4483cddfe6968b45acaed27af9c65d8b33e5871628d23775` 的 30/30 Episode 完成，21 `NO_OPPORTUNITY`、9 `OPPORTUNITY_CANDIDATE`，合计 2,149,792 tokens、平均 55,627 ms。解封后 9 个候选中 4 个五日方向一致；确定性基线 11 个中 5 个一致，Agent 与基线 28/30 相同，尚未证明正增量。scorecard digest `76460c64334d1518ed6e3d07de9af876c5932b35987dbb8aefb6e4605d5b0085` 明确 `holdout_ready=false`；独立 Critic ablation、fault injection、冻结智能阈值、50 holdout、10 shadow 和治理决定仍缺。最新 `make check` 为 contract `284 passed`、property `9 passed`、mypy `66` source files；任务继续 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Iteration 2: 2026-08-29 用户指示继续并记录 `ITERATE`。确定性代码预取 historical/L0/L1，`gpt-5.6-terra` / `medium` 只用一回合生成 hypothesis report；独立 Critic 按 hypothesis family 解释正/反向准确率、stress、counterfactual 与 market state。冻结 diagnostic suite `5cd69c3d851f71c356c0e569e20b2e6f0fa49ef0e6a0aac4426b4011e043c642` 完成 30/30；Critical refusal 4/4、Critic fault recall 60/60。Agent without Critic 为 15 候选/6 个五日方向一致，Agent + Critic 为 3/3，确定性基线为 5/2。usage 583,597 tokens、平均 25,423 ms，较 iteration 1 降约 73%；scorecard `78a78350b7fea311c87a64800121e124e7ad8ace2aab1862ffce4cfc6aa6b818` 给出 `holdout_ready=true`。holdout 阈值已在预注册协议冻结，下一步运行 50 条且不得修改同一 suite；任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Holdout: 同一冻结 suite 于 2026-08-29 完成 50 条新 holdout，49 完成、1 显式 provider 失败；Agent without Critic 35 候选/17 个五日方向一致，Agent + Critic 5/3，确定性基线 11/4。Critical 4/4、Critic fault 98/98、完成 hypothesis 49/49，平均 19,113 tokens、25,792 ms。自动 scorecard `7a4387cc1eb05711996e1a9fc0b432b1ed3324c7dd00d6e77f0362ce8cb399b9` 为 `holdout_passed=true`；由精确 ModelRun/authorization/replay/event 重建签发的 hard-gate scorecard `5ad1c431f5f2ecb599669a6b16bc7650927f6242ecf05d0cd0c2a8c83ea43658` 为 `passed=true`。10 份 future-blind shadow 报告已冻结，roster `715d72e7fd2e02f9ee3b7c11b62209e7495c220cdf67711ada9ea8f44dbc1a69`；最终 `make check` 通过（contract `286 passed`、property `9 passed`、mypy `66` source files），`git diff --check` 通过。只剩用户逐项评价和最终治理决定，任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Iteration 3: 用户无法直接理解 iteration 2 Shadow，并取得另一个 AI 的下游 LLM 评审；该评审不作为真人价值评分，但有效证明现有报告不能无歧义实例化实验。用户于 2026-08-29 批准最后一次 `ITERATE`。Codex `gpt-5.6-terra` / `high` 正在实现确定性 `mvp-r.machine-handoff.v1`，产品模型仍为 `gpt-5.6-terra` / `medium`。新契约显式绑定窗口、单位、成本、换月、统一方向证据、Critic 门槛、非交易标志和完整下一实验请求；positive-fold 改为真实三段顺序净结果覆盖度，不再复制准确率。新 suite revision 3 的 diagnostic/holdout 均未完成，旧 Evidence 不覆盖；任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Iteration 3 diagnostic/repair: 首次 suite `c8717433edf79e332022247793dfbbf058c94662a6bda6df7c0be453e3bfbf07` 完成 28/30，1 个 Critical provider failure、1 个唯一 pointer 标点错误，Critical 3/4，因此 scorecard `821ea3f3d89b52fcc0a0158d9879a23ded4b6e0eff894d1aaa1d787c4411b353` 明确 `holdout_ready=false`；25/25 个成功非 Critical handoff 可 hydrate，Critic fault 56/56。现记录 `REPAIR` 而非第四次智能迭代：必需 L1 失败确定性零-token `DEFER`，claim 仅在 owner result 存在唯一 exact value+unit 时规范化 pointer；模型、Prompt、数据和门槛不变。repair suite 尚未重跑，任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Repair diagnostic: suite `e41367db3afe7f35ae13f6dd092e9c80cd175ceee0748918657ccbcdd76513c3` 为 30/30、Critical 4/4、Critic 60/60；Agent without Critic 16/5、Agent + Critic 2/2、确定性基线 8/4。26/26 个非 Critical machine handoff 可 hydrate，1 `CONTINUE_TEST`、1 `OBSERVE_ONLY`、24 `DO_NOT_ADVANCE`；平均 17,129 tokens、22,690 ms，冻结交接门槛后的 scorecard `e426d3999bf50dc081628027c74b8efc15741c214151038eaabf5bbd1d5332d2` 为 `holdout_ready=true`。同一 suite 的 holdout 随后封存失败：13 完成、37 条 `CODEX_PROVIDER_FAILED`。第二次 `REPAIR` 加入最多两次瞬时失败退避后，diagnostic suite `4c7a956d7696b01258cdd6a1ad1c20482114cc26edd62e19c96c945721d7a48a` 仍失败：4/30 完成，后 26 条全部 `CODEX_PROVIDER_FAILED`。用户继续后先完成 1 条真实模型探针，Codex provider 已恢复；revision `3-repair-3` diagnostic suite `e1789aff7f92b2de3c526e0d9f08574c0008fce6e3e3978d97c9a12d7f7a05ee` 为 29/30、Critical 4/4、Critic 58/58，25/25 handoff 可 hydrate，scorecard `3f6003d52f76cfcc78317617af6ae8d5ed6f3c4b2b5dcc4141896123a7902b35` 为 `holdout_ready=true`。同一 suite 的 holdout 50/50 完成，机器交接 46/46 可 hydrate、2 READY / 42 DO_NOT_ADVANCE，但智能门槛未过：Agent + Critic 4/2 未超过确定性基线 11/5。scorecard `5b59f194a5cf3e69e4f330f8fe01f483e85e7bcc4d769fe10e57aff54759c529` 为 `holdout_passed=false`。任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Iteration 4 authorization: 2026-08-29 用户明确批准第四次智能迭代，作为对原三次预算的治理例外，将代码层 `maximum_iterations` 上限精确扩为 4。该授权不是 `GO`，不覆盖旧 Evidence，也不允许复用已查看 future reveal 的 holdout。revision 4 必须先针对“Agent + Critic 未超过最强确定性基线”完成新预注册并冻结 Prompt、角色边界、指标、roster、预算和阈值；冻结前不得运行 diagnostic，diagnostic 达标前不得生成新 holdout。实现/记录模型为 `gpt-5.6-sol` / `high`，未委托独立 reviewer；定向契约测试 37 项通过，`make check` 通过（mypy 67 个 source files、contract 292 passed、property 9 passed）。任务仍 `IN_PROGRESS`，`V1-011` 仍锁定。<br>
  Iteration 4 freeze: revision 4 已冻结为“基线约束的残差研究”；模型不得越过 family-specific accuracy/net/fold/counter-evidence gate 扩大候选，Critic 固定顺势仅 `NOISE/EXTREME_VOLATILITY/FALSE_BREAKOUT`、逆势仅 `RANGE/REVERSAL/FALSE_BREAKOUT`。最强确定性 baseline 同时修正逆势 accuracy 与 positive-fold 评分，避免弱基线假增量。suite `bc658765a8e466b15a6b6ca4c3f42222315b2480e2a7554909c8d8197fac3e12`、prompt `06bcce06fd3a040f2b85ad4f6192e17a77741a3259464f861faf7e530513c8b0`、diagnostic roster `224a6a079fcf4773ed7e9f2ef1fb2219b0d4104ecc6eb0cab3220418b01b7cb1`。新 holdout 强制排除 Iteration 3 已解封的 50 个 instrument + cutoff identity；plan-only 验证排除后仍有 118 个候选，未读取 future value、未持久化正式 roster。下一步只运行已冻结 diagnostic。<br>
  Iteration 4 diagnostic: 冻结 suite 30/30 完成，无 provider 失败。Agent without Critic 3/2、Critic 2/2、修正后的最强确定性 baseline 3/2；Critical 4/4、Critic fault 60/60、machine handoff 26/26，平均 17,236 tokens、23,094 ms。scorecard `1045ff615bbcf7bacbcc8a09a243b5da0bf321395010516838db31708c5f4c5d` 为 `holdout_ready=true`。已在查看新 future value 前冻结排除旧 50 时点的 50 条 holdout roster `969e5631f18a9d68d9bc5b17b3c629cf01378609b2f6476ebbe732724c866cf0`；下一步只运行该 holdout，不得修改同一 suite。<br>
  Iteration 4 holdout: 冻结 roster 50/50 完成，无 provider 失败；Critical 4/4、Critic fault 100/100、machine handoff 46/46，平均 18,325 tokens、25,392 ms。Agent without Critic 与 Agent + Critic 均为 6 候选/3 个五日方向一致，修正后的最强确定性 baseline 为 16/8；两者精度同为 50%，Critic 对 Agent 也无增量。scorecard `1d1840b84f378795737b7c2ebf77abcdcfbab9d9efd751db6f8e6bcfeca8bee9` 为 `holdout_passed=false`。四次智能迭代预算已用尽；任务仍 `IN_PROGRESS`，等待用户明确 `STOP/PIVOT`，当前不是 `GO`，`V1-011` 继续锁定。<br>
  Capability Pivot: 2026-08-30 用户明确批准 `PIVOT`。新产品假设不再让 LLM 对单一 prior-close signal 做顺/逆势分类，而是由确定性代码并行验证 `MOMENTUM_CONTINUATION`、`MEAN_REVERSION`、`BREAKOUT_CONTINUATION`、`FALSE_BREAKOUT_REVERSAL`、`PARTICIPATION_CONFIRMED_TREND`、`VOLATILITY_COMPRESSION_BREAKOUT`，Research Agent 跨 family 综合，独立 Critic Agent 反证。已实现 causal family screen、family-specific baseline、封闭 schema enum/方向映射、确定性 Critic 前置门槛、独立 Critic 签名授权、严格非交易 machine handoff、critical/fault 注入、开发 runner/evaluator；期限结构/库存/新闻/宏观因无合格 PIT 输入明确不支持。开发诊断冻结为 suite `ef6e2a43afa5b461023e1ff1733bd33348382ed858b3610207ed591263d6dcd3`、双 Prompt `6c46e8cc990902369934056e6a69fad2048c7a27b52699b2d996bc4e8baa2d38` / `9e684d45600cc3f2b4638bf4b85daadb688717fa9694f2b6c5edb0e19a8eed8f`、roster `f141cfa50b91a00566fe3c741a57a0e7324778ad87adfd653c0a2d368b6c3eac`；实际实现模型 `gpt-5.6-sol` / `high`，定向契约测试 44 项通过。旧 3–8 月 future path 只作开发诊断且表现只能 descriptive；最终 sealed forward holdout 强制使用 2026-08-30 之后新产生并按时采集的数据。任务仍 `IN_PROGRESS`，不是 `GO`，`V1-011` 继续锁定。<br>
  Pivot development result: suite 30/30 artifact 中仅 13 完成，第 16 条起连续 15 条被旧 adapter 折叠为 `CODEX_PROVIDER_FAILED`；Critical 4/4、fault 26/26、handoff 13/13，scorecard `f440d2f542b84dde5ccd2ee1f961f41234f5fee0edfd874038384faa1d50cf11` 为 `development_diagnostic_passed=false`。同一时段小输入同 schema 的官方 App Server 可成功，确认至少存在 adapter 把 transport 与 response-contract failure 混为瞬时 provider failure 的可观测性缺陷。用户指示继续后，仅修失败分类且不改 Prompt/数据/floor，repair suite `6a38e42255b9c24bb94106058d8121e832df18aebf4f68ba85901895ede2378d`、roster `a346a8f95c6f7a2ba989bf38b589da62e5811bae85b74c72b5002c58d547163d` 已冻结；下一步只运行隔离 probe。旧失败 Evidence 不覆盖，任务仍 `IN_PROGRESS`。<br>
  Pivot grounding diagnosis: 分类 repair probe 返回 schema-valid FINAL 与 usage，loop 的真实稳定失败码为 `UNVERIFIED_CLAIM_EVIDENCE`，不是 provider outage。observability-only suite `9610be30d74e9fd5acacdd16149f0776800c5b2630ec9874093c19e59e3ff7fe` 仅把失败 turn 的结构化 conclusion 写入审计 artifact 以定位 exact JSON Pointer；Prompt、数据、floor、Critic 和 evaluator 均不变。下一步仍只运行单条 probe。<br>
  Pivot parser diagnosis: 后续 probe 在 hydration 前返回 response-contract failure，现以非敏感 allowlisted bucket 细分 parser exception；suite `9cadae7a28e4458ee7c37a4fc80fd94dd2a301b39f08157d1712a49e0bdd0155` 已冻结，下一步只运行单条分类 probe，仍不修改研究语义。<br>
  Pivot wire repair: 分类 probe 确认为 `CODEX_RESPONSE_NUMERIC_GROUNDING`。Pivot profile 现绑定独立 no-digit/non-numeric-claim structured schema，领域 grounding 未放宽，旧通用 schema 不变；suite `cb7b355c78b737780ab0597e7d3f2027cac402aefb6ff5224a253988132757d9`、roster `4122d8b104b495048b8e7f19607f2cdac7272818795ac8414a83dbb1abff065b` 已冻结，下一步只运行单条 wire-repair probe。<br>
  Pivot wire-repair probe: 单条真实 Research 已完成，2/2 fault 捕获，无 provider/parse/grounding failure；现只允许运行同一 suite/roster 的完整 development repair。<br>
  Pivot development repair result: 冻结 suite `cb7b355c78b737780ab0597e7d3f2027cac402aefb6ff5224a253988132757d9` 已 30/30 完成，Critical 4/4、fault 60/60、handoff 30/30；machine decision 为 1 `CONTINUE_TEST` / 25 `DO_NOT_ADVANCE` / 4 `DEFER`，independent Critic 5 次为 4 VETO / 1 ACCEPT、零失败。平均 20,867 tokens、22,639 ms；scorecard `72068447e1e7335b52ec0acd6fab030801e5a61f7f43d6cb46ac51a09e4a81ab` 为 `development_diagnostic_passed=true`。`make check` 全绿（mypy 70、contract 299、property 9），`git diff --check` 通过；实现模型 `gpt-5.6-sol` / `high`，产品模型 `gpt-5.6-terra` / `medium`。旧 future 表现只作 descriptive，最终 `forward_holdout_ready=false` 仍由 post-Pivot 新数据尚不存在阻塞；不是 `GO`，`V1-011` 继续锁定。<br>
  Pivot forward protocol: 已在任何 post-Pivot reveal 前冻结 `mvp-r.pivot-forward.v1` 与最终智能门槛。collection/roster/evaluator authority 分离；每日四品种形成签名 acquisition chain，40-bar commitment 不含 label，少于 50 条不能冻结 roster，evaluator 只能读取 cutoff 后连续五个签名交易日。同日 commitment 入口只接受 chain tip 并拒绝跨上海自然日倒签；采集入口也拒绝跨过未签名工作日，休市必须另有 closure attestation。改签名、跳 label、提前 available 和 late commitment 均 fail closed。四品种理论下限为 13 个完整新交易日形成 50 条，再等待最后一批 5 个交易日；2026-08-30 plan-only 为 0 acquisition / 0 commitment，首个候选日 `2026-08-31`，future reveal 锁定；roster plan-only 为 0/50、`FEWER_THAN_FIFTY_COMMITMENTS`、未读取 future。实现模型 `gpt-5.6-sol` / `high`，定向反例 3 项；最终 `make check` 全绿（mypy 71、contract 302、property 9），`git diff --check` 通过。任务仍 `IN_PROGRESS`，下一步是逐日官方采集，不是继续 Prompt repair。<br>
  Pivot forward live status: 2026-08-31 00:00（Asia/Shanghai）expected next weekday=`2026-08-31` 且 eligible=true，但当日日线尚未产生，故保持 0 acquisition / 0 commitment、`OFFICIAL_DAY_NOT_YET_ACQUIRED`，没有网络或持久化副作用。已建立工作日收盘后继续的 heartbeat `MVP-R forward 日采集`，只在四品种完整、日期连续且仍可同日 commitment 时写入；失败保持链不变。<br>
  Retrospective confirmation authorization: 2026-08-31 用户授权不等待 18 个真实交易日，由 Codex 使用历史数据作出判断。真正 forward 保留为后续确认，但不再唯一阻塞本次 Gate。已新采集从未参与开发的 2025-01-02 至 2025-06-30 官方数据，SHFE/CZCE 各 117 日、四品种共 468 条，summary `4b9ad877ed35e08d8b917b9f460af3b0440f531d81717d59583abf8a415a9ed1`。未读取 future value 的 plan-only 已冻结 suite `8485bc807c6c50ca781c906998742796cf14e76d3d05f870224c58039bfc09c7`、50 条 roster `374730d6e4ffbf1fd02b293be4b70b86b8511d0dc4835d7971bd69200f33c842`、runtime `12382e9db1259678253112c02f34d9e733aca8aefe865376de43cf488f0c4dc9` 和原双 Prompt。Evidence 必须标为 retrospective，下一步只运行该冻结 holdout。<br>
  Retrospective evaluator freeze: 在产品运行与 label reveal 前冻结独立评分入口 `scripts/summarize_mvp_r_pivot_holdout.py`，SHA-256 `74e15fb3e2cb0422a4bbf6519cdd27ae0efe3802d67131aa99e11efc8203e757`；Agent without Critic 固定为通过确定性 floor、尚未经 independent Critic 的候选，且沿用全部预注册门槛。<br>
  Retrospective confirmation result and governance decision: 冻结 suite 完整运行 50 条，45 完成、5 条因模型非数值 metric pointer 无法解析为 owner evidence 而显式 `UNVERIFIED_CLAIM_EVIDENCE`；Critical 4/4、fault 90/90、完成 hypothesis/handoff 45/45，Critic 19 次为 17 VETO / 2 ACCEPT。解封后 Agent without independent Critic 为 19/9、Agent + Critic 为 2/1、最强 family baseline 为 21/10；点估计满足精度比较，但完成数低于 49、候选少于 3，平均 25,026 tokens 超过上限 26，平均时延 24,050 ms。scorecard `751631cbab3da76732f6fd12d3345d2a910859f9dbf70e54de8b4cfcb9f24048` 为 `retrospective_confirmation_passed=false`。依据用户授权由 Codex 判断，现记录 `STOP_CURRENT_CAPABILITY`：不进入 Shadow、不是 `GO`、`V1-011` 继续锁定；同一已解封 holdout 不得 repair/replay，未来只有新能力 Pivot 才能另建 suite。<br>
  Forward collection paused: 当前能力停止后，工作日 `MVP-R forward 日采集` heartbeat 已改为 `PAUSED`，保留配置但不继续采集；只有未来明确授权并预注册的新能力 Pivot 才能评估恢复。<br>
  Final verification: 停止记录后 `make check` 全绿（mypy 71 source files、schema 2、unit 1、property 9、contract 302，Ruff/secret/health 通过），`git diff --check` 与 scorecard digest 复验通过。实现、判分和治理模型为 `gpt-5.6-sol` / `high`，产品运行模型为 `gpt-5.6-terra` / `medium`，未委托独立 reviewer。<br>
- [ ] `MVP-R-002` 验证“确定性候选筛选 + Agent 反证与实验设计 + 独立 Critic”的研究简报产品任务。
  Status: STOPPED_AT_GATE（RESCOPED）；负责人：Codex + 用户/产品治理；工作区：`/Users/qiu/work/futures-agent-os`；开始日期：2026-08-31；停止日期：2026-09-01。<br>
  Depends: `V1-010`；`MVP-R-001` 已记录 `STOP_CURRENT_CAPABILITY`。<br>
  Acceptance: 严格执行 [`MVP-R-002-PREREGISTRATION.md`](./MVP-R-002-PREREGISTRATION.md)。确定性代码独占候选、family、方向、数值和资格真值；Agent 只生成支持/反证/未知与可实例化研究实验，不能升级确定性拒绝、复算数字或产生交易对象。先完成 30 条 diagnostic 并冻结 exact suite，再一次性运行 50 条新 sealed holdout，至少 49 条无人工修复完成；Critical 4/4、grounding/权限/交易副作用硬门槛、artifact hydrate、deterministic-action congruence 和 READY experiment instantiation 必须达到预注册阈值，Critic fault recall 至少 95%，平均 token 不超过 20,000、时延不超过 35 秒。自动门槛通过后完成 10 次 Deterministic Template 对 Agent + Critic 的真实用户盲测，Agent 至少被偏好 7/10、价值 7/10、省时 5/10、促成明确动作 3/10；只有用户/产品治理明确 `GO` 才完成任务并解锁 `V1-011`。方向收益、五日涨跌、PnL、Sharpe 或胜率不是本任务门槛。<br>
  Evidence: 2026-08-31 用户连续两次明确“批准”，授权新的能力 Pivot。已使用 `gpt-5.6-sol` / `high` 完成任务级预注册，文档 SHA-256 `c0e8c257f0d3b1386804f5cdc96d045da23f0b06f3896fe709c563e236033d48`；冻结产品任务、确定性 authority、最强模板基线、Critic ablation、旧 Episode 隔离、30 diagnostic / 50 holdout / 10 A/B shadow 阶段、自动门槛、用户价值门槛和 sealed holdout 后无 repair/iterate 的停止规则，未委托独立 reviewer。当前没有 suite、Prompt、roster 或数据 freeze，不得直接运行 diagnostic/holdout/shadow；下一步只实现 Phase 0 typed artifacts、反例测试、模板、runner/evaluator 和非技术 renderer。预注册更新后 `make check` 全绿：mypy 71 source files、schema 2、unit 1、property 9、contract 302，Ruff/secret/health、`git diff --check` 和预注册 digest 复验通过。<br>
  Receipt-lineage implementation Evidence: foundation/runtime 首轮由 `gpt-5.6-terra` / `high` 实现；lineage 与五轮修复由 `gpt-5.6-sol` / `high` 实现。最初因 Terra 使用额度不可用按策略升级到 Sol；额度恢复后由同一 Sol/high owner 连续完成安全关键修复。独立 `gpt-5.6-sol` / `xhigh` 已连续五次给出 `REJECT_RUNTIME_SLICE`；第五次最终消息被平台拦截，但 reviewer 已确认同一 sole/atomic P1 的三条 reflection-level 复现：registry completed pending flag 可写、orchestrator name-mangled 对象图可取回 executor/lease/port/assets、adapters 仍可直接构造 R-002 Codex provider。前五次 REJECT 均保留为历史 Evidence。第五轮修复删除 registry 全部 pending/completed flag并以 slots 阻断属性注入，public add/constructor 对 completed receipt 永久拒绝，唯一 atomic API 验证 exact receipt + MODEL_OUTPUT + RESEARCH_RUN/CRITIC_RUN 后在隔离 clone 直接插入 completed receipts并完成语义验证；orchestrator 实例只持 opaque id和公开业务方法，executor/lease/transport/assets/issuer/state 全在 factory closure，module 无 executor symbol且属性遍历不能取回能力；adapters package 不再导出 `CodexAppServerProvider`，仅保留通用 `CodexGenericModelProvider`，R-002 adapter和单次lease只在orchestrator closure内。FAILED receipt 与 zero-token DEFER 独立路径、前三轮 family/trust-root/cross-proof/exact wire/usage/evaluator 等约束保留。实现者回归包含四个 reviewer 反例，production-shaped synthetic 三 workload E2E 与 research/critic atomic batch 继续通过。第六次独立 `gpt-5.6-sol` / `xhigh` 验收结论为 `ACCEPT_RUNTIME_SLICE`，P0/P1/P2/P3 均为 0；R-002 五文件 69 passed，`make check` 通过（ruff format/check、mypy 74 个 source files、secret scan、schema compatibility 2、unit 1、property 9、contract 367、health），`git diff --check` 通过。按当前威胁模型，任意同进程代码主动反射 Python function closure 不是 authority boundary，因此作为非阻断 hardening note；未来可用进程隔离或不可反射 capability container 继续收紧。该 ACCEPT 仅覆盖 runtime receipt-lineage slice；整体任务仍 `IN_PROGRESS` / `AUTHORIZED_NOT_FROZEN`，真实最小 capability probe 与可信 `FROZEN` Evidence 未完成，未运行 diagnostic、holdout 或 shadow，不等于 Phase 0/`MVP-R-002` 完成或整体主链成立。<br>
  Stop/Rescope Evidence: 2026-09-01 最小真实 capability probe 已产生失败 Evidence：仅尝试首个 `research.hypothesis_synthesis` workload，`provider_turn_started_count=0`、`provider_response_observed_count=0`，状态为 `NOT_QUALIFIED_MINIMAL_CAPABILITY_PROBE_ONLY`。同日产品复核确认当前实现主要验证封闭研究简报与 runtime 治理，尚未验证 Agent 提出新 Hypothesis、实际执行实验并根据结果改判；用户明确确认停止并重定向，不继续 qualification、diagnostic、holdout 或 shadow。现有代码、测试、runtime slice 与失败 probe 全部保留，不构成 `GO`，也不解锁 `V1-011`。<br>
- [ ] `MVP-R-003` 验证“真实 PIT 证据 → 2–3 个可执行 Hypothesis → 独立 Critic → 真实 L0/L1 实验 → 结果反馈 → ACCEPT/REJECT/MODIFY/NEED_MORE_DATA”的同步研究闭环。
  Status: STOPPED_AT_GATE（R-003 v1 测量方案失败；不是多 Agent 产品失败判定）；负责人：用户/产品治理 + Cursor；工作区：`/Users/qiu/work/futures-agent-os` 当前 checkout；授权日期：2026-09-01；开始日期：2026-09-01；停止日期：2026-09-01。<br>
  Depends: `V1-010`；`MVP-R-001` 与 `MVP-R-002` 均已停止并保留历史 Evidence。<br>
  Acceptance: 严格执行 [`MVP-R-003-VERTICAL-SLICE-PLAN.md`](./MVP-R-003-VERTICAL-SLICE-PLAN.md)。先稳定当前未提交工作区，再实现同步、非交易 vertical slice；固定 8 个 AG/CU/MA/SR 历史 PIT Episode，至少 7/8 无人工修复完成、至少 6/8 产生可执行 Hypothesis、全部被选实验 100% 实际运行，Critical 4/4、future leak/无来源数字/越权工具/交易副作用为零。FinalVerdict 必须对实验结果敏感，反证结果下错误 ACCEPT 为零；Critic 必须降低坏 Hypothesis 进入实验的比例。用户盲评完整流程相对 Single-prompt/Template 至少偏好 6/8。Discovery Gate 通过只允许另行预注册正式 eval，不等于 MVP-R `GO`，不得直接进入 `V1-011`。<br>
  Evidence: 2026-09-01 用户确认停止/重定向 `MVP-R-002`，并要求先产出可交给 Cursor 或 Grok Build 的执行方案。方案已写入 `docs/MVP-R-003-VERTICAL-SLICE-PLAN.md`，包括目标领域产物、现有 V1-010 工具复用、四臂基线、8 Episode Discovery Gate、停止规则、WP0–WP5、验证命令以及 Cursor/Grok Build 执行提示。方案编写使用当前 GPT-5 Codex 会话；宿主未向任务上下文暴露更精确的 model profile 或 reasoning effort，因此未虚构记录。方案完成后已在当前 dirty checkout 执行 WP0–WP5；未创建 baseline commit（用户禁止未经要求提交）。<br>
  WP0 Evidence: 2026-09-01 Cursor / GPT-5.6 Sol 完成当前 dirty baseline 审计与保护，reasoning effort=`NOT_EXPOSED`。基线 HEAD `d72afbeed54e83bb9bec4afdff9884a423cce0ac`；未 reset、clean、checkout 覆盖、删除、创建 worktree、提交或重跑 capability probe。capability-probe Evidence 的两个确定性 SHA-256 高熵误报改用 `.secrets.baseline` 精确值审计，scanner 仍强制全部插件且未排除 Evidence 目录；契约测试 `4 passed`。完整 `uv run pytest` 为 `402 passed, 42 skipped`；`make check` 通过（mypy 74、schema 2、unit 1、property 9、contract 392、secret scan、health），`git diff --check` 通过。可复核记录：`evidence/mvp-r-003/wp0-baseline.json`。未创建 baseline commit，因为用户明确禁止未经要求提交；任务保持未完成。<br>
  WP1 Evidence: 2026-09-01 Cursor / GPT-5.6 Sol（reasoning effort=`NOT_EXPOSED`）实现七类最小版本化 contract、内容哈希 hydrate/serialize、2–3 个不同 Hypothesis 批次约束和只判断可执行性的 deterministic validator。future result、无来源 evidence ref、不可执行 operator 和 trading request 四类 Critical 反例 fail closed；`MODIFY` 必须创建绑定原版本的新版本且同 Episode 不自动再执行。定向契约测试 `4 passed`，Ruff 与定向 mypy 通过；完整 `make check` 通过（mypy 77、schema 2、unit 1、property 9、contract 396、secret scan、health）。Evidence：`evidence/mvp-r-003/wp1-contracts.json`。尚未连接模型或运行实验。<br>
  WP2 Evidence: 2026-09-01 Cursor / GPT-5.6 Sol（reasoning effort=`NOT_EXPOSED`）实现 `MvpR003ExperimentAdapter`，薄封装并实际调用现有 V1-010 `issue_replay_tool_results`，同步执行 L0、L1、chronological walk-forward、cost/slippage stress 与 inverted-direction counterfactual；计划绑定 PIT Episode、Hypothesis、原有 `ValidationConfig` 和 code ref，结果转换为 content-addressed `ExperimentResultPacket`。真实确定性 fixture 重复执行得到 byte-identical packet；新旧 replay/contract 联合测试 `397 passed`，完整 `make check` 通过（mypy 78、contract 396、secret scan、health）。Evidence：`evidence/mvp-r-003/wp2-experiment-adapter.json`。尚未连接三个模型 workload、CLI 或运行 Discovery Episode。<br>
  WP3 Evidence: 2026-09-01 Cursor / GPT-5.6 Sol（reasoning effort=`NOT_EXPOSED`）实现 hypothesis generation、independent Critic、result feedback 三个无工具 structured workload，固定 schema/预算，校验模型、实际 effort、usage、activity 和 grounded Critic refs，并保留每次 request/response receipt。测试证明反证结果会把同一 Hypothesis 的 verdict 从 `ACCEPT` 改为 `REJECT`。真实最小 smoke 前两次因请求 `medium` 但 provider 报告 `xhigh` 而 fail closed；第三次用精确 `gpt-5.6-terra` / `xhigh` 成功生成 2 个不同 Hypothesis，无工具活动，receipt `f1644fb6bb8e42239098932cc8751926fddc83c3ec94895055963d51ced1eb7c`。定向测试 `8 passed`，完整 `make check` 通过（mypy 79、contract 396）。Evidence：`evidence/mvp-r-003/wp3-model-workloads.json`。真实 Critic/final-feedback 留待 Discovery runner。<br>
  WP4 Evidence: 2026-09-01 Cursor / GPT-5.6 Sol（reasoning effort=`NOT_EXPOSED`）新增 `run_mvp_r_003_demo.py` 与 episode reporter。默认 fixture 模式完全离线、model receipt 为零，并显式标记 `FIXTURE_RENDER_ONLY`，不能冒充 Discovery；只有 `--execute-model` 才允许隔离模型调用。JSON/Markdown 报告校验 selected Hypothesis → plan → complete result packet → FinalVerdict lineage，并并列实验前判断、Critic、确定性结果、实验后改判和限制。方案列出的 demo 命令成功生成 `evidence/mvp-r-003/demo/fixture-episode-001.{json,md}`；CLI/report/replay 测试 `5 passed`，完整 `make check` 通过（mypy 80、contract 396）。新 Evidence 的 12 个 digest 高熵命中经精确值审计加入 baseline，未排除 Evidence 或弱化插件。Evidence：`evidence/mvp-r-003/wp4-cli-reporting.json`。<br>
  WP5 Evidence: 2026-09-01 Cursor / Grok 4.6（reasoning effort=`NOT_EXPOSED`）冻结 8 个 AG/CU/MA/SR PIT Episode 并跑完四臂 Discovery。无 Critic 臂 8/8 实际执行 L0/L1/walk-forward/stress/counterfactual；完整臂因 independent Critic 对 16 个可执行 Hypothesis 全部 `DEFER/REJECT` 而未实验，保留为 `NO_EXPERIMENT_CRITIC_SELECTED_NONE`。无人工修复完成 5/8，低于 7/8；Single-prompt 与 Template verdict 8/8 一致。用户盲评未开始。v1 runner 将 Gate 写死为 `STOP/PIVOT`。方案 §13 复验：定向 R-003 测试 9 passed；demo fixture 输出 `FIXTURE_RENDER_ONLY`；`--summarize-only` 复写 scorecard；`uv run pytest` 为 `411 passed, 42 skipped`；`make check` 通过（mypy 80、schema 2、unit 1、property 9、contract 396、secret scan、health），`git diff --check` 通过。Scorecard：`evidence/mvp-r-003/discovery/scorecard.json`（保留原样，不改写成通过）；WP5 Evidence：`evidence/mvp-r-003/wp5-discovery.json`；本地逐例报告：`datasets/mvp-r-001/runs/mvp-r-003-discovery/`。<br>
  Product interpretation Evidence: 2026-09-01 用户判定 v1 为测量方案失败，不能据此判定多 Agent 产品失败。已核实：模型只看到 `market_state` 与哈希引用，候选空间为单算子/单阈值/两方向；Critic 未收到 validator 已确认的窗口/成本/样本/fold/PIT 协议；Gate 在 `write_discovery_summaries` 写死 `STOP/PIVOT`，clean retention 用 `SELECT/全部 executable` 代替金标；schema 允许 `net_directional_mean` 而 ResultPacket 实际是 `signal_accuracy`/`proxy_net_return`/`stressed_net_return`；Template 与 Single-prompt 共用同一模板 Hypothesis 与 ResultPacket。不对 v1 完整臂做用户盲评。后继任务为 `MVP-R-004`。授权记录：`evidence/mvp-r-004/authorization-2026-09-01.json`。<br>
- [ ] `MVP-R-004` 修复 Discovery 测量方案，使完整研究闭环能被公平测量，而不是把产品收缩为“确定性系统 + LLM 解释器”。
  Status: STOP/PIVOT；负责人：用户/产品治理 + Cursor；工作区：`/Users/qiu/work/futures-agent-os` 当前 checkout；授权日期：2026-09-01；开始日期：2026-09-01；停止日期：2026-09-02。<br>
  Depends: `MVP-R-003` v1 Evidence 全部保留。<br>
  Acceptance: 严格限时测量修复，不恢复 30/50/shadow，不解锁 `V1-011`。必须同时满足：(1) 保留全部 R-003 v1 Evidence，不覆盖、不改写成通过；(2) Research 与 Critic 共用带真实数值的 `ResearchEvidenceBundle`，不得只给 `market_state` 和哈希引用；(3) Critic 必须收到确定性 validation/protocol 摘要，包括成本、样本、fold、embargo、PIT 和 multiple-testing budget；(4) direction/control/primary metric 与 ResultPacket 实际字段语义一一对应；(5) 用预注册金标 clean/bad Hypothesis 集合计算 Critic retention/recall，不得用 `SELECT/全部 executable` 代替金标；(6) Discovery Gate 按真实指标计算，禁止写死判定；(7) 先跑两个已知 clean 的 canary Episode，完整臂必须 2/2 完成 `Critic SELECT → 真实五项实验 → Result Feedback`；canary 未过不得冻结新 8 例、不得盲评；(8) canary 通过后再冻结新版并跑全新 8 例，然后才做用户盲评。禁止对当前 R-003 v1 完整臂做盲评。第二轮修复后若仍出现 Agent 只能产生模板变体、Critic 对金标 clean 大量误杀、完整流程盲评不优于 Single-prompt、或 Critic 未降低已知坏假设进入实验的比例，再正式 Pivot。<br>
  Evidence: 2026-09-01 用户批准小型测量修复，明确不批准正式 eval 与 `V1-011`。授权记录：`evidence/mvp-r-004/authorization-2026-09-01.json`。同日 Cursor / Grok 4.6（reasoning effort=`NOT_EXPOSED`）在当前 dirty checkout 实现 `ResearchEvidenceBundle`、`ValidationProtocolDigest`、packet 实际字段映射、金标 clean/bad 与计算型 canary Gate；产品模型 research/feedback=`gpt-5.6-terra`/`xhigh`、critic=`gpt-5.6-sol`/`xhigh`。冻结 canary roster SHA-256 `b1b0ec9b1a7ec7b6480a0d70b0be07fe7bf79b7285c64ce668f9d84f8cad8f5a` 后跑通两例：`r004-canary-ag-uptrend`、`r004-canary-sr-false-breakout`。Gate 计算得出 `CANARY_PASS`（`hardcoded=false`）：完整臂 2/2 完成 Critic SELECT → 五项实验 → Result Feedback；金标 clean retention 2/2 SELECT，bad recall 2/2 REJECT，坏假设进入实验 0。R-003 v1 `evidence/mvp-r-003/discovery/scorecard.json` 仍为 `STOP/PIVOT`。scorecard 体积过大的 40-bar 包只留在 gitignored `datasets/mvp-r-001/runs/mvp-r-004-canary/`；Evidence 目录未排除扫描，roster/scorecard 的 SHA-256 高熵命中按精确 hashed value 审计进 `.secrets.baseline`。完整 `uv run pytest` 为 `416 passed, 42 skipped`；`make check` 通过（mypy 89、schema 2、unit 1、property 9、contract 401、secret scan、health），`git diff --check` 通过。Canary Evidence：`evidence/mvp-r-004/canary/scorecard.json`、`evidence/mvp-r-004/wp-canary.json`。<br>
  Discovery Evidence: 2026-09-01/02 同一执行器冻结与 v1 不同 cutoff 的 8 例 roster SHA-256 `afdd4b24b7e78af33e5913f5aafbb213567e86872a84955fcb199797ae674567`，并跑完四臂 Discovery。无人工修复 8/8；可执行 Hypothesis 8/8；无 Critic 臂实验 8/8；完整臂 8/8 均完成第一个 Critic SELECT 的五项实验与 Result Feedback（15 个 SELECT 决策中每例只实例化第一个，不自动跑其余）。金标 clean retention 8/8 SELECT，bad recall 8/8 REJECT，坏假设进入实验 0。Gate 计算得出 `DISCOVERY_PASS`（`hardcoded=false`）。Template 与 Single-prompt 仍 8/8 同判；`r004-sr-extreme` 的无 Critic 臂为 `NEED_MORE_DATA`，其余三臂为 `ACCEPT`。R-003 v1 仍为 `STOP/PIVOT`。完整 `uv run pytest` 为 `417 passed, 42 skipped`；`make check` 通过（mypy 89、contract 402）。Discovery Evidence：`evidence/mvp-r-004/discovery/scorecard.json`、`evidence/mvp-r-004/wp-discovery.json`。<br>
  User Blind Evidence: 2026-09-02 产品负责人在 Codex 生成的中文对照上逐例确认 8 例盲评（打分前未打开 `blind-mapping.json`）。评估人记录为 `product_owner_assisted_by_codex`，**不是**独立真实用户验证。完整流程被偏好 1/8（仅 `r004-ma-downtrend`），无 Critic 臂 5/8，Single-prompt 2/8，Template 0/8。无需额外解释可理解 7/8，明显省时 8/8，促成明确动作 8/8。用户价值门槛 `USER_VALUE_FAIL`；机器 `DISCOVERY_PASS` 未改写。第 4 例映射复核：用户偏好的 B 是无 Critic 臂，原文写同向延续；A 是 Single-prompt，实验后写成 INVERT。第 8 例用户偏好无 Critic 臂的 `NEED_MORE_DATA`，完整臂把 `positive_fold_ratio` 当成各段命中率门槛并给出 `ACCEPT`。金标路径 Critic 仍 8/8 留 clean、8/8 拒 bad。Evidence：`evidence/mvp-r-004/discovery/user-blind-eval.json`。<br>
  Product Pivot Evidence: 2026-09-02 产品负责人确认 `STOP/PIVOT`。**拒绝**“删掉 Agent、只留确定性引擎”。**确认**方向为单 Research Agent + 确定性实验闭环；Critic 降为可选、非阻断的影子质检。强制多 Agent 主路径停止，Agent 研究闭环保留。后继任务 `MVP-R-005`。授权记录：`evidence/mvp-r-004/product-pivot-2026-09-02.json`、`evidence/mvp-r-005/authorization-2026-09-02.json`。<br>
- [x] `MVP-R-005` 把研究主路径改成决策简报：单 Research Agent 提出有界假设，确定性 validator 与工具完成实验，Agent 给出 `ACCEPT / REJECT / NEED_MORE_DATA / MODIFY`；Critic 只做影子质检。
  Status: COMPLETED；负责人：用户/产品治理 + Grok Build/Codex；工作区：`/Users/qiu/work/futures-agent-os` 当前 checkout；授权日期：2026-09-02；开始日期：2026-09-02；完成日期：2026-09-02。<br>
  Depends: `MVP-R-004` 已确认 `STOP/PIVOT`，且 Pivot 方向不是删掉 Agent。<br>
  Acceptance: 不恢复 30/50/shadow，不解锁 `V1-011`。必须同时满足：(1) 主路径没有实验前强制 Critic 门卫；(2) Research Agent 提出有界假设；(3) 确定性 validator 拦截非法算子、缺失指标和方向错配；(4) 确定性工具实际执行实验；(5) Research Agent 输出 `ACCEPT / REJECT / NEED_MORE_DATA / MODIFY`；(6) 用户报告只保留四块：测了什么、结果怎样、当前判断、下一步动作；(7) Critic 若运行，只能在 shadow 中记录风险提示，不得阻断实验；(8) 用新 8 例比较“单 Agent 闭环”与 Single-prompt，Single-prompt 作为基线或降级方案，Template 不是产品；(9) 若证伪条件要求分段命中率，ResultPacket 必须给出分段 `signal_accuracy`，不得用 `positive_fold_ratio` 代替；(10) 保留全部 R-003/R-004 Evidence，不得把 R-004 机器 `DISCOVERY_PASS` 或协助盲评宣传成 `GO` 或独立真实用户验证。<br>
  Evidence: 2026-09-02 用户下令开始。执行器 Cursor Grok 4.6，reasoning effort=`NOT_EXPOSED`；产品模型 research/feedback=`gpt-5.6-terra`/`xhigh`，shadow critic=`gpt-5.6-sol`/`xhigh`。冻结与 R-003 v1、R-004 均不重叠的 8 例 roster SHA-256 `a1900210000aebffc792a94518dce7402ea250ed615f2cd143c973c3aebb7ed2`。主路径为 generate → R-004 validator → 第一个 EXECUTABLE → 五项实验 → 四块中文决策简报；Critic 只在实验后写 shadow 风险，2 例 `would_have_blocked=true` 均未阻断实验。v1 ResultPacket 把全窗信号平均切成 12/13/13 并写 `fold_1/2/3_signal_accuracy`，且未按 FOLLOW/INVERT 交换 treatment/control。v1 Gate 计算得出 `R005_PASS`（`hardcoded=false`）：8/8 完成、8/8 实验、8/8 Single-prompt、实验前 Critic 门卫 0、阻断 0、8/8 含分段命中率字段、与前序窗口重叠 0。该 Gate 只验证完成和字段存在。Agent 与 Single-prompt 在 `r005-sr-extreme` 不同判（ACCEPT vs REJECT），其余 7/8 同判。R-003 v1 仍为 `STOP/PIVOT`，R-004 仍为 `DISCOVERY_PASS` / `USER_VALUE_FAIL`。不是 `GO`，不是独立真实用户验证。授权：`evidence/mvp-r-005/authorization-2026-09-02.json`。v1 Evidence 原样保留：`evidence/mvp-r-005/roster.json`、`evidence/mvp-r-005/scorecard.json`、`evidence/mvp-r-005/wp-discovery.json`，运行产物 `datasets/mvp-r-001/runs/mvp-r-005-discovery/`。<br>
  Correction-v2 Evidence: 2026-09-02 独立复核拒绝 v1 `R005_PASS`，记录于 `evidence/mvp-r-005/reviewer-rejection-2026-09-02.json`；未改写、未删除 v1 scorecard。同一执行器 Cursor Grok 4.6（reasoning effort=`NOT_EXPOSED`）在当前 dirty checkout 实现 correction-v2：`execute_replay` 显式绑定 `HypothesisSpec`；FOLLOW 时 treatment=原始信号、control=反向，INVERT 时完整镜像；raw tool result 仍为 FOLLOW lineage。walk-forward 改用唯一 planner，`fold_N_signal_accuracy` 只按真实 OOS test indices 计算，每折 `signal_count<=test_bars=5`；缺折不合成。`minimum_samples=20` 约束全窗/train 资格，不约束 OOS（3×5 最多 15）。证伪改为版本化 typed predicate，确定性 evaluator 出 ACCEPT/REJECT/NEED_MORE_DATA；Agent verdict 必须一致，否则 fail closed。v1 路径未覆盖。新 8 例写入 `evidence/mvp-r-005/correction-v2/` 与 `datasets/mvp-r-001/runs/mvp-r-005-correction-v2/`。v2 Gate 计算得出 `R005_CORRECTION_V2_PASS`（`hardcoded=false`）：direction binding 8/8、treatment/control semantic mirror 8/8、authentic walk-forward fold manifest 8/8、fold metrics 与 manifest exact binding 8/8、verdict/predicate congruence 8/8、four-block report 8/8、pre-experiment Critic gate 0/8、Critic blocked experiment 0、predecessor overlap 0/8、predecessor Evidence 未覆盖、`not_go=true`、`independent_real_user_validation=false`。3 例因方向/真实 OOS 折数相对 v1 改判。该机器 PASS 随后被独立复核拒绝，scorecard 原样保留。<br>
  Correction-v3 Evidence: 2026-09-02 独立复核拒绝 correction-v2，记录于 `evidence/mvp-r-005/correction-v3/reviewer-rejection-correction-v2.json`。用户授权 Grok Build（reasoning effort=`NOT_EXPOSED`）在当前 dirty checkout 实现 correction-v3。raw `ToolRunResult` 不再被 FOLLOW/INVERT 覆盖；treatment-relative 指标进入 `mvp-r-005.treatment-metric-view.v1`。谓词任一 FAIL 即为 REJECT；INSUFFICIENT 不能覆盖已知失败；`AT_LEAST_N` 按可达性判断；stop 后 `REQUIRED_OOS_FOLD_COUNT` 为 FAIL。fold clause 只绑定 `signal_accuracy`/`proxy_net_return` 的真实 per-fold 字段，`stressed_net_return` fail closed。Agent 可见 view 删除被 stop 的折的标准字段、raw 字段和 manifest；完整 raw 只留 evaluator-only packet。predecessor 用 SHA-256 baseline/final manifest，`pre_v2_byte_stability=NOT_PROVEN`，`v3_predecessor_hashes_match` 由文件哈希比较。复用冻结 roster SHA-256 `a1900210000aebffc792a94518dce7402ea250ed615f2cd143c973c3aebb7ed2`。`r005-cu-extreme` attempt-1 失败 JSON 保留，不计入完成。8/8 完成后 v2 的三个 `NEED_MORE_DATA` 按规则重算为 `REJECT`。v3 Gate 计算得出 `R005_CORRECTION_V3_PASS`（`hardcoded=false`）：complete/agent loop/experiments/Single-prompt 8/8，raw tool result lineage 8/8，predicate metric binding 8/8，verdict/predicate congruence 8/8，four-block reports 8/8，pre-experiment Critic gate 0/8，Critic blocked 0，predecessor window overlap 0/8，stopped folds invisible 8/8，treatment view bound 8/8，`v3_predecessor_hashes_match=true`，`pre_v2_byte_stability=NOT_PROVEN`，`not_go=true`，`independent_real_user_validation=false`。任务仍 `[ ]` / `IN_PROGRESS`，等待独立复核。完整 `uv run pytest` 为 `452 passed, 42 skipped`；`make check` 通过（mypy 102 source files、schema 2、unit 1、property 9、contract 437、secret scan、health）；`git diff --check` 通过。未提交、未推送、未开 PR。v3 Evidence：`evidence/mvp-r-005/correction-v3/scorecard.json`、`evidence/mvp-r-005/correction-v3/wp-discovery.json`；运行产物 `datasets/mvp-r-001/runs/mvp-r-005-correction-v3/`。<br>
  Correction-v4 Evidence: 2026-09-02 Codex 独立复核拒绝 correction-v3 Gate，记录于 `evidence/mvp-r-005/correction-v4/reviewer-rejection-correction-v3.json`；复核同时重建两条臂共 16 个实际 view，全部与 correction-v3 packet/hypothesis/plan/config 一致，因此用户授权直接做 Evidence-only 修复且产品模型调用为 0。v4 对 Agent 与 Single-prompt 对称执行 exact view rebuild、direction/mirror/fold manifest/walk-forward、`agent_visible_experiment` exact binding；lineage exact coverage 并核对 mapped raw value，stop 后派生 ratio 从可见 folds重算。原 `raw_tool_result_lineage` 诚实改名为 `raw_packet_to_view_lineage`，不宣称 source-ref authenticity，未增加签名/registry/qualification。v1–v3 共 138 个受保护文件 baseline/final 完全一致。Gate 计算得出 `R005_CORRECTION_V4_PASS`（`hardcoded=false`）：complete/agent loop/experiments/Single-prompt 8/8、packet→view lineage 8/8、predicate binding/congruence 8/8、four-block 8/8、pre-experiment Critic 0/8、blocked 0、overlap 0/8、stopped folds invisible 8/8、treatment view bound 8/8、`not_go=true`、`independent_real_user_validation=false`。新增三类合法重哈希篡改测试并 fail closed；`uv run pytest` 为 `456 passed, 42 skipped`；`make check` 通过（mypy 102、schema 2、unit 1、property 9、contract 441、secret scan、health）；`git diff --check` 通过。执行器 Codex，精确 model profile/reasoning effort 均为 `NOT_EXPOSED`。后续未主导 v4 实现的 Codex 最终独立复核仍拒绝该机器 PASS：`_agent_model_input` 在 `agent_visible_experiment` 缺失、`null` 或空容器时 truthy-fallback 到 treatment view，空对象篡改后仍错误得到 view bound/lineage/complete 全 true，未证明 exact visible binding。现存 16 条臂本身均为非空 exact visible payload，Markdown/brief/verdict 也 16/16 一致，所以只需 correction-v5 Evidence-only fail-closed 修复，无需重跑产品模型。拒绝 Evidence：`evidence/mvp-r-005/correction-v5/reviewer-rejection-correction-v4.json`。任务仍 `[ ]` / `IN_PROGRESS`；不进入 30/50/shadow，不解锁 `V1-011`。<br>
  Correction-v5 Evidence: 2026-09-02 用户授权 Codex 直接实施 Evidence-only 修复，产品模型调用为 0，继续复用 correction-v3 的 16 条臂。两条臂的 `agent_visible_experiment` 现在必须显式存在、类型为非空 exact mapping，不再 fallback 到 treatment view；`DecisionBrief` 使用 closed hydrate，brief verdict 必须与 FinalVerdict 一致，Agent 与 Single-prompt Markdown 必须逐字等于确定性四块 renderer 输出。missing/null/空对象/空列表/空元组 visible、额外 H2、矛盾 Markdown、brief/final verdict 冲突均有 fail-closed 测试。v1–v4 共 143 个受保护文件 baseline/final 完全一致。Gate 计算得出 `R005_CORRECTION_V5_PASS`（`hardcoded=false`）：complete/experiments/Single-prompt 8/8、双臂 visible/view exact binding 8/8、四块 Markdown/brief/final exact binding 8/8、packet→view lineage 8/8、predicate binding/congruence 8/8、pre-experiment Critic 0/8、blocked 0、overlap 0/8、`not_go=true`、`independent_real_user_validation=false`。`uv run pytest` 为 `465 passed, 42 skipped`；`make check` 通过（mypy 102、schema 2、unit 1、property 9、contract 450、secret scan、health）；`git diff --check` 通过。执行器 Codex，精确 model profile/reasoning effort 为 `NOT_EXPOSED`。未主导 v5 实现的 Codex 随后独立核对 16 条实际产物，未发现功能缺陷；产品负责人将仅对抗主动本地 JSON 合法重哈希的 Evidence 加固降为非阻断项。独立复核 `PASS`，任务完成并勾选；仍不进入 30/50/shadow，不解锁 `V1-011`。独立复核 Evidence：`evidence/mvp-r-005/correction-v5/independent-review-2026-09-02.json`。<br>
  Formal Eval v2 Evidence: 2026-09-04 产品负责人授权使用 `gpt-5.6-sol/high`，不采用 `custom/high` 作为产品模型配置。新预注册与全新 roster 在模型调用前冻结；diagnostic SHA-256 `d7d15cd81532687512be6d16075a96d886041f9488c9f700a97bad6b722fcb15`，holdout SHA-256 `382f6a987fc2410ee3b60a4ede605c1c0c4d5d2727c1b8ecc60b08089aaad9ba`。roster 外 preflight 观察到模型 `gpt-5.6-sol`、effort `high`、宿主 provider 标签 `custom`、无工具/reroute/timeout，记录于 `evidence/mvp-r-formal-eval-v2/preflight-2026-09-04.json`。Diagnostic 运行 13/30 完成；`formal-diagnostic-013` 因不足 2 个 well-typed hypotheses 失败，`formal-diagnostic-015` 与 `016` 因 `STATUS_NOT_COMPLETED` 失败。三条失败使 29/30 不可达，按预注册停止并记录 `FORMAL_DIAGNOSTIC_FAIL`；scorecard、termination、失败 Evidence 原样保留，holdout/shadow 未启动，`V1-011` 仍锁定。实现/运行执行器 Codex，model=`gpt-5.6-sol`，reasoning effort=`high`。<br>
- [x] `V1-011` 实现基础 Experiment Manager 与异步 Research Job 状态机：预注册实验、排队、运行、部分完成、失败、取消、超时和恢复。
  Status: COMPLETE；最小闭环已验收，未启动 formal eval v3 或任何交易能力。<br>
  Depends: `MVP-R-005` 已通过 correction-v5 独立功能复核，且最小 MVP Closure Acceptance 为 `MVP_ACCEPTED`。Formal Eval v1/v2 失败保留为后续质量 backlog，不阻塞本任务启动。<br>
  Acceptance: 每个任务有算力/时间预算；结果可回流原对话；Experiment Manager 不能交易或晋升策略。  
  Evidence: [`evidence/v1-011/implementation-2026-09-04.json`](../evidence/v1-011/implementation-2026-09-04.json)。
- [x] `V1-012` 建立 Agent 研究评测集：工具选择、引用正确性、数字 grounding、反证覆盖、`NO_TRADE/DEFER` 和相同证据重放。
  Depends: `MVP-R-005` 通过，并完成正式 MVP-R eval、取得 `GO`、`V1-011`。<br>
  Acceptance: 评测集、评分规则和版本已冻结；每次模型/Prompt/Toolset 变更都会生成可比较报告。  
  Status: COMPLETE；实现、定向测试和未主导实现的 Sol/high 独立验收均通过。<br>
  Evidence: [`evidence/v1-012/implementation-2026-09-04.json`](../evidence/v1-012/implementation-2026-09-04.json)。
- [x] `V1-013` 实现 `OBSERVE` Opportunity Radar：按 ScanPolicy/UniversePolicy 或事件扫描品种宇宙，产出 `OpportunityScan` 与 `OpportunityCandidate`，并形成重要研究摘要。
  Status: COMPLETE；OBSERVE-only 最小扫描契约与独立 Sol/high 验收均通过。<br>
  Depends: `V1-011`、`V1-012`。<br>
  Acceptance: 每次扫描绑定宇宙、时点、数据/特征版本和预算；OBSERVE 的 account/mandate 可空；候选有支持与反对证据、时间尺度、去重/冷却信息和 `NO_OPPORTUNITY`结果；漏跑可补跑，且不能创建 TradePlan、Order 或账务副作用。  
  Evidence: [`evidence/v1-013/implementation-2026-09-05.json`](../evidence/v1-013/implementation-2026-09-05.json)。

Exit：`MVP-R-005` 单 Agent 研究决策简报通过，且最小 MVP Closure Acceptance 证明从用户问题或时间表/市场事件到 Hypothesis、实验结果和证据化答复的核心路径可完整重放；Critic 若存在只作为影子质检。没有任何 Order、Fill、Position 或账本副作用。Formal Eval v1/v2 仍作为独立质量记录，不再阻塞本 MVP Exit；formal evaluation reliability / quality improvement 进入后续 backlog。`MVP-R-003` v1 与 `MVP-R-004` 强制多 Agent 主路径均不得单独作为该 Exit 的通过证据。

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
- [ ] `V3-013` 建立多 Agent 自治评测与 V3 最小人工治理 Registry：机会覆盖/精度、`NO_TRADE` 纪律、不必要交易率、Mandate 遵循、通知精度、委派、handoff、冲突、预算耗尽、超时、工具/作用域错误输入和模型降级。
  Acceptance: 每个已启用 Strategy/Agent/Prompt/Model/Toolset 版本都有独立基准集和发布门槛，并经人工分离的 qualification + Activation 后才能绑定 AUTONOMOUS_SIMULATION；Mandate 遵循、数字引用、不必要交易和错误输入不产生越界业务效果达到硬门槛。对抗性 Prompt Injection/red-team 不属于当前可信本机范围的硬门槛。
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
  Acceptance: 每条证据有来源、许可、发布时间/有效时点和质量；非结构化内容只作为研究数据进入 Agent 提案，不直接成为确定性业务指令或权限。当前范围不要求独立对抗性 Prompt Injection 测试。
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
- [ ] `V5-010` 完成 SLO、容量、背压、限流、熔断、备份、恢复、灾难演练和 runbook；多用户权限审计与对抗性安全演练不在当前范围。
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
