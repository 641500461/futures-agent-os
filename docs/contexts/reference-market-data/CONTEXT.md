# Reference Market Data

本上下文管理系统从交易所或数据供应方采用的带时点市场事实，包括合约标识、交易日历、交易规则、行情观测和结算参考。它不解释市场状态，也不产生研究或交易结论。

## Language

### Instruments and calendars

**Exchange**:
期货合约挂牌并定义其标识命名空间的交易所，例如 SHFE 或 DCE。
_Avoid_: 市场、数据源、交易通道

**Variety**:
共享交易标的与基础制度的一组期货合约，例如铁矿石 I。
_Avoid_: Instrument、板块、品种代码字符串

**Instrument**:
可被观察或交易的具体期货合约，具有唯一交易所、Variety 和到期标识。
_Avoid_: Variety、Continuous Series、股票代码

**Contract Delivery Code**:
交易所赋予具体 Instrument 的到期标识。它是注册事实；三位代码不自行推断所属年代。
_Avoid_: 当前年份推算的到期月、连续合约代码

**Instrument Alias**:
在明确交易所、有效区间、版本与来源下指向一个参考对象的外部标识。它不因字符串形状自动获得含义。
_Avoid_: 永久代码、供应商默认映射

**Contract Chain**:
同一 Variety 按到期顺序排列的一组有效 Instrument。
_Avoid_: Continuous Series、持仓组合、跨期策略

**Dominant Contract**:
在明确判定方法和有效区间下，被指定为某一 Variety 主要活跃合约的 Instrument。
_Avoid_: Continuous Series、永远的主力、近月合约

**Dominant Contract Reference**:
在一个有效区间内把 Variety 指向具体 Instrument 的带来源主力映射。
_Avoid_: 可交易的品种代码、Continuous Series、永久主力

**Continuous Series**:
按明确换月和调整规则拼接的研究价格序列，不是可直接成交的 Instrument。
_Avoid_: Dominant Contract、真实合约、可交易代码

**Trading Date**:
交易所归属一段交易活动的业务日期，夜盘的 Calendar Date 可能与其不同。
_Avoid_: Calendar Date、自然日、结算时间

**Trading Session**:
某个明确 Variety 或 Instrument 在一个 Trading Date 内允许特定交易活动的时间区间；交易所相同不意味着时段相同。
_Avoid_: 交易所级默认时段、K 线区间、系统运行时间、持仓周期

**Trading Calendar**:
交易所对 Trading Date、Trading Session、节假日和特殊休市安排的带版本事实集合。
_Avoid_: 普通日历、Cron、市场是否活跃的猜测

**Session Phase Occurrence**:
一个在 Asia/Shanghai 时区内以明确起止时点给出的集合竞价、连续交易或休市阶段；它归属某一明确 Trading Date，不是按工作日重复的模板。
_Avoid_: 固定开收盘时段、自然日推断、系统任务窗口

**Calendar Closure**:
交易所对一个明确 Calendar Date 发布的节假日或临时全日休市事实。
_Avoid_: 没有来源的“周末不开盘”规则、策略暂停

**Calendar Revision**:
以唯一身份和来源可见时点记录的日历事实更正；它必须明确指出被替代的先前事实，使旧 as_of 可回放而不是按列表顺序选择最新值。
_Avoid_: 就地覆盖、隐式闭市优先、最新记录优先

**Calendar Reference Event**:
发生在明确 Trading Date、只指向其他权威参考事实的日历事件，例如主力切换、临近交割或规则调整；它不拥有或解释被指向事实。
_Avoid_: Dominant Contract、交割限制、Contract Rule

### Rules and observations

**Contract Rule**:
在明确有效区间内适用于 Instrument 或 Variety 的交易、费用、保证金和交割约束集合。
_Avoid_: 永久参数、默认保证金、Risk Policy

**Contract Rule Version**:
带唯一版本、适用 Trading Date 区间与来源说明的一组不可变 Contract Rule 事实；后续修订创建新版本，而不改写历史版本。
_Avoid_: 当前默认参数、Risk Policy、可变配置项

**Rule Resolution**:
在指定 Instrument、Trading Date 和 as_of 下选出的唯一可见 Contract Rule Version 及其来源证据。
_Avoid_: 最新规则、金额计算结果、风险许可

**Contract Status**:
Instrument 在指定时点是否可挂牌、开仓、平仓、停牌或进入交割限制期的交易所状态。
_Avoid_: Market State、策略暂停、流动性判断

**Market Observation**:
数据源在特定事件时点发布的价格、数量、成交、持仓量或盘口事实。
_Avoid_: Market State、Feature Observation、交易信号

**Market Snapshot**:
为某一用途在明确 `as_of` 时点冻结的一组 Market Observation、规则引用和质量声明。
_Avoid_: 最新行情、Market State、缓存副本

**Settlement Reference**:
交易所或授权来源为特定 Instrument 与 Trading Date 发布的结算价格及关联规则事实。
_Avoid_: Settlement、收盘价、账户估值

### Data trust

**Data Provenance**:
一项参考事实来自何处、何时取得以及经历何种来源修订的可追溯说明。
_Avoid_: 数据库记录、引用链接、Agent 解释

**Data Quality Status**:
一组参考事实在完整性、新鲜度、一致性和预定用途上的质量结论。
_Avoid_: 接口成功、数据存在、Market Confidence

**Data Revision**:
来源方对已发布参考事实作出的带时间和原因的后续更正，不覆盖原事实的历史可见性。
_Avoid_: 数据清洗、静默覆盖、账务更正

**Dataset Snapshot**:
为研究或重放冻结的参考数据版本集合，保持当时可见内容及其来源边界。
_Avoid_: CSV 文件、查询结果、Experiment Run
