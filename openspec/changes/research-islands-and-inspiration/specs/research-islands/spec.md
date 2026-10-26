## Purpose

将不同研究路线的经验作为长期方法资产保存，在共享基础能力的同时保留可审计的独立探索历史，并通过显式发布而不是默认全量互读来控制交流，避免把角色名称或重复方法计为实际专业差异。

## ADDED Requirements

### Requirement: Independent campaign history
每个岛 SHALL 绑定独立 campaign，复用其成员权限；跨岛交流不得自动开放源 campaign 的原始记录。

#### Scenario: Method is published
- **WHEN** 目标岛读取已发布的方法快照
- **THEN** 能读发布内容，但不能因此读取源 campaign 的私有实验

### Requirement: Immutable method snapshots
方法 SHALL 有内容摘要、父版本、适用前提、实现说明与证据范围，发布后修改必须生成新版本。

#### Scenario: Fork after publication
- **WHEN** 作者改变已发布方法的实现
- **THEN** 新快照关联旧版本，旧内容保持不变

### Requirement: Observable specialization
系统 MUST 将“岛屿存在”和“专长已测量”分开；没有对齐的行为证据时，差异指标为空而不是按角色名计分。

#### Scenario: Only labels differ
- **WHEN** 只配置了不同 focus 或角色名称
- **THEN** measured=false，behavioral_diversity=null

### Requirement: Protected evidence cannot cross islands
发布方法 MUST 拒绝隐藏评测、受保护协议及其衍生内容作为可共享证据，即使提交者是操作者。

#### Scenario: Operator cites sealed protocol
- **WHEN** 发布请求引用隐藏评测协议
- **THEN** 返回 PROTECTED_EVIDENCE，不输出题目或答案
