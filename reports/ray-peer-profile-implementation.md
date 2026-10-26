# 轻量四会话初始化实现

2026-10-26。此前spec/RED/CI门禁已推送；本次用户授权后实施。

- 追加认证参数、CLI完整性、无网络/进程/调度副作用测试，共11项部署契约先RED后GREEN。
- rsi init --profile ray-peers生成operator+四个researcher、独立目录/环境与共享模型/数据目录，原local初始化兼容。
- 所有文件以0600创建，部署目录0700；环境脚本只引用凭证路径，支持含空格目录。相同Unix用户可互读，非沙箱。
- 模板配置Ray、节点Python、认证引用及节点遥测；evaluator明确unconfigured。8是用户期望值，没有进行GPU探测。
- 170项回归/部署/看板入口测试通过。10项真实CPU Ray集成通过，新增用生成的四套身份运行实际Ray任务并检查recipe、作者与看板归属。
- wheel/sdist构建成功，干净venv安装后在失效RSI_TOKEN_FILE条件下离线创建四身份profile；不需要安装可选Ray运行时才能生成配置。
- 研究skill通过校验；CI保留独立部署契约门禁，并增加干净wheel的profile创建验证。
- H100设备不可访问，未执行GPU任务或真实模型训练，未创建四个harness会话。原研究层32项RED仍阻止整体发布。

配置使用见docs/ray-peers.md。初始化不会覆盖旧部署、启动head、切换认证、提交任务或配置真实evaluator。

线上CI暴露并修正一项契约夹具错误：测试从tests/移到contracts/ray_peer_profile后，子进程PYTHONPATH仍按parents[1]生成，指向不存在的contracts/src。本地editable安装掩盖了问题。修正为仓库根parents[2]/src，保留全部行为断言；以未安装项目包的干净venv复现CI执行方式验证。新增CI失败注解保留JUnit详情便于定位。
