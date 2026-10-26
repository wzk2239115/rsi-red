# Benchmark Runner 规划验证

2026-10-26，本轮按用户要求只做spec、RED和CI/CD，等待审批，不实施产品。

变更入口：openspec/changes/benchmark-runner-execution/review.md。已交付proposal、两个能力spec、design、分阶段tasks与审阅说明。

实际本地结果：

| 检查 | 结果 |
|---|---|
| CPU runner应用/CLI契约 | 46 RED，0收集错误、0 skip |
| Ray runner契约 | 2 RED，0收集错误、0 skip |
| 已实现功能回归 | 315通过 |
| 外部CPU测试driver自检 | 真子进程生成合法JSONL、非零退出通过；只是fixture分数 |
| OpenSpec strict / ruff | 通过 |
| CI YAML及release/simulation复用verify | 通过 |
| 产品src差异 | 无 |

主要RED来自runner.register/show/list和eval.config缺失、CLI入口缺失。另一个独立负例揭示：当前eval.submit若同时提供旧字段，会忽略未知runner_id并接受旧evaluator请求；未来实现必须拒绝不存在runner，不能静默回退。

Ray两项尚在runner.register处失败，没有启动临时head或真实执行，不能将它们称为“Ray已验证”。审批后转GREEN时必须真走head/SDK和外部进程；local子进程fixture也不能由进程内fake evaluator代替。更深的崩溃窗口/并发账目/实际环境漂移测试列在对应实现任务中，必须先RED后实现。

CI新增benchmark-runner-contracts（Ubuntu/macOS）与benchmark-runner-ray-contracts（Ubuntu+固定Ray extra），均保存JUnit和失败注解，无continue-on-error、skip或xfail。新RED会阻断发布，既有32项研究岛屿RED保留，未更改其行为。远端状态见benchmark-runner-red.json的ci字段；本报告不把配置存在称为远端通过。

本轮不改正式docs/contract.md中“已实现接口”的语义、不重启原服务、不更改任何实际bench方向、不安装真实bench或占用GPU。待用户明确批准，再进入OpenSpec apply。
