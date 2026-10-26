## Purpose

为外部研究 agent 提供长期运行的实验执行能力，将研究方向选择与 GPU 作业执行分离，使训练、评测依赖、故障恢复和资源账目可以独立于 agent 会话持续运行并被追溯。

## ADDED Requirements

### Requirement: Durable asynchronous jobs
系统 SHALL 在启动外部作业前持久化请求并立即返回作业标识，作业不依赖客户端或 agent 会话存活。

#### Scenario: Control process restarts
- **WHEN** 已运行任务期间控制进程被终止并重启
- **THEN** 同一个任务可被找回，完成结果可查询且不启动第二个作业

### Requirement: Idempotent submission
系统 MUST 对同一 campaign 的相同幂等键和请求返回同一任务；对不同请求报冲突，提交响应丢失不得重复消耗 GPU。

#### Scenario: Scheduler accepted but response lost
- **WHEN** 调度器已接受任务但返回超时
- **THEN** 服务通过提交标识恢复任务，不盲目重发

### Requirement: Atomic budget reservation
系统 SHALL 将排队与运行任务的资源预留计入预算，并在完成后按真实资源时间结算且不重复计费。

#### Scenario: Concurrent requests exhaust budget
- **WHEN** 多个并发请求合计超出剩余预算
- **THEN** 接受范围不能超过预算，其余请求返回 BUDGET_EXCEEDED

### Requirement: Observable terminal causes
系统 SHALL 保留 OOM、训练错误、抢占、节点丢失、超时、取消等原因，依赖失败时不得启动下游任务。

#### Scenario: Failed prerequisite
- **WHEN** 子任务所依赖的任务失败
- **THEN** 子任务以 dependency_failed 终止且不分配 GPU

### Requirement: Explicit scheduler adapters
系统 MUST 显式选择 local CPU、Slurm 或 Kubernetes 后端，不支持的后端不得静默降级；取消操作必须传播到外部资源。

#### Scenario: Unsupported backend
- **WHEN** 后端名称无法识别
- **THEN** 配置立即报错，不启动本地任务
