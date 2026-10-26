# Design

## Context

现有 local/Slurm/Kubernetes scheduler 共用 submit/find/status/cancel/logs。用户新增希望在 CI 内真实启动 Ray。原集群配置仍不可用。

## Goals / Non-Goals

**Goals:** Ray Jobs 稳定ID与实际 CPU 集成门禁；基础 CI 不强制安装 Ray，单独的 Linux/Python3.12 job 安装固定版本。

**Non-Goals:** 不创建外部集群，不冒充真实 GPU，也不把 Ray 当作评测权限沙箱。

## Decisions

- 固定 Ray 2.59.0（本次从 PyPI 与官方文档核对），作为可选 extra；生产后端通过官方 JobSubmissionClient 连接已有地址。
- 上传冻结工作目录，将目录内绝对路径转换成相对路径；用 argv 驱动的标准库超时 wrapper，避免 shell 注入并兼容 macOS/Linux。
- Ray submission_id 复用控制面 job id；查询网络失败转为可重试异常，不能误判为“没有任务”再提交。
- CI 启动自己拥有的 ray.init(address=local) 实例并在 finally shutdown；不调用会影响其他实例的全局 ray stop。保存日志诊断。
- 默认 CI 只 CPU；entrypoint 的资源申请不是整棵 Ray actor 树配额，gpu_seconds 标为 driver 资源估算。

## Risks / Trade-offs

- [Ray 启动与依赖耗时] → 独立20分钟 CI job、pip cache与固定版本；本地先运行集成测试。
- [Ray 集群终止意味着作业终止] → 保留控制服务与 Ray 生命周期的区分，不承诺集群重启后训练继续。
- [非共享输入/输出路径] → 自动上传代码，但远程数据/产物仍需要共享存储配置。
