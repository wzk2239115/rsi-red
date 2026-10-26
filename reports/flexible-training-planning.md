# 开放训练规划基线

日期：2026-10-26。change：flexible-training-execution。

本轮按用户要求仅规划、RED/CI，不改src。审阅入口：openspec/changes/flexible-training-execution/review.md。

- 新CPU契约37：28失败、9通过，0收集错误、0跳过。
- 新功能真实Ray Jobs CPU契约2：2失败、0收集错误、0跳过；实际启动独立0-GPU head，仅运行CPU脚本，无模型下载。
- 原有已实现功能204项通过，包含审核、轻量部署和看板CLI；未把既有研究层32项RED混作回归GREEN。
- OpenSpec strict、ruff、CI YAML和release/simulation依赖检查通过。
- CPU/Ray RED直接使用产品service/CLI/worker边界；只有纯控制契约使用外部scheduler double，不用产品占位代码替代缺失功能。
- 生产代码未改、运行中服务未重启、研究会话未启动、GPU未使用。

新增门禁为flexible-training-contracts矩阵与flexible-training-ray-contracts；预期RED会阻止release/simulation，保留JUnit与失败注解。线上结果以GitHub Actions实际run为准。

Ray前置条件修正：通用Rig默认GPU镜像标签会使CPU测试在提交前失败。已对CPU Ray请求省略镜像声明，并要求拿到实际scheduler_id；重新执行后RED分别来自缺少runtime记录，以及错误依赖未阻止训练（实际job succeeded），不再把submission_error当作新功能验收。loopback客户端显式NO_PROXY，避免代理造成假失败。
