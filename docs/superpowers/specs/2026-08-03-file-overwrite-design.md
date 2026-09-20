# 同名文件覆盖设计（上传 + AI 写入）

> 日期：2026-08-03 · 状态：已批准（用户确认：同名上传直接覆盖，保留原 id，创建时间更新为最新，文件置顶）

## 目标

"我的文件"中同名文件**直接覆盖**：保留原记录 `id` 与存储路径，更新内容与元数据，`created_at` 同步刷新为覆盖时间（前端"创建时间"列随之变化），列表按 `created_at` 降序自然置顶。

## 现状

- `file_service.upload`：无同名检查，每次上传创建新记录 → 出现多个同名文件
- `tool_executor._write_file`（AI 工具）：同名覆盖但仅更新 `updated_at`，`created_at` 不变，列表不置顶
- `file_repository.list_files`：已按 `FileObject.created_at.desc()` 排序（file_repository.py:190）——无需改排序

## 改动

### 1. `backend/app/services/file_service.py` `upload`

内容校验（MIME/大小）通过后、新建记录之前，查询同名：

```python
existing = await db_session.scalar(
    select(FileObject).where(
        FileObject.owner_user_id == owner_user_id,
        FileObject.folder_id == target_folder_id,
        FileObject.original_filename == display_name,
        FileObject.is_deleted == False,
    )
)
```

命中 → 覆盖：
- 写新内容到 `existing.storage_key` 原路径（目录不存在则重建）
- 更新：`media_type`、`size_bytes`、`sha256`、`extracted_text`（重新提取）、`preview_status`、`updated_at = now`、**`created_at = now`**
- 文件夹计数/大小不变；返回 `FileObjectResponse`（同 id）
- 未命中 → 新建（现状逻辑不变）

### 2. `backend/app/services/agent/tool_executor.py` `_write_file`

existing 覆盖分支同样设置 `existing.created_at = datetime.now(UTC)`（与上传行为一致化，AI 更新后文件同样置顶）。

### 3. 前端

无改动（列表已显示 `created_at`、按 `created_at` 降序）。

## 测试

- `tests/test_file_service.py`：
  - 同名上传（同 owner + 同 folder + 同名）→ 第二次返回同一 `id`、`created_at` 晚于第一次、`size_bytes` 为新内容大小、列表数量不增
  - 不同文件夹同名 → 各自独立创建（不误覆盖）
- `tests/test_agent_tool_files.py`：`write_file` 覆盖分支断言 `created_at` 被更新
- 现有上传/工具测试回归

## 不在范围内

- 前端覆盖确认弹窗（用户选择直接覆盖，不提示）
- 文件版本历史
- `edit_file` / 重命名 / 移动行为（不变）
