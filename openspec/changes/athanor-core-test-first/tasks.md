# Tasks

## 1. 测试先行与交付准备（本轮）

- [x] 1.1 写67项核心契约及真实进程测试；以 pytest collect-only 验证可收集，保存全红 JUnit 基线。
- [x] 1.2 写 GitHub Actions CI 与草稿 Release CD；本地核对 YAML 结构与发布依赖，尚未推送触发线上运行。
- [x] 1.3 写接口契约、测试边界与实集群验收清单，并通过 OpenSpec strict validate。

## 2. 记录与数据实现（已获统一授权）

- [x] 2.1 实现鉴权、envelope、持久化事件与 note；通过 test_execution 的权限测试及 test_evidence 的事件/笔记测试，文档同步。
- [x] 2.2 实现不可变数据快照、采样、schema check 与去污染；通过 test_evidence/test_evaluation 对应测试，保留规则未覆盖情况。
- [x] 2.3 实现模型 manifest 校验、原子发布、拉取与 DAG 血缘；通过 artifact 系列测试，记录支持的模型格式限制。

## 3. 任务服务与调度

- [x] 3.1 实现 job 事务接受、预算预留、并发幂等和 journal；通过预算/提交相关测试，补充事务失败注入测试。
- [x] 3.2 实现 reconcile/outbox、提交超时找回、失败原因、依赖与取消；通过重启/响应丢失/失败参数化测试，文档同步。
- [x] 3.3 实现 Slurm/Kubernetes 外部适配边界；通过 test_scheduler_contract，并补充真实输出解析样本测试，不能仅硬编码当前 fixture。
- [x] 3.4 实现 local CPU 独立 worker、退出记录及服务 HTTP 生命周期；通过 test_lifecycle 的真实 SIGKILL 恢复，记录生产适用范围。

## 4. 评测与 CLI

- [x] 4.1 实现冻结协议、异步 evaluator、逐题反馈、同协议比较和隐藏集权限；通过 test_evaluation，新增缺题/重复题/非法评分测试。
- [x] 4.2 实现 cli/server、help/version、专用命令及 request 通用接口；通过 test_cli 与进程测试，文档示例实际运行。
- [x] 4.3 补充重复评测汇总、不确定性、模型能力回归比较的数值测试；使用受控样本验证统计方法，不把一次评测当独立训练。

## 5. Athanor 完整工作流与集群扩展验收

- [x] 5.1 按用户新增的模拟授权，为 SFT、GRPO、两步环境 RL、on-policy distillation、合并实现 CPU 线性策略 starter 与真实子进程 smoke，先保存16项 RED 再实现；明确不是 LLM/verl 训练。真实训练框架留在5.3验收。
- [x] 5.2 为团队模型/笔记共享、持久 transcript 与事件通知补测试并实现 adapter；验证模拟 agent 重启读取及真实通知 handler 接收完成事件。真实 Codex/Claude 会话集成未执行。
- [ ] 5.3 根据实际 partition/namespace/镜像把 cluster-acceptance.md 转成实集群测试，在资源上限内验证真实权重加载、评测、故障恢复与资源账目，保存证据。
- [ ] 5.4 验证独立身份/存储/网络的最终评测隔离，以及去污染入口不能泄露隐藏样本；用绕过 CLI 的访问测试确认边界。

## 6. 最终交付

- [x] 6.1 核心测试与新增集成测试全绿，干净环境安装 wheel 冒烟；保持原始红色基线不变供比较。
- [ ] 6.2 推送授权后验证 GitHub 四组 matrix jobs 与发布门禁；配置 required checks 前不得声称分支保护已启用。
- [ ] 6.3 实集群参数明确后补部署/健康检查/回滚 CD 并在测试环境验证；目前只有安装包持续交付。

## 当前外部条件

- 用户于实现阶段明确暂不提供集群信息，要求先模拟，因此5.3、5.4、6.3保留待验收；本轮不部署集群、不占用GPU。
- 6.2所需推送/线上验证尚未进行；工作流已在本地核对，不声称 GitHub Actions 已通过。
