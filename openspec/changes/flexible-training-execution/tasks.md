# Tasks

## 1. 本轮规划与RED（不授权产品编码）
- [x] 1.1 阅读现有job、recipe、runtime、artifact实现，创建三份能力spec与设计；用openspec strict验证。
- [x] 1.2 编写自由入口/参数保真/预检/环境快照/通用输出契约，正常收集并记录实际RED和已有GREEN，不使用skip/xfail。
- [x] 1.3 接Ubuntu/macOS与真实Ray CPU独立CI门禁、JUnit与失败注解，核对release/simulation复用verify；本地确认RED为需求缺失而非收集错误。
- [x] 1.4 原有204项本地（含33项审核）已实现回归保持GREEN；交付review与基线报告，提交GitHub供用户审阅。

## 2. 预检与参数保真（用户再次授权后）
- [x] 2.1 实现共享validate/submit校验、无副作用job.validate、模式明确拒绝和CLI入口；通过对应契约并补CLI/权限/幂等负例，更新使用文档。
- [x] 2.2 修正凭证键识别，保留tokenizer/长度等训练参数；普通参数与真实凭证双向测试通过，记录兼容性变更。
- [x] 2.3 保持任意method/argv/训练reward不受模板限制；原有预算、代码快照、正式评测权限、审核门禁测试继续通过。

## 3. 逐任务环境（用户再次授权后）
- [x] 3.1 冻结requirements内容和解释器声明；摘要/幂等/重启测试通过，文档说明声明快照与实际环境的区别。
- [x] 3.2 CPU执行端实现私有venv与总walltime覆盖准备/训练；离线双版本wheel、安装失败不启动trainer、deadline负例先RED再GREEN；保持共享环境不变。
- [x] 3.3 Ray实际CPU任务使用同一runtime语义；验证显式任务Python优先和清单回传，不用mock代替真实SDK；不支持后端返回UNSUPPORTED_RUNTIME。

## 4. 通用产物与运行期来源（用户再次授权后）
- [x] 4.1 artifact通用kind文件校验与旧model严格校验同时通过，补自定义格式不能伪造可评测结论的负例，更新artifact文档。
- [x] 4.2 实现运行期manifest、文件收集、job.outputs与CLI；正常/缺失/越界/重复名称的真实进程测试先RED再GREEN，保留进程退出与收集阶段信息。
- [x] 4.3 实现服务验证的job→code/runtime/data/parents来源和幂等发布；中断/重启/原目录改写负例通过，不能仅信任provenance自由字段。
- [x] 4.4 接看板运行环境/输出状态和研究skill，核对仅展示事实、不把任务成功变成模型收益，完成浏览器验证。

## 5. 集成验收与交付（用户再次授权后）
- [ ] 5.1 全量已实现测试、新契约、构建/干净wheel安装与OpenSpec strict通过；Ubuntu/macOS CI绿色，既有研究层RED单独披露不绕过。
- [x] 5.2 真实Ray CPU运行自定义Shell/Python/launcher、私有依赖和动态输出恢复闭环；报告明确不是GPU训练测量。
- [ ] 5.3 用户GPU节点可用后，以实际训练框架做单卡/单节点8卡冒烟，验证GPU分配、torchrun、产物与冻结评测；无设备时保留未验收状态，不据CPU模拟勾选完成。

## Workflow follow-up
- 多节点与受管动态Ray actors需另写spec/RED/CI并获授权，不作为本change已完成能力。
- 本轮到规划交付停止，用户看过后再授权apply；不启动实际训练、不改运行中服务。
