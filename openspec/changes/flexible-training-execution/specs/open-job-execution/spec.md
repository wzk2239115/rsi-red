## Purpose

让研究agent通过稳定CLI自由定义计算过程，而不被starter模板或算法白名单限制。系统承担能力校验、资源约束和执行记录；保留正式评测边界，明确区分已支持的单节点运行与尚未交付的分布式能力。

## ADDED Requirements

### Requirement: 研究方法保持开放
系统 SHALL 接受任意有效argv、非空method及可序列化JSON参数；不要求从starter中选择算法，不依据方法陌生、训练reward改动、失败或分数下降拒绝任务。参数保密处理不改变普通训练配置。

#### Scenario: 自定义算法与训练奖励
- **WHEN** agent登记新的method、自定义loss/reward并提交自己的代码
- **THEN** 在身份、输入、资源有效时接受，不增加方法审批

#### Scenario: 模板不是白名单
- **WHEN** 提交starter未提供的方法或Shell入口
- **THEN** job.submit继续支持，原始argv语义保留

### Requirement: 无执行副作用预检
系统 SHALL 提供job.validate，复用提交校验，返回valid、normalized和warnings；预检不创建job/事件、不预留预算、不安装依赖、不运行代码、不提交或连接外部调度器。预检只代表静态条件，不证明训练成功或GPU可用。

#### Scenario: 反复预检
- **WHEN** 同一有效spec多次validate
- **THEN** 每次valid=true，job列表、预算与事件游标不变

#### Scenario: 输入或依赖摘要不符
- **WHEN** 预检发现代码或requirements实际内容与摘要不符
- **THEN** 返回CHECKSUM_MISMATCH，不创建任务

### Requirement: 明确执行拓扑能力
第一阶段 SHALL 支持execution.mode=command、nodes=1，在一次资源分配内运行任意程序，包括torchrun。未声明execution的旧请求采用同一语义。请求nodes>1或mode=ray_tasks时，validate与submit SHALL 返回UNSUPPORTED_EXECUTION_TOPOLOGY，不能静默降级到单节点。

#### Scenario: 单节点八卡入口
- **WHEN** 支持GPU的后端接收nodes=1、gpus=8和torchrun参数
- **THEN** 保留参数与整组GPU申请，进入正常预算/队列流程，不宣称实际训练验收

#### Scenario: 后端不能执行的模式
- **WHEN** 请求多节点或受管动态Ray子任务模式
- **THEN** 提交前明确拒绝，不预留预算，不创建accepted任务

### Requirement: 执行字段不可静默丢弃
系统 SHALL 校验execution与runtime的未知结构字段，返回INVALID_REQUEST；训练框架自己的任意参数继续放配置文件、argv或recipe.parameters。校验不得变成训练算法白名单。

#### Scenario: 拼错运行环境字段
- **WHEN** runtime包含未声明的结构字段
- **THEN** validate和submit拒绝，不出现“接受后忽略”

### Requirement: 训练奖励与正式评分分离
系统 SHALL 允许agent训练代码中的自定义reward和独立训练验证，同时维持operator登记的正式协议不可被researcher/auditor修改。普通研究失败不自动形成作弊判决；审核仍依据可信检查证据。

#### Scenario: 合法reward实验
- **WHEN** agent修改训练reward且没有修改正式协议
- **THEN** 实验可执行，原正式协议摘要不变

#### Scenario: 研究者修改正式评分器
- **WHEN** researcher请求覆盖或登记正式protocol
- **THEN** 保留FORBIDDEN，不通过开放训练接口绕过
