# Accepted Paper Ingestion

## Purpose

将独立整理会话发现的论文转成有版本、可核验录用与正文来源的研究材料，为大批量机制提取提供可恢复基础。官方录用只代表符合用户设定的入库筛选范围，不代表所有方法结论正确或已在本项目复现。

## ADDED Requirements

### Requirement: Configurable venue policy
系统 SHALL 仅允许 operator 注册不可变来源政策，明确 provider、venue_id、year、track、全文要求、批量/并发/大小/重试限制。不得内置“顶会名单”猜测或让 curator 修改政策。

#### Scenario: Workshop is outside main track policy
- **WHEN** 论文来自同一会议但 track 不在政策允许范围
- **THEN** 标为 ineligible，不成为可发布知识岛来源

### Requirement: Independently verified acceptance
系统 MUST 通过受权来源适配器读取官方记录，保存官方身份、状态、版本、观察时间和原始响应摘要。请求中的 accepted=true、arXiv 标题、自报录用或引用数量不得替代核验；未知 provider 明确拒绝。

#### Scenario: Curator claims accepted
- **WHEN** curator 自报 accepted，而来源记录是 rejected、withdrawn 或未公开
- **THEN** 不晋升为 verified/ready，不产生知识岛或桥

### Requirement: Versioned full text and citations
系统 SHALL 保存正文 PDF 与提取文本的校验快照、revision 和页码来源。原 URL 变化或文件消失不改变旧版本；只有摘要、损坏 PDF、摘要不匹配或正文不能定位时不得发布机制卡。

#### Scenario: Camera ready changes
- **WHEN** 同一官方记录的正文版本改变
- **THEN** 产生新 revision，保留旧快照及其岛屿引用，不静默重指旧证据

### Requirement: Identity and conflict handling
系统 SHALL 根据官方稳定 ID/版本/内容摘要保证幂等，不能仅靠标题、向量相似或 PDF 同名合并不同论文。身份和正文冲突进入 quarantine，跨来源别名须有明确的同一性证据。

#### Scenario: Same title different records
- **WHEN** 两篇稳定 ID 不同的论文标题相同
- **THEN** 保留独立身份，不自动覆盖或去重

### Requirement: Resumable bounded batch ingestion
批次 SHALL 立即返回 ID，逐项提交状态、错误类别和重试次数。中断后从已持久化状态恢复，幂等重试不重复成功项；遵守并发、大小、分页与有限退避，不因一项失败回滚全部成功项。

#### Scenario: Thousand item batch restarts
- **WHEN** 1000 项批次部分成功、部分限流后控制面重启
- **THEN** 成功项不重复拉取/登记，仅重试允许重试的失败项，最终计数与逐项状态一致

### Requirement: Curator identity and inert content
独立 curator SHALL 只获得论文/知识库写入与公开材料读取权限，不获得 job/eval/方向授权/原始受保护记录的操作能力。正文、PDF 附件和提取内容 MUST 作为引用数据处理，不运行代码或创建训练/评测。

#### Scenario: Prompt injection in paper
- **WHEN** 正文写着执行命令、读取密钥或改评测方向
- **THEN** 只保存文本，无命令执行、无任务提交、无权限或方向变化

### Requirement: Recheck and withdrawal
系统 SHALL 追加来源状态重核记录，保留旧正文与解释版本。撤稿、撤回或录用资格失效的来源不得继续进入默认推荐；依赖它的岛/关系必须显示失效原因，而非删除历史。

#### Scenario: Accepted record is withdrawn
- **WHEN** 来源重核变为 withdrawn
- **THEN** 默认 pack 排除仅由它支持的机制，历史 show 仍能查看旧版本与警示
