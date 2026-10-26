# Proposal

## Why

当前 eval 只冻结模型/协议引用并调用 evaluator，缺少外部 benchmark 的执行版本和逐次运行配置证据。新的 checkpoint 需要重放同一 harness/judge/split/解码设置，研究者也需要区分模型收益与执行条件变化。

## What Changes

- 新增 operator-only runner.register；runner.show/list按权限投影。冻结 harness 来源/完整commit/源码快照、judge版本、数据内容/split、解码、资源、环境、argv模板和输出schema。修改生成新runner，不提供原地更新。
- runner绑定不可变protocol，校验judge评分摘要、sampling、题目及数据版本兼容；不能借runner改变人的direction授权。
- eval.submit可按runner+model执行，异步返回；服务保存解析后的完整run-config及digest、实际执行收据、逐题预测和原始得分，继续按protocol归一化。
- 新增operator-only eval.config；公开eval汇总只增加runner/config/可比组摘要，不公开路径、题库、预测、日志或凭证。
- compare/aggregate/select/audit按runner和执行可比组约束，不能只检查protocol后混合不同harness。旧的无runner评测保留原流程，与有runner评测不能混比。
- 首版规划local CPU与现有单节点共享文件根Ray执行，使用真实外部CPU fixture验证生命周期，不绑定特定安全bench或要求现在接入H100。
- 本轮仅OpenSpec、可执行RED、CI/CD阻断和审阅材料。用户再次批准后才实施产品代码。

## Capabilities

### New Capabilities

- `benchmark-runners`: 可信执行配置注册、不可变输入、协议兼容与权限。
- `evaluation-run-provenance`: 运行固化、外部执行、结果校验、可比性、恢复、预算与安全读取。

### Modified Capabilities

无已归档主spec；与在途evaluation-direction、evaluation-integrity及trusted-evaluation共同遵守。不能扩大训练者读题或改正式评分的权限。

## Impact

后续实施涉及service/evaluation/evaluator执行器、CLI、audit、campaign资源/选择、kanban安全投影及文档/研究技能。当前eval为进程内阻塞回调，不能简单把subprocess.run塞进全局锁；现有训练job查询也不能泄露评测内部任务。

不实现全部benchmark适配、GPU推理引擎、远程API judge可重复性、强沙箱、多节点、论文岛屿、真实训练。执行条件可还原不等于逐位确定性。本轮不改src或运行中服务，不占用真实GPU。
