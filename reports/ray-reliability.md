# Ray运行可靠性修复

2026-10-26。用户提供远端8×H100容器探索报告，但本次无该设备访问权。该报告不是本次现场验收结果。

## 根因与修复

- 已定位：Ray _info统一转TimeoutError、reconcile静默continue；现在有持久化健康状态、warning、事件、恢复记录和默认300秒停滞提示。未决提交不重放、不释放未知外部作业预算。
- 已定位：适配器将控制机sys.executable改成裸python；现在保留绝对解释器，增加节点python_executable和runtime_env PATH。
- 已定位：SDK错误诊断、退出码及GPU估算范围未进入job；现在保留，空stdout回退SDK message并做有限脱敏。
- 已定位：未显式配置客户端认证，Ray本地token发现和进程认证模式可能不一致；现在支持auto/token/disabled、受保护文件头注入和重建时重载。未对任何既存集群关闭认证。
- 已定位：Ray2.59 dashboard-agent HTTP默认52365；新测试CLI head独立GCS/agent/dashboard等端口、目录、进程组和子进程环境，不全局ray stop。
- 已澄清：cluster_image只是操作者声明标签匹配，不验证实际容器，job明确标记operator-declared-label-only。

## 验证

- 首10项故障契约先RED后GREEN，追加6项边界验证；普通回归+看板入口共159通过。
- 真实CPU Ray：9项集成测试，覆盖原闭环、认证正/负例、两个head共存、同URL重启、无效解释器诊断、有界HTTP请求。
- 原研究层32项RED继续保留，整体CI发布门禁仍阻塞；这不等于Ray修复测试失败。

## 尚不能证实的报告推断

- 普通get-auth-token在2.59源码中只读，--generate才生成；不能认定读取命令改变正在运行head的认证。
- ray.init local通常使用动态GCS端口；不能认定容器故障唯一原因是6379争用。
- GCS working_dir下载失败需在容器复核代理、节点IP、临时目录和网络；当前本地上传成功不能代替复测。
- GPU调度/利用率、CUDA/NCCL、真实训练、实际镜像与跨节点数据分发尚未在该H100容器复验。

操作和配置见docs/ray.md。SDK deadline覆写依赖固定Ray2.59的_do_request接口，版本升级需重新验证。
