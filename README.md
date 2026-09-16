# futures-agent-os

一个完全独立的期货智能研究与模拟交易绿地项目。系统目标是让受约束的 Agent 自主发现机会、研究、模拟交易、盯盘与复盘；交易真值和风险许可始终由确定性内核掌握。

当前阶段：V5 受限研究模拟；V0–V5 Exit 均已通过，MVP Closure 为 `MVP_ACCEPTED`。当前允许 SHFE AG/CU 研究范围的本地模拟运行，CZCE、Q3/Q4 决策数据、Paper/L5 和真实交易仍关闭。

## 本地开始

要求：Python 3.14、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync --locked
uv run futures-agent-os health
uv run futures-agent-os trial --at 2026-09-14T01:00:00Z
uv run futures-agent-os research --limit 1
uv run pytest
```

也可以运行：

```bash
make check
```

`trial` 会在内存中运行一次完整的研究到模拟交易周期，输出确定性成交、保护、结算、复盘和 Decision Journal 结果。它不连接交易所、不发送真实订单，也不需要外部凭据；省略 `--at` 时使用当前 UTC 时间，传入固定时间可重复结果。

`research` 默认只生成绑定当前 manifest 的 SHFE AG/CU 研究运行计划；增加 `--execute` 才调用配置的研究模型。该入口不读取 CZCE 数据，不产生 Order、Fill、Position 或账本副作用。

飞书长连接以 `uv run futures-agent-os gateway run` 启动。正式入口会处理“状态”“运行模拟”“复盘”三个有界文本命令，并将最近一次合成模拟 artifact 保存在 `.runtime/operator/` 供重启后复盘；暂停、撤销和 Kill Switch 不能通过自由文本触发，只能使用系统预签发的一次性控制卡片。

启动前可用 `uv run futures-agent-os gateway doctor --config /absolute/path/to/local-config.toml` 做只读检查。它会核对 PostgreSQL 可达性、migration head、Feishu 身份映射和 inbound/outbox 队列；transport 连通性仍需看网关运行日志或已有连接确认，不会被配置存在误报为在线。长期运行可使用 `scripts/run_local_gateway.py --config ... --state-dir ...`，它提供单实例锁、信号收尾和稳定错误码，适合交给本机进程托管器。

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
产品运行时 V1–V5 的 LLM workload、模型 Profile 与升级规则见 [`docs/LLM-SCENARIO-AND-MODEL-ROUTING.md`](docs/LLM-SCENARIO-AND-MODEL-ROUTING.md)。

## 产品边界

- 仅用于研究与模拟交易，不接入真实资金或真实下单。
- 默认是个人自用、单用户、可信本机部署；对抗性本地防篡改、多租户和零信任安全加固不作为默认开发目标，具体边界见 [`docs/SECURITY-THREAT-MODEL.md`](docs/SECURITY-THREAT-MODEL.md)。
- 旧 `futures_workflow` 仅是 donor，不得成为运行时依赖。
- Agent 不得直接创建 Order、Fill、Position 或 LedgerEntry。
- 风控、执行、账本、保护与恢复必须可在没有 LLM 的情况下确定性运行。

## 许可证

MIT，见 [LICENSE](LICENSE)。
