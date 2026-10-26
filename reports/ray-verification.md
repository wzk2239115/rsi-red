# Ray 运行时验收

2026-10-26；Ray 2.59.0，macOS/Python3.12，本地真实 Ray Jobs（2CPU/0GPU）。

- 11项先写的适配器契约由 RED 转 GREEN；普通测试总计124项通过。
- 5项真实 Ray 集成测试通过，0错误、0跳过；涵盖实际 remote tasks/日志、取消、失败、超时和控制服务重开找回。
- Ray 关闭时未关闭的 reaper 管道通过显式回收本实例句柄修复，保留严格资源警告策略。
- CI 新增独立 Ubuntu/Python3.12 Ray 任务；发布/模拟交付依赖整套 CI，包括这项门禁。
- 原67项测试文件摘要不变。未接GPU、未测多机、未推送、未在线触发GitHub Actions。

详见 [Ray 使用说明](../docs/ray.md)。
