## Purpose

提供可预注册的研究对照协议，判断分岛与选择性交流是否在相同总资源下改善未见任务表现，并进一步检验改进是否让后续研究更有效，防止将累计答案、额外计算或被选择器见过的评测当作递归自改进证据。

## ADDED Requirements

### Requirement: Four matched-budget arms
试验计划 MUST 包含集中共享、独立岛屿、随机桥和选择桥四组，初始资料/工具/预算对齐，计入检索、适配、失败、训练和评测成本。

#### Scenario: Plan created
- **WHEN** 提供每组统一预算
- **THEN** 四组预算相同且没有预设赢家或伪造结果

### Requirement: Unseen families stay out of selection
选择器开发任务族与最终任务族 MUST 不相交，最终结果不得在研究过程中反馈给选桥器。

#### Scenario: Family overlap
- **WHEN** 相同 family 同时位于选择和最终集合
- **THEN** 拒绝计划并指出 overlap

### Requirement: No automatic RSI claims
系统 SHALL 将迁移、积累学习和研究效率改进分别报告；没有跨后续新任务族的证据时 RSI 状态为 not_established。

#### Scenario: New archive has no validated transfer
- **WHEN** 查询刚创建的群岛报告
- **THEN** successful_transfer_count=0，未来研究效率为空，RSI 未建立

### Requirement: Confirmatory controls
迁移收益确认 SHALL 包含移除迁入方法及同预算继续独立研究对照，不能只与不继续训练的基线比较。

#### Scenario: Ablation plan generated
- **WHEN** 为一座桥制定确认计划
- **THEN** 包含 remove_transferred_method 和 continue_independent_search
