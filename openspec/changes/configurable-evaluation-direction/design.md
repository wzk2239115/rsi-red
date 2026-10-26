# Design

## Context

见 proposal.md。现有 summarize 和 paired_comparison 都直接使用 item.score；audit.evaluation_summary 用白名单投影，protocol.show 对研究者不返回 items。campaign.submit 只记录指定模型，并无最优选择器。看板也尚无真实评测数据面。

## Goals / Non-Goals

Goals：人描述目标，harness 整理显式方向并执行已授权操作；服务验证权限与精确授权范围，冻结方向，统一评分与安全展示。全部控制面可在 CPU 测试，不依赖 H100。

Non-Goals：不在 CLI 部署自然语言模型/脆弱关键词分类器；不根据 bench 名字推断方向。不实现 campaign 原地换协议、隐藏反馈、无界指标变换或 GPU evaluator。

## Decisions

### 1. 人授权与 agent 提案分离

新增 operator-only `direction.authorize`，payload 为 `{source_protocol_digest: null|string, tasks: {task: {direction, metric?, role?}}, goal: string}`。服务保存不可变记录、操作者、时间与 digest。协议注册/派生接受 `direction_authorization_id`，核对展开后的完整 task 映射及来源 digest；不可仅检查 ID 存在或信任 human_authorized 布尔值。未知 task/metric、额外覆盖、旧来源均拒绝 DIRECTION_AUTHORIZATION_MISMATCH；缺授权报 DIRECTION_AUTHORIZATION_REQUIRED。重复使用同一授权仅允许同一映射/来源，不授权其他目标。

正常研究会话只有 researcher 凭证。operator 是人的配置通道；skill 只有在人的直接表述已明确指定 bench、指标与方向时才能代表人登记；“去实现功能”“自动找更高分”不是改方向授权。只说“优化”时必须澄清。自然语言能力来自现有 harness，服务不声称能验证一段文字真由人写出；同用户可任意读文件的物理隔离不在本版保证内。凭证持有人越权冒充人是部署信任边界，不能用目标说明字符串来解决。

### 2. 展开元数据与一致性

item.direction 优先于显式 protocol.direction；两者均无则拒绝。role/metric 采用相同继承规则且仅为标注。按现有 task 分组，整组有效元数据必须一致；一个 bench 要测两个指标，应现有建模为两个 task，本次不变 suite 划分。协议输入不提供 schema 默认方向。

protocol.show 研究者视图新增 `spec.task_metrics`（task→direction/metric?/role?）、`direction_authorization_id` 与 normalization 版本，不返回 items。operator 仍可完整查看。role=judge 不等于访问权限，不改变 actor role。

### 3. 不可变派生

`protocol.derive {id, direction_authorization_id, task_overrides: {task: {direction,metric?,role?}}}` 在服务端复制题目并替换 task 元数据；task_overrides 中只允许已存在 task，不允许额外参数修改 sampler/grader/items。返回新协议 ID/digest、来源字段；旧协议和历史不修改。新目标使用现有 campaign.create 建立新研究窗口，旧 campaign 不偷换口径。该选择减少 in-flight 请求、审核策略和累计预算被重绑定重置的风险；需要同 campaign 换目标时另写 spec。新 campaign 的预算由人显式配置，不自动恢复额度。

### 4. 原始证据与目标分

冻结 normalization=bounded-complement-v1：maximize x→x，minimize x→1-x；沿用原始[0,1]约束，不支持将任意 loss、延迟或百分数直接套 1-x。不同范围先由可信 evaluator 定义[0,1]评分语义，不能默默裁剪。

保存原始 item.score，另存服务计算的 normalized_score；忽略/拒绝 evaluator 提供的伪造归一化值。task_mean 先逐 task 平均再等权 suite 平均，禁止按题数加权。`score/task_scores` 为 normalized 别名；显式提供 `raw_score/raw_task_scores/normalized_score/normalized_task_scores/task_metrics/normalization`，raw_score 仅是原始等权均分，不作选择。

compare 的 CI/回归列表取归一化逐题配对差；返回 `left/right` 各含 model_id、eval_id、raw_score、raw_task_scores、normalized_score、normalized_task_scores，加 task_metrics。跨 digest 拒绝。aggregate 增加 raw_mean_score 与 mean_score，既有 mean 保留为 mean_score 的 normalized 别名，保留重复次数与不确定性限制。

### 5. 只读最优建议，显式提交

`campaign.select {id}` 读取当前 campaign 开发协议的成功评测，按 model_id 对全部成功重复求归一化均分，排除其他协议、失败/未完成评测和无合格证据者。若配置审核，复用当前策略对该 model+protocol 的门禁；拒绝项用已有安全原因码解释，不暴露细题。返回 model_id、protocol_digest、raw_mean_score、normalized_mean_score、eval_ids 与候选排名；平分按 model_id 字典序，空候选 NO_ELIGIBLE_CANDIDATE。

select 不改 submission；之后 campaign.submit 仍可显式提交任何通过既有审核的候选，不能把自动最优强制成研究策略。没有审核通过的最高分不得绕过门禁。这补上原代码不存在的选择能力，同时保留人工选择权。

### 6. 展示、兼容与证明范围

新增仅汇总 eval.list（按 campaign 权限过滤，held-out 对研究者不返回），供看板拉取；snapshot 包含 evaluations 与 task_metrics，web 标 ↑/↓、role、raw/目标分、协议版本。不得把 operator 完整协议直接传给浏览器。使用前端 textContent 显示外部 metric/task 字符串。看板按 digest 分组比较。

旧协议保留只读显示 `direction_status=legacy_unconfigured`，旧历史不可在新目标中复用。旧数据上的新 eval/选择拒绝 DIRECTION_UNCONFIGURED，operator 需给出完整授权后 derive。测试/演示的新注册显式通过测试 operator 授权 maximize，不能产品回填。审核 exact_match 继续比 raw，不拿目标分当原始 grader；旧 pass 不迁移到新协议。

自然语言需人工 harness 验收：正向、反向、含糊、参考未知、明确翻转、仅授权开发六组；不以查找 SKILL 文本关键字的测试冒充模型理解测试。

## Risks / Trade-offs

- [人类意图不能由字符串自动证明] → 限定 operator 配置通道，记录人的原话/映射/身份/时间，研究凭证禁止自授；部署前约束 operator 凭证归属。
- [改变 direction 看起来像成绩暴涨] → 新 digest/new campaign，禁止跨协议配对，保留 raw 与目标说明。
- [兼容破坏] → 实现时升级所有合法 fixture/示例，旧记录只读，不默认为 maximize；原有安全断言不得删减。
- [当前无最优选择与评测看板] → 明确增加只读 API 及真实数据连接，不能只画箭头宣称完成。

## Migration Plan

本轮仅规划、RED、CI；产品 src 与运行服务不变。用户审阅后实施授权/schema→归一化→比较/选择→看板/技能/文档；每步保留旧测试并转 GREEN。上线前备份存储；旧记录不重写，回滚程序前停止新方向任务，避免旧版本忽略方向字段而错误评分。不宣称 CPU 验收证明 GPU 性能或物理隔离。
