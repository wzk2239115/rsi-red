# 评测方向：本轮审阅入口

状态：仅规划、RED 契约与 CI/CD；产品尚未实现，无服务重启或 GPU 操作。

你可以说：“攻击 bench 的 ASR 我要提高；检测 bench 的 AUROC 也要提高。”即便外部 bench 推荐降低 ASR，也以你明确授权的研究目标为准。只说“优化某 bench”不足以决定方向，harness 需要澄清。

## 人授权是硬约束

agent 可提议目标、展示映射，但不能自行设定或翻转。人的明确自然语言即可构成对应目标授权，无需对已明确的同一目标反复确认。服务端通过独立 operator 配置通道登记授权，精确绑定 task/metric/direction/来源版本；训练者与审核者无权自授。你授权“开发这个功能”，不代表授权任何具体 bench 的目标。

这保证的是应用权限与可追溯记录；若 operator 凭证被其他进程拿走，服务不能仅凭文本证明请求来自人，本版不把 workspace-only 说成物理安全隔离。

## 关键设计

| 项目 | 规划行为 |
|---|---|
| 有效方向 | 显式 protocol 默认值 + item 覆盖；同 task 必须一致，无有效方向拒绝 |
| 目标分 | [0,1] 原始分：maximize=raw；minimize=1-raw；始终保留 raw |
| 修改目标 | 新的人授权、新协议 digest；沿用 campaign.create 新窗口，旧记录不重算 |
| 比较和选择 | 同协议归一化分、重复均分；只读推荐后显式提交，审核门禁继续生效 |
| 公开信息 | task/metric/role/方向、汇总 raw/normalized；不返回题目答案 |
| 看板 | 真实开发评测数据、↑/↓、role、两套分及协议版本，不拼跨协议曲线 |

重要现状：campaign.submit 目前只提交指定模型，无最佳模型排序；本 change 将新增只读 campaign.select。eval.list 和真实评测看板数据也需新增，不能只画箭头。

## mixed-polarity 自测算例

ASR ↓、AUROC ↑：原始 (.6,.6) → (.2,.8)，目标分 (.4,.6) → (.8,.8)，suite 从 .5 → .8。若人授权 ASR ↑，同一原始变化就不是上述进步。方向不同的实验不能作同协议比较。

## 交付与后续

- [proposal.md](proposal.md)：范围与现状。
- [specs/evaluation-direction/spec.md](specs/evaluation-direction/spec.md)：行为验收。
- [design.md](design.md)：授权、协议、评分、迁移与信任边界。
- [tasks.md](tasks.md)：分阶段任务。
- `contracts/evaluation_direction/test_contract.py`：30 项可执行新契约。
- `reports/evaluation-direction-red.json`：实际本地基线，不用“应失败”冒充执行结果。
- `.github/workflows/ci.yml`：独立 Ubuntu/macOS 方向门禁；release/simulation 复用 verify，失败阻断交付。

自然语言正反意图与歧义澄清留人工 harness 验收；不拿文档关键字测试冒充语义理解。旧记录迁移、raw grader 一致性、选择平分/重复等扩展负例在对应实现任务中先补 RED。

遵守用户既定顺序，本轮停在可审阅 spec/RED/CI。仓库 `AGENTS.md` 规定“先OpenSpec及验收范围，再可执行RED测试和CI/CD阻断门禁，再产品编码转GREEN”；`.agents/skills/openspec-propose/SKILL.md` 要求规划完成后等待新的 apply 请求。审阅后另行授权实现，当前没有把任何具体 bench 方向设进产品。
