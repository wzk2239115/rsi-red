# 论文机制资料库

用户已批准实现 `paper-mechanism-island-library`。论文按**独立可检验机制**分岛：一篇可拆多个岛；多篇只有作用对象、干预、关键前提和不变量一致，才允许 operator 显式归并。论文被录用只满足来源筛选，不代表结论正确，也不代表本地复现。

这是公开文献基础设施，不创建整理会话、campaign、训练或评测，不把全文自动导入训练数据。原 `island/bridge/archipelago` 研究工作区草案保持独立，32 项 RED 不属于这次实现。新对象 `kind=paper_mechanism`。

## 身份与配置

在受保护的服务配置 `principals` 中由 operator 添加独立身份，例如：

```json
{"CURATOR_TOKEN_FROM_PRIVATE_FILE":{"id":"curator-01","role":"curator"}}
```

示例字段不是可用 token；按既有部署方式生成随机凭证并存入私有 token 文件，整理会话设置 `RSI_TOKEN_FILE`。身份添加需要重启服务；来源政策、摄入、提取和检索均可通过 CLI/API 运行时操作。

curator 只能调用 paper/knowledge 白名单，即使误加入 campaign.members 也不能调用 job、eval、protocol、direction 或私有研究接口。researcher 只读公开资料与机制，不能发布或读取全文文档入口。operator 注册政策、归并、审查；审查关系必须与提案作者是不同身份。auditor 权限不扩大。同 Unix 用户的 API 权限不是物理隔离。

## 来源政策

operator 将以下合成示例保存为 policy.json，再执行 `rsi paper policy_register --spec policy.json --json`。实际允许的会议、年份和 track 由人/操作方配置，不内置“顶会名单”。

```json
{
  "name":"accepted-main-policy-v1",
  "venues":[{"provider":"openreview_v2","venue_id":"Fixture.cc/2026/Conference","year":2026,"track":"main"}],
  "require_full_text":true,
  "batch_size_limit":1000,
  "max_parallel":4,
  "max_pdf_bytes":52428800,
  "source_timeout_seconds":15,
  "retry_limit":3
}
```

政策不可变，`paper policy_show POLICY_ID` 返回原 spec/digest；改政策注册新 ID。范围：batch_size_limit 1–1000，max_parallel 1–4，max_pdf_bytes 1024–52428800，source_timeout_seconds 1–60，retry_limit 0–5。全文是发布机制的必需条件，即使筛选政策不要求全文，也不能用摘要发布机制。

首个适配器只支持公开 OpenReview API v2，固定官方 `https://api2.openreview.net`；依据公开 note 的 venueid 和 venue group 的 v2 domain 核验，Conference 主会路径解析 year/main。其他路径、workshop、API v1、未知录用状态不推测为 accepted。它不是适用于全部出版站点的爬虫。实际会议字段兼容性需操作方在配置真实 venue 后单独在线验收。

保存原 note、group 响应、稳定 record/forum ID、mdate/pdate 版本、provider 版本、观察时间及内容摘要。HTTP 重定向和任意 PDF URL 不跟随；PDF 从同一 API 的 `/pdf?id=...` 读取。429 返回 SOURCE_RATE_LIMITED，不在适配器中忙重试。请求和下载限制字节数及网络超时。

仅供集成测试时，服务配置可显式设置 `paper_source:{api_base:"http://127.0.0.1:PORT",allow_loopback_fixture:true}`。没有该标志拒绝回环，其他自定义远端拒绝；curator 请求无法改来源地址。该模式只证明测试链路，不能作为真实会议核验。

参考官方接口文档：[获取 notes 与 accepted papers](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)、[识别 API 版本](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-check-the-api-version-of-a-venue)。

## 异步摄入与恢复

```sh
rsi paper ingest --spec ingest.json --json
rsi paper show PAPER_ID --json
rsi paper document PAPER_ID --json
```

```json
{"policy_id":"POLICY_ID","provider":"openreview_v2","record_id":"NOTE_ID","idempotency_key":"stable-key"}
```

请求立即登记 queued ID，不在请求的 SQLite 事务内联网或解析。后台每轮处理至多 max_parallel 项，下载和 PDF 解析不占数据库锁。正文在独立 Python 子进程用固定 `pypdf==6.12.0` 解析：最多 500 页、400 万字符、政策限时；Linux 附加 1GiB 地址空间上限。Mac 使用输入/页数/字符限额和进程超时。它是有界解析进程，不宣称强沙箱或通用恶意 PDF 防护。

PDF 和页文本以 SHA256 blob 冻结，读取校验，不依赖原 URL 继续存在。`paper.document` 返回每页文本、页号、尺寸与解析器版本，curator/operator 可读。未提取文字进入 needs_text；扫描版 OCR 未实现。

状态为 queued → ready / ineligible / needs_text / failed / quarantine / duplicate。缺正文报 FULL_TEXT_REQUIRED，不合格来源报 PAPER_NOT_ELIGIBLE。损坏 PDF、字节摘要不符、过大分别为 INVALID_PDF、CHECKSUM_MISMATCH、DOCUMENT_TOO_LARGE；错误不回显路径或凭证。

幂等键按 owner/操作绑定原请求；改变内容报 IDEMPOTENCY_CONFLICT。相同 canonical ID 与 PDF digest 去重，返回 duplicate_of；同标题不同官方 ID 保留；同 ID 新官方版本和新正文建立新记录；同官方版本标记却不同内容 quarantine。旧正文与引用不会被新版本改写。

服务重启自动恢复已持久化 queued 项。尝试次数在 I/O 前落盘，最多 retry_limit+1；崩溃前已预留的尝试也计入上限，达到上限以 RETRY_EXHAUSTED 结束。只读请求可能因宕机被重放，不声称跨崩溃 exactly-once。已成功提交的项不重下载。

批次支持 records 与 catalog 二选一：

```json
{"policy_id":"POLICY_ID","idempotency_key":"batch-page-1","records":[{"provider":"openreview_v2","record_id":"NOTE_ID"}]}
```

或：

```json
{"policy_id":"POLICY_ID","idempotency_key":"catalog-page-1","catalog":{"provider":"openreview_v2","venue_id":"Fixture.cc/2026/Conference","cursor":null,"limit":100}}
```

```sh
rsi paper batch_submit --spec batch.json --json
rsi paper batch_show BATCH_ID --json
rsi paper batch_retry BATCH_ID --json
rsi paper batch_list --json
```

catalog 只读取一页并保存页快照摘要/next_cursor；下一页用新批次键，不自动无限抓取。批次逐项事务、有界并发、可重试网络错误指数退避（最高30秒），不合格/坏 PDF 不自动重试。batch_retry 只恢复未耗尽总次数的可重试项，不重置计数、不重做成功项。catalog 失败也有限重试并保存错误；新一轮重新发现需新批次。批次仅 owner/operator 可读。

## 机制提取与发布

整理 agent 读 `paper document` 后提交 extract.json：

```json
{"paper_id":"PAPER_ID","mechanisms":[{
  "key":"mixing","name":"混合采样",
  "signature":{"target":"rollout_sampler","intervention":"sampling_mixture","assumptions":["editable_sampler"],"invariant":"unchanged_reward"},
  "source_finding":"论文在其设置下报告的结果",
  "ai_interpretation":"AI 对作用机制的解释，不是证明",
  "transfer_hypothesis":"需要另做实验的迁移假设",
  "minimal_trial":"固定数据与预算，仅改变采样混合",
  "falsifier":"匹配对照下没有改善",
  "requirements":["editable_sampler"],"variants":{"greedy_fraction":0.25},
  "limitations":["仅限论文设置；未本地复现"],
  "citations":[{"page":1,"kind":"body","quote":"EXACT FROZEN PAGE TEXT"}]
}]}
```

```sh
rsi paper extract --spec extract.json --json
rsi knowledge create --spec create.json --json
```

create.json 为 `{"extraction_id":"EXTRACTION_ID","mechanism_key":"mixing"}`。引用允许规范化空白，不能换词。figure/table 需 label 出现在引用原文，若提供 caption/bbox 也验证固定页文字与页面范围；这校验定位，不替代人工看图或证明图像语义。protected protocol/eval 引用即使 operator 也报 PROTECTED_EVIDENCE。假引用报 INVALID_CITATION。

始终输出 `evidence_level=paper_reported`、`local_validation=not_tested`、`interpretation_status=curator_interpretation`。自填本地复现报 UNVERIFIED_CLAIM。服务不调用 LLM，解释由独立整理会话提交；能追溯原文不代表 AI 理解被自动证明。论文中命令和提示词只保存为数据。

## 归并、修订、检索

```sh
rsi knowledge show ISLAND_ID --json
rsi request knowledge.list --payload '{"query":"rollout","limit":20}' --json
rsi knowledge merge --spec merge.json --json
rsi knowledge revise --spec revise.json --json
rsi knowledge pack --spec pack.json --json
```

merge.json：`{"ids":["ISLAND_A","ISLAND_B"],"rationale":"逐来源机制与关键前提一致"}`。operator 显式归并，保守签名一致（assumptions 按集合比对），不同干预/前提报 MECHANISM_MISMATCH。新岛保留 parent_ids、逐论文 variants/citations、全部限制和来源发现；原记录不修改。相似度或同名不会自动归并。

revise.json：`{"id":"ISLAND_ID","limitations":["新负结果范围"],"ai_interpretation":"更窄解释"}`。原作者/operator 创建新 ID/digest，限制只追加不抹除。

pack.json：`{"signals":["rollout"],"capabilities":["editable_sampler"],"limit":5,"context_budget_chars":8000}`。按关键词召回与能力前提筛选，不把相似度当证据。返回完整 cards、实际 context/context_chars 和 excluded；missing_capability、source_ineligible、context_budget 等明确解释。整卡放不下就排除，不截掉局限/未验证标识。上下文限额针对实际 context 字符串，响应元数据/排除列表另外返回。

list/bridges 支持 `limit` 1–1000 与 `cursor`；更多过滤参数通过 `rsi request`。show 可以保留失效历史；默认 list/pack 只用当前有效来源。`paper recheck PAPER_ID` 在后台追加核验，重复在途请求不重置预算；撤回/不可核验/官方版本变化会停止推荐旧来源。原 PDF/revision/digest 不变。多来源归并只要仍有有效来源可以保留，但附失效成员警示。

## 唯一建桥例外

所有摄入、提取、建岛、归并和 pack 默认不建边。`paper relationship_evidence` 只登记提案：paper_id、两端 island_id、relation=composition|transfer、scope、limitations、experiment。两端均须有该论文的正文依据。

experiment 需 baselines、treatment（有限 raw score 与不同 id）、metric、reported_metric_direction、controls（data/compute/model/evaluation 为 same 或 matched）、uncertainty、可定位 citations。composition 至少两基线与可识别 ablation；transfer 至少目标基线及 target+source 干预，并明确 source_method/target_setting。无不确定性须限制中标 `uncertainty_not_reported`。

`paper review_relationship` 由不同于提案作者的 operator 给出 `{"id":"EVIDENCE_ID","decision":"supported","rationale":"具体范围与依据"}`；supported 还检查结果相对所有基线方向正向。方向是论文报告指标的方向，**不修改也不授权本地 benchmark 优化方向**。审核是受权判断，不是自动统计显著性或普适因果证明。

只有服务保存的 supported 收据才允许 `knowledge bridge_register --spec bridge.json`（`{"evidence_id":"EVIDENCE_ID"}`）。结果 paper_reported/not_tested 且带 scope、原文、局限与 review_id。`knowledge bridges` 默认只返回 active；operator 可 request `{"include_suspended":true}` 看历史。后续 contradicted/insufficient 审查、来源失效会挂起关系；历史 review_id 和正文保留，不能客户端自填 reviewed=true 放行。

## 看板与验证边界

`rsi kanban` 的“机制资料库”通过独立只读 `/api/library` 展示机制、出处/版本、局限和批次计数。普通研究者看不到他人的批次；curator 只能资料入口，研究项目读取仍被拒绝。正文/凭证不发给浏览器，文本使用 textContent。默认无桥，只显示独立审查后的论文实验关系，不把论文数量或整理速度说成模型能力/RSI 指数。

CI 覆盖合成 PDF、1000 条批次、重启、双 curator、真实回环 HTTP 与安装 wheel；这些不代表真实会议字段全部兼容，更不代表 H100、训练、方法收益或强隔离已验收。实际 venue 的小规模在线验收由操作方配置后另行记录。
