# futures-agent-os

一个完全独立的期货智能研究与模拟交易绿地项目。系统目标是让受约束的 Agent 自主发现机会、研究、模拟交易、盯盘与复盘；交易真值和风险许可始终由确定性内核掌握。

当前阶段：V1 自主研究与机会雷达；已完成 `V1-007`，下一任务为 `V1-008`。

## 本地开始

要求：Python 3.14、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked
uv run futures-agent-os health
uv run pytest
```

也可以运行：

```bash
make check
```

质量门禁的本地命令与 CI 完全相同：`make lock format lint type scan schema`，以及
`make test-unit`、`make test-property`、`make test-contract`。真实 PostgreSQL 验收使用
隔离数据库，例如：

```bash
FAO_DATABASE_URL='postgresql+psycopg://<local-user>@/futures_agent_os?host=/tmp' make test-integration
```

CI 使用无密码的临时 PostgreSQL `trust` 服务；本地连接串必须指向 disposable database。

健康检查只验证新项目自身，不读取 `/Users/qiu/futures_workflow` 的代码、配置或数据库。

## 仓库结构

- `apps/`：未来独立运行进程的入口边界。
- `src/futures_agent_os/`：按领域上下文组织的模块化单体。
- `schemas/`：Artifact、Tool、Event 与 API 契约。
- `migrations/`：新项目 PostgreSQL schema migration。
- `tests/`：单元、契约、集成、回放、故障与 Agent eval。
- `datasets/`：合成数据与 manifest，不承接旧系统运行状态。
- `docs/`：PRD、技术方案、架构、ADR、上下文地图、Roadmap 与交接记录。

开发进度只以 [`docs/ROADMAP.md`](docs/ROADMAP.md) 为准，跨任务交接先阅读 [`docs/HANDOFF.md`](docs/HANDOFF.md)。
开发任务的模型选择与升级规则见 [`docs/DEVELOPMENT-MODEL-POLICY.md`](docs/DEVELOPMENT-MODEL-POLICY.md)。

## 产品边界

- 仅用于研究与模拟交易，不接入真实资金或真实下单。
- 旧 `futures_workflow` 仅是 donor，不得成为运行时依赖。
- Agent 不得直接创建 Order、Fill、Position 或 LedgerEntry。
- 风控、执行、账本、保护与恢复必须可在没有 LLM 的情况下确定性运行。

## 许可证

MIT，见 [LICENSE](LICENSE)。
