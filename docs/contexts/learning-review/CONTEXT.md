# Learning & Review

本上下文评价决策、执行和结果，提出解释并用额外证据验证可复用经验。它决定一条解释是否得到支持，但不直接修改策略、Prompt、模型、风险政策或启用范围。

## Language

### Episodes and review

**Decision Journal**:
由已持久化的决策、授权、风险、执行、账务、监控与复盘事件构建的追加式时间投影，供审计、重放和用户学习；同一 source event 的完全相同重放幂等，ID 指向不同不可变事实或不同投影内容必须失败关闭，事后解释只能以新条目追加。
_Avoid_: Chat History、可编辑复盘文档、Decision Episode、源业务事实

**Decision Cutoff**:
某个决策当时允许进入 Decision Journal 的最后可用时点，用来区分 DECISION_TIME 事实与只能追加的 POST_HOC 事实。
_Avoid_: Projected At、市场收盘、Review 时间

**Trade Episode**:
Learning & Review 基于各源上下文事件与 Decision Journal，从 Decision Episode 延伸到 Authorization Basis、风险裁决、执行、保护、账务结果和后续市场路径所构建的完整可追溯投影；相同源事实重放幂等，冲突的 source event identity 必须失败关闭；它可重建且不取得源业务事实的写权限。
_Avoid_: Decision Episode、Order、单次对话

**Trade Review**:
对一个 Trade Episode 的证据、过程、执行和结果所作的结构化评价。
_Avoid_: 交易摘要、复盘聊天、Validated Lesson

**Process Quality**:
决策和执行是否遵守当时可见证据、Trade Plan、有效 Authorization Basis、Mandate Scope、风险约束和操作规则的评价。
_Avoid_: 盈亏、Outcome Quality、用户满意度

**Outcome Quality**:
交易结果和后续市场路径相对原目标的评价，不自动推翻 Process Quality。
_Avoid_: 决策正确、策略有效、Realized PnL

**Execution Quality**:
实际执行相对 Execution Plan 和当时可成交条件的偏差评价。
_Avoid_: Outcome Quality、Fill 数量、策略收益

**Attribution**:
把 Trade Episode 的结果分解到市场方向、策略选择、仓位、执行、成本、保护和外部条件等来源的解释。
_Avoid_: 因果证明、盈亏汇总、Reflection

**Counterfactual Review**:
比较实际 Trade Episode 与一个明确替代决策路径，以检验某项选择是否实质影响结果。
_Avoid_: 后见之明、Counterfactual Test Run、情景想象

**Review Finding**:
Trade Review 中由现有事实直接支持的观察结论。
_Avoid_: Reflection、Lesson、改进任务

### Reflection and lessons

**Reflection**:
Trade Review 对原因、失效机制或改进方向提出的未经充分验证解释。
_Avoid_: Review Finding、Validated Lesson、知识

**Lesson Candidate**:
具有明确主张、适用范围、反例和验证方法的 Reflection。
_Avoid_: Validated Lesson、策略规则、普通笔记

**Lesson Validation**:
使用独立 Episode、历史相似样本、反事实或实验来检验 Lesson Candidate 的过程。
_Avoid_: Strategy Promotion、人工同意、重复复盘

**Validation Evidence**:
Lesson Validation 产生、可追溯且同时保留支持与反对结果的证据。
_Avoid_: Research Evidence、Review Finding、审批记录

**Validated Lesson**:
达到预定证据门槛、带置信度、反例、适用范围与有效期限的可复用经验；是否默认可用仍由 Governance 决定。
_Avoid_: Reflection、永久真理、Active Strategy

**Lesson Applicability**:
Validated Lesson 被证据支持的市场、Regime、策略、时间尺度和其他适用边界。
_Avoid_: 搜索过滤器、通用经验、Activation Scope

**Lesson Conflict**:
两个或更多 Lesson 对同一适用范围提出不相容主张的显式关系。
_Avoid_: 静默覆盖、版本更新、低置信度

**Lesson Decay**:
随着市场时间、制度或新反证变化，Validated Lesson 的证据权重降低。
_Avoid_: 删除 Lesson、固定过期日、模型遗忘

**Experience Memory**:
由可追溯 Trade Episode、Reflection 和 Lesson 组成的经验集合，并保留每类内容不同的证据等级。
_Avoid_: Chat History、向量数据库、Prompt
