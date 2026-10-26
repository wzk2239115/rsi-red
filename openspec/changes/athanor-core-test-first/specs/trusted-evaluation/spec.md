## Purpose

让研究 agent 根据固定评测协议与逐题证据改进模型，并限制数据污染、协议漂移和隐藏评测泄露带来的错误结论，明确区分软件角色检查与真实部署中的身份和存储隔离。

## ADDED Requirements

### Requirement: Frozen evaluation protocol
系统 SHALL 固定评测题目、评分器、采样与聚合参数的版本和摘要，修改参数产生新协议，跨协议不得直接作配对改进比较。

#### Scenario: Output budget changes
- **WHEN** 将 max_tokens 从8改为32
- **THEN** 创建新协议摘要，原协议不变，跨协议比较报 PROTOCOL_MISMATCH

### Requirement: Item-level diagnostic feedback
系统 MUST 异步返回开发评测的逐任务分数、逐题答案与终止原因，重复评测不能覆盖原结果。

#### Scenario: Truncated answer
- **WHEN** 一道题因输出长度限制终止
- **THEN** 可按 truncated 筛选并读取该题答案及 finish_reason

### Requirement: Protected evaluation authority
系统 MUST 拒绝研究者注册评分器、获取隐藏协议或请求隐藏评测；操作者权限必须来自服务身份配置而不是请求自报角色。

#### Scenario: Forged operator field
- **WHEN** 研究者在请求中声明 role=operator
- **THEN** 不能获得操作者权限

### Requirement: Honest decontamination status
系统 SHALL 标明未检查数据与规则覆盖限制，去污染返回新快照，严格 campaign 禁止未经检查数据进入训练，研究端不得获得隐藏题匹配明细。

#### Scenario: Short benchmark item
- **WHEN** 题目短于所选13-word shingle窗口
- **THEN** 报告未覆盖题数，不宣称已证明无语义污染
