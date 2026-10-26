# 论文机制库实现验收

实现 `paper.*` / `knowledge.*`、独立 curator 权限、OpenReview v2 I/O、异步冻结正文/有界批次/恢复、准确页图表引用、独立机制归并与修订、有界灵感包和只读资料看板。默认无桥；仅服务保存的独立 operator 实验审查收据放行有范围的 paper_reported 边。方向仍须人授权。

原始62项RED保存在 paper-library-red.json，未覆盖。补充测试先捕获新官方版本错误重核、缺资料HTTP入口（4 fail）；在途重核重置与宕机预留尝试超额（2 fail）；catalog 宕机尝试超额（1 fail），随后修复。非法 query/catalog/venue 形状另补3项RED，修复为结构化 INVALID_REQUEST。HTTP 429 错误响应资源未关闭也已修复，最终警告按错误处理通过。

本地结果：79项新契约、392项既有回归、18项真实Ray CPU通过。1000条合成PDF的批次恢复、双curator去重与私有批次、逐项有限重试，以及真正CLI→HTTP控制服务→HTTP来源→解析子进程链路已验证。后者未产生job/eval/方向授权。

ruff、OpenSpec strict、构建与干净wheel检查通过。wheel在仓库外、无PYTHONPATH注入的独立venv验证PDF解析/建岛/pack，并验证原任务runtime/产物与外部CPU runner。浏览器检查了合成卡、来源版本、局限、检索与默认无桥，截图 paper-library-ui.png。

原 research-islands-and-inspiration 仍32失败/2通过，本次不改变其功能和门禁；完整CI不能据此说全绿。实现提交00053ad的[远端CI](https://github.com/wzk2239115/rsi-red/actions/runs/40362328764)已完成：19个门禁中18个通过，唯一失败为原 research-islands-contracts。论文机制 Ubuntu/macOS、1000项批次/HTTP、原回归、构建/wheel和三组真实Ray CPU门禁通过。最终产品提交a9fcda2的[CI](https://github.com/wzk2239115/rsi-red/actions/runs/40362909987)已确认论文机制Ubuntu、1000条批次/HTTP、全部Ray与既有回归通过；记录时论文机制/评测方向/runner的三个macOS门禁仍排队，未计作通过。此前00053ad包含相同核心实现的macOS论文门禁通过。本地Mac的最终79项全绿。工作流因原研究岛屿RED仍不会全绿或放行发布。

真实会议兼容性与实际录用、GPU训练和收益、物理隔离未在本次验收。配置具体会议政策后需少量在线验收。接口与使用见 docs/paper-mechanism-library.md；独立整理技能见 .agents/skills/rsi-paper-curator/SKILL.md。

最终产品wheel重新构建并安装到仓库外独立venv，在无PYTHONPATH环境验证正文解析、机制岛和pack。模拟demo为0.5→1.0，不代表模型推理结果。末次交付提交仅回填文档/任务/证据，不修改已验证产品代码。
