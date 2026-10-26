## Purpose

为后训练研究 agent 提供可追溯、可检验且符合当前模型与预算约束的灵感材料，将论文所报告的发现与当前任务的迁移假设分开，并限制上下文大小与材料执行权限，使材料帮助研究而非替代研究判断。

## ADDED Requirements

### Requirement: Traceable and scoped materials
每张材料 MUST 有来源版本/位置、source_finding、迁移假设、前提、小实验、对照和反证条件；导入不能自称已本地验证。

#### Scenario: Local validation is self-declared
- **WHEN** 材料写入 validated_local 却没有服务测量证据
- **THEN** 返回 UNVERIFIED_CLAIM

### Requirement: Immutable material revisions
同 id/version 同内容导入 SHALL 幂等，不同内容必须更换版本，不得覆盖旧材料。

#### Scenario: Content changes without revision
- **WHEN** 同版本改变 hypothesis
- **THEN** 返回 VERSION_CONFLICT

### Requirement: Constrained inspiration pack
灵感包 SHALL 按失败症状、能力前提和岛屿策略筛选，解释推荐与排除原因，并按实际输出上下文长度限额。

#### Scenario: Architecture changes disallowed
- **WHEN** 候选方法要求架构变化而岛策略禁止
- **THEN** 排除该卡并说明 architecture_change_disallowed

### Requirement: Material is data
库内容 MUST 只作为引用数据；即使文本包含提交训练或覆盖规则的指令，也不得执行。

#### Scenario: Hostile text in hypothesis
- **WHEN** 导入的 hypothesis 包含命令式指令
- **THEN** 仅存为内容，不产生作业或改变权限
