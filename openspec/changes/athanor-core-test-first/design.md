# Design

## Context

见 proposal.md。当前仓库无业务实现，用户要求先交付失败测试与 CI/CD，后续一次授权实现。行为接口见 docs/contract.md，测试直接约束应用边界而不绑定数据库表。

## Goals / Non-Goals

**Goals:** 支持 Athanor 核心执行和证据机制，保持 agent 的算法与研究自由；真实失败、可恢复状态、可独立验证的交付包。

**Non-Goals:** 本次测试阶段不运行训练、不部署集群、不复现论文模型分数；CPU fixture 不证明 GPU、训练算法或操作系统权限隔离完成。

## Decisions

1. Python 3.12+ 控制面与 CLI，训练 entrypoint/镜像独立。相比绑定某个训练框架，更容易允许 agent 改写算法。用 pyproject 声明包，当前暂不创建 src 实现。
2. 应用服务 dispatch 与 CLI 共享操作，鉴权在服务处理请求处，不信任 payload 的角色。单个后台服务管理持久状态和作业协调；不先拆微服务。
3. 测试对真正的 ResearchService 发请求，仅替代外部 scheduler/evaluator。纯算法与 CLI 分别验证；独立进程测试验证服务 SIGKILL 后 worker 存活，避免所有结果仅来自 mock。
4. 第一个实现阶段同时提供 local CPU 调试后端与 Slurm/Kubernetes adapter 契约。用户未选择实后端，两套边界都测试；只在实际接入的后端上声称实集群可用。测试中的 adapter fake 不承担业务逻辑。
5. 元数据事务、请求先入 journal、预算原子预留与调度器 submission_key 找回共同处理超时窗口；数据库与外部调度器不存在单事务，需要 outbox/reconcile。单控制服务可先 SQLite（WAL/事务）与不可变文件存储；多副本前需替换为共享事务数据库。
6. 模型/数据按内容保存，manifest 完整后发布。模型多父边和完整输入配方用于复现。原始 token 不能写入研究记录；生产 secret 使用引用。
7. eval 通过固定 digest 链接模型、协议和逐题输出，dev 可读、held-out 仅操作者。API 角色测试先行；真实系统账号、容器/网络/存储边界由集群验收验证。
8. GitHub Actions 测试矩阵与草稿 Release 分离。只有 verify 成功才发布，版本一致并带 SHA-256。未选择部署目标时不添加虚假的集群 deploy。

## Risks / Trade-offs

- [契约过早锁定] → 只约束可观察行为；实现时发现真实矛盾，记录修正原因和需求映射，不偷删断言。
- [mock 测试与生产漂移] → CPU 独立进程测试、实集群验收清单并行；增加真实 adapter 任务前不得宣称集群运行成功。
- [全红测试掩盖测试错误] → 独立 collect、lint、人工检查 fixture，保存每例失败原因；缺模块是目前的预期，不是长期验收结果。
- [Athanor 范围很大] → 67项核心测试只是第一批；训练 starter、真实推理、多 agent 唤醒与隐藏评测隔离需补集成验收，不能以67项绿灯宣称全部复现。

## Migration Plan

当前无既有数据或服务。先完成测试基线；授权后按 tasks.md 实现，CI 全绿并在干净环境安装，再配置真实集群 smoke。发布采用草稿包交付；部署前另定数据库迁移与回滚，不在本次写入集群配置。

## Open Questions

具体 partition/namespace、资源规格、训练镜像、模型与数据 revision 将影响部署配置及实集群验收参数，后续接入时由操作者提供，不影响本轮核心软件契约与测试实施。

## 用户授权后的范围更新（2026-10-26）

用户已统一授权编码，并因暂时不能提供集群配置而明确要求先模拟执行。已实现单控制器 SQLite/HTTP 服务、独立 CPU worker、两类集群适配器，以及 CPU 线性策略的五类训练 starter、实际模拟推理和事件通知 handler。大模型训练框架、实集群资源和操作系统级隔离未被模拟测试替代，也不声称完成。
