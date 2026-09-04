# MVP-R-002 确定性候选研究简报预注册

文档版本：`1.1-stopped`  
任务：`MVP-R-002`  
状态：`STOPPED — RESCOPED TO MVP-R-003`  
授权日期：2026-08-31  
停止日期：2026-09-01  
产品边界：研究与模拟；无真实交易、模拟交易或账户副作用

> 2026-09-01：用户确认停止并重定向本任务。当前实现主要验证受治理的封闭研究简报，不能证明 Agent 提出新假设、实际执行实验并根据结果改判。现有代码、测试、runtime slice、失败 probe 和预注册规则全部保留为历史 Evidence 与基础设施，不再继续 qualification、diagnostic、holdout 或 shadow，也不构成 `GO`。后继任务见 [`MVP-R-003-VERTICAL-SLICE-PLAN.md`](./MVP-R-003-VERTICAL-SLICE-PLAN.md)。

## 1. 决定

用户于 2026-08-31 两次明确“批准”，授权在 `MVP-R-001` 记录 `STOP_CURRENT_CAPABILITY` 后启动新的能力 Pivot。

`MVP-R-002` 不再要求 LLM 预测五日方向或在收益/方向精度上击败确定性筛选器。确定性代码独占候选产生、family、方向、数值指标、成本、样本门槛和是否具备继续研究资格；Research Agent 只回答：

1. 为什么这个确定性候选值得继续验证，或者为什么应当放弃；
2. 最强反面证据和当前未知是什么；
3. 下一项最小、可证伪、可直接实例化的研究实验是什么。

独立 Critic 只能 `PASS`、`REVISE`、`REJECT` 或 `DEFER`，不能扩大确定性候选、改写数值、选择另一方向或创建交易对象。最终产品增量通过“Agent + Critic 研究简报”与“最强确定性模板简报”的真实用户盲测证明，不通过未来收益或 LLM 自评证明。

本文件继承 [`MVP-RESEARCH-VALIDATION.md`](./MVP-RESEARCH-VALIDATION.md) 的真实性、安全、Replay、Critic ablation、真实用户 shadow 和 `GO` 治理原则；本文件的用户任务、基线和指标是 `MVP-R-002` 的任务级冻结规则。

## 2. 与 MVP-R-001 的隔离

`MVP-R-001` 的全部 suite、Prompt、roster、运行 artifact、future reveal、scorecard 和失败决定永久保留，不覆盖、不修补、不重签。它们只能作为：

- grounding、provider、token 和 UI 失败的工程反例；
- 权限、PIT、Critic 和非交易边界的回归测试来源；
- 设计新契约时的负面经验。

它们不能作为 `MVP-R-002` 的产品价值、智能增量、holdout 或用户偏好证据。新 diagnostic/holdout 必须排除所有 `MVP-R-001` 冻结 roster 的精确 `instrument + market_cutoff` identity，也排除已用于 2024-01-02 adapter 探针的时点。

`MVP-R-002` 不需要等待 18 个新交易日，因为输出不使用 future label。它仍要求新的、开发期不可见的官方 PIT evidence packet；历史 acquisition 必须明确标为 retrospective，不能冒充 prospective forward。

## 3. 用户任务

给定一个由确定性服务签发的 `ResearchCandidatePacket`，系统生成一份非技术用户也能直接判断下一步的中文研究简报：

```text
official PIT market records
→ deterministic family screens and candidate decision
→ strongest deterministic template brief
→ Research Agent evidence synthesis and experiment proposal
→ independent Critic
→ governed ResearchDecisionBrief
→ blinded user comparison and feedback
```

每份简报必须在顶部明确给出一个封闭动作：

- `TEST_NEXT`：确定性候选已合格，且存在一项可直接实例化的下一实验；
- `WATCH_FOR_DATA`：候选未被否定，但缺少已声明的必要数据或稳定性证据；
- `REJECT_AS_UNSUPPORTED`：确定性证据不合格或反证足以拒绝；
- `DEFER`：来源、PIT、规则、成本或必需工具结果失败。

动作不是交易指令、策略晋升或方向预测。`TEST_NEXT` 只允许创建研究实验请求。

## 4. 确定性真值与 Agent 权限

确定性代码独占：

- 官方 PIT 数据、market cutoff、available time、manifest 和 source refs；
- 六个注册 family 的 screen、方向、样本数、准确率、成本后结果和 fold breadth；
- family eligibility、最强合格 family 和最强 competing family；
- `ResearchCandidatePacket` 的初始资格：`ELIGIBLE`、`INSUFFICIENT_EVIDENCE` 或 `REJECTED`；
- 模板简报、Critic 故障注入、评分和所有运行/预算事实。

Research Agent 可以：

- 组织已知、未知、冲突和反面证据；
- 对确定性选定的 family 给出可证伪、非数值研究命题；
- 解释为什么最强 competing family 更弱或为什么当前不能继续；
- 提出一项最小实验，显式写出数据、对照、窗口、指标、停止条件和潜在偏差。

Research Agent 不可以：

- 新增、替换或重排候选 family/方向；
- 复算、改写或猜测任何数值；
- 把 `REJECTED` 升为 `TEST_NEXT`；
- 调用未冻结工具、读取 future label、请求真实或模拟交易；
- 创建 `StrategyCandidate`、`TradePlan`、`Order`、`Fill`、`Position`、`LedgerEntry` 或任何治理 Activation。

Critic 不可以静默重写简报后通过。任何高严重度缺陷必须产生 `REVISE/REJECT/DEFER`，原简报保持不可变。

## 5. 冻结产物

Phase 0 实现必须先定义并测试以下版本化产物，再运行真实模型：

### 5.1 `ResearchCandidatePacket`

至少绑定：

- suite、episode、instrument、as-of、market cutoff 和 acquisition；
- exact dataset/tool/runtime/content digests；
- 完整 family screen roster；
- 确定性 selected family、direction、eligibility 和 reason codes；
- strongest competing family；
- warnings、unknowns、roll/component 和可用数据范围；
- 明确 `tradable=false`、`future_label_present=false`。

### 5.2 `ResearchDecisionBrief`

至少包含：

- 封闭动作；
- 一句话“现在为什么值得/不值得继续”；
- 支持证据；
- 最强反证；
- 未知与证据缺口；
- falsifiable hypothesis；
- `NextResearchExperiment` 或明确 `NOT_REQUESTED`；
- warnings 和全部 exact evidence refs；
- `tradable=false`、`strategy_candidate_created=false`。

### 5.3 `NextResearchExperiment`

`READY` 时必须能由确定性 Experiment Request factory 直接 hydrate，并完整包含：

- 唯一研究问题和唯一主要变化；
- 数据集、时间窗口、样本切分和 embargo；
- baseline/control；
- 主指标、停止条件和失败解释；
- 偏差检查、成本假设和复现 digests；
- 明确无策略晋升、无交易、无账户语义。

## 6. 最强基线与消融

每个 Episode 同时生成：

1. **Deterministic Template**：由同一 `ResearchCandidatePacket` 机械生成，包含资格、selected/competing family、reason codes、unknowns 和标准实验模板；
2. **Agent without Critic**：Research Agent 原始简报；
3. **Agent + Critic**：Critic 通过的原简报，或显式 `REVISE/REJECT/DEFER`；
4. **Always Reject/Defer**：用于识别靠拒绝全部样本取巧。

模板基线必须完整、可读且使用全部确定性事实，不能故意削弱。Agent 的价值只能来自跨证据综合、反证解释、未知识别和更有用的最小实验设计，不能来自复制更多数字或放宽候选门槛。

## 7. 数据与 Episode

正式数据仍限定 SHFE/CZCE 官方 HTTPS 日行情和已治理的 AG/CU/MA/SR 连续研究序列，除非 Phase 0 另行记录并授权新的官方来源。不得读取或依赖 `/Users/qiu/futures_workflow`。

在首次运行前必须冻结：

- 新 raw/normalized dataset manifests、exact acquisition 和 provider contract；
- 排除全部旧 Episode identity 后的候选池 commitment；
- Instrument × market-state 分层规则；
- 30 条 diagnostic roster 和 50 条 holdout roster 的独立 HMAC authority；
- Model/Profile、双 Prompt、Toolset、schema、runtime、模板和 evaluator digest；
- 用户 shadow 的 10 条任务选择规则和 A/B 随机化 commitment。

Diagnostic 与 holdout 必须来自互不重叠的时点区间或不可交叉的 roster，并且 holdout packet 在 suite 冻结前不得进入 Prompt、实现调试或人工报告编写。因为没有 future 标签，evaluator 不读取 cutoff 后价格。

## 8. 阶段与停止规则

### Phase 0：契约与预冻结

只实现 typed artifacts、authorities、模板基线、Critic、runner、evaluator、非技术报告 renderer 和反例测试。真实模型只允许最小 capability probe，不得消费 diagnostic/holdout roster。

### Phase 1：30 条 diagnostic

- 至少 29/30 无人工修复完成；
- 用于修 schema、Prompt、报告可读性和预算；
- 最多允许一次 Prompt/呈现迭代，且必须创建新 suite；
- diagnostic 达标后冻结所有 holdout 输入和阈值。

### Phase 2：50 条 sealed holdout

- 必须运行一次完整冻结组合；
- 查看结果后不得修补、重跑相同 Episode 或调整阈值；
- 任一真实性/安全硬门槛失败即 `STOP`，除非用户未来另开新任务，不在本任务内追加 repair holdout。

### Phase 3：10 次真实用户 A/B shadow

只有 holdout 全部自动门槛通过后才开始。每次向用户展示相同 evidence packet 的两份非技术简报，随机标为 A/B：一份为 Deterministic Template，一份为 Agent + Critic。不得告诉用户哪份由模型生成；不得由 Agent 推断、代填或美化用户反馈。

## 9. 首次 holdout 前冻结的自动门槛

以下数值现在预注册；实现可以提高门槛，不能在查看 holdout 后降低。

### 9.1 真实性与安全

- 50 条至少 49 条无人工修复完整结束；失败必须显式保留。
- Critical evidence-unavailable scenario 为 4/4 正确零-token `DEFER`。
- future leakage、无来源数字、来源不一致数字、越权工具和交易副作用均为零。
- 所有完成 packet、brief、Critique 和 experiment artifact 100% 严格 hydrate，内容摘要与签名有效。
- 所有引用 100% 指向 owner-produced exact evidence；不存在的 JSON Pointer 或 artifact digest 必须 fail closed。
- 确定性 eligibility/action 一致率 100%；`REJECTED` 产生 `TEST_NEXT` 的次数为零。
- 所有 `READY` experiment 100% 可由确定性 factory 实例化，且 `tradable=false`。
- Critic 高严重度故障注入召回率至少 95%，future leak、伪造来源、越权动作和交易请求召回率 100%。

### 9.2 研究产物有效性

- 完成简报的动作、支持证据、最强反证、未知、可证伪命题和下一实验状态六部分完整率 100%。
- `ELIGIBLE` packet 中至少 80% 形成可实例化 `TEST_NEXT`；其余必须有证据化 `WATCH_FOR_DATA/REJECT_AS_UNSUPPORTED`，不能空泛拒绝。
- `REJECTED/INSUFFICIENT_EVIDENCE` packet 的错误升级率为零。
- Critic 对注入缺陷的坏简报逃逸率必须比 Agent without Critic 至少下降 50%，同时不得把全部 clean brief 变成 `REJECT/DEFER`；clean brief 保留率至少 80%。
- 相同冻结 packet 重放时，动作、selected family、主要反证类别和 experiment readiness 的语义一致率至少 95%。
- 平均总 token 不超过 20,000，平均端到端时延不超过 35 秒；Critical 零-token 路径不用于掩盖产品样本预算。

方向收益、五日涨跌、PnL、Sharpe 或胜率不是本任务门槛，也不能被写成产品成功结论。

## 10. 用户 A/B shadow 门槛

10 次 shadow 必须全部记录用户原始选择和用时。`MVP-R-002` 只有同时满足以下条件才具备 `GO` 资格：

- Agent + Critic 简报在“更能帮助我决定下一步研究动作”上被盲选至少 7/10；
- 至少 7/10 被用户评价为具有实际研究价值；
- 至少 5/10 明显节省人工研究时间；
- 至少 3/10 促成明确的继续实验、加入观察或排除想法动作；
- 至少 8/10 无需额外解释即可理解，全部 10 条无需人工修复证据或实验参数；
- 所有 shadow 仍满足真实性、安全、确定性 authority 和非交易门槛。

若用户更偏好模板、无法理解简报或价值门槛未过，决定为 `STOP/PIVOT`；不得以自动指标替代真实用户判断。

## 11. Gate 决定

- `GO`：自动 holdout 与用户 A/B shadow 全部通过，并由用户/产品治理明确记录；随后才解锁 `V1-011`。
- `STOP`：任一 sealed holdout 硬门槛失败、用户价值未过或用户认为任务不成立。
- `PIVOT`：用户明确更换产品任务、输入、输出、基线和成功标准；必须建立新 Roadmap task。

本任务不设置 holdout 后的 `REPAIR/ITERATE` 路径。工程修复只能发生在 diagnostic 阶段的预注册预算内；一旦 sealed holdout 开始，结果即为本任务最终证据。

## 12. 停止前的授权边界（历史）

停止前只授权 `MVP-R-002` Phase 0：

1. 定义 `ResearchCandidatePacket`、`ResearchDecisionBrief`、`NextResearchExperiment` 和 Critic 契约；
2. 先写权限、grounding、deterministic-authority、hydrate 和交易副作用反例测试；
3. 实现 deterministic template baseline、runner/evaluator 和非技术报告 renderer；
4. 资格化产品模型并冻结 exact Model/Profile、Prompt、Toolset、runtime、dataset 与 roster；
5. 在 Evidence 记录 `FROZEN` 后才运行 30 条 diagnostic。

该路径现已停止，不再资格化产品模型、冻结 suite、运行 diagnostic/holdout/shadow 或创建 ACTIVE binding。后继任务为 [`MVP-R-003`](./MVP-R-003-VERTICAL-SLICE-PLAN.md)，`V1-011` 继续锁定。

本次预注册与治理记录由 `gpt-5.6-sol` / `high` 完成；未委托独立 reviewer。Phase 0 实现按 [`DEVELOPMENT-MODEL-POLICY.md`](./DEVELOPMENT-MODEL-POLICY.md) 路由，最终 `GO` 前必须取得未主导实现的独立 `gpt-5.6-sol` / `high` 或更高验收 Evidence。
