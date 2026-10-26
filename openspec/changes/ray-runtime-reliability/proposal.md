# Proposal

## Why

用户提供H100容器接入报告：head重启后的静默accepted、解释器PATH差异、runtime_env空日志、认证状态混乱和测试head冲突。设备当前不可访问，报告作为故障线索而非本次复测证据。

## What Changes

- Ray SDK有界HTTP调用、延迟连接、只读请求故障后重建、文件凭证重载；写提交不自动重放。
- 控制面持久化degraded/stalled/recovered事件和健康状态；无法确认停止时不释放预算或伪造终态。
- 显式节点Python路径、保留绝对解释器、环境PATH、runtime_env诊断和退出信息透传。
- 显式auth_mode与受保护auth_token_file；不修改运行中head认证，不执行get-auth-token。
- 测试使用私有CLI head、随机GCS与agent端口、专用目录和进程组；验证两个head共存、token认证和同URL重启。
- 明确cluster_image只作操作者声明标签匹配，不证明镜像执行或容器隔离。

## Capabilities

### New Capabilities
- ray-reliability: 连接恢复、调度健康、显式环境/认证、隔离运行时验收。

### Modified Capabilities
无。原submission_id幂等与旧CLI保持兼容。

## Impact

修改Ray适配器、任务reconcile与Ray fixture。补充普通故障契约与真实CPU Ray测试；原研究层32项RED继续保留。H100的GCS下载失败、GPU/NCCL与容器网络复测待设备可用。
