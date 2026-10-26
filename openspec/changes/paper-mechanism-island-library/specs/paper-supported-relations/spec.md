# Paper Supported Relations

## Purpose

默认保持论文知识岛之间无桥，只允许将论文自身直接实验支持的特定方法关系登记成有范围的文献证据边。防止共同引用、语言相似或 AI 的迁移猜测被画成已存在的关系，也不把源论文结果等同于本地复现。

## ADDED Requirements

### Requirement: No implicit edges
摄入、提取、建岛、归并、检索与 pack SHALL 默认不创建桥。共现、相似度、同论文/同会议、引用关系或 agent 自信表述均不得产生可见实验支持边。

#### Scenario: Paper mentions both methods
- **WHEN** 正文同时出现 A 与 B，但没有直接实验比较
- **THEN** 可保留“待检查关系”文本，不产生 bridge 实体或看板连线

### Requirement: Direct experimental evidence
例外关系 SHALL 绑定已合格论文的固定正文版本、确切两端机制、关系种类、实验条件/基线/干预、raw 结果与位置。组合需要 A/B/A+B 或能识别组成贡献的消融；迁移需要目标基线和加入源方法的可比对照。

#### Scenario: Unmatched compute
- **WHEN** A+B 成绩较高，但对照预算/数据/评测条件未对齐且不能隔离方法贡献
- **THEN** 返回 INSUFFICIENT_BRIDGE_EVIDENCE，不登记为支持边

### Requirement: Independent authorized review
只有受权 operator 的服务端审查收据 SHALL 能放行关系，且审查者不得等于材料作者。curator 自填 supported=true、reviewed=true 或客户端伪造收据不得放行；审查须记录具体理由与缺失证据。

#### Scenario: Curator self approves
- **WHEN** 整理者自报 supported 或直接登记未经审查的关系
- **THEN** 拒绝且无边；审查记录不能由客户端声明替代

### Requirement: Scoped paper reported edges
通过审查的边 SHALL 明确标 paper_reported、local_validation=not_tested，保留指标方向、结果范围、不确定性是否报告、限制与原文引用。不能自动推广到其他模型/任务/安全领域或改变人授权 benchmark 方向。

#### Scenario: Paper reports improvement without uncertainty
- **WHEN** 对齐实验支持特定设置下的收益但未报告不确定性
- **THEN** 只登记有界 reported 结果，显示 uncertainty_not_reported，不宣称普遍有效或统计显著

### Requirement: Revalidation and contrary evidence
新版本、撤回或反证 SHALL 追加状态并重新计算边的可用性，不将旧证据静默重指新论文版本。默认图与 pack 不展示失效支持边，历史证据仍可查看。

#### Scenario: Supporting paper is withdrawn
- **WHEN** 关键支持论文失去来源资格
- **THEN** 边标为 suspended 并从默认图排除，旧结果和审查记录保留
