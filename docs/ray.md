# Ray 后端：运行、认证与故障恢复

固定支持 Ray 2.59.0。Ray可以运行在裸机、Slurm分配的节点或Kubernetes中；H100并不必然只能使用Ray，当前项目的local adapter仅支持CPU，Slurm/Kubernetes也有适配器但未在该容器现场验收。

## 安装与独立集成测试

```sh
python3.12 -m venv .venv-ray
source .venv-ray/bin/activate
python -m pip install -e '.[ray]' -r requirements-dev.txt
RAY_USAGE_STATS_ENABLED=0 python -m pytest integration/ray -v
```

测试通过CLI启动自己拥有的临时head（2 CPU、0 GPU），GCS使用`--port=0`，dashboard与dashboard-agent HTTP/gRPC、runtime-env、metrics、Ray Client端口独立分配，目录独立。启动子进程设置venv PATH、显式测试认证模式，清除继承的Ray地址和该子进程的代理。清理只作用于自有进程组，绝不执行全局`ray stop`，不用先停已有集群。临时选端口存在常规bind竞争窗口，启动失败会保留日志。

9项真实CPU Ray验收：remote tasks与日志、取消、非零退出、walltime、控制服务重开找回、认证head与原head共存、无效Python的可见诊断、同URL重启head后旧记录丢失且不重放、真实SDK HTTP超时。日志保存在reports/ray-logs下每个实例自己的子目录。

Ray 2.59的ray.init local本身默认可用动态GCS端口，并不能凭报告确认是6379冲突；已确认dashboard-agent HTTP默认端口52365是同机冲突风险。容器GCS包下载失败还可能涉及网络/代理/地址/临时目录，不能仅靠本地测试认定根因已排除。

## 连接与解释器

scheduler配置示例（替换为节点真实路径；不要把Mac解释器路径带到Linux）：

```json
{
  "backend": "ray",
  "address": "http://127.0.0.1:8265",
  "python_executable": "/opt/rsi/.venv/bin/python",
  "request_timeout": 5,
  "auth_mode": "token",
  "auth_token_file": "/secure/ray-auth-token",
  "cluster_image": "operator-declared-image@sha256:REPLACE_WITH_DIGEST"
}
```

python_executable同时用于任务wrapper与Python训练入口，runtime_env的PATH加入其bin目录。绝对解释器不再自动变成裸python。没有显式配置时，裸python仍依赖节点PATH；原绝对路径保持原样并要求在节点存在。自定义非Python入口保留argv语义。Ray worker环境仍需具备ray/torch/CUDA等依赖；指定路径不会自动安装包，也不保证多节点上的路径一致。

数据/权重不随代码working_dir自动解决分发，应配置共享路径或对象存储。代码包下载失败时先查看job.show中的scheduler_error_type、diagnostic，再查任务节点runtime_env日志。不要依赖driver stdout一定存在。

## 显式认证策略

rsi控制服务凭证和Ray集群凭证是两套不同凭证。不要将Ray token写入job env、metadata、脚本头或Git配置。

- `auth_mode: auto`（兼容默认）：SDK使用进程自身Ray认证环境；容易受既存环境影响，部署应显式选择。
- `auth_mode: token`：要求auth_token_file，权限0400/0600；SDK通过Authorization头认证，重建客户端时重新读取文件。不回显token值。
- `auth_mode: disabled`：客户端显式不加载本地token，不修改head的认证设置。只适用于操作者已配置的隔离开发head；连接认证head会明确失败。

启动认证集群时，操作者应预先配置同一受保护token文件并分发到必要节点，然后在启动head/worker前设置：

```sh
export PATH="/opt/rsi/.venv/bin:$PATH"
export RAY_AUTH_MODE=token
export RAY_AUTH_TOKEN_PATH=/secure/ray-auth-token
ray start --head --node-ip-address=127.0.0.1 --dashboard-host=127.0.0.1 --num-gpus=8
```

这是启动示例，不是对现有集群执行重启的指令；多节点应使用节点间可达的私网地址并配置网络边界。只在隔离开发环境创建无认证head时才显式设置`RAY_AUTH_MODE=disabled`，不得为排障自动关闭已有认证。

Ray2.59源码中，普通`ray get-auth-token`只是读取；`--generate`才会在缺失时生成token。RAY_AUTH_MODE未显式设置且已有token时，新的ray start进程可能自动启用认证。没有现场进程环境与日志，不能认定“读取一次token改变了运行中head”。不要反复生成或切换token来试错。文件更新后，错误请求会触发客户端重建与重读；需要同步更新节点端凭证，客户端文件单独改变不会自动轮换整个集群。

容器使用外网代理时，为Ray私网地址和localhost配置NO_PROXY/no_proxy；如使用gRPC代理变量也应核对对应绕过配置。外部模型下载仍可保留所需代理。不要把代理凭证写进错误报告，测试子进程的清理代理策略不等于生产环境的统一策略。

## 失联、恢复与未决提交

SDK请求有界超时；只读查询失败后最多重建重试一次。POST提交不自动重放，以稳定submission_id查询找回。控制服务可在head暂不可达时启动。

job.show增加scheduler_health：status=degraded/stalled/healthy、code、since、last_checked、failures、needs_operator。默认失联300秒后stalled，可通过服务顶层scheduler_stall_seconds配置。状态变化写warning日志和job.scheduler_degraded/stalled/recovered事件，可接rsi watch通知。

**失联超时不是作业停止证明。** 不会为“修好accepted”自动释放预算或重复训练。SUBMISSION_UNRESOLVED表示请求可能已被接受、但无法确认，应查实际集群记录后再取消/重新开展试验。旧Ray任务在新head上明确缺失时立即告警RAY_JOB_LOST并保留预算待操作者核查，不宣称训练跨head重启存活。控制服务重启与Ray head重启不同。

job.show保留exit_code（SDK无值则null）、diagnostic、scheduler_error_type、accounting_estimate、accounting_scope、environment_verification。日志为空时job logs回退到脱敏后的SDK诊断。脱敏覆盖当前凭证及常见token/password格式，不能替代任意用户训练日志的数据保护。

## 镜像与计费边界

cluster_image只校验请求标签与操作者声明相同，**不会拉取、验证或执行该镜像**。结果明确标记environment_verification=operator-declared-label-only。真实镜像约束需单独接入并验证Ray容器运行时/image_uri与节点部署；当前不能将字符串匹配说成镜像已验证。

entrypoint_num_gpus/cpus只表示Ray job driver资源，不限制整个子actor树。gpu_seconds为driver-reservation-estimate，服务现在保留估算字段；并非GPU实际利用率或完整GPU账单。CUDA_VISIBLE_DEVICES是进程可见设备映射，不足以证明整个集群资源边界。

## H100恢复后的复测

1. 固定Ray/Python/torch版本与节点解释器路径，核对服务和head认证模式；不输出token。
2. 保留外部代理，确认localhost/节点地址绕过代理；上传小working_dir验证GCS下载。
3. 提交单卡冒烟程序，检查torch可用、CUDA设备、日志和记账范围。
4. 在已授权测试窗口重启head，验证健康告警、丢失状态和不重复提交；不要在生产运行中随意测试。
5. 再跑短程真实训练和受控评测，验证存储、CUDA/NCCL及镜像事实。

参考：[Ray Jobs SDK](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/sdk.html)、[Ray认证](https://docs.ray.io/en/latest/ray-security/token-auth.html)、[RuntimeEnv](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html)。本地CPU通过不代表H100容器问题已全部现场解决。
