# 开发模型路由策略

状态：active  
生效日期：2026-08-18

本策略规定项目开发任务的默认模型、升级条件和独立验收方式。模型负责产生候选实现，Roadmap Acceptance、自动化测试和可复核 Evidence 才决定任务是否完成。

本文件不规定产品运行时 Agent 的模型。V1–V5 产品 workload、Model Profile、fallback、升级和运行 Evidence 见 [`LLM-SCENARIO-AND-MODEL-ROUTING.md`](./LLM-SCENARIO-AND-MODEL-ROUTING.md)。

安全范围遵循 Roadmap 的“个人自用、可信本机”前提：纯对抗性安全加固默认不是开发任务，也不因“安全”标签自动升级模型。下表中的高强度路由针对交易正确性、资金/仓位/账本真值、并发、恢复和不可逆状态风险；只有用户明确授权或部署边界改变时，才把独立攻击者威胁作为升级原因。

## 路由矩阵

| 任务类型 | 默认模型 | 推理强度 | 典型范围 |
|---|---|---|---|
| 常规开发 | GPT-5.6 Terra | medium | V0/V1 地基、接口、领域模型、适配器、测试、文档和大部分功能实现 |
| 交易与状态关键开发 | GPT-5.6 Terra | high | 风控、订单/成交/账本、幂等与并发、自治控制、状态机、保护和故障恢复 |
| 版本与关键不变量验收 | GPT-5.6 Sol | high；复杂跨上下文验收可用 xhigh | 每个版本 Exit、跨模块一致性、交易/状态边界和全量代码审查 |
| 批量机械任务 | GPT-5.6 Luna | medium | 格式整理、重复测试脚手架和简单机械变更；不得独立承担交易或状态关键判断 |

该选择遵循 [OpenAI GPT-5.6 模型指导](https://developers.openai.com/api/docs/guides/latest-model)：Terra 用于能力与成本平衡，medium 作为平衡起点，更高推理强度用于存在可测质量增益的复杂任务，Sol 用于旗舰能力需求。

## 自动路由规则

1. 开始 Roadmap 任务前，当前统筹对话根据任务 Acceptance 和影响边界选择模型与推理强度。
2. 同一任务同时包含普通部分和交易/状态关键部分时，按最高业务风险等级路由，不拆低正确性门槛；纯对抗性 hardening 按上述范围先判断是否应做。
3. 常规任务由 Terra/medium 实现；一旦触及资金/仓位真值、风险许可、执行、账本、授权竞态或恢复，升级为 Terra/high。
4. 每个 V0–V5 版本 Exit 必须由未主导该版本实现的 Sol/high 或 Sol/xhigh 进行独立审查。
5. Luna 只能处理结果容易机械验证的任务；发现领域歧义、权限变化或状态机变化时立即升级。
6. 若运行环境不能在活动 turn 中切换主模型，统筹对话将任务交给指定模型的受控执行任务，再由统筹对话复核、测试和提交。

## 任务级外部执行器例外

### `MVP-R-003` 外部执行器例外

2026-09-01 用户明确授权 `MVP-R-003` 优先由 Cursor 或 Grok Build 执行，以使用即将过期的外部额度。该任务级例外不改变产品运行时模型路由，也不降低 Acceptance、测试、领域所有权或独立验收要求。

- 每个工作包必须记录实际执行器、精确模型/版本和 reasoning effort；若宿主不暴露某字段，明确记录 `NOT_EXPOSED`，不得猜测。
- 外部执行器必须遵守 `AGENTS.md`、Roadmap 单任务边界和 [`MVP-R-003-VERTICAL-SLICE-PLAN.md`](./MVP-R-003-VERTICAL-SLICE-PLAN.md)。
- 最终评审必须由未主导实现的模型/执行器完成；Cursor/Grok 自报成功不能替代测试与用户 Discovery 评价。
- 该例外不自动授权 Grok、Cursor 或任何外部模型成为产品运行时 Agent Profile。
- 该例外不自动延伸到 `MVP-R-004`、`MVP-R-005` 或后续任务；后续任务未另授例外时，回到本文件默认路由。

## Evidence 要求

每个完成任务的 Evidence 至少记录：

- implementation model 与 reasoning effort；
- reviewer model 与 reasoning effort（若适用）；
- commit、测试命令和结果；
- 是否发生模型升级，以及触发原因；
- 模型输出未覆盖但由人工规则或确定性测试裁决的事项。

模型名称不是质量证据。任何模型都不能替代领域所有权、Risk Constitution、契约测试、属性测试、回放、故障注入或版本 Exit 条件。
