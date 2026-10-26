# Tasks

## 1. 本轮规划、RED与CI

- [x] 1.1 核对现有eval/协议/审核/选择/账目，写两份能力spec与设计；用OpenSpec strict核验，src不修改。
- [x] 1.2 编写外部CPU fixture、46项应用/CLI RED及2项Ray RED，0收集错误；独立driver真子进程自检通过。Runner尚未到实际执行，不用mock产品逻辑或skip/xfail。
- [x] 1.3 接Ubuntu/macOS CPU、真实Ray CPU CI门禁及JUnit/失败注解；核对release/simulation复用verify，已有315项回归GREEN，报告明确远端状态独立观察。
- [x] 1.4 交付review入口、命令/配置草案与RED基线，停在审批阶段，不开始产品编码；规划材料提交GitHub供审阅。

## 2. Runner注册与输入固化（用户审批后）

- [x] 2.1 实现operator注册、schema校验、git来源/commit/dirty/内容快照校验和不可变版本；对应正负契约GREEN，docs/contract.md补字段与错误。
- [x] 2.2 实现protocol benchmark元数据和runner兼容性、固定code/model judge引用与私有绑定、方向授权不变、show/list安全投影；补judge漂移/隐藏/auditor范围测试，写服务端摄入示例。
- [x] 2.3 增加源目录删除/源码blob损坏、requirements/凭证引用、占位符与模型格式边界RED后实现；写受支持schema与真实环境声明边界。

## 3. 异步运行与证据（用户审批后）

- [x] 3.1 实现run-config持久化、eval.config与runner提交CLI，保留旧--spec；补请求冲突/重启读取/锁内不执行/幂等测试及完整调用文档。
- [x] 3.2 实现受管local CPU进程、标准JSONL解析与原子结果发布、严格分数/题目校验、方向服务归一化；外部driver确实运行、失败保留收据，文档不宣称真实推理。
- [x] 3.3 实现eval取消、walltime、local丢进程/重启、准备/收集失败诊断；补并发取消/崩溃窗口RED，验证不重复发布及不误杀PID，写恢复说明。

## 4. 可比组、账目与审核（用户审批后）

- [x] 4.1 compare/aggregate/select按runner和comparison_digest约束，模型/私有路径变化可比，其他语义漂移拒绝；补多组筛选/环境漂移/legacy混比，文档解释两种digest。
- [x] 4.2 audit策略/case/pass绑定runner与实际eval证据，旧pass不能放行新组；补审核与query预算跨runner负例，更新审核文档。
- [x] 4.3 eval与job共享GPU预留/消耗账目；补并发预算/失败取消/重复reconcile测试，内部评测job/logs不可公开，更新预算计量范围文档。

## 5. Ray、权限与交付（用户审批后）

- [x] 5.1 接真实Ray CPU与共享文件根执行；补SDK响应丢失/控制重启/输出收集/节点丢失契约，保留不重放写语义；真实集成与部署说明通过。
- [x] 5.2 全公开投影、日志、events、看板不泄题或凭证，runner元数据/比较组安全显示；HTTP/浏览器权限验收及rsi-research使用说明完成。
- [ ] 5.3 本地315项回归、新CPU/Ray契约、ruff/OpenSpec/build/干净wheel全通过；远端CI结果留证，原islands RED不绕过；交付两checkpoint重放与完整配置还原报告。

## Workflow follow-up

- 本轮等待用户审批后再进入apply；不修改运行中服务，不调用真实GPU、不安装真实bench。
- H100与实际外部bench由操作方提供配置后另验收，不把CPU fixture当论文成绩。
