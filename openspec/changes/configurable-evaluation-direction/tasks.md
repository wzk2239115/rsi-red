# Tasks

## 1. 规划与 RED 门禁

- [x] 1.1 阅读现有协议/比较/审核/提交/看板，写 proposal/spec/design，并记录人授权方向的新增决定；以 OpenSpec strict 验证。
- [x] 1.2 编写30项可执行方向与授权契约，实际30 RED、265项已实现回归GREEN，记录reports/evaluation-direction-red.json；无skip/xfail、收集错误或产品修改。
- [x] 1.3 接Ubuntu/macOS独立CI JUnit/失败注解与发布阻断，核对release/simulation复用verify，写review入口供审阅；不跳过RED放行发布。

## 2. 人授权与协议版本（另行授权实现后）

- [x] 2.1 实现 direction.authorize 的权限、范围、持久化与元数据；授权越界/伪造/缺失契约转 GREEN，docs/contract.md 写操作方信任边界。
- [x] 2.2 实现 schema 默认继承与 task 一致性；补未知字段、同 task metric/role 冲突、非法数值负例，迁移合法测试/演示显式授权，不删除断言。
- [x] 2.3 实现 protocol.derive 及 CLI，增加未知 task、偷改 sampler/grader、来源错配、重启后版本不变测试与完整 CLI 示例。
- [x] 2.4 无方向旧记录只读标记；构造升级前存储验证读取保留、新 eval/排序拒绝，文档列派生/重测步骤。

## 3. 测量、比较、选择（另行授权实现后）

- [x] 3.1 原始证据与服务归一化分开，task_mean、反向目标和越界/NaN/伪造 normalized 先 RED 后 GREEN，docs/contract.md 添加 mixed-polarity 数值算例。
- [x] 3.2 compare/aggregate 使用归一化配对/重复均分，保留 raw、安全投影及跨协议拒绝；补跨版本、隐私与 grader 一致性回归，文档说明 CI 含义。
- [x] 3.3 实现只读 campaign.select，验证重复平均/平分/空候选/不同协议/审核拒绝/审核通过者选择，并确保显式 submit 仍有门禁；写 API/CLI 契约。

## 4. 看板与自然语言配置（另行授权实现后）

- [x] 4.1 实现权限过滤 eval.list 与看板真实评测数据、↑/↓/role/raw/quality，HTTP/浏览器核对三处元数据一致及不可写/不泄题；文档区分原始分与目标分。
- [x] 4.2 更新 rsi-research skill 的自然语言目标预览/人授权/歧义澄清流程；手工 harness 验收正反目标、仅授权开发不授权方向等六组，不把文档字符串检查冒充意图理解测试。

## 5. 整体验证

- [x] 5.1 本地315项已实现回归与新方向契约全绿、15项真实Ray CPU/ruff/build/clean wheel/OpenSpec strict通过；GitHub run40332953479的12项已实现门禁全绿，只有原islands RED失败，完整历史留证且不绕过。
- [x] 5.2 交付授权→新协议→两候选受控分→比较→建议→显式提交→看板的 CPU 集成证据；说明其不是 H100/真实模型评测结果。

## Workflow follow-up

- 规划轮已交付spec/RED/CI；用户已进一步授权apply，现按该任务清单验证交付。
- 真实安全 benchmark evaluator、H100 训练、held-out 策略、同 campaign 切换目标均不在本 change。
