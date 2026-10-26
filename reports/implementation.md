# 实现与验证报告

2026-10-26。用户授权先采用模拟方式，未使用真实集群或 GPU。

- **113项测试通过，0失败、0错误、0跳过**（macOS，Python 3.12.13）。
- 最初67项测试的文件摘要与红色基线一致，没有改动原断言。新增测试覆盖故障窗口、统计、CPU算法、会话/通知和安装配置。
- lint、OpenSpec strict validate 通过；三个 workflow 的 YAML 结构及发布依赖已核对。
- 独立 CPU worker 通过 CLI 退出及控制服务 SIGKILL 恢复测试；实际 HTTP 健康检查和鉴权请求通过。
- 演示的5个CPU训练任务全部完成，6次评测、6个模型节点均可追溯；小型二分类分数从0.5到1.0，只是模拟数据与模型上的结果。
- wheel/sdist 已构建；干净临时虚拟环境安装 wheel 后，help/version 与完整 CPU campaign 成功。

运行说明：[docs/usage.md](../docs/usage.md)。示例报告：仓库 `.rsi/demo-20261026/report.json`。

已实现：job/eval/data/artifact、campaign、预算、幂等、journal、模型DAG、笔记、会话chunk、通知游标、CLI/HTTP、CPU worker，以及 Slurm/Kubernetes adapter。

尚未验证：真实GPU/LLM训练与加载、实际集群故障与资源账目、操作系统级评测隔离、真实Codex/Claude harness通知。GitHub尚未推送，Actions/Release/集群部署均未执行。

CPU starters 使用小型线性策略实现SFT、GRPO、两步环境RL、on-policy蒸馏和权重合并；它们是可修改可执行的模拟程序，不是大模型训练框架的生产实现。
