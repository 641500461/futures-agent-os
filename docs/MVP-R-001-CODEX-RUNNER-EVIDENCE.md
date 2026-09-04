# MVP-R-001 Codex runner 资格证据

日期：2026-08-28  
状态：`QUALIFIED FOR DIAGNOSTIC/SHADOW — NOT A SUITE GO`

## 冻结身份

- workload：`research.hypothesis_synthesis`
- runner/auth：`CODEX_LOCAL + CHATGPT_SESSION`
- provider/model：`openai / gpt-5.6-terra`
- 默认 effort：`medium`；`high` 只保留为预注册诊断比较组
- SDK/固定 runtime：`openai-codex 0.147.0` / `openai-codex-cli-bin 0.147.0`
- 成本模式：`SUBSCRIPTION_UNAVAILABLE`；逐回合美元费用不伪造，预算以 token、turn、tool-call 和 wall-clock 控制

## 可复现命令

```bash
uv run python scripts/qualify_mvp_r_codex.py
uv run pytest -q tests/contract/test_model_routing_contracts.py tests/contract/test_mvp_r_validation_contracts.py
```

资格脚本不读取、不复制、不打印认证文件或 token；官方 SDK 仅复用本机已有 ChatGPT/Codex 登录态。每次调用使用独立 ephemeral thread、空临时工作目录、read-only sandbox、`approvalPolicy=never`、空 MCP 配置和显式拒绝审批 handler。

## 2026-08-28 实测

完整 11 工具探针同时注册：

`market_query`、`historical_query`、`feature_query`、`contract_query`、`memory_search`、`experiment_search`、`l0_signal_test`、`l1_bar_backtest`、`walk_forward_test`、`cost_slippage_stress`、`counterfactual_test`。

结果：

- App Server 报告 model `gpt-5.6-terra`、provider `openai`，`model/rerouted` 事件为零；
- 唯一 server request 为 `item/tool/call`；模型请求 `market_query`，参数为冻结的 `request_sha256`；
- item 类型只有 `userMessage`、`reasoning`、`dynamicToolCall`、`agentMessage`；
- usage：input `13,903`、cached input `13,056`、output `15`、reasoning output `0`、total `13,918`；
- 独立完整 conclusion-schema 探针成功，usage：input `13,080`、output `84`、total `13,164`；没有工具请求或 reroute；
- adapter 不保存 reasoning 内容；任何 command/file/web/MCP/collaboration 等内置工具 item、未知 server request、多工具请求、模型 reroute、usage 缺失或 schema 错误均转换为确定性失败码；
- 动态工具 handler 只记录一个 typed request，不执行研究逻辑；真实结果仍由 `SerialResearchLoop` 在参数授权后调用 V1-010 owner 签发的只读 `FrozenToolResultExecutor`，因此模型仍不是业务真值或工具执行权威。

## 资格边界

这份证据只使 runner Profile 可进入 diagnostic/shadow。它不替代授权真实 PIT dataset、真实 V1-010 result binding、30 diagnostic、50 holdout、10 次用户 shadow、阈值冻结或治理 `GO`。订阅 runner 不提供可核验的逐调用美元价格，因此不能用于要求精确货币成本比较的 suite；本 MVP-R suite 必须冻结为 token/time 成本口径。

## 2026-08-30 Pivot 后复验

Pivot grounding repair 后重新运行同一资格命令。资格脚本现对 tool schema 以原始 `parameters_json` 计算 digest，并把 App Server JSON list 冻结为项目 canonical tuple 后再签 Evidence；不读取或输出认证材料。结果为 SDK/CLI `0.147.0`、请求/实际模型 `gpt-5.6-terra`、provider `openai`、11 个注册工具、1 个动态工具调用、零 reroute、未超时、status `completed`，toolset digest `1fab0cdbbfa3739f4589c2ed920345d7e4b8d5d55630a764ccdf363c104f9906`。这再次只证明 runner transport/tool surface，不改变 suite Gate。
