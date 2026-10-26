# 测试先行与 CI/CD

## 红色阶段

最初红色阶段产品包 src/rsi_red 不存在，原始67项失败记录保存在 reports/red-baseline.json；现在已有实现。测试导入发生在测试体/测试内构造 harness 时，因此整套测试能正常 collect，而不是一次 import collection error 就中断。CLI 测试直接执行待实现模块；服务测试调用真正待实现的服务，只替代外部 scheduler/evaluator；不提供假的 ResearchService。

不使用 skip、xfail、continue-on-error、`|| true` 或 assert False 占位来制造红色/绿色。进程测试里的失败断言只在被测服务提前退出时报告日志；服务存在后会继续验证真实子进程与重启。

## 文件与覆盖

- test_execution.py：异步、持久化、并发幂等、提交响应丢失、重启、故障原因、依赖、取消、预算、鉴权。
- test_evidence.py：数据不可变版本、采样与 schema、模型校验/目录逃逸/多父血缘、代码来源、事件恢复、笔记、秘密脱敏。
- test_evaluation.py：逐题反馈、截断过滤、协议版本、重复评测、隐藏集访问、去污染边界。
- test_cli.py：help/version、结构化参数错误、后端不可达超时。
- test_scheduler_contract.py：Slurm/Kubernetes 与外部命令/API 边界。
- test_lifecycle.py：真实 CPU worker 跨 CLI 退出和控制服务 SIGKILL 恢复，不使用 scheduler double。

这套测试覆盖核心软件机制，尚不是“论文全部实现”的充分证明。训练 starter、真实 GPU、最终评测运行账户隔离和 agent 唤醒还需要 cluster-acceptance.md 的扩展验收。

## 实现阶段

先挑一个真实行为测试 RED → 最小正确实现 GREEN → 保持所有既有断言重构。实现中添加新边界测试；不能把现有失败偷偷改成通过。不要求配置/lint 等工具检查也人为失败：全红指尚未实现的业务行为测试。

## 工作流

ci.yml: PR、main push、手动或复用触发；Linux/macOS × Python 3.12/3.13，lint → pytest → 包构建 → 临时 venv 安装 wheel 冒烟。测试失败后仍上传 JUnit，正常失败阻止包检查和发布。
release.yml: v* 标签 → 复用同一完整 CI → 校验标签=pyproject版本 → 构建 wheel/sdist → SHA-256 → 草稿 GitHub Release。没有 PyPI/GPU/集群凭证，不会向集群部署。主 CI 只读 contents；发布任务单独获得 contents:write。取消草稿不影响运行中任务。

推送前只能验证本地测试与 YAML，不能声称 GitHub CI 已通过。远端 required status checks/分支保护需仓库设置，本轮未修改；建议后续将四个 matrix jobs 设为 required。不要在全红期间关闭检查来强行发布。

## 当前实现阶段

原67项测试文件摘要保持不变。实现后新增故障窗口、统计、模拟算法、adapter 输出解析、通知/会话和开发配置测试。对新发现缺陷先保存 RED 运行记录，再修复；reports/implementation.json 汇总最终验证。

用户明确授权模拟验收：现有 starters 是实际可运行的 CPU 线性策略算法，不是 verl/TRL 的 LLM 训练。集群和 OS 隔离仍未验证。CI 增加干净 wheel 安装后的完整 demo；手动 simulation.yml 保存演示报告。
