# 论文机制岛：本轮审阅入口

**当前只完成 spec、RED、CI/CD，产品尚未编码。** 用户已确认按独立机制分岛。变更名 `paper-mechanism-island-library`。

## 需要核对的行为

1. 独立 curator 整理已录用论文，训练者只读灵感；不形成主/子 agent 拓扑，不自动创建训练会话。
2. 顶会名单、年份与主会/分会范围由政策配置，不硬编码。首个来源 OpenReview v2，官方身份/状态与全文均核验；arXiv、workshop、标题相同不能代替主会录用。
3. 一篇可拆多个岛。多篇只有机制、对象与关键前提一致才显式归并；同关键词不合并，参数变体与反例保留。
4. 默认不建桥。只有论文固定正文中的直接对照/消融支持具体关系，经非作者 operator 审查后才可登记；仅 paper_reported，未本地复现。operator 是受权服务角色，本条不要求用户逐篇批准普通整理；实验优化方向仍必须由人授权。
5. 1000 项有界批次、分页、断点恢复、失败分类与有限重试；成功项不重做。AI 提取由外部整理会话完成，服务没有隐藏的大模型调用或 GPU 花费。
6. 论文知识岛与原 campaign 工作区岛是不同对象。旧研究层32 RED保留，不因本次变更移除桥试验/RSI消融原契约。

## 材料

- [proposal](proposal.md)：范围与非目标。
- [design](design.md)：API/schema、身份、异步批次、机制签名和证据边界。
- [tasks](tasks.md)：先规划门禁，后获批实现，各组含测试与文档。
- [录用摄入](specs/accepted-paper-ingestion/spec.md)、[机制库](specs/mechanism-island-library/spec.md)、[关系例外](specs/paper-supported-relations/spec.md)。
- `contracts/paper_library/`：54 项应用/CLI RED。
- `contracts/paper_library_io/`：8 项1000条/双身份/分页/失败与真实HTTP适配器 RED。
- `reports/paper-library-red.json`：不可覆盖的原始失败基线；`reports/paper-library-planning.md`：实际执行与CI状态。

## 命令草案（当前不可用）

```sh
# operator：定义允许的真实会议范围
rsi request paper.policy_register --payload '{...}'
# 独立 curator：摄入 -> 读正文 -> 自己理解 -> 提交引用与结构化机制
rsi paper batch_submit --spec accepted-records.json
rsi paper batch_show BATCH_ID
rsi paper ingest --spec one-paper.json
rsi paper document PAPER_ID
rsi paper extract --spec extracted-mechanisms.json
rsi knowledge create --spec one-mechanism.json
# 研究者：带能力与上下文约束读取，不能从“入库”直接发训练
rsi knowledge pack --spec current-research-needs.json
```

schema 见 design。这里的 `{...}` 是说明用占位，尚不是有效请求。不把本轮合成论文当真实中稿，也不预先建立任何真实桥。
