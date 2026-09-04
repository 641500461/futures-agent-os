# V1–V5 LLM 场景与模型路由设计

状态：`PROPOSED — NOT ACTIVATED`  
版本：`1.0-proposed`  
日期：2026-08-27  
适用范围：产品运行时 Agent、用户交互、模型评测与治理；不替代 [`DEVELOPMENT-MODEL-POLICY.md`](./DEVELOPMENT-MODEL-POLICY.md) 的工程开发模型路由。

## 1. 目的

本设计回答四个问题：

1. V1–V5 哪些业务场景真正需要 LLM；
2. 每类内容应使用什么能力档位和 reasoning effort；
3. 哪些能力必须始终由确定性系统负责；
4. 模型频繁升级时，如何替换模型而不修改业务角色、不破坏 Replay、不静默改变已激活行为。

本设计不把“节省 Token”解释为统一压低 turns、tool calls 或输出长度。预算是每个 workload Profile 的可配置运行保护，必须结合代表性 eval、质量、延迟和成本分别校准。OpenAI 当前模型指导也建议从平衡 effort 起步，并只在代表性任务证明质量收益后使用更高 effort，而不是默认选择最高强度：[OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model)。

## 2. 强制边界

- LLM 只生成提案、解释、研究判断和结构化候选，不拥有市场、账户、风险、订单、成交、持仓、账本、结算或治理真值。
- Workflow Orchestrator、实验状态机、风险门禁、执行、保护、结算、Replay 和 hard-gate 不得依赖 LLM 才能保持正确。
- 业务代码引用 `workload_id`，不得到处硬编码 provider、model slug 或 reasoning effort。
- 实际调用前，Governance & Registry 把 `workload_id` 解析为一个已激活、版本化的 `ModelProfile`；运行 Evidence 保存解析后的完整快照。
- 模型、Prompt、Toolset、输出 schema 或路由规则任一变化都创建新 revision，不覆盖历史版本。
- 模型不能自行选择更强模型、提高 effort、切换 provider 或追加未授权调用。升级只能由确定性路由规则或治理绑定触发。
- 不允许静默 fallback。每个 fallback 必须预注册、兼容同一输出契约，并在 Evidence 中记录原因。
- LLM 不可用时不产生新的 Agent 交易提案；已有仓位的保护、退出、Kill Switch、结算和审计继续运行。

## 3. 术语与分层

### 3.1 Workload

`workload_id` 表示一类稳定的业务认知工作，不等同于某个 Agent，也不包含具体模型名称。例如：

- `interaction.simple_explanation`
- `market.regime_interpretation`
- `research.hypothesis_synthesis`
- `decision.opportunity_synthesis`
- `assurance.adversarial_critique`
- `learning.post_trade_review`

### 3.2 Model Profile

`ModelProfile` 是 workload 到实际运行配置的版本化映射，至少包含：

```text
profile_id + revision
workload_id
provider + model_id + reasoning_effort
supported input/output/tool capabilities
prompt_binding + output_schema_binding + toolset_binding
context policy + budget policy + timeout policy
fallback_profile_ref（可空）
eval_suite_ref + qualification_state
pricing_snapshot_ref + effective_at + retired_at
```

### 3.3 当前能力档位

档位是稳定语义，具体模型只是当前候选映射：

| 能力档位 | 适用内容 | 当前候选映射 |
|---|---|---|
| `FAST_STRUCTURED` | 简单分类、格式转换、短摘要、低风险交互 | GPT-5.6 Luna / medium |
| `BALANCED_REASONING` | 多数业务解释、研究综合、Agent 常规判断 | GPT-5.6 Terra / medium |
| `DEEP_REASONING` | 独立反证、尾部风险、严重冲突、治理证据审查 | GPT-5.6 Terra / high |
| `INDEPENDENT_ASSURANCE` | 模型/Prompt/Tool/版本的独立验收 | GPT-5.6 Sol / high；复杂验收可单独批准更高 effort |
| `NO_LLM` | 真值、状态机、计算、门禁、执行和评分 | 确定性代码 |

当前候选参考：[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)、[Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)、[Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)。这些名称不得成为长期领域术语；后续升级只修改 Profile revision。

### 3.4 开发、产品运行与验收三个平面

- **代码开发平面**：由 [`DEVELOPMENT-MODEL-POLICY.md`](./DEVELOPMENT-MODEL-POLICY.md) 决定实现与复核模型。当前用户决定“本次 MVP-R 代码开发暂不用 Grok”只约束这一平面。
- **产品运行平面**：保持 provider-neutral；OpenAI Responses、ChatGPT 登录态下的隔离 Codex runner、Grok runner 或后续 provider 都可以成为某个 workload 的候选 Profile，但必须分别完成资格评测和冻结。
- **独立验收平面**：用于审查代码、Prompt、Tool、Model Profile 和跨模块安全，不自动成为产品运行模型。

同一模型或 provider 可以出现在不同平面，但其身份、权限、Evidence 和 activation 独立。不得因为某 provider 不参与本次代码开发，就把它从产品业务候选中永久排除。

## 4. 全 PRD 场景清单

### 4.1 产品 Agent 与交互 workload

| 角色/场景 | `workload_id` | LLM 负责 | 默认档位 | 条件升级 | 明确不负责 |
|---|---|---|---|---|---|
| Main：研究协调 | `decision.research_coordination` | 理解触发、选择最小充分专家、组合研究 artifact、输出候选/NO_OPPORTUNITY/DEFER | `BALANCED_REASONING` | 跨专家严重冲突进入 `decision.conflict_resolution` | 调度、重试、授权、风险裁决 |
| Main：完整 Episode 决策 | `decision.opportunity_synthesis` | 综合 Regime、Strategy、Critic、Portfolio、Risk Analyst，形成 TRADE/NO_TRADE/DEFER 提案及理由 | `BALANCED_REASONING` | 高影响冲突或 Critical scenario 使用 `DEEP_REASONING` | Order、Fill、最终数量、RiskDecision |
| Main：持仓 Thesis Watch | `decision.thesis_reassessment` | 解释新证据是否破坏 Thesis，提出 HOLD 或降险请求 | `BALANCED_REASONING` | 证据冲突时 `DEEP_REASONING` | 放宽止损、扩大风险、直接执行 |
| 简单用户交互 | `interaction.simple_explanation` | 状态说明、短摘要、已验证 artifact 的用户化表达 | `FAST_STRUCTURED` | 涉及研究判断则改走专业 workload | 重新计算数字或创造结论 |
| 深度用户问答 | `interaction.evidence_explanation` | 回答“为什么做/不做/退出”，区分当时证据与事后结果 | `BALANCED_REASONING` | Critical 风险解释使用专业 Risk workload | 修改历史决策、隐藏不确定性 |
| Market Regime | `market.regime_interpretation` | 解释确定性状态、候选 Regime、反证、转换风险和 unknown | `BALANCED_REASONING` | 多模型严重冲突时 `DEEP_REASONING` | 自算波动率、概率、基差或方向授权 |
| Research | `research.hypothesis_synthesis` | 可证伪 Hypothesis、已知/未知/冲突、最小充分实验 | `BALANCED_REASONING` | 复杂反事实/泄漏争议使用 `DEEP_REASONING` | 自报实验数值、删除失败实验 |
| Strategy | `strategy.plan_drafting` | StrategyCandidate/TradePlanDraft、Thesis、Invalidation、Entry/Exit/ProtectionIntent | `BALANCED_REASONING` | 多策略/多 Regime 冲突使用 `DEEP_REASONING` | 最终手数、风险许可、订单 |
| Critic | `assurance.adversarial_critique` | 独立寻找泄漏、过拟合、成本、集中、稳定性和反例缺陷 | `DEEP_REASONING` | 不再由同一运行自行升级；必要时启动独立第二审查 Profile | 重写原计划后静默放行、替代 Risk Engine |
| Portfolio | `portfolio.exposure_interpretation` | 解释相关性、集中、替换/降权/对冲建议和未知组合风险 | `BALANCED_REASONING` | 跨品种/跨账户尾部冲突使用 `DEEP_REASONING` | 账户真值、优化计算、最终数量 |
| Risk Analyst | `risk.tail_scenario_analysis` | 尾部场景、非线性风险、缓解建议和仍未知风险 | `DEEP_REASONING` | 无自动升级；失败即不声称完成专家分析 | RiskDecision、Kill Switch、风险规则修改 |
| Execution Advisor | `execution.method_comparison` | 比较已注册执行方式的成本、时机、紧急度和取消条件 | `BALANCED_REASONING` | 高保真订单簿复杂场景可独立评测更深 Profile | 创建 Order、改变数量或最大亏损 |
| Post-trade Reviewer | `learning.post_trade_review` | 区分过程/结果/执行质量，提出有证据的 Reflection | `BALANCED_REASONING` | 事故或复杂因果争议使用 `DEEP_REASONING` | 修改历史、把 Reflection 直接变 Lesson |
| Experiment Manager：实验设计 | `experiment.preregistration_design` | 把 Hypothesis/Reflection/Candidate 转为对照、指标、停止规则和证据门槛 | `BALANCED_REASONING` | 复杂多阶段实验使用 `DEEP_REASONING` | 排队、状态推进、自动晋升、隐藏失败 |
| Memory Curator | `learning.lesson_curation` | 合并相似 Reflection、保留冲突/反例、提出适用域和验证请求 | `BALANCED_REASONING` | 高影响 Lesson 冲突使用 `DEEP_REASONING` | 创建 ValidatedLesson、删除反例 |
| Governance Agent | `governance.change_proposal_review` | 汇总证据、分类风险、形成 ChangeProposal 与所需验证步骤 | `DEEP_REASONING` | 独立验收另走 `INDEPENDENT_ASSURANCE` | 修改 Registry、激活/撤销版本 |
| 报告编排 | `interaction.report_rendering` | 在不改变结论时整理已验证结构化内容 | `FAST_STRUCTURED` | 内容需要新判断时回到来源 workload | 新增主张、重算指标、覆盖 Evidence |
| 模型/Prompt/Tool 独立验收 | `assurance.version_acceptance` | 独立检查能力、退化、安全和跨模块一致性 | `INDEPENDENT_ASSURANCE` | 复杂争议需明确治理批准 | 自动激活或替代 deterministic eval |

### 4.2 `NO_LLM` 强制清单

以下能力即使关联 Agent，也必须由确定性组件拥有：

- Scheduler、Workflow Orchestrator、lease、幂等、deadline、取消、重试和恢复；
- Instrument、规则、交易日历、Market Snapshot、Feature、Regime/Signal 数值计算；
- backtest、walk-forward、stress、counterfactual、成本、归因和 sample sufficiency 计算；
- Experiment Manager 的持久状态机、算力队列和实验执行；
- Simulation Autonomy Mandate、Mode、AuthorizationBasis、RiskBudgetReservation、AutonomyGateReceipt；
- Position Sizing、Risk Constitution、RiskDecision、Kill Switch；
- Execution Planner 默认策略、Order、Fill、Position、Protection、Accounting、Settlement；
- Dataset/Model/Prompt/Tool/Strategy Registry 的 qualification/activation 状态变更；
- schema、provenance、grounding、PIT、权限、Replay、hard-gate 和审计校验；
- 通知投递、重试、去重和紧急控制。自然语言润色失败时使用确定性模板。

## 5. V1–V5 启用计划

| 版本 | 启用的 LLM workload | 保持关闭或 `NO_LLM` |
|---|---|---|
| V0 | 无产品 LLM；只定义 Profile/Binding/Evidence 契约 | 全部运行能力 |
| V1 | `decision.research_coordination`、`market.regime_interpretation`、`research.hypothesis_synthesis`、`assurance.adversarial_critique`、`experiment.preregistration_design`、研究报告/问答 | TradePlan、交易、账户、风险和学习晋升 |
| V2 | 沿用 V1 只读研究 workload | 固定 Strategy Spec 的 sizing、gate、risk、execution、accounting、protection 全部无 LLM |
| V3 | 增加完整 Main、Strategy、Portfolio、Risk Analyst、Execution Advisor、Post-trade Reviewer、用户决策解释 | 交易和风险真值仍全部 `NO_LLM` |
| V4 | 增加 Memory Curator、Governance 基础模式和规模化研究设计 | Lesson/Strategy/Model/Prompt 实际晋升与激活 |
| V5 | Governance Model/Policy Steward、复杂执行解释和可选离线模型研究 | 在线 RL、自动模型激活、真实交易仍禁止 |

未到目标版本的 workload 不得由 Main 或其他 Agent 静默代写；只能返回明确 `UNAVAILABLE/DEFER` 或走已注册确定性 fallback。

## 6. 路由决策

### 6.1 输入

确定性路由器至少使用：

- `workload_id`；
- Agent role/version 和 task/output schema；
- phase：`OBSERVE/SHADOW/AUTONOMOUS_SIMULATION/REVIEW/GOVERNANCE`；
- impact class：`READ_ONLY/PROPOSAL/RISK_ADVISORY/GOVERNANCE_ADVISORY`；
- evidence volume、冲突等级、工具需求和 deadline；
- 当前 activation binding、health、预算和资格状态。

路由器不得读取模型的自然语言“自评难度”后直接升级。模型可以输出结构化 `NEEDS_DEEP_REVIEW` 建议，但确定性 policy 决定是否创建新任务。

### 6.2 基本算法

```text
task → validate workload/role/schema
     → resolve ACTIVE ModelProfile revision
     → verify model/prompt/tool/schema qualification
     → freeze RunConfig and budgets
     → invoke model
     → verify actual model id, schema, tool calls, grounding and limits
     → persist Evidence
     → accept artifact, explicit fallback, DEFER or fail closed
```

### 6.3 升级与 fallback

- `FAST_STRUCTURED → BALANCED_REASONING`：只有内容从转换/表达变为新的业务判断时发生。
- `BALANCED_REASONING → DEEP_REASONING`：只有预注册的严重冲突、Critical scenario、尾部风险或治理审查条件触发。
- Critic、Risk Analyst 和 Governance 默认已是 `DEEP_REASONING`，不能靠模型自报继续无限升级。
- fallback 必须输出相同 schema 或显式更弱的降级 schema；不能伪装成原 Profile 成功。
- fallback、retry 和 escalation 都产生独立 run identity，并绑定 parent/causation。

## 7. Token、上下文与成本策略

本设计不设置跨场景统一 Token 上限。每个 Profile 独立配置并通过 eval 调整：

- 输入只包含任务所需的不可变 artifact 与引用，不复制整个对话、全量行情或全部历史实验；
- 数值计算由工具完成，LLM 读取精简结构化结果和 artifact refs；
- 稳定 Prompt、schema 和工具定义允许缓存，但缓存计费与实际 usage 必须记录；
- 相同 artifact 在同一运行中以内容哈希复用，不让模型反复总结同一事实；
- Main 只启动最小充分专家集合，不为“多 Agent 完整性”调用无关角色；
- turns、tool calls、tokens、wall time 和 cost 都是 Profile policy，不是模型自行决定；
- 调低 effort、删减 Prompt、减少调用或启用缓存，都必须在相同代表性 eval 上证明输出仍满足质量门槛。官方 eval 指南要求围绕生产目标设计和持续运行评测：[Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)。

## 8. 运行 Evidence

每次 LLM 调用至少保存：

- `workload_id`、Agent/task/run/correlation/causation identity；
- requested `profile_id/revision` 与 registry/activation binding digest；
- 实际 provider/model ID、reasoning effort、endpoint/runner identity；
- Prompt、Agent、Toolset、output schema、code 和 dataset digest；
- 输入 artifact refs、PIT `as_of`、工具 call/result refs；
- input/output/reasoning/cache tokens、延迟、成本和重试次数；
- escalation/fallback 原因和 parent run；
- validation、grounding、hard-gate、failure code 与最终 artifact identity；
- 不保存 API key、Bearer token、完整受限行情或私有思维过程。

历史 Replay 使用运行时冻结快照，不重新解析“当前默认 Profile”。

## 9. 模型升级生命周期

### 9.1 状态

```text
DRAFT → EVALUATING → SHADOW → QUALIFIED → ACTIVE
                         ↘ REJECTED
ACTIVE → DEPRECATED → RETIRED
```

代码合并、Profile qualification、activation 和 Mandate binding 是不同状态。

### 9.2 升级流程

1. 为现有 `workload_id` 创建新 Profile revision，保留旧 revision；
2. 绑定候选模型、effort、Prompt、Toolset、schema 和预算快照；
3. 在该 workload 的代表性固定 eval 上与当前 ACTIVE revision 比较；
4. 检查 schema、grounding、PIT、工具权限、安全、质量、Token、延迟、成本和失败模式；
5. 进入 SHADOW，不影响交易或治理真值；
6. 通过独立验收后标记 QUALIFIED；
7. 由治理服务/用户显式更新 activation binding；
8. 保留一键回滚 binding，未完成 run 继续使用原冻结 revision；
9. DEPRECATED/RETIRED 不删除历史配置和 Evidence。

模型发布新版本时不得全局搜索替换 model slug。应逐 workload 评估，因为同一升级可能改善 Research，却降低 Critic 缺陷召回或结构化输出稳定性。

## 10. Profile 验收指标

所有 Profile：

- 输出 schema 有效率、PIT/grounding 合规、Tool allowlist 越权率；
- task success、证据完整性、DEFER 适当性；
- tokens、延迟、成本、timeout、retry 和 fallback 率；
- prompt injection、陈旧数据、冲突证据和模型不可用反例。

角色专项：

- Main：最小充分专家选择、NO_TRADE/DEFER 质量、权限合规；
- Regime：unknown/conflicted 保留和状态解释稳定性；
- Research：可证伪性、泄漏识别、失败实验保留；
- Strategy：Thesis/Invalidation 对称性和成本覆盖；
- Critic：高严重度缺陷召回、无意义否决率；
- Portfolio/Risk：集中与尾部风险覆盖、服从确定性门禁；
- Execution Advisor：成本估计与可用执行方式一致性；
- Reviewer：过程/结果分离和因果过度归因率；
- Experiment：预注册完整性、指标/停止规则漂移率；
- Memory：未验证经验泄漏、冲突/过期召回；
- Governance：证据门槛、风险分类和越权率；
- Interaction：事实引用、用户纠正率和敏感信息泄漏。

## 11. 与 MVP-R Gate 的关系

`MVP-R-001` 只验证 V1 中最小的 `research.hypothesis_synthesis` 主路径、受限工具循环、Critic ablation、Replay 和真实用户 shadow，不代表 V1–V5 全部 Profile 已实现或合格。

2026-09-01 `MVP-R-001` 与 [`MVP-R-002`](./MVP-R-002-PREREGISTRATION.md) 均已停止。[`MVP-R-003`](./MVP-R-003-VERTICAL-SLICE-PLAN.md) v1 记为测量方案失败。[`MVP-R-004`](./ROADMAP.md) 机器门槛已过，协助盲评未过强制多 Agent 主路径；产品 Pivot 为单 Research Agent + 确定性实验闭环，Critic 降为影子质检。协助盲评不是独立真实用户验证。当前任务 [`MVP-R-005`](./ROADMAP.md) 为 `IN_PROGRESS`，机器门槛 `R005_PASS`，不是 `GO`。不在正式 eval 前恢复 full qualification 或 30/50/shadow。

MVP-R-003 Discovery 可以选择一个明确记录的产品模型完成最小 smoke 和 8 Episode 运行；进入正式 eval 前仍须把候选表达为版本化 Profile，而不是把 provider/model 字符串散落到业务代码。Cursor 或 Grok Build 作为开发执行器不等于 Grok 产品 Profile 已启用；若正式 MVP-R 要比较 Grok 业务运行，必须另建冻结 suite，不能与另一 provider 混用 holdout。

## 12. 实施顺序

1. V0/V1 契约层：实现 `WorkloadId`、`ModelProfile`、`ModelProfileRevision`、`ModelActivationBinding` 和 `ResolvedRunConfig`；
2. MVP-R：先接入 `research.hypothesis_synthesis`，冻结实际模型/effort/Prompt/Toolset/Evidence；
3. V1-011 之后按实际启用角色增加 Profile，不预建空运行服务；
4. V2 保持交易内核 `NO_LLM`；
5. V3–V5 每启用一个 Agent，先补 workload eval、qualification、fallback 和 rollback；

实施状态（2026-08-28）：第 1 步的最小契约已落地，并已把 MVP-R 的正式 `ModelRunConfig` 接到精确 Profile/activation 快照；Registry 持久化与治理服务仍待后续 Roadmap 任务实现。ChatGPT 登录态 Codex App Server runner 已凭 thread model/provider、零 reroute、完整 output schema、精确 token usage、11 工具注册和内置工具 fail-closed Evidence 进入 `QUALIFIED`；订阅逐调用货币费用保持 `SUBSCRIPTION_UNAVAILABLE`，不伪造成本。它仍需随完整 suite 建立 activation，不能由资格状态自动启用。
6. Registry UI/API 只能修改 activation binding，不能覆盖历史 Profile revision。

## 13. 仍需治理确认

- 产品运行端最终使用 Responses API、隔离 Codex SDK runner、Grok runner，或把它们作为不同 Profile provider；
- 各 workload 首批代表性 eval 数据与质量/成本阈值；
- 哪些严重冲突允许 `BALANCED → DEEP`，哪些必须直接 DEFER；
- ChatGPT/Codex 订阅运行的 usage、模型身份和保留 Evidence 是否满足正式 holdout 审计；
- V3 风险相关 LLM workload 的独立验收人与 activation 流程。

在这些事项确认前，本文是设计基线，不是模型启用授权，也不改变 `MVP-R-002` 的 `IN_PROGRESS` 状态或 `V1-011` Gate。
