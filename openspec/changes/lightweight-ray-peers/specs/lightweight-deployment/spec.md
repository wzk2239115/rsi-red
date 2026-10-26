## ADDED Requirements

### Requirement: 轻量平级研究部署
系统 SHALL 提供可选ray-peers初始化配置，生成四个独立researcher身份和工作目录，使用共享Ray执行队列，不要求嵌套Docker或namespace沙箱，不创建主子agent层级。默认local初始化保持兼容。

#### Scenario: 四个独立身份
- **WHEN** 初始化新的ray-peers目录
- **THEN** 生成一个operator和四个不同researcher凭证、四套独立工作与运行目录，凭证文件不可对其他Unix用户公开

#### Scenario: 基础分离边界
- **WHEN** 查看peers配置
- **THEN** 明确标记workspace-only、expected_gpus=8、gpus_detected=false，不冒充系统隔离或实际设备探测

### Requirement: 初始化无执行副作用
初始化 SHALL 仅生成配置，不启动或停止Ray、不创建harness会话、不提交训练、不修改已有部署和认证；离线配置不依赖服务凭证文件可用。

#### Scenario: 旧目录保护
- **WHEN** 输出目录已存在
- **THEN** 拒绝初始化，保留已有配置和凭证内容

#### Scenario: 失效的客户端凭证
- **WHEN** RSI_TOKEN_FILE指向不存在文件并执行离线初始化
- **THEN** 仍可生成新配置，不尝试读取旧服务凭证

### Requirement: 显式运行环境
Ray配置 SHALL 保留地址、节点Python、认证模式/文件引用与可选镜像声明，默认evaluator未配置；环境脚本引用凭证路径，支持带空格的目录。

#### Scenario: 路径与资源
- **WHEN** 在含空格目录初始化并加载某个研究者环境
- **THEN** 工作目录、凭证、缓存和临时目录正确指向该研究者，且未输出token字面值

### Requirement: 先规范与交付门禁再实现
开发 SHALL 先落盘spec、行为失败测试和CI/CD门禁，再实现产品逻辑；不得删除断言、skip/xfail或吞失败来绿灯。

#### Scenario: 功能仍未实现
- **WHEN** CI执行轻量部署契约
- **THEN** 正常收集并失败，上传JUnit并阻止复用CI的release/simulation交付，已有回归独立执行
