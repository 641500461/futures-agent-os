# V5-010 模拟运行可靠性与灾备 Runbook

状态：active  
适用边界：单用户、可信本机、研究与模拟系统  
禁止事项：本 Runbook 不授权真实下单、真实资金操作或从恢复状态自动恢复新增风险。

## 1. 正式目标

### 1.1 SLO

所有 SLO 使用 `operations.SloMeasurementWindow` 绑定不可变 `MetricSample`，采用 nearest-rank 百分位；样本不足与超阈值都必须告警。告警必须含 `runbook_ref` 和 `impact_scope`。

| SLO | 指标 | 目标 | 最少样本 |
|---|---|---:|---:|
| Gateway 持久化 ACK | `gateway_ack_ms` p95 | ≤ 2000 ms | 20 |
| 风险预算预留 | `risk_reservation_ms` p95 | ≤ 200 ms | 20 |
| Final Receipt Gate | `final_receipt_gate_ms` p95 | ≤ 100 ms | 20 |
| Risk Constitution | `risk_constitution_ms` p95 | ≤ 200 ms | 20 |
| 保护循环 | `protection_loop_ms` p99 | ≤ 1000 ms | 20 |
| 关键 Outbox 写入 | `critical_outbox_write_ms` p95 | ≤ 2000 ms | 20 |
| 账本对账差异 | `ledger_reconciliation_difference` max | = 0 | 20 |

缺少一个完整测量窗不能解释为“无异常”。测试与故障注入证明计算、摘要、告警和 runbook 映射；V5-011 的真实一日连续运行负责积累 sim-prod 稳定性记录，不得用这里的合成越界样本宣称生产 SLO 达标。

### 1.2 容量与隔离

正式单机模拟 profile 为 `single-host-simulation:v1`：总 in-flight 64，固定保留 16 个关键槽；Protection、Settlement、Gateway、Outbox 可使用保留槽，Trading/Agent/Research 不可占用。逐类上限、backlog、速率和 burst 由 `standard_capacity_profile()` 固定。当前演练阈值如下：

| Workload | In-flight | Backlog | Rate/s | Burst |
|---|---:|---:|---:|---:|
| Protection | 16 | 1000 | 1000 | 100 |
| Settlement | 8 | 100 | 100 | 20 |
| Gateway | 16 | 1000 | 500 | 100 |
| Outbox | 8 | 1000 | 500 | 100 |
| Trading | 32 | 500 | 200 | 50 |
| Agent | 12 | 100 | 10 | 12 |
| Research | 8 | 50 | 2 | 8 |

处理顺序：backlog 达上限时 `SHED/BACKLOG_LIMIT`；后台工作触及关键保留线时 `DEFER/CRITICAL_RESERVE`；并发已满时 `DEFER/CONCURRENCY_LIMIT`；token 不足时 `DEFER/RATE_LIMIT` 并返回正数 `retry_after_ms`。研究任务不得通过增加 retry、并发或 worker 数绕过保护资源保留。

### 1.3 恢复目标

| 故障范围 | RPO | RTO | 恢复模式 |
|---|---:|---:|---|
| 单节点进程/数据库重启 | 已接受模拟命令 0 秒 | 60 秒 | `PROTECT_ONLY` |
| 主数据目录丢失/PITR | ≤ 300 秒；演练目标事务处为 0 秒 | 3600 秒 | `PROTECT_ONLY` |

正常 ACK 必须发生在本机 PostgreSQL WAL flush/事务提交后，因此单节点重启的已接受命令 RPO=0。跨故障域 RPO 由 base backup + 连续 WAL 归档决定；没有健康 WAL 归档时，不得声称 300 秒 RPO，也不得允许新增风险。灾备恢复后旧 Receipt 永不复用。

备份策略：每日一次 PostgreSQL base backup，连续归档 WAL，base backup manifest 做 SHA-256；每日备份保留 35 天、月末备份保留 12 个月。文件型本地模拟审计/订单/保护快照与对应 manifest 一并备份；每月运行一次恢复演练，任何失败产生 `ACTION_REQUIRED`。

## 2. 统一恢复门禁

任一重大故障先阻止新增风险，进入 `RECOVERING`，随后固定落在 `PROTECT_ONLY`。只有以下五项全部完成才允许提交人工恢复申请：

1. `DATABASE`：schema revision、backup manifest、目标时间/事务一致；
2. `LEDGER`：审计链可重放且 cash/position/PnL 平衡；
3. `OPEN_ORDERS`：本地命令、模拟 connector 与 Fill 精确对账；
4. `POSITIONS`：每个模拟持仓都有数量匹配的保护，未知状态按更保守值处理；
5. `CONNECTOR`：熔断器通过受限 half-open 探针并重新同步状态。

任何一项未知或失败都保持 `PROTECT_ONLY/HALTED`。人工批准也不能复用旧 Gate Receipt；每个新 Plan 必须重新经过当前 Snapshot、Basis、Reservation、Final Gate 与 Risk Constitution。

## 3. 主要故障 Runbook

### 3.1 PostgreSQL 主数据目录丢失

影响：全部模拟账户、任务、授权、审计和通知；禁止新增风险。  
触发：数据库不可达、存储损坏、恢复校验失败或 WAL archive 超过 RPO。

1. 进入 `RECOVERING`，暂停 Agent/Research/Trading 新任务；保护动作只使用最后一致快照。
2. 选择 manifest 校验通过的最新 base backup，读取连续 WAL；记录目标时间或事务 ID。
3. 恢复到新数据目录，不覆盖损坏目录；验证 Alembic revision、关键命令、audit chain 和 post-target 排除项。
4. 完成五项统一恢复门禁，保持 `PROTECT_ONLY`。
5. 只有人工根因记录、对账 Evidence 和治理批准齐备后才能恢复；所有旧 Receipt 失效。

演练命令：

```sh
uv run python scripts/run_v5_010_pitr_drill.py \
  --output evidence/v5-010/postgresql-pitr-drill-YYYY-MM-DD.json
```

脚本只创建临时 PostgreSQL 集群，开启真实 WAL archive，执行全量 migration、base backup、目标事务前后写入、PITR 与边界核对；不读取或修改现有数据库。该脚本的交易对账范围明确为 `EMPTY_TRADING_STATE`，会查询并证明无 ledger/order/position/connector 事实或活动 Receipt/Reservation；非空订单、账本和保护状态的崩溃恢复另由 V2 fault/replay 契约测试证明，不能把空状态 PITR 单独外推为非空业务恢复。

### 3.2 Queue/worker 过载

影响：扫描/研究延迟；若关键保留也耗尽则影响保护、结算或通知。  
触发：backlog、oldest age、in-flight 或 rate SLO 告警。

1. 先对 Research/Agent 执行 `DEFER/SHED`，不得借用 16 个关键保留槽。
2. 停止新回测和低优先级扫描；保留 Protection、Settlement、Gateway、Outbox。
3. oldest age 继续增长时阻止新增风险；检查 lease/fencing，禁止直接删除未知任务。
4. backlog 回落后按 idempotency key 重领；过时机会扫描标记 MISSED，不补发交易。

### 3.3 Paper connector 或外部依赖持续失败

影响：外部模拟订单状态未知；不得把 timeout 当成功。  
触发：连续失败达到 dependency policy 阈值。

1. 熔断器转 `OPEN`，拒绝新调用；已有仓位由确定性保护路径处理。
2. 标记 connector `DEGRADED/UNKNOWN`，阻止新增风险并通知 operator。
3. recovery timeout 后只允许 policy 数量的 half-open 探针；探针失败立即重新 OPEN。
4. 探针成功仍需本地/connector 双向订单与成交对账，才可关闭熔断；旧 Receipt 不复用。

### 3.4 账本不平或无保护暴露

影响：全部模拟交易，严重级别 CRITICAL。  
触发：ledger difference > 0、重复 Fill、position/protection 数量不一致。

1. 立即 `HALTED/PROTECT_ONLY`，禁止新增风险；确定性撤单/减仓/平仓优先。
2. 从不可变 Fill/Settlement audit chain 重放账户；不得直接编辑 projection 消除差异。
3. 订单、Fill、仓位、现金、保证金和保护逐项对账；未知 connector 状态保持 HALTED。
4. 记录根因和修复测试，人工治理批准后用新 Receipt 恢复。

### 3.5 SLO 数据缺失或越界

影响：见每个 objective 的 `impact_scope`。  
触发：测量窗样本不足或 nearest-rank 结果超阈值。

1. 产生带 objective、window digest、runbook 和 impact scope 的告警。
2. 保护/风险/账本 SLO 告警禁止新增风险；Gateway/Outbox 告警降级并保留可靠队列。
3. 不用平均值、缺失值或合并窗口掩盖尾延迟；恢复后重新建立完整测量窗。

## 4. 可复现演练与验收

```sh
uv run python scripts/run_v5_010_control_drills.py \
  --output evidence/v5-010/control-drills-YYYY-MM-DD.json
uv run python scripts/run_v5_010_pitr_drill.py \
  --output evidence/v5-010/postgresql-pitr-drill-YYYY-MM-DD.json
uv run pytest -q \
  tests/contract/test_v5_010_operational_reliability.py \
  tests/property/test_v5_010_operational_properties.py \
  tests/contract/test_v2_011_fault_injection.py \
  tests/contract/test_v2_010_replay.py
make check
```

验收 Evidence 必须保留：两份 drill JSON、精确 commit、上述命令输出和 `make check` 计数。PITR Evidence 必须同时出现 target 前保留项与 target 后排除项；只证明“服务能启动”不算恢复成功。
