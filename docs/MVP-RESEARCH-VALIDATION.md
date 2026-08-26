# MVP-R：研究可用性验证

文档版本：`1.0-proposed`<br>
最后更新：2026-08-25<br>
状态：PLANNED<br>
启动条件：`V1-010` Acceptance 与 Evidence 完成<br>
路线图任务：`MVP-R-001`

## 1. 决策

`V1-010` 完成后，项目不自动继续 `V1-011` Experiment Manager 或后续 Opportunity Radar，而是先启动 `MVP-R-001` 研究可用性试验。

`V1-010` 只表示确定性研究工具已经具备；它是 MVP 试验的起跑线，不等于 MVP 已成立。只有本文件定义的真实性与安全、智能有效性和真实用户价值三类门槛全部满足，并记录 `GO` 决定后，系统才可称为 **MVP-R（Research MVP）**，并解锁后续 V1 工业化任务。

本门槛验证的是研究产品价值，不验证自主模拟交易价值。完整 LONG/SHORT、仓位、止损、PnL、Order/Fill 和 Trade Episode 价值验证属于 V2/V3 之后的独立门槛。

## 2. MVP-R 用户任务

给定授权研究宇宙和历史时点，用户可手工触发一次研究。系统只使用该时点可见的真实数据，完成：

```text
point-in-time Market Snapshot
→ Market State
→ Falsifiable Hypothesis
→ L0/L1 + walk-forward / cost stress / counterfactual
→ independent Critic
→ OpportunityCandidate / NO_OPPORTUNITY / DEFER
→ evidence-linked report
```

报告必须让用户能够判断：为什么值得继续研究、为什么应该放弃，或者为什么当前证据不足。正确排除一个想法、明确 `NO_OPPORTUNITY` 或诚实 `DEFER` 都可构成用户价值。

## 3. 最小范围

必须包含：

- 至少一个授权的真实历史数据来源；synthetic/golden 数据只用于回归与故障样本，不得作为产品价值结论。
- 3–4 个预先登记的代表性品种，覆盖不同交易所、资产类别和市场状态；数据、规则、日历和修订均有 PIT provenance。
- 最小 provider-neutral 模型调用适配器，固定 Model、Prompt、Agent、Toolset 和代码版本；记录结构化结论、工具轨迹、token、延迟和成本，不保存或依赖模型私有思维过程。
- 串行、有预算的工具循环和 Replay/Evaluation Harness；无需先建设异步 Experiment Manager。
- evaluator 独占 future reveal；Agent、Prompt 和全部工具在评分前都不能读取 `as_of` 之后的数据。
- 最小 CLI 或单份 HTML/Markdown 报告；无需飞书或完整 UI。

明确不包含：

- TradePlan、Order、Fill、Position、LedgerEntry 或任何真实/模拟交易副作用。
- Portfolio、Execution、Memory/Lesson、飞书、完整 Scheduler、自动全市场扫描。
- 用回测收益、胜率或专业化文本单独证明 MVP 成立。

## 4. 试验阶段

### Phase 0：预注册与最小运行准备

在查看 holdout 未来结果前冻结：

- 用户任务、研究宇宙、时间范围、Episode 选择规则和数据 manifest。
- Model/Prompt/Agent/Toolset 版本、温度/随机参数、预算和失败策略。
- 基线、主次指标、评分规则、通过阈值、最大迭代次数、时间和单次成本预算。
- future reveal 权限边界与泄漏检测反例。

最小基线至少包括：确定性 Regime/Signal、模板化 Hypothesis、Agent without Critic、Agent + Critic 和 always `DEFER/NO_OPPORTUNITY`。

### Phase 1：诊断集

运行 30 个可人工审阅的高质量 Episode，覆盖上升、下跌、震荡、反转、极端波动和假突破/噪声等状态。诊断集只用于发现缺口、校准指标和修改模型/Prompt/工具，不用于最终 MVP 结论。

完成诊断后冻结评分规则和阈值；任何后续变化必须产生新 eval suite/version，不能覆盖原结果。

### Phase 2：封存 holdout

在至少 50 个开发期不可见的 PIT Episode 上运行冻结组合。holdout 必须跨时间、品种和 Regime，并保留数据、规则、Prompt、Model、Tool、代码、配置和运行成本引用。

不得在查看 holdout 结果后继续调整同一 suite 并把重跑结果伪装为首次验证。发生调整时必须新建 suite/version 和新的封存 holdout。

### Phase 3：真实 shadow 使用

用户连续完成至少 10 次真实研究任务。每次只记录结构化反馈：

- 报告是否值得保留。
- 是否节省研究时间。
- 是否促成继续验证、加入观察、排除想法或保持 `NO_OPPORTUNITY/DEFER` 的明确行动。
- 如果没有系统，用户是否仍需手工完成相同工作。
- 完成时间、模型成本、失败和人工修复情况。

## 5. Acceptance

### 5.1 真实性与安全硬门槛

以下条件必须全部满足：

- future data leakage = `0`。
- 无来源或来源不一致的数字 claim = `0`；数字 grounding = `100%`。
- 未授权工具调用成功 = `0`。
- synthetic 数据被呈现为真实研究结论 = `0`。
- Critical scenario 正确拒绝率 = `100%`。
- Critic 高严重度缺陷召回率 `>= 95%`。
- Order、Fill、Position、LedgerEntry 或其他交易副作用 = `0`。
- 数据、规则、成本或证据不足时显式 `DEFER/INCOMPLETE`，不得静默采用默认值或生成伪结论。
- 相同冻结输入能够解析完整版本组合并重放；不要求模型文本逐字一致，但结论类别、核心证据和实验请求的语义稳定性必须达到预注册阈值。

任何硬门槛失败都阻断 MVP 声明和后续 V1 工业化任务，先修复并以新 Evidence 复验。

### 5.2 智能有效性门槛

具体数值阈值在 Phase 0/1 后、首次查看 holdout 前预注册。最终至少证明：

- Hypothesis 的可证伪性、引用正确性和实验可执行性达到冻结阈值。
- Agent 相对最强已声明朴素基线，在主指标上不劣，并在证据质量、候选筛选或研究效率至少一个预注册维度产生正增量。
- Agent + Critic 相对 Agent without Critic 可测量地降低坏候选逃逸率，且不是通过把全部结果变成 `DEFER` 获得。
- `NO_OPPORTUNITY/DEFER` 在噪声或证据不足 Episode 中具有实际筛选价值。
- walk-forward、成本压力和 counterfactual 结果不会被样本内表现、单一品种或单一 Regime 垄断；样本不足时结论必须保持 `INCOMPLETE/DEFER`。
- 每个有效研究结论的延迟和成本不超过 Phase 0 预注册预算。

### 5.3 真实用户价值门槛

10 次 shadow 研究中至少满足：

- `>= 7` 次被用户评价为具有实际研究价值。
- `>= 5` 次明显节省人工研究时间。
- `>= 3` 次促成明确的后续研究、观察或排除行动。
- 连续 30 次正式候选运行中至少 29 次无需人工修复即可完整结束；其余运行必须显式失败或 `DEFER`，不得静默丢失。
- 全部运行满足真实性与安全硬门槛。

## 6. Gate 决定

- `GO`：全部硬门槛、智能门槛和用户价值门槛通过；记录 Evidence 后可声明 MVP-R，并开始 `V1-011`。
- `ITERATE`：硬门槛通过但智能或用户价值不足；只允许在预注册迭代预算内调整数据、Model、Prompt、Tool 或角色边界，并创建新 suite/version 后重跑。
- `REPAIR`：任一真实性或安全硬门槛失败；停止价值结论，先修复并完整复验。
- `STOP/PIVOT`：用尽预注册迭代预算仍无增量价值，或用户明确判断产品任务不成立；不得因已有工程投入自动继续 V1/V2。

Gate 决定属于用户/产品治理，不由 Agent、单次收益或测试数量自动产生。

## 7. Evidence 包

`MVP-R-001` 完成时至少记录：

- 实际 implementation/reviewer model 与 reasoning effort。
- 代码 commit、数据 manifest、许可/来源、品种和 Episode 选择规则。
- Model/Prompt/Agent/Toolset/代码版本、预算与失败策略。
- 30 个诊断 Episode 报告、冻结评分规则和 suite digest。
- 50+ 个 holdout Episode 的逐例结果、聚合 scorecard、基线与 Critic ablation。
- 10 次 shadow 使用记录、时间/成本和用户价值判断。
- 泄漏、grounding、权限、Critical scenario 和交易副作用反例测试结果。
- 最终 `GO/ITERATE/REPAIR/STOP-PIVOT` 决定、决定者和日期。
