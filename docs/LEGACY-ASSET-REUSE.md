# `futures_workflow` Donor 资产复用评估

文档版本：`2.1-proposed`  
日期：2026-08-18  
Donor 审计对象：`/Users/qiu/futures_workflow`  
目标项目：尚未创建的独立绿地项目

## 1. 定位

`futures_workflow` 不是目标项目的旧版本、运行基线、兼容层或待接管系统。它只是 donor，可提供：

- 已实现算法和代码片段；
- 解析、计算和边界条件测试；
- 合成/脱敏样本与黄金输出；
- 中国期货业务规则的实现经验；
- 已知缺陷、错误模式和反例；
- 外部工具/数据源接入经验。

目标项目不继承 donor 的数据库、账户、订单、成交、持仓、账本、通知、审批、Agent memory、任务状态或运行配置。donor 通过 256 个测试、存在某个模块或拥有历史数据，都不表示目标项目已完成相应能力。

本文件不是迁移计划。不存在兼容 facade、Strangler、双写、逐聚合切换、SQLite 主库升级或关闭旧写路径。

## 2. 强制边界

1. 新项目必须在 donor 不可访问时仍可安装、启动、测试、部署和恢复。
2. 新项目运行时不得从 `/Users/qiu/futures_workflow` 直接 import 业务模块、读取其本地配置或连接其数据库。
3. 采用的实现必须进入新项目拥有的包，或进入独立版本化、可发布且有明确所有权的库。
4. donor schema、ID、会话格式、CLI 文本和文件路径不得泄漏进新领域模型。
5. 每项复用必须由某个新项目 Roadmap 任务提出；复用本身不产生完成勾选。
6. 新契约、安全边界和点时正确性优先于保持 donor 行为；预期差异不叫回归。
7. donor 的账户/交易/学习数据默认不导入。未来若有研究价值，必须另立只读 Archive Importer 需求与审批。

## 3. 复用等级

| 等级 | 含义 | 允许方式 |
|---|---|---|
| `R1 PORT` | 边界清晰的纯函数、静态数据或渲染逻辑 | 审计后移植到新命名空间，补新契约和测试 |
| `R2 REIMPLEMENT` | 思路和测试有价值，但实现耦合旧服务、配置或类型 | 按新端口重实现，选择性移植算法和测试样本 |
| `R3 EVIDENCE_ONLY` | 目标语义不同或职责混杂 | 仅作为反例、fixture、验收场景和设计证据 |
| `R4 REJECT` | 与目标安全边界冲突 | 不进入新运行时；只记录拒绝理由 |

等级是初步建议，不是批准状态。最终资格由 `V0-013` 的逐项证据决定。

## 4. 资格门禁

每项 donor 资产只有同时满足以下条件，才能进入新项目：

- 有来源、作者/许可和原文件/commit 记录；
- 有明确的新项目 Roadmap 任务和目标包所有者；
- 输入、输出、错误、精度、时区、版本、点时和副作用契约已定义；
- 不依赖 donor 数据库、绝对路径、全局单例、硬编码目标或本机命令；
- 金额、价格、数量和 PnL 符合新项目 Decimal/定点策略；
- 行情与特征处理通过无未来数据、陈旧、乱序、缺失和规则版本测试；
- 通过许可证、凭据、依赖和静态安全扫描；
- 测试已移植到新项目，并覆盖新契约而非仅复制旧断言；
- 新项目 CI、契约测试、属性测试或黄金回放给出 Acceptance Evidence；
- 文档记录与 donor 行为的已知差异和不采用部分。

## 5. 候选资产矩阵

### 5.1 市场、合约与特征

| Donor 模块 | 初评 | 可利用资产 | 新项目处理 | 禁止继承 |
|---|---|---|---|---|
| `futures_symbol_registry.py` | R1/R2 | 品种表、别名、主连命名、健康测试 | 移植静态事实；按新 `InstrumentRegistry` 契约实现 | 本地文件路径、隐式默认合约 |
| `futures_symbol_resolver.py` | R2 | 输入归一、合约解析案例 | 按 `InstrumentResolver` 重实现并移植解析测试 | 把连续序列当可交易合约、过期合约默认通过 |
| `contract_metadata.py` | R2 | TqSdk/AKShare provider 经验和字段解析 | 实现新 `ContractRulePort` adapters | 无生效区间的永久规则、静默 fallback |
| `market_data_service.py` | R2 | 报价/K 线、fallback 和健康检查场景 | 实现新 `MarketDataPort` 和不可变快照 | 全局 API、旧缓存、无 `as_of` 数据 |
| `akshare_*`、`tqsdk_quote_runner.py` | R2 | 数据源字段、限频和异常案例 | 新 source adapters；统一错误 taxonomy | 会话格式、本机配置和 subprocess 约定 |
| `technical_indicators.py` | R1 | 确定性指标公式 | 移植纯函数，增加窗口/版本/空值元数据 | 隐式排序、未来数据、二进制浮点账本用途 |
| `kline_analyzer.py` | R2 | 趋势、形态、支撑阻力算法 | 拆为纯 feature/assessment 函数 | 大类状态、隐式字段、文本与计算混合 |
| `intraday_context.py` | R2 | 多周期摘要、盘中 gate 和辅助规则 | 作为 `MarketStateBuilder` 算法参考 | 未冻结输入和无版本 feature |

### 5.2 研究、筛选与策略

| Donor 模块 | 初评 | 可利用资产 | 新项目处理 | 禁止继承 |
|---|---|---|---|---|
| `futures_candidate_screener.py` | R2 | 池解析、结构评分、覆盖/失败解释 | 按 Research/Opportunity 用例重实现 | 直接取行情、隐式副作用 |
| `intraday_candidate_screener.py` | R2/R3 | 日内候选、去重、冷却和管线样本 | 移植规则样本；重新设计任务和状态 | scan/risk/watch/notification 混合职责 |
| `strategy_spec.py` 与策略 JSON | R2 | 规则数据化和 digest 思路 | 转为版本化 `StrategySpec` schema | 旧文件格式作为领域接口 |
| `futures_trade_setup.py` | R3 | Setup 字段和证据组织案例 | 作为 Hypothesis/TradePlan fixture | 执行、文本渲染与决策混合 |
| `watch_trigger_engine.py` | R3 | 稳定性、门禁、LLM payload 和丰富测试 | 提取边界案例与黄金样本 | 3000+ 行混合编排作为新内核 |
| `llm_router.py` | R3 | provider fail-closed、去重、费用估算案例 | 作为 ModelProvider/observability 需求证据 | 把点状路由器当 Agent Runtime |
| 外部回测证据格式 | R3 | 历史 artifact 与失败案例 | 经版本化 connector 读取 | 把会话格式或外部摘要当 BacktestRun 真值 |

### 5.3 风险、执行与账户

| Donor 模块 | 初评 | 可利用资产 | 新项目处理 | 禁止继承 |
|---|---|---|---|---|
| `position_sizing.py` | R2 | 风险/保证金双约束公式和测试 | 用 Decimal、RuleSnapshot 和稳定错误码重实现 | 未知输入默认通过、旧账户类型 |
| `account_capital.py` | R2/R3 | 账户快照、资金与加仓风险案例 | 提取公式和边界测试 | donor 余额、策略桶或状态所有权 |
| `execution_safety.py` | R2 | 新鲜度、来源、交易时段 gate | 按 ContractRule/Calendar 实现 pre-trade validation | 中国期货通用近似时段决定执行 |
| `futures_sim_trade_bridge.py` | R3/R4 | TradePlan 字段雏形和错误样本 | 仅用作契约反例和测试输入 | 直接创建 OPEN trade、触发即成交 |
| `position_management.py` | R3 | 分层止盈止损、加减仓和修订测试 | 提取 Protection 场景和属性测试 | 直接改仓、任意放宽止损、轮询状态所有权 |
| `execution_quality.py` | R1/R2 | 计划价/成交价偏差统计 | 以新 Fill/MarketSnapshot 为输入移植 | 从旧 trade row 推断成交真值 |
| `db_manager.py` | R3/R4 | 查询用例、表关系和故障样本 | 仅用于识别需求、测试数据规模和反例 | 旧 schema、内联 ALTER、repository/ledger 混合实现 |
| `trade_events`、`position_ledger` | R3 | 审计字段和历史错误模式 | 作为 event/ledger schema 测试素材 | 把旧事件或流水导入为新权威事实 |

### 5.4 复盘、实验、治理与交互

| Donor 模块 | 初评 | 可利用资产 | 新项目处理 | 禁止继承 |
|---|---|---|---|---|
| `notification_inbox` | R2 | outbox、去重和投递状态思路 | 实现新 inbox/outbox/lease/retry | 固定飞书目标和本机命令 |
| `daily_review.py`、`weekly_review.py` | R2/R3 | 报表口径、人工可读结构和测试 | 从新投影读取，保留部分 renderer | 复盘代码写业务状态 |
| `trade_kline_review.py` | R2 | 图表和过程诊断 | 作为 Reviewer Tool 算法参考 | 自动把诊断晋升为 Lesson |
| `post_exit_review.py` | R1/R2 | T+1/T+3/T+5 观察方法 | 使用新交易日历和 OutcomeQuality | 旧 trade ID 或自然日假设 |
| `unexecuted_setup_review.py` | R2 | 机会成本和未执行样本 | 实现 Counterfactual Evidence | 无 Hypothesis/Plan lineage 的结论 |
| `review_action_items.py` | R2 | 来源、负责人、期限和证据字段 | 映射到新 Governance Task | donor 任务状态 |
| `experiment_strategy_pool.py` | R2/R3 | 版本、stale、时间窗和审批案例 | 作为 Strategy Registry 需求与 fixture | 外部摘要直接晋升策略 |
| `strategy_experiment_service.py` | R3 | 反事实和幂等测试场景 | 使用新 Experiment/Backtest 引擎重做 | 旧会话/账本语义 |
| `improvement_governance.py` | R2/R3 | 提案和分级审批思想 | 实现新 ChangeProposal/Activation | donor 审批记录作为新授权 |
| `development_task_runner.py` | R3 | 隔离工作区和验收卡经验 | 仅供研发流程设计参考 | 与业务数据库或运行身份共享权限 |
| `interactive_chart_report.py` | R1/R2 | 离线 HTML/SVG 和渲染逻辑 | 移植 renderer，增加 artifact manifest/hash | 绝对路径与隐式数据读取 |

## 6. 明确拒绝的行为

### 6.1 触发即成交

Donor 中参考价或最新价直接形成 OPEN/CLOSED 记录的行为不得进入目标实现。新系统只有以下链路能改变持仓：

```text
TradePlan → AuthorizationBasis（有效 Mandate 或可选逐 Plan Approval）
→ PositionSizing → RiskBudgetReservation → AutonomyGateReceipt
→ RiskDecision → ExecutionPlan
→ Order → FillModel/Matcher → Fill → Ledger/Settlement → Position
```

### 6.2 无法计算风险时继续交易

保证金、规则、价格、数据质量或最坏损失不可计算时，只能继续只读研究，不能产生新风险。

### 6.3 放宽既定风险边界

删除止损、扩大止损、提高 `max_loss` 或借已实现盈利扩大原始风险必须拒绝；如要提出新的风险意图，必须生成新 TradePlan，重新取得有效 `AuthorizationBasis` 与 `AutonomyGateReceipt`，并仍受 Risk Constitution 硬上限限制。

### 6.4 近似规则决定执行

通用交易时段、静态保证金或永久手续费只能用于提示或测试，不能决定正式模拟或历史验证。

### 6.5 硬编码外部目标与本机命令

固定飞书 chat/user、token、绝对路径、`openclaw` subprocess 或个人机器配置不得进入新运行时。

### 6.6 让 LLM 输出成为数字真值

模型文本不能成为价格、PnL、保证金、余额、仓位、成交、规则或结算来源；只能引用版本化工具结果。

## 7. 采用流程

1. 新项目 Roadmap 任务识别一个具体 donor 候选，说明采用它能降低什么风险或成本。
2. 先定义新领域/端口契约、Acceptance 和失败场景，不以 donor API 反推目标设计。
3. 建立新项目测试；可移植 donor fixture，但必须说明来源和修改。
4. 对 R1 执行最小移植，对 R2 独立重实现，对 R3 只提取证据，对 R4 禁止进入运行时。
5. 运行静态、安全、许可证、契约、属性、点时和集成测试。
6. 记录 donor 文件/commit、新文件、采用/拒绝范围和行为差异。
7. 只有整体 Roadmap 任务满足 Acceptance，才可在 `ROADMAP.md` 勾选；本文件不产生项目完成状态。

## 8. 历史资料的可选导入边界

默认不导入任何 donor 业务数据。若未来确需用历史交易或复盘做研究，必须新增独立需求，并满足：

- one-way、read-only、可重复、可删除的 Archive Importer；
- 导入到隔离 schema/dataset，不进入账户、订单、持仓、账本和 ValidatedLesson 当前态；
- 所有记录带 `donor_archive`、来源、原始 ID、导入版本和质量标记；
- 不伪造 Order/Fill sequence，不把旧即时成交包装成高真实性成交；
- 不完整计划、自动复盘和未经验证经验默认标为 incomplete/unvalidated；
- 导入失败不影响新系统运行；删除 archive 不改变任何新业务事实。

该能力不在当前 V0–V5 路线图内，除非用户另行批准加入。

## 9. Donor 审计备注

- 2026-08-18 只读审计时，donor 工作区有 29 个 tracked 修改和 3 个 untracked 文件。
- 256 个 unittest 是在该工作区状态上通过，不证明其 HEAD 单独通过，也不证明目标语义正确。
- donor 的脏工作区不阻塞新项目创建；除非执行某项具体资产资格评估，否则无需处理、提交或清理它。
- 本设计包没有修改 donor 仓库。
