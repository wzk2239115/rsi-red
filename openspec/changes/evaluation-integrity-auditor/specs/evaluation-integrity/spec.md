## ADDED Requirements

### Requirement: 独立平级审计身份
系统 SHALL 支持operator授予campaign范围的auditor身份，仅允许读取授权审计证据与追加疑点；不得因此授予训练、评分器修改、策略配置或隐藏评测访问权限。

#### Scenario: 审计身份不是operator
- **WHEN** auditor尝试提交训练、配置审计策略或读取held-out协议
- **THEN** 拒绝相应操作

### Requirement: 审计绑定不可变事实
audit.submit SHALL 返回异步case ID，绑定真实模型digest、开发协议digest、eval ID与策略digest，不因高分直接放行；跨模型/协议记录拒绝。

#### Scenario: 高分不等于审计完成
- **WHEN** 提交开发评测成功的模型审核
- **THEN** 返回pending，保留对应digest，不自行生成通过检查或训练任务

### Requirement: 线索与可信结果分离
audit.observe SHALL 保留作者和追加证据引用，标为auditor_hypothesis；客户端不得上传自称trusted的通过收据或仅凭文字将状态设为checks_passed。

#### Scenario: 不可伪造放行
- **WHEN** auditor或researcher提交无执行收据的通过声明
- **THEN** 拒绝放行，保留case待验证状态

### Requirement: 开发审计不泄露隐藏反馈
首版审计 SHALL 拒绝held-out评测进入研究可见case，不返回隐藏样本、逐题答案或自适应隐藏反馈。

#### Scenario: held-out不进入普通审计队列
- **WHEN** 请求审计held-out协议的评测
- **THEN** 拒绝且不暴露题目或答案

### Requirement: 策略启用后的候选提交门禁
启用审计策略的campaign SHALL 在最终提交时要求同模型/同开发协议、全部必需检查有可信收据且符合策略的case；训练保持异步自由，未启用campaign保持兼容。

#### Scenario: 没有审计收据
- **WHEN** 研究者提交未完成审计的候选
- **THEN** 返回AUDIT_REQUIRED，不改变campaign提交记录
