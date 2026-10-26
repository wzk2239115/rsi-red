# 配置约定和当前可用接口

以下 research.yaml 是技能维护的研究简报，不是已经存在的 `rsi run --config` 配置。不要编造 run/target/launch 等 CLI 命令。

```yaml
schema_version: 1
goal: 提高模型在指定开发评测上的表现
mode: configure
base_model:
  repository: Qwen/Qwen3-4B-Base
  revision: null
  artifact_id: null
training_data: []
evaluation:
  development_protocol_id: null
  held_out_protocol_id: null # 只保留 operator 提供的引用，不包含题目或答案
  scoring_code_digest: null
  repeat_seed_schedule: null
resources:
  total_gpus: 8
  gpu_type: H100
  gpu_memory_gib: null
  scheduler: null
budget:
  gpu_hours: null
  agent_budget: null
  deadline: null
peers:
  - {target: session-1, researcher_id: null, workspace: null, campaign_id: null}
  - {target: session-2, researcher_id: null, workspace: null, campaign_id: null}
  - {target: session-3, researcher_id: null, workspace: null, campaign_id: null}
  - {target: session-4, researcher_id: null, workspace: null, campaign_id: null}
```

target 是实际 harness 会话的引用，不是已实现的 rsi 实体。共享团队可使用同一 campaign；如果需要独立岛屿历史，使用独立 campaign，当前跨 campaign 方法发布/共享仍待实现。不同 researcher_id 需要 operator 预先配置独立凭证，不能四个会话都使用本地 operator token 冒充独立身份。工作区路径分开不代表系统权限隔离。

## Recipe

```sh
rsi recipe create --spec recipe.json --json
rsi recipe list --campaign CAMPAIGN_ID --json
rsi recipe show RECIPE_ID --json
rsi recipe update --spec observation.json --json
rsi resource show --json
```

recipe.json：campaign_id、title、hypothesis、method、datasets（数据ID数组）、parents（模型ID数组）、parameters（可选对象）。服务从凭证确定 owner，客户端不能指定其他作者。输入和方法不可原地修改；改变配方时创建新记录。

observation.json：id、state（planned/trying/completed/abandoned）、observation。保留追加历史，只有作者可更新。job spec 可带 recipe_id，必须属于提交者、同 campaign，并与 recipe 的数据/父模型一致。

resource.show 仅 operator 可用，避免把全节点信息发给所有研究者。看板对 researcher 显示“无权查看”，其他研究数据仍可使用。服务配置加入 `telemetry: {backend: nvidia-smi}` 后读取控制服务所在节点的 GPU，依赖节点有 nvidia-smi；未配置、工具缺失或采样失败显示 unavailable。尚无多节点汇总和 job→GPU UUID 映射。

## 必须如实呈现的当前限制

真实大模型训练 starter、推理 evaluator、自动会话投递/恢复/唤醒、系统级隔离、跨岛方法发布仍待接入；campaign 截止时间/团队提交规则、重复评测实际 seed 的修复也尚未完成。已有 repeat_index 不等于已经使用不同实际采样 seed。

配额目前约束 GPU 时间预留与消耗；不能声称已经强制执行 agent token 成本、磁盘配额或 research.yaml 中的 deadline。继续执行前，应使用户要求的硬限制有实际执行机制。
