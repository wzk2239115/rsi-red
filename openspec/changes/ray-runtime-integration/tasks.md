# Tasks

## 1. 接口与测试

- [x] 1.1 写11项 Ray adapter 失败契约，保存 RED 记录并实现稳定ID、目录、状态、日志、取消和错误语义，通过契约测试。
- [x] 1.2 固定可选 Ray 2.59.0，配置独立环境验证可安装，不影响普通 tests 的无 Ray 运行。

## 2. 真实运行时与交付

- [x] 2.1 写并通过5项真实 CPU Ray 集成测试，验证 remote task、失败、取消、超时与控制面恢复，清理实例不遗留资源。
- [x] 2.2 CI 新增 Ubuntu/Python3.12 真实 Ray 门禁、JUnit与诊断日志，检查 release/simulation 的复用关系；线上运行尚未触发。
- [x] 2.3 写 docs/ray.md，区分本地运行时与 GPU/多机/driver资源预算边界，校验 OpenSpec。
