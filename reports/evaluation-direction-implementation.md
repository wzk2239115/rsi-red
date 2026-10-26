# 评测方向实现与验收

2026-10-26，用户在spec/RED/CI审阅后授权编码。方向机制已实现；没有登记任何真实bench目标，没有重启原服务或启动GPU任务。

- direction.authorize 仅operator配置通道可用，记录完整task/metric/direction、人的目标说明、身份/时间和来源digest；注册/派生精确核对，研究者和审核者不能自授。
- 新协议无方向即拒绝，显式默认可由item覆盖、同task一致。protocol.derive服务端保留题库/采样，只改已授权元数据，新ID/digest，旧记录不改。
- raw证据保留，minimize=1-raw、maximize=raw。task_mean、同协议配对bootstrap、重复均分、只读候选推荐统一使用目标分；审核器继续核对raw。
- campaign.select 在当前协议和审核资格下推荐，仍须显式submit。eval.list、protocol.show、eval.compare和看板仅公开安全开发汇总，不向研究者返回题目/答案。
- 研究技能已更新（个人安装为仓库符号链接，同步生效），人的明确自然语言目标可以直接登记；含糊目标先澄清，开发授权不能扩展为方向授权。

验收：新增方向契约50项通过；本地已实现功能与新契约合计315项通过；真实Ray CPU 15项通过；ruff、OpenSpec strict、技能格式验证、构建、干净wheel安装/实际CPU执行/演示通过。原研究层32项RED仍存在，CI/CD保留阻断。

远端[CI run40332953479](https://github.com/wzk2239115/rsi-red/actions/runs/40332953479)验证提交e5dc6b1：12个已实现门禁全部通过，包括Ubuntu/macOS方向契约、Python3.12/3.13基础测试和两组真实Ray CPU；仅既有research-islands失败，不能称整库发布绿色。最后交付提交仅更新报告与任务状态。

此前两轮CI有Ray启动/提交连接失败，本地完整15项及单独重启用例通过；缩短JUnit注解到末尾4000字符以保留异常，再将测试夹具HTTP上限从2秒对齐生产默认10秒，第三轮通过。本次未改生产调度语义、任务重放或任何断言；SDK错误被脱敏，不能据此断言首次故障的唯一根因。完整CI历史在同名JSON中。

最初30项RED报告未改写；实施前扩展到49项，其中44 RED、5项原始评分边界已通过；随后加实际CLI子进程/HTTP/看板链路验收至50项。测试修正一处：看板fixture回调应像真实客户端一样把权限拒绝转换为RuntimeError，不能用rig.ok断言截断权限分支；产品权限没有放宽。

两候选受控分与显式提交证据见evaluation-direction-smoke.json。六组自然语言由当前harness人工解释并仅操作临时测试fixture，见evaluation-direction-intent-review.json；不是独立模型benchmark。浏览器截图evaluation-direction-ui.png显示ASR↓、AUROC↑、raw与目标分。

边界：本次CPU分数为fixture，无真实模型推理/H100成绩；operator凭证是配置授权边界，无法从文字本身证明真人来源；同Unix用户的物理隔离、真实安全评测器和已知重复评测seed问题均未被本变更解决。方向改变使用新协议/new campaign，不自动重置现有预算或迁移审核pass。

用法见[完整方向文档](../docs/evaluation-direction.md)。
