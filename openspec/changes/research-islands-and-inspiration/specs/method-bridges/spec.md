## Purpose

将跨路线交流转化为具有表示转换、适用条件和验证方案的可证伪迁移假设，使实验收益能追溯到实际训练与测量，同时保留无收益、负迁移及不确定结果，防止把建议或自报分数当作发现。

## ADDED Requirements

### Requirement: Explicit transfer mapping
桥提案 MUST 包含源方法、目标岛、源到目标表示映射及不变量、最小实验、等预算对照和反证条件。

#### Scenario: Mapping is absent
- **WHEN** 提案没有 mapping
- **THEN** 返回 INVALID_REQUEST，不自动生成训练任务

### Requirement: Hypothesis is not validation
桥提案 SHALL 初始为 hypothesis、validation_scope=null；提案和检索操作不得自动提交训练或评测。

#### Scenario: Proposal accepted
- **WHEN** 有效迁移假设被保存
- **THEN** 只返回提案记录，任务队列不变

### Requirement: Evidence-bound review
审查 MUST 从服务内真实 job/eval/模型来源、对齐协议与题目、预算及重复结果计算，不接受 claimed_gain 替代证据；缺少独立等预算对照时不得晋升为已支持。

#### Scenario: User reports large gain
- **WHEN** 只提供 claimed_gain 和期望结论
- **THEN** 返回 MISSING_TRIAL_EVIDENCE

#### Scenario: No trials available
- **WHEN** 审查缺少迁移与独立对照记录
- **THEN** 返回 inconclusive 与缺失证据清单

### Requirement: Negative transfer persists
失败观察 SHALL 保留作者、来源、适用范围与时间；没有正式实验的观察不得标为已验证事实。

#### Scenario: Session resumes
- **WHEN** 服务重启后查询有负迁移观察的桥
- **THEN** 原记录仍在，证据状态不会自动变为 supported_dev
