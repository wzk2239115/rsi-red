## Purpose

让研究工具在已有 Ray Jobs 运行时上执行任务，并通过 CI 的真实本地 CPU Ray 环境验证从提交到结果的生命周期，提高控制服务与执行环境之间的接口可信度，而不将其等同于 GPU 或多机训练验收。

## ADDED Requirements

### Requirement: Stable Ray submission identity
系统 MUST 使用控制面稳定的任务标识作为 Ray submission_id，上传冻结工作目录，并在重连时通过同一标识找回原任务。

#### Scenario: Control service reconnects
- **WHEN** Ray 任务已提交而控制服务关闭后重新打开
- **THEN** 找回同一 scheduler_id，任务只执行一次

### Requirement: Ray lifecycle and diagnostics
系统 SHALL 映射 Ray 的排队、运行、成功、失败、停止状态，返回日志，并将超时与主动取消区分。

#### Scenario: Entrypoint exceeds walltime
- **WHEN** 任务执行超过指定时限
- **THEN** 终止入口进程并报告 timed_out，而不是成功

### Requirement: Real CPU runtime CI gate
CI MUST 启动独立真实 Ray Jobs 服务，验证远程 task、取消、失败、超时与控制服务恢复，失败阻止版本交付。

#### Scenario: Integration fails
- **WHEN** 真实 Ray 测试有失败
- **THEN** 保存测试和 Ray 日志，不创建发布交付

### Requirement: Honest runtime and accounting boundaries
系统 SHALL 明确 Ray driver 资源估算与子 actor 的区别，并拒绝忽略未配置的镜像；本地 Ray 测试不能替代 GPU、CUDA 或多机验证。

#### Scenario: Unconfigured image
- **WHEN** 请求镜像与配置的集群镜像不一致
- **THEN** 拒绝提交，不静默运行在另一环境中
