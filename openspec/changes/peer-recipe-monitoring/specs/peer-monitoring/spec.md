## ADDED Requirements

### Requirement: 平级研究身份与配方记录
系统 SHALL 支持独立 researcher 身份登记自己的 recipe；不得从客户端指定作者或以主子 agent 替代用户选择的平级会话。配方包含假设、方法、同campaign的数据与父模型引用；观察为追加历史。

#### Scenario: 同伴只读
- **WHEN** 同campaign的同伴读取或尝试更新他人的recipe
- **THEN** 允许读取且拒绝修改，保留原作者和历史

#### Scenario: 任务关联
- **WHEN** job.submit指定recipe_id
- **THEN** 校验作者、campaign与输入一致，recipe.show可查询关联任务真实状态

### Requirement: 资源事实分层
看板 SHALL 分开展示未结束任务GPU申请量与真实节点利用率、显存MiB、功耗W和采样时间。未经采样不得填0%或生成设备；不将整节点利用率归给某个agent。

#### Scenario: 缺少GPU
- **WHEN** 没有配置遥测或nvidia-smi不可用
- **THEN** 返回unavailable、空设备列表和无采样时间

#### Scenario: 真实节点采样
- **WHEN** operator配置nvidia-smi遥测并查询资源
- **THEN** 以有限超时采集真实指标，标明仅控制服务节点范围，N/A保持未知

#### Scenario: 研究者无节点权限
- **WHEN** researcher查看看板
- **THEN** 不读取全节点GPU详情，显示资源受限，继续展示其获准的研究数据

### Requirement: 技能配置与真实执行分离
rsi-research技能 SHALL 将用户目标、基座、数据、评测与预算整理为研究简报，核对实际CLI与harness能力；缺少执行条件时如实标记，不声称四个会话已启动或GPU实验已运行。

#### Scenario: 四个平级会话
- **WHEN** 用户要求配置四个研究会话
- **THEN** 每个target使用独立身份与工作区，不自动创建主子agent层级；仅使用harness已提供且用户授权的会话管理能力
