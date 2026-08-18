# Governance & Registry

本上下文记录哪些策略、模型、Prompt、数据集、Lesson 和风险政策版本具备何种使用资格，并控制其晋升、启用、回滚与退役。它不生成研究结论，也不把技术部署事实等同于业务启用。

## Language

### Governed artifacts

**Governed Artifact**:
必须经过版本、证据与权限治理才能在系统中使用的对象，包括 Strategy、Agent、Model、Prompt、Toolset、Dataset、Lesson 和 Risk Policy。
_Avoid_: 任意文件、开发任务、运行结果

**Artifact Version**:
一个 Governed Artifact 内容固定、可独立引用且不可被静默改写的版本。
_Avoid_: 最新版本、代码提交、编辑历史

**Registry Entry**:
Registry 对一个 Artifact Version 的身份、来源、资格、状态和适用范围所保存的权威记录。
_Avoid_: 文件目录、实验记录、Deployment

**Registry**:
对同一类 Governed Artifact 及其版本关系和使用资格进行权威登记的业务目录。
_Avoid_: 数据库表、搜索索引、Artifact 仓库

**Artifact Lineage**:
一个 Artifact Version 与其前身、输入证据、产生过程和派生版本之间的可追溯关系。
_Avoid_: Git History、Evidence Chain、依赖列表

**Candidate Version**:
已登记但尚未获得目标使用资格的 Artifact Version。
_Avoid_: 草稿文件、Active Version、Strategy Candidate 专属含义

### Qualification and activation

**Qualification Level**:
Artifact Version 被允许用于研究、回放、前向模拟或其他指定场景的资格等级。
_Avoid_: 环境名称、版本号、用户权限

**Autonomous Simulation Qualification**:
一个 Strategy、Agent、Model、Prompt 或 Toolset Version 在证据、评测与安全门槛上达到可被 Simulation Autonomy Mandate 引用的资格，不自动产生具体账户的委托或交易许可。
_Avoid_: Simulation Autonomy Mandate、Activation、Plan Approval、Risk Decision

**Promotion Gate**:
Artifact Version 获得更高 Qualification Level 前必须满足的证据、评测、审批和风险条件。
_Avoid_: 自动测试、单一阈值、Risk Decision

**Promotion Decision**:
对 Candidate Version 提升、维持或降低 Qualification Level 的治理事实。
_Avoid_: Backtest 通过、Plan Approval、Deployment

**Change Approval**:
有权角色对 Governed Artifact 的晋升、启用、回滚或退役作出的正式同意或拒绝。
_Avoid_: Plan Approval、代码评审、口头确认

**Activation**:
让合格 Artifact Version 在明确 Activation Scope 内成为可用版本的独立治理决定。
_Avoid_: Merge、Deployment、开发完成

**Activation Scope**:
Activation 对账户、策略、Agent、市场、用户、时间或运行模式的适用边界。
_Avoid_: Lesson Applicability、用户权限、全局默认

**Rollback**:
撤销当前 Activation 并恢复到先前合格版本的治理决定，同时保留原使用历史。
_Avoid_: Git Revert、删除版本、故障重试

**Deprecation**:
Artifact Version 不再允许用于新的目标范围、但历史引用仍保持有效的治理状态。
_Avoid_: 删除、过期缓存、Rollback

**Revocation**:
因安全、证据失效或重大缺陷立即取消 Artifact Version 使用资格的治理决定。
_Avoid_: Deprecation、暂停任务、Risk Reject

### Change governance

**Improvement Proposal**:
对策略、模型、Prompt、数据、风险政策或系统能力变更提出的正式建议，包含范围、证据需求和风险。
_Avoid_: Lesson Candidate、开发任务、用户反馈

**Evidence Sufficiency**:
候选版本所附证据是否满足其目标 Promotion Gate 的治理判断，不表示证据内容必然为真。
_Avoid_: Research Evidence、模型准确率、人工信任

**Separation of Duties**:
要求提案、验证、批准和启用中的关键决定不能由同一未受约束权限自动完成的治理原则。
_Avoid_: 多 Agent 投票、多人账号、代码 Owner

**Governance Audit**:
对 Governed Artifact 的提案、证据、批准、资格和 Activation 历史形成的完整可追溯记录。
_Avoid_: 运行日志、交易审计、聊天记录
