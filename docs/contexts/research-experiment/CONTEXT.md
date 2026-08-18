# Research & Experiment

本上下文管理对市场规律的可证伪主张、策略定义、验证设计和研究证据。它可以产生候选策略与验证结论，但不授予交易许可，也不决定候选对象能否被正式启用。

## Language

### Questions and hypotheses

**Research Question**:
对尚不确定的市场关系、策略行为或失效原因提出的明确问题。
_Avoid_: 用户问题、Hypothesis、开发任务

**Hypothesis**:
关于特定条件与可观察结果之间关系的可证伪主张，包含适用范围与反证条件。
_Avoid_: 观点、Signal、Strategy Spec

**Evidence Requirement**:
在研究开始前声明何种观察会支持、削弱或否定 Hypothesis 的判定条件。
_Avoid_: 成功指标、回测结果、晋升门槛

**Feature Definition**:
对一个可重复计算的市场特征及其输入、时间尺度和含义的领域定义。
_Avoid_: Feature Observation、Factor、代码函数

**Factor**:
被研究为与未来收益、风险或市场状态相关的可比较特征。
_Avoid_: Feature Definition、Signal、指标数值

**Signal**:
由明确规则在特定时点产生的方向、强度或状态指示，不等于交易决定。
_Avoid_: Order、Trade Plan、Agent 建议

### Strategy language

**Strategy Spec**:
一个版本化的交易行为定义，明确适用市场、选择条件、入场、退出、失效、暴露与风险意图。
_Avoid_: Prompt、策略名、代码文件

**Strategy Candidate**:
拥有完整 Strategy Spec、关联 Hypothesis 和验证计划，但尚未取得指定使用资格的策略版本。
_Avoid_: Active Strategy、功能提案、回测结果

**Dataset Candidate**:
具有冻结 Dataset Snapshot、来源、质量和适用边界，拟申请成为受治理研究输入的数据集版本。
_Avoid_: Dataset Snapshot、查询结果、Experiment Run

**Benchmark Strategy**:
实验用于比较增量价值的预先指定基线行为。
_Avoid_: 最优策略、市场指数、默认参数

### Experiments and evidence

**Experiment Design**:
在观察结果前冻结的验证方案，规定对象、基线、数据范围、评价方法和失败判据。
_Avoid_: Experiment Run、临时尝试、任务配置

**Experiment Run**:
一个 Experiment Design 在固定版本输入上的单次执行事实。
_Avoid_: Experiment Design、研究结论、运行任务

**Backtest Run**:
某个 Strategy Spec 在固定历史数据、规则、成本和评价条件下的一次 Experiment Run。
_Avoid_: 回测结论、策略有效、历史收益证明

**Forward Experiment**:
在 Strategy Spec 冻结后，只使用随后到达市场数据进行的模拟观察。
_Avoid_: 样本外回测、Paper Account、实盘

**Walk-forward Evaluation**:
按时间顺序重复训练或选择与后续验证，用于检查策略能否在滚动未知区间保持表现。
_Avoid_: 普通样本外、全样本优化、Forward Experiment

**Stress Test**:
在预先定义的极端市场、成本、流动性或规则条件下检查策略脆弱性的实验。
_Avoid_: 高波动回测、Monte Carlo、Risk Decision

**Counterfactual Test**:
通过改变一个明确决策或条件，比较实际路径与替代路径差异的实验。
_Avoid_: 情景描述、事后解释、参数扫描

**Research Evidence**:
由已完成 Experiment Run 产生、可追溯并带局限说明的研究证据。
_Avoid_: 未来有效证明、Promotion Decision、研究意见

**Parameter Robustness**:
策略表现对合理参数扰动保持稳定的程度，而不是单一最优点的高表现。
_Avoid_: 参数寻优、最好参数、单次敏感性结果

**Evidence Package**:
围绕一个 Hypothesis 或 Strategy Candidate 汇集支持、反对、稳健性和适用边界的证据集合。
_Avoid_: 实验报告、Registry Entry、审批材料
