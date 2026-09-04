# MVP-R-003 真实研究闭环纵向验证执行方案

文档版本：`0.1-authorized-plan`  
任务：`MVP-R-003`  
状态：`IMPLEMENTED — V1 MEASUREMENT PROTOCOL FAILED`  
产品解释：2026-09-01 用户判定 v1 为测量方案失败，不能据此判定多 Agent 产品失败。v1 Evidence 保留，不得改写成通过。后继任务为 Roadmap `MVP-R-004`。  
授权日期：2026-09-01  
建议执行器：Cursor（当前脏工作区优先）或 Grok Build（形成基线 commit 后）  
产品边界：研究与模拟；无真实交易、模拟交易、账户、订单或账本副作用

## 1. 决定

`MVP-R-002` 停止并重定向，不继续扩大 qualification、receipt lineage、registry、execution lease、同进程反射对抗或 30/50/10 评测流水线。其代码、测试和失败 Evidence 保留为基础设施与负面经验，不删除、不覆盖，也不作为 `MVP-R-003` 的产品价值证据。

`MVP-R-003` 只回答一个一级产品问题：

> Research Agent 能否从真实 point-in-time 市场证据提出有信息量、可证伪且可执行的假设，经独立 Critic 筛选后运行真实 L0/L1 实验，并根据实验结果明确接受、拒绝或修改原判断？

本任务先做 8 个可人工审阅的 Discovery Episode。只有 Discovery Gate 显示真实增量，才另行预注册 30 diagnostic、50 sealed holdout 和用户 shadow；不得在价值信号出现前恢复大规模治理建设。

## 2. 为什么需要重定向

PRD 的 V1 用户价值是：

```text
市场证据
→ 可证伪 Hypothesis
→ 可执行 Experiment
→ 实验结果
→ independent Critic
→ candidate / reject / defer
→ 用户可理解的研究报告
```

`MVP-R-002` 实际把模型限制为封闭叙事类别，并由确定性代码预先固定研究问题、窗口变化和实验绑定。它可以验证“受治理的 Agent 简报是否优于模板”，但不能回答：

- Agent 是否发现了模板没有表达的研究方向；
- Agent 生成的实验能否实际运行；
- 实验结果是否真正改变 Agent 判断；
- 完整流程是否优于“单次通用模型 Prompt + 同样工具”。

因此 `MVP-R-002` 不能作为完整 Research MVP 的唯一 Gate，也不能单独解锁 `V1-011`。

## 3. 目标用户任务

用户或测试用例选择一个历史 PIT 市场时点。系统在一次同步、可重放、非交易的研究运行中完成：

```text
official PIT records + deterministic market state
→ Research Agent proposes 2–3 bounded executable hypotheses
→ deterministic hypothesis validator
→ independent Critic ranks/rejects hypotheses
→ deterministic experiment adapter instantiates exactly one plan
→ existing L0/L1/walk-forward/stress/counterfactual tools execute
→ result packet returns to Research Agent
→ final verdict: ACCEPT / REJECT / MODIFY / NEED_MORE_DATA
→ Markdown + JSON report compares pre-result claim with post-result verdict
```

`MODIFY` 只生成一个新版本 Hypothesis，不在同一 Episode 自动递归运行第二个实验。循环深度固定为一，避免重新进入无限 Agent 迭代。

## 4. 明确不做

- 不继续完成 `MVP-R-002` 的 full qualification 或冻结 suite。
- 不实现 `V1-011` 异步 Experiment Manager、scheduler、lease 或跨进程恢复。
- 不实现 Opportunity Radar、全市场扫描或自动调度。
- 不创建 StrategyCandidate、TradePlan、Order、Fill、Position、LedgerEntry。
- 不接真实资金、经纪商或模拟账户。
- 不让模型执行任意 Python、生成自由代码或访问网络。
- 不迁移或运行 `/Users/qiu/futures_workflow`。
- 不使用收益、胜率或单次表现自动宣布产品成立。
- 不因现有代码投入而放宽 Discovery Gate。

## 5. 必须保留的最小安全边界

以下约束继续作为硬门槛：

1. Agent 输入只能包含 `available_time <= as_of` 的 PIT 记录。
2. 数值来自确定性服务；模型不得无来源生成或改写数值。
3. 每个重要 claim 绑定 owner-produced source/tool-result reference。
4. Hypothesis、ExperimentPlan、ExperimentResult 和 FinalVerdict 使用版本化结构化 schema。
5. Agent/Critic 无交易、治理 Activation、数据库写入或任意代码执行能力。
6. Prompt、模型、数据、工具、代码 commit、token、时延和失败均记录。
7. 失败运行与被拒绝 Hypothesis 保留，不能静默删除或改写为成功。
8. 测试不联网；真实模型运行必须通过显式 CLI 参数单独触发。

以下已完成能力保留但不再作为 Discovery Gate 的阻断项：复杂 receipt lineage、append-only qualification registry、同进程反射对抗、inner/outer asset cross-proof、每 profile 15 份 qualification receipt 和多轮独立安全攻击验收。

## 6. 最小领域产物

### 6.1 `ResearchEpisodeInput`

至少包含：

- episode/instrument/as-of/market-cutoff/acquired-at；
- exact dataset、market snapshot、feature、rule、cost 和 toolset refs；
- 可用的注册信号原语与参数边界；
- market state、warnings、unknowns；
- `tradable=false`、`future_result_present=false`。

### 6.2 `HypothesisSpec`

Research Agent 每个 Episode 输出 2–3 个不同的候选，每个候选至少包含：

- stable hypothesis id/version；
- 注册的 hypothesis family；
- 适用 market/regime condition；
- 使用的注册 signal operator 与有限参数；
- 预期可观察结果；
- 明确 falsification condition；
- 支持证据、最强反证和未知；
- 可执行实验所需的 primary metric、control 和 cost assumption refs；
- `tradable=false`。

Agent 可以组合已注册原语并选择有限参数，但不能增加未知算子、自由生成代码、改写数据或自行声明实验通过。

### 6.3 `HypothesisValidation`

确定性 validator 对每个 Hypothesis 返回：

- `EXECUTABLE`、`UNSUPPORTED` 或 `DEFER`；
- stable reason codes；
- 参数、数据、窗口、metric、control 和成本是否可解析；
- 是否存在 future leak、重复假设或不可运行条件。

Validator 只判断是否可执行，不替 Agent 生成新假设。

### 6.4 `CriticReview`

独立 Critic 对通过 validator 的假设逐项给出：

- `SELECT`、`REJECT` 或 `DEFER`；
- 泄漏、成本、样本、Regime、反证、可证伪性和多重检验检查；
- 一个首选 Hypothesis，或明确零选择。

Critic 不能重写 Hypothesis，也不能扩大算子/参数范围。

### 6.5 `ExecutableExperimentPlan`

确定性 adapter 从被选 Hypothesis 实例化：

- PIT dataset、window、train/validation/test split、embargo；
- L0、L1、walk-forward、cost stress、counterfactual 的精确 request；
- baseline/control、primary metric、stop rule；
- engine/tool/config/code digests；
- `tradable=false`。

若无法完整实例化，Episode 显式 `DEFER`，不得人工补参数后冒充 Agent 成功。

### 6.6 `ExperimentResultPacket`

由现有确定性工具生成，至少包含：

- 每个 tool run 的状态、metrics、warnings 和 source refs；
- walk-forward/stress/counterfactual 是否完整；
- 数据/样本/成本限制；
- 结果内容摘要与完整 digest；
- 不包含 evaluator-only future 数据。

### 6.7 `ResearchFinalVerdict`

Research Agent 在读取结果后只能输出：

- `ACCEPT`：预注册门槛满足且没有阻断反证；
- `REJECT`：主要命题被证伪或成本/稳健性不成立；
- `MODIFY`：结果支持一个有界修订，并生成新版本 HypothesisSpec；
- `NEED_MORE_DATA`：结果不可判定且明确缺什么。

FinalVerdict 必须逐项对照实验前 Hypothesis、falsification condition 和实际结果。不得修改旧 Hypothesis、旧计划或门槛。

## 7. 实现架构

优先复用：

- `reference_market_data` 的 PIT records/snapshots；
- `market_intelligence` 的 feature/regime 事实；
- `research_experiment.validation_tools.DeterministicResearchTools`；
- V1-010 的 L0/L1、walk-forward、stress、counterfactual 契约；
- 已有官方 SHFE/CZCE 日线 materializer；
- provider-neutral model adapter 和结构化响应解析；
- 现有 canonical hash、source ref 和非交易检查。

建议新增小型 package，而不是继续扩张单个 `mvp_r_002.py`：

```text
src/futures_agent_os/research_experiment/mvp_r_003/
  contracts.py
  hypothesis_validator.py
  experiment_adapter.py
  runner.py
  evaluator.py
  report.py

scripts/run_mvp_r_003_demo.py
prompts/mvp-r/r003-hypothesis-v1.md
prompts/mvp-r/r003-critic-v1.md
prompts/mvp-r/r003-result-review-v1.md
tests/contract/test_mvp_r_003_contracts.py
tests/replay/test_mvp_r_003_vertical_slice.py
tests/agent_eval/test_mvp_r_003_eval_fixtures.py
```

实现必须是同步 vertical slice。不得为本任务预建通用 scheduler、distributed worker、完整 Registry 或运行启用系统。

## 8. Discovery 数据与 Episode

固定 8 个历史 PIT Episode：

- AG、CU、MA、SR 各 2 个；
- 覆盖趋势、震荡、反转、极端/噪声等不同状态；
- 使用已经治理的官方 SHFE/CZCE HTTPS 日行情；
- Agent 输入只到 market cutoff；
- Episode 选择规则与 manifests 在首个真实模型运行前固定；
- 8 个 Episode 可用于发现产品缺口，不用于最终泛化结论。

测试还必须包含至少 4 个合成反例：future leak、无来源数字、不可执行算子、交易请求。

## 9. 基线与消融

每个 Episode 生成四个可比较结果：

1. **Deterministic Template**：使用相同确定性输入与工具结果生成机械报告；
2. **Single-prompt Analyst**：一个普通模型 Prompt 读取相同 evidence + experiment results 后直接写最终报告；
3. **Research without Critic**：保留 Hypothesis → Experiment → Result → Verdict，但移除 Critic；
4. **Research + Critic + Result Feedback**：完整目标流程。

Single-prompt Analyst 必须获得相同事实和工具结果，不能被故意削弱。它用于回答：为什么需要 futures-agent-os，而不是一次普通模型调用。

## 10. Discovery Gate

### 10.1 工程硬门槛

- 8 个 Episode 至少 7 个无人工修复完整结束；失败必须显式保留。
- 至少 6 个 Episode 由 Agent 提出一个 validator 判定为 `EXECUTABLE` 的 Hypothesis。
- 所有被选 Hypothesis 的 ExperimentPlan 100% 可实例化并实际运行。
- future leak、无来源数字、未授权工具和交易副作用均为零。
- 4 个 Critical 反例 4/4 fail closed。
- 所有结果可从相同 PIT manifests 与配置重放确定性事实。
- `make check`、定向 contract/replay/agent-eval 和 `git diff --check` 通过。

### 10.2 结果敏感性门槛

- 对人工构造的“支持结果/反证结果”成对 fixture，FinalVerdict 语义变化率至少 80%。
- 反证结果下错误 `ACCEPT` 为零。
- FinalVerdict 100% 引用实验前 Hypothesis、falsification condition 和 owner-produced result refs。
- `MODIFY` 必须产生新版本 Hypothesis，不能改写原版本，也不自动运行第二轮。

### 10.3 Critic 增量门槛

- 对注入的不可执行、泄漏、成本缺失和不可证伪 Hypothesis，Critic 召回率至少 90%。
- Research + Critic 的坏 Hypothesis 进入实验率低于 Research without Critic。
- Critic 不能通过把全部结果变成 `REJECT/DEFER` 获得表面增量；clean Hypothesis 保留率至少 75%。

### 10.4 用户价值门槛

用户盲看 8 组报告：

- 完整流程相对 Single-prompt/Template 在“更能帮助决定下一步研究动作”上被偏好至少 6/8；
- 至少 6/8 无需额外解释即可理解；
- 至少 4/8 明显节省人工研究时间；
- 至少 3/8 促成继续实验、加入观察或排除想法的明确动作。

Discovery Gate 通过只表示值得进入正式 MVP eval，不等于 MVP-R `GO`，也不解锁 `V1-011`。

## 11. 停止规则

任一情况发生即记录 `STOP/PIVOT`，不得因已有投入自动扩大工程：

- 8 个 Episode 中少于 6 个产生可执行 Hypothesis；
- Agent 主要输出模板化改写，无法产生不同、可测的 Hypothesis；
- 实验结果不能稳定改变 FinalVerdict；
- Critic 没有降低坏 Hypothesis 进入实验的比例；
- 用户对完整流程的偏好低于 6/8；
- Single-prompt Analyst 在相同事实与工具下不劣于完整系统；
- 为修复 Discovery Gate 而需要重新引入大规模 qualification/governance 建设。

若最后一项成立，优先降级产品定位为“确定性研究系统 + LLM 报告解释器”，不要继续假设多 Agent 一定有价值。

## 12. 工作包与提交顺序

### WP0：稳定当前基线

目标：让外部执行器不会丢失当前约 2.9 万行未跟踪/未提交工作。

- 禁止 `git reset --hard`、`git clean`、`git checkout --` 或删除现有文件。
- 先检查并记录 `git status --short` 和当前 HEAD。
- 修复当前 capability evidence 导致的 secret-scan 高熵误报；只能通过明确的生成证据目录策略或安全 baseline 处理，不能关闭整个 secret scan。
- 运行 `make check` 与 `uv run pytest`。
- 在用户确认后形成一个可恢复的 baseline commit/branch，再使用 Git worktree 或 Grok multi-PR execution。

WP0 不重跑 capability probe，不继续修 `MVP-R-002`。

### WP1：契约与反例测试

- 先实现 6.1–6.7 的最小 schema 与 hydrate/serialize 测试；
- 加入 PIT、grounding、不可执行算子、结果不可改写和非交易反例；
- 不连接真实模型。

### WP2：同步实验 adapter 与 replay

- 将 `HypothesisSpec` 映射到现有 V1-010 工具；
- 跑通一个 deterministic fixture 的完整 ExperimentResultPacket；
- 证明相同输入重放得到相同确定性事实。

### WP3：三个模型 workload

- Hypothesis generation；
- independent Critic；
- result feedback/final verdict；
- 固定结构化 schema、预算、无工具或最小只读工具面；
- 先跑一个最小真实模型 smoke case。

### WP4：CLI 与报告

- 新增 `run_mvp_r_003_demo.py`；
- 默认 plan/fixture 模式不联网；
- `--execute-model` 才运行真实模型；
- 输出 JSON Evidence 与面向用户的 Markdown 报告；
- 报告清楚并列“实验前判断、Critic、实验结果、实验后改判”。

### WP5：8 Episode Discovery

- 冻结 Episode 选择与 manifests；
- 一次运行四个基线臂；
- 生成逐例报告和聚合 scorecard；
- 用户本人完成 8 组盲评；
- 记录 `PROCEED_TO_FORMAL_EVAL` 或 `STOP/PIVOT`。

不得在 WP5 结果出来后直接开始 `V1-011`。

## 13. 验证命令

外部执行器应根据实际文件名补齐定向命令，但最终至少执行：

```bash
uv run pytest tests/contract/test_mvp_r_003_contracts.py
uv run pytest tests/replay/test_mvp_r_003_vertical_slice.py
uv run pytest tests/agent_eval/test_mvp_r_003_eval_fixtures.py
uv run python scripts/run_mvp_r_003_demo.py --fixture tests/fixtures/mvp_r_003/episode-001.json
uv run pytest
make check
git diff --check
uv run futures-agent-os health
```

真实模型 smoke/discovery 命令必须单独记录，不能混入默认测试或 CI。

## 14. Evidence 要求

每个工作包记录：

- 实际执行器（Cursor/Grok/Codex）与精确模型、版本和 reasoning effort（若产品暴露）；
- commit、分支/worktree、开始/结束时间；
- 变更文件与没有实现的范围；
- 测试命令和完整结果；
- 数据 manifest、Prompt、schema、toolset、runtime digests；
- provider failure、人工修复和重试；
- 是否触及或改变安全边界；
- 用户盲评原始结果。

“使用 Cursor”或“使用 Grok”不是质量证据；Acceptance、测试、可重放 Evidence 和用户判断才是。

## 15. 外部执行器选择

当前工作区包含大量未跟踪文件，而 Git worktree 只能从 commit 构建。因此推荐顺序是：

1. **先用 Cursor 在当前 checkout 执行 WP0**，它能直接看到现有脏工作区；
2. WP0 形成用户确认的 baseline commit 后，二选一：
   - 继续由 Cursor 依次完成 WP1–WP5；
   - 把本设计文档交给 Grok Build，使用 design/execute-plan 多 PR 流程；
3. 最终评审必须由未主导实现的模型/执行器完成，且不得仅相信实现者自报。

如果直接选择 Grok Build，必须让它操作当前 checkout，或先由用户明确创建包含未跟踪资产的 baseline commit；不要从当前 `HEAD` 新建 worktree 后误以为 `MVP-R-001/002` 文件不存在。

## 16. Cursor 执行提示

```text
请严格执行 docs/MVP-R-003-VERTICAL-SLICE-PLAN.md，从 WP0 开始，一次只完成一个工作包。

当前仓库 main HEAD 仍停在 V1-010，工作区包含大量未提交和未跟踪的 MVP-R-001/002 资产。禁止 reset、clean、checkout --、删除或覆盖用户现有更改。先记录 git status，修复当前 secret-scan 门禁并恢复可复现 baseline；不要继续 MVP-R-002 qualification，也不要开始 V1-011。

每个工作包先写测试，再做最小实现，运行文档列出的验证命令，并在 Evidence 中记录实际 Cursor 模型/版本、测试和未完成范围。没有用户盲评结果时，不得把 MVP-R-003 标为完成或解锁后续任务。
```

## 17. Grok Build 执行提示

### Goal

Implement the authorized `MVP-R-003` discovery vertical slice defined in `docs/MVP-R-003-VERTICAL-SLICE-PLAN.md`, one work package at a time.

### Context

`MVP-R-002` stopped because governance and receipt-lineage work displaced the primary product test. The repository still has a dirty post-`V1-010` workspace with many untracked MVP assets, so a new worktree from HEAD may omit required files.

### Constraints

Read `AGENTS.md`, `docs/HANDOFF.md`, `docs/ROADMAP.md`, and the plan first. Preserve all existing changes; do not reset, clean, delete, continue R-002 qualification, start V1-011, add trading effects, or perform drive-by refactors. Start with WP0, write tests before behavior, reuse V1-010 deterministic tools, and keep the implementation synchronous and non-trading.

### Done when

The current work package meets its documented Acceptance, relevant tests and `make check` pass, `git diff --check` is clean, and Evidence records exact changed files, commands/results, executor/model details, remaining work, and any blocker. Do not mark `MVP-R-003` complete before the user finishes the eight blinded evaluations.

