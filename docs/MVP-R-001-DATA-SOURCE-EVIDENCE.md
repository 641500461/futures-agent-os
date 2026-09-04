# MVP-R-001 数据源资格证据

状态：`PARTIALLY QUALIFIED — DATASET NOT FROZEN`  
日期：2026-08-28  
开发模型：`gpt-5.6-terra` / `high`

## 1. 结论

MVP-R 的历史日线主来源采用交易所公开文件，问财只作为当前行情、基本资料与人工 shadow 的辅助查询及交叉核验。两类来源均已通过真实只读探针，但目前只完成 source adapter 与 normalization 资格验证，尚未形成正式数据集 manifest、Episode roster 或 provider/legal license 结论。

首轮研究宇宙调整为：

- `SHFE.AG`：贵金属；
- `SHFE.CU`：有色金属；
- `CZCE.MA`：化工；
- `CZCE.SR`：农产品。

`DCE.M` 的旧公开接口当前返回 412/WAF，替代 `dceapi` 需要独立 DCE 凭据；`CFFEX.IF` 历史文件当前仅能从 HTTP 入口稳定取得，而 MVP-R 数据证据要求 HTTPS。两者本轮均不降级绕过，待取得合格来源后再扩展。

## 2. 交易所文件适配器

实现：

- `OfficialExchangeDailyClient` 只允许 GET；
- host 与 path prefix 固定 allowlist；
- SHFE/CZCE 强制 HTTPS；
- 限制超时和最大响应字节数；
- redirect 必须仍处于原交易所边界；
- 保存 exact raw bytes、请求/最终 URL、采集时间、媒体类型和 SHA-256；
- 保存 HTTP `Last-Modified` 与 `ETag`（存在时）作为 source revision Evidence，但保持实际 `acquired_at` 不变；provider 声明的历史修订时间不能冒充本系统的历史采集时间；
- normalization 保留 raw hash，并把 `available_time` 保守设为实际采集时间，不伪造历史发布时间。
- governed materializer 复算 raw normalization、防止调用方删改记录，并只允许 SHFE 的 AG/CU、CZCE 的 MA/SR；
- 同一次采集生成相互绑定的 RAW 与 NORMALIZED_PIT manifest，normalized content 使用 canonical JSON、绑定 raw dataset ID/hash；
- normalized exact bytes 与授权方使用同一 PIT canonical encoding；授权时必须同时命中 exact manifest/provider contract 和显式 normalizer 白名单，且必须存在 RAW 上游 lineage；
- manifest 的 `as_of` 必须严格等于实际 `acquired_at`，历史文件名不能冒充历史可见性；LicenseTerms 只能由 composition root/governance 显式传入。

2024-01-02 真实探针：

| 来源 | 原始字节 | SHA-256 | 规范化行 | 目标品种行 |
|---|---:|---|---:|---|
| SHFE | 134,054 | `158fc4b72d97fba974c149134133d1a9cc6e021d3b32661eaa5941e67db50964` | 279 | AG 12、CU 12 |
| CZCE | 34,271 | `cce80985453e21f9b07557945ddecf6d8c8397a181f3d6cc86c041920eaf2bc2` | 214 | MA 12、SR 6 |

这些 hash 只证明本次响应的 exact bytes，不表示交易所永不修订同一 URL。正式数据集必须逐文件保存、绑定采集时间与 source revision，并执行质量检查。

## 3. 问财 Skill 与项目适配器

本机已安装并审阅：

- `hithink-futures-query` `1.0.0`；
- `hithink-basicinfo-query` `1.0.0`。

两个 Skill 的代码许可证为 MIT；这不等于返回数据具有相同许可证。项目不导入 SkillHub/OpenClaw 安装目录，而是实现独立的固定 endpoint、固定 skill/version、POST-only、响应上限、redirect 拒绝和 trace/hash Evidence 适配器。credential 只由 composition root 注入，不进入 Evidence 或仓库。

真实探针结果：

| Skill | 状态 | `code_count` | Evidence |
|---|---|---:|---|
| futures query | OK | 12 | 64-char trace ID + response hash |
| basic info query | OK | 12 | 64-char trace ID + response hash |

问财自然语言历史查询不能稳定返回指定日期的连续历史 bars，所以它不承担 30/50 Episode 的主 PIT 数据。它只适合：当前行情/资料查询、用户 shadow、缺失字段辅助和交叉核验；任何结果在进入研究工具前仍必须规范化、内容寻址并标注来源。

## 4. 使用授权边界

用户在 2026-08-28 明确本项目为个人、非商业、内部研究与模拟使用，并授权在该边界内使用交易所公开行情。项目侧据此允许采集和本地保留，但默认禁止再分发、商业使用和真实交易。

这是一项项目治理授权，不是对交易所或问财条款的法律解释，也不能替代 provider 的服务条款。正式 manifest 仍需记录当时可见的来源页面/条款快照、保留政策和再分发政策；无法确认时必须标为限制项，而不是猜测许可证。

## 5. 尚未完成

- 批量采集并内容寻址保存目标日期范围；
- 形成 raw/normalized PIT manifest 与质量报告；
- 冻结确切 continuous-series/roll policy、成本假设和 30/50 Episode roster；
- 把真实数据绑定到 V1-010 trusted executor；
- 运行 diagnostic、holdout 与用户 shadow。

仓库还新增 `composite-stratified-hmac-sha256.v1` roster authority：按 Instrument × 七类 Regime 组合进行 keyed HMAC 选择，冻结 30 diagnostic 或 50 holdout，签名同时绑定候选池 commitment、suite、phase 和最终 Episode。选择密钥不进入 roster 或模型输入；真正 holdout 候选池仍须在阈值冻结后由隔离 evaluator 环境生成，当前没有提前消费 holdout。

因此本证据不会把 `MVP-R-001` 标记完成，也不会解锁 `V1-011`。
