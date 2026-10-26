# Design

四个平级会话由各自 harness 管理；当前服务以 researcher ID 表示作者，尚不声称有 target 注册表或会话心跳。独立会话、目录和凭证不等于操作系统隔离。

recipe 是不可变方法与输入加追加观察历史。planned/trying/completed/abandoned 来自作者上报，jobs 中的状态来自控制面；完成声明不证明任务成功或模型变好。job recipe_id 限制同作者、同campaign、同数据与父模型集合。方法/输入改变需新recipe。

看板只投影必要字段，参数只展示已知训练超参，不回传原始job spec。卡片和资源为当前快照；时间线仍仅回看事件与演示桥，不声称回放历史会话或GPU状态。可见页面每10秒刷新，采样超过30秒标为过期。

GPU 申请量包含未结束任务的排队预留，不等于实际分配；GPU利用率/显存/功耗来自可选nvidia-smi。采集仅服务所在节点，不等于多节点集群；无job→GPU UUID映射时不将某张卡的利用率归给某个agent。节点遥测仅operator可读，researcher看板可继续展示获准研究数据。

nvidia-smi 通过固定argv、5秒超时执行，不执行shell；N/A为null。尚无远程采集器、时序数据库和资源预约到设备UUID的对齐。Mac默认无遥测；CPU fixture只验证解析和缺失行为，不能说明已接H100。

skill保存在项目.agents/skills/rsi-research，并在本机技能目录创建指向它的链接。其他harness需按各自技能发现机制安装；不复制全局凭证，不自动建立四个付费会话。
