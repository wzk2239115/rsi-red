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

### Requirement: 训练者可接收审计反馈
系统 SHALL 为开发审计的疑点和可信判决生成持久化反馈，包含case/model/protocol引用、来源、状态、理由、可见证据和建议；接收者由服务端campaign共享范围确定。默认同一共享campaign的四个训练者可读，跨campaign不自动广播。

#### Scenario: 疑点广播给训练者
- **WHEN** auditor为开发case追加疑点
- **THEN** 产生source=auditor_hypothesis、status=suspected的反馈和audit.feedback_available事件，所有获准训练者可查询，不能显示为已证实作弊

#### Scenario: 判决来源可辨认
- **WHEN** 可信检查器完成验证
- **THEN** 追加confirmed_issue/checks_passed/incomplete等反馈，附执行收据；保留先前疑点记录，不以客户端自报替代判决

### Requirement: 可恢复投递与确认
系统 SHALL 提供有游标的audit.feedback查询和按接收身份幂等的audit.ack，保留事件以供watch/harness适配器至少一次投递。实际送入会话需明确target映射与适配器，不得仅凭事件存在声称用户会话已收到。

#### Scenario: 独立确认
- **WHEN** 某训练者确认收到反馈
- **THEN** 仅更新该接收者的确认记录，其他训练者仍可独立接收；重复确认幂等，服务重启后仍可查询

#### Scenario: 离线训练者恢复
- **WHEN** 训练者恢复后按游标拉取
- **THEN** 可以读取遗漏反馈，已确认消息不被删除，发送失败不错误推进投递游标

### Requirement: 反馈不扩大权限或执行范围
系统 SHALL 校验反馈查询/确认的campaign权限与接收身份；反馈文字是审计证据数据，不自动执行建议命令。隐藏审计结果不进入研究者可见反馈流。

#### Scenario: 无关身份不可取反馈
- **WHEN** campaign外研究者查询或确认反馈
- **THEN** 拒绝操作，不透露反馈内容或隐藏评测信号

### Requirement: CLI评测投影不含考题
训练者和auditor的protocol.show SHALL 不返回items、prompt或标准答案；eval.samples仅operator可用。eval.show及按模型查询仅返回白名单汇总字段，不回显evaluator附加字段、逐题ID、原始输出或自由文本诊断。

#### Scenario: 权限兼容调整
- **WHEN** 训练者查询逐题结果
- **THEN** 拒绝访问，operator仍可诊断；保留原逐题测试并将调用身份明确为operator，新增训练者拒绝断言

### Requirement: 可见反馈采用安全投影
训练者收到的反馈 SHALL 只包含固定问题类别、模型/协议引用、状态及预定义建议；auditor自由文本和可信checker的私有逐题证据不进入训练反馈。原文仅保存供授权auditor/operator复核。

#### Scenario: 疑点文本夹带考题
- **WHEN** auditor观察包含题目、答案或指令文字
- **THEN** 原文不进入训练者audit.show、反馈、事件或看板；对外只返回标准化疑点类别

### Requirement: 有界检查与明确覆盖
可信检查器 SHALL 使用实际冻结输出和服务端代码生成收据，未实现的检查标unavailable；exact_match评分一致性需operator显式选择。策略限制case与开发eval次数，幂等重试不重复消耗；未覆盖检查不放行。检查通过仅适用于该模型/协议及声明范围。

#### Scenario: 缺少真实扰动执行器
- **WHEN** policy要求format_robustness但没有相应执行器
- **THEN** case为incomplete，不生成通过收据

### Requirement: 可选第五身份离线初始化
ray-peers profile SHALL 支持显式--with-auditor，额外生成一个独立auditor凭证/工作区/environment.sh，不改变四个researcher身份、不授予operator权限、不启动会话或任务；不带选项保持兼容。

#### Scenario: 准备第五个平级会话
- **WHEN** operator离线初始化ray-peers并启用auditor
- **THEN** 生成第五套独立配置并在peers.json单独记录auditor，不自动加入campaign训练成员

### Requirement: 本地观察与控制服务启动不依赖外部DNS
控制服务和看板 SHALL 在已明确loopback地址时直接绑定监听，不为了server_name发起反向DNS查询，避免macOS runner的DNS等待阻断CLI就绪。

#### Scenario: 反向DNS不可用
- **WHEN** socket.getfqdn不可用或阻塞
- **THEN** loopback HTTP服务仍能创建并给出端口，不延长启动测试期限
