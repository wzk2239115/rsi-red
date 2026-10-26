# Proposal

## Why

研究agent应能自行改变训练代码、算法、数据、奖励设计和实验顺序；rsi负责执行与证据，不用训练模板或审核员偏好限制研究方法。当前任意argv入口已可用，但逐任务依赖环境、通用产物和能力预检仍有缺口，影响现有单节点8卡容器上的探索。

## What Changes

- 保留自定义Python/Shell/torchrun入口、自由method和JSON参数；starter仅示例，不是算法白名单。不新增逐实验人工审批。
- 新增`job.validate`静态预检，校验输入/资源/运行能力但不创建job、不预留预算、不连接GPU。对不支持的拓扑明确拒绝，不静默忽略。
- 新增逐任务runtime：冻结requirements内容，可指定节点已有Python，在任务私有venv中安装依赖，记录实际解释器和包清单；不修改其他agent环境。
- 保留`MAX_TOKENS`、`TOKENIZERS_PARALLELISM`等普通配置，凭证字段使用明确规则处理，不能用子串token误删训练参数。
- 新增运行期输出manifest与`job.outputs`，收集任意类型研究产物，关联job/代码/运行环境/数据/父模型，支持幂等发布和重启恢复。HF model原有完整性检查保留，通用文件/自定义checkpoint不被强制当HF模型。
- 正式eval与训练自定义reward分开：自由改变训练reward不等于改正式评分器；疑点、评分错误、已证实违规分开表达。失败或没涨分不构成作弊。
- 本轮仅spec、可执行RED/已有能力GREEN契约与CI/CD门禁。用户审阅并再次授权后才修改产品实现。

## Capabilities

### New Capabilities
- open-job-execution: 自由训练入口、无副作用预检、明确拓扑/资源边界与正式评测边界。
- job-runtime: 每任务环境快照、独立准备、真实运行清单与参数保真。
- job-output-provenance: 运行期通用产物、幂等发布和生成来源绑定。

### Modified Capabilities
无已归档主spec；已有在途core/auditor/monitoring change继续有效。本change通过新增delta扩展现有API，旧请求保持兼容。

## Impact

待授权后涉及service、CLI、local/Ray执行包装器、artifact验证、看板运行信息与研究skill。CI新增独立flexible-training-contracts门禁，release/simulation复用verify，RED期间正常阻断。CPU/真实Ray验证与真实8卡验收分开，不启动Docker-in-Docker，不把物理隔离作为前置。

第一阶段仅单节点command模式，包括在一次资源分配内运行torchrun。多节点rendezvous、弹性训练、动态Ray actors资源包络及子资源完整记账单列后续change；本阶段不得宣称已支持，也不得无声接受相应请求。不是禁止agent使用Ray库，而是不把未受控子资源计为已落实的预算保证。
