# 独立评测审核与训练者反馈

四个训练会话保持平级；第五个auditor会话独立提出疑点。服务端负责保存不可变证据、执行可信检查和限制最终模型提交。此版本用于打磨infra；物理隔离在后续部署阶段完成，不是本轮前置条件。

## 1. 准备身份与策略

全新部署可以离线生成四个researcher和一个auditor配置：

```sh
rsi init --profile ray-peers --with-auditor --output .rsi/h100-team --json
```

四位训练者分别加载peers/agent-N/environment.sh；第五个会话加载auditor/environment.sh。operator凭证单独保管。该操作不连接Ray、不创建实际harness会话、不启动训练，也不探测GPU。已有部署不要覆盖；operator可在service.json的principals中登记新的独立role=auditor身份，然后重启控制服务。不要把auditor加入训练members以替代scope授权。

operator创建audit-policy.json（替换真实ID）：

```json
{
  "campaign_id": "CAMPAIGN_ID",
  "protocol_id": "DEVELOPMENT_PROTOCOL_ID",
  "auditor_ids": ["auditor-1"],
  "checks": ["grader_consistency"],
  "grader_mode": "exact_match",
  "max_cases": 20,
  "max_evaluations": 100
}
```

```sh
rsi audit configure --spec audit-policy.json --json
```

只有评分定义本身就是字符串精确匹配时才选择exact_match；它不适合数学等价、代码执行或语义判分。默认grader_mode=unconfigured，缺少检查器时保留incomplete。策略绑定campaign的开发协议，held-out不能加入审核队列。

max_cases限制整个campaign的案例数；max_evaluations限制该campaign/协议的累计评测请求数，包含已有、排队和失败请求。改策略不会重置计数。审计提交的相同幂等键与相同参数返回原case，不重复计费；相同键不同参数拒绝。观察每case最多100条、单条64KiB，不触发额外推理或训练。当前不计agent token成本，也没有新增GPU扰动执行器。

## 2. 训练者查询与提交候选审核

```sh
rsi eval model MODEL_ID --json
rsi eval show EVAL_ID --json
rsi protocol show PROTOCOL_ID --json
```

输出仅含开发评测汇总、协议元数据和审核案例；不返回题目、标准答案、逐题ID、生成答案或自由文本报错。eval.samples改为operator专用诊断入口。held-out及其结果/事件不进入普通训练者查询或反馈。

将成功的开发eval提交审核（audit-case.json）：

```json
{
  "campaign_id": "CAMPAIGN_ID",
  "model_id": "MODEL_ID",
  "eval_id": "EVAL_ID",
  "policy_id": "POLICY_ID",
  "idempotency_key": "candidate-001-audit"
}
```

```sh
rsi audit submit --spec audit-case.json --json
rsi audit show CASE_ID --json
rsi audit list --campaign CAMPAIGN_ID --json
```

提交立即返回pending。服务后台根据冻结的模型、开发协议、eval和policy摘要检查；case及每个收据包含相应引用和服务端检查代码摘要。audit.record不允许客户端伪造可信收据，包括operator API客户端。

当前内置grader_consistency在显式exact_match策略下，独立重算保存输出与标准答案的一致性，检测“错误输出却被记为正确”等评分问题；不再运行模型，不声称发现所有reward hacking。format_robustness、data_overlap尚无独立可信执行器，选中时返回unavailable，case=incomplete，禁止提交。检查全部通过才是checks_passed；发现确定性不一致是blocked。

启用策略后campaign.submit只接受当前策略、同模型/协议的有效通过案例。新策略使旧通过失效；同候选的新案例尚未通过时也不沿用旧通过。未启用策略的campaign保持兼容。通过只证明列出的检查在声明范围内完成，不代表通用无作弊证明。

## 3. 第五个审核会话

审核者可以读取获授权的开发eval摘要、模型报告和case；不能提交训练或eval，不能修改评分器、配置策略或读取隐藏集。审核者不需要成为campaign的训练成员。

```sh
rsi eval model MODEL_ID --json
rsi audit show CASE_ID --json
rsi audit observe --spec observation.json --json
```

```json
{
  "id": "CASE_ID",
  "text": "需复核评分逻辑是否接受无效输出。此处为线索，不是可信结论。",
  "evidence_ids": ["EVAL_ID"]
}
```

原文只供授权auditor/operator复核；不能当指令执行。训练者仅收到固定类别independent_review_requested及预定义建议，避免审核原文夹带考题。疑点标为auditor_hypothesis/suspected，不自行更改可信检查结果。需要复杂反例时先由operator接入对应服务端检查器，不用文字声明替代实测，也不提供人工强制放行API。

## 4. 四位训练者读取并确认反馈

```sh
rsi audit feedback --campaign CAMPAIGN_ID --limit 100 --json
rsi audit feedback --campaign CAMPAIGN_ID --after LAST_FEEDBACK_ID --json
rsi audit ack FEEDBACK_ID --json
```

同campaign训练者都能读到持久化反馈。source区分auditor_hypothesis和trusted_checker；status区分suspected、confirmed_issue、incomplete、checks_passed。正文只含固定原因/建议及模型、协议、eval引用。每个身份独立ack，重复ack幂等；重启后仍保留，不删除已读历史。ack表示该身份确认阅读，不代表问题已解决。

每条反馈发出audit.feedback_available事件，可复用rsi watch和已有stdin通知handler。保存事件游标和反馈游标，失败后重试；不要把事件产生等同于实际进入harness会话。当前支持CLI主动读取、watch子进程通知，没有自动创建、投递或唤醒Codex/Claude会话的适配器。

rsi kanban显示审核状态、标准化反馈，以及每位训练者是否确认。看板只读，不暴露题目/原始疑点，也不显示“已交付到会话”。后台服务与看板需使用本次代码重启；--demo不产生真实审核结果。

## 5. 验收范围

本地验证包括正确评分通过、错误高分拦截、跨模型/隐藏集/身份越权拒绝、幂等预算、策略更换、反馈独立确认与重启恢复，以及真实HTTP后台循环和CLI。CPU fixture不代表真实Qwen/H100评测；目前生产evaluator仍需接入。后续物理隔离与真实GPU/模型/任务检查器独立验收，本轮不阻塞infra迭代。
