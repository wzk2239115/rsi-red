# Proposal

## Why

同一个 benchmark 的原始指标在不同研究目标下可能需要相反方向。当前服务直接把原始分当成越高越好，无法表达操作者用自然语言指定的目标，也无法正确比较混合方向的 suite。

## What Changes

- harness 将“提高此 bench 的 ASR”等自然语言目标转换成显式 task/metric/direction 配置，展示映射；含糊目标先澄清，不按指标名、模型角色或外部 bench 默认值猜测。
- 用户最新确认：bench 优化方向必须由人授权。增加独立 operator 授权记录，绑定准确 task/metric/direction 和目标版本；研究 agent 不可授权，也不能拿产品开发授权冒充实验方向授权。
- **BREAKING**：新注册协议必须给每个 task 明确方向；允许显式 protocol 默认方向与 item 覆盖，同 task 的有效配置必须一致。role/metric 仅为标注。
- 冻结方向与可解释的 bounded-complement-v1 变换；保留 raw，以 normalized 计算 task_mean、比较、重复评测和候选排序。
- 增加 operator-only 的 protocol.derive，从已有协议派生方向版本，不需要导出题库；改变目标创建新协议，原历史不重算。本轮沿用 campaign.create 绑定新目标，不原地切换已有 campaign。
- 增加只读 campaign.select，按同协议归一化重复均分推荐候选；提交仍显式调用 campaign.submit，并执行既有审核门禁。
- protocol.show / eval.show / eval.compare / 看板展示无题目泄漏的方向、原始分与归一化分。
- 先交付 OpenSpec、可执行 RED、CI/CD 发布阻断门禁；用户审阅后另行授权产品编码。

## Capabilities

### New Capabilities

- `evaluation-direction`: 显式方向协议、自然语言配置约定、版本派生、可解释归一化、同协议选择及安全展示。

### Modified Capabilities

无已归档主 spec；与在途 trusted-evaluation、evaluation-integrity、research-kanban 需求共同遵守，不能放宽原有权限和审核门禁。

## Impact

后续实现涉及 service.py、evaluation.py、audit.py 的安全投影、CLI、kanban 和 web，以及 .agents/skills/rsi-research、docs/contract.md。已有测试/演示中的合法注册需通过测试 operator 显式授权并补 maximize，不能由产品隐式补值。

不提供各 bench 方向默认表、不接真实安全 evaluator、不改 held-out 策略或 suite 划分、不接 GPU、不把自然语言解析内置成新的服务端 LLM。无方向的旧记录保留只读，参与新排序前需操作者明确派生并重新评测。
