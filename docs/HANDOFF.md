# 跨对话交接

文档版本：`3.0-proposed`<br>
最后更新：2026-09-04
当前阶段：V1 自主研究与机会雷达
最近完成：`V1-010` 可重放研究工具、基础验证与 Catalog 1.5 Critic 垂直链
当前开发任务：`V1-013` 已完成独立验收。MVP 验证阶段已关闭，结论为 `MVP_ACCEPTED`；正式 MVP-R eval v1/v2 的失败结论保持原样，但不再阻塞 Roadmap。
建议下一步：完成 `V1-013` 独立验收后进入后续 Roadmap 规划；不要启动 formal eval v3、v2 holdout/shadow，也不要解锁任何交易能力。v1/v2 历史失败均不得修补、覆盖或重跑为成功。

开发模型路由（2026-09-05）：复杂任务由 GPT-6 Astra 统筹，明确的常规实现默认由 GPT-5.6 Sol 执行；机械任务可由 Luna 执行。GPT-6 仅在需求/Acceptance 歧义、跨模块冲突、一次返工仍未解决或关键验收反复失败时接管。产品运行时 ModelProfile 不因该开发路由自动改变。

## V1-012 当前进展（2026-09-04）

已完成最小评测闭环：`research_experiment.v1_012_evaluation` 提供不可变、内容寻址的评测集，冻结 dataset/rubric revision；逐例覆盖工具选择、引用正确性、数字 grounding、反证覆盖、`NO_TRADE/DEFER` 决策纪律与相同证据重放。`EvaluationRun` 固化 model/prompt/toolset revision，`EvaluationManager.report` 仅允许同一冻结 suite 生成确定性可比较差异报告。无交易、副作用、Formal Eval v3 或 UI。契约测试 4 项通过；Evidence 见 [`evidence/v1-012/implementation-2026-09-04.json`](../evidence/v1-012/implementation-2026-09-04.json)。

## V1-011 当前进展（2026-09-04）

已开始最小闭环实现：`research_experiment.experiment_manager` 提供不可变 `ExperimentPlan`、有限 `ResearchBudget`、`ResearchJob` 及确定性 `QUEUED → RUNNING → PARTIAL/SUCCEEDED/FAILED/CANCELLED/TIMED_OUT` 状态推进；结果按原始 `conversation` 回流查询，预算超限、截止时间、非法结果身份和终态重复推进均 fail closed。`0007_v1_011_experiment_manager` migration 为 research-only 注册/作业事实提供持久表；不含调度平台、UI、策略晋升或交易写入。契约测试 5 项通过，完整 `make check` 通过（466 contract tests）。实现与限流说明见 [`evidence/v1-011/implementation-2026-09-04.json`](../evidence/v1-011/implementation-2026-09-04.json)。

## MVP Closure：`MVP_ACCEPTED`

2026-09-04 按产品负责人指示执行最小 MVP Acceptance，复用既有 `MVP-R-005 correction-v5` 的 8 个代表性 Episode、R-003 vertical-slice 契约/回放测试、R-002 runtime/safety 反例和 v2 三条失败 artifact；未重新调用模型，未重跑 formal eval。8/8 代表性研究闭环均完成确定性实验、结果反馈和四块决策简报；future leak、无来源证据、非法 operator、交易请求、报告/lineage 篡改、runtime authority 越权等关键边界均 fail closed。`formal-diagnostic-013` 分类为 `NON_BLOCKING_PRODUCT_QUALITY`；`015`、`016` 分类为 `EVAL_OR_RUNTIME_FAILURE`；没有证据支持 `BLOCKING_PRODUCT_FAILURE`。

Acceptance 记录：`evidence/mvp-closure/acceptance-2026-09-04.json`。因此 MVP 验证阶段结束，Formal Eval v2 仍为 `FORMAL_DIAGNOSTIC_FAIL`，但不再作为产品 Roadmap 的必要结束条件。Formal evaluation reliability / quality improvement 转入后续 backlog。下一项 Roadmap 任务为 `V1-011`，等待用户确认后再开始开发。

开发模型路由：默认按 `docs/DEVELOPMENT-MODEL-POLICY.md` 自动选择。2026-09-01 用户允许 `MVP-R-003` 由 Cursor 或 Grok Build 优先执行的任务级例外只覆盖该任务；`MVP-R-004` 与 `MVP-R-005` 未另授例外。该政策不降低 Acceptance；每个工作包必须记录实际执行器、精确模型/版本和 reasoning effort（若宿主暴露）；最终验收仍由未主导实现的模型/执行器完成。

项目级安全范围：2026-09-02 用户明确将本系统定位为个人自用、单用户、本机受控、可信操作者环境。今后不要为本地对抗者、主动改写并重哈希 Evidence、多租户/RBAC、零信任或类似攻击面扩张 Roadmap/Acceptance；现有 V0 安全代码与历史 Evidence 保留，不要求回滚。研究/仿真边界、确定性交易正确性、风险/订单/成交/账本不变量、幂等/并发/恢复、实验可复现性和最小密钥卫生仍属硬要求。只有用户明确重新授权，或部署边界变为公网、多用户、非可信执行环境或真实资金时，才重开威胁模型。此次文档澄清由 Codex 执行，精确 model profile/reasoning effort 为 `NOT_EXPOSED`；无 Roadmap 任务状态变化。

## 最新结果：正式 MVP-R eval v1 `FORMAL_DIAGNOSTIC_FAIL`

2026-09-02 已按用户授权直接冻结并启动正式 eval，不创建 `MVP-R-006`。30 条 diagnostic roster SHA-256 `583625bde1a27587c9029283663cb6cb9acd20b29961267791b9a2d0cc9b35b6`、50 条 sealed holdout roster SHA-256 `f85914a590b647f8429283274730acd334cfba3734c9ea72dc3785372c040136` 均在模型调用前冻结；Critical 4/4 通过。前三条 diagnostic 均因 model workload observation contract fail closed，且冻结门槛只允许最多一条失败，因此停止剩余调用并记录 `FORMAL_DIAGNOSTIC_FAIL`；holdout/shadow 未启动，v1 不得 repair/iterate 或重跑。

2026-09-04 用户要求从该终点继续。Codex `gpt-5.6-sol` / `high` 增加结构化且不保留模型正文的 observation reason codes 与失败 Evidence。一次 roster 外最小 probe 证明官方 App Server 正常完成并返回唯一 Agent JSON、无工具/reroute/timeout，model 为 `gpt-5.6-terra`；但 SDK provider 标签为 `custom`、实际 effort 为 `high`，与 v1 冻结的 `openai` / `xhigh` 不一致，明确触发 `PROVIDER_MISMATCH` 与 `EFFORT_MISMATCH`。这证明 v1 严格拒绝正确，且失败属于冻结运行配置与宿主 observation contract 不匹配，不是产品 Brief 不合格。

后继正式评测必须使用全新预注册和全新 roster，并先以 roster 外 preflight 证明 provider/model/effort exact match。当前待产品负责人选择：改用能精确证明 `openai/xhigh` 的执行通道，或将官方 App Server 实际可观察的 `custom/high` 作为新冻结配置。结果与恢复边界见 `docs/MVP-R-FORMAL-EVAL-V1-RESULT.md`；Probe Evidence：`evidence/mvp-r-formal-eval/recovery/observation-probe-2026-09-04.json`。

## 最新结果：正式 MVP-R eval v2 `FORMAL_DIAGNOSTIC_FAIL`

2026-09-04 产品负责人明确选择产品模型 `gpt-5.6-sol/high`。新预注册 `docs/MVP-R-FORMAL-EVAL-V2-PREREGISTRATION.md`、diagnostic 30 条与 sealed holdout 50 条在模型调用前冻结；roster SHA-256 分别为 `d7d15cd81532687512be6d16075a96d886041f9488c9f700a97bad6b722fcb15` 与 `382f6a987fc2410ee3b60a4ede605c1c0c4d5d2727c1b8ecc60b08089aaad9ba`，并排除了既有 R-003/R-004/R-005 及 formal v1 样本。

roster 外 preflight 观察到 status=`completed`、model=`gpt-5.6-sol`、reasoning effort=`high`、宿主 provider 标签=`custom`、无 timeout/reroute/dynamic call/server request，记录于 `evidence/mvp-r-formal-eval-v2/preflight-2026-09-04.json`。该标签只是宿主观测字段，不是产品模型配置。

Diagnostic 实际完成 13/30。`formal-diagnostic-013` 因生成假设使用未注册 primary metric，过滤后不足两个 well-typed hypothesis；`formal-diagnostic-015` 与 `formal-diagnostic-016` 因 `STATUS_NOT_COMPLETED` fail closed。三条失败使冻结最低 29/30 不可达，已停止剩余调用并记录 `evidence/mvp-r-formal-eval-v2/diagnostic/termination-2026-09-04.json`、scorecard 与三个失败 artifact。v2 holdout/shadow 未启动，`V1-011` 仍锁定。实现/运行执行器 Codex，model=`gpt-5.6-sol`，reasoning effort=`high`。

## 最近完成：`MVP-R-005` correction-v5（独立复核 `PASS`；任务已完成，但不是 `GO`）

2026-09-02 未主导 correction-v5 实现的 Codex 完成最终独立功能复核。8 例两条臂共 16 个实际产物的 visible/view、Markdown/DecisionBrief/FinalVerdict、packet/view、predicate/verdict 均精确一致；额外 exact hydrate 核对也确认 16/16 FinalVerdict 的 hypothesis ref、falsification condition 和 result ref 与各自 selected hypothesis/result packet 一致。未发现实际功能或现存产物缺陷。

复核曾发现一个只影响“有人主动改写本地 JSON 并合法重哈希”的 Evidence Gate 加固点：Gate 比较 FinalVerdict enum 时没有 hydrate 全部 lineage。用户/产品负责人明确要求个人自用、无对抗者系统忽略安全/对抗性 Evidence 防篡改；该项因此记录为非阻断 hardening note，不再扩张 Acceptance 或要求 correction-v6。定向 v3/v4/v5 契约测试 29 passed，`uv run pytest` 为 `465 passed, 42 skipped`，`make check` 全绿（contract 450），`git diff --check` 通过。reviewer model/reasoning effort 宿主未暴露，记录为 `NOT_EXPOSED`。独立复核 Evidence：`evidence/mvp-r-005/correction-v5/independent-review-2026-09-02.json`。

2026-09-02 未主导 correction-v4 实现的 Codex 拒绝 `R005_CORRECTION_V4_PASS`，记录于 `evidence/mvp-r-005/correction-v5/reviewer-rejection-correction-v4.json`。v4 的 `_agent_model_input` 会在 `agent_visible_experiment` 缺失、null 或空容器时 truthy-fallback 到 treatment view；四块报告 Gate 也只搜索标题，额外 H2 或与结构化 verdict 矛盾的 Markdown 仍会通过。复核同时确认 correction-v3 的 16 条实际臂 visible/Markdown/brief verdict 全部一致，无需重新调用产品模型。

用户授权继续直接修复。correction-v5 要求两条臂的 `agent_visible_experiment` 字段显式存在、类型为非空 exact mapping，完全移除 treatment-view fallback。新增 closed `DecisionBrief.hydrate`，要求结构化 brief verdict 等于 `ResearchFinalVerdict`，并要求 Agent 与 Single-prompt 两份 Markdown 都逐字等于确定性 renderer 输出；missing、null、空对象、空列表、空元组、额外 H2、矛盾 Markdown、brief/final verdict 冲突全部 fail closed。

v5 不调用产品模型，继续复用 correction-v3 运行产物。Gate 计算得出 `R005_CORRECTION_V5_PASS`（`hardcoded=false`）：complete/experiments/Single-prompt 8/8、双臂 exact visible/view binding 8/8、四块 Markdown/brief/final verdict exact binding 8/8、packet→view lineage 8/8、predicate binding/congruence 8/8、Critic gate 0/8、blocked 0、overlap 0/8。v1–v4 共 143 个受保护文件 baseline/final 完全一致。`uv run pytest` 为 `465 passed, 42 skipped`；`make check` 通过（mypy 102 source files、schema 2、unit 1、property 9、contract 450、secret scan、health）；`git diff --check` 通过。实现执行器 Codex，精确 model profile/reasoning effort 为 `NOT_EXPOSED`。后续独立功能复核 `PASS`，任务已勾选；仍不是 `GO`。

Correction-v5 Evidence：`evidence/mvp-r-005/correction-v5/scorecard.json`、`wp-discovery.json`、`reviewer-rejection-correction-v4.json`、`predecessor-hash-baseline.json`、`predecessor-hash-final.json`。

## 历史进展：`MVP-R-005` correction-v4（机器 Gate 已被独立复核拒绝；不是 `GO`）

2026-09-02 未主导 correction-v4 实现的 Codex 完成最终独立复核并拒绝 `R005_CORRECTION_V4_PASS`。第一项阻断是 `_agent_model_input` 对 `agent_visible_experiment` 使用 truthy fallback：字段被删除、设为 `null`、空对象或其他空容器时，Gate 会退回 `treatment_metric_view`，错误返回 `treatment_view_bound=true`。最小复现把 Single-prompt visible payload 设为空对象后仍得到 `complete=true`、`lineage=true`、`invisible=true`、`view bound=true`。第二项阻断是 `_four_blocks` 只搜索四个 heading 子串；添加第五个 H2 或让四块 Markdown 与结构化 brief/final verdict 矛盾，仍错误返回 `four_block_report=true`。因此 v4 没有证明宣称的 exact visible binding 与四块报告完整性/fail-closed。

复核也独立核对了现存 correction-v3 的 16 条臂：16/16 visible payload 实际存在且非空、16/16 Markdown 与结构化四块简报精确一致、16/16 brief verdict 与 final verdict 一致，所以无需重跑产品模型或改写研究结果。定向 v3/v4 契约测试 20 passed，`uv run pytest` 为 `456 passed, 42 skipped`，`make check` 全绿（contract 441），`git diff --check` 通过。reviewer model/reasoning effort 宿主均未暴露，记录为 `NOT_EXPOSED`。拒绝 Evidence：`evidence/mvp-r-005/correction-v5/reviewer-rejection-correction-v4.json`。

2026-09-02 Codex 独立复核拒绝 correction-v3 的机器 Gate，但重新计算确认 correction-v3 的 8 例、两条臂共 16 个实际 treatment view 均与各自 packet/hypothesis/plan/config 精确一致，因此无需重跑模型或改写研究结论。v3 Gate 的阻断是 Evidence 检查不对称：只重建 Agent view，只对 Agent 检查 mirror/fold manifest/walk-forward，未把两条臂的 `agent_visible_experiment` 精确绑定 view，且 INVERT lineage 未核对映射后的值。`raw_tool_result_lineage` 名称也超出实际证明范围。拒绝记录：`evidence/mvp-r-005/correction-v4/reviewer-rejection-correction-v3.json`。

用户随后授权 Codex 直接修复。correction-v4 仅修改 Evidence Gate，产品模型调用为 0，继续引用 `datasets/mvp-r-001/runs/mvp-r-005-correction-v3/`。两条臂现在都 hydrate plan/packet/hypothesis/view，重建 treatment view，并检查 direction、mirror、真实 fold manifest、walk-forward 与 Agent-visible exact binding；lineage 必须 exact coverage、值与 mapped raw metric 一致，stop 后派生的 positive-fold ratio 从可见 folds 重算。Gate 将诚实范围命名为 `raw_packet_to_view_lineage`，不宣称 `research-tool-result://` source-ref authenticity，也未增加签名、registry 或 qualification 系统。

correction-v4 Gate 计算得出 `R005_CORRECTION_V4_PASS`（`hardcoded=false`）：8/8 完成、8/8 双臂 treatment view exact binding、8/8 packet→view lineage、8/8 predicate binding/congruence、8/8 四块简报、pre-experiment Critic gate 0/8、Critic blocked 0、predecessor overlap 0/8。v1–v3 共 138 个受保护文件的 baseline/final manifest 完全一致。新增合法重算 content hash 后的 Single-prompt INVERT metric 篡改、visible payload 篡改和 lineage value 篡改测试，均 fail closed。`uv run pytest` 为 `456 passed, 42 skipped`；`make check` 通过（mypy 102 source files、schema 2、unit 1、property 9、contract 441、secret scan、health）；`git diff --check` 通过。实现执行器为 Codex；宿主未暴露精确 model profile 与 reasoning effort，均记录 `NOT_EXPOSED`。该机器 PASS 后续已被上文独立复核拒绝；scorecard 原样保留。

Correction-v4 Evidence：`evidence/mvp-r-005/correction-v4/scorecard.json`、`wp-discovery.json`、`reviewer-rejection-correction-v3.json`、`predecessor-hash-baseline.json`、`predecessor-hash-final.json`。

## 历史进展：`MVP-R-005` correction-v3（机器 PASS 已被复核拒绝，不是 `GO`）

2026-09-02 独立复核拒绝 correction-v2 `R005_CORRECTION_V2_PASS`。v2 的 FOLLOW/INVERT 镜像、真实 5-bar walk-forward、typed predicate、四块中文简报和 Critic 非阻断 shadow 有效，但仍有五组阻断：FAIL 被 INSUFFICIENT 覆盖、fold predicate 忽略注册 metric、stop 后第三折 raw 字段泄露给 Agent、方向转换后 source_refs 与值错位、以及无条件写死 predecessor untouched。拒绝记录：`evidence/mvp-r-005/correction-v3/reviewer-rejection-correction-v2.json`。v1 与 correction-v2 scorecard/WP/failure Evidence 均未改写、未删除。

同日用户授权 Grok Build 执行 correction-v3（reasoning effort=`NOT_EXPOSED`）。产品模型不变：research/feedback=`gpt-5.6-terra`/`xhigh`，shadow critic=`gpt-5.6-sol`/`xhigh`。复用 v1 roster SHA-256 `a1900210000aebffc792a94518dce7402ea250ed615f2cd143c973c3aebb7ed2`。raw `ToolRunResult` 保持 FOLLOW 原值与原 source_refs；treatment-relative 指标进入独立 `mvp-r-005.treatment-metric-view.v1`。谓词组合改为任一 FAIL→REJECT，无 FAIL 且有 INSUFFICIENT→NEED_MORE_DATA，全部 PASS→ACCEPT；`AT_LEAST_N` 做可达性判断；stop 后 `REQUIRED_OOS_FOLD_COUNT` 为 FAIL。fold clause 只允许 `signal_accuracy`/`proxy_net_return`，renderer 输出实际字段名。Agent prompt 只看到 treatment view；被 stop 的折的标准字段、raw 字段和 manifest 均不可见，完整 raw 只留 evaluator-only packet。predecessor 用 SHA-256 baseline/final manifest；`pre_v2_byte_stability=NOT_PROVEN`，`v3_predecessor_hashes_match` 由文件哈希比较得出。

新 8 例写入 `evidence/mvp-r-005/correction-v3/` 与 `datasets/mvp-r-001/runs/mvp-r-005-correction-v3/`。`r005-cu-extreme` attempt-1 因 fold clause 使用 `stressed_net_return` fail closed，失败 JSON 保留且不计入完成。v2 的三个 `NEED_MORE_DATA`（`r005-ag-uptrend`、`r005-sr-false-breakout`、`r005-sr-extreme`）按规则重算为 `REJECT`，未硬编码。Agent 与 Single-prompt 仅在 `r005-ma-downtrend` 不同判（REJECT vs ACCEPT），其余 7/8 同判。v3 Gate 计算 `R005_CORRECTION_V3_PASS`（`hardcoded=false`）：complete 8/8、agent loop 8/8、experiments 8/8、Single-prompt 8/8、raw tool result lineage 8/8、predicate metric binding 8/8、verdict/predicate congruence 8/8、four-block reports 8/8、pre-experiment Critic gate 0/8、Critic blocked 0、predecessor window overlap 0/8、stopped folds invisible 8/8、treatment view bound 8/8、`v3_predecessor_hashes_match=true`、`pre_v2_byte_stability=NOT_PROVEN`、`not_go=true`、`independent_real_user_validation=false`。任务仍 `[ ]` / `IN_PROGRESS`，等待独立复核。完整 `uv run pytest` 为 `452 passed, 42 skipped`；`make check` 通过（mypy 102 source files、schema 2、unit 1、property 9、contract 437、secret scan、health）；`git diff --check` 通过。未提交、未推送、未开 PR。

Correction-v3 Evidence：`evidence/mvp-r-005/correction-v3/scorecard.json`、`evidence/mvp-r-005/correction-v3/wp-discovery.json`、`evidence/mvp-r-005/correction-v3/predecessor-hash-baseline.json`、`evidence/mvp-r-005/correction-v3/predecessor-hash-final.json`。运行产物：`datasets/mvp-r-001/runs/mvp-r-005-correction-v3/`。

## 历史进展：`MVP-R-005` correction-v2（已被复核拒绝，不是 `GO`）

2026-09-02 独立复核拒绝 v1 `R005_PASS`：机器 Gate 只验证完成和字段存在，没有验证指标语义。三个阻断问题是假设方向未绑定实验结果、`fold_N_signal_accuracy` 不是真实 walk-forward OOS、以及 Agent 可用自然语言证伪条件改写预注册规则。拒绝记录：`evidence/mvp-r-005/reviewer-rejection-2026-09-02.json`。v1 `evidence/mvp-r-005/scorecard.json` 仍为 `mvp-r-005.discovery-gate.v1` / `R005_PASS`，未改写、未删除。v1 运行目录 `datasets/mvp-r-001/runs/mvp-r-005-discovery/` 未覆盖。

同日 Cursor Grok 4.6（reasoning effort=`NOT_EXPOSED`）在当前 dirty checkout 实现 correction-v2，产品模型不变：research/feedback=`gpt-5.6-terra`/`xhigh`，shadow critic=`gpt-5.6-sol`/`xhigh`。复用 v1 roster SHA-256 `a1900210000aebffc792a94518dce7402ea250ed615f2cd143c973c3aebb7ed2`。`execute_replay` 显式传入并校验 `HypothesisSpec`；raw tool 仍计算 FOLLOW，adapter 输出 treatment-relative 指标。OOS fold 来自唯一 planner（`train_bars=20`、`test_bars=5`、`step_bars=5`、`embargo_bars=1`）；缺折不合成；`minimum_samples=20` 约束全窗资格。证伪为 `mvp-r-005.falsification-predicate.v1`，确定性 evaluator 与 Agent verdict 必须一致。

新 8 例一次跑完（`r005-ag-uptrend` 前 3 次 generate/binding fail closed，attempt-1/2/3 失败 JSON 保留，不计入完成）。v2 Gate 计算 `R005_CORRECTION_V2_PASS`（`hardcoded=false`）：direction binding 8/8、treatment/control semantic mirror 8/8、authentic walk-forward fold manifest 8/8、fold metrics 与 manifest exact binding 8/8、verdict/predicate congruence 8/8、four-block report 8/8、pre-experiment Critic gate 0/8、Critic blocked 0、predecessor overlap 0/8。因方向镜像和真实 OOS 折，`r005-ag-uptrend`、`r005-sr-false-breakout`、`r005-sr-extreme` 相对 v1 改判。任务未勾选。不是独立真实用户验证，不批准 30/50/shadow，不解锁 `V1-011`。未提交、未推送、未开 PR。

Correction-v2 Evidence：`evidence/mvp-r-005/correction-v2/scorecard.json`、`evidence/mvp-r-005/correction-v2/wp-discovery.json`。运行产物：`datasets/mvp-r-001/runs/mvp-r-005-correction-v2/`。

## 历史进展：`MVP-R-005` v1 机器门槛 `R005_PASS`（已被复核拒绝，不是 `GO`）

2026-09-02 已跑完新 8 例单 Agent 闭环 vs Single-prompt。主路径没有实验前 Critic 门卫；确定性 validator 与五项工具先跑实验；用户报告只有四块中文：测了什么、结果怎样、当前判断、下一步动作。Shadow Critic 在实验后记录风险，2 例声称“若在事前会阻断”但都没有挡住实验。v1 walk-forward 字段存在，但把全窗约 38 个信号平均切成 12/13/13，且 INVERT 未交换 treatment/control。

Roster SHA-256 `a1900210000aebffc792a94518dce7402ea250ed615f2cd143c973c3aebb7ed2`，与 R-003 v1 / R-004 cutoff 无重叠。Gate 计算 `R005_PASS`（`hardcoded=false`），后被独立复核拒绝。Agent 与 Single-prompt 仅在 `r005-sr-extreme` 不同判。R-003/R-004 Evidence 未改写。不是独立真实用户验证，不批准 30/50/shadow，不解锁 `V1-011`。

授权：`evidence/mvp-r-005/authorization-2026-09-02.json`。v1 Discovery Evidence：`evidence/mvp-r-005/scorecard.json`、`evidence/mvp-r-005/wp-discovery.json`。

## 历史进展：MVP-R-004 用户盲评 `USER_VALUE_FAIL`，产品 `STOP/PIVOT`

2026-09-02 产品负责人在 Codex 生成的中文对照上逐例确认 8 例盲评。打分前未打开 `blind-mapping.json`。门槛按 `docs/MVP-R-003-VERTICAL-SLICE-PLAN.md` §10.4。评估人是 `product_owner_assisted_by_codex`，不是独立真实用户验证。

揭盲后完整流程（Research + Critic + 实验 + Result Feedback）只在 `r004-ma-downtrend` 被偏好，合计 **1/8**，低于 6/8。无 Critic 臂 5/8，Single-prompt 2/8，Template 0/8。无需额外解释可理解 7/8，明显省时 8/8，促成明确动作 8/8。用户价值门槛计算为 `USER_VALUE_FAIL`（`hardcoded=false`）。机器 Discovery Gate 仍为 `DISCOVERY_PASS`，没有用盲评去改写。

第 4 例映射复核：用户偏好的 B 是无 Critic 臂，假设写的是同向延续；A 是 Single-prompt，实验后理由写成 INVERT。此前主持人摘要把整例说成“测反向”是错的。第 8 例用户偏好无 Critic 臂的 `NEED_MORE_DATA`：合计命中率过关，但结果包没有分段 `signal_accuracy`，不能用 `positive_fold_ratio` 代替“各段命中率是否超过 0.50”。完整臂对此给出 `ACCEPT`。

预注册停止规则已触发：完整流程偏好低于 6/8，且完整流程盲评不优于 Single-prompt。金标路径 Critic 仍 8/8 留 clean、8/8 拒 bad、坏假设进入实验 0，该条 Pivot 触发器未点燃。产品随后确认 Pivot 方向见上文。Evidence：`evidence/mvp-r-004/discovery/user-blind-eval.json`。

## 历史进展：MVP-R-004 Discovery 已 `DISCOVERY_PASS`

2026-09-01 用户复核 R-003 v1 后明确产品决策：本轮记为 **R-003 v1 测量方案失败**，还不能判定多 Agent 产品失败。批准一个小型 `MVP-R-004` Discovery Measurement Repair；不批准正式 30/50/shadow eval，不批准 `V1-011`。

已核对四类测量缺陷属实：

1. `ResearchEpisodeInput` 只向模型提供 `market_state` 和哈希引用；Discovery 候选空间为单个 `PRIOR_CLOSE_RETURN_THRESHOLD`、单个冻结阈值、`FOLLOW/INVERT` 两个方向。
2. `MvpR003ModelWorkloads.critique` 只发送 `episode.to_dict()` 与 `hypothesis.to_dict()`，Critic 拿不到 validator 已确认的窗口、成本、样本、fold、embargo、PIT 协议和 multiple-testing budget，于是把“看不到内容”写成阻断。
3. `write_discovery_summaries` 把 Gate `decision` 写死为 `STOP/PIVOT`；`clean_hypothesis_retention` 用 `SELECT / 全部 executable` 代替金标。
4. Hypothesis schema 允许 `net_directional_mean`，但 replay ResultPacket 实际字段是 `signal_accuracy`、`proxy_net_return`、`stressed_net_return` 等；模板 Verdict 也按这些 proxy 字段判断。Template 与 Single-prompt 共用同一模板 Hypothesis 和 ResultPacket，8/8 结论一致不能证明多 Agent 没价值。

R-003 v1 Evidence 全部保留：`evidence/mvp-r-003/discovery/scorecard.json` 仍为 `STOP/PIVOT`。**禁止做 v1 盲评**。

Canary 已 `CANARY_PASS`。随后冻结与 v1 不同 cutoff 的 8 例 roster SHA-256 `afdd4b24b7e78af33e5913f5aafbb213567e86872a84955fcb199797ae674567`（AG/CU/MA/SR 同 8 格，取 `candidates_per_cell=2` 的另一窗口）。产品模型不变。8/8 无人工修复完成；金标 clean 8/8 SELECT、bad 8/8 REJECT、坏假设进入实验 0；完整臂 8/8 跑通每例第一个 Critic SELECT 的五项实验与 Result Feedback。Gate 计算得出 `DISCOVERY_PASS`（`hardcoded=false`）。Template 与 Single-prompt 仍 8/8 同判；`r004-sr-extreme` 无 Critic 臂为 `NEED_MORE_DATA`，其余三臂 `ACCEPT`。完整 `uv run pytest` 为 `417 passed, 42 skipped`；`make check` 通过（mypy 89、contract 402）。未提交。

Discovery 机器门槛通过不等于 `GO`。用户盲评已完成且为 `USER_VALUE_FAIL`；产品记录 `STOP/PIVOT`。授权记录：`evidence/mvp-r-004/authorization-2026-09-01.json`。Discovery Evidence：`evidence/mvp-r-004/discovery/scorecard.json`、`evidence/mvp-r-004/wp-discovery.json`、`evidence/mvp-r-004/discovery/user-blind-eval.json`。

## 历史进展：MVP-R-003 WP0–WP5（v1 测量方案失败）

2026-09-01 Cursor 使用 GPT-5.6 Sol（reasoning effort 宿主未暴露，记录为 `NOT_EXPOSED`）在当前 checkout 完成 WP0。开始基线为 main HEAD `d72afbeed54e83bb9bec4afdff9884a423cce0ac`，全部既有 R-001/R-002 tracked/untracked 资产保留；未运行 reset、clean、checkout 覆盖、批量删除、worktree、commit、push、PR 或 capability probe。

现有 capability-probe JSON 的两个 SHA-256 被 detect-secrets 高熵插件误报。修复采用 `.secrets.baseline` 对精确 hashed value 标记人工复核 false positive，`verify_secret_scan.py` 每次复制 baseline 到临时目录、强制最新全部插件扫描并只忽略已审计精确值；没有关闭插件、降低 entropy 阈值或排除 Evidence 目录。对应契约测试 4 项通过。

WP0 验证：`uv run pytest` 为 `402 passed, 42 skipped`；`make check` 全绿（mypy 74 source files、schema 2、unit 1、property 9、contract 392、secret scan、health）；`git diff --check` 通过。完整机器可读记录位于 `evidence/mvp-r-003/wp0-baseline.json`。由于用户明确禁止未经要求提交，方案中“baseline commit”没有执行；当前 checkout 本身是唯一受保护工作面。

WP1 使用同一 Cursor / GPT-5.6 Sol 实现 `ResearchEpisodeInput`、`HypothesisSpec`、`HypothesisValidation`、`CriticReview`、`ExecutableExperimentPlan`、`ExperimentResultPacket`、`ResearchFinalVerdict` 及 deterministic executability validator。所有对象带版本化 schema、规范内容哈希和严格 hydrate；Agent 批次固定 2–3 个语义不同 Hypothesis。future result、无来源引用、不可执行 operator、交易请求四个反例 fail closed；`MODIFY` 只能产生绑定原版本的新版本且同 Episode 不自动递归执行。定向测试 4 项、Ruff、mypy 通过；完整 `make check` 全绿（mypy 77、contract 396）。Evidence 位于 `evidence/mvp-r-003/wp1-contracts.json`；尚未连接模型或运行实验。

WP2 使用同一 Cursor / GPT-5.6 Sol 实现同步 experiment adapter，没有创建第二套计算框架。Adapter 把通过 deterministic validator 的 Hypothesis 精确绑定到已有 V1-010 `ValidationConfig`，并调用 `issue_replay_tool_results` 实际运行 L0 signal test、L1 daily-bar backtest、chronological walk-forward、cost/slippage stress 和 inverted-direction counterfactual，随后生成 content-addressed `ExperimentResultPacket`。测试使用受治理 PIT artifact/window 实际执行两次并证明 packet byte-identical；新旧 replay 与全部 contract 联合 `397 passed`，完整 `make check` 全绿（mypy 78、contract 396、secret scan、health）。Evidence 位于 `evidence/mvp-r-003/wp2-experiment-adapter.json`；尚未连接模型、生成 CLI 报告或运行 Discovery Episode。

WP3 使用同一 Cursor / GPT-5.6 Sol 实现三个独立 structured workload：Hypothesis generation、independent Critic、result feedback/final verdict。模型工具面为空，schema、timeout/output 预算固定；runtime 检查 exact model、provider 报告的实际 effort、usage、reroute/tool activity，并强制 Critic source ref 来自冻结 Episode。测试证明结果包确实进入 final workload，支持与反证指标会使同一 Hypothesis 分别得到 `ACCEPT`/`REJECT`。最小真实 generation smoke 请求 `medium` 时 provider 实际报告 `xhigh`，两次均 fail closed（第二次仅采集非内容元数据）；改用 exact `gpt-5.6-terra` / `xhigh` 后生成 2 个不同 Hypothesis，无工具活动，receipt 为 `f1644fb6bb8e42239098932cc8751926fddc83c3ec94895055963d51ced1eb7c`。定向测试 8 项和完整 `make check` 通过（mypy 79、contract 396）。Evidence 位于 `evidence/mvp-r-003/wp3-model-workloads.json`；真实 Critic/final workload 尚未在 Discovery Episode 执行。

WP4 使用同一 Cursor / GPT-5.6 Sol 新增 demo CLI 和 episode reporter。默认 fixture 命令不联网、不调用模型，输出显式 `FIXTURE_RENDER_ONLY` 且 model receipts 为空；`--execute-model` 是唯一模型开关。Reporter 强制 selected Hypothesis、experiment plan、complete result packet 与 FinalVerdict 的 exact lineage，并生成并列“实验前判断、独立 Critic、确定性实验结果、实验后判断”的 JSON 与 Markdown。方案命令成功生成 `evidence/mvp-r-003/demo/fixture-episode-001.json` 和 `.md`；CLI/report/replay 测试 5 项及完整 `make check` 通过（mypy 80、contract 396）。生成 Evidence 暴露的 12 个 content/request/response digest 均通过与 WP0 相同的精确值 baseline 人工审计，Evidence 目录未排除且插件未关闭。WP4 Evidence 位于 `evidence/mvp-r-003/wp4-cli-reporting.json`；fixture 明确不算 Discovery 实验。

WP5 由 Cursor / Grok 4.6 接续完成剩余 Discovery Episode 与离线 scorecard。冻结 roster 覆盖 AG/CU/MA/SR 各两例不同状态，使用官方 SHFE/CZCE 日线 PIT。8/8 Episode 均由 Research Agent 提出 2 个 validator 判定为 `EXECUTABLE` 的 Hypothesis；无 Critic 臂 8/8 真实跑完五项 V1-010 实验。independent Critic（`gpt-5.6-sol` / `xhigh`）对 16 个候选全部 `DEFER` 或 `REJECT`，完整臂因此 0/8 实验，报告为 `NO_EXPERIMENT_CRITIC_SELECTED_NONE`，没有伪造 ResultPacket。3 个 Episode 曾 fail-closed 修复后重跑，无人工修复完成 5/8，低于 7/8。Single-prompt 与 Template 在 8/8 上给出相同 ACCEPT/REJECT。用户盲评未做。v1 runner 将 Gate 写死为 `STOP/PIVOT`。该 scorecard 作为测量方案失败的历史输出保留，2026-09-01 产品解释不再把它读成多 Agent 产品失败。Scorecard 位于 `evidence/mvp-r-003/discovery/scorecard.json`，逐例产物在本地 `datasets/mvp-r-001/runs/mvp-r-003-discovery/`。

WP5 方案 §13 复验由同一 Cursor / Grok 4.6 完成（reasoning effort=`NOT_EXPOSED`）：`tests/contract/test_mvp_r_003_contracts.py`、`tests/replay/test_mvp_r_003_vertical_slice.py`、`tests/agent_eval/test_mvp_r_003_eval_fixtures.py` 合计 9 passed；`scripts/run_mvp_r_003_demo.py --fixture tests/fixtures/mvp_r_003/episode-001.json` 输出 `FIXTURE_RENDER_ONLY`；`scripts/run_mvp_r_003_discovery.py --summarize-only` 复写 `evidence/mvp-r-003/discovery/scorecard.json`；`scripts/verify_secret_scan.py` 通过；完整 `uv run pytest` 为 `411 passed, 42 skipped`；`make check` 通过（mypy 80 source files、schema 2、unit 1、property 9、contract 396、secret scan、health）；`git diff --check` 通过；`uv run futures-agent-os health` 为 `ok`。未提交、未推送、未开 PR。

2026-09-01 产品复核确认：系统研究与模拟边界没有偏离，但当前工程重心和 Gate 已偏离一级产品假设。`MVP-R-002` 主要验证受治理的封闭研究简报，不能证明 Agent 提出新 Hypothesis、实际执行实验并根据结果改判，也不能回答完整系统是否优于“单次通用模型 Prompt + 同样工具”。

用户已明确确认停止并重定向 `MVP-R-002`。其代码、测试、runtime slice、预注册和失败 Evidence 全部保留，不删除、不重跑为通过，也不解锁 `V1-011`。最新最小 capability probe 只尝试首个 workload，provider turn 与 provider response 均为 0，状态为 `NOT_QUALIFIED_MINIMAL_CAPABILITY_PROBE_ONLY`；该事实作为停止前最后一项运行 Evidence 保留。

后继任务 `MVP-R-003` 的方案已执行完毕，执行文档为 [`MVP-R-003-VERTICAL-SLICE-PLAN.md`](./MVP-R-003-VERTICAL-SLICE-PLAN.md)。v1 目标链路仍然有效，但测量方案未能公平检验该链路。当前授权任务改为 [`ROADMAP.md`](./ROADMAP.md) 中的 `MVP-R-004`。

Discovery 只使用 8 个 AG/CU/MA/SR Episode，并同时比较 Deterministic Template、Single-prompt Analyst、Research without Critic、Research + Critic + Result Feedback。v1 未满足这些门槛，且测量本身有缺陷；不得把 v1 scorecard 单独当作产品 Pivot 证据。正式 30/50/shadow eval 仍须在修复后的 Discovery 通过后再另行预注册。Discovery Gate 本身不是 `GO`。

当前工作区仍基于 `V1-010` HEAD，包含大量未提交和未跟踪的 MVP-R 资产，包括完整的 R-003 v1 Evidence。任何执行器都禁止 reset、clean、删除、覆盖现有更改，也禁止把 R-003 v1 产物改写成通过。

方案编写阶段使用 GPT-5 Codex 会话，当时尚未开始实现。实现已在当前 dirty checkout 完成 WP0–WP5；未创建 baseline commit，因为用户明确禁止未经要求提交。

## 历史进展：MVP-R-002 Phase 0

2026-08-31 用户连续两次明确“批准”，正式授权 `MVP-R-002` 新能力 Pivot。`MVP-R-001` 已以 `STOP_CURRENT_CAPABILITY` 永久封存，不再 repair/replay；原工作日 forward heartbeat 保持 `PAUSED`。

新产品任务不再要求 LLM 预测五日方向或击败确定性方向基线。确定性代码独占候选产生、family、方向、数值、成本和 eligibility；Research Agent 只组织支持证据、最强反证、未知、可证伪命题和下一项最小研究实验，独立 Critic 不能扩大候选或改写数值。输出只允许 `TEST_NEXT`、`WATCH_FOR_DATA`、`REJECT_AS_UNSUPPORTED`、`DEFER`，全部为研究动作而非交易、策略晋升或治理 Activation。

预注册已写入 [`MVP-R-002-PREREGISTRATION.md`](./MVP-R-002-PREREGISTRATION.md)，SHA-256 `c0e8c257f0d3b1386804f5cdc96d045da23f0b06f3896fe709c563e236033d48`。正式 Gate 为：30 条 diagnostic 后冻结 exact suite；一次性运行 50 条新 sealed holdout，至少 49 条无人工修复完成，Critical/grounding/权限/交易副作用、artifact hydrate、deterministic-action congruence、experiment instantiation、Critic recall、token 与时延满足冻结门槛；之后才向用户做 10 次 Deterministic Template 对 Agent + Critic 的盲测，至少达到偏好 7/10、价值 7/10、省时 5/10、明确行动 3/10。方向收益、五日涨跌、PnL、Sharpe 和胜率不再是门槛。

当前仅授权 Phase 0，状态为 `AUTHORIZED_NOT_FROZEN`：没有 suite、Prompt、roster 或数据 freeze，不能运行 diagnostic/holdout/shadow。下一步只实现 typed artifacts、authorities、最强确定性模板、Critic、runner/evaluator、非技术 renderer 和反例测试。预注册与治理记录使用 `gpt-5.6-sol` / `high`，未委托独立 reviewer；最终 `GO` 前仍必须取得未主导实现的独立 Sol/high 或更高验收 Evidence。

预注册更新后 `make check` 全绿：mypy 71 source files、schema compatibility 2、unit 1、property 9、contract 302，Ruff、secret scan、health、`git diff --check` 和预注册 digest 复验通过。

Phase 0 foundation/runtime 首轮由 `gpt-5.6-terra` / `high` 实现；exact receipt lineage、首轮修复及当前第二轮修复由 `gpt-5.6-sol` / `high` 实现。最初从 Terra 升级到 Sol 的原因是当时环境 Terra 使用额度不可用，按模型策略升级；额度恢复后仍由同一 Sol/high 实现者连续完成已开始的安全关键修复，避免中途更换 owner。首轮独立 `gpt-5.6-sol` / `xhigh` 验收明确给出 `REJECT_RUNTIME_SLICE`：activation 可被非空 toolset/self authority/字符串 `FROZEN` 绕过，experiment public call 可触达 port，runtime 与 domain 的五项资产摘要不一致，critic verdict 可脱离 receipt output，异常观察字段丢失，bad object 未签 failure receipt，repo root 可替换，usage 内部关系与 evaluator 官方聚合未封闭。

第一次修复后，同一独立 `gpt-5.6-sol` / `xhigh` reviewer 第二次仍给出 `REJECT_RUNTIME_SLICE`：R-002 family 仍依赖 prompt/schema namespace 判族；qualification 没有完整的 append-only typed receipt trust root 与 frozen case roster 重派生；五项资产只证明 outer owner evidence，未逐 workload 精确映射 inner bytes；runner factory/下划线执行能力及 completed receipt 原子语义仍可绕开 sole orchestrator；critic request/run-id 未统一，缺少生产形态 synthetic 三 workload E2E；official App Server 不能证明 actual effort 时的完成路径不充分；bad-object 异常未先保留安全可观察字段。两次 REJECT 都是历史事实，当前仍没有被独立接受的 runtime 主链。

第二轮修复后，第三次独立 `gpt-5.6-sol` / `xhigh` 验收为 `REJECT_RUNTIME_SLICE`（0 P0 / 4 P1）：公开 `_factory_create` 仍允许任意 authority/key 自铸 qualification trust root；`ResolvedQualificationRunConfig` 丢失签名 `protocol_family`，使 R-001 profile 可进入 R-002 bundle；导出的 runner/port 与低层执行入口仍能绕开 sole orchestrator；`RuntimeOwnerBinding` 可直接构造伪 inner digest，orchestrator/_rebind 没有每次回到 FrozenRuntimeAssets 对 inner bytes 和 outer payload 做完整 cross-proof。三次 REJECT 都是历史事实，当前仍没有被独立接受的 runtime 主链。

第三轮修复后，第四次独立 `gpt-5.6-sol` / `xhigh` review 仍为 `REJECT_RUNTIME_SLICE`，仅剩 1 P1、表现为两个入口：低层 executor/registry `_issue` 或单项 `OwnerEvidenceRegistry.add` 仍可能写入没有 MODEL_OUTPUT/RUN 的 completed receipt orphan；`CodexAppServerProvider.run_frozen_structured` 仍可被普通调用方直接触发 R-002 transport，没有 per-invocation、单次使用、绑定 exact owner/workload/config/request 的 execution lease。四次 REJECT 都是历史事实，当前仍没有被独立接受的 runtime 主链。

第四轮修复后，第五次独立 `gpt-5.6-sol` / `xhigh` review 的最终消息被平台拦截，但 reviewer 已确认同一 sole/atomic P1 的三条 reflection-level 复现：可写 completed pending flag 仍能改变 registry 单项规则；name-mangled executor/lease issuer/port/assets 仍可从 orchestrator 对象图取回；从 adapters 直接构造的 Codex provider 仍保留 R-002 frozen execution 能力。第五次 REJECT 是历史事实，当前仍没有被独立接受的 runtime 主链。

第五轮修复实现保持 `AUTHORIZED_NOT_FROZEN`。`OwnerEvidenceRegistry` 已删除所有 pending/completed flag，并使用固定 slots 拒绝调用方注入此类属性；public add/constructor 对 `COMPLETED RUNTIME_RECEIPT` 无条件永久拒绝，唯一 atomic API 先严格验证 exact receipt + MODEL_OUTPUT + 唯一对应 RESEARCH_RUN/CRITIC_RUN，再把 completed receipt 直接插入隔离 clone，随后执行完整既有语义验证并一次提交。orchestrator 实例只持不可变 opaque id 和公开业务方法；executor、单次 lease、transport、assets、issuer 与 runtime state 全部位于 factory 闭包映射，模块没有可构造 executor symbol，对象属性遍历也不能取回执行能力。adapters package 不再导出 `CodexAppServerProvider`，仅保留重命名的通用 `CodexGenericModelProvider`；R-002 transport adapter 与 lease 签发/消费只在 orchestrator closure 内完成。FAILED receipt 仍可单独审计，deterministic zero-token DEFER 仍无 model receipt。

本轮 deterministic 回归新增 pending-flag 注入、orchestrator 属性遍历、module executor import 与 direct adapters provider 四个 reviewer 复现；原 missing output/run、atomic batch、family、trust root、cross-proof、failure、usage、root 等攻击继续保留。生产形态 synthetic synthesis + experiment-design + critic E2E 继续仅经 public orchestrator，research/critic completed evidence 均以 atomic batch 提交。R-002 五个定向文件 69 项通过；`make check` 通过（ruff format/check、mypy 74 个 source files、secret scan、schema compatibility 2、unit 1、property 9、contract 367、health）。这些是 `gpt-5.6-sol` / `high` 实现者自证；未运行任何 diagnostic/holdout/shadow，也不表示 suite freeze、Phase 0 完成或整体主链成立。

第六次独立 `gpt-5.6-sol` / `xhigh` 验收结论为 `ACCEPT_RUNTIME_SLICE`，P0/P1/P2/P3 均为 0。reviewer 复验 R-002 五个定向文件 69 项通过；完整 `make check` 通过（contract 367、mypy 74 个 source files，以及 ruff format/check、secret scan、schema compatibility 2、unit 1、property 9、health），`git diff --check` 通过。该接受仅覆盖 exact runtime receipt lineage slice；整体 `MVP-R-002` 仍为 `IN_PROGRESS` / `AUTHORIZED_NOT_FROZEN`，真实最小 capability probe 与可信 `FROZEN` Evidence 尚未完成，仍未运行 diagnostic、holdout 或 shadow。按本任务威胁模型，任意同进程代码主动反射 Python function closure 不被视为 authority boundary，因而不是本 slice 的阻断项；进一步做进程隔离或不可反射 capability container 可作为后续 hardening，不改变本次接受结论。foundation/runtime 早期实现模型为 `gpt-5.6-terra` / `high`，receipt lineage 与五轮修复的实际实现模型为 `gpt-5.6-sol` / `high`。

## 历史进展：MVP-R-001

2026-08-27 使用 `gpt-5.6-terra` / `high` 建立最小真实模型适配与不可绕过的试验边界：stateless OpenAI Responses、冻结 prompt/config/tool schemas、治理签名 preflight capability、真实数据 manifest/provider-contract 授权、逐记录 PIT Episode issuer、串行工具参数前置校验、数值/单位双指针 grounding、语义 Replay 与 evaluator 事件签名。独立 `gpt-5.6-sol` / `high` 多轮复核发现的自证评分、调用方自选工具、PIT 仅验哈希、license 文本猜测、preflight 可绕过、数值 grounding 不完整、provider 错误处理、工具结果 owner 自证及 caller 伪造 roster 等问题均已按反例加固；最终独立签字因 reviewer usage limit 尚未取得，不能写成“无 P0–P3”。

已新增 [`LLM-SCENARIO-AND-MODEL-ROUTING.md`](./LLM-SCENARIO-AND-MODEL-ROUTING.md)，完整盘点 V1–V5 的 12 个逻辑 Agent、用户交互与独立验收 workload，并把 Luna/Terra/Sol 降为可替换的版本化 Model Profile 当前映射；交易/风险/执行/学习/治理真值路径仍明确 `NO_LLM`。该文档是 `PROPOSED — NOT ACTIVATED`，尚未实现 Registry，也不改变 MVP-R Gate。

用户关于 Grok 的决定已澄清：只规定本次 `MVP-R-001` **代码开发**不使用 Grok，不排除 Grok 成为产品运行时某个 workload 的候选 Profile。产品 provider 仍保持 OpenAI/Codex/Grok 中立；任何 Grok 业务运行都必须独立评测、冻结 suite 和记录 Evidence，不能因插件可用而自动启用。

2026-08-28 继续使用 `gpt-5.6-terra` / `high` 完成首个可维护路由契约：`WorkloadId`、`ModelProfileRevision`、`ModelActivationBinding`、`ResolvedRunConfig` 和 runner capability gate 已落地，MVP-R 正式配置不再只靠散落的 provider/model 字符串。未资格化或 revision/digest 漂移的 Profile 无法激活或解析。

已安装官方 `openai-codex 0.147.0` 与固定 `openai-codex-cli-bin 0.147.0`，并实现 ChatGPT 登录态 App Server adapter。每回合使用独立 ephemeral thread、空临时目录、read-only、`approvalPolicy=never`、空 MCP 配置和显式 decline handler；动态工具只捕获一个 typed request，真实执行仍由确定性 loop 与 V1-010 owner executor 完成。完整 11 工具实测返回 model `gpt-5.6-terra`、provider `openai`、零 reroute，唯一 server request 为 `item/tool/call`，usage 为 input `13903`、cached `13056`、output `15`、total `13918`；完整 conclusion schema 也单独实测通过。任何内置工具 item、未知 request、多工具调用、reroute 或 usage/schema 缺失均 fail closed。因此 `CODEX_LOCAL + CHATGPT_SESSION` Profile 已为 `QUALIFIED`，但尚未随完整 suite `ACTIVE`。证据见 [`MVP-R-001-CODEX-RUNNER-EVIDENCE.md`](./MVP-R-001-CODEX-RUNNER-EVIDENCE.md)。没有读取或复制认证文件。

已实现交易所官方日行情与问财辅助查询的独立只读 adapter。SHFE/CZCE 强制 HTTPS、host/path allowlist、响应上限、redirect 边界、exact raw hash 和保守 `available_time=acquired_at`；2024-01-02 真实探针规范化 SHFE 279 行（AG/CU 各 12）及 CZCE 214 行（MA 12、SR 6）。问财两个 `1.0.0` Skill 已安装并实测，但项目不依赖其安装目录；独立 adapter 固定 endpoint、skill/version 和 trace/hash，凭据不落 Evidence。问财只作当前查询/shadow/交叉核验，不作历史 PIT 主源。`DCE.M` 因 412/WAF、`CFFEX.IF` 因历史入口仅 HTTP 暂不进入本轮，候选宇宙调整为 AG/CU/MA/SR。详见 [`MVP-R-001-DATA-SOURCE-EVIDENCE.md`](./MVP-R-001-DATA-SOURCE-EVIDENCE.md)。

恢复由 Codex 使用 `gpt-5.6-terra` / `high` 开发后，已补 governed official-data materializer、keyed composite-stratified roster 与 V1-010 executor binding。前者生成 raw/normalized PIT 双 manifest，复算 raw normalization、绑定 exact hash/上游 ID，并强制 `as_of == acquired_at`；只有治理白名单内、具有 RAW 上游的确定性 normalizer 才能取得真实数据授权，未知转换和 synthetic 数据仍 fail closed。roster authority 按 Instrument × UP/DOWN/RANGE/REVERSAL/EXTREME/FALSE_BREAKOUT/NOISE 分层，以不外泄的 HMAC key 可复现冻结 30 diagnostic 或 50 holdout，并签名候选池 commitment。Episode issuer 现可绑定 exact `MarketSnapshot`，V1-010 owner executor 只能返回其 frozen input hash 范围内的 source refs。尚未生成或消费真实 holdout。

已按用户批准的 retrospective sealed replay 路线固化 2026-01-05 至 2026-08-27 的 SHFE/CZCE 官方研究序列：AG/CU/MA/SR 各 158 个交易日，共 632 条规范化记录，实际 acquisition 为 `2026-08-28T04:01:01.279125Z`。回放明确分离真实 acquisition `as_of` 与模型可见的 `market_cutoff`，每个 Episode 使用 40 根历史记录和封存的 5 日 future reveal；后见数据只归 evaluator，未进入模型、Prompt 或工具结果。

Phase 1 正式 diagnostic suite `3f8a57fcd57b3b0b4483cddfe6968b45acaed27af9c65d8b33e5871628d23775` 已使用产品运行模型 `gpt-5.6-terra` / `medium` 完成 30/30 Episode。开发实现仍按安全关键路由使用 Codex `gpt-5.6-terra` / `high`，本批未使用 Grok。每条都严格调用 historical、L0、compact L1 后输出，合计 2,149,792 tokens，平均 55,627 ms；结论为 21 个 `NO_OPPORTUNITY`、9 个 `OPPORTUNITY_CANDIDATE`。9 个候选在 evaluator 解封后的五日方向检验中 4 个一致；确定性同规则基线为 11 个候选、5 个一致，Agent 与基线 28/30 决策相同且未产生正增量。可复现 scorecard digest 为 `76460c64334d1518ed6e3d07de9af876c5932b35987dbb8aefb6e4605d5b0085`。

Iteration 1 当时只证明工程可靠性，智能有效性尚未成立，因此按协议记录 `holdout_ready=false` 并进入一次 `ITERATE`；该历史结果未被后续 suite 覆盖或伪装成通过。

2026-08-29 用户记录 `ITERATE` 后完成 iteration 2：确定性代码预取 historical/L0/L1，产品模型 `gpt-5.6-terra` / `medium` 只用一个回合生成假设报告，独立 Critic 执行 veto。冻结 suite `5cd69c3d851f71c356c0e569e20b2e6f0fa49ef0e6a0aac4426b4011e043c642` 的第二轮 diagnostic 为 30/30 完成，Critical 4/4、Critic fault 60/60；Agent + Critic 留下 3 个候选且 3 个五日方向一致，确定性基线为 5/2。usage 从 iteration 1 的 2,149,792 降至 583,597 tokens。

同一冻结 suite 随后完成 50 条新 holdout：49 条成功、1 条显式 `CODEX_PROVIDER_FAILED`，满足 49/50 可靠性线；Agent without Critic 为 35 候选/17 个方向一致，Agent + Critic 为 5/3，确定性基线为 11/4。Critical 4/4、Critic fault 98/98、49 个完成结论 hypothesis 字段齐全；平均 19,113 tokens、25,792 ms。自动 scorecard `7a4387cc1eb05711996e1a9fc0b432b1ed3324c7dd00d6e77f0362ce8cb399b9` 为 `holdout_passed=true`，签名 hard-gate scorecard `5ad1c431f5f2ecb599669a6b16bc7650927f6242ecf05d0cd0c2a8c83ea43658` 为 `passed=true`。

已从 Critic 接受的 future-blind 结果中冻结 10 份 shadow 报告，roster digest `715d72e7fd2e02f9ee3b7c11b62209e7495c220cdf67711ada9ea8f44dbc1a69`。当前唯一未完成项是用户真实评价与最终治理决定；不得由 Agent 代填反馈或自动产生 `GO`。

用户表示 iteration 2 Shadow 报告本人无法直接理解，并让另一个 AI 评审下游 LLM 可用性。评审结论为研究骨架可用、机器交接字段不足，建议 `ITERATE`；其十行“价值/省时”不能冒充真人反馈。用户已批准 iteration 3，也是冻结最大三次预算内最后一次：新增确定性 `mvp-r.machine-handoff.v1`，修正 positive-fold 与 accuracy 重复，固定窗口/单位/成本/方向/门槛/非交易标志和下一实验参数。旧 holdout 不变，新 holdout 尚未授权运行。

Iteration 3 首次 diagnostic suite `c8717433edf79e332022247793dfbbf058c94662a6bda6df7c0be453e3bfbf07` 为 28/30，因一个 Critical provider failure 和一个唯一指针标点错误未达到可靠性与 Critical 4/4，已封存为失败 Evidence；25/25 个应生成的机器交接全部严格 hydrate，Critic fault 56/56。现处于同一 iteration 的 `REPAIR`：必需结果失败时确定性零-token `DEFER`，唯一 exact value+unit 才能规范化指针；模型/Prompt/数据/门槛均不变，repair suite 尚未完成。

Repair diagnostic suite `e41367db3afe7f35ae13f6dd092e9c80cd175ceee0748918657ccbcdd76513c3` 已 30/30、Critical 4/4、Critic 60/60；26/26 handoff 可 hydrate，1 个可直接实例化实验、24 个确定性不推进、1 个仅观察，平均 17,129 tokens、22,690 ms，冻结交接门槛后的 scorecard `e426d3999bf50dc081628027c74b8efc15741c214151038eaabf5bbd1d5332d2` 为 `holdout_ready=true`。已在查看新 holdout 前冻结机器交接 100% 完整、至少一个 READY 且至少一个 DO_NOT_ADVANCE；下一步运行 50 条 repair holdout。

同一 suite 的 holdout 已封存失败：13 完成、37 条 `CODEX_PROVIDER_FAILED`，从第 14 条起每条约 5 秒失败。现进入同一 iteration 的第二次 `REPAIR`：瞬时 provider 失败最多重试两次（5 秒、15 秒），语义/权限/grounding 失败不重试；revision `3-repair-2` 尚未完成。

Repair-2 diagnostic suite `4c7a956d7696b01258cdd6a1ad1c20482114cc26edd62e19c96c945721d7a48a` 已失败：4/30 完成，后 26 条全部 `CODEX_PROVIDER_FAILED`，重试未恢复。scorecard `41679ebb6585b197524335f6d6cdfb4fd8f9c1c45ab3f254f84def9106a51aa7` 为 `holdout_ready=false`。当前阻塞是 Codex provider 可用性，不是交接契约本身。

用户指示继续后，先做 1 条真实模型探针而非整批重跑。探针完成且交接有效，Codex provider 已恢复。现开 revision `3-repair-3` 完整重跑 diagnostic；旧失败 Evidence 不覆盖。

Repair-3 diagnostic suite `e1789aff7f92b2de3c526e0d9f08574c0008fce6e3e3978d97c9a12d7f7a05ee` 为 29/30、Critical 4/4、Critic 58/58；25/25 handoff 可 hydrate，1 个可直接实例化实验、23 个确定性不推进、1 个仅观察。scorecard `3f6003d52f76cfcc78317617af6ae8d5ed6f3c4b2b5dcc4141896123a7902b35` 为 `holdout_ready=true`。下一步运行 50 条 holdout。

同一 suite 的 holdout 50/50 完成，机器交接 46/46 可 hydrate，2 个可直接实例化实验、42 个确定性不推进。智能门槛未过：Agent + Critic 4/2，未超过确定性基线 11/5。scorecard `5b59f194a5cf3e69e4f330f8fe01f483e85e7bcc4d769fe10e57aff54759c529` 为 `holdout_passed=false`。不得覆盖该 Evidence，也不得自动 `GO`。

用户于 2026-08-29 明确批准第四次智能迭代，作为对原最大三次预算的治理例外。代码层 `maximum_iterations` 上限已精确扩为 4；该决定不是 `GO`，不覆盖旧 Evidence，不允许复用已查看 future reveal 的 holdout，也不解锁 `V1-011`。

Revision 4 已冻结为“基线约束的残差研究”：模型不得在确定性 family evidence gate 外提名候选，Critic 固定 family/regime 匹配；确定性 baseline 修正逆势 accuracy 与 positive-fold 计算，避免以弱基线制造假增量。suite `bc658765a8e466b15a6b6ca4c3f42222315b2480e2a7554909c8d8197fac3e12`、prompt `06bcce06fd3a040f2b85ad4f6192e17a77741a3259464f861faf7e530513c8b0`、diagnostic roster `224a6a079fcf4773ed7e9f2ef1fb2219b0d4104ecc6eb0cab3220418b01b7cb1` 已冻结。新 holdout 排除 Iteration 3 已解封的 50 个 Episode identity。

Revision 4 diagnostic 随后 30/30 完成：Agent 3/2、Critic 2/2、修正后确定性 baseline 3/2；Critical 4/4、fault 60/60、machine handoff 26/26，平均 17,236 tokens、23,094 ms。scorecard `1045ff615bbcf7bacbcc8a09a243b5da0bf321395010516838db31708c5f4c5d` 为 `holdout_ready=true`。已在查看新 future value 前冻结排除旧 50 时点的 holdout roster `969e5631f18a9d68d9bc5b17b3c629cf01378609b2f6476ebbe732724c866cf0`；尚未运行。

Revision 4 holdout 已 50/50 完成，无 provider 失败；Critical 4/4、fault 100/100、machine handoff 46/46，平均 18,325 tokens、25,392 ms。Agent + Critic 为 6 候选/3 个方向一致，Critic 未否决模型候选；修正后的最强确定性 baseline 为 16/8，二者精度同为 50%。scorecard `1d1840b84f378795737b7c2ebf77abcdcfbab9d9efd751db6f8e6bcfeca8bee9` 为 `holdout_passed=false`。第四次智能迭代正式失败且预算已用尽；不得自动 `GO`、不得继续同 suite 调参、不得进入 `V1-011`。

用户于 2026-08-30 明确批准能力 `PIVOT`：不再让 LLM 对单一 prior-close signal 做顺/逆势分类，而是先由确定性代码验证顺势、均值回归、突破延续、假突破反转、参与确认趋势和波动压缩突破六个 family，再由独立 Research/Critic Agent 综合与反证。期限结构、库存、新闻和宏观因当前无合格 PIT 输入不进入。旧 3–8 月 future path 已暴露，只能作开发诊断；最终 holdout 必须使用 Pivot 之后新产生的数据。当前已实现 causal family screen、family-specific baseline、封闭 wire enum 与确定性 Critic 基础契约；仍不是 `GO`。

Pivot 双 Agent 契约、独立 Critic 签名授权、确定性前置门槛、严格非交易 machine handoff、critical/fault 注入、开发 runner 与 evaluator 已完成。开发诊断冻结为 suite `ef6e2a43afa5b461023e1ff1733bd33348382ed858b3610207ed591263d6dcd3`、Research Prompt `6c46e8cc990902369934056e6a69fad2048c7a27b52699b2d996bc4e8baa2d38`、Critic Prompt `9e684d45600cc3f2b4638bf4b85daadb688717fa9694f2b6c5edb0e19a8eed8f`、roster `f141cfa50b91a00566fe3c741a57a0e7324778ad87adfd653c0a2d368b6c3eac`。真实链路探针已分别证明零 token evidence-unavailable `DEFER`、确定性 veto 阻断 independent Critic，以及双 Critic `ACCEPT → CONTINUE_TEST`；探针属于被旧 future path 污染的开发证据，不是价值结论。实际实现模型为 `gpt-5.6-sol` / `high`，未委托独立 reviewer；下一步只允许运行该冻结 development suite。

该 development suite 随后 30/30 artifact 封存但仅 13 条完成，第 16 条起连续 15 条记为 `CODEX_PROVIDER_FAILED`；Critical 4/4、fault 26/26、handoff 13/13，independent Critic 因无 proposal 通过确定性 floor 而零调用。scorecard `f440d2f542b84dde5ccd2ee1f961f41234f5fee0edfd874038384faa1d50cf11` 为失败 Evidence。小输入同 schema 的官方 App Server 同期可成功，故进入不改 Prompt/数据/floor 的 adapter 可观测性 REPAIR：transport、invalid JSON、contract 与 policy failure 已拆分，repair suite `6a38e42255b9c24bb94106058d8121e832df18aebf4f68ba85901895ede2378d` / roster `a346a8f95c6f7a2ba989bf38b589da62e5811bae85b74c72b5002c58d547163d` 已冻结。下一步只跑一条 repair probe，再决定是否完整重跑。

repair probe 已证明模型返回 FINAL 与 usage，真实失败码为 `UNVERIFIED_CLAIM_EVIDENCE`。下一步 observability-only suite `9610be30d74e9fd5acacdd16149f0776800c5b2630ec9874093c19e59e3ff7fe` 只在失败 artifact 中保留已有结构化 conclusion，检查 exact grounding pointer；不放宽规则、不重跑整批。

随后两个 probe 均在 hydration 前返回 generic response-contract failure；现进一步冻结非敏感 parser failure bucket suite `9cadae7a28e4458ee7c37a4fc80fd94dd2a301b39f08157d1712a49e0bdd0155`，下一步只跑一条 probe 确认是 prose digits、pointer、numeric grounding、usage 还是 payload shape。

分类结果为 `CODEX_RESPONSE_NUMERIC_GROUNDING`。现用独立 Pivot wire schema 禁止模型复述数字并固定 numeric fields 为 null，确定性 evidence 保留全部数值；旧 schema 不变。wire-repair suite `cb7b355c78b737780ab0597e7d3f2027cac402aefb6ff5224a253988132757d9` / roster `4122d8b104b495048b8e7f19607f2cdac7272818795ac8414a83dbb1abff065b` 已冻结，下一步只跑一条 probe。

wire-repair probe 已完成且 2/2 fault 被捕获，无 provider/parse/grounding failure。下一步运行同一冻结 suite 的完整 30 条 development repair，不再修改冻结输入。

完整 development repair 随后 30/30 完成：Critical 4/4、fault 60/60、handoff 30/30；1 `CONTINUE_TEST`、25 `DO_NOT_ADVANCE`、4 `DEFER`；independent Critic 5 次调用为 4 VETO / 1 ACCEPT 且零失败。平均 20,867 tokens、22,639 ms；scorecard `72068447e1e7335b52ec0acd6fab030801e5a61f7f43d6cb46ac51a09e4a81ab` 为 `development_diagnostic_passed=true`。旧 future 上 raw 12/4、floor 后 5/2、Critic 后 1/1、baseline 8/2 只作描述，不构成最终智能增益。当前唯一不可修复于今天的 blocker 是 post-Pivot forward data 尚未产生；任务仍不是 `GO`。

最终 `make check` 通过：mypy 70 source files、contract 299、property 9，其余 format/lint/secret/schema/unit/health 全绿；`git diff --check` 通过。资格脚本 live 复验为 SDK/CLI 0.147.0、Terra/medium、11 工具、1 dynamic call、零 reroute、未超时。实际实现模型 `gpt-5.6-sol` / `high`，未委托独立 reviewer。

用户继续 `MVP-R-001` 后，已把真正的 forward 因果边界落成 `mvp-r.pivot-forward.v1`：collection authority 每个新交易日只接受 AG/CU/MA/SR 四品种完整 PIT 记录并形成签名链；每个 cutoff 在下一交易日数据出现前签名 40-bar input、六 family screen 和 future-blind stratum scores；roster authority 少于 50 条 commitment 固定拒绝，且接口不接收 reveal；evaluator 只允许冻结 roster 中 Episode 解封签名链紧接着的五个交易日。改签名、跳过不利 label、提前解封或 commitment 晚于第一条 label acquisition 均 fail closed。

最终 intelligence 门槛也已在任何 post-Pivot reveal 前冻结：50 条至少 49 完成、Critical 4/4、fault recall 至少 95%、handoff 100%、至少 1 `CONTINUE_TEST` 和 1 `DO_NOT_ADVANCE`、Critic 至少保留 3 个候选；Agent + Critic 精度必须严格高于 Agent without Critic 且不低于最强确定性 family baseline，平均 token 不超过 25,000、延迟不超过 45 秒。之后仍需 10 次真人 shadow 与用户 `GO`。

`scripts/collect_mvp_r_forward.py --plan-only` 已验证今天 `2026-08-30` 是决策日而非合格 forward 日期，首个候选日为 `2026-08-31`：签名采集日 0、commitment 0、future reveal 锁定。采集入口禁止跨过未签名工作日；官方休市必须先有合格 closure attestation，不能让后一天静默补位。另已加入只接受 chain tip、且必须在同一上海自然日运行的 `scripts/commit_mvp_r_forward_day.py`，自动把已治理历史上下文与当天新 bar 组成四条 40-bar commitment；迟交不能倒签。四品种每日最多四条，理论上至少需要 13 个完整新交易日形成 50 条，再等最后一批五个交易日，合计至少 18 个完整交易日；休市、缺数或漏采会延长。新增反例测试 3 项通过，Ruff 与 mypy（71 source files）通过；实际实现模型 `gpt-5.6-sol` / `high`，未委托独立 reviewer。当前可继续的是按日采集，不能用 repair 制造尚未发生的 future。

`scripts/freeze_mvp_r_forward_roster.py --plan-only` 只读取 commitment 目录，当前为 0/50，返回 `FEWER_THAN_FIFTY_COMMITMENTS` 且 `future_reveal_read=false`；正式模式会用独立 roster key 分层冻结恰好 50 条并不可变写入。最终 `make check` 全绿：mypy 71 source files、contract 302、property 9，其余 format/lint/secret/schema/unit/health 均通过，`git diff --check` 通过。

2026-08-31 00:00（Asia/Shanghai）进入首个合格候选日；只读状态确认 expected next weekday=`2026-08-31`、eligible=true，但官方当日日线尚未产生，故仍为 0 acquisition / 0 commitment，blocker=`OFFICIAL_DAY_NOT_YET_ACQUIRED`，没有发起网络采集或写入。已在当前任务建立工作日收盘后继续的 heartbeat `MVP-R forward 日采集`：先检查日期和完整性，成功才依次采集、同日 commitment、验证并更新 Evidence；失败保持链不变。达到 50 条前不会 freeze，任何阶段都不会提前 reveal。

用户随后授权不等待 18 个真实交易日，由 Codex 使用历史数据判断。现采用双轨：forward heartbeat 保留为后续确认；本次立即运行全新 2025-01-02 至 2025-06-30 retrospective sealed holdout，证据等级明确低于 prospective forward。SHFE/CZCE 各取得 117 个完整交易日，AG/CU/MA/SR 共 468 条，collection summary `4b9ad877ed35e08d8b917b9f460af3b0440f531d81717d59583abf8a415a9ed1`。在读取任何五日 label value 前已固定 suite `8485bc807c6c50ca781c906998742796cf14e76d3d05f870224c58039bfc09c7`、50 条 roster `374730d6e4ffbf1fd02b293be4b70b86b8511d0dc4835d7971bd69200f33c842`、runtime `12382e9db1259678253112c02f34d9e733aca8aefe865376de43cf488f0c4dc9` 和双 Prompt；下一步只运行该历史 holdout，不得改门槛或 roster。

历史 holdout 的独立评分入口也在运行前冻结，SHA-256 `74e15fb3e2cb0422a4bbf6519cdd27ae0efe3802d67131aa99e11efc8203e757`。它把 Agent without Critic 固定为通过确定性 family floor、但尚未经 independent Critic 的候选，严格执行第 17 节 49/50、Critical、fault、handoff、候选数、精度增量、baseline、token 与时延门槛；只在运行封存后读取 fifth-future label。

该 retrospective confirmation 已完成并失败：45/50 完成，5 条全部为 `UNVERIFIED_CLAIM_EVIDENCE`，根因是模型生成了形状合法但实际不存在的非数值 metric pointer，运行时正确 fail closed。Critical 4/4、fault 90/90、hypothesis/handoff 45/45、Critic 19 次无调用失败；Critic 仅保留 2 个候选。解封后 Agent without independent Critic 为 19/9、Agent + Critic 为 2/1、最强 family baseline 为 21/10；精度点估计满足算术比较，但候选少于 3、完成数少于 49，且平均 25,026 tokens 超上限 26。平均时延 24,050 ms。scorecard `751631cbab3da76732f6fd12d3345d2a910859f9dbf70e54de8b4cfcb9f24048`，rows digest `decb57f1dd6ea84d98366ef46079168998d57e1aa57ec3c92a82d84e236576dd`。

Codex 依据用户授权记录最终治理判断 `STOP_CURRENT_CAPABILITY`。本版本不进入 10 次 Shadow、不是 `GO`、不解锁 `V1-011`；同一已解封历史 holdout 不得修补或重跑。若未来重新定义能力 Pivot，pointer/schema 和 token 可作为工程输入，prospective forward 数据只能用于新版本确认。

工作日 `MVP-R forward 日采集` heartbeat 已暂停，避免在当前能力已停止后继续收集无对应冻结决策用途的数据；automation 配置保留，可在未来新能力 Pivot 获得明确授权并重新预注册后再评估恢复。

最终 `make check` 全绿：mypy 71 source files、schema compatibility 2、unit 1、property 9、contract 302，Ruff、secret scan 和 health 同时通过；`git diff --check` 与 scorecard digest 复验通过。实现、判分和治理模型为 `gpt-5.6-sol` / `high`，产品运行模型为 `gpt-5.6-terra` / `medium`，未委托独立 reviewer。

本轮最终 `make check` 通过：Ruff format/lint、mypy（67 个 source files）、secret scan、schema compatibility、unit、property（9 passed）、contract（292 passed）和 health 均通过；Iteration 4 预算定向契约测试 37 项通过，`git diff --check` 通过。

## 给下一段对话的上下文胶囊

本项目是从零建设的 **Agent Quant Research & Simulation OS**，不是 `futures_workflow` 的重构、迁移、兼容升级或替代分支。对用户呈现为一个能独立找机会、模拟交易、盯盘和复盘的 Agent，内部由受限的专业 Agent 与确定性内核协作。

新系统必须拥有独立仓库、独立数据模型、独立数据库、独立配置和独立运行生命周期。`/Users/qiu/futures_workflow` 只是 donor，可供只读审计、算法移植、测试样本和失败案例参考；其代码、测试或数据库状态不构成新项目完成度，也不阻塞 V0 开始。

核心安全边界：

- Agent 对建立/增加/反向暴露只产生结构化 TradePlan；对已有暴露的 REDUCE/CLOSE/收紧保护只提交 RiskReductionRequest。两条路径都不能直接创建 Order、Fill、Position 或 LedgerEntry，降险请求还必须经过 Execution 的 T4-SAFE Validation 才能成为 ProtectiveRiskAction。
- 价格、规则、账户、持仓、PnL、保证金、成交与结算由确定性工具/内核给出。
- Risk Analyst Agent 只分析风险；Risk Constitution 才能产生权威 `RiskDecision`。
- 没有 Thesis、Invalidation、ProtectionIntent、MaxLoss、有效快照、有效 `AuthorizationBasis`（Simulation Autonomy Mandate 或可选 PlanApproval）、原子 RiskBudgetReservation 和单用途 AutonomyGateReceipt 的开仓计划不得进入 Risk Constitution；RiskDecision 才生成 ProtectionMandate，Execution 再把它落地为 StopPolicy。
- Simulation Autonomy Mandate 由 Decision 上下文拥有，是可暂停、恢复、撤销、过期且有明确作用域的长期模拟委托；它不是 RiskDecision、RiskBudget、ToolGrant 或 Strategy Activation。
- 日常自主模拟的必要条件是 `EffectiveAutonomy = ACTIVE Mandate ∧ ACTIVE AUTONOMOUS_SIMULATION Binding ∧ qualified bindings ∧ health permits`；满足后，机会扫描、计划、模拟执行、盯盘和复盘不等待用户逐笔操作。系统主动推送重要信息和完整证据，用户可随时暂停/撤销 Mandate、暂停运行模式或触发 Kill Switch。
- 保护性退出、Kill Switch 和日终结算不依赖 LLM、飞书或 Agent 在线。
- Reflection 不是知识；只有有证据、通过验证且带适用范围和有效期的内容才是 ValidatedLesson。
- 产品只用于研究与模拟；真实资金和真实下单不在范围内。

## 完整目标角色

目标逻辑角色为 Autonomous Quant PM / Main、Market Regime、Research、Strategy、Portfolio、Risk Analyst、Execution Advisor、Pre-trade Critic、Experiment Manager、Post-trade Reviewer、Memory Curator 和 Governance Agent；确定性 Workflow Orchestrator 负责触发、状态推进、重试与恢复，不计入 Agent 角色。Governance Agent 在 V5 可扩展 Model/Policy Steward 工作模式。

这些角色不等于十二个常驻服务。源码可采用模块化 monorepo，物理运行按 Gateway、Agent Worker、Research Worker、Trading Worker、Market Ingest 和 Scheduler/Outbox Sender 等安全与故障边界拆分。Agent 之间只交换版本化 artifact，不自由共享可变业务对象。

## 版本顺序

| 版本 | 结果 |
|---|---|
| V0 地基 | 新仓库、领域/Agent/Tool 契约、PostgreSQL、数据 manifest、安全与 CI |
| V1 自主研究与机会雷达 | Main、Regime、Research、Critic、基础 Experiment Manager 按用户、时间表或市场事件完成只读可复现机会研究 |
| MVP-R 研究可用性门槛 | `V1-010` 后用真实模型、授权真实 PIT 数据、Replay/基线/Critic ablation 和用户 shadow 证明研究价值；`GO` 才解锁 `V1-011` |
| V2 确定性模拟内核 | 原子风险预留、最小 AutonomyGate/Receipt、硬风控、订单、撮合、账本、结算、保护和恢复无需 LLM |
| V3 受约束自治多 Agent 模拟交易 | EffectiveAutonomy 成立时自主找机会、论证、模拟执行、盯盘、复盘和重要信息通知 |
| V4 验证学习 | Experiment 与 V3 Reviewer 扩展、Memory、Lesson 与 Strategy 晋升闭环 |
| V5 高保真/离线增强 | Tick/订单簿/Paper、组合扩展、离线模型增强和运营成熟 |

详细任务、依赖和 Acceptance 只以 `ROADMAP.md` 为准。当前 `V0-001` 至 `V0-014`、`V1-001` 至 `V1-010` 与 `MVP-R-005` 已完成；`MVP-R-001` 与 `MVP-R-002` 已停止，`MVP-R-003` v1 记为测量方案失败，`MVP-R-004` 已 `STOP/PIVOT`。当前无开发任务获授权。`MVP-R-005` 完成不是 `GO`；正式 eval 与 `V1-011` 仍锁定。

## 设计资料状态

- PRD、技术方案、上下文地图和 ADR 已作为新仓库的设计基线入库；`docs/adr/0001` 至 `0007` 已由 `V0-002` 接受，后续实现必须遵守。
- `LEGACY-ASSET-REUSE.md` 只记录 donor 资格，不是迁移计划，也不是进度基线。
- 对旧项目执行过的测试仅是 donor 审计证据；新项目必须拥有自己的 CI、契约测试、属性测试、黄金回放和 Agent eval。
- 新项目仓库为 `/Users/qiu/work/futures-agent-os`；项目名 `futures-agent-os`，包名 `futures_agent_os`，Python 3.14，uv，MIT License；首个基线 commit 为 `8d00a4331581026175270ae3bfa1414d438dc5df`。
- PostgreSQL 从新项目首个持久版本使用；不存在 SQLite 业务主库迁移阶段。

## 最近完成：V0-001

2026-08-18 完成以下范围：

1. 确认新项目名称和绝对路径。
2. 初始化独立 Git 仓库、许可证、运行时、依赖管理和目录骨架。
3. 建立最小健康检查与测试入口。
4. 证明 clean checkout 不读取旧仓库代码、数据库或配置即可运行。
5. 已把基线 commit 和验证命令作为 Evidence 写回 `ROADMAP.md` 并勾选 `V0-001`。

验证结果：clean clone 执行 `uv sync --locked` 成功，`uv run pytest` 为 `2 passed`，健康检查返回 `legacy_runtime_dependency=false`。未移植 donor 代码、未创建交易能力、未修改旧仓库、未启用外部消息。

## 最近完成：V0-002

2026-08-18 按领域建模门槛审阅并接受 7 项绿地架构决策，建立 `docs/adr/README.md` 索引和 ADR 契约测试。基线 commit 为 `dad8c5802abba56fa285a53ee6b7e436daf093fd`，`uv run pytest` 为 `5 passed`。未实现数据库、交易或 Agent 运行时。

## 最近完成：V0-003

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成领域边界基线，统筹对话复核。9 个核心业务上下文、1 个 supporting context、16 个关键聚合 owner 和 201 个 canonical term 均纳入自动检查；commit 为 `8d53b4b2ae485848b25153d50ff1a0d8fb796412`，`uv run pytest` 为 `10 passed`。未提前实现跨上下文业务功能。

## 最近完成：V0-004

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成共享内核契约，统筹对话补强定点 scale、极端 Decimal 与 Failure 序列化边界。commit 为 `eadb35640365a03759bcedf53446dbbfb8c0fb1e`，`uv run pytest` 为 `19 passed`。`TradingDate` 明确保留给交易日历赋值，夜盘归属不会由共享内核根据自然日猜测。

## 最近完成：V0-005

2026-08-18 使用 `gpt-5.6-terra` / `medium` 完成版本化 Agent Catalog、任务信封、不可变 artifact 与有界 handoff 协议，统筹对话补强预算、输入、重复声明和失败结果边界。commit 为 `6070d236f0129de01455001870cdaf2b3f87b66a`，`uv run pytest` 为 `24 passed`。12 个逻辑角色不等于 12 个常驻服务，Catalog 声明也不等于 Tool Grant 或运行启用。

## 最近完成：V0-006

2026-08-18 使用 `gpt-5.6-terra` / `high` 完成 Tool Registry、ToolGrant、ToolScope 与默认拒绝授权判定，统筹对话修正 owner、交易/治理 scope 和受信 Grant 来源边界。commit 为 `2ed377491212de476ec20bc9521fe48f9affba1e`，`uv run pytest` 为 `39 passed`。Registry 与权限判定不执行工具，也不替代业务授权或风险许可。

## 最近完成：V0-007

已使用 `gpt-5.6-terra` / `high` 建立 PostgreSQL 初始 schema、正式 migration、数据库角色、inbox/outbox、任务租约、Mandate/可选批准、调度、监督通知和 durable checkpoint 基础，实现 commit 为 `64ceb630975fa46420875a8e8c383e8bfd9c1906`。已在 Homebrew PostgreSQL `17.11` 的隔离空库执行真实 `upgrade → downgrade → upgrade` 及 integration round-trip；`FAO_DATABASE_URL=postgresql+psycopg://qiu@/futures_agent_os_v0_007?host=/tmp uv run pytest` 为 `48 passed`。业务 schema 与 Agent checkpoint 已验证隔离，且无旧库导入。PostgreSQL 服务已作为本机开发依赖启动。

## 最近完成：V0-008

已使用 `gpt-5.6-terra` / `medium` 建立本地、不可变的数据层契约与 content-addressed adapter，实现 commit 为 `87bc6416eb367d6f9f754134eba5fac3205ea6b4`。raw、normalized PIT、feature snapshot、dataset 与 artifact 都必须绑定完整 manifest。内容与 manifest identity 分离：相同 bytes 可服务多个独立修订，数据内容仍仅保存一次；读取一律验证内容 hash，PIT 记录必须在 `as_of` 前可用。`uv run pytest` 为 `53 passed, 1 skipped`；未接入外部数据源或 donor 运行时。

## 最近完成：V0-009

已使用 `gpt-5.6-terra` / `high` 建立 V0 安全契约，实现 commit 为 `4810527f049f1d0bc5c82b4b9a5d05035064dea6`。服务身份只绑定 versioned `secret://` 引用；结构化日志递归脱敏；外部文本被固定为数据且无法更改 ToolGrant/Policy authority；研究沙箱在 V0 仅作 default-deny 限额校验而不执行工作负载。统筹复核后强制所有权限和 sandbox collection 使用不可变容器，防止校验后篡改。`uv run pytest` 为 `60 passed, 1 skipped`。真实 secret manager、代码执行和网络连接仍未启用。

## 最近完成：V0-010

已使用 `gpt-5.6-terra` / `high` 建立统一 correlation/causation、命令幂等、追加审计、metrics/logs/traces 与最小告警框架，实现 commit 为 `50cd1b756ea301a5d4b4ea59a821956b08eb1df4`。统筹复核补强深度不可变 payload、并发单效果、真实 ToolCall trace、数据库往返隔离以及告警 runbook/用户影响范围。PostgreSQL `0002_v0_010` 已通过真实 downgrade/upgrade 与 append-only/idempotency 权限验证；全量测试为 `74 passed`。外部 tracing/exporter 尚未启用，本地审计与业务数据库仍是真值。

## 最近完成：V0-011

已使用 `gpt-5.6-terra` / `medium` 建立 CI、依赖锁、Ruff、mypy、Hypothesis、schema compatibility、detect-secrets 与分层测试门禁，基础实现 commit 为 `a2aaeeaba6ab102c3d55213005d0bb67604c4efb`。本地与 CI 共用 Make targets，第三方 Actions 固定 commit SHA；`make check`、真实 PostgreSQL integration 和 DB-backed 全量测试均通过，最终全量为 `80 passed`。远端公开仓库 `https://github.com/641500461/futures-agent-os` 的五个 Quality gate job 全绿；main branch protection 已启用，要求 PR 和 strict checks，禁止 force push/delete，管理员也受约束。V0-011 Acceptance 已全部满足。

## 最近完成：V0-012

2026-08-19 使用 `gpt-5.6-terra` / `medium` 实现 12 品种 synthetic/golden 数据集、非冗余产品理由、严格边界语义、可复现生成器与四资产 hash/bundle/release oracle。统筹对话使用独立 `gpt-5.6-sol` / `high` 三轮复核，最终无 P0–P3。`make check` 的 contract 为 `89 passed`，全量测试为 `91 passed, 2 skipped`。这些资产仅为 Q2 研究/回放夹具，不声称 tick、订单簿、成交或执行保真度。

## 最近完成：V0-013

2026-08-19 使用 `gpt-5.6-terra` / `medium` 建立 34 项 donor 资格清单、固定 Git provenance、强制 license/新接口/隔离/安全/新项目测试门禁与显式只读验证脚本；独立 `gpt-5.6-terra` / `high` 安全复核最终无 P0–P3。38 blob 与 1 ABSENT 通过固定 commit 复验；结果为 20 CANDIDATE、3 DEFERRED、9 EVIDENCE_ONLY、2 REJECTED、0 QUALIFIED。未修改 donor，未运行 donor 副作用，未读取旧 DB/状态。`make check` 的 contract 为 `98 passed`，全量为 `100 passed, 2 skipped`。

## 最近完成：V0-014

2026-08-21 使用 `gpt-5.6-terra` / `high` 实现自治授权与风险预留契约，独立 `gpt-5.6-sol` / `high` 多轮验收并最终确认无 P0–P3。内存参考模型与 PostgreSQL 持久语义已对齐；授权、预算、健康、快照、并发、到期、撤销、投影重建、迁移往返和最小权限反例全部关闭。`make check` 通过（contract `118 passed`），真实 PostgreSQL 全量测试 `145 passed`。V0 Exit 成立：新仓库可独立启动、测试、迁移与恢复，无 donor 运行时依赖。

## 最近完成：V1-001

2026-08-23 使用 `gpt-5.6-terra` / `medium` 完成不可变、版本化的 Instrument Registry，独立 `gpt-5.6-terra` / `high` 最终复验无 P0–P3。首批 12 品种 synthetic contracts、交易所交割码、PIT 可见性、固定 release oracle、半开区间和 alias 冲突均已覆盖；Variety、Dominant 与 Continuous Series 不可进入可交易解析。`make check` 的 contract 为 `137 passed`，真实 PostgreSQL 全量测试为 `165 passed`。未接入外部行情、真实交易或 donor 运行时。

## 最近完成：V1-002

2026-08-23 使用 `gpt-5.6-terra` / `high` 完成 Instrument 精确作用域、不可变且双时维的 `ContractRuleVersion` 与 `RuleSetRef`，独立 `gpt-5.6-terra` / `high` 最终复验无 P0–P3。完整规则集显式包含乘数、tick、最小量、保证金、开/平/平今费、涨跌停、sessions、最后交易日、交割限制、持仓/交易限额和 offset 规则；禁止字段继承、拼接、永久默认值和未来泄漏。`make check` 的 contract 为 `146 passed`，真实 PostgreSQL 全量测试为 `176 passed`。未实现 V1-003 日历推导、V2 资金计算、外部规则接入或交易副作用。

## 最近完成：V1-003

2026-08-23 使用 `gpt-5.6-terra` / `high` 完成 Variety 精确作用域、不可变且支持显式修订链的 PIT `TradingCalendar/TradingDateService`，独立 `gpt-5.6-terra` / `high` 最终复验无 P0–P3。四所代表性夜/日盘、竞价、午休、节假日、临时休市和早收均由显式 occurrence 归属 TradingDate；open→closure→reopen 可按历史 `as_of` 重放，未来修订不改变旧结果。`make check` 的 contract 为 `161 passed`，真实 PostgreSQL 全量测试为 `193 passed`。未接入官方日历数据、scheduler 或交易副作用。

## 最近完成：V1-004

2026-08-23 使用 `gpt-5.6-terra` / `high` 完成用途专属、不可变且内容寻址的 PIT `MarketObservation/MarketSnapshot`，独立 `gpt-5.6-terra` / `high` 最终复验无 P0–P3。规则、日历、Instrument Registry、Dataset Manifest 与逐记录证据均由实际不可变对象验证；质量判定覆盖缺失、陈旧、乱序、重复、冲突、未来、未完成、缺口、跳变、fallback 和不可信时间戳。修订链按 `as_of` 选择唯一 active leaf，连续合约、跨合约规则、闭市、零深度报价或伪造引用不能获得执行资格。`make check` 的 contract 为 `175 passed`、property 为 `9 passed`，真实 PostgreSQL 全量测试为 `210 passed`。未接入外部行情、Feature Engine、Agent 或交易副作用。

## 最近完成：V1-005

2026-08-24 使用 `gpt-5.6-terra` / `high` 完成版本化 Feature Engine 和确定性 Regime/Signal Model Service，独立 `gpt-5.6-sol` / `high` 以 15 组真实反例最终验收无 P0–P3。特征计算严格绑定唯一 market reference、ObservationKind、PIT 快照/记录、窗口、cadence、session、scale 与算法版本；固定 Decimal context、不可变 evidence 和内容哈希保证相同输入可重放。Regime/Signal 输出固定为 `NON_TRADING`，不能生成或替代 TradePlan、RiskDecision、Order 等权威对象。`make check` 的 contract 为 `184 passed`、property 为 `9 passed`，隔离 PostgreSQL 全量测试为 `219 passed`。期限结构、基差和跨换月连续历史因当前单 component 快照边界显式 defer，没有伪造完成度。

## 最近完成：V1-006

2026-08-24 使用 `gpt-5.6-terra` / `high` 完成 Market Regime Agent 与证据化 `MarketStateAssessment`，独立 `gpt-5.6-sol` / `high` 多轮反例验收最终无 P0–P3。Market Intelligence 负责纯领域组合，Agent Orchestration 仅处理 Catalog 1.1 task/artifact port 和 `StructuredArtifact` 包装；快照、全部特征与确定性 Regime 谱系、时间、schema 和 hash 必须精确一致。候选完整保留正反证据、未知项与替代解释，反证-only/unknown-only 不会被提升为主状态。输出固定 `NON_TRADING`，缺失或冲突只可 `DEFERRED`。`make check` 的 contract 为 `187 passed`、property 为 `9 passed`，隔离 PostgreSQL 全量测试为 `222 passed`。

## 最近完成：V1-007

2026-08-24 使用 `gpt-5.6-terra` / `high` 完成只读 Research Agent，独立 `gpt-5.6-sol` / `high` 四轮对抗验收最终无 P0–P3。Research & Experiment 以不可变、内容寻址的 `Hypothesis`、`EvidenceSynthesis` 与非执行 `ExperimentRequest` 消费精确 `MarketStateAssessment` 谱系；Hypothesis 显式包含适用市场、可观察结果、反证、所需数据、提出来源和完整七态生命周期，但 V1-007 只能创建/封装 `DRAFT`。实验请求固定数据、对照、评估窗口、方法、指标、诊断、停止条件和潜在偏差；显式空的 known/unknown/conflict/gap 不会被迫伪造。Catalog 升至 1.2 并仅声明本任务实际支持的 MarketStateAssessment 输入；封闭 duck-port schema、严格类型、深冻结、spec/source identity、跨 artifact 一致性与重放哈希均有真实反例。实现 commit 为 `5ee47cb`；`make check` 通过（contract `208 passed`、property `9 passed`、mypy `47` source files），连接隔离 PostgreSQL 的全量测试为 `243 passed`。没有模型升级；确定性测试与 Sol/high reviewer 而非模型输出裁决了 lifecycle owner、空冲突语义、bool-as-int、隐藏 authority 字段和数据谱系漂移。未实现实验执行、LLM/持久 AgentRun、用户观点/Reflection adapter、StrategyCandidate 或任何交易副作用。

## 最近完成：V1-008

2026-08-25 使用 `gpt-5.6-terra` / `high` 完成只读 Main、持久 Workflow Orchestrator、`AutonomyCycle/DecisionEpisode` 与 DecisionJournal 基础投影，独立 `gpt-5.6-sol` / `high` 多轮并发与故障验收最终无 P0–P3。用户、时间表、市场/数据事件触发具备规范 hash 与持久幂等；typed plan/task、租约 fencing、预算、超时、取消及实际 artifact fan-in 可跨进程恢复。并发首次精确写入仅产生一套 task，非精确重试拒绝；DecisionJournal 从 episode 绑定的追加式源事件增量重建并保留 DECISION_TIME/POST_HOC。实现 commit 为 `8be2e36`；`make check` 通过（contract `215 passed`、property `9 passed`、mypy `48` source files），真实 PostgreSQL 全量为 `266 passed`，8 项迁移往返通过。没有 LLM 调用或交易副作用。

## 最近完成：V1-009

2026-08-25 初始使用 `gpt-5.6-terra` / `medium` 实现研究版 Pre-trade Critic，因独立复核发现安全关键持久化与权限边界而升级至 `gpt-5.6-terra` / `high` 加固；独立 `gpt-5.6-sol` / `high` 最终复验无 P0–P3。实现 commit 为 `efd832a`。Catalog 1.4、不可变 Critique、固定 policy/revision、Research 三产物实际 fan-in、专用 fenced PostgreSQL completion、持久 hydration、ACL 和 migration downgrade 边界均已完成。V1-010 尚未提供权威诊断，因此八类检查固定为 GAP/UNRESOLVED、DATA_LEAKAGE 为 HIGH，结论只能 DEFER，迭代上限为 1；调用方不能注入诊断或 verdict。`make check` 通过（contract `224 passed`、property `9 passed`、mypy `50` source files），全新 PostgreSQL 全量 `276 passed`，8 项 migration round-trip 与 populated downgrade 原子拒绝通过。没有模型调用、诊断工具、StrategyCandidate、TradePlan 或交易副作用。

## 最近完成：V1-010

2026-08-27 使用 `gpt-5.6-terra` / `high` 实现，独立 `gpt-5.6-sol` / `high` 六轮对抗复验最终无 P0–P3；实现 commit `67faddf`。新增精确版本的 market/historical/feature/contract、memory/experiment、L0/L1、walk-forward、成本/滑点 stress 与 counterfactual 工具，以及独立 Diagnostic Producer 和 Catalog 1.5 Critic worker。冻结 request/config/split/cost/stop/scope 可跨 JSON/进程完整重放；结果与上游 feature/memory/experiment 由 composition-root trusted ports 验证，真实 V1-005 `FeatureObservation` 谱系、PIT/有效期、失败实验、工具 metrics 及八类 diagnostics 皆 fail closed。冻结 `MarketSnapshot → 11 tool results → 8 diagnostics → Critic → AgentTaskEnvelope/StructuredArtifact` 垂直链可重放，缺失/重复/过期/篡改诊断只产生可审计 FAILED，不产生 PASS artifact。`make check` 通过（contract `232 passed`、property `9 passed`、mypy `53` source files）；全新 PostgreSQL 升级到 head 后全量 `284 passed`，8 项 migration round-trip 通过。未实现真实模型调用、V1-011/V2、StrategyCandidate、TradePlan、Order/Fill/Position 或任何交易副作用；完成只触发 `MVP-R-001`，不等于 MVP 已成立。

## 历史 Gate：MVP-R-001

立即按 [`MVP-RESEARCH-VALIDATION.md`](./MVP-RESEARCH-VALIDATION.md) 启动研究可用性试验：补齐最小真实模型调用、受限串行工具循环、少量授权真实 PIT 数据和 Replay/Evaluation Harness；先跑 30 个诊断 Episode 并冻结评分，再跑至少 50 个新封存 holdout Episode，最后完成至少 10 次真实用户 shadow 研究。

只有硬安全、智能有效性和用户价值三类门槛全部通过并由用户/产品治理记录 `GO`，才能称为 MVP-R 并启动 `V1-011`。`ITERATE/REPAIR` 只允许在预注册预算内修正和复验；`STOP/PIVOT` 时不得因已有投入自动继续 V1/V2。

## 固定工作流程

本节的“授权/审批”指开发任务、代码合并、数据发布和治理 Activation 权限，不是产品运行中的逐笔模拟交易批准。

1. 先读本文件、`ROADMAP.md` 和任务引用的 PRD/技术章节。
2. 确认任务已获用户授权，且不会扩大到真实交易或外部启用。
3. 在新项目仓库记录 HEAD、工作区、负责人和开始日期；不得把旧仓库状态当成阻塞条件。
4. 先写 Acceptance 对应的测试或检查，再实现最小任务范围。
5. 使用新项目隔离配置、临时数据库和合成/获授权数据；不得读取旧业务数据库作为默认依赖。
6. 运行任务测试、相关集成测试和当时可用的全量回归。
7. 只有 Evidence 可复核时才更新勾选；同时更新本文件的阶段、最近完成、下一任务、风险和验证结果。
8. donor 复用必须单独通过 `LEGACY-ASSET-REUSE.md` 的资格门禁；复制代码不等于功能完成。
9. 合并、发布数据、策略晋升和运行启用分别审批。

## 进度更新模板

```text
Current version:
Current task:
Status: NOT_STARTED | IN_PROGRESS | BLOCKED | COMPLETED
Owner:
Workspace/branch:
Started at:
Completed at:
Acceptance checked:
Evidence:
New risks/open decisions:
Next task:
```

## 新对话可直接使用的提示

> 请先阅读 `/Users/qiu/work/futures-agent-os/docs/HANDOFF.md`、`ROADMAP.md`、仓库根 `README.md` 及当前任务引用的 PRD/技术章节。这是完全独立的绿地项目；`/Users/qiu/futures_workflow` 仅是 donor，不继承其运行状态，也不把其能力计作新项目进度。`MVP-R-001/002` 已停止，`MVP-R-003` v1 记为测量方案失败，其 Evidence 不得覆盖或改写成通过。`MVP-R-004` 已确认 `STOP/PIVOT`。`MVP-R-005` Research Decision Brief 已通过 correction-v5 独立功能复核并完成，但不是 `GO` 或独立真实用户验证。当前无开发任务获授权；正式 MVP-R eval 与治理 `GO` 前禁止 30/50/shadow、禁止启动 `V1-011`。保持研究与模拟边界，并记录实际执行器/model/effort、测试和 Evidence。
