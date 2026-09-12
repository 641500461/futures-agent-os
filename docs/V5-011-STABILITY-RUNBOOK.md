# V5-011 1 天稳定性运行手册

状态：COMPLETE（2026-09-12；冻结计划中的 `minimum_end_at` 已达到）

## 边界和验收

本运行只使用 `sim-prod` 模拟环境，不连接外部交易场所，不创建真实订单或真实资金授权。每个心跳都实际执行一条隔离的确定性模拟路径：L1 成交、重复 Fill 重放、持久审计日志重载与 hash-chain 校验、账本 replay/reconcile，以及每个未平仓 lot 的 active StopPolicy 检查。

运行至少跨越 1 个真实墙钟日。测试中的时间推进、历史回放、SLO 合成样本或手工修改日志均不能代替该时间要求。完成门禁要求整个 hash-chain 同时满足：

- 每个心跳至少产生 1 次模拟成交；
- 重复交易、无保护持仓、审计链断点和账本差额全部为 0；
- 健康检查无失败；
- 单次心跳间隔不超过 1 小时，累计超出固定 15 分钟 cadence 的 gap 不超过 6 小时；
- 所有超过两个 cadence 的 gap 都自动形成内联事故报告，记录发现、恢复、停机时长和稳定引用；
- 最后一个有效心跳和实际当前时间都达到 `minimum_end_at`，代码提交始终等于冻结提交。

任一业务不变量失败会永久阻断本次运行完成，不得删除或改写失败心跳。应保留日志、修复原因，并重新启动一轮完整的 1 天运行。

## 操作

运行目录使用 `.runtime/v5-011/<run-id>`，不进入 Git；最终通过后才将摘要、文件摘要和 chain head 固化到 `evidence/v5-011/`。

```bash
uv run python scripts/run_v5_011_stability.py start --directory .runtime/v5-011/current
uv run python scripts/run_v5_011_stability.py heartbeat --directory .runtime/v5-011/current
uv run python scripts/run_v5_011_stability.py status --directory .runtime/v5-011/current
uv run python scripts/run_v5_011_stability.py finalize \
  --directory .runtime/v5-011/current \
  --output evidence/v5-011/stability-run-<completion-date>.json
```

`start` 拒绝覆盖已有计划；同一 15 分钟 bucket 的重复心跳返回原记录，不追加第二效果。计划、每个心跳、前序 digest 和最终 evidence 均内容寻址。`finalize` 在任何时间不足、chain 异常、gap 超预算或模拟不变量失败时返回失败，不产生 Evidence。

## 故障处理

心跳超过 30 分钟后恢复时，追加操作自动生成 `HEARTBEAT_GAP` 事故记录；不得手工补造缺失时间点。先运行 `status` 查看稳定 reason code：

- `INVALID_HEARTBEAT_CHAIN` / `AUDIT_CHAIN_BREAK`：停止写入，复制运行目录做只读调查；不得修订原文件。
- `DUPLICATE_TRADE` / `UNPROTECTED_POSITION` / `LEDGER_DIFFERENCE`：保持研究与模拟边界，停止本轮验收并修复确定性 owner；修复后以新冻结提交重新开始 1 天。
- `SINGLE_GAP_BUDGET_EXCEEDED` / `TOTAL_GAP_BUDGET_EXCEEDED`：保留事故报告，本轮不能通过；恢复调度后从新计划重新计时。
- `MINIMUM_1_DAY_NOT_ELAPSED`：正常运行中状态，不是失败，不得提前 finalize。

完成后仍只能进入 V5-012 模拟系统评审，不代表允许真实交易。
