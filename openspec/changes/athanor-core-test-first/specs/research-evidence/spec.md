## Purpose

保留 agent 后训练研究中的数据、模型、代码和观察证据，使结果能够追溯到完整来源，团队可以共享可靠记录，并在会话与服务重启后恢复已有的研究上下文而不是重新猜测。

## ADDED Requirements

### Requirement: Immutable data and artifacts
系统 SHALL 保存内容可校验的数据与模型快照，原始路径后续改变不得修改已注册产物，损坏或不完整模型不得发布。

#### Scenario: Source weights change after registration
- **WHEN** 已发布模型的原目录被修改
- **THEN** 拉取已发布模型得到原内容，并可逐文件校验摘要

### Requirement: Multi-parent provenance
系统 MUST 保存模型所有父节点以及实验的代码、数据、镜像、随机性配置与执行来源。

#### Scenario: Two-model merge
- **WHEN** 模型合并两个具有共同祖先的模型
- **THEN** 血缘包含两条父边及完整祖先，不遗漏任一来源

### Requirement: Durable team research record
系统 SHALL 提供带作者、证据引用和稳定游标的团队笔记与事件记录，并执行成员访问控制。

#### Scenario: Member resumes after restart
- **WHEN** 团队成员在服务重启后使用已保存的事件游标
- **THEN** 获得相同后续记录，既无遗漏也不重复返回游标之前的事件

### Requirement: No secret leakage
系统 MUST 防止敏感凭证进入可查询的作业配置与事件正文，普通非敏感超参仍需可追溯。

#### Scenario: Submitted environment includes token
- **WHEN** 请求包含敏感 token 值与普通学习率参数
- **THEN** token 值不会出现在查询结果或研究事件中，学习率仍可查询
