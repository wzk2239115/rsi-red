## Purpose

使同一GPU容器内的平级研究任务能够使用各自的训练依赖，并记录执行时的环境事实。依赖准备、训练参数和解释器选择应可追溯，不修改其他研究任务的共享环境；不把环境标签或依赖文本摘要等同于可复现运行环境。

## ADDED Requirements

### Requirement: 逐任务依赖内容冻结
job.submit SHALL 支持runtime.requirements的file URI与sha256摘要，入队时冻结实际字节并记录job.runtime.requirements_digest。摘要错误拒绝；相同幂等键但requirements内容不同拒绝冲突。submit不安装依赖或执行训练。

#### Scenario: 提交后依赖源文件变化
- **WHEN** 成功提交后源requirements被改写
- **THEN** job仍引用提交时内容及摘要，执行端使用快照

#### Scenario: 伪造依赖摘要
- **WHEN** 声明摘要不匹配实际requirements内容
- **THEN** 返回CHECKSUM_MISMATCH，不产生可调度任务

### Requirement: 任务私有环境准备
提供requirements的任务 SHALL 在自己的环境目录准备依赖，不向共享Python/其他任务环境安装。依赖安装在已提交任务资源和walltime内执行，失败为job failed、reason=runtime_setup_failed，日志可诊断且不启动训练；不自动换环境重试。

#### Scenario: 两任务不同依赖
- **WHEN** 同时执行两个使用不同版本依赖的任务
- **THEN** 两者环境目录不同，实际导入各自版本，共享环境不被修改

#### Scenario: 环境准备失败
- **WHEN** 安装退出非零或超过walltime
- **THEN** 不运行训练入口，持久记录失败与执行阶段，超时仍保留timed_out语义

### Requirement: 解释器选择与真实环境清单
runtime.python_executable SHALL 支持节点上已有的绝对Python路径；未指定时沿用后端配置。不因全局解释器配置覆盖显式任务选择。准备成功后job.runtime SHALL 记录state=ready、actual_python、packages_digest和isolation；清单可查询，不宣称镜像级隔离或完全确定复现。

#### Scenario: 显式任务解释器
- **WHEN** 任务指定不同于服务默认的有效Python绝对路径
- **THEN** 执行端按声明选择并记录实际解释器，不替换成全局默认

#### Scenario: 保持旧请求兼容
- **WHEN** 请求未包含runtime
- **THEN** 旧任务仍可执行，新增环境字段不改变原入口行为

### Requirement: 普通训练参数保真
系统 SHALL 完整保留max_tokens、tokenizer_name、MAX_TOKENS、TOKENIZERS_PARALLELISM等非凭证配置。明确凭证字段不能明文进入共享spec/recipe/环境清单；使用凭证字段名规则，不按token子串泛化删除。

#### Scenario: tokenizer相关配置
- **WHEN** recipe.parameters与job.env包含普通tokenizer/长度参数
- **THEN** 存储、查询和实际执行值均与请求一致

#### Scenario: 真正凭证不能回显
- **WHEN** 共享记录包含API_KEY或ACCESS_TOKEN等凭证键
- **THEN** 保持现有不明文回显约束，不借参数保真泄露凭证
