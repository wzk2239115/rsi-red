# Proposal

## Why

四位研究 agent 需要可追溯的论文机制库，独立的整理 agent 需要批量收集、核验录用、提取机制与恢复中断的接口。当前只有静态灵感卡和未实现的 campaign 岛草案，不能支撑大量论文整理，也不能区分同主题与同机制。

## What Changes

- 本轮只交付 OpenSpec、可执行 RED 契约、CI/CD 门禁和审阅入口，不修改产品源码、不批量爬论文、不运行模型或训练；审阅后另行授权实现。
- 用户已确认按**独立可检验机制**分岛：一篇可拆多个，多篇仅在机制、作用对象与关键前提一致时经显式归并进入同岛，主题相似不构成归并理由。
- 新增公开录用来源政策、OpenReview API v2 首个适配器、版本化全文快照/引用、异步批量摄入、去重/隔离/有限重试/断点恢复。其他来源返回 unsupported，不把 arXiv、workshop 或引用数量自动当顶会主会录用。
- 独立 curator 身份整理论文机制，研究者检索有界灵感包；材料是数据，不执行论文代码，不创建 campaign/job/eval，不授予实验方向权限。
- 默认没有桥。唯一例外是**论文自身直接实验支持的具体关系**，须保存对照/消融、条件、结果位置并经独立受权审查；标为 paper_reported，不能冒充本地复现或普遍有效。
- 论文知识岛与旧草案的研究工作区岛分开命名、存储和展示，保留旧 32 RED，不为了本轮绿灯移除它们。

## Capabilities

### New Capabilities

- `accepted-paper-ingestion`: 来源政策、独立录用核验、版本全文、批次队列与可恢复摄入。
- `mechanism-island-library`: 机制粒度岛屿、显式归并/修订、证据边界与受限灵感包。
- `paper-supported-relations`: 默认无桥、论文实验支持的关系审查、范围/反证及失效处理。

### Modified Capabilities

无。主 specs 库目前为空；与在途 research-islands-and-inspiration 的关系在设计中明确，不重定义其 island/bridge 操作。

## Impact

未来涉及 paper/knowledge CLI/API、curator 权限、来源适配器、私有文档快照和看板资料层。本轮新增 contracts/paper_library、独立离线与 HTTP/大批量 CI 门禁；release/simulation 继续复用完整 verify，新增 RED 会诚实阻断发布。现有 392 项本地与 18 项 Ray CPU 为回归基线，不宣称已完成真实会议信息抓取或论文理解。
