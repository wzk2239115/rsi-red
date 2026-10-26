# Proposal

## Why

用户希望独立agent检查四个研究者产生的模型是否利用评分漏洞获得虚假收益。保持四个平级研究会话，增加第五个平级评测完整性审计会话，区分可疑线索、可信验证与真正能力。

## What Changes

- 规划独立auditor身份，只读取被授权的审计证据并提出检查/疑点，不训练模型、不改评分器、不拥有operator权限。
- operator预先固定审计策略，候选模型的模型digest、开发协议digest、评测记录、数据/代码来源进入不可变审计快照。
- 服务端可信检查执行器验证疑点并记录收据；agent自报、较高分数、未执行的检查不能放行提交。
- 审计策略启用时，campaign提交候选需同一模型/协议的完整检查结果；平时训练不逐步阻塞。
- 看板后续显示待审/检查通过/有可复现问题/覆盖不足，保留证据与审计预算，不承诺消除reward hacking。
- 本轮仅spec、RED契约与CI/CD门禁；不新增运行中会话、不执行评测或修改现有campaign规则。

## Capabilities

### New Capabilities
- evaluation-integrity: 独立审计身份、冻结证据、可信检查与候选提交门禁。

### Modified Capabilities
无。未启用策略的campaign保持兼容；启用后的提交门禁由新能力约束。

## Impact

新增contracts/evaluation_integrity及独立CI门禁，复用release/simulation阻断。实现阶段待后续推进；当前workspace-only部署不是抗恶意篡改的系统隔离。

用户补充：四个训练会话须能接收疑点与判决。新增持久反馈流、事件、接收者独立幂等确认和离线恢复要求；真实会话投递依赖harness适配器，首版仅开发集可见反馈。
