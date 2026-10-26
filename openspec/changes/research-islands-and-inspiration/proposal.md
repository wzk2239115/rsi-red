# Proposal

## Why

当前工具可以可靠执行实验，却不能帮助 agent 系统性保留不同研究路线、找到可检验的跨路线迁移假设。用户提出“方法岛屿与桥梁”，需要先把其可证伪机制与灵感输入定义清楚，避免用多人聊天、角色标签或更多算力冒充研究进步。

## What Changes

- 本轮先交付 spec、RED 契约、CI 门禁与带来源的灵感素材；不实现研究策略、不自动发训练、不访问额外模型 API。
- 将独立 campaign 组织为岛屿，显式发布不可变方法快照，保留私有研究历史与负结果。
- 将桥定义为包含表示映射、前提、反证与等预算对照的迁移假设，收益必须绑定真实实验记录。
- 给 agent 返回有界灵感包，区分论文发现、本项目假设与本地验证；不替 agent 决定研究方向。
- 预注册四组等预算消融和未来新任务族验证，区分迁移、累积学习与 RSI 证据。

## Capabilities

### New Capabilities

- `research-islands`: 独立历史、显式方法发布、不可变版本与可测互补性。
- `method-bridges`: 可证伪迁移假设、试验绑定、证据审查及负迁移记录。
- `inspiration-library`: 来源可追溯的材料库、适配约束与有界上下文包。
- `research-ablation`: 等预算四组对照、新任务族切分和科学主张范围。

### Modified Capabilities

无。已有 campaign/job/eval/artifact 作为依赖，不改变其已验证行为。

## Impact

新增 research/inspiration/、contracts/research_islands/、设计说明与 CI research-islands-contracts job。
现有 124 项普通测试和 Ray 5 项集成测试是回归基线；新增研究层测试在实现前诚实失败，因此主 CI 与发布会保持阻塞。当前新增的素材校验测试应正常通过。
