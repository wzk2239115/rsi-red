# Design

## 用户决策

先在一个平台容器中共享8张H100；以后不同研究agent可接不同集群。当前只做workspace-only分离，不要求Docker-in-Docker、namespace或额外内核能力，不创建主子agent。

## 目标接口（尚未实现）

rsi init --profile ray-peers --output DIR，可选--ray-address、--python-executable、--cluster-image、--ray-auth-mode、--ray-token-file。Python初始化边界initialize增加同义关键字；原默认调用保持兼容。

输出service.json、operator token、peers.json、peers/agent-{1..4}/token和environment.sh，以及workspace/tmp/cache/logs/outputs。共享目录为shared/models、shared/datasets；共享仅是工作约定，不声称只读安全边界。

service.json配置四个researcher和一个operator，Ray backend，显式节点解释器，默认auto认证、不改变head；token模式要求受保护文件路径。telemetry为节点nvidia-smi，evaluator为unconfigured。peers.json标明isolation=workspace-only、expected_gpus=8、gpus_detected=false。未探测时不能把用户期望值当成硬件发现。

environment.sh仅写凭证文件引用，不写token内容；正确引用带空格的路径。设置身份、工作目录、临时目录、缓存、日志/输出和共享资源路径；不自动修改外部harness。目录/文件权限为0700/0600，但相同Unix用户可以互读，不能说已实现沙箱或隐藏评测保护。

初始化严格拒绝覆盖既有目录；离线配置不依赖可能失效的RSI_TOKEN_FILE，不联网、不提交任务。默认节点Python为执行初始化的解释器，所以应在GPU容器运行，远程配置必须显式指定节点路径。

## 验证与阶段

1. 本轮：spec通过strict、4项核心RED、CI/CD门禁；159项已实现回归保持通过。
2. 编码前补齐认证参数组合、离线无网络/无任务副作用、CLI选项完整性等测试，再实现。
3. 用隔离临时目录验收生成配置；再通过实际Ray CPU验证身份/配方/任务接口，不代替GPU验收。
4. 设备恢复后：单卡冒烟、8卡资源申请、短程真实训练、产物登记与真实评测；模型/数据和预算未配置前不执行。

## 本轮纠正

此前先写4项测试后直接改了dev.py/cli.py，违反spec/CI先行顺序。未提交产品改动已反向撤回；草稿保留在.rsi/deferred-ray-peer-profile/implementation.patch（不入Git）。后续实现需依照最终spec和测试重新审查，不直接把草稿视为通过验收。
