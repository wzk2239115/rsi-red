## ADDED Requirements

### Requirement: 群岛看板通过 CLI 启动
系统 SHALL 提供 `rsi kanban` 作为群岛浏览器看板入口。默认仅监听 loopback、自动打开浏览器，并复用 RSI_ENDPOINT / RSI_TOKEN_FILE 连接控制服务；凭证 SHALL 留在本地代理端，不进入 URL 或浏览器脚本。`--port` 指定看板端口，`--no-open` 禁止自动打开浏览器，`--demo` 使用显式标注的独立示意数据且不提交训练。退出看板 SHALL 不取消后台研究任务。

#### Scenario: 发现看板命令
- **WHEN** 用户执行 `rsi --help` 或 `rsi kanban --help`
- **THEN** 帮助列出入口及启动选项，且不要求凭证、不启动服务器

#### Scenario: 启动群岛
- **WHEN** 用户执行 `rsi kanban`
- **THEN** 启动本地看板并打开浏览器，展示群岛、桥的证据侧栏和研究时间线
- **AND** 数据仅来自调用身份获准读取的服务对象；接口缺失或断线时显示明确状态，不伪造研究数据

#### Scenario: 显式演示
- **WHEN** 用户执行 `rsi kanban --demo --no-open`
- **THEN** 输出本地地址而不打开浏览器，页面持续标注示意数据，不提交训练或评测任务

### Requirement: 可视化保留证据边界
系统 SHALL 将岛映射到研究工作区，将桥映射到有来源的迁移记录；选择岛显示假设/任务/失败，选择桥显示来源/复用/对照与验证状态。模型表现和研究机制证据 SHALL 分开展示；无证据不生成 RSI 指数。时间线回看 SHALL 只显示截止该时刻已有的记录。

#### Scenario: 已复用但未完成消融
- **WHEN** 桥记录显示复用且缺少独立贡献验证
- **THEN** 页面同时展示已复用与待消融，不将其显示为已证明收益
