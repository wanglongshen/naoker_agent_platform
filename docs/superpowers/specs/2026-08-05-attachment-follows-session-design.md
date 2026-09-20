# 附件跟随会话（豆包模式）— 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

当前附件生命周期是"1 天临时中转"：上传时 `expires_at = now + 1 天`，retention 按 TTL 删附件 + 附件文件夹清理器 1 天删 file_objects。用户参考豆包产品行为，要求改为**会话记忆模式**：

1. **附件跟随会话保留**：会话存在 → 附件在（可回看、可重新引用）
2. **会话删除 → 附件级联删除**（记录 + storage 文件 + 附件文件夹 file_objects 记录）
3. **移除 1 天 TTL**：不主动按时间到期删
4. **retention 降级为孤儿清理**（兜底防磁盘泄漏）

## 现状（已核实）

- `AgentAttachment.session_id` FK 有 `ondelete="CASCADE"`（DB 级）——会话删除时附件**行**自动删
- **缺口**：① storage 文件（`var/agent/attachments/{hex}`）不删 → 孤儿文件 ② 附件文件夹 `file_objects` 记录不删 → 孤儿记录
- `retention.run_once`：`_delete_attachments(cutoff)` 按 `expires_at < now - agent_attachment_retention_days`（1 天）删
- `cleanup_attachment_folders(now)`：删附件文件夹（name="附件"）中 `created_at < now - 1 天` 的 file_objects
- `delete_session`（agent_repository.py:78）：显式删 runs/events/steps/attempts/run_attachments，**不处理 AgentAttachment 与 file_objects**
- config：`agent_attachment_retention_days = 1`

## 设计

### 1. 会话删除级联附件（agent_repository.py `delete_session`）

在现有删除逻辑中追加（runs 删除前）：

```
收集该会话所有 AgentAttachment（id, storage_key）
→ 删除 AgentAttachment 行（显式 delete，不依赖 DB CASCADE 顺序）
→ 删除对应 storage 文件（storage.delete，best-effort）
→ 删除附件文件夹中 storage_key 匹配的 file_objects 记录（软删 is_deleted=True，与文件库删除策略一致）
```

注意：文件库 file_objects 删除用**软删**（`is_deleted=True`）——与现有文件库删除端点一致；storage 文件删除 best-effort（try/except，单文件失败不中断会话删除）。

### 2. retention 孤儿清理（retention.py）

- `_delete_attachments`：不再按 `expires_at` 删。改为**孤儿清理**：找出 storage 目录中存在的、但 DB 无对应附件行/无关联会话的残留文件 → 删文件。
- `cleanup_attachment_folders(now)`：改为"附件文件夹中 `file_objects` 对应的 AgentAttachment（按 storage_key）已不存在"才软删该记录。
- `run_once` 中原 `_delete_attachments(attachment_cutoff)` 调用替换为孤儿清理。

实现方式：孤儿判定用"附件文件夹 file_objects 的 storage_key 集合 - agent_attachments 的 storage_key 集合"差集。这个差集 = 会话已删但 file_objects 残留 → 删。这样同时覆盖 storage 孤儿（file_objects 软删后文件也可删）。

简化：`cleanup_attachment_folders` 变成孤儿清理函数：
```
attached_keys = SELECT storage_key FROM agent_attachments
orphan_records = SELECT * FROM file_objects WHERE folder IN (附件文件夹) AND storage_key NOT IN attached_keys
→ 软删 + storage 文件删除（best-effort）
```
（file_objects 软删后 storage 文件删——注意附件文件夹的 storage_key 就是附件 storage_key，两者一一对应）

### 3. config

`agent_attachment_retention_days: 1 → 90`（长期保留兜底，保留该配置项但不再有主动到期删路径）。

### 4. 不做

- 前端零改动
- expires_at 列保留（写 90 天远期值，不再被 retention 使用）
- 文件库其他文件夹不受影响

## 错误处理

| 场景 | 处理 |
|---|---|
| storage 文件删除失败 | best-effort 跳过（try/except），不中断会话删除/孤儿清理 |
| file_objects 已软删 | 差集查询已排除（is_deleted=False 过滤） |
| 附件被 run 引用 | 会话删除本来就删全部 run，无独立引用问题 |
| 并发上传与删除竞争 | 差集以快照为准，极端竞争留孤儿由下轮清理 |

## 测试策略

**test_agent_repository.py**：
- 删会话 → 附件行删除 + storage 文件删除 + file_objects 附件文件夹记录软删
- 普通文件夹文件不受会话删除影响

**test_agent_retention.py**：
- 孤儿清理：附件文件夹 file_objects 无对应附件行 → 被软删 + storage 删
- 有对应附件的记录 → 保留
- 普通文件夹 → 不受影响

**回归**：test_agent_attachments.py（双写不受影响）、全量后端。

## 范围边界

**本期做**：delete_session 级联附件、retention 孤儿清理、config 90
**不做**：附件文件夹 UI 管理、附件容量配额、手动转存文件库
