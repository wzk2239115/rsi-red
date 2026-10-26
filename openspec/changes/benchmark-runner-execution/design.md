# Design

## Context

当前eval.submit必须给campaign/model/protocol，reconcile在DB锁外调用进程内evaluator.evaluate；成功保存items和归一化汇总。无runner实体、run-config接口或执行身份校验。compare仅比protocol，aggregate按model/protocol分组，campaign.select也会合并同协议全部评测；audit当前按model/protocol/policy绑定。新增runner不能只加一个字符串字段。

## Goals / Non-Goals

Goals：以operator登记的可信外部程序为入口，在local CPU与既有Ray共享文件根执行，完整保留配置与逐题证据；保护既有direction/审核/预算/无题边界。首版输出统一JSONL，由adapter适配各bench原格式。

Non-Goals：不安装真实安全bench/推理栈，不下载任意模型，不提供不固定版本的远程API judge，不新增强隔离/多节点，也不修改论文岛屿。资源字段不等于真实GPU验证。

## Decisions

### 1. Registry 与协议关系

操作：`runner.register --spec FILE`、`runner.show ID`、`runner.list --protocol ID`。注册仅operator；研究者show/list安全投影，隐藏runner仍operator-only，auditor只看当前审核授予的protocol范围。

runner输入包含：

```json
{
  "name": "example-v1", "protocol_id": "PROTOCOL_ID",
  "source": {"repository": "https://example.org/bench.git", "commit": "FULL_GIT_COMMIT", "path": "/operator/clean/checkout", "tree_digest": "CONTENT_DIGEST"},
  "judge": {"kind": "code", "revision": "FULL_GIT_COMMIT", "code_digest": "PROTOCOL_EVALUATOR_DIGEST"},
  "dataset": {"name": "example", "revision": "v1", "split": "dev", "items_digest": "PROTOCOL_ITEMS_DIGEST"},
  "decoding": {"temperature": 0, "max_tokens": 8, "eval_seed": 42},
  "environment": {"python_executable": "/absolute/python", "python_version": "EXACT_VERSION", "requirements": "", "requirements_digest": "SHA256_OF_EMPTY_CONTENT"},
  "execution": {"backend": "local", "resources": {"gpus": 0, "cpus": 1, "walltime_seconds": 30}},
  "command": ["{python}", "driver.py", "--config", "{run_config}"],
  "output_schema": {"format": "rsi-predictions-jsonl-v1", "path": "predictions.jsonl"}
}
```

source.path仅用于摄入，不成为执行时可变依赖或语义digest；冻结spec改为内容快照引用。验证git完整commit与HEAD一致、tracked/untracked非忽略文件干净、origin与声明来源一致；按commit导出文件，拒绝越界/符号链接逃逸，核对清单内容digest，持久化到服务blob。初次只接受已在服务端准备的clean checkout，不在eval时联网clone。judge支持code固定源码，或model的artifact_id/digest+revision+template_digest固定绑定；model模式必须与protocol.judge完整声明一致，验证artifact及模板摘要，运行时恢复私有judge_path。实际judge推理由外部harness实现，本工具不提供内置LLM推理引擎；CPU假judge仅证明引用/快照链路，不证明推理有效。不固定版本的API judge不在首版。

protocol增加可选benchmark{name,revision,split}元数据；有runner时必需。items_digest为服务规范化完整protocol.items的摘要；runner.dataset与该协议完全匹配，judge.code_digest匹配evaluator_digest，decoding与sampling加eval_seed严格相同。runner绑定一个protocol，方向改变新protocol后需新runner版本；不允许eval层覆盖sampling/judge/split/direction。

tree_digest采用现有canonical JSON digest，对按path排序的[{path,sha256}]清单计算；不包含.git或摄入目录路径。model judge的template保存完整冻结文本并校验template_digest，artifact_digest核对服务实际产物；不接受只报一个版本名。

### 2. 命令与环境

argv数组按参数替换{python}/{model}/{input}/{output}/{run_config}，未知占位符拒绝，不隐式shell拼接；需要shell时operator显式指定bash及已冻结脚本。output为执行根内相对路径。常规参数保真，secret只允许部署侧引用，快照保存引用不保存解析值；原始日志仅operator并清理已知凭证值，不把stdout当公共反馈。

环境固定Python版本与requirements内容digest；空requirements可用于stdlib fixture。执行隔离/安装复用现有runtime机制，保存实际Python/包清单摘要；声明指纹与实际执行证据分开。Ray仍需显式shared_filesystem，cluster_image标签不视为实际容器校验；真实镜像证明只能由可信执行端提供。

### 3. 异步提交与执行证据

新请求：`eval.submit {runner_id,model_id,campaign_id?,protocol_id?,idempotency_key?}`，model的campaign与runner的protocol解析引用；显式值冲突拒绝，不覆盖。CLI保留--spec旧用法，新增--runner/--model可选--campaign；两种模式同时给值报INVALID_ARGUMENT。旧无runner请求保持现有evaluator后端。

校验和预算预留完成后，先保存eval、模型/runner/protocol摘要、resolved run_config与config_digest及稳定submission_key，再由reconciler执行，不阻塞请求锁。准备中的实际环境信息后写execution_receipt，不回写原run_config。完整输入快照/operator-config与私有运行目录由服务生成，模型文件从artifact blobs恢复，不读取原训练目录。

run_config含：schema_version、runner/protocol/model的ID与digest、source/judge/dataset、decoding、environment声明、resources、展开后的command(argv)、bindings{input_path,model_path,output_path,config_path}绝对位置、secret_refs。外部driver通过bindings读取文件，不读取服务DB。eval.config返回{run_config,run_config_digest,execution_receipt,output_digest}，仅operator；失败和pending也能取回已形成配置，未执行收据为空。receipt含实际环境、启动/结束、exit_code/信号/超时、成本范围及日志blob引用。不把调度器错误原文或未知程序输出直接回传训练者。

run_config完整摘要因model/路径不同而不同；另有comparison_digest，来自runner/protocol/data/judge/decoding/输出schema及实际软件环境身份，排除model、私有目录、时间、调度ID。实际seed照冻结protocol记录；本次不引入隐式seed变化，重复均值不宣称独立采样/训练。实际环境不符合声明时失败，符合声明但额外软件环境不同则禁止受控比较。

### 4. Local/Ray 与预算恢复

local用受管CPU子进程，GPU>0拒绝UNSUPPORTED_RESOURCES；Ray复用现有低层scheduler和标准库执行器，资源声明实际传递，shared_filesystem=false拒绝UNSUPPORTED_RUNNER_BACKEND。不经公开job.submit创建训练可读job；评测执行与日志另存在eval内部状态，避免job.list/show/logs绕过保护。

异步状态保留accepted/running/succeeded/failed/cancelled/timed_out；增加eval.cancel，只有提交者或operator可取消，auditor不能。评测预留与已用GPU秒接入campaign.usage，与训练共享预算；成本是driver预留估算时明确标注，不伪称实际利用率。失败/取消只释放剩余预留，重复观察不重复扣费；现有max_evaluations在接受请求时仍计数，不能靠runner换版本重置同协议预算。

恢复按eval稳定submission_key find/status，不确定写不重放。结果先校验/保存blob再原子提交终态；崩溃重试解析同一输出不重复发布。local记录pid和进程实例身份，重启不盲目杀同pid的新进程；无法找回的运行标failed/lost，不假装成功。walltime包含环境准备/执行/收集。

### 5. 输出与可比性/审核

第一版统一JSONL：每行{id,task,prediction,score,finish_reason,output_tokens?}。prediction是模型输出，内部兼容item.answer；它不是protocol标准答案。严格检查全量ID/task、类型和有限[0,1]分数，缺题/重复/外来题/坏JSON/非零退出/越界输出均失败；保存原始输出blob和错误类别，不补零，不部分发布suite。服务用summarize重新计算目标分，忽略或拒绝外部normalized字段。

compare/aggregate：协议不同仍PROTOCOL_MISMATCH；runner不同或一边legacy返回RUNNER_MISMATCH；实际comparison_digest不同返回EVALUATION_CONFIG_MISMATCH。公共compare只给raw/normalized及安全摘要。两边legacy继续旧行为，旧记录不假造run_config。

campaign.select有多个runner/group时返回EVALUATION_GROUP_REQUIRED，支持可选runner_id/comparison_digest选单组；无runner参数且仅一个组可直接推荐。不要将同模型不同runner的评测平均。campaign.submit也接受可选runner_id/comparison_digest；有多个执行组时要求指定或由已固定的当前audit策略唯一确定，不静默忽略组参数。audit.configure对runner模式绑定runner_id/digest，audit case绑定eval+runner+config/comparison digest；旧policy/pass不能为新runner模式通过。保留既有无runner策略行为，不能因新机制放宽审核。

### 6. 测试边界与交付顺序

本轮先CPU应用契约和真实子进程fixture、Ray CPU独立契约及CI。fixture创建小git仓库、两份假checkpoint，用外部stdlib driver产生受控预测；它验证执行/证据与数据流，不是LLM或真实bench效果。RED会在runner.register缺失时失败，未到达子进程/Ray启动，报告必须注明；实施后这些同一断言必须真正走外部进程/SDK。

实施前补崩溃窗口、预算、原子发布、权限/错误泄漏、seed/环境漂移、CLI与干净wheel测试。新CI作业不得continue-on-error；release/simulation复用既有verify，因此RED阻断发布。原315项已实现回归保持GREEN，原islands 32 RED单独披露。

## Risks / Trade-offs

- [任意外部bench格式差异] → 首版只收标准JSONL，适配器随harness源码冻结；不冒充开箱支持全部bench。
- [API权限不等于物理隔离] → runner仅operator登记、输出按角色投影；共享Unix用户的文件旁路仍留后续，不作为本轮强沙箱承诺。
- [命令/环境变更伪装模型收益] → 完整快照+实际收据+独立comparison_digest，不以runner名或标签判断可比。
- [收集GPU成本遗漏] → eval执行单独可追溯但纳入同campaign账目，不通过公开job暴露受保护信息。
- [无法逐位复现] → 还原配置与声明确定性范围分开，记录实际设备/软件信息，不给无依据保证。

## Migration Plan

本轮不改产品。用户批准后依次注册/快照→local执行与run-config→比较/审核/账目→Ray恢复→CLI/文档/看板安全投影。旧无runner评测不迁移或补造证据，可继续旧比较；新runner需要新的真实执行。上线前备份状态；旧版本程序不得读取新runner请求并忽略runner_id退回旧evaluator，回滚前停止新提交并保存执行账目。
