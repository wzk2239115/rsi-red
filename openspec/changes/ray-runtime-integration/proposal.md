# Proposal

## Why

用户希望在 CI 中建立真实 Ray 环境，让任务生命周期通过真实运行时验证，而不只依赖模拟调度器。

## What Changes

- 新增 Ray Jobs 后端和可选固定版本依赖，先写失败契约测试。
- 在独立 CPU Ray 实例上验证任务、日志、取消、超时与控制服务恢复。
- CI 增加 Ubuntu/Python3.12 的真实 Ray job，发布和模拟交付依赖同一 CI，失败阻止交付。

## Capabilities

### New Capabilities

- `ray-execution`: 将统一研究任务映射到 Ray Jobs，并提供真实运行时验收。

### Modified Capabilities

无。

## Impact

修改 scheduler factory、可选依赖与 CI；新增 adapter、单元测试及独立 integration/ray。不需要 GPU，不接外部集群；不宣称支持了多机容错或真实 CUDA 训练。
