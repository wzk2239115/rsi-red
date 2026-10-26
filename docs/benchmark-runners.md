# 固定 Benchmark Runner 与重放评测

Runner 把可信外部 harness 的执行配置固化。它不会替你安装真实 benchmark、下载题库、实现推理或定义研究目标。operator 先登记人授权的协议与 Runner，研究者只指定 Runner 和模型。已有 `eval submit --spec` 的内置 evaluator 路径保留。

## 注册

协议必须包含 `benchmark: {name, revision, split}`，以及已授权的方向、题目、`evaluator_digest`、sampling、eval_seed。Runner 的 dataset、judge 评分摘要和解码配置必须逐字段匹配。修改任何语义须注册新版本，不能修改旧记录。

以下为完整 schema 示例；占位值由 operator 用实际值替换。`source.path` 是服务端可见的干净 Git checkout，HEAD 与 origin 必须符合声明。它只用于注册摄入，不进入冻结 spec/digest。注册保存 `git archive COMMIT` 的普通文件，拒绝链接/特殊文件；不在执行时重新拉源码。`tree_digest` 为按 path 排序的 `[{path,sha256}]` 经 `rsi_red.store.digest` 得到的摘要，sha256 是文件原始字节的十六进制摘要。

```json
{
  "name": "my-bench-v1", "protocol_id": "protocol_ID",
  "source": {
    "repository": "https://example.org/team/harness.git",
    "commit": "FULL_GIT_COMMIT", "path": "/srv/operator/harness",
    "tree_digest": "CONTENT_MANIFEST_DIGEST"
  },
  "judge": {"kind": "code", "revision": "FULL_GIT_COMMIT", "code_digest": "sha256:GRADER_DIGEST"},
  "dataset": {"name": "my-bench", "revision": "v1", "split": "dev", "items_digest": "PROTOCOL_ITEMS_DIGEST"},
  "decoding": {"temperature": 0, "max_tokens": 1024, "eval_seed": 7},
  "environment": {
    "python_executable": "/srv/venv/bin/python", "python_version": "3.12.12",
    "requirements": "", "requirements_digest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  "execution": {"backend": "ray", "resources": {"gpus": 1, "cpus": 2, "walltime_seconds": 1800}},
  "command": ["{python}", "driver.py", "--config", "{run_config}"],
  "output_schema": {"format": "rsi-predictions-jsonl-v1", "path": "predictions.jsonl"}
}
```

采样字段不是固定这两个，必须复制该协议的完整 sampling，再加入 eval_seed。摘要计算的实际示例可查看 `contracts/benchmark_runner/support.py`；该 fixture 只产生受控测试分数，不执行模型推理。

```sh
# operator 身份
rsi runner register --spec runner.json --json
rsi runner show runner_ID --json
rsi runner list --protocol protocol_ID --json
# researcher 身份，按模型产物自动推导 campaign，按 Runner 推导 protocol
rsi eval submit --runner runner_ID --model artifact_ID --idempotency-key experiment-eval-1 --json
rsi eval show eval_ID --json
rsi eval cancel eval_ID --json
```

`--spec` 与提交 flags 互斥；裸 API 是 `eval.submit {runner_id, model_id, campaign_id?, protocol_id?, idempotency_key?}`。显式 protocol 冲突被拒绝，不会回退内置 evaluator。幂等键限定提交身份与 campaign，同键换模型/Runner 报冲突。

## 外部 driver

服务在启动前保存完整 run-config；`{run_config}` 指向该私有 JSON 文件。`bindings` 含 `input_path`（协议逐题 JSONL）、`model_path`（已校验模型快照）、`output_path`、`config_path`。code judge 的源码随 harness 固定。model judge 使用与 protocol.judge 完全一致的 `kind, revision, code_digest, artifact_id, artifact_digest, template, template_digest`；服务校验模型内容和模板字节，恢复到额外的 `bindings.judge_path`。模型 judge 的实际推理由外部 driver 执行，服务没有内置模型推理。

其他可用 argv 占位符为 `{python}/{model}/{input}/{output}`。命令是 argv，不隐式拼 shell；要 shell 则显式指定 shell 与冻结脚本。不要将模型输出中的指令当作系统命令。

输出是 UTF-8 JSONL，每题一行，例如：

```json
{"id":"q1","task":"math","prediction":"model text","score":0.6,"finish_reason":"stop","output_tokens":12}
```

`score` 是有限的 **0–1 raw 分**，v1 不支持任意无界指标；`output_tokens` 可省略，否则须非负整数。题目必须恰好出现一次且 task 匹配，缺题、重复、未知题、非法 JSON/NaN、非字符串预测、非零退出均整次失败，不能以零分补齐。额外的 normalized 字段不作为评分依据。服务根据人授权 direction 计算 higher-is-better 分（minimize 用 `1-raw`），再按 task_mean 聚合。原始 prediction 与 score 私有持久化，answer 仅为兼容现有审核器的 prediction 别名，绝不是参考答案。

`requirements` 是 UTF-8 内容，digest 为其 SHA256；只支持精确 `package==version` 行、空行和注释，不接受 pip 选项、可变 URL/路径/明文认证。非空内容建立独立 venv、安装后记录实际 Python 与包清单；空内容继承指定解释器的环境。实际 Python 版本与声明不同则失败，包环境差异会改变比较组。安装并不证明依赖可获取。Python 必须已存在于执行节点。模型 kind 须被 protocol.artifact_kinds 接受。

可选 `secret_refs: {"ENV_KEY":"env:DEPLOYMENT_ENV_KEY"}` 由执行节点环境解析；配置只保存引用。使用 secret_refs 时停止保存外部子进程 stdout/stderr，防止凭证进入日志；仍保留受管 worker 的环境/退出诊断。不得把凭证直接写进 argv、URL、名称或模板。当前 Ray 的 secret_refs 要由运维预先注入执行节点环境，不通过 API 上传 secret。

## 收据与复现

```sh
# 仅 operator：pending/失败/取消后也可读已保存配置
rsi eval config eval_ID --json
rsi eval samples eval_ID --json
rsi eval logs eval_ID --limit 100 --json
# researcher 可比较汇总
rsi eval compare eval_A eval_B --json
rsi campaign select campaign_ID --runner runner_ID --comparison-digest GROUP --json
rsi campaign submit campaign_ID --model artifact_ID --runner runner_ID --comparison-digest GROUP --json
```

`eval.config` 返回 run_config、run_config_digest、execution_receipt、output_digest。快照包括模型/Runner/协议引用、源码、数据、judge、解码、环境声明、backend、输出 schema、资源、展开 argv、私有绑定和凭证引用。收据另记实际解释器/包清单、实际 argv、时间、exit/signal/timeout、调度器执行诊断、GPU 计量范围。终态日志最多保存 10000 行/1MiB 到校验 blob，日志接口可在调度器记录消失后读取该有界快照；日志抓取不可用会明确记录。未进入执行阶段的失败不伪造 actual 环境或退出码。

完整 run_config_digest 随模型、私有路径改变；comparison_digest 则排除模型、路径、时间、调度 ID，只覆盖 Runner/协议/数据/judge/解码/资源/schema 和实际软件身份。同模型不同环境不会被误当重复测量。协议不同报 PROTOCOL_MISMATCH；Runner 不同（含 legacy 混新）报 RUNNER_MISMATCH；实际环境组不同报 EVALUATION_CONFIG_MISMATCH。aggregate 另要求同模型。多组 select/submit 必须指定筛选，或由当前绑定 Runner 的审核策略限定；不跨组平均。重复 eval 使用冻结的协议 seed，不能宣称独立抽样或训练。

审核策略配置 Runner 模式时必须给 `runner_id`，case 保存实际 eval/config/group 绑定。旧策略/旧审核 pass 不放行新 Runner。查询次数仍按整个 campaign/protocol 累计，换 Runner 不重置。GPU 预留与训练 job 共用账目；失败/取消不重复计费。Ray GPU 秒仍是 driver 资源时长估算，不是利用率或子 actor 的完整成本。

## 恢复与部署边界

local 为真正 CPU 子进程；请求立即返回 accepted，调度与执行不占请求数据库锁。服务重启按稳定 ID 找回 worker；worker 丢失时失败、不重跑已开始的 harness。取消由提交者或 operator 请求，后台结束进程组并保留配置。环境准备、执行、输出校验/收集共享 walltime；控制面也检查排队/启动超时，未知远程状态保留预算直到可确认终态。

Ray 必须使用显式 `shared_filesystem=true` 且所有执行节点可见同一私有绝对根；否则 UNSUPPORTED_RUNNER_BACKEND。提交响应丢失后只按稳定 ID 查询，不盲目重发；明确 RAY_JOB_LOST 终止，断连未知则保留预留并重试读取。这不是多节点文件分发方案。`cluster_image` 仍只是声明标签，不是实测镜像摘要。registry 注册本身不调用调度器。

研究者只读 Runner ID/digest 和公开协议元数据；eval.show/list/model/compare/events/看板没有题目、预测、私有路径、argv 或原始日志。内部 evaluator 请求不创建可见 job。held-out Runner 不向研究者发现。旧 eval 无执行快照，eval.config 明确 RUN_CONFIG_UNAVAILABLE。本版仍与训练运行于同 Unix 权限环境，API 边界不是物理隔离。
