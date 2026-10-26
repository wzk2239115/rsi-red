# Design

## Context

参见proposal.md。当前代码观察：job接受argv与代码快照；recipe.method任意字符串；Ray runtime_env属于scheduler全局；artifact.register不论kind都要求HF式三件套；redact使用token子串会误伤MAX_TOKENS、tokenizer_name。已有预算、依赖、幂等、审核和四个平级身份不重做。

## Goals / Non-Goals

**Goals:** 先打磨当前单节点8卡容器上的自由命令、逐任务环境与实际产物闭环。CPU/真实Ray验证软件语义；GPU现场另验。训练策略继续由agent决定，CLI不引入算法审批。

**Non-Goals:** 本change不交付多节点rendezvous、弹性训练、动态Ray子资源记账、Docker-in-Docker、物理隔离、真实训练框架模板、自动harness会话管理。nodes>1/mode=ray_tasks属于明确未支持模式。command内部可调用库和子进程，但不能据此声称已落实动态actors预算包络；正式支持前不提供“子资源已记账”的虚假标签。

## Decisions

### 1. 新字段与预检

现有job spec扩展以下可选字段，旧请求默认command/nodes=1：

```yaml
execution: {mode: command, nodes: 1}
runtime:
  python_executable: /opt/venvs/research/bin/python  # 节点上已有的绝对路径；可省略
  requirements:
    uri: file:///service-visible/requirements.txt
    digest: sha256:ACTUAL_CONTENT_HASH
output_manifest: outputs/manifest.json
```

`rsi job validate --spec job.yaml` → `{valid:true,normalized:{...},warnings:[...]}`。这里只做静态验证，normalized不能包含凭证明文；不承诺解释器在远端存在、依赖能下载或GPU空闲。validate不创建快照blob或事件，不连接scheduler。submit复用校验，在事务中冻结代码和requirements字节并预留预算。runtime/execution中的未知字段拒绝，避免接受后丢弃。训练参数仍可放任意argv/代码内配置/recipe.parameters，不限制参数名。

替代方案：把所有CLI字段都解释为训练框架参数。放弃，因为控制字段拼写错误会被静默吞掉；框架配置应保持在自己的配置文件中。

### 2. 环境准备与费用

入队时`job.runtime={state:pending,requested_python,requirements_digest}`；无runtime旧请求使用inherited。执行包装器在作业资源范围内启动总walltime计时，若有requirements，使用声明基础Python创建job独立venv并安装冻结依赖。pip阶段、训练阶段与收集阶段明确记录，实际失败不自动换配置重试。运行清单记录actual_python、实际包清单内容摘要与isolation=job-venv/inherited；包清单通过受权job查询获取，凭证不进入清单。

Ray沿用当前已分配driver GPU给同节点子进程；不对torchrun再申请第二组GPU。任务runtime解释器优先于scheduler默认，task venv的bin加入PATH，使python/torchrun找到同一环境；保留绝对非Python可执行入口。CPU local使用同一环境准备语义。Slurm/Kubernetes尚无该功能时对新runtime明确UNSUPPORTED_RUNTIME，不静默接受；旧请求不变。

替代方案：agent自行pip install共享环境。虽然当前command可运行这种命令，但框架不将其作为默认依赖准备机制，避免四个实验互相覆盖。任务环境不是恶意代码沙箱。

requirements快照只冻结声明，不保证下载内容确定。建议hash-pinned锁文件；实际解析结果必须记录，离线CI使用本地测试wheel，不访问模型仓库。大依赖安装时间计入walltime和GPU预留，不承诺免费预热。

### 3. 输出与来源

训练脚本运行后写：

```json
{"items":[{"name":"candidate","path":"outputs/checkpoint","kind":"custom_checkpoint"},
          {"name":"analysis","path":"outputs/report.json","kind":"research_report"}]}
```

path是工作目录相对路径，可为文件或目录；目录递归收集普通文件，禁止越界/重复name/符号链接逃逸。成功进程且声明收集时要求非空合法manifest，先校验全部输出再原子发布元数据。`job.outputs`返回`{state,items:[{name,artifact_id,digest,kind}],reason?}`；字段同时用于看板。失败进程不自动发布为成功候选，保留诊断与退出信息。

第一阶段明确使用单容器共享文件根：worker将收集结果写入服务为job分配的受管目录，控制面校验并幂等登记；不能把Ray runtime-env缓存目录直接当控制面目录。部署需声明control/worker可见同一shared root；没有该传输能力时拒绝UNSUPPORTED_OUTPUT_TRANSPORT，声明后实际不可写则收集失败。跨主机对象存储/网络传输另行实现，不在本阶段暗示已支持。以job ID/name/content digest恢复，验证完成后追加服务来源，冻结data/parents/code/environment事实。`artifact.register`自定义kind采用通用文件校验；legacy model保留原严格校验。自定义格式如何变成可推理模型由后续evaluator/agent转换，不强制套用HF。

替代方案：所有产物都叫model并补空tokenizer。放弃，因为制造假完整性；任意格式应能存取，不能假装可直接评测。

### 4. 训练开放与正式评测

自定义训练reward、代理指标、合成数据、模型合并、采样搜索均不需要method白名单。protocol.register operator-only、隐藏集不开放、正式收据不可客户端伪造继续有效。审核反馈是证据，不是研究方法审批。资源预算、权限与有效文件是执行约束；失败、怪方法和低分不是作弊证据。

### 5. CI/CD先RED再GREEN

新增`contracts/flexible_training`独立非容错job，matrix Ubuntu/macOS Python3.12，另加安装真实Ray的CPU新功能契约job，均输出JUnit和失败注解；release/simulation已通过workflow_call复用全量CI，无须放行旁路。本轮允许已有自由入口契约自然GREEN，缺失功能真实RED，不写xfail/skip/continue-on-error。

授权实现时补真实进程集成：离线wheel的双版本环境、设置失败不启动trainer、runtime安装也受deadline、运行期输出与重启恢复、CPU torchrun式launcher（不冒充CUDA）。Ray真实CPU集成验证任务环境和输出回传；真实8卡Torch训练独立现场验收，不把CI CPU当GPU通过。多节点/动态actors移到后续spec，不混入本change的完成承诺。

## Risks / Trade-offs

- [全局脱敏规则放宽泄漏凭证] → 明确凭证键与普通参数的双向回归；不放宽真正API_KEY/ACCESS_TOKEN等键。
- [环境准备慢、依赖不可下载] → stage诊断、总超时、实际清单、离线CI；不自动改依赖。
- [输出已写但控制面重启] → 不可变收集记录与幂等发布；不把路径存在当成artifact已注册。
- [单节点命令内部另建Ray actors] → 明示当前记账只覆盖作业分配；受管子资源支持后再承诺其预算边界。
- [第三方训练框架组合无限] → 框架无关入口与集成契约，不承诺逐框架开箱即用。

## Migration Plan

本轮只交付spec、契约、CI和基线报告；不改src或已实现接口文档。用户再次授权后，先转预检/参数保真GREEN，再实现环境，再实现产物；每段跑原有审核/预算/恢复测试。新字段默认缺省保持兼容；后端不支持时明确拒绝。保留旧数据与产物；不对已有job做推测性环境或来源回填。
