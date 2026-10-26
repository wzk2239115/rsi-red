# Ray 后端与 CI 中的真实运行时

Ray 是分布式运行时，可以部署在裸机、Slurm 分配的节点或 Kubernetes（如 KubeRay）上。它不是物理集群的替代物。rsi-red 的后端可以直接连接已有 Ray Jobs 服务，由它管理任务生命周期。

## 已实现

- `backend: ray`，使用官方 JobSubmissionClient；submission_id 固定为控制面的任务 ID。
- 冻结代码目录通过 runtime_env.working_dir 上传；目录内绝对路径转换为相对路径，适用于 Ray 工作目录。
- 任务状态、日志、取消、入口超时与重连找回；连接失败不会误判为“任务不存在”。
- CI 独立增加 `ray-jobs-ubuntu-py3.12`，真实启动 CPU Ray，不使用 mock SDK。release 与 simulation delivery 复用整个 CI，所以 Ray 测试失败会阻止交付。

Ray 固定为 **2.59.0**，是可选 extra，不强迫基础控制面安装整个运行时。

## 本地运行集成测试

```sh
cd /Users/wzk/Desktop/rsi-red
source .venv-ray/bin/activate
RAY_USAGE_STATS_ENABLED=0 python -m pytest integration/ray -v
```

若没有专用虚拟环境：

```sh
python3.12 -m venv .venv-ray
source .venv-ray/bin/activate
python -m pip install -e '.[ray]' -r requirements-dev.txt
RAY_USAGE_STATS_ENABLED=0 python -m pytest integration/ray -v
```

测试独立创建本地 Ray 实例（2 CPU、0 GPU），完成后关闭自己拥有的实例并保存 reports/ray-logs/。不使用全局 ray stop，以免终止其他实例。Ray 2.59.0 关闭时遗留 reaper stdin 管道，fixture 显式持有并关闭该实例的进程句柄，不屏蔽 ResourceWarning；此清理代码依赖固定版本的内部句柄结构，升级 Ray 需重新验证。

5项真实运行时验收：

1. 提交程序，实际执行 Ray remote tasks 并读取日志。
2. 停止一个正在运行的长任务。
3. 非零退出应报失败。
4. 超出入口时间预算应终止并报 timed_out。
5. 控制服务关闭并重新打开，找回同一 Ray 任务，attempt_count 保持1。

基础测试仍使用 `pytest tests`，其中包含 Ray adapter 契约测试但无需安装 Ray。`pytest integration/ray` 必须有真实 Ray，缺少依赖时正常失败，不使用 skip。

## 连接已有 Ray

先使用操作者配置的 Ray 地址，将控制服务 JSON 的 scheduler 改为：

```json
{
  "backend": "ray",
  "address": "http://127.0.0.1:8265"
}
```

例如在隔离开发机上手动启动：

```sh
ray start --head --node-ip-address=127.0.0.1 --dashboard-host=127.0.0.1 --num-cpus=2 --num-gpus=0
```

控制服务用同一虚拟环境启动。代码自动上传；数据和模型的跨机存储仍需要配置共享路径/对象存储，不能依赖 Mac 本地绝对路径。若任务声明 image，必须和操作者的 cluster_image 配置一致；适配器不会静默忽略镜像并在别的环境运行。

## 验证边界

- CI 验证真实 Ray Jobs 与 CPU task，不代表真实 GPU、CUDA、NCCL、多机容错或 LLM 训练通过。
- entrypoint_num_gpus/cpus 限定的是 driver 资源，不能当作整个子 actor 树的配额；gpu_seconds 标记为估算。使用 Ray Train 等框架时还需单独设计 worker 资源与预算。
- Ray 集群停止后，作业也会终止；控制服务重启与 Ray 集群重启是不同的故障条件。
- Ray 不是隐藏评测的权限沙箱；访问 Ray Jobs 的用户可以执行代码，开发环境只监听本机，不暴露不受控网络。
- 本地成功与 GitHub Actions 在线执行分开记录，本轮没有推送或触发远端 CI。

参考：[Ray Jobs Python SDK](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/sdk.html)、[submit_job](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/doc/ray.job_submission.JobSubmissionClient.submit_job.html)、[Ray 安全模型](https://docs.ray.io/en/latest/ray-security/index.html)。
