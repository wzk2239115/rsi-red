# Proposal

## Why

需要把 Athanor 的异步研究环境做成外部 agent 可用的 CLI，并在业务实现前冻结可执行行为测试，避免用演示脚本冒充可靠的训练研究系统。

## What Changes

- 先交付测试、行为契约、CI/CD 和可追溯验收计划；本轮不实现业务，不提交集群任务。
- 后续一次实现授权覆盖 job/eval/data/artifact、campaign、团队记录、预算与故障恢复。
- 以 Python 3.12+ 为控制面语言；训练运行时通过独立容器/entrypoint 接入，不要求与控制面同版本。
- CPU 契约测试与真实 GPU/权限隔离验收分开；红色基线禁止 skip、xfail、吞退出码来伪装通过。
- GitHub Actions 执行自动测试与包检查；版本标签通过完整检查后构建 GitHub Release。集群持续部署待确定后端及环境配置。

## Capabilities

### New Capabilities

- `research-execution`: 异步任务、调度器适配、预算、幂等与恢复。
- `research-evidence`: 数据快照、模型多父血缘、日志、事件及研究记录。
- `trusted-evaluation`: 固定协议、逐题证据、去污染及角色边界。
- `agent-cli`: 可机读 CLI 与稳定错误语义。
- `delivery`: 测试门禁、包构建、发布和实集群验收分层。

### Modified Capabilities

无。

## Impact

新增 tests/、docs/、Python 测试配置、.github/workflows/ 与本 change。暂不创建 src/ 实现，不推送仓库或发布版本。参考原论文 §3、§4.1、§5、附录 A；目标是系统机制对齐，不承诺复现模型分数或训练成本。
