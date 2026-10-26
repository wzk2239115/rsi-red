# Design

## 定位

原_info将所有SDK错误包装TimeoutError，reconcile又无记录continue，导致无可见故障。SDK是HTTP接口，不假定存在需要“连接池重连”的持久GCS会话；用有界HTTP请求、失败后重建SDK并刷新凭证解决客户端侧问题。单独重启head会丢历史job，不能承诺原任务继续运行。

Ray2.59本地源码显示get-auth-token不带--generate只读取token；新进程在RAY_AUTH_MODE未设置且有token时可能自动启用认证。无法凭容器报告断言普通读取命令改变了正在运行head的认证。

ray.init local默认GCS动态端口，但dashboard-agent HTTP默认52365；报告中6379冲突不是已证实唯一原因。新fixture显式隔离所有可配置固定端口，并使用CLI --head --port=0 --block，移除继承的RAY_ADDRESS/GCS端口和子进程代理，只清理自己的进程组。

## 决策

- GET类查询仅重试一次，可重建SDK；POST提交结果不明只按稳定ID查询，不能自动再次提交。
- 每次SDK HTTP调用设置超时。使用固定2.59 SDK的_do_request覆写，升级需测试。连接延迟到reconcile，head短暂不可用不阻止控制服务启动。
- 调度错误健康状态默认300秒后stalled，错误类型、起始时间、计数、操作需求持久化；通过事件可通知watch。仍保持任务和预留，不把失联当作已取消。恢复记录事件。
- job.show保留SDK诊断/退出码/计费估算范围。空stdout时logs使用受限长度、凭证脱敏后的SDK message。仅作已知凭证与常见格式脱敏，不承诺任意训练日志DLP。
- python_executable为节点上有效的绝对路径，同时用于wrapper和python训练入口；runtime_env PATH补该目录。默认保留原绝对解释器，不把控制机路径伪装成远程可用路径。
- auth_mode=auto沿用SDK环境策略；token要求auth_token_file，0600/0400，使用Authorization头；disabled只显式选择客户端无凭证，不关闭head保护。重建时重读文件。rsi与Ray token彼此独立。
- image digest标签匹配只证明声明相等，结果标注operator-declared-label-only。真正镜像执行需要Ray image_uri/容器运行时和节点验收，当前不做虚假背书。

## 验证边界

CPU真实Ray可验证上传/执行/认证/端口隔离/重启丢历史，不证明H100容器的代理、GCS包下载、CUDA/NCCL和存储挂载正确。保留设备复测清单和日志诊断步骤。
