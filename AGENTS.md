# rsi-red 协作入口

项目进入已授权的实现与验证阶段。先阅读 [AGETN.md](AGETN.md)、[行为契约](docs/contract.md) 和 `openspec/changes/athanor-core-test-first/`。

- 用中文交流和编写规划；区分论文事实、工程建议和待确认决策。
- 已初始化 OpenSpec，Codex 工作流位于 `.agents/skills/`。用户已统一授权实现，并明确在暂不能提供集群信息时使用模拟方式验收。
- Agent 决定研究方向；CLI 和后台服务负责执行、测量、持久化。不要把固定 SFT→RL 流程、自动挑选算法或逐实验人工审批写死在工具内。
- 用户已有 Slurm 或 Kubernetes 集群，具体先接哪个仍待确认。不得在讨论阶段提交真实训练、占用集群资源或修改集群配置。
- 不把模拟运行、仅进程分离或未接入的适配器描述成真实集群验证、权限隔离或完整复现。
- 规划变更同步到 `AGETN.md`；形成正式 OpenSpec change 后，明确标记哪些讨论已转为需求，避免维护两套冲突的规范。
- 实现遵守 RED→GREEN→REFACTOR；不得删除断言、添加 skip/xfail 或吞掉失败来绿灯。真实契约错误可修正但需记录原因和需求映射。
- `reports/red-baseline.json` 保存原始基线；CPU fixture、模拟 scheduler、真实 GPU 与权限隔离结果分开报告。CI/CD 配置写入不等于线上运行成功。
- 用户已确定四个平级 harness 会话对应四个研究 agent；本项目研究拓扑不得改为主 agent/子 agent。节点遥测、GPU申请与实测利用率、agent上报recipe与服务任务状态分别呈现。
