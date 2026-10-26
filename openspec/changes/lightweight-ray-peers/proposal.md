# Proposal

## Why

用户首要目标是在平台提供的8卡Docker中跑通真实研究；接受基础目录/身份分离，不将namespace沙箱或Docker-in-Docker作为前置。四个研究会话仍为平级。用户再次明确流程必须先spec、CI/CD门禁，再编码。

## What Changes

- 规划rsi init --profile ray-peers，生成operator和四个researcher的独立配置、工作目录、缓存、临时目录、日志和输出目录，共享模型/数据目录和Ray队列。
- 配置明确的Ray地址、节点解释器、认证文件引用、可选镜像声明；真实evaluator默认未配置，不能生成模拟成绩。
- 初始化不启动head、不创建会话、不提交训练、不更改已有部署或认证。
- 本轮仅落盘spec、RED契约与阻止交付的CI门禁；产品实现草稿已撤回并保存在忽略目录，尚未合入。

## Capabilities

### New Capabilities
- lightweight-deployment: 共享Ray的平级会话轻量初始化与事实边界。

### Modified Capabilities
无。默认rsi init仍保持当前CPU配置。

## Impact

新增contracts/ray_peer_profile和独立CI job，release/simulation通过复用CI受此门禁阻止。profile尚不可调用，不宣称8卡训练通过；真实starter/evaluator/数据仍需后续落实。
