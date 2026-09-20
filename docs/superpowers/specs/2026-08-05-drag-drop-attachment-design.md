# 拖拽附件 → 用户附件文件夹（双写 + 1 天删除）— 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

当前附件系统（`agent_attachments`，会话级）：
1. 只能点击选择上传（antd Upload），**无拖拽**
2. 白名单类型（文本/代码）、单个 2MB、最多 5 个——拖图片/PDF 会被拒
3. 存储仅 `agent_attachments`（90 天保留），用户不可见，无法在文件库管理

用户需求：
1. **拖拽文件进对话框**（批量 + 单个）
2. **丢进的文件 → 该用户的附件文件夹**（文件库 `file_objects` 里的特殊文件夹）
3. **附件 1 天删除**（所有附件统一 1 天）
4. **模型能读取的文件 = 拖入对话框的附件**（附件即对话输入，经 attachment 上下文注入模型）

## 决策

1. **拖拽支持**：composer 整块区域 drag-and-drop（单/多文件），拖入后立即上传
2. **类型/大小**：任意类型（去白名单），单个 ≤20MB，批量上限 10 个
3. **双写存储**：上传 → ① `file_objects` 用户"附件"文件夹（文件库可见）② `agent_attachments` 记录（引用同一 storage 文件，`expires_at = +1 天`）→ `attachment_ids` 传给 run，模型经 attachment 上下文读取（现有 `_read_attachment_context` 路径）
4. **1 天删除**：`agent_attachment_retention_days` 90 → 1（agent_attachments）；附件文件夹的 `file_objects` 记录由新清理器 1 天删除（复用 RetentionService 模式）
5. **点击选择入口统一**：现有附件按钮也走同一双写逻辑（所有附件统一 1 天——用户确认）
6. **附件 = 对话输入**：模型读到的 = 拖入/选择的附件文件（经现有 attachment 上下文，`extract_file_text` 提取文本；不可提取的类型标记不可读但不阻塞）

## 架构

```
拖拽/选择文件（任意类型 ≤20MB，批量 ≤10）
  → 上传端点（改造 uploadAttachment → 双写）
  → ① file_objects：owner=当前用户，"附件"文件夹（自动创建，TTL 1 天）
  → ② agent_attachments：storage_key 同一文件，expires_at = now + 1 天
  → attachment_ids → run 创建 → _read_attachment_context 注入模型
清理（后台任务）：
  → RetentionService（已有）：agent_attachments.expires_at < now → 删记录 + storage
  → 附件文件夹清理器（新）：file_objects 文件夹名="附件" 且 created_at < now-1天 → 删
```

## 组件明细

### 1. 前端拖拽（chat-composer.tsx / attachment-input.tsx）

**chat-composer.tsx**：
- composer 容器加 drag handlers：`onDragOver`（`preventDefault` + 视觉高亮 class）、`onDrop`（`preventDefault`，取 `event.dataTransfer.files` → 传给 AttachmentInput 的 handlePendingFiles 逻辑）
- 高亮状态 `isDragOver`（useState）

**attachment-input.tsx**：
- `ACCEPTED_EXTENSIONS`：改为 `*`（任意类型）——`accept` 属性移除或设 `undefined`
- `MAX_BYTES`: 2MB → 20MB（20_000_000）
- `MAX_FILES`: 5 → 10
- `handlePendingFiles` 提取为可复用函数（选择/拖拽共用）
- sessionId 分支（现有 Upload）与无 sessionId 分支（pending files）**统一走 pending files 路径**——拖拽/选择 → pendingFiles → 发送时逐文件上传（双写端点）→ attachment_ids

**发送流程**（chat-composer handleSubmit）：
```
提交 → 逐文件上传（双写端点）→ 收集 attachment_ids → onSubmit({goal, attachmentIds})
```

### 2. 后端双写端点（app/api/agent.py 改造 uploadAttachment）

```python
@router.post("/sessions/{session_id}/attachments", status_code=201)
async def upload_attachment(...):
    # ① 解析文件（任意类型，≤20MB 校验）
    # ② 附件文件夹双写：
    #    - file_objects：folder = _ensure_attachment_folder(user)（自动创建"附件"文件夹）
    #    - agent_attachments：expires_at = now + timedelta(days=1)
    # ③ 返回 {id, filename, ...}
```

`_ensure_attachment_folder`：查用户"附件"文件夹，不存在则创建（幂等）。

### 3. 1 天清理

**config.py**：`agent_attachment_retention_days: int = 90` → `1`

**附件文件夹清理器**（新，`app/services/agent/attachment_folder_cleanup.py` 或并入 retention.py）：
```python
async def cleanup_attachment_folders(session, storage, now, batch_size=50) -> int:
    # file_objects 中 folder 属于"附件"文件夹且 created_at < now - 1 天
    # → 删记录 + storage 文件（仅附件文件夹，不碰普通文件）
```
- 挂载点：worker 主循环（与 `_recover_expired` 并列）或 RetentionService.run_once 内
- 幂等、分批、容错（单文件失败不中断）

### 4. 附件 = 对话输入（模型读取）

无需新代码——现有 `_read_attachment_context`（loop.py）按 `agent_attachments` 记录读 storage + `extracted_text` 注入 prompt。双写保证了记录存在。不可提取文本的类型（图片等）`extraction_status` 保持非 ready → 跳过（现有逻辑）。

## 错误处理

| 场景 | 处理 |
|---|---|
| 文件 >20MB | 前端拒绝提示；后端 413/422 兜底 |
| 附件文件夹创建失败 | 回退仅 agent_attachments（不阻塞上传） |
| storage 写失败 | 返回 500，前端"上传失败" |
| 不可提取文本（图片/PDF） | 正常存储，attachment 上下文跳过（现有逻辑） |
| 清理时文件已被手动删除 | 容错跳过（storage.is_file 检查） |

## 测试策略

**前端**（attachment-input.test.tsx / chat-composer.test.tsx）：
- 拖拽 drop 多文件 → pending 列表
- 选择文件 → pending 列表（复用逻辑）
- 发送 → 逐文件上传 → attachment_ids 传入 onSubmit
- 超 20MB → 拒绝提示

**后端**（test_agent_api.py / test_retention.py）：
- 双写：上传后 file_objects 附件文件夹 + agent_attachments 同 storage_key
- expires_at = +1 天
- retention 90→1 天配置生效
- 附件文件夹清理器：1 天前的附件文件夹文件被删；普通文件夹文件不受影响
- 任意类型上传（非白名单类型）成功

## 范围边界

**本期做**：
- 前端拖拽 + 选择统一 + 类型/大小放宽
- 后端双写端点（附件文件夹 + agent_attachments）
- config 90→1 天
- 附件文件夹清理器 + worker 挂载

**本期不做**：
- 附件文件夹在文件库页面的独立管理 UI（本期仅存储位置，文件库页面自然可见）
- 图片/PDF 的视觉预览作为附件（沿用现有 preview 机制）
- 附件文件夹的容量配额
