## ADDED Requirements

### Requirement: 有界恢复与持久调度健康
系统 SHALL 为Ray SDK HTTP请求设置超时，只读查询失败后最多重建重试一次，认证错误显式分类；任务提交结果不明不得自动重放。控制面 SHALL 持久化调度健康、停滞告警和恢复事件。

#### Scenario: head短暂失联
- **WHEN** 查询失败并超过停滞阈值
- **THEN** job.show显示stalled和原因，写事件与日志，保留未决任务预算

#### Scenario: 未知提交结果
- **WHEN** submit响应丢失且后续查不到记录
- **THEN** 标记SUBMISSION_UNRESOLVED，要求操作核查，不自动重训

### Requirement: 显式执行环境与诊断
系统 SHALL 支持节点python_executable，保留绝对解释器路径，不隐式替换成裸python；终态保留退出码、runtime_env错误及计费估算范围。

#### Scenario: runtime_env失败但无stdout
- **WHEN** SDK返回RUNTIME_ENV_SETUP_FAILURE且日志为空
- **THEN** job.show及logs可见脱敏失败诊断

### Requirement: 显式认证与声明边界
系统 SHALL 支持auto/token/disabled客户端模式和受保护token文件，通过SDK请求头认证，不将token写入job spec或metadata，不更改运行中head认证。cluster_image SHALL 明确只是声明标签而非镜像执行证明。

#### Scenario: 凭证更新
- **WHEN** 客户端重建
- **THEN** 重读token文件，认证失败显示RAY_AUTH_ERROR而非任务不存在

### Requirement: 测试head互不干扰
真实Ray测试 SHALL 使用独立端口/目录/进程组，清理只影响自有实例，不执行全局ray stop。

#### Scenario: 同机并存与重启
- **WHEN** 测试创建第二个认证head或在原URL重建head
- **THEN** 首个head仍可访问，新head缺失的旧任务不被当作成功或自动重新提交
