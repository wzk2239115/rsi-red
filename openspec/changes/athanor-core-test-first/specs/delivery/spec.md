## Purpose

通过可执行行为测试和持续交付门禁控制项目从红色测试基线走向可安装版本的过程，保留真实失败证据，并避免将本地模拟、尚未运行的线上工作流或未配置的集群部署误报为完成。

## ADDED Requirements

### Requirement: Test-first evidence
项目 MUST 在业务实现之前交付可收集的失败测试，不得通过跳过、预期失败、无条件占位断言或掩盖退出码制造通过。

#### Scenario: Implementation absent
- **WHEN** 执行红色基线测试
- **THEN** 测试正常收集并因产品缺失失败，报告真实数量和退出码

### Requirement: CI blocks release on failure
CI SHALL 在 Linux/macOS 与受支持 Python 版本执行测试并保存 JUnit；发布必须重新通过相同检查并校验标签与包版本。

#### Scenario: Tests fail on release tag
- **WHEN** 版本标签触发的测试有失败
- **THEN** 不构建发布流程的交付产物，不创建 GitHub Release

### Requirement: Explicit delivery boundary
CD SHALL 构建带校验和的安装包并创建草稿发布；真实集群部署和训练验收必须单独配置及记录，不得由 CPU 测试代替。

#### Scenario: No cluster credentials configured
- **WHEN** 版本通过测试并构建
- **THEN** 只交付安装包，不向 Slurm/Kubernetes 提交任务或修改服务
