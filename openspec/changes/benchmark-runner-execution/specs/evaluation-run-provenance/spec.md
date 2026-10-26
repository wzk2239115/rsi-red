# Evaluation Run Provenance

## Purpose

把每次外部benchmark执行的具体条件与预测、评分、成本和终态一起持久化，使不同checkpoint之间的比较能够还原运行事实。保护逐题证据不进入训练会话，并使失败、重启和资源消耗仍可核对而非只有一个最终分数。

## ADDED Requirements

### Requirement: Asynchronous runner submission
eval.submit SHALL 支持runner_id和model_id，推导一致的protocol/campaign；显式引用冲突必须拒绝。提交校验权限、模型格式、预算及后端能力后仅入队，返回冻结引用和run-config摘要，不在请求锁内执行。CLI SHALL 支持eval submit --runner ID --model ID；不能同时用spec/flags相互覆盖。

#### Scenario: Checkpoint replay
- **WHEN** 同campaign两个不同checkpoint使用同一runner提交
- **THEN** 返回不同eval ID，执行配置仅模型绑定和运行私有位置不同，submit不等待harness结束

### Requirement: Complete protected run snapshot
服务 SHALL 在启动前保存解析后的run-config、其digest和不可变输入引用，完成后保存实际argv/环境/资源/seed/退出信息收据、日志引用、逐题预测与raw分。operator通过eval.config和eval.samples可完整取回；失败/取消也保留已形成的配置和诊断，不伪造完整结果。

#### Scenario: Reconstruction after restart
- **WHEN** 控制服务或源目录关闭后重新查询已完成eval
- **THEN** 能还原两次完整配置及预测/评分，旧配置与摘要不变

### Requirement: Strict result publication and direction
服务 SHALL 校验输出格式、完整唯一题目ID、task、预测类型、finish_reason和[0,1]有限raw分，原子发布成功记录；缺失/重复/未知/非法分不补零、不发布部分suite。normalized由服务按protocol计算，不信任外部harness上传的目标分。

#### Scenario: Invalid predictions
- **WHEN** harness退出0但遗漏题目、输出NaN或JSON损坏
- **THEN** eval失败并保留运行收据，没有score成功汇总

### Requirement: Local and Ray execution lifecycle
runner SHALL 支持真实local CPU进程及现有共享文件根的Ray执行。GPU需求不得降级为CPU；不支持后端明确拒绝。walltime覆盖准备/执行/收集；取消、进程失败、丢任务和重启均有终态，恢复先查稳定外部ID，未知提交不得盲目重放。

#### Scenario: Reconcile after response loss
- **WHEN** 外部已接受runner任务但提交响应丢失
- **THEN** 控制面按稳定ID找回原任务，保持一份执行和一份结果

### Requirement: Evaluation accounting
runner评测 SHALL 与训练共享campaign GPU预留/消耗预算并受既有评测查询预算约束，账目记录范围与估算方式。失败/取消释放未用预留，重复reconcile不得重复记账；评测内部执行不得通过研究者job/logs接口泄露。

#### Scenario: Evaluation budget bypass attempt
- **WHEN** runner请求的GPU时间超出campaign剩余额度
- **THEN** 提交拒绝BUDGET_EXCEEDED，不能通过eval绕过job预算

### Requirement: Comparable execution groups
compare/aggregate SHALL 同时验证protocol digest、runner digest、题目/数据版本及实际可比执行身份。不同runner或legacy混比返回RUNNER_MISMATCH；其他语义条件不一致返回EVALUATION_CONFIG_MISMATCH。模型绑定、输出目录、时间和调度ID不构成配置冲突。旧的两次legacy评测沿用现有规则。

#### Scenario: Two models same runner
- **WHEN** 两模型使用同runner且实际可比条件相同
- **THEN** compare返回双方raw/normalized、runner引用和可比组摘要

#### Scenario: Same protocol different runner
- **WHEN** protocol相同但runner版本不同
- **THEN** compare和aggregate拒绝，不能用同protocol冒充同执行条件

### Requirement: Selection and audit binding
候选选择 SHALL 在唯一可比组内计算重复均分；有多个组时要求显式runner/group选择，不能混合排名。runner评测的审核策略/案例 SHALL 绑定runner与执行证据；旧runner或legacy的pass不能给新runner候选放行。

#### Scenario: Audit pass from another runner
- **WHEN** 同模型在runner A通过审核，尝试提交runner B的候选证据
- **THEN** 不复用A的pass，仍须当前执行组的可信审核

### Requirement: No new disclosure paths
eval.show/list/model、compare、events、kanban及job接口 SHALL 仅暴露有权限的开发汇总和摘要。完整run-config、逐题证据、stdout/stderr和输入路径仍限operator；auditor仅既有授权汇总范围。隐藏结果不进入研究反馈，角色权限不因使用runner而扩大。

#### Scenario: Training agent requests run config
- **WHEN** researcher或auditor请求eval.config或尝试经内部job读取评测日志
- **THEN** 请求被拒绝，公开投影不含题库、预测、命令或路径
