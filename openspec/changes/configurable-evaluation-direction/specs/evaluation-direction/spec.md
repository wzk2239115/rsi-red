# Evaluation Direction

## Purpose

让操作者以自然语言表达各 benchmark 的优化目标，在人明确授权后形成不可变的显式方向协议。保留原始测量，统一目标分的计算、比较和展示，使相反方向的研究都可以追溯其真实目标，且不向训练者泄露题库。

## ADDED Requirements

### Requirement: Human authorized objective
系统 SHALL 仅接受 operator 创建方向授权记录，绑定 task、metric、direction 的完整映射、来源协议 digest（初次注册为 null）和人的目标说明。注册及派生 SHALL 验证授权映射完全匹配，拒绝缺失或越界授权。researcher/auditor SHALL 无权授权；开发授权不构成实验方向授权。

#### Scenario: Exact human goal
- **WHEN** 人明确指定攻击 bench 的 ASR 要提高，并由 operator 登记对应授权
- **THEN** 仅该 task/metric 的 maximize 可用该授权注册，不能偷偷换成 minimize 或增加另一 task

#### Scenario: Agent cannot self authorize
- **WHEN** researcher 或 auditor 请求 direction.authorize，或在 payload 自称 human_authorized
- **THEN** 请求被拒绝且不产生授权、协议或调度副作用

### Requirement: Natural language configuration contract
harness skill SHALL 把人明确的自然语言目标映射为 task/metric/direction，展示将被授权的映射并记录目标来源。明确的“提高/降低”可直接表达授权；含糊的“优化”“相反”在无明确参照时 SHALL 先澄清。不得从指标名、role 或外部默认值猜方向，不得自动翻转已授权目标。

#### Scenario: Opposite benchmark convention
- **WHEN** 人要求一个通常追求降低的 ASR 指标提高
- **THEN** 映射为 maximize，不以 bench 惯例覆盖人的目标

#### Scenario: Ambiguous goal
- **WHEN** 人仅说“优化这个 bench”或无法确定指标的“反过来”
- **THEN** harness 展示待澄清 task/metric/方向，不提交授权或新协议

### Requirement: Explicit consistent schema
新协议 SHALL 支持 protocol 级 direction/role/metric 显式默认值及 item 覆盖。每个 item 的有效 direction 必须为 minimize 或 maximize；同 task 的 direction/role/metric SHALL 一致。role 仅允许 policy/judge，metric 为非空字符串，均为可选标注且不推断方向。

#### Scenario: Mixed polarity
- **WHEN** ASR task 显式 minimize、AUROC task 显式 maximize 且匹配人授权
- **THEN** 注册成功，无 protocol 默认值时每个 item 必须自行声明方向

#### Scenario: Missing or inconsistent direction
- **WHEN** 有 item 无有效方向、direction 非法或同 task 有矛盾配置
- **THEN** 注册报 INVALID_REQUEST，不能静默使用 maximize

### Requirement: Immutable runtime derivation
operator SHALL 通过 protocol.derive 在服务端按 task 覆盖已授权元数据，保留原题目、grader 和采样，产生新 ID/digest 并记录 source_protocol_id/digest 与授权 ID。原协议与既有评测不得改写。改变目标沿用 campaign.create 绑定新协议，不在本次加入原地 campaign 切换。

#### Scenario: Reverse an existing direction
- **WHEN** 人授权对现有协议某个 task 翻转方向，operator 提交匹配授权的 derive 请求
- **THEN** 无需配置文件或重启服务即可产生新版本，原版本逐字段不变

### Requirement: Reversible bounded score normalization
系统 SHALL 验证 evaluator 的原始 score 为 [0,1] 内有限数，保留原始逐题证据；maximize 使用 raw，minimize 使用 1-raw。eval.show SHALL 同时提供 raw_score/raw_task_scores、normalized_score/normalized_task_scores、task_metrics 与 normalization=bounded-complement-v1；兼容 score/task_scores 指向 normalized。

#### Scenario: Raw decrease is quality improvement
- **WHEN** minimize ASR 从 0.6 降到 0.2，maximize AUROC 从 0.6 升到 0.8
- **THEN** 归一化 task_mean 从 0.5 升到 0.8，原始分原样可查且可由方向反算

#### Scenario: Wrong direction regresses
- **WHEN** AUROC 不变而 minimize ASR 从 0.2 升到 0.6
- **THEN** 归一化 suite 分下降，不作为进步

### Requirement: Consistent comparison repeats and selection
eval.compare SHALL 在同协议同题配对下用归一化逐题差异计算 delta、bootstrap 和 regressions，并返回双方 raw/normalized 汇总及 task_metrics。eval.aggregate 与只读 campaign.select SHALL 使用归一化重复均分；select 仅比较 campaign 所绑定协议，执行当前审核资格检查；平分按 model_id 字典序确定。提交仍显式执行并验证审核。

#### Scenario: Lowest ASR wins
- **WHEN** 同协议候选甲 ASR=0.1、乙 ASR=0.9，方向 minimize，其余指标一致
- **THEN** select 推荐甲，未评测/失败/跨协议/审核不合格者不参与；select 不自行提交

#### Scenario: Protocol flip is not paired improvement
- **WHEN** 两次评测来自方向不同的协议 digest
- **THEN** compare 拒绝 PROTOCOL_MISMATCH，不把目标改变算作模型进步

### Requirement: Safe public metadata and dashboard
protocol.show SHALL 为研究者提供 task 级 direction/role/metric 与授权 ID，保留题目/答案/逐题证据限制；eval.show、eval.compare 与看板 SHALL 使用同一元数据和 ↑/↓ 标注。看板 SHALL 只读且仅展示当前身份可见的开发评测，目标变化不得拼成同一可比曲线。

#### Scenario: Metadata without question disclosure
- **WHEN** 研究者查看协议、评测对比及群岛看板
- **THEN** 三处方向一致，能区分 raw/normalized，无题目、答案、逐题 ID 或隐藏分数

### Requirement: Raw grading and legacy integrity
审核器 SHALL 继续按原始分检查 grader 一致性，不能把 minimize 后的归一化值误判为篡改。无方向的旧协议与评测 SHALL 只读保留且标记 legacy，不自动猜方向或重算；新排序与派生评测必须使用人明确授权的新协议，不复用旧协议的审核结论。

#### Scenario: Minimized exact match
- **WHEN** raw exact-match=1，方向 minimize，normalized=0
- **THEN** grader 一致性检查认可 raw=1，不因目标转换报告作弊

#### Scenario: Legacy data cannot inherit guessed goal
- **WHEN** 升级后读取旧的无方向协议，并尝试用其结果参与新候选排序
- **THEN** 历史仍可读，新排序拒绝未授权方向；只能经明确授权派生并重新评测
