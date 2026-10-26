# 大批量论文 → 机制岛：规划验收

状态：**spec + RED + CI/CD，未实现产品**。基线为20548bb。用户已确认按独立机制分岛，而非按篇或主题自动聚类。

## 交付

- `paper-mechanism-island-library` 的 proposal、三份能力 spec、design、tasks、review。
- 独立curator、运行时venue/year/track政策、官方录用核验、全文版本/页引用、批次恢复/有限重试、机制归并和受限pack的接口约定。
- 默认零桥；论文自身直接对照/消融 + 独立受权审查才允许 paper_reported 例外，始终不代表本地复现。
- 新命名空间paper/knowledge，与原campaign岛及其32 RED分开；未改旧研究层契约。

## 实测基线

| 检查 | 结果 |
|---|---|
| 新应用/CLI契约 | **54 RED** |
| 新1000条批次/双身份/分页/重试/HTTP适配器契约 | **8 RED** |
| 测试收集 | **62项，0错误** |
| 原已实现功能回归 | **392 GREEN** |
| 合成PDF独立解析 | 通过，页文本与表格文字可取 |
| ruff / OpenSpec strict / diff检查 | 通过 |
| src差异 | 无 |

失败分类是缺operation、缺CLI、缺来源适配器模块，以及当前尚无curator白名单；没有测试夹具/收集错误。详情见同名RED JSON。**1000条处理和HTTP产品调用尚未执行到**，不能将已写测试说成通过大规模或真实来源验证。Fixture是合成论文，未下载实际中稿论文，也未创建真实岛/桥。

原18项真实Ray CPU已在产品基线验收，本轮没有因仅规划改动重复运行；没有GPU调用或真实论文方法实验。

## CI/CD

新增Ubuntu/macOS应用门禁，以及Ubuntu批次+实际loopback HTTP门禁，保存JUnit并注解失败。新门禁没有skip/xfail/continue-on-error；预期在获批实现前保持失败。release与simulation均复用完整verify，保留全部原门禁。配置完成不等于远端已运行，远端状态在推送后独立记录。

## 审阅

入口：[review](../openspec/changes/paper-mechanism-island-library/review.md)。会议清单和年份为运行时政策，不是本轮写死的值；首个计划网络适配器只覆盖OpenReview v2公开记录，其他来源后续适配。具体论文解释质量、真实会议信息和吞吐在线验收须后续单独报告。

本轮不开始apply；审阅后另行授权编码。普通整理/归并的受权服务角色审查，不等于要求用户逐篇人工批准；正式bench目标方向仍必须来自人授权。

## 远端配置校正

初次规划提交d8a29ec的run40355116986在作业启动前被GitHub拒绝：`NO_PROXY`/`no_proxy`是大小写不敏感的重复env键（本地YAML解析未检出）。已删除workflow中的重复小写键；HTTP fixture在Python运行时分别设置环境，不影响测试代理隔离。该次是配置错误，不计为契约RED或已运行门禁。修正提交的实际结果另行核对。


## 远端门禁已运行

修正提交 **3618895** 对应 [CI run40355680187](https://github.com/wzk2239115/rsi-red/actions/runs/40355680187)：GitHub创建19个作业，新增三个门禁均已实际执行并在契约pytest步骤失败，而非安装步骤。

| 新门禁 | 实际状态 |
|---|---|
| paper-mechanism-ubuntu-latest-py3.12 | RED，契约步骤失败 |
| paper-mechanism-macos-latest-py3.12 | RED，契约步骤失败 |
| paper-library-1000-records-and-http | RED，契约步骤失败 |

检查注解包含预期的UNKNOWN_OPERATION/缺来源模块，没有观察到收集错误。GitHub对同一步骤的注解有截断，因此远端注解数量不是测试总数；54+8的精确原始计数来自已保存的本地JUnit。新门禁仍待产品获批实现后转GREEN，不能宣称CI/CD全绿。原始RED JSON保留建基线时的CI状态，以本节后续观察为准。

本轮规划任务4项完成，其余产品实现任务保持未完成；没有开始apply或修改src。远端状态固定到上述提交，后续报告提交不改变产品或验收断言。
