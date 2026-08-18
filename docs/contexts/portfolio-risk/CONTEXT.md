# Portfolio & Risk

本上下文把账户、持仓、在途订单和候选 Trade Plan 解释为组合暴露，并对新增或变化中的风险作出不可绕过的裁决。它拥有风险许可与限制，但不撮合订单，也不计算账本真值。

## Language

### Portfolio

**Portfolio**:
在同一资本与风险目标下共同管理的一组策略、持仓和候选暴露。
_Avoid_: Simulation Account、Position 列表、Watchlist

**Portfolio Snapshot**:
在明确时点汇总 Portfolio 的持仓、资金引用、在途订单、暴露和风险预算状态的不可变视图。
_Avoid_: Account Snapshot、持仓查询、Market Snapshot

**Target Portfolio**:
Portfolio 在考虑现有暴露与候选计划后希望达到的整体风险结构。
_Avoid_: Target Exposure、当前持仓、Order List

**Strategy Allocation**:
Portfolio 授予某个策略在指定范围内使用资本和风险预算的份额。
_Avoid_: Position Size、保证金、策略权重指标

**Gross Exposure**:
不抵消相反方向后汇总的绝对风险暴露。
_Avoid_: Margin、Net Exposure、名义本金

**Net Exposure**:
按明确风险维度抵消相反方向后剩余的组合暴露。
_Avoid_: Gross Exposure、单一 Position、对冲有效性

**Concentration**:
Portfolio 风险集中于同一 Variety、方向、期限、行业或相关性来源的程度。
_Avoid_: Position 数量、Correlation Cluster、持仓上限

**Correlation Cluster**:
基于共同风险行为被视为同一集中度来源的一组暴露。
_Avoid_: 行业分类、Strategy Group、固定相关系数

**Portfolio Proposal**:
对候选 Target Exposure 作出的接受、缩减、替代、对冲或拒绝建议，尚不是风险许可。
_Avoid_: Risk Decision、Trade Plan、Order Plan

### Risk authority

**Risk Budget**:
Portfolio、策略或 Trade Plan 在指定范围和时段内可以承担的最大损失或暴露额度。
_Avoid_: Margin、Available Funds、止损距离

**Risk Budget Reservation**:
为一个候选 Plan Version 原子占用、带有效期且可缩小、消费、释放和对账的临时 Risk Budget 份额，用于防止并发计划合计突破组合上限。
_Avoid_: Risk Decision、Position、Margin Reservation、Authorization Basis

**Risk Policy**:
一组有明确适用范围、有效期和版本的风险限制与处置规则。
_Avoid_: Contract Rule、策略参数、风险建议

**Risk Constitution**:
当前有效且所有交易意图都必须遵守、不能被用户普通指令、Agent 或策略绕过的 Risk Policy 集合。
_Avoid_: Risk Agent、风险报告、单条限额、Simulation Autonomy Mandate

**Risk Assessment**:
对一个 Portfolio 或 Trade Plan 的损失来源、脆弱性和压力情景所作的分析性判断。
_Avoid_: Risk Decision、Risk Constitution、保证金计算

**Risk Decision**:
Risk Constitution 对具有效 Autonomy Gate Receipt 与 Risk Budget Reservation 的具体 Plan Version 给出的 APPROVE、MODIFY、REJECT、PROTECT_ONLY 或 HALT 事实，并绑定所依据的组合、快照与规则版本。
_Avoid_: Plan Approval、Simulation Autonomy Mandate、Authorization Basis、Portfolio Proposal、风险意见

**Immutable Risk Ceiling**:
Risk Decision 冻结的最大允许风险边界，后续普通管理只能保持或收紧。
_Avoid_: 当前止损、Risk Budget、建议仓位

**Protection Mandate**:
Risk Decision 对获准暴露必须具备的保护范围、最大损失和持续有效性要求。
_Avoid_: Stop Policy、Exit Intent、止损建议

**Risk Breach**:
实际或预计 Portfolio 状态超出有效 Risk Policy 的事实。
_Avoid_: 亏损、告警、Risk Reject

**Margin Headroom**:
在当前保证金占用与限制下，Portfolio 仍可承受的保证金空间。
_Avoid_: Available Funds、Risk Budget、可开手数

**Kill Switch**:
阻止新增风险并按预定范围处置既有风险的最高优先级风险状态。
_Avoid_: 暂停策略、No Trade、系统关机
