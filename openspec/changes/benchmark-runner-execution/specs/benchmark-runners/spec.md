# Benchmark Runners

## Purpose

为外部benchmark保存可执行、内容固定且来源可核验的运行配置，明确评测协议与执行器的边界。让操作方登记可信harness、judge及数据版本，让研究者对新模型复用同一配置，同时保留方向的人授权与题库访问限制。

## ADDED Requirements

### Requirement: Operator registration and immutable version
系统 SHALL 仅允许operator注册runner，冻结protocol引用、harness来源/完整commit/内容快照、judge版本、dataset/split、解码、环境、资源、命令模板和输出schema并计算digest。修改配置 SHALL 生成新ID/digest，不提供更新原实体的操作。注册不得启动评测或训练。

#### Scenario: New judge version
- **WHEN** operator用新judge版本登记配置
- **THEN** 产生新runner版本，旧runner和既有eval不变

#### Scenario: Researcher attempts registration
- **WHEN** researcher或auditor请求runner.register
- **THEN** 返回FORBIDDEN，不创建runner或外部任务

### Requirement: Verified content inputs
runner SHALL 使用内容固定的输入，拒绝分支名/latest等浮动revision、dirty源码、错误commit/内容摘要。注册时保存实际源码和协议输入快照；执行时不得重新读取可变原目录或重新拉取远端分支。环境声明与实际环境收据 SHALL 区分，不把镜像标签当实际镜像证明。

#### Scenario: Original source modified
- **WHEN** 注册后原harness目录被修改或删除
- **THEN** 已注册runner仍执行原快照；内部快照校验失败时拒绝执行

### Requirement: Compatible authorized protocol
runner SHALL 绑定唯一不可变protocol ID/digest；dataset名称/revision/split、题目内容摘要、judge评分摘要、sampling和seed必须匹配协议。方向由protocol的人授权决定，runner和eval请求不得覆盖direction或正式评分定义。

#### Scenario: Decoder override
- **WHEN** runner与protocol的temperature/max_tokens或评分摘要不一致
- **THEN** 注册拒绝RUNNER_PROTOCOL_MISMATCH，不静默采用任意一方

### Requirement: Structured execution contract
runner SHALL 定义argv数组、受限占位符、local或ray后端、非负资源、正walltime、固定版本环境及严格输出schema。拒绝未知占位符/字段、命令字符串、越界输出路径和明文凭证；支持凭证引用，不在配置/公共输出持久化解析后的secret值。

#### Scenario: Unknown template placeholder
- **WHEN** 命令包含未声明占位符或输出指向执行目录外
- **THEN** 返回INVALID_REQUEST，无调度副作用

### Requirement: Safe runner discovery
runner.show/list SHALL 按身份和protocol可见性过滤。operator可查看完整冻结配置；研究者只能查看开发runner的ID/digest、protocol引用及无题来源元数据，不得获取完整命令、路径、题目、答案、凭证或隐藏runner。

#### Scenario: Hidden runner discovery
- **WHEN** researcher列出runner或请求隐藏runner
- **THEN** 列表不含隐藏runner，直接请求被拒绝，不泄露题目或judge凭证
