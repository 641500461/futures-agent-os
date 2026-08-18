# Execution & Simulation

本上下文把同时具有有效 Authorization Basis、单用途 Autonomy Gate Receipt、Risk Budget Reservation 与 Risk Decision 的新增风险意图转换为模拟订单；也独立校验已有暴露的 Risk Reduction Request/Protection Trigger，并在 T4-SAFE 通过后创建 Protective Risk Action。它拥有降险校验、保护动作、订单与成交过程，但不拥有 Simulation Autonomy Mandate、风险预算、账户余额、持仓或结算真值。

## Language

### Execution intent

**Execution Plan**:
在 Trade Plan、Authorization Basis、Autonomy Gate Receipt、Risk Budget Reservation、Risk Decision 和当前可执行状态约束下，将获准目标暴露转换为一个或多个订单意图的计划。
_Avoid_: Trade Plan、Order、Portfolio Proposal

**Execution Instruction**:
Execution Plan 中对单个 Instrument、方向、数量、订单条件和时效的明确执行意图。
_Avoid_: Order、Signal、自然语言命令

**Execution Episode**:
从接受一份有效 Execution Plan 到其完成、取消、失败或失效的一次执行过程。
_Avoid_: Decision Episode、Trade Episode、Agent Run

### Orders and fills

**Order**:
向 Simulation Venue 请求按特定条件买卖某个 Instrument 的执行对象，具有独立生命周期。
_Avoid_: Trade、Fill、Execution Instruction

**Working Order**:
已被 Simulation Venue 接受、仍可能产生 Fill 或接受撤销的 Order。
_Avoid_: Pending Task、未成交意图、Position

**Time in Force**:
Order 在何种时段或条件下保持有效的交易语义。
_Avoid_: Plan Expiry、持仓周期、任务超时

**Cancel Request**:
要求终止 Order 尚未成交部分的执行请求，不撤销已经产生的 Fill。
_Avoid_: Order Rejection、删除订单、平仓

**Fill**:
Order 实际成交的一部分或全部，是带价格、数量和事件时点的不可变执行事实。
_Avoid_: Order、触发价、参考价

**Partial Fill**:
Order 只有部分剩余数量转化为 Fill、且仍存在未成交部分的执行状态。
_Avoid_: 分批下单、完整成交、Position Lot

**Order Rejection**:
Simulation Venue 因明确执行条件不满足而拒绝接受 Order 的事实。
_Avoid_: Risk Reject、No Trade、系统错误

### Simulation semantics

**Simulation Venue**:
按照声明的市场与执行语义接受 Order 并产生 Fill 的模拟交易环境。
_Avoid_: Simulation Account、Backtest、真实交易所

**Matching Model**:
Simulation Venue 用于判断 Order 是否、何时、以何价格和数量成交的声明性市场假设。
_Avoid_: 撮合代码、Cost Model、真实成交保证

**Fidelity Level**:
Simulation Venue 所采用行情粒度和成交语义的明确真实性等级。
_Avoid_: 回测质量、策略可信度、性能等级

**Liquidity Constraint**:
在指定市场状态下限制可成交价格、数量或时点的市场条件。
_Avoid_: Risk Limit、成交量指标、订单拒绝

**Slippage**:
Fill Price 与预先声明参考价格之间、由执行条件产生的差异。
_Avoid_: Fee、亏损、预测误差

**Execution Cost**:
由价差、Slippage、冲击和执行机会损失形成的交易执行代价。
_Avoid_: Exchange Fee、Margin、总 PnL

**Paper Trading**:
使用到达中的市场数据驱动 Simulation Venue、但不向真实经纪账户发单的前向执行模式。
_Avoid_: Historical Backtest、真实交易、Experiment Account

### Protection

**Risk Reduction Validation**:
Execution & Simulation 针对 Risk Reduction Request 或 Protection Trigger，读取最新 Position、Protection Mandate/Kill Switch 与 expected version，确定性判断目标是否只会撤销未成交风险、降低/关闭现有暴露且不反向、不放宽保护的校验事实。
_Avoid_: Risk Decision、Risk Assessment、Agent 审批

**Protective Risk Action**:
在已有 Position 和 Protection Mandate/Kill Switch 下，经确定性证明只能取消未成交风险、减少或关闭现有暴露的幂等执行事实；它不得反向开仓或放宽保护。
_Avoid_: Trade Plan、Risk Decision、普通 Order、Agent 自由命令

**Stop Policy**:
把 Protection Mandate 转化为覆盖全部剩余暴露的可执行退出约束。
_Avoid_: Invalidation、Protection Intent、止损建议

**Protection Trigger**:
Stop Policy、Risk Breach 或 Kill Switch 条件满足后产生的强制执行事实。
_Avoid_: Agent 建议、行情提醒、Fill

**Protection Order**:
由 Protection Trigger 产生、用于减少受保护暴露的 Order。
_Avoid_: 普通退出建议、止损价、已完成保护

**Unfilled Protection Exposure**:
Protection Trigger 已发生但 Protection Order 尚未完全成交时仍然存在的暴露。
_Avoid_: 无保护 Position、订单失败、已平仓
