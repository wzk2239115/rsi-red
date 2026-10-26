# v1 行为与接口契约

此文件定义已实现且由测试约束的边界。所有 ID/digest 从返回值获取，测试不依赖数据库表结构或私有方法。

## 控制服务

控制面 Python 3.12+。`rsi_red.service.ResearchService(root, scheduler, evaluator, clock, principals)` 可用关键字参数构造，提供：

- `dispatch(token=..., operation=..., payload={...})`：经过鉴权与校验的同步请求处理，耗时任务仅入队。
- `reconcile()`：服务后台循环的一轮；执行 ready work、协调外部状态并记录结果，不选择研究方向。
- `close()`：关闭控制面连接，不取消训练。

这是测试可直接调用的应用边界，不是网络鉴权部署方案。production principals 来源不能由客户端请求自带；开发 token map 只用于测试，部署必须由操作者安全配置。

每次返回 `{schema_version: "1", request_id: nonempty-string, data: object|null, error: null|{code, message, retryable}}`。
成功 error=null，失败 data=null。operation/payload 的字段见 tests/support.py 与各断言。未知 operation 返回 UNKNOWN_OPERATION，未知实体 NOT_FOUND，资源越权 FORBIDDEN。

## 关键操作和字段

| 操作 | 输入 | 输出关键字段 |
| --- | --- | --- |
| campaign.create | name,members,gpu_hours_budget,protocol_id,require_decontamination | id |
| campaign.show | id | id,usage{gpu_seconds,reserved_gpu_seconds} |
| campaign.submit | id,model_id | model_id（不触发部署/最终评测） |
| job.submit | campaign_id,idempotency_key,entrypoint,code,image,datasets,parents,resources,training_seed；可选 depends_on,env | id,experiment_id,state |
| job.show | id | id,state,reason,scheduler_id,spec,attempt_count |
| job.cancel | id | id,state |
| data.import | campaign_id,path,source,revision,license | id |
| data.inspect | id | id,digest,rows,decontamination{status} |
| data.sample | id,count,seed | items |
| data.check | id,profile | valid,invalid_rows,issues[{row,...}] |
| data.decontaminate | id,campaign_id | output_dataset_id,removed_count（不泄露隐藏题） |
| artifact.register | campaign_id,path,files[{path,sha256}],parents,kind,provenance | id |
| artifact.show | id | id,digest,files |
| artifact.fetch | id,output | 完整下载并校验 |
| artifact.lineage | id | nodes[{id}],edges[{parent,child}] |
| protocol.register | name,visibility,items,evaluator_digest,sampling,aggregation,eval_seed | id,digest |
| protocol.show | id | id,digest,spec |
| protocol.list | campaign_id | items（普通身份无隐藏集） |
| eval.submit | campaign_id,model_id,protocol_id | id,state |
| eval.show | id | id,state,model_id,model_digest,protocol_digest,score,task_scores |
| eval.samples | id,limit,filter? | items，filter=truncated 表示 finish_reason=length |
| eval.compare | left,right | 同协议/同题配对比较；跨协议 PROTOCOL_MISMATCH |
| events.list | campaign_id,after?,limit | items[{id,type,entity_id,...}] |
| note.add / note.show | campaign_id,text,evidence_ids / id | id,text,author,evidence_ids |

job resources 包含 gpus、walltime_seconds；code 包含内容 digest、uri；生产 image 必须可追溯到 digest。local CPU 进程测试允许 gpus=0 且无镜像，不能用作生产 GPU 配置。
数据 snapshot 与模型文件必须复制/持久引用内容，原文件后续改变不改变已注册实体；摘要依据实际内容计算。模型 fixture 故意不是真实权重，完整性检查是清单/必需文件/校验和，不宣称解析权重或推理成功。

幂等键按 campaign 作用域生效，同键同有效请求返回同 job；不同有效请求返回 IDEMPOTENCY_CONFLICT。保密字段不能明文持久化/回显；真实 secret 通过引用注入，不在普通 job.spec、journal 或日志暴露。

## 外部 adapter 边界

scheduler: `submit(request, submission_key=...) -> id`、`find(submission_key) -> id|null`、`status(id) -> {state,reason,gpu_seconds,...}`、`cancel(id)`、`logs(id, offset=0, limit=100)`。
GPU 秒是 GPU 数 × 占用秒。相同状态多次观察不能多次计费。恢复先查 submission_key，不能 timeout 后盲目 submit。

- Slurm: `rsi_red.schedulers.slurm.SlurmScheduler(runner=...)`，runner 是 subprocess.run 形态的可注入外部命令执行器；用参数数组，不用 shell=True；squeue 无记录要查询 sacct，不能判断完成。
- Kubernetes: `rsi_red.schedulers.kubernetes.KubernetesScheduler(api=..., namespace=...)`，api 是 BatchV1Api 兼容边界；保留 argv，设置 GPU limit、deadline、幂等 label，默认不盲目重试，删除作业需级联。
- `rsi_red.schedulers.create_scheduler(config)` 对不支持后端直接报错。
- evaluator: `evaluate(model, protocol) -> {items:[{id,task,answer,score,finish_reason,output_tokens}]}`。冻结协议确定 task_mean 聚合；测试每项得分 0/1，平均为 0.5。测试 evaluator 是纯 fixture，真实推理另验。
- clock 是可调用时间源，测试用可控时钟。预算预留须在接受请求的事务中完成。

纯数据算法 `rsi_red.decontamination.filter_rows(rows, benchmark_texts, text_field, shingle_size, overlap_threshold)` 返回 rows、removed_count、uncovered_items、semantic_contamination_free=false。参考论文的规则不覆盖语义重复，短题必须披露未覆盖。

## CLI 与进程

`python -m rsi_red` 与安装后的 `rsi` 一致，--help/--version 不依赖集群。--json 在子命令后也能使用，错误 stdout 仍为一个 JSON envelope，不能混入日志。

- 参数错误退出2，INVALID_COMMAND/INVALID_ARGUMENT，retryable=false。
- 后端不可达输出 SERVICE_UNAVAILABLE、retryable=true，有限超时。
- `--endpoint URL --timeout SECONDS --token-file PATH` 指定连接；token 不出现在 argv 明文。
- 通用 `request OPERATION --payload JSON --json` 与专用 job/eval/data/artifact 等子命令指向同一 dispatch 语义，不提供绕过鉴权的路径。
- `python -m rsi_red.server --config FILE --ready-file FILE` 启动独立服务。config 示例见进程测试。ready 文件原子写入实际 endpoint，listen 支持 127.0.0.1:0 避免端口冲突。
- local CPU adapter 需独立 worker、持久 exit record 与可恢复 identity；控制服务被 SIGKILL 后作业仍能完成，并被重启服务找回。

## 测试不代表的能力

角色分支测试不是操作系统隔离验证；adapter double 不是实集群运行；CPU marker 脚本不是 SFT；固定答案不是模型性能。真实验收见 cluster-acceptance.md。SFT、GRPO、环境 RL、on-policy distillation、merge starter 以及 agent 会话通知均需后续可执行集成测试，不能由本轮契约自动宣称完成。

## 已实现的扩展

- eval.aggregate(ids)：相同模型/协议的独立评测记录，返回 count、mean、standard_error_over_eval_repeats（只有一次时为 null），明确 independent_training_runs=false。
- transcript.append(campaign_id,session_id,sequence,text) / transcript.show(campaign_id,session_id)：团队可读、原作者追加、序号幂等。
- rsi init、starter create、demo：离线 CPU 开发配置与演示；rsi watch 将服务事件交给 argv handler，成功后推进持久游标。
- code.uri 支持单文件或安全 tar 包；执行从注册时的内容快照展开。
- 评测与任务由独立循环协调，慢 evaluator 不持有数据库/请求锁。

部署限制与具体命令见 usage.md。模拟 evaluator 明确返回 simulation=true，未配置真实 evaluator 时请求失败，绝不生成虚构分数。

## 平级会话监控扩展

- recipe.create(campaign_id,title,hypothesis,method,datasets,parents,parameters?)：作者由凭证决定，方法与输入不可原地修改；返回id、owner、source=agent_report、state和history。
- recipe.update(id,state,observation?)：仅作者追加状态/观察；planned/trying/completed/abandoned为上报状态，不等于job终态或实测收益。
- recipe.show(id) / recipe.list(campaign_id)：团队只读共享，关联job状态从服务记录读取。
- job.submit可选recipe_id：同作者、同campaign、相同数据/父模型集合，否则拒绝；旧请求无需recipe。
- resource.show：仅operator读取节点遥测；ResearchService增加可选telemetry provider。未配置返回unavailable、空gpus和null采样时间。nvidia-smi provider只采集服务节点，不包含多节点汇总或GPU到job的映射。

## Ray恢复与诊断扩展

job.show可包含scheduler_health（degraded/stalled/healthy与错误码、停滞时间和人工核查标志）。失联和未决提交仍保留资源预留，不自动重训；状态变化写scheduler事件。SDK终态的exit_code、diagnostic、scheduler_error_type、accounting_estimate/scope、environment_verification会持久保存。

Ray的cluster_image仅为操作者声明标签匹配，不保证执行于指定镜像；与真实容器部署事实分开。Ray生产请求的digest约束是可追溯声明要求，尚非运行时镜像验证，详见ray.md。


## 开放训练扩展

- job.validate(spec) → valid/normalized/warnings，无任务/事件/预算/调度副作用；与submit共用权限、输入、拓扑和预算校验。
- execution仅command/nodes=1；runtime可含requirements{uri,digest}、python_executable；未知结构字段拒绝，未支持后端明确UNSUPPORTED_RUNTIME/UNSUPPORTED_OUTPUT_TRANSPORT。
- job.runtime记录实际解释器、包清单与摘要、环境分离方式；环境准备和收集计入总walltime，实际失败不继续训练。
- output_manifest是运行期相对清单；job.outputs返回not_requested/pending/published/failed和产物引用，提交和恢复不重复发布。
- 自定义artifact kind使用普通文件完整性校验，legacy model保持HF校验；正式protocol可声明artifact_kinds（默认model），不支持类型返回EVALUATION_UNSUPPORTED_ARTIFACT。
- protocol.show为非operator的无题元数据，eval.samples仅operator；详细隐私与审核边界见evaluation-integrity.md。
- 自动来源verification=service-collected由服务确认，客户端不能设置；训练参数中的tokenizer/max_tokens不再被凭证子串误删。

字段示例、错误语义和共享文件根部署前提见flexible-training.md。
# 评测方向与人授权（2026-10-26）

新注册协议必须显式配置有效 direction（minimize/maximize），支持 protocol 默认值与 item 覆盖；同 task 必须一致。可选 role=policy/judge、metric=非空字符串，仅标注，不决定方向或角色权限。缺方向报 INVALID_REQUEST，缺人的 operator 授权报 DIRECTION_AUTHORIZATION_REQUIRED，映射或来源不一致报 DIRECTION_AUTHORIZATION_MISMATCH。

方向由人明确授权，研究者/审核者不能通过 direction.authorize 自授权。配置凭证与训练凭证分开；服务验证 operator 通道，不宣称能证明文本确由人撰写。授权开发与授权具体实验目标分开。

normalization=bounded-complement-v1 冻结进协议 digest，score 必须 [0,1]；maximize=raw、minimize=1-raw，task_mean 用目标分。eval.show/compare 同时显示 raw/normalized 与 task_metrics；score/task_scores 为目标分别名。审核检查原始分，跨协议比较拒绝。

混合算例：ASR minimize、AUROC maximize，raw (.6,.6)→(.2,.8)，normalized (.4,.6)→(.8,.8)，suite .5→.8；ASR 反向变高会退步。完整授权JSON、逐item协议、派生与CLI见 [评测方向完整契约及示例](evaluation-direction.md)。

protocol.derive 只能凭绑定来源 digest 的完整授权覆盖已有 task 元数据，不改题目或采样；新 ID/digest，原记录不变。新目标使用新 campaign；无方向旧记录只读，不自动补值。campaign.select 只读按同协议成功重复的目标均分推荐，并执行当前审核资格检查，平分按 model_id；campaign.submit 仍显式提交并执行门禁。

## Benchmark Runner（已实现）

`runner.register/show/list` 与 `eval.submit/config/logs/cancel` 支持冻结外部 harness；完整 schema、可重放命令、JSONL 输出约束、模型 judge 和混合方向示例见 [Benchmark Runner](benchmark-runners.md) 与 [方向机制](evaluation-direction.md)。`protocol.benchmark` 精确为非空 name/revision/split。注册仅 operator，source.path 是干净 checkout 摄入位置，不进入 Runner digest。未知字段、浮动 commit、越界路径、明文凭证/不固定依赖报 INVALID_REQUEST；dirty/错误 HEAD/tree 报 RUNNER_SOURCE_MISMATCH；judge/data/sampling 冲突报 RUNNER_PROTOCOL_MISMATCH；blob/模型 judge 摘要损坏报 CHECKSUM_MISMATCH。local GPU 报 UNSUPPORTED_RESOURCES，Ray 无共享根报 UNSUPPORTED_RUNNER_BACKEND。

Runner eval 的 run-config 在调度前固化；完整 config、样本和日志仅 operator。公开摘要额外返回 runner_id/runner_digest/run_config_digest/comparison_digest。方向仅来自已授权 protocol，raw 和 normalized 分开。compare/aggregate 禁止跨 Runner/实际环境组；campaign.select/submit 支持 runner_id/comparison_digest 筛选，多个组报 EVALUATION_GROUP_REQUIRED。审核 case/pass 必须匹配 Runner 与实际组，query/GPU 预算不因换 Runner 重置。legacy evaluator 接口保留，旧记录不回填伪造执行证据。
