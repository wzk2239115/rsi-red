# 人授权的评测方向

人的研究目标决定方向，不由 benchmark 名称或惯例决定。可以对同一 ASR 指标要求提高或降低。四个训练会话及审核会话都不能自行授权或翻转；方向设置使用单独的 operator 配置凭证。

在 harness 中说“攻击 bench 的 ASR 我要提高；检测 bench 的 AUROC 也要提高”，rsi-research 会展示明确的 task/metric/direction 映射，记录这段目标，在已有 operator 配置权限时登记。明确目标无需重复确认；“优化它”“反过来”但无明确参照时需要澄清。授权实现工具不等于授权任何实验方向。CLI 本身不运行自然语言模型。

## 注册 mixed-polarity 协议

以下是假数据接口示例，不是推荐你的真实 bench 方向。仅在人的目标确实是 attack.asr ↓、detect.auroc ↑ 时使用。operator 凭证由操作方保存，不放进四个研究会话。

`authorization.json`：

```json
{
  "source_protocol_digest": null,
  "goal": "本人授权：attack 的 ASR 越低越好；detect 的 AUROC 越高越好",
  "tasks": {
    "attack": {"direction": "minimize", "metric": "asr", "role": "policy"},
    "detect": {"direction": "maximize", "metric": "auroc", "role": "judge"}
  }
}
```

```sh
rsi --token-file OPERATOR_TOKEN direction authorize --spec authorization.json --json
```

把返回的 `data.id` 填入下面的 `direction_authorization_id`。`protocol.json`：

```json
{
  "name": "human-objective-v1",
  "visibility": "development",
  "direction_authorization_id": "DIRECTION_AUTHORIZATION_ID",
  "items": [
    {"id": "fixture-attack", "task": "attack", "prompt": "operator-owned fixture", "answer": "fixture", "direction": "minimize", "metric": "asr", "role": "policy"},
    {"id": "fixture-detect", "task": "detect", "prompt": "operator-owned fixture", "answer": "fixture", "direction": "maximize", "metric": "auroc", "role": "judge"}
  ],
  "sampling": {"temperature": 0, "max_tokens": 8},
  "evaluator_digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  "aggregation": "task_mean",
  "eval_seed": 42
}
```

```sh
rsi --token-file OPERATOR_TOKEN protocol register --spec protocol.json --json
rsi protocol show PROTOCOL_ID --json
```

evaluator_digest、题库、采样和基座由实际实验另行配置，上述占位内容不能冒充真实评测器。新 campaign 的配置通过现有 `campaign create --config` 绑定 PROTOCOL_ID，运行时无需改服务配置或重启。

## 字段与分数

direction 仅接受 minimize/maximize；protocol 显式默认值可由 item 覆盖，同 task 有效 direction/role/metric 必须一致。role 可选 policy/judge，仅为语义标注，不授予审核权限。metric 可选非空字符串，不负责推断方向。任一 item 无有效方向，或授权映射不完全一致，注册失败。

normalization 固定 `bounded-complement-v1`：原始 score 必须是 [0,1] 有限数；maximize 用 raw，minimize 用 1-raw。不裁剪、不把任意 latency/loss/百分数默默当成 [0,1]。其他量纲先由可信 evaluator 定义 [0,1] 的原始评分语义。

`eval show` 返回 raw_score/raw_task_scores 和 normalized_score/normalized_task_scores；既有 score/task_scores 是 normalized 别名。task_metrics 说明每项 direction/metric/role。先在 task 内平均，再对 task 等权平均，不按题数加权。

算例：ASR ↓、AUROC ↑ 的 raw (.6,.6)→(.2,.8)，目标分 (.4,.6)→(.8,.8)，suite .5→.8；ASR 变高则退步。原始均分并非 mixed suite 的优化依据。

```sh
rsi eval list --campaign CAMPAIGN_ID --json
rsi eval compare LEFT_EVAL_ID RIGHT_EVAL_ID --json
rsi eval aggregate --spec repeats.json --json
rsi campaign select CAMPAIGN_ID --json
rsi campaign submit CAMPAIGN_ID --model MODEL_ID --json
```

repeats.json 为 `{"ids":["EVAL_ID_1","EVAL_ID_2"]}`。aggregate 的 mean/mean_score 均为目标均分，另返回 raw_mean_score。compare 返回双方 raw/normalized、方向元数据、目标分 delta/回归及同题配对 bootstrap CI；这是题目抽样不确定性，不证明训练可复现或等价。

select 只读推荐：同 campaign 所绑定开发协议，候选全部成功重复取目标均分，平分按 model_id 字典序；未评测、其他协议和未通过当前审核策略者不参与。没有合格候选时报 NO_ELIGIBLE_CANDIDATE。不自动提交，不妨碍 agent 显式选择其他审核合格候选；submit 仍执行审核门禁。

## 人授权改变方向与旧记录迁移

先从 protocol.show 读取来源 digest。人明确决定翻转 attack 后，再登记新的 authorization.json：source_protocol_digest 为来源 digest，tasks 必须是**完整目标映射**，attack.direction 改为 maximize，其他 task 保持。goal 记录人的新目标。

`derive.json`：

```json
{
  "id": "SOURCE_PROTOCOL_ID",
  "direction_authorization_id": "NEW_AUTHORIZATION_ID",
  "task_overrides": {"attack": {"direction": "maximize"}}
}
```

```sh
rsi --token-file OPERATOR_TOKEN protocol derive --spec derive.json --json
```

只能覆盖已有 task 的 direction/metric/role，不能改题库、grader 或采样。派生结果含 source_protocol_id/source_protocol_digest，新 ID/digest，旧协议及评测不重算。用新协议通过 campaign.create 建立新的研究窗口，预算由人另行明确；不能自动重置或补充预算。

旧的无授权/无方向协议仍可读，protocol.show 标记 legacy_unconfigured。其新 eval/选择/统计不继续隐式 maximize，需给完整方向授权后派生并重新评测；旧协议没有方向时，task_overrides 也要显式覆盖每个 task。旧审核结论不能给新版本放行。跨协议 compare 一律拒绝。

## 权限与看板

研究者只能查看 task 级方向与汇总 raw/目标分；protocol.show 不给题目/答案，eval.samples 仍 operator-only，隐藏集不进入训练会话与看板。审核器始终检查原始 item.score，不因 minimize 的目标分取反而误报评分作弊。

看板按 campaign+协议 digest 分组显示 ↑/↓、role 和两套分，不画跨版本进步曲线，浏览器不接收完整题库或 operator token。方向授权记录含 authorized_by/authorized_at/digest 和人的目标说明；服务验证的是 operator 身份与映射范围，无法从一段字符串证明背后确实是人。共享 Unix 用户下的凭证旁路依旧属于未来物理隔离范围。
