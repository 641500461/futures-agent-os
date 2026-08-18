---
status: accepted
---

# 从首个持久化版本开始使用 PostgreSQL

## Context

新系统从早期就需要持久 Agent checkpoint、异步研究任务、inbox/outbox、任务租约、审批、交易状态、审计事件和多个 worker 的并发协调。先使用 SQLite 再迁移 PostgreSQL 会制造两套事务、锁、JSON、时间和并发语义，并在 Agent 与交易闭环形成后引入一次高风险数据库迁移。

## Decision

所有具有持久状态的产品版本从第一天使用 PostgreSQL 作为业务当前态、追加审计、inbox/outbox、任务租约和 Agent checkpoint 的权威数据库。产品运行时不提供 SQLite 持久模式；纯领域单元测试可使用内存对象，集成测试使用隔离 PostgreSQL 实例。大体量 bars、ticks、order books 和报告 artifact 继续存放在 Parquet/对象目录等适合的存储中，PostgreSQL 保存 manifest、引用和业务元数据。

## Consequences

- 开发初期即需容器化或受管 PostgreSQL、schema migration、备份恢复和连接治理。
- 所有环境共享同一事务和并发语义，避免后期从 SQLite 迁移关键状态。
- PostgreSQL 不被当作全部市场大数据仓库；需要同时维护对象数据的完整性、hash 和 manifest。
- 本地离线开发的启动成本略高，但多 worker、checkpoint、租约和原子 outbox 可以按目标形态直接验证。

## Considered Options

- 先 SQLite、达到多 worker 后再迁移：拒绝，因为绿地项目没有承担过渡迁移风险的必要。
- 从第一天引入独立消息中间件：暂不采用；先使用 PostgreSQL 事务队列与租约，达到明确吞吐门槛后再评估。
