# Benchmark Runner：审批入口

当前状态：只有spec、RED测试、外部测试fixture和CI/CD配置。新runner/eval.config/CLI旗标尚未实现，src未修改；等用户审批后再编码。

## 本次要实现

1. operator登记不可变runner：harness来源/完整commit/实际源码快照、judge及版本、数据/split、解码、环境、资源、argv模板、输出schema。改配置登记新版本。
2. 新checkpoint用同一runner执行，保存启动前解析后的run-config、实际运行收据、逐题预测/原始得分；目标分继续由protocol的人授权方向计算。
3. 比较必须同时满足protocol、runner和实际执行条件一致；模型和私有输出目录可以不同。不能只看runner名字或完整配置digest（模型变化本来就会改变完整digest）。
4. 研究者只看开发汇总与摘要；完整配置、题目、逐题预测/分数、路径和日志仍由operator读取。内部评测执行不能经job接口泄露。
5. local CPU与现有单节点共享文件根Ray执行，受同campaign预算/取消/超时/恢复约束。CPU fixture不证明LLM/GPU或真实bench效果。

## 拟议调用（当前不可用）

```sh
rsi --token-file OPERATOR_TOKEN runner register --spec runner.json --json
rsi runner show RUNNER_ID --json
rsi runner list --protocol PROTOCOL_ID --json
rsi eval submit --runner RUNNER_ID --model ARTIFACT_ID --json
rsi eval show EVAL_ID --json
rsi --token-file OPERATOR_TOKEN eval config EVAL_ID --json
rsi --token-file OPERATOR_TOKEN eval samples EVAL_ID --json
rsi eval compare LEFT_EVAL RIGHT_EVAL --json
```

完整runner配置草案与字段约定见[design.md](design.md)。外部bench须由adapter输出标准JSONL；固定本地model judge可以绑定artifact及模板版本，但真实judge推理由harness实现，本次不内置推理引擎。不固定版本的API judge不保证可重放。

## 审批时关注的决定

| 项目 | 方案 |
|---|---|
| runner注册权 | operator；训练/审核agent不能登记或改正式执行方式 |
| protocol关系 | 一runner绑定一protocol；方向变更新protocol及新runner，不修改原记录 |
| 输入固化 | 服务端clean git checkout摄入，验证commit和内容；评测不临时拉浮动分支 |
| 完整run-config | 展开的命令、输入引用、seed、资源、环境声明、模型绑定、私有路径；actual receipt另存 |
| 比较身份 | runner+protocol+数据/judge/解码/实际软件环境；模型、位置和时间排除 |
| 下游约束 | compare/aggregate/select/submit/audit不能混runner或复用旧pass |
| 兼容 | 旧无runner评测仍可用；与有runner的新记录不能混比，旧记录不补造配置 |
| 后端范围 | local CPU和既有Ray共享根；无强隔离/多节点/GPU现场成绩承诺 |

## 可执行验收

- CPU 46项RED：注册/schema/版本/源码/协议兼容、local两checkpoint、重启读取、错误输出/超时/取消、公开投影、budget、judge引用、legacy审核pass拒绝与CLI。
- Ray 2项RED：未来通过后必须真正使用临时Ray head验证控制重启和共享根前提；现在均在registry缺失处失败，尚未到达Ray启动。
- 原有315项已实现回归GREEN，无skip/xfail或产品stub。
- CI：Ubuntu/macOS CPU门禁、Ubuntu真实Ray CPU门禁，JUnit与失败注解；release/simulation复用verify，RED不会放行。
- 其余崩溃窗口/实际环境漂移/并发账目/审核绑定等边界，审批后在对应任务中先补RED再实施，见[tasks.md](tasks.md)。

基线见[benchmark-runner-red.json](../../../reports/benchmark-runner-red.json)，规划验证见[benchmark-runner-planning.md](../../../reports/benchmark-runner-planning.md)。

本轮按用户“先spec，然后ci/cd，然后等我审批”的要求停止；没有实际bench配置或GPU操作。审批后再进入apply。
