# Proposal

## Why

用户决定四个独立平级 harness 会话对应四个 agent，不采用主子 agent。看板需要观察每个身份在尝试的 recipe 和 GPU 使用，避免把示意岛屿当成真实研究监控。

## What Changes

- 增加 recipe.create/update/show/list，作者由认证身份确定，输入不可变、观察追加、关联 job。
- 看板按 researcher 身份显示 recipe、关联任务和未结束任务 GPU 申请量。
- operator 的 resource.show 可选通过 nvidia-smi 读取控制服务所在节点的真实 GPU 指标；缺失/过期/权限状态明确展示。
- 提供可复用 rsi-research skill，配置基座、数据、评测与预算，为平级会话准备简报。skill 不冒充会话调度器。

## Capabilities

### New Capabilities
- peer-monitoring: 平级 recipe、任务关联、节点 GPU 遥测及看板。

### Modified Capabilities
无；原 job.submit 新增可选 recipe_id，不改变旧请求。

## Impact

扩展 service/CLI/server/kanban；新增9项行为测试；沿用普通tests CI门禁。原研究层32项RED不删除、不弱化。真实GPU、harness会话管理和多节点汇总仍需现场接入。
