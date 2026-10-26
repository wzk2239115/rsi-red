# rsi-red：面向 agent 的 AutoPostTrain CLI 讨论稿

状态：已实现 CPU 模拟版，持续测试验证中。日期：2026-10-26。

用户后续决策：优先对齐 Athanor 系统机制；已完成先写失败测试，并统一授权实现。用户暂不提供集群信息，明确授权先模拟执行。
已形成 `openspec/changes/athanor-core-test-first/`，其中需求/设计与 `docs/contract.md` 是当前核心接口依据，以下内容保留为研究背景；冲突处以该 change 和后续用户指示为准。
最初67项红色测试保留；现已扩展测试并实现 CPU 模拟训练、事件通知和团队会话记录。真实 LLM/GPU、实际 agent harness 唤醒及操作系统隔离未验收。当前运行说明见 docs/usage.md。

## 1. 我们要做什么

让 Codex、Claude Code 或其他能调用 shell 的研究 agent，通过一个 CLI 在已有 GPU 集群上做后训练研究：查看数据、编写训练程序、提交实验、评测 checkpoint、检查错误样本、比较结果，再决定下一次实验。人的职责是设定目标、资源预算和评测规则。

用户已明确：有 Slurm 或 Kubernetes 集群。尚未明确：具体调度系统、模型规模、训练框架、数据平台及首个评测任务。

命令暂名 `rsi`，以下全部是拟议接口，不是已经可运行的命令。AutoPostTrain 是本阶段目标；工具可帮助研究其他模型，不等于已经实现递归自我改进（RSI）。

## 2. 从 Athanor 取什么，不照搬什么

依据：Athanor: An Agent-Native System for Autonomous Post-Training Research，arXiv:2610.21055v1，2026-10-15。
原文：https://arxiv.org/abs/2610.21055 。本次规划阅读了已下载的英文 PDF，重点是正文 §2–§3、§4.1、§5–§8、附录 A；下列页码是原论文页码。

| 论文中的事实 | 对我们的工程启发（建议） |
| --- | --- |
| §3、图2、算法1（p6–7）：研究者和环境服务并发运行；job / eval / data / artifact 是主要操作 | CLI 提供原子操作，后台服务执行；不要把研究流程固定成模板流水线 |
| §3.3、附录 A（p7、24–25）：任务归服务所有，agent 会话结束后仍运行；状态变化写入记录并通知 agent | 提交立即返回 ID；断线可恢复；提供增量事件接口和可选唤醒适配器 |
| 附录 A：请求先写 journal，再执行；checkpoint 关联代码、数据、父模型、任务和评测 | 一等公民是可追溯的实验与模型产物，不只是 shell 命令和日志 |
| §3.2、附录 A：冻结 evaluator、开发集反馈和隐藏最终评测，去污染服务位于沙箱外 | 训练权限与可信评测权限分开，最终评测不成为日常调参接口 |
| §5.1、Trace 1（p13）：agent 从截断答案中发现贪心重复循环，修改 rollout | 必须支持逐题输出、终止原因和诊断，不应只返回排行榜总分 |
| §5.2（p13–15）：团队共享模型和证据，checkpoint 可以有多个父节点 | 模型血缘是 DAG，支持跨 agent 引用；合并时保留全部来源 |
| §5.3–5.4（p14–15）：团队过早收敛于同一数据源，较少验证答案正确性 | 数据工具应提供抽样、质量检查、配比统计和对照证据；不替 agent 自动决定“最佳数据” |
| §4.1–4.2、图8a（p8–9、16）：一次评测会有噪声，筛选最优模型还会选择到噪声 | 保存完整协议，支持重复评测、同题配对比较和分项回归检查 |

论文实验是一种受控设置：禁止调用外部教师，但使用了包含教师蒸馏内容的公开数据。我们的工具应能配置教师模型使用策略，不能把“没有调用教师 API”说成“没有使用教师知识”。

论文只验证了一次 campaign、一个基础模型和一种研究 agent；四个合作 agent 不是四次独立复现实验。不要把它的模型增益、104 小时或利用率当成本项目承诺。其最终测量还改变了输出预算与采样设置，我们应把这类变更记成新协议，不能混进原排行榜。

## 3. 三种角色及边界

1. **研究 agent**：决定假设、数据配比、算法、代码、超参、父 checkpoint、是否继续以及提交哪个模型。能读开发评测与团队共享证据。
2. **执行环境**：校验请求、交给调度器、持久化状态、收集日志与模型、执行冻结评测、计算资源用量。基础设施可以排队和分配资源，但不替 agent 选择研究方向。
3. **操作者**：设置 campaign、凭证、预算、可用数据与模型、评测协议及最终评测权限；处理集群故障。操作也留记录。

Mac 是控制端，Linux GPU 集群是执行端。CLI 只负责交互并不保证任务存活，需独立服务与调度器作业。把配置文件藏起来不能构成隐藏评测：真实保护需要不同身份、存储权限和执行边界；同一个 agent 若持有集群管理员凭证，就不能声称评测已对它隔离。

## 4. 能力范围与优先级

| 能力 | 第一阶段需要的最小形态 | 后续扩展 |
| --- | --- | --- |
| Campaign | 基础模型、开发评测协议、预算、运行状态、提交记录 | 多团队、更多策略与跨 campaign 汇总 |
| 集群任务 | 单个实际后端：提交、查询、日志、取消、依赖、超时、资源申请 | 第二后端、弹性、多集群 |
| 训练入口 | 自定义 entrypoint + 代码快照/镜像 + 输入引用；一个 SFT starter | GRPO、环境 RL、自蒸馏、合并等 starter |
| 数据 | 导入、版本快照、schema 检查、抽样、统计、转换后注册 | 质量验证器、生成/验证工作流、更复杂去污染 |
| 模型产物 | 注册、校验、拉取/引用、父节点和产物清单 | 高效跨节点分发、更多模型格式 |
| 可信评测 | 一个任务族，冻结版本，逐题反馈，协议可追溯 | 多能力套件、重复评测、独立最终评测 |
| 研究记录 | 请求、状态、结果、代码/数据/模型血缘、研究笔记 | 可选会话 transcript 接入和图形浏览 |
| 事件与恢复 | 增量查询/长轮询、稳定事件 ID、服务重启协调 | agent harness 主动唤醒、webhook |
| 成本 | 资源预留、任务时限、GPU 时间、预算核算 | 精细利用率、agent token 成本、价格模型 |

这里的训练入口不是重新写一个训练框架。训练框架如 verl、TRL 或其他项目可通过 adapter 或 entrypoint 接入；先确定一个真实可用的组合。Athanor 的 starter 用了 verl 和 mergekit，这不意味着我们必须绑定这两者。

## 5. 拟议 CLI

统一支持 `--json`，stdout 输出稳定结构，诊断写 stderr；不用交互式确认来阻塞 agent 的正常任务。变更、取消、清理等动作依权限和显式参数处理。

```sh
# 配置与资源发现
rsi doctor --json
rsi cluster capabilities --json
rsi campaign create --config campaign.yaml --json
rsi campaign show cp_001 --json

# 数据不只有下载：快照、检查、处理、再注册
rsi data import --source <uri> --revision <immutable-revision> --json
rsi data inspect ds_001 --json
rsi data sample ds_001 --count 10 --seed 42 --json
rsi data check ds_001 --profile sft --json
rsi data decontaminate ds_001 --policy policy_001 --json

# 实验配置声明输入/资源；训练程序仍可由 agent 自由编写
rsi job submit --campaign cp_001 --spec train.yaml --idempotency-key exp_001 --json
rsi job show job_001 --json
rsi job logs job_001 --tail 100 --json
rsi job cancel job_001 --json

# 评测返回 eval ID，异步执行；逐题输出与汇总分离
rsi eval submit --campaign cp_001 --model model_001 --protocol dev_v1 --json
rsi eval show eval_001 --json
rsi eval samples eval_001 --filter truncated --limit 20 --json
rsi eval compare eval_001 eval_002 --json

# 正在训练的目录不能直接当成已完成模型
rsi artifact register --manifest model.json --json
rsi artifact fetch model_001 --output ./models/model_001 --json
rsi artifact lineage model_001 --json

# agent 会话恢复后可从事件游标和笔记恢复上下文
rsi events --campaign cp_001 --after evt_100 --wait 30 --json
rsi note add --campaign cp_001 --file findings.md --json
rsi campaign submit cp_001 --model model_001 --json
```

`campaign submit` 表示选定研究结果，不表示部署上线。最终评测由操作者侧执行，不提供普通 researcher 可调用的隐藏集接口。命令分组、ID 前缀、配置格式都可讨论。

建议 JSON 统一包含 `schema_version`、`request_id`、`data`、`error`；错误需有稳定错误码和 `retryable`，不能仅靠自然语言判断。大日志、逐题文件和权重返回引用与分页，避免把整个数据集塞进 agent 上下文。

## 6. 实验记录：能否解释一个分数来自哪里

最小对象：Campaign、DatasetSnapshot、Experiment、Job、Artifact/Model、Evaluation、Event、Note。

**Experiment 是逻辑研究尝试，Job 是一次执行尝试**，两者分开：重试/OOM/节点抢占不应伪装成新的研究结论。研究动机与假设可写笔记并链接实验，不强制 agent 为每次提交填长表。

每个实验至少冻结：

- 输入：基础/父模型的不可变引用与 digest；全部训练数据快照及变换配方/实际选择样本清单。
- 程序：Git commit 和未提交改动快照，或内容哈希代码包；容器 image digest、依赖锁、启动命令与非敏感配置。只有 commit 不够覆盖 agent 的未提交修改。
- 资源：GPU 型号/数量/显存、CPU、RAM、时限、框架、随机性配置与分布式参数。
- 结果：scheduler job ID、每次 attempt、终态、退出原因、日志/曲线、输出清单、成本与评测引用。

模型 lineage 支持单父训练、继续训练、多父合并、蒸馏的学生/教师来源。蒸馏数据和教师模型是明确依赖，不能只连一个“上一步任务”。模型目录保存 tokenizer、配置和分片清单，完成上传并校验后原子发布，半成品不能出现在可评测模型池。

训练 loss、吞吐和显存用于诊断，不是跨 SFT、RL、蒸馏阶段通用的能力分数。研究笔记应区分观察、猜测和对照实验结论。日志与配置持久化时剔除密钥；会话 transcript 需要接入 agent harness 才能捕获，不能仅靠 CLI 声称已记录完整推理过程。

## 7. 集群执行与故障语义

建议结构：`agent → CLI → control service → scheduler adapter → GPU job`。评测、数据和产物服务共享可追溯 ID；初版可以同一代码库部署，不必一开始拆成微服务。

- Slurm adapter 负责 sbatch/squeue/sacct/scancel 等映射；Kubernetes adapter 负责 Job/Pod 或现有训练 operator 的映射。先选一个，沿用已有调度与资源配额。
- 状态建议：accepted → queued → running → succeeded / failed / cancelled / timed_out；上传、评测依赖另有显式状态。OOM、节点丢失、抢占、用户取消要能区分。
- 后台进程持续 reconcile 调度器状态，不能靠 agent 自己轮询维持执行。先持久化请求再创建作业，使用 submission token/调度标签找回“已提交但响应丢失”的任务。
- 相同幂等键和相同请求返回原 job；同键不同请求报冲突，避免超时重试多烧一份 GPU。
- 只有确定可恢复的基础设施错误才按策略重试；训练异常、OOM、错误数据返回证据。训练续跑必须确认框架支持且存在完整 checkpoint，不能承诺透明恢复。
- 取消、任务超时和预算封顶应清理关联训练进程、评测推理服务和资源申请。记录取消发生时已有的费用与产物。
- 配额包括正在运行和已接受/排队任务的预留，防止并发提交绕过预算。记录实际 GPU 时长；占用率与有效计算利用率分别统计。没有价格来源时只报资源用量，不伪造费用。
- 初版元数据数据库与共享存储按现有基础设施选型；数据库是权威状态，产物内容不可变，事件可重放。Mac 本地磁盘不能成为集群唯一依赖。

## 8. 数据与可信评测

### 数据

数据集记录源地址、revision、许可证信息、内容摘要、split、schema、行数/长度分布和处理版本。原始、转换后、混合后分别有快照。公开训练集不自动等于可以无条件复用，工具记录来源而不推断授权。

SFT 检查 messages/roles、空回答、chat template、截断比例；可验证 RL 检查问题/标准答案/评分函数能否配对，抽查答案正确性。每种任务用自己的验证器，不要只做格式检查。

去污染在所有训练入口生效，包括公共数据、自建数据和自生成数据；每次输出新快照与报告。Athanor 附录 A 使用规范化后的 13-word shingles 和“覆盖至少一半题目 shingles”的规则，短于 13 词的题目不能由此检出。它不能证明语义无污染，中文/代码还需单独设计匹配策略。

若要对隐藏集去污染，匹配只能在受保护服务中完成；研究端不返回隐藏样本、逐题命中或高频探测能力。去污染状态明确标记为未检查、通过指定检查或失败，不允许模拟检查输出“clean”。

### 评测

冻结协议至少包括：题目版本与 ID、评测代码/容器 digest、prompt、chat template、tokenizer、采样参数、输出长度、评分规则、推理引擎及版本、重复策略、聚合规则。修改任何影响结果的项产生新协议版本。

开发评测需要提供：分任务总分、逐题答案与得分、输入/输出 token、截断/超时/重复循环/格式错误、必要的执行轨迹及耗时。对齐样本和协议才能做比较；跨协议结果可以展示，但不能当作控制变量一致的改进。

先做低成本 smoke eval，再做完整开发评测；二者结果分开命名，不能互相替代。候选最优模型重复评测，保存每次结果。Athanor 的 seed 是完整评测重复，不是独立训练；我们的 schema 显式分开 `training_seed`、`eval_seed` 和 `repeat_index`。

总分之外必须显示各能力变化与回归，避免“平均分涨了但主要能力下降”。不确定性按任务与样本依赖结构选择估计方法，注明计算方式；置信区间含零不能写成已证明等价。

最终评测与研究反馈隔离，提交后由操作者测量。若每轮结果都回传 agent，那就是新的开发集，不能再声称它是封闭最终评测。

## 9. 第一条真实闭环及验收建议

按集群现有条件确认一套模型、数据、训练框架和任务后再实现：

1. 在同一冻结开发协议下测基础模型与一个可比基线，确认推理和评分可靠。
2. 注册小规模训练数据快照，检查格式并执行指定去污染规则。
3. agent 写一个短程 SFT 实验，在选定的 Slurm/Kubernetes 后端提交。
4. 关闭 CLI/agent 会话，再打开并查询同一任务；不会重复提交，状态与日志仍在。
5. 训练产物校验并注册，再异步评测，得到逐题结果和分项比较。
6. 从一个分数追溯到完整代码快照、数据和模型来源；记录一份基于具体错误样本的后续假设。
7. 至少验证一次提交响应丢失、一次训练失败、一次取消和一次服务重启，确认终态与资源账目一致。
8. 人工检查 researcher 身份不能读取/修改受保护评测资源；未部署这一权限边界时，只称原型。

这一阶段成功的标准是闭环可靠、证据可追溯，不是保证训练后必涨分。第二阶段再增加 GRPO/蒸馏/合并入口、多 agent 团队记录、唤醒集成和独立最终评测，按实际需求拆成 OpenSpec changes。

## 10. 需要和用户讨论的决策

1. **先接哪个后端？** 现有的是 Slurm、Kubernetes，还是两个都有？已有镜像/训练 operator/共享存储能否复用？
2. **首个研究目标？** 通用指令/推理模型，还是安全领域模型？具体模型、GPU 型号和可用预算是什么？
3. **谁负责长期运行 agent？** 外部 Codex/Claude Code 调用 CLI，还是本工具还要托管 agent 会话？建议先支持外部 agent，后台只托管实验；事件接口为后续主动唤醒留扩展点。
4. **现有训练和评测栈？** 已有 verl/TRL/自研脚本和任务集应优先接入。没有可验证目标时，先设计评测，不能仅凭 loss 自动选模型。
5. **研究权限？** 是否允许教师 API、额外模型下载、联网数据导入；最终评测谁来保管？这些是可配置 campaign 规则，不是把论文限制硬编码进产品。

如果首个场景是安全：可考虑可验证的漏洞定位/补丁或内容分类任务。EDR/NDR 需定义带来源/时间切分的数据和误报约束；漏洞利用类训练需明确可复现隔离环境与评分。以上是迁移建议，Athanor 并未验证这些领域。

当前建议：先定后端与第一项评测能力，完成一次短程 SFT → 完整产物 → 可信评测 → 错误分析的真实闭环，再扩大算法空间。

2026-10-26 新增决策：用户希望 CI 内启动真实 Ray 环境；对应 change 为 ray-runtime-integration，增加 Ray Jobs 后端及 CPU 运行时集成测试，生产集群与 GPU 边界仍独立验收。

2026-10-26 新增研究层规划：用户提出方法岛屿与桥梁，并要求继续spec、测试先行与CI/CD。当前change为research-islands-and-inspiration，先交付32项RED契约和8张灵感卡，尚未实现新operation或自动训练。详见docs/research-islands.md。

2026-10-26 看板入口确认：用户要求群岛以 `rsi kanban` 启动；规范新增 research-kanban，2项 CLI RED 契约加入现有研究层 CI。规划默认本地启动并打开浏览器，支持 --port、--no-open、--demo；当前尚不可调用，视觉参考 design/archipelago-v1/dashboard.png。

2026-10-26 用户授权实现与推送GitHub：rsi kanban 已实现只读本地看板，真实模式展示有权限的campaign、job、events；演示模式提供群岛/桥证据/时间线。真实方法桥与评测曲线尚未接入；当前任务与历史事件明确分开展示。134项已实现测试通过，新研究层32项RED仍保留。图形为原生SVG/CSS，不依赖外部前端库。

2026-10-26 用户最终确定四个平级harness会话分别对应四个agent，不采用主/子agent。新增peer-recipe-monitoring change：recipe记录/追加观察/同作者任务绑定、按身份的看板卡片、未结束任务GPU申请量、可选控制服务节点nvidia-smi实测。真实多节点GPU归属、target会话管理和隔离未接入。rsi-research技能整理目标/基座/数据/评测/预算配置，不把skill当成后台进程或声称四个研究会话已启动。

2026-10-26 用户提供H100 Ray接入故障报告，设备暂不可访问。ray-runtime-reliability修复静默重试、显式Python、runtime_env诊断、客户端认证文件与独立测试head；只读重试与未知提交不重放分开。节点重启丢作业不等于控制面重启恢复。GPU秒数保留driver估算范围，cluster_image标签不声称验证真实容器。报告的GCS下载失败和“读取token改变head认证”因果需现场复核。

2026-10-26 用户接受workspace-only基础分离，优先在现有8卡容器跑通；再次要求先spec、CI/CD，再编码。lightweight-ray-peers本轮仅spec+4项RED+CI门禁；此前未提交dev/cli实现已撤回，草稿放.rsi/deferred-ray-peer-profile，不合入产品。该profile当前尚不可调用。

2026-10-26 用户授权实现lightweight-ray-peers，按已推送spec/CI门禁开始：新增7项边界后共11项部署契约先RED；实现离线profile，四套身份/工作与运行目录、显式Ray环境、未配置evaluator、无启动/训练副作用。GPU容器用法见docs/ray-peers.md，尚未现场8卡验收。

2026-10-26 用户提出独立agent审计其他四个agent模型的reward hacking。evaluation-integrity-auditor先spec+8项RED+CI/CD门禁，不编码。第五个平级auditor只提疑点和反例，可信checker及提交门禁由服务端执行；首版开发评测、不开放隐藏反馈。相同Unix用户基础分离不能提供抗恶意篡改安全保证。

2026-10-26 用户要求训练者接收审计疑点/判决：补充evaluation-integrity-auditor的反馈流、事件、接收身份独立ack和游标恢复规范及5项RED。默认同共享campaign训练者可读，仅开发反馈；真实harness投递仍需target适配器，不能把事件存在当作会话已收到。

2026-10-26 用户授权实现独立审核并要求CLI查询评测信息时不泄题。evaluation-integrity-auditor现已实现策略、异步case、显式exact_match可信复核、候选门禁、固定类别反馈/游标/独立ack、看板与可选第五auditor离线身份；protocol.show收紧为元数据、eval.samples改operator专用，模型报告仅开发汇总。格式扰动/数据溯源执行器仍unavailable，不伪造通过。用户确认本版优先打磨infra，任意文件读取/物理隔离留后续，不作为当前前置。真实harness投递和GPU检查器仍独立待验收。详见docs/evaluation-integrity.md。

2026-10-26 用户要求训练足够开放，“除作弊外允许自由探索”，并明确本轮只写spec、CI/CD，审阅后另行授权编码。新增flexible-training-execution：无方法白名单、job.validate、逐任务依赖与Python、普通训练参数保真、通用kind与运行期输出来源。第一阶段聚焦现有单节点8卡容器；多节点与受管动态Ray资源需后续单独spec。新接口尚未实现，src保持未修改；规划入口见该change/review.md，RED基线见reports/flexible-training-red.json。
