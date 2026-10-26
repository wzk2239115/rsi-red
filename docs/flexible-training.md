# 开放训练执行

研究agent自由选择代码、方法、训练reward与实验顺序；starter不构成算法白名单。下面的接口支持单节点command运行，包括一次8卡分配内的torchrun。训练资源、数据来源、代码和正式评测继续留记录；不会因任务成功而自动产生分数或通过审核。

## 预检与提交

```sh
rsi job validate --spec experiment.yaml --json
rsi job submit --spec experiment.yaml --json
rsi job show JOB_ID --json
rsi job logs JOB_ID --json
rsi job outputs JOB_ID --json
```

validate只检查当前权限、输入摘要、预算和静态后端能力，不创建job/事件/快照，不安装依赖或联系调度器。成功返回valid、normalized、warnings；不证明远端解释器存在、依赖可下载或GPU空闲。submit冻结实际代码与requirements内容，并立即返回任务ID。

在现有job spec中增加可选字段：

```yaml
execution: {mode: command, nodes: 1}
runtime:
  python_executable: /opt/venvs/training/bin/python
  requirements:
    uri: file:///service-visible/requirements.txt
    digest: sha256:ACTUAL_REQUIREMENTS_HASH
output_manifest: outputs/manifest.json
```

其余campaign_id、idempotency_key、entrypoint、code、datasets、parents、resources沿用现有契约。URI必须在控制服务上可读，不是任意客户端本地路径。代码包可含train.py、训练配置和launcher；argv可使用Python、Shell、torchrun或自定义程序。单文件的相对入口名保持相对；原绝对源路径会重定位至快照。框架参数放argv、代码包配置文件或recipe.parameters，不放在runtime/execution中充当未定义控制字段。

nodes>1或mode=ray_tasks目前明确返回UNSUPPORTED_EXECUTION_TOPOLOGY；未知控制字段INVALID_REQUEST。当前不承诺动态Ray actors的全部资源记账。未声明新字段的旧请求仍可用。

## 每任务环境

local CPU与声明shared_filesystem的Ray后端支持runtime。Ray部署在service.json的scheduler中设置`shared_filesystem: true`，表示worker与控制面位于现有同一容器/共享相同绝对文件根；`rsi init --profile ray-peers`生成的配置已包含此声明。worker的runtime-env缓存目录不是控制面目录，执行结果会复制到服务分配的结果目录。未声明共享文件能力时，新runtime/outputs明确拒绝，不把跨主机传输描述成已实现。

- 提供requirements时，任务在自己的venv中安装冻结内容；安装不修改全局环境。
- 没有requirements时使用已有环境，runtime.python_executable可选择节点已有的绝对Python；未指定沿用后端默认。明确任务Python不被Ray全局默认覆盖。
- 依赖准备、训练、文件收集共享walltime；环境失败不运行trainer，不自动改配置重试。
- job.runtime记录实际Python、实际包名/版本清单、摘要、requested_python、requirements_digest和isolation。requirements是声明快照，实际包清单才是运行事实；不等同于完整镜像复现。
- job.stage区分runtime/training/collection/completed；失败返回runtime_setup_failed、training_error、output_collection_failed等原因，超时保持timed_out/walltime。取消仍只操作当前任务。
- 显式环境会把自身bin加入PATH，python/torchrun可找到该环境的可执行文件；绝对的非Python入口不被替换。

普通max_tokens、tokenizer_name、MAX_TOKENS、TOKENIZERS_PARALLELISM保真。真正凭证键继续从可共享spec中移除，不把API_KEY/ACCESS_TOKEN等字面量当普通训练参数回显或注入。

Slurm/Kubernetes目前不支持新runtime和自动输出回传时会明确拒绝；旧任务保持原行为。环境安装时间占用所申请作业资源，不能将其记为免费预热。

## 运行期输出

训练程序最后写出manifest；内容不必在提交前知道：

```python
from pathlib import Path
import json

out = Path("outputs")
out.mkdir(exist_ok=True)
# 此前由你的训练代码产生 outputs/checkpoint/ 和 outputs/report.json。
(out / "manifest.json").write_text(json.dumps({"items": [
    {"name": "candidate", "path": "outputs/checkpoint", "kind": "custom_checkpoint"},
    {"name": "analysis", "path": "outputs/report.json", "kind": "research_report"}
]}))
```

path可指工作目录内的文件或目录，目录递归收集普通文件。名字必须唯一，禁止越界、缺失文件和符号链接逃逸。成功训练但输出清单无效时，job仍为failed，exit_code保留0，reason=output_collection_failed；不会把空输出算成功。没有声明manifest的旧任务返回`{state:not_requested,items:[]}`。

job.outputs的published记录包含name、kind、artifact_id、digest。所有输出元数据原子发布；后续输出校验失败不会留下前面部分成功的artifact。控制服务在发布前/后重启都恢复原任务，不重复训练或重复发布。注册内容不会随原目录被改写。

自动收集的artifact.provenance含job_id、code_digest、datasets、runtime_manifest_digest，父模型在artifact.parents；verification=service-collected由控制面确认，客户端不能设置这个标记。手工provenance只是提交者描述，不能当可信生成收据。

自定义kind支持adapter、研究报告、生成数据、自定义checkpoint等任意非空类型，文件摘要仍验证。旧kind=model继续要求HF式完整性；产物能登记不代表能推理。正式协议默认只接受kind=model；operator可在冻结protocol登记时用artifact_kinds明确声明其真实evaluator接受的类型，协议摘要随之改变。研究者不能为获取分数自行改正式协议。

## 看板与验收

看板按研究身份展示近期任务的环境状态、包数量与产物发布状态，不把绝对路径、原始环境变量或包清单送到浏览器。明细通过CLI查询。四个训练会话仍平级，审核身份保持独立。

CI包含离线双版本wheel、实际CPU子进程、安装失败/超时、控制服务重启和真实Ray Jobs。CPU多进程launcher不代表CUDA/8卡torchrun已验收；真实GPU节点可用后再独立执行现场验收。多节点与受管Ray子资源属于后续spec范围。
