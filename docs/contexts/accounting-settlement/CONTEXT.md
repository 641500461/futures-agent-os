# Accounting & Settlement

本上下文根据成交、结算参考和有效费用规则，维护模拟账户的资金、持仓、保证金、盈亏和结算真值。所有更正通过新的账务事实表达，不由 Agent、Decision 或 Execution 直接改写。

## Language

### Accounts and ledger

**Simulation Account**:
承载模拟资金、持仓和结算结果的账户边界，不代表真实经纪账户。
_Avoid_: Portfolio、Strategy、Simulation Venue

**Experiment Account**:
专门隔离未晋升策略或受控实验结果的 Simulation Account，其实验身份不豁免账务或硬风险规则。
_Avoid_: 无限制账户、Experiment Run、Paper Trading

**Ledger**:
一个 Simulation Account 所有资金与持仓变化的完整账务事实集合。
_Avoid_: 当前余额、交易日志、审计日志

**Ledger Entry**:
由成交、费用、结算或更正产生的不可变账务事实。
_Avoid_: 数据库行、Fill、可编辑流水

**Correction Entry**:
用于纠正既有账务事实影响、同时保留原始历史的 Ledger Entry。
_Avoid_: 覆盖数据、删除错误、Data Revision

**Account Snapshot**:
在明确时点由 Ledger 汇总得到的资金、保证金、盈亏和持仓账务视图。
_Avoid_: Portfolio Snapshot、余额字段、Broker Statement

### Funds and positions

**Position**:
由 Fill 和 Settlement 形成的当前 Instrument 暴露及其账务数量。
_Avoid_: Trade Plan、Order、Target Exposure

**Position Lot**:
具有共同开仓来源、价格和交易日属性的一部分 Position，用于正确处理平仓、平今和费用。
_Avoid_: Partial Fill、整笔交易、策略仓位

**Available Funds**:
在当前账务与规则下未被冻结或占用、可用于承担新义务的模拟资金。
_Avoid_: Account Balance、Margin Headroom、Risk Budget

**Frozen Funds**:
因 Working Order、保证金或其他既有义务暂时不可用于新增义务的模拟资金。
_Avoid_: Margin Requirement、亏损、不可提现资金

**Margin Requirement**:
按适用 Contract Rule 和当前暴露计算的最低保证金义务。
_Avoid_: Frozen Funds、Risk Budget、保证金率

**Margin Occupancy**:
Simulation Account 当前因持仓和在途义务实际占用的保证金金额及比例。
_Avoid_: Margin Requirement、Margin Headroom、名义敞口

### Profit, loss, and settlement

**Realized PnL**:
已通过平仓、结算或其他完成事件确认的盈亏。
_Avoid_: Cash Flow、Unrealized PnL、总收益率

**Unrealized PnL**:
当前 Position 相对有效计价基础尚未通过完成事件确认的盈亏。
_Avoid_: Realized PnL、可用资金、预测收益

**Trading Fee**:
根据 Fill、开平属性和有效费率规则确认的账户费用。
_Avoid_: Execution Cost、Slippage、Margin

**Mark-to-Market**:
使用指定计价价格重新确认 Position 当期账面价值与盈亏的账务过程。
_Avoid_: Market Snapshot、实时 PnL 展示、Settlement

**Settlement**:
在 Trading Date 结束时，依据 Settlement Reference 和有效规则确认资金、保证金、持仓成本与当日盈亏的账务事实。
_Avoid_: 平仓、收盘、Settlement Reference

**Reconciliation**:
比较 Ledger 派生状态与独立成交、结算或账户证据，以确认账务完整性的领域过程。
_Avoid_: 单元测试、余额刷新、Trade Review
