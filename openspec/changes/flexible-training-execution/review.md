# 供审阅：开放训练执行

原始规划状态：只写spec、测试与CI/CD。后续更新：用户已授权实现；本页保留当时审阅内容，当前实现与验收见docs/flexible-training.md、reports/flexible-training-implementation.md。

## 你要审的核心决定

1. **研究方法完全开放**：自定义算法、loss/reward、模型结构、数据生成、合并和任意训练入口都不需要方法白名单或审核员批准。starter只是例子。实验失败、低分、陌生方法不等于作弊。
2. **正式评测独立**：训练reward可改，正式protocol/标准答案/可信收据仍由独立服务管理，研究者不能伪造结果。沿用已有审核反馈，不增加逐实验审批。
3. **先打磨单节点8卡**：自定义Python/Shell/torchrun，一次申请内使用8卡；四个平级会话的拓扑不变。物理隔离后续做。
4. **逐任务环境**：依赖内容快照、可选已有Python、私有venv、实际包清单；安装也计入预算和walltime，失败不继续跑训练。
5. **自由产物**：adapter、自定义checkpoint、生成数据、分析报告都能保存；程序运行后再决定实际输出，通过manifest发布并绑定生成job、代码与环境。

## 拟新增/扩展的接口

| 接口 | 可见行为 | 当前状态 |
| --- | --- | --- |
| `rsi job validate --spec job.yaml` | 不执行、不预留预算的静态预检 | 待实现 |
| job.spec `execution` | 单节点command拓扑；不支持的模式明确拒绝 | 待实现新校验 |
| job.spec `runtime` | 每任务Python/requirements内容快照、执行清单 | 待实现 |
| job.spec `output_manifest` | 程序运行后公布产物，不预设算法/文件格式 | 待实现 |
| `rsi job outputs JOB_ID` | 查询已校验产物、ID与内容摘要 | 待实现 |
| `artifact.register kind=自定义类型` | 通用文件校验，旧model校验保留 | 待实现 |
| recipe.method / parameters / argv | 保持自由，修复普通tokenizer参数被脱敏误伤 | 已有基础能力，待修保真问题 |

完整字段、错误码、状态与执行策略见[design.md](design.md)；三份规范在[specs/](specs/)。

## 第一阶段明确不混入的能力

多节点rendezvous/弹性训练、受管动态Ray actors与全部子资源记账、跨主机产物网络传输另写后续change。第一阶段采用现有单容器共享文件根，不能把worker缓存目录当控制面目录。CLI对未支持的拓扑/输出传输明确报错，不假装“接受了就支持”。agent可用Ray库，但当前不能承诺未受管子资源也被完整计费。

这不是限制研究方法：是把基础设施尚未实现的运行能力明确标出来，后续仍可扩展。

## 已实际跑出的测试结果

| 范围 | 结果 |
| --- | --- |
| 新CPU契约（包含真实子进程） | 37项：28 RED、9 GREEN |
| 新功能真实Ray Jobs CPU契约 | 2项：2 RED |
| 已实现功能回归 | 204 GREEN |
| OpenSpec strict、ruff、CI依赖检查 | 通过 |

没有skip、xfail、产品占位实现、GPU任务或模型下载。RED是预检、环境、产物等需求尚未实现，不是导入/收集错误。9项已有GREEN保护“算法开放、任意argv、正式评测权限和旧模型完整性”等已具备行为。

额外确认：现有token子串脱敏会误删max_tokens/tokenizer_name等普通配置，还可能把两次不同MAX_TOKENS请求误认成幂等重试。这次已写RED约束，但未提前修产品代码。

## CI/CD

新增Ubuntu/macOS Python3.12契约矩阵，以及真实Ray CPU新功能契约job。各自留JUnit/失败注解；不使用continue-on-error。release/simulation复用全量verify，RED期间按预期阻断交付，原有门禁不移除。

测试清单位于`contracts/flexible_training/`与`contracts/flexible_training_ray/`，基线JSON位于`reports/flexible-training-red.json`。任务拆分见[tasks.md](tasks.md)。本轮交付到这里停止，等用户审阅授权后再把RED逐项转GREEN。
