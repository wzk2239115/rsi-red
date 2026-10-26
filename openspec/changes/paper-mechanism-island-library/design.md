# Design

## Context

参见 proposal.md。src/service.py 目前以 SQLite transaction 包装请求，job/eval 在后台 reconcile；Store 已有内容校验 blob，可复用，但没有论文/知识库实体或 curator 权限白名单。CLI 目前是两级命令；看板显示 campaign 和评测。原研究岛 change 的 island=独立 campaign，32 项 RED，不能偷偷改成论文知识岛。

用户已明确：**按独立机制分岛**；本轮先 spec、RED、CI/CD，另行批准后编码。当前工作树基线 20548bb，392 项已实现 CPU/应用契约、18 项真实 Ray CPU 通过。GPU 和真实会议信息抓取均非本轮验收。

## Goals / Non-Goals

**Goals:** 服务支撑独立整理会话有界批量摄入公开已录用论文、冻结正文、提交可追溯机制解读、显式归并，向四个训练会话提供只读灵感；默认无桥，文献实验例外独立审查。

**Non-Goals:** 不自动创建/调度整理会话，不内置 LLM 提取调用、不自动发训练/评测、不建立推测桥、不宣称语义正确或已复现，不把全文导入训练数据。首个网络来源只做 OpenReview v2 公开记录；API v1、其他出版站点、OCR 扫描版、跨进程物理隔离、向量数据库和自动语义聚类留后续 change。

## Decisions

### 1. 两类岛分开，不覆盖旧接口

新增 `paper.*` 与 `knowledge.*`，实体 `paper_policy/paper/paper_extraction/knowledge_island/paper_relation_evidence/paper_relation_review/paper_bridge/paper_batch`。不实现或替换旧 island/bridge/archipelago 操作；旧研究机制四组消融仍独立 RED。看板未来资料视图明确 kind=paper_mechanism，工作区仍 kind=campaign；未批准的关系不画边。未来从知识岛选方法创建 recipe 必须经过既有研究授权，不能通过“入库”绕过人授权 direction。

不采用一篇一岛：一篇可能包含独立的多个干预，按篇分组会把不可兼容机制粘在一起；也不按 embedding 自动聚类，文本相似不能证明机制等价。

### 2. 来源政策与官方事实

`paper.policy_register` 仅 operator：

```json
{"name":"configured-main-tracks", "venues":[{"provider":"openreview_v2","venue_id":"Fixture.cc/2026/Conference","year":2026,"track":"main"}], "require_full_text":true, "batch_size_limit":1000, "max_parallel":4, "max_pdf_bytes":52428800, "source_timeout_seconds":15, "retry_limit":3}
```

这是合成配置示例，不是具体顶会名单或真实录用声明。实际 venue/year/track 由运行时 operator 配置。政策不可变且 digest 绑定，curator 不能改。

首个 `OpenReviewSource` 使用官方 v2 note/venue 元数据和 PDF attachment；不只搜索标题或从 arXiv 猜录用。公开 accepted note 的 content.venueid 要对应政策中的正式 venue，核对 group/domain 与公开权限，不用 submission invitation 把所有投稿当录用。保存原始响应、provider/parser 版本、record/forum ID、mdate/pdate、下载时刻及 digest。未知状态不默认接受；workshop 必须有单独允许项。来源不可访问时 pending/failed，不伪造 verified。

来源适配器的外部接口固定为 get_record(record_id)、get_pdf(record)、discover(venue_id,cursor,limit)。它只提供外部事实与字节，不负责权限、预算、建岛等产品逻辑；单元契约可替换外部 I/O。另有真实 HTTP fixture 检查 v2 解析/分页/429，明确不是实际顶会验收。

实现参考官方文档：[API v2 notes/accepted/PDF](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)、[API 版本识别](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-check-the-api-version-of-a-venue)。API v1 不适用同一解析路径，明确 unsupported。

### 3. 异步摄入、版本和批次

`paper.ingest {policy_id,provider,record_id,idempotency_key}` 立即返回 queued paper ID；不在请求事务内联网/解析。后台读取来源、下载限额内 PDF、校验并提取页文本。`paper.show {id}` 返回 state、acceptance、revision、文档摘要及资格状态；curator/operator 可通过 `paper.document {id}` 读取受控原文/页文本，普通研究者读公开来源链接与机制摘要。错误只给稳定类别，不回显私密路径/凭证。

paper 对应**被摄入的一个正文版本**，canonical_key 为 provider+forum/record。相同幂等键回同 ID，改请求报 IDEMPOTENCY_CONFLICT；新摄入遇同来源同 digest，返回 state=duplicate、duplicate_of 原 ID；同 canonical_key 新正文生成新 ID/revision。不同 ID 同标题不归并；同版本标识却不同内容进入 quarantine，并保留候选快照供 operator 检查。原 URL 改动不改旧引用。PDF/text 在 Store blob 中，读取检查 hash；文本解析计划使用隔离的固定版本 PDF 解析依赖，拒绝损坏/超限文件，不运行附件代码。

`paper.batch_submit` 支持 records manifest 和 catalog 两种输入：

```json
{"policy_id":"POLICY", "idempotency_key":"batch-1", "records":[{"provider":"openreview_v2","record_id":"NOTE_ID"}]}
```

catalog 输入改为 `catalog:{provider,venue_id,cursor,limit}`，每批至多政策上限，保存来源页快照和 next_cursor；不把整个会议一次塞入上下文。`paper.batch_show {id}` 给逐项状态、计数、下一游标；`paper.batch_retry {id}` 仅恢复可重试项。仅 owner/operator 查看批次详情。每轮 reconcile 有界处理至多 max_parallel 项后让出执行，持续发布进度；每项事务独立，成功项不重做，限流/超时有限退避，不可重试的拒稿/非法 PDF 不自动重试。崩溃前未提交的只读下载可重复，**不声称跨崩溃 exactly-once 网络请求**；已落盘成功项不重复。

批次 CPU 合成基准 1000 个独立记录、至多四个并行摄入 worker 与两个整理身份，确认有界分页/恢复/去重和无训练副作用。不给“可处理全部顶会论文”或并发吞吐的未测保证。

### 4. 提取由整理 agent 做，服务校验来源而非代替理解

curator 读正文后调用 `paper.extract`：

```json
{"paper_id":"PAPER_REV_ID", "mechanisms":[{"key":"rollout-mixing", "name":"混合采样", "signature":{"target":"rollout_sampler","intervention":"sampling_mixture","assumptions":["editable_sampler"],"invariant":"unchanged_reward"}, "source_finding":"论文报告的事实", "ai_interpretation":"AI 解读", "transfer_hypothesis":"待验证迁移", "minimal_trial":"只改采样混合", "falsifier":"同预算无改善", "limitations":["仅该设置"], "requirements":["editable_sampler"], "variants":{"greedy_fraction":0.25}, "citations":[{"page":1,"quote":"EXACT_TEXT_IN_FROZEN_PDF","kind":"body"}]}]}
```

引用须在固定页文本中可定位，允许将换行/连续空白规范化，不能改词或补写原文；figure/table 引用还记录 label/page/caption 或 bbox，不凭空猜图表内容。只有摘要/无引用拒绝为 FULL_TEXT_REQUIRED/INVALID_CITATION。源原文与解释分字段，AI 不理解时可留 unknowns；不可自填 validated_local。正文可追溯不等于模型解释语义已被自动证明，默认 interpretation_status=curator_interpretation。

### 5. 岛屿粒度、归并与修订

`knowledge.create {extraction_id,mechanism_key}` 把一个机制变成知识岛，paper_ids/citations 来自已校验提取，evidence_level=paper_reported、local_validation=not_tested。不得通过手写字符串引用任意 protocol/eval/held-out 资料。相关资料是公开来源，研究权限不会因此扩大。

机制 signature 的 target/intervention/assumptions/invariant 作为保守候选标识，name/tags/venue/标题不作等价判据；参数变体单独保存。相同签名也不自动合并。`knowledge.merge {ids,rationale}` 仅 operator，要求签名一致和每个源有有效正文证据；形成新岛 ID/digest、parent_ids、来源集合、逐论文变体与全部限制。不同签名返回 MECHANISM_MISMATCH，后续语义别名映射另行设计，不静默用 LLM 判断覆盖。

`knowledge.revise {id,...}` 只能由原 curator 或 operator 创建新版本，parent_ids 指向旧岛，旧字段/证据不变；增加反例不能删除既有证据。错误拆分可从旧岛派生多个新岛，不在本轮自动重写历史或桥的端点。

`paper.recheck {id}` 异步追加来源状态；资格是派生视图，与不可变内容版本分开。撤回后仅靠该来源的岛不进入默认 pack；历史 show 保留失效警示。其他合格论文可继续支持同机制，但必须显示被排除来源。

### 6. 默认无桥，实验例外必须独立审查

`paper.relationship_evidence` 仅登记提案，不建边：绑定 source/target island ID、paper_id、relation=composition|transfer、基线/干预、数据/预算/评测控制、raw 结果/论文指标方向、页码/图表引用、uncertainty 是否报告、scope/limits。组合 A/B/A+B 或能识别组成贡献的消融；迁移 target vs target+source。共现、引文、同主题、摘要“有效”、无控制的更高分均不足。

`paper.review_relationship {id,decision,rationale}` 仅 operator，且 actor.id != proposer。服务检查所有必要字段、源引用和支持方向；review 决定 supported|insufficient|contradicted，保留理由。数值正差只能支持声明范围内报告，不自动证明因果充分或统计显著；review 是受权审阅，不是通用科学事实判定器。

`knowledge.bridge_register {evidence_id}` 仅允许已有服务端 supported 收据且仍合格的证据，幂等返回 paper_bridge。客户端 supported/reviewed/local_validation 不能放行。桥标 paper_reported、not_tested，并保留未报告不确定性、负结果/失效状态；`knowledge.bridges {}` 默认只返回有效证据边。不生成“潜在桥”图线、不扩展到网络安全场景，不创建旧研究 bridge.propose。源失效或证据 contradicted 时挂起边并保留历史。

### 7. 查询、边界与 CLI/看板

curator 是独立服务身份，不是主 agent 的子进程；白名单允许 paper/knowledge 整理操作，但 policy/merge/review 仅 operator。即使 curator 被误填 campaign.members，也不能 job/eval/方向授权或读取原始协议。researcher 只读合格 public paper 元数据与 knowledge show/list/pack/bridges；auditor 原权限不扩大。

`knowledge.pack {signals,capabilities,limit,context_budget_chars}` 返回有界 cards/context、context_chars、excluded 和桥的证据范围。缺能力明确排除，limits/引用/未本地验证标签不得裁掉来凑预算；最小卡片装不下返回空卡与明确原因。相似匹配只用于召回，不能作归并/建桥证明，不调用模型或更改正式目标方向。

两级 CLI 使用现有风格 `rsi paper ingest --spec FILE`、`rsi paper batch_submit --spec FILE`、`rsi knowledge create --spec FILE`、`rsi knowledge pack --spec FILE`，通用 `rsi request` 同样支持。看板新增独立资料类型与批次状态，不将论文数画成 GPU/模型能力或虚构 RSI 分数。未完成能力明确 unavailable，不显示演示关系为真实边。

## Risks / Trade-offs

- [官方站点字段/录用状态变化] → provider/解析器版本与响应快照；未知状态 fail closed；在线验收与 CI fixture 分别报告。
- [PDF 漏提取/扫描页] → 保留 PDF 与页引用，不能定位则 needs_text；OCR 后续支持，不用摘要补全文。
- [AI 解读和语义归并错误] → 明确解释状态、原文证据、保守签名与显式受权归并，不宣称自动语义证明。
- [大规模限流/局部失败] → 小批分页、有限并发/退避、单项提交、幂等和断点，不“无限重试直到成功”。
- [知识库注入/假中稿/受保护泄漏] → 非执行文本、独立来源读取、curator 操作白名单、仅公开论文引用。
- [顶会录用被当真理/桥过度推广] → 每项结论限定论文设置，未复现标签随包输出，默认不建桥。

## Migration Plan

本轮无产品/数据库迁移。后续获批后以新增实体上线，不转换旧 campaign/island 或静态卡，不自动填满资料库。回退停用整理入口/worker，保留内容与审查历史。CI/CD 不排除旧 RED，新门禁阻断 release；首个真实 venue 的在线 smoke 由操作方配置后单独记录，不与合成 HTTP 测试混称。
