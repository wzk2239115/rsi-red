# Mechanism Island Library

## Purpose

按可独立检验的作用机制组织已核验录用论文的知识资产，使四个平级研究会话能查到方法原理、适用条件、实验依据与局限。知识岛保存论文材料，不冒充运行研究 campaign 或已测得的 agent 专长。

## ADDED Requirements

### Requirement: Atomic mechanism granularity
知识岛 SHALL 对应一个可独立检验机制，具有作用对象、干预方式、关键前提、不变量和最小检验说明。一篇论文可贡献多个岛；同一主题、同 venue 或关键词接近不得自动归同岛。

#### Scenario: One paper has two interventions
- **WHEN** 论文分别提出数据筛选与 rollout 混合两个可独立干预机制
- **THEN** 能建立两个共享论文来源但机制不同的岛，二者之间默认没有边

### Requirement: Grounded extraction with scope labels
机制提取 SHALL 绑定准确 paper revision 及可定位正文/图表位置，区分 source_finding、AI 解读、迁移假设与未理解项。无正文依据或引用不存在时拒绝发布；论文报告的结论不得自标 validated_local。

#### Scenario: Fabricated page or result
- **WHEN** 引用页码/原文片段不属于该正文版本，或只有摘要
- **THEN** 返回证据错误，不进入发布与推荐

### Requirement: Explicit cross paper consolidation
跨论文归并 SHALL 经显式受权审查，核对作用对象、干预与关键前提一致，保存逐来源依据与参数变体。只给相似度或主题标签不得通过；不兼容签名须分岛。

#### Scenario: Same mechanism across two papers
- **WHEN** 两个机制签名一致、各自正文证据有效且 operator 给出归并理由
- **THEN** 生成包含两篇来源的新岛版本，旧岛及引用仍保留

### Requirement: Immutable revisions and contrary evidence
岛屿修订/归并 SHALL 创建新 ID/digest 并保留父版本、作者与引用。正负结果、假设限制和相互矛盾的发现不得因归并消失，不能把多数论文支持当因果证明。

#### Scenario: New paper reports a boundary failure
- **WHEN** 同机制新来源记录负结果
- **THEN** 新版本和 pack 保留该范围限制，不输出全局有效或虚构一致性分数

### Requirement: Bounded useful inspiration packs
pack SHALL 以真实能力前提、问题与预算约束筛选机制，给出推荐/排除理由、来源位置、最小实验与反证条件；实际渲染上下文长度须满足限额。未本地验证标识必须随卡片输出。

#### Scenario: Teacher requirement is not available
- **WHEN** 机制需要 teacher，而调用者 capabilities 不含该能力
- **THEN** 排除并说明缺失前提，不自动放宽政策或申请资源

### Requirement: Distinct objects and safe read views
论文知识岛 SHALL 与 campaign 工作区岛使用不同 API/实体/看板类型。研究者可读合格公开资料，不能借知识库读取私有 campaign、held-out 证据或 curator 凭证；本轮操作不得创建研究任务。

#### Scenario: Operator cites protected evaluation as paper evidence
- **WHEN** 提取或发布引用 held-out/protocol/eval 私有材料
- **THEN** 返回 PROTECTED_EVIDENCE，即使提交者是 operator 也不发布

### Requirement: Observable library status
CLI 与看板 SHALL 展示来源核验状态、venue/year/track、版本、机制、适用前提、局限和 paper_reported/not_tested 标识。论文数量、整理吞吐不得显示为模型提升、RSI 或已测得专长。

#### Scenario: Only literature was ingested
- **WHEN** 1000 篇论文成为资料但没有本地实验
- **THEN** 看板只报告资料进度，local_validation=not_tested，不生成模型成绩或 RSI 指数
