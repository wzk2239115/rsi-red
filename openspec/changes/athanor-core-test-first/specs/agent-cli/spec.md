## Purpose

向能够调用 shell 的 agent 暴露稳定的研究操作接口，使工具调用可以通过结构化结果、错误码和有限超时可靠组合，而无需 agent 解析混杂日志或在训练结束前保持终端会话。

## ADDED Requirements

### Requirement: Structured command contract
CLI SHALL 为 JSON 模式输出单一版本化结果，诊断写入 stderr，参数错误退出2并给出稳定非重试错误码。

#### Scenario: Unknown command
- **WHEN** 调用未知命令且指定 --json
- **THEN** stdout 是一个有效 envelope，错误码为 INVALID_COMMAND

### Requirement: Backend-independent discovery
CLI MUST 在没有集群连接时提供帮助和版本信息，并对后端连接失败使用有界超时及可重试错误。

#### Scenario: Backend is unreachable
- **WHEN** 请求连接不可达的控制服务
- **THEN** 在指定超时内返回 SERVICE_UNAVAILABLE 与 retryable=true
