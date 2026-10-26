# 本地使用（CPU 模拟版）

已实现 CLI、后台服务、持久任务/事件、数据与模型快照、逐题评测、团队笔记和会话记录。Slurm/Kubernetes 是可配置适配器，仅用外部命令/API 模拟验证过；没有在真实集群上运行。

## 安装与一次完整演示

```sh
cd /Users/wzk/Desktop/rsi-red
source .venv/bin/activate
rsi --help
rsi demo --output .rsi/my-first-campaign --json
```

目标目录应为新的目录（不要覆盖已有模型）。演示会真正启动5个 CPU 子进程，执行 SFT、GRPO、两步环境 RL、on-policy 自蒸馏、模型合并，并实际推断小型线性二分类模型。
`report.json` 保存任务、评测与 DAG；state/research.sqlite 保存所有事件与实体，blobs 保存不可变内容。
这些模型是 JSON 编码的 `simulation-linear-v1`，不是 transformers/torch 权重。模型文件名 model.bin 是模拟格式，不能拿去给 vLLM 加载。二分类得分不表示大模型能力。

## 启动持续服务

```sh
rsi init --output .rsi/my-service --json
python -m rsi_red.server --config .rsi/my-service/service.json --ready-file .rsi/my-service/ready.json
```

另一个终端：

```sh
cd /Users/wzk/Desktop/rsi-red
source .venv/bin/activate
export RSI_ENDPOINT=http://127.0.0.1:8787
export RSI_TOKEN_FILE="$PWD/.rsi/my-service/token"
rsi doctor --json
rsi campaign list --json
```

本次已经生成 `.rsi/local/`，可以直接用其 service.json/token，勿重复 init 同一目录。凭证文件为0600、目录0700，不应提交 Git。默认只绑定 loopback；远程访问使用 SSH 隧道或受控 TLS 入口，不把开发服务直接暴露公网。

## Agent 调用方式

### 群岛看板

```sh
rsi kanban --demo                  # 完整示意交互，不提交任务，不需要服务凭证
rsi kanban                        # 使用以上环境变量连接服务并自动打开浏览器
rsi kanban --port 8791 --no-open    # 仅输出地址；Ctrl-C 退出看板
```

默认地址 http://127.0.0.1:8790，--port 0 可自动分配空闲端口。看板进程在前台运行，退出不会关闭控制服务或取消训练。
点击岛屿显示项目ID、当前任务和所选时刻前的事件；点击示意桥展示假设、方法、贡献边界与下一步对照。
拖动时间线仅过滤事件与示意桥，任务列表明确保持当前快照，不声称完整重建历史模型状态。
刷新按钮重新读取服务。断线或权限错误会清除旧画面并显示错误；不会自动切换为示意数据。
真实模式只读取当前身份可访问的 campaign/job/events。真实方法桥与评测曲线尚未接入，保持空状态。
--demo 始终有“示意数据”标注，RSI_TOKEN_FILE 即使指向失效路径也不影响演示模式。

### 任务与数据

`request` 通用入口支持所有 contract.md 中的操作，专用命令是其便捷封装，经过同一鉴权与校验。

```sh
rsi request campaign.list --payload '{}' --json
rsi job submit --campaign <campaign-id> --spec train.json --idempotency-key my-experiment --json
rsi job show <job-id> --json
rsi job logs <job-id> --limit 100 --json
rsi eval submit --spec evaluate.json --json
rsi eval samples <eval-id> --filter truncated --limit 20 --json
rsi events --campaign <campaign-id> --after <cursor> --wait 30 --json
rsi starter create --method grpo --output .rsi/editable-grpo --json
```

train.json 的完整可执行例子可在 demo 的 recipes/、归档及数据库 job.spec 中查看。entrypoint 是 argv 数组；code 支持单文件或 tar/tar.gz 快照，校验摘要后持久化，运行使用冻结副本。tar 包可带多模块与配置，不允许 symlink/hardlink/路径逃逸。集群容器仍需自行提供相同共享路径挂载。

数据/模型导入路径与 fetch 输出路径位于**服务端**文件系统，不是远程客户端自动上传/下载协议。第一版按操作者信任的本地/共享目录使用。当前服务、训练和模拟 evaluator 以同一用户运行，CLI 角色判断不等于 Athanor 的沙箱隔离；任意训练程序可能访问该用户的其他文件。生产多租户/隐藏集保护须使用独立执行身份、存储和网络边界，当前不声称具备。

模型注册校验文件清单与内容摘要，但不解析大模型张量格式；真实部署需要推理引擎加载验收。原始 env 凭证字段从任务环境与持久配置中移除，返回 dropped_secret_env_keys，不负责自动注入 secret。真实凭证应由操作者在运行环境/集群 secret 中管理，不能把敏感值塞入命令行或自由文本日志。

## 会话恢复与通知

```sh
rsi transcript append --spec transcript-chunk.json --json
rsi transcript show --spec transcript-query.json --json
rsi watch --campaign <campaign-id> --cursor-file .rsi/watch-cursor.json \
  --command '["/absolute/path/to/agent-wakeup-handler"]'
```

append 格式：campaign_id、session_id、sequence（从0递增）、text。show 格式：campaign_id、session_id。
捕获内容需 agent harness 主动提交，工具不会从 Codex/Claude 私有状态凭空读取会话。团队成员可读，同一会话只能由原作者追加；同序号不同文本报冲突。

通知 handler 从 stdin 收到事件 JSON，通过 argv 执行，无 shell 字符串拼接。成功后写游标，失败保留游标；交付语义为至少一次，handler 应按事件 ID 幂等。它是可接入 harness 的通知接口，本次验证了子进程 handler，未把通知发送到真实 Codex 会话。

## 资源与失败恢复

服务关闭不会取消 worker；local CPU backend 使用独立进程与 OS 文件锁，结果文件持久化。重启服务可找回原任务。控制面同时只有一个进程能持有同一 state 的锁。

提交超时后先按 submission_key 找回调度任务；无法确认的请求保持未决，**不盲目重发**。外部调度器若没有记录/记录过期，需操作者核查后处理，当前不保证这种模糊窗口自动恢复。Slurm 查询范围为最近7天，超过范围需要调整适配器/现场恢复。

预算按 GPU 占用时长而非有效计算量；运行中的预留不重复计入已消耗时间。local CPU 不申请 GPU，gpus 必须为0。实际 CPU 配额、磁盘额度、日志轮转和 Kubernetes 的精细计费需部署层补齐。

## 发布与验证

- `python -m pytest tests`：所有本地自动化测试。
- `python -m ruff check .`：静态检查。
- `python -m build`：wheel/sdist。
- CI：PR/main，四组 Python/OS 测试，失败保留 JUnit；通过后用干净 venv 安装 wheel，运行完整 demo。
- CD：v* 标签重新验证后创建带校验和的草稿 GitHub Release；simulation.yml 可手动运行模拟交付并保存报告。
- 本次未推送、未触发 GitHub Actions、未创建远端 Release、未部署集群。

## Ray 执行环境

现已新增 Ray Jobs 后端和独立真实 CPU Ray 集成门禁；见 [Ray运行说明](ray.md)。它可运行在已有基础设施上，不要求先拿到 Slurm/Kubernetes 管理权限。

## 平级会话、recipe 与 GPU 看板

四个研究会话使用各自 researcher 凭证和工作区；不从主会话生成子 agent 代替。当前服务按身份记录作者，尚无target会话注册/心跳/自动唤醒。使用相同operator凭证的四个会话不会变成四个独立作者。

```sh
rsi recipe create --spec recipe.json --json
rsi recipe list --campaign CAMPAIGN_ID --json
rsi recipe show RECIPE_ID --json
rsi recipe update --spec observation.json --json
rsi resource show --json
```

recipe.json包含campaign_id/title/hypothesis/method/datasets/parents，可选parameters；数据和父模型使用已登记ID。创建后方法与输入保持不可变；更改配方创建新记录。observation.json包含id/state/observation，state为planned/trying/completed/abandoned，只有作者可追加；上报状态不证明模型收益。job spec带recipe_id时校验同作者、同campaign、输入一致，并自动在recipe详情列出任务。

kanban按身份显示recipe、实际关联任务状态与未结束任务GPU申请量（含排队，不是实际分配）。当前卡片不随历史时间线回退。页面可见时每10秒刷新。

operator可在service.json加入 `"telemetry": {"backend": "nvidia-smi"}`，在有GPU的控制服务节点采集利用率%、显存MiB、功耗W与时间。Mac默认不采样。该实现只覆盖服务所在节点，不包含远程多节点汇总或job→GPU UUID归属；看板不把全节点指标归给某个agent。researcher无权读取全节点指标，会显示“资源受限”。N/A为未知、30秒前采样标过期。

可调用项目技能 `$rsi-research` 整理自然语言目标和配置；技能文件位于 .agents/skills/rsi-research/SKILL.md，本机已链接到 ~/.codex/skills/rsi-research。其他harness需使用自身支持的技能发现路径。真实训练入口、evaluator和会话管理缺失时，技能只完成配置与预检，不冒充已经自动开展研究。


## 独立评测审核

使用`rsi eval model MODEL_ID`读取不含考题的开发汇总；`rsi audit`提供配置、候选检查、疑点、反馈与独立确认。训练者的`eval.samples`现被拒绝，operator仍可诊断。五会话配置、精确匹配检查的适用范围和当前缺口见[独立审核](evaluation-integrity.md)。
