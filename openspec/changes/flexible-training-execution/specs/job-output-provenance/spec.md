## Purpose

让研究任务在运行后公布实际产物清单，保存模型以外的中间成果，并使每份产物可追溯到真实执行和输入。通用产物登记不应限制训练框架或文件格式，也不能把缺失文件、无效清单或客户端自报当作已验证产出。

## ADDED Requirements

### Requirement: 任意研究产物类型
artifact.register SHALL 对非空自定义kind接受任意完整文件清单并校验内容摘要，不强制要求HF config/tokenizer/weights。旧kind=model仍遵守既有完整性校验；登记成功不代表所有evaluator支持该格式。

#### Scenario: 自定义中间成果
- **WHEN** 登记adapter、自定义checkpoint、生成数据或报告文件
- **THEN** 内容有效即可登记和fetch，不返回INCOMPLETE_MODEL

#### Scenario: 原有模型校验保留
- **WHEN** 旧kind=model缺失必要模型文件
- **THEN** 仍拒绝INCOMPLETE_MODEL

### Requirement: 运行期产物清单
job.submit SHALL 支持output_manifest的工作目录相对路径。训练成功后执行端读取实际生成的清单，校验每个name/path/kind及内容，返回持久job.outputs。清单内容无需提交前知道；未声明清单的旧任务保持兼容并显示not_requested。第一阶段使用明确声明的单容器共享文件根；无可用传输能力时预检和提交返回UNSUPPORTED_OUTPUT_TRANSPORT，不假设worker缓存路径能被控制面读取。

#### Scenario: 程序运行后决定输出
- **WHEN** 成功进程生成先前未知名称的checkpoint和报告，并写出manifest
- **THEN** 服务发布实际清单中的产物，job.outputs可查询artifact ID和摘要

#### Scenario: 清单或文件无效
- **WHEN** 请求收集但清单缺失、输出越界、文件缺失或名称重复
- **THEN** job最终failed且reason=output_collection_failed，保留训练exit_code与收集阶段诊断，不把空清单当成功

### Requirement: 来源绑定与幂等发布
自动发布产物 SHALL 绑定真实job、代码摘要、环境清单、注册数据和父模型；由服务确认来源，不信任客户端伪造verified标志。服务重启后相同job输出不重复创建artifact；发布成功后不随原目录改写。

#### Scenario: 控制服务重启
- **WHEN** 进程已完成而发布流程中断后reconcile恢复
- **THEN** 恢复同一输出集，artifact ID与来源不重复，job.outputs可恢复

### Requirement: 产物不会自行成为研究结论
系统 SHALL 将任务成功、产物完整和正式评测结果分别记录；不因生成checkpoint、训练reward高或job退出0自动判为性能提升或审核通过。正式eval继续校验格式与权限。

#### Scenario: 训练成功但尚无评测
- **WHEN** 自定义任务成功并发布产物
- **THEN** 没有自动生成分数、checks_passed或campaign最终提交
