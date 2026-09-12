# V5-012 模拟系统上线评审包

状态：评审包 COMPLETE；启用决定为 `RESTRICTED_SIMULATION_ONLY`

评审日期：2026-09-12  
适用边界：单用户、可信本机、研究与模拟系统  
真实交易：禁止

## 决策

V5-012 的评审包已经形成，覆盖产品、架构、风险、数据和运营结论。当前只允许在已授权数据、隔离模拟账户和明确的 `OBSERVE`、`SHADOW` 或受控 `AUTONOMOUS_SIMULATION` 范围内运行。任何 Paper connector、真实资金、真实订单路由或未登记的数据来源都不在启用范围内。当前受限策略仅适用于本次开发/CI 范围，尚未扩大为常驻 Paper 或真实行情部署。

评审包不批准无条件的 `sim-prod` 扩大启用。以下事项全部关闭并取得独立证据前，启用门保持 `DENY`：

1. `V5-012-B1 CLOSED`：由未主导 V5 实现的独立 `gpt-5.6-sol/high` 身份在源提交 `3a99e32d09f3547770e3fb559dacd547d2a78ea7` 上完成 V5 Exit 复核；Evidence 见 `evidence/v5-exit/independent-review-2026-09-12.json`。
2. `V5-012-B2 OPEN`：为部署实际使用的数据集登记 license、allowed use、retention、来源、schema、覆盖范围和 `as_of` 证据。
3. `V5-012-B3 CLOSED`：当前开发/CI 受限部署已明确关闭 Paper connector、凭据和 Paper/L5 真实性宣传；若未来要启用，必须取得有授权且具有代表性的 Paper 观测并完成 V5-006 校准。Evidence：`evidence/v5-012/paper-scope-decision-2026-09-12.json`。
4. `V5-012-B4 CLOSED`：操作者决定直接查看 Codex 用量，不建设单独计费账本；Paper 已禁用，因此没有 Paper 费用。现有本机资源基线继续保留作诊断，不解释为货币成本。

这些门禁未关闭时，系统仍可用于本地和测试环境的研究与确定性模拟验收；不产生真实订单或真实资金副作用。

## 产品评审

| 项目 | 结论 | 依据 |
|---|---|---|
| 用户旅程 | PASS（受限） | V3 完整自治周期、重要通知、暂停/撤销 Mandate、保护与复盘链路已具备 |
| 能力边界 | PASS | Agent 只提交 proposal/TradePlan；Risk、Execution、Accounting、Protection 为确定性 owner |
| 环境标识 | PASS | local/test/staging/sim-prod 均保持模拟边界；Paper connector 不等于真实交易 |
| 启用策略 | ACTION_REQUIRED | 先 OBSERVE → SHADOW → 受限 AUTONOMOUS_SIMULATION；不得自动扩大 Mandate 或版本范围 |

## 架构评审

确定性交易真值由 Risk Constitution、订单/成交、持仓、账本、结算和 Position Protection 持有。Agent checkpoint 与业务状态分离；Gateway、通知和外部 connector 不直接写订单、风险或账本。恢复从 `PROTECT_ONLY` 开始，旧 Receipt 不可复用。V5-010 的 SLO、容量保留、背压、限流、熔断和恢复门禁，以及 V5-011 的 append-only hash-chain 运行记录，满足当前模拟系统的架构验收。

## 真实性级别与能力矩阵

| 能力 | 级别 | 当前结论 | 限制 |
|---|---|---|---|
| L1/L2 事件驱动模拟 | L1/L2 | 可用 | 仅模拟环境 |
| Tick/Quote replay | L3 | 可用 | 依赖授权的代表性数据；当前证据证明语义与重放，不证明所有市场覆盖 |
| Order-book/queue replay | L4 | 可用（研究） | 检查样本是 synthetic golden oracle，尚无交易所队列校准 |
| Paper connector 边界 | L5 boundary | 未启用 | 需要部署凭据、外部状态对账和代表性 Paper 校准 |
| TWAP/VWAP/Iceberg/批量计划 | L2–L5 | 可用 | 成交质量由选定 FillModel 和校准范围约束 |
| 组合、跨期、换月和资本分配 | 确定性组合层 | 可用 | 输入必须共享声明的报告币种；仍不授权真实资金 |
| Model/Prompt/Strategy 评测与 canary | 治理层 | 可用 | 只能 proposal、人工批准、独立 Activation 和 rollback |
| Offline RL | 研究层 | 可用（隔离） | 只允许低维模块，不能替代高层 Agent 或默认运行路径 |
| 运营控制 | 模拟运行层 | 可用（受限） | 一天稳定性和单机恢复已证；不等同 HA 或长期生产 SLO |

## 风险评审

已验证的硬门禁包括：无保护暴露、重复 Fill/记账、reservation 超卖、越过风险 ceiling、账本差异和旧授权复用均被确定性测试阻断；Kill Switch、保护退出、撤销 Mandate、模式暂停和恢复均保留审计。模型不可用时不产生新的 Agent 交易提案，已有暴露仍由确定性保护、结算和 Kill Switch 处理。

剩余风险必须在扩大启用前处理：Paper 状态可能未知、数据代表性和授权可能不足、单机故障域仍有限、V5-010 PITR 演练的业务状态范围是 `EMPTY_TRADING_STATE`，以及当前真实行情数据授权仍未形成部署确认。上述风险均不允许通过文字假设关闭。

## 数据评审

数据进入决策前必须有来源、license、allowed use、retention、schema、coverage、质量等级、revision、ingested time 和 `available_time <= as_of` 证据。Q0/Q1 数据不得进入决策或模拟执行；Q3/Q4 才可作为决策/执行输入。当前代码和契约支持这些门禁，但本评审包没有替部署生成新的第三方授权；真实行情部署数据 manifest 仍是 B2 的 ACTION_REQUIRED 项。synthetic v0-012 仍只限开发/CI，不能代表真实市场数据授权。

## 运营评审

V5-010 已演练七项关键 SLO 告警、关键容量保留、backlog/rate/circuit 故障、PostgreSQL PITR、RPO=0 秒目标事务和 `PROTECT_ONLY` 恢复。V5-011 在冻结提交上完成了真实一日运行：85 次心跳、6 个 gap 事故报告、累计 gap 6465.484496 秒，重复交易/无保护持仓/审计断点/账本差额均为零。

该证据支持受限模拟运行，不支持 HA、30 天长期 SLO、非空业务状态 PITR 或 Paper 真实性外推。运行中断、SLO 缺失、connector 状态未知、账本不平或无保护暴露时，必须暂停新增风险并进入 `PROTECT_ONLY`/`HALTED`。

本机 `make check` 控制基线的墙钟为 18.34 秒、用户 CPU 为 41.94 秒、系统 CPU 为 4.09 秒；稳定性运行目录为 49,152 字节、V5 Evidence 当前为 69,632 字节。这些值用于容量和保留策略的起点，不是生产账单或长期容量承诺。

## 回滚与 Kill Switch 演练

1. 操作者触发账户/品种/全局 Kill Switch，或执行暂停新仓、撤销 Mandate；
2. 立即拒绝新的风险增加，继续执行确定性保护、撤单、减仓/平仓和结算；
3. 用户暂停同时版本化 Mandate/Mode，使未消费 Basis、Receipt 失效并释放 reservation；
4. 保留原始审计、账本和 connector 状态，禁止直接编辑 projection 消除差异；
5. 通过数据库、账本、未完成订单、持仓保护和 connector 五项恢复门禁后，人工批准才可重新绑定已批准且仍有资格的版本；
6. 恢复使用新 Snapshot、AuthorizationBasis、Reservation、Final Gate、RiskDecision 和 Receipt，旧 Receipt 永不复用。

演练依据：`tests/contract/test_v2_002_risk_engine.py`、`test_v2_007_protection.py`、`test_v3_009_autonomy_mandate.py`、`test_v5_008_model_evaluation_pipeline.py`、`test_v5_010_operational_reliability.py`、`test_v5_011_stability_run.py`，以及 V5-010 PITR/control drill Evidence。

## 评审结论

- 产品：PASS（受限模拟）。
- 架构：PASS（确定性 owner 与恢复边界满足要求）。
- 风险：PASS（硬门禁通过）；扩大启用仍受剩余风险门禁约束。
- 数据：ACTION_REQUIRED（部署授权 manifest 尚待绑定）。
- 运营：PASS（受限模拟）；V5 Exit 已独立复核，B4 采用操作者手动查看 Codex 用量。
- 总决定：`RESTRICTED_SIMULATION_ONLY`；`enablement_gate=DENY_UNTIL_BLOCKERS_CLOSED`。
