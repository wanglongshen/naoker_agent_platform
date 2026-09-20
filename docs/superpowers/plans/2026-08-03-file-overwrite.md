# 同名文件覆盖实现计划（上传 + AI 写入）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "我的文件"同名文件直接覆盖：上传同名时保留原记录 `id` 与存储路径、更新内容与元数据并将 `created_at` 刷新为当前时间（列表按 `created_at` 降序自动置顶）；AI 写入工具（`write_file`）覆盖行为一致化。

**Architecture:** `file_service.upload` 在新建前按 `owner + folder_id + original_filename` 查询同名记录，命中则复用记录写盘并刷新元数据（含 `created_at`）；`tool_executor._write_file` 的覆盖分支同步设置 `created_at`；列表排序无需改动（已按 `created_at` 降序）。

**Tech Stack:** Python (FastAPI/SQLAlchemy async + PostgreSQL), pytest

**Spec:** `docs/superpowers/specs/2026-08-03-file-overwrite-design.md`

## Global Constraints

- 同名判定：`owner_user_id == owner AND folder_id == target_folder_id AND original_filename == display_name AND is_deleted == false`
- 覆盖时保留原 `id` 与 `storage_key`（目录不存在则重建后写盘）
- 覆盖更新字段：`media_type`、`size_bytes`、`sha256`、`extracted_text`、`preview_status`、`updated_at = now`、**`created_at = now`**
- 文件夹计数与大小在覆盖时不变
- 不同文件夹的同名文件各自独立（不误覆盖）
- 前端无改动

---

### Task 1: `upload` 同名覆盖

**Files:**
- Modify: `backend/app/services/file_service.py`（`upload` 方法，`digest = sha256.hexdigest()` 之后）
- Test: `backend/tests/test_file_service.py`

**Interfaces:**
- Consumes: 现有 `FileService.upload(owner_user_id, folder_id, upload_file, db_session, settings=None) -> FileObjectResponse`、`_extract_text(media_type, content)`、`_is_text_mime(media_type)`、`_resolve_storage_path`（文件内现有）
- Produces: 同名（owner+folder+original_filename）上传返回同一 `id` 的 `FileObjectResponse`，`created_at` 刷新；不同文件夹同名不互相覆盖

- [ ] **Step 1: Write the failing tests**

追加到 `backend/tests/test_file_service.py` 的 `TestUpload` 类中：

```python
    async def test_upload_same_name_overwrites_same_record(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("report.md", b"# v1", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            first = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        second_upload = _make_upload_file("report.md", b"# v2 content", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            second = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=second_upload,
                db_session=session,
            )

        assert second.id == first.id
        assert second.size_bytes == len(b"# v2 content")
        assert second.created_at > first.created_at

        repo = FileRepository(session)
        file_obj = await repo.get_file(first.id)
        assert file_obj is not None
        assert file_obj.extracted_text == "# v2 content"

    async def test_upload_same_name_different_folder_keeps_both(
        self, file_service, session, seeded_user, folder_for_service
    ):
        upload_file = _make_upload_file("notes.md", b"root", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            root_file = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        folder_upload = _make_upload_file("notes.md", b"folder", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            folder_file = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=folder_for_service.id,
                upload_file=folder_upload,
                db_session=session,
            )

        assert folder_file.id != root_file.id
        repo = FileRepository(session)
        assert await repo.get_file(root_file.id) is not None
        assert await repo.get_file(folder_file.id) is not None
```

注意：`_make_upload_file` 的 `read` side_effect 为 `[content, b""]`——同一次上传只调用一次 read；第二次上传需新建 `_make_upload_file` 实例（内容不同）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_file_service.py::TestUpload::test_upload_same_name_overwrites_same_record tests/test_file_service.py::TestUpload::test_upload_same_name_different_folder_keeps_both -q`（在 `C:\01_agent_loop_pro\backend`）
Expected: `test_upload_same_name_overwrites_same_record` FAIL（`second.id != first.id`）；`test_upload_same_name_different_folder_keeps_both` PASS（现状已满足）。

- [ ] **Step 3: Implement the overwrite branch**

修改 `backend/app/services/file_service.py` `upload`：在 `digest = sha256.hexdigest()` 之后、`file_uuid = uuid.uuid4()` 之前插入同名查询与覆盖逻辑：

```python
        existing = await db_session.scalar(
            select(FileObject).where(
                FileObject.owner_user_id == owner_user_id,
                FileObject.folder_id == target_folder_id,
                FileObject.original_filename == display_name,
                FileObject.is_deleted == False,
            )
        )
        if existing is not None:
            now = datetime.now(UTC)
            storage_path = Path(existing.storage_key) if existing.storage_key else None
            if storage_path is None or not storage_path.parent.exists():
                storage_path = _resolve_storage_path(owner_user_id, existing.id)
                storage_path.parent.mkdir(parents=True, exist_ok=True)

            def _write_existing_sync():
                with open(storage_path, "wb") as f:
                    f.write(content)

            await asyncio.to_thread(_write_existing_sync)

            extracted_text: str | None = None
            try:
                extracted_text = _extract_text(media_type, content)
            except Exception:
                extracted_text = None
            existing.media_type = media_type
            existing.size_bytes = total
            existing.sha256 = digest
            existing.extracted_text = extracted_text
            existing.preview_status = "ready" if extracted_text is not None else ("pending" if _is_text_mime(media_type) else "none")
            existing.created_at = now
            existing.updated_at = now
            db_session.add(existing)
            await db_session.flush()
            return FileObjectResponse.model_validate(existing)
```

同时在文件顶部 import 区确认已有：`from datetime import UTC, datetime`（若缺失则补充）、`from sqlalchemy import select`（若缺失则补充）、`from app.models.file import FileObject`（若缺失则补充）、`from pathlib import Path`（已导入）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_file_service.py -q`
Expected: 全部 PASS（含 2 个新测试与全部现有测试）。

- [ ] **Step 5: Run API-level regression**

Run: `python -m pytest tests/test_agent_attachments.py -q`
Expected: 全部 PASS（上传 API 行为不变——同名覆盖不影响下载/删除测试）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/file_service.py backend/tests/test_file_service.py
git commit -m "feat: same-name upload overwrites existing file keeping id and refreshing created_at"
```

---

### Task 2: `write_file` 覆盖时刷新 `created_at`

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py:505`（`existing.updated_at = datetime.now(UTC)` 行附近）
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `ToolExecutor._write_file(payload, owner_user_id)` 现有签名、conftest 的 `session` fixture、`FileObject`
- Produces: `_write_file` 覆盖已有文件时 `existing.created_at` 同样刷新为当前时间

- [ ] **Step 1: Write the failing test**

追加到 `backend/tests/test_agent_tool_files.py` 文件末尾：

```python
class TestWriteFileCreatedAtRefresh:
    async def test_overwrite_refreshes_created_at(self, test_engine, monkeypatch):
        import uuid
        from datetime import UTC, datetime, timedelta
        from pathlib import Path

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.rbac import User
        from app.models.file import FileObject
        from app.services.agent import tool_executor
        from app.services.agent.tool_executor import ToolExecutor

        factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(tool_executor, "async_session_factory", factory)

        async with factory() as s:
            async with s.begin():
                owner = User(username=f"wf_owner_{uuid.uuid4().hex[:6]}", display_name="Owner", password_hash="x")
                s.add(owner)
                await s.flush()
                past = datetime.now(UTC) - timedelta(days=1)
                file_obj = FileObject(
                    owner_user_id=owner.id,
                    storage_key="",
                    filename="doc.md",
                    original_filename="doc.md",
                    media_type="text/markdown",
                    size_bytes=3,
                    sha256="x" * 64,
                    extracted_text="old",
                    preview_status="ready",
                    created_at=past,
                    updated_at=past,
                )
                s.add(file_obj)
                await s.flush()
                owner_id = owner.id
                old_id = file_obj.id

        executor = ToolExecutor()
        result = await executor._write_file(
            {"path": "doc.md", "content": "new content", "overwrite": True},
            owner_id,
        )

        assert result["action"] == "updated"
        assert result["file_id"] == str(old_id)

        async with factory() as s:
            fresh = await s.get(FileObject, old_id)
            assert fresh.created_at > past
            assert fresh.extracted_text == "new content"
            storage = Path(fresh.storage_key) if fresh.storage_key else None
            if storage is not None and storage.exists():
                storage.unlink()
```

注意：`_write_file` 内部使用模块级 `async_session_factory`（生产库）——必须 monkeypatch 指向测试库；`storage_key=""` 使覆盖分支走重建路径（`./var/files/{owner}/{id}`，测试运行目录为 `backend`），测试末尾清理磁盘文件。`path="doc.md"` 无文件夹 → `folder_uuid=None` → 命中同名查询。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_tool_files.py::TestWriteFileCreatedAtRefresh -q`
Expected: FAIL（`fresh.created_at` 仍为 `past`——现状只更新 `updated_at`）。

- [ ] **Step 3: Implement**

修改 `backend/app/services/agent/tool_executor.py` `_write_file` 的 existing 覆盖分支（`existing.updated_at = datetime.now(UTC)` 前一行）加：

```python
                existing.created_at = datetime.now(UTC)
                existing.updated_at = datetime.now(UTC)
```

即把该处代码改为：

```python
                existing.size_bytes = len(content_bytes)
                existing.sha256 = digest
                existing.extracted_text = content
                existing.preview_status = "ready"
                now = datetime.now(UTC)
                existing.created_at = now
                existing.updated_at = now
                session.add(existing)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_tool_files.py -q`
Expected: 全部 PASS（含新测试与现有 write/edit 测试）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: write_file overwrite refreshes created_at for consistent list ordering"
```

---

### Task 3: 全量回归

**Files:**
- 无（仅验证）

- [ ] **Step 1: Run full backend suite**

Run: `python -m pytest -q`（在 `C:\01_agent_loop_pro\backend`）
Expected: 662 基线 + 新增测试全部 PASS（约 664+ 个）。

- [ ] **Step 2: 人工验证（可选）**

启动后端后：上传同名文件两次 → 文件列表只保留一条记录且"创建时间"为第二次上传时间、文件位于列表最上方；AI 对话要求"把总结保存到 reports/2026-08/template-summary.md"两次 → 同一条记录、时间刷新、置顶。
