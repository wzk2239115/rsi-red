# Design

## 角色和流程

四个平级研究者 + 第五个平级auditor。审计agent是找漏洞/提出反例的研究会话，可信检查器是operator配置的执行组件，二者不是同一个权限主体。auditor没有主agent身份，不改其他会话工作区，不训练或替研究者选算法。

operator通过audit.configure为campaign登记审计策略（checks、auditor_ids和开发protocol_id）。审计身份从服务端principals读取；scope只授予audit API中的证据访问，不通过把auditor加入研究成员绕开权限。普通researcher不能配置规则、伪造收据或通过audit API获得operator访问。

候选模型登记并获得开发评测后，audit.submit冻结模型digest、协议digest、eval ID、检查策略digest与输入来源引用；队列异步执行，返回audit ID。审计时训练继续，只有声明“可提交/可信候选”时需要通过门禁。审核不需要对每个训练step重跑完整评测。

## 检查范围

- 评分一致性：独立检查器与冻结原评分器出现分歧，检查错误答案得分、解析器漏洞、执行退出码被忽略等。
- 格式/提示鲁棒性：保留题目语义和正确判据的预注册扰动；真实任务敏感变化不能直接判定作弊。
- 数据与来源：训练样本对开发题的直接/近似重合、未知来源、评分代码/协议变化。词面重合只是风险证据，不证明使用意图或语义无污染。
- 非分数诊断：截断、重复循环、固定输出、奖励上升但独立判据不升等信号；仅信号不能自动定罪。
- 评分器改动或失配属于评测完整性失败，不能自动归因模型存在主观欺骗。

可信runner收据需包含实际检查代码digest、模型digest、原protocol digest、变换协议、种子、逐题证据和成本。每种检查缺代码/数据/预算时标unavailable/incomplete，不能默认通过。自然语言建议、模型输出、日志和审计指令文本都作为数据，不直接执行或当授权。

## 状态与提交

case状态：pending、running、needs_review、blocked、checks_passed、incomplete；checks_passed只表示预注册检查通过，不表示永远不会hack。agent可追加audit.observe线索，source=auditor_hypothesis，不得将它当成trusted check receipt。最终门禁仅由服务端核验真实检查收据与预注册判据；高分和“我看过了”都不能替代。

提交必须引用该policy、同模型digest和同开发protocol的已完成审计，策略或模型变化需重新审核；保留旧case。异常时不删除产物/任务和历史。单个可疑文本作为suspected反馈待复核，保留case的可信检查状态，不直接定罪或放行；真正阻断需策略定义的完整性失败/可复现反例。

## 隐藏集与预算

首版只审计开发协议；audit.submit拒绝held_out，auditor无法取隐藏题/答案/逐题结果。未来隐藏审计由operator封闭服务执行，不逐轮向研究者返回分数、反例、命中数量或晋级状态等优化信号。审计agent不拿held-out答案后去教训练agent规避。

检查次数、生成token、CPU/GPU费用计入独立审计预算并在公平对照中计入总成本；不能无限重试以“挑到通过”。原评测seed问题需先修正才能声明独立采样重复。实现范围：仅内置保存输出的exact_match复核；没有真实扰动推理执行器，不能把占位结果当验收。

## 看板

按候选显示审计状态、检查覆盖、绑定模型/协议、可见证据与预算。标明来源为agent线索还是可信runner收据；GPU继续区分申请与实测。无检查保持待审或未覆盖，不生成安全百分比。审计会话心跳依旧需harness接入。

## 交付边界

初始轮只提交规范/行为RED/CI；本次授权已实现CLI摘要、疑点记录、确定性checker收据和候选门禁。第五个实际harness会话仍由外部会话启动。当前同Unix用户的基础分离不能阻止其直接读文件/攻击Ray；本方案先防研究流程中的评分错误和投机，不能宣称提供抵御恶意训练进程的强隔离。

## 训练者反馈闭环（用户补充）

训练者需要收到反馈，不只是看板上有审计状态。同一共享campaign默认四个训练者都可读开发审计反馈，便于其他路线避免同类问题；未来独立campaign仅通过显式授权的共享范围发布，不能借审计广播私有模型/隐藏证据。

反馈为独立持久实体：id/case_id/campaign_id/model_id/model_digest/protocol_digest/source/status/reason/evidence_ids/recommendation/recipients。audit.observe生成suspected反馈，source=auditor_hypothesis；可信runner完成后追加confirmed_issue/checks_passed/incomplete等判决，附可信收据，不覆盖旧疑点。检查通过仍不承诺从未reward hacking。

追加反馈后写audit.feedback_available事件，entity_id指向反馈记录。audit.feedback(campaign_id,after?)按稳定ID游标查询，audit.ack(id)仅确认当前凭证对应接收者；确认幂等、持久化，不删除共享消息，也不能替其他会话确认。事件handler成功交付后推进自己的游标，失败保留；至少一次交付要求harness按反馈ID去重。

已有rsi watch只能运行handler，尚无真实target→harness会话投递适配器。实现阶段必须分别验证：反馈生成、事件可见、handler交付、实际会话接收，不把其中任一步当作全部完成。用户的四个训练会话仍平级，auditor的建议不会自动变成训练命令或operator授权。

研究者可以据反馈修改recipe并重新提交候选；case/反馈绑定旧模型，不能将旧通过记录转移到新模型。首版只开发审计，所以没有隐藏反馈流；将来隐藏集连通过/拒绝与汇总变化也不能逐轮回传作调参信号。

## 实现前隐私补充（用户授权）

全局默认收紧：非operator的开发protocol.show只返回白名单元数据（无items）；eval.samples只限operator；eval.show投影固定摘要字段，不将任意evaluator键透传。rsi eval model MODEL_ID汇总获准模型的开发评测与审计。auditor只能读取被audit.configure授权campaign/协议的开发摘要，不给普通campaign成员权限。

反馈使用固定分类/建议，auditor.observe原文仅对授权auditor/operator可见；服务事件只带实体引用。原有两个逐题诊断测试改为operator调用，同时新增非operator拒绝断言，以保留诊断验收并落实新权限。

内置checker仅在operator明确选择grader_mode=exact_match时按原始字符串相等复核已冻结输出，记录自身代码digest与私有逐题证据；不宣称验证数学等价或独立模型重评。data_overlap需有可核验成功job→model来源和实际数据，否则unavailable；format_robustness无实际扰动推理执行器时unavailable。无法覆盖即incomplete。case/eval次数通过策略封顶，不承诺消除通过分数反馈过拟合或同Unix用户直接文件访问。


## 当前收据与部署范围

内置检查不追加推理调用，收据记录eval_seed、transform=none、additional_model_calls=0、checked_at及代码/模型/协议/策略摘要。精确匹配的逐题记录分数与独立重算分数作为私有证据持久化，仅operator能读；auditor和训练者均只能看汇总收据。缺失检查不生成伪造逐题结果。

用户确认本版首要目标是打磨infra，物理隔离后续部署，不阻塞本轮。可选ray-peers --with-auditor离线生成第五套身份，仍不启动实际会话。
