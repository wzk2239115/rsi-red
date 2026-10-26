# Tasks

## 1. Spec与CI/CD先行
- [x] 1.1 记录workspace-only与8卡优先决策，撤回先行产品改动并保存本地草稿。
- [x] 1.2 创建proposal/design/spec，验证OpenSpec strict。
- [x] 1.3 保留4项可执行RED契约，普通回归独立验证。
- [x] 1.4 新增CI门禁和JUnit留存，沿用release/simulation的needs verify依赖。

## 2. 编码（本轮未开始）
- [ ] 2.1 补齐认证组合、CLI参数和离线无执行副作用测试。
- [ ] 2.2 实现profile与四套身份/目录，保持默认init兼容，转GREEN。
- [ ] 2.3 临时目录和实际CPU Ray验收，构建安装包，更新skill和部署说明。

## 3. H100现场验收
- [ ] 3.1 连接实际节点，单卡/8卡冒烟；验证共享队列和日志。
- [ ] 3.2 配置真实模型/训练数据/冻结评测后，完成短程真实训练闭环。
