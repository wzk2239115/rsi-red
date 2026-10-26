# rsi-red

供外部研究 agent 调用的 AutoPostTrain CLI，参考 Athanor 的 job/eval/data/artifact、异步实验与持久化证据。

**当前是可运行的 CPU 模拟版**：真实子进程执行与恢复、不可变数据/模型、逐题评测、团队记录和通知接口；Slurm/Kubernetes 已做适配器契约测试，尚未接真实 GPU 集群。模拟训练的是小型二分类策略，不代表大模型训练效果或完整 Athanor 沙箱。

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
rsi demo --output .rsi/my-campaign --json
```

## 群岛看板

```sh
rsi kanban --demo              # 示意数据预览，默认打开浏览器
rsi kanban --no-open --port 8790 # 连接控制服务，仅输出本地地址
```

真实模式使用 RSI_ENDPOINT 和 RSI_TOKEN_FILE；先按[运行文档](docs/usage.md)启动后台服务。
已实现只读的项目岛屿、任务列表、事件时间回看与演示桥证据侧栏；新增按研究身份的recipe卡片、任务GPU申请量和可选节点nvidia-smi遥测（见运行文档）。卡片来自服务身份记录，尚无会话心跳。
真实方法桥接口仍待实现，因此真实模式不绘制虚构桥；当前任务状态与历史事件分开展示。
凭证保留在本地代理，服务仅监听127.0.0.1。退出看板不会取消训练。

- [方法岛屿与灵感库规划（新研究层仍为RED）](docs/research-islands.md)
- [Ray 后端与真实运行时 CI](docs/ray.md)
- [运行、后台服务及 agent 接入](docs/usage.md)
- [行为接口契约](docs/contract.md)
- [测试与交付说明](docs/testing.md)
- [实集群验收边界](docs/cluster-acceptance.md)
- [最初67项全红基线](reports/red-baseline.md)
- [本次验证报告](reports/implementation.md)
- [OpenSpec实施清单](openspec/changes/athanor-core-test-first/tasks.md)

## 验证

```sh
python -m pytest tests --junitxml=reports/junit.xml
python -m ruff check .
python -m build
```

测试不依赖 GPU 或真实集群，不下载外部模型/数据，也不调用教师 API。CI 在 PR/main 上运行 Linux/macOS × Python 3.12/3.13，通过后验证安装包与完整 CPU 演示。版本标签通过完整 CI 后交付 wheel/sdist、校验和和草稿 GitHub Release；另有手动模拟交付工作流。

真实部署与训练验收将在有集群环境后单独进行。本地已验证不等于 GitHub Actions 已运行或集群已部署。

研究层处于测试先行阶段：`pytest contracts/research_islands` 当前仍有32项失败，看板入口2项通过，对应CI发布门禁保持红灯；`pytest tests` 是已实现功能与素材校验。两者状态分开报告。

轻量8卡部署：`rsi init --profile ray-peers --output .rsi/eight-gpu-peers` 已实现四个平级研究身份与workspace-only目录配置；不创建会话、不提交GPU任务。使用方式见[单容器四会话部署](docs/ray-peers.md)。11项部署契约由独立CI门禁验证；真实模型训练和评测仍需接入。

评测完整性审计规划：`openspec/changes/evaluation-integrity-auditor/` 定义第五个平级auditor和可信检查器，先提交8项RED契约及CI/CD门禁。当前尚未实现，不会自动启动第五个会话或改变现有campaign提交行为。
