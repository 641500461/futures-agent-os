# Market Intelligence

本上下文把带时点的参考市场数据解释为可讨论、可比较和可引用的市场状态。它描述环境与不确定性，但不选择策略、不产生 Trade Plan，也不授予交易许可。

## Language

### Market interpretation

**Market State**:
对特定 Instrument 或 Variety 在明确时点与时间尺度上的结构化环境描述，包含趋势、波动、流动性、期限结构和关键风险。
_Avoid_: 行情快照、涨跌预测、交易信号

**Regime**:
一类具有相对一致行为特征的市场环境，例如趋势、高波动、流动性压力或换月期。
_Avoid_: 趋势方向、策略、行情标签

**Regime Assessment**:
对某个时点属于哪些 Regime 的带依据判断，包含时间尺度、置信度和替代解释。
_Avoid_: Regime、确定分类、交易结论

**State Horizon**:
一个 Market State 试图描述的时间尺度，使日内、波段和长期状态不会被当成同一判断。
_Avoid_: 持仓周期、K 线周期

**State Confidence**:
Market Intelligence 对某项状态解释的证据支持程度，不表示交易胜率或可承担风险。
_Avoid_: 胜率、仓位权重、模型准确率

### Derived market views

**Feature Observation**:
某个已定义市场特征在特定快照上的取值及其适用范围。
_Avoid_: Factor、Signal、原始行情

**Term Structure**:
同一 Variety 不同到期 Instrument 之间的价格关系及其时点状态。
_Avoid_: Continuous Series、单一跨期价差、交易策略

**Liquidity State**:
对当前可成交深度、价差、交易活跃度和冲击风险的综合描述。
_Avoid_: 成交量、一定能成交

**Volatility State**:
对当前价格变动幅度及其相对历史位置的描述。
_Avoid_: ATR、风险预算、高波动策略

**Crowding State**:
对市场参与是否集中在相似方向或仓位的证据化描述，允许明确标记为未知。
_Avoid_: Open Interest、主观拥挤判断

**Market Catalyst**:
可能改变 Market State 的已识别事件或信息因素，但尚不表达方向性交易结论。
_Avoid_: 新闻、交易理由、确定原因

### Evidence

**Market Evidence**:
可被 Hypothesis 或 Trade Plan 引用、并能追溯到 Market Snapshot 与推导依据的市场结论。
_Avoid_: 观点、Lesson、原始数据

**Contradictory Market Evidence**:
对当前 Market State 或 Regime Assessment 构成实质冲突的市场证据。
_Avoid_: 风险提示、负面信息、普通噪声

**Intelligence Brief**:
在同一 State Horizon 下汇总 Market State、Regime Assessment、支持证据、冲突证据和未知项的市场解释对象。
_Avoid_: 研报、Trade Plan、Agent 回复
