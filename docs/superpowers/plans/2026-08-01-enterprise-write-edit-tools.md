# Enterprise File Write/Edit Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `write_file`/`edit_file` save md files into the user's "我的文件" folders with exact path resolution, overwrite policy, and full metadata (`extracted_text`, preview) — aligned with `file_service` uploads. `list_files` exposes folders so the AI knows where to save.

**Architecture:** Four hardening changes in the tool layer: (1) planner input models + prompt, (2) `_list_files` returns folders, (3) `_write_file` exact-segment folder resolution + overwrite + extracted_text, (4) `_edit_file` file_id/path resolution + metadata refresh.

**Tech Stack:** Python, SQLAlchemy

## Global Constraints

- Exact folder matching ONLY in write (no ILIKE fuzzy) — prevent wrong-folder writes
- `extracted_text`/`preview_status` set on every write/edit (frontend search & preview depend on it)
- storage_key format `var/files/{owner}/{uuid}` consistent with `file_service`
- Return `file_id` so the AI can reference the file later
- Existing tests must pass (test_agent_tool_files.py)

---

### Task 1: Planner — input models + prompt

**Files:**
- Modify: `backend/app/services/agent/planner.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Produces: `WriteFileInput.overwrite: bool = True`; `EditFileInput.file_id: str | None`; updated `action_policy` text

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_tool_files.py`:

```python
class TestWriteEditModels:
    def test_write_file_input_accepts_overwrite(self):
        from app.services.agent.planner import WriteFileInput
        parsed = WriteFileInput(path="a/b.md", content="x", overwrite=False)
        assert parsed.overwrite is False

    def test_edit_file_input_accepts_file_id(self):
        from app.services.agent.planner import EditFileInput
        parsed = EditFileInput(file_id="00000000-0000-0000-0000-000000000001", old_str="a", new_str="b")
        assert parsed.file_id == "00000000-0000-0000-0000-000000000001"

    def test_action_policy_mentions_overwrite_and_folders(self):
        from app.services.agent.planner import ResearchPlanner
        planner = ResearchPlanner()
        messages = planner._build_messages(
            goal="写文件", step_index=0, previous_observation=None,
            session_history=None, mode="quick", web_enabled=True, final_step=False,
        )
        system_content = messages[0]["content"]
        assert "write_file" in system_content
        assert "覆盖" in system_content or "overwrite" in system_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestWriteEditModels -v
```

Expected: FAIL (fields/text missing).

- [ ] **Step 3: Implement**

In `backend/app/services/agent/planner.py`:

Change `WriteFileInput` (line ~47):

```python
class WriteFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)
    overwrite: bool = True
```

Change `EditFileInput` (line ~54):

```python
class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, min_length=1, max_length=500)
    file_id: str | None = Field(default=None, min_length=36, max_length=36)
    old_str: str = Field(min_length=1, max_length=10000)
    new_str: str = Field(min_length=0, max_length=10000)
```

Update `action_policy` in `_build_messages` (the write/edit portion, currently around line 116):

```python
                "write_file（创建或覆盖 .md 文件并保存到\"我的文件\"，"
                "path 为\"文件夹/文件名.md\"或\"文件名.md\"，文件夹不存在会自动创建，已存在默认覆盖）、"
                "edit_file（修改文件，可用 file_id 或 path 定位，需 old_str、new_str，old_str 必须唯一）、"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestWriteEditModels -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/planner.py backend/tests/test_agent_tool_files.py
git commit -m "feat: planner write/edit input models with overwrite and file_id"
```

---

### Task 2: `_list_files` returns folders

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Produces: `_list_files` output adds `folders: [{folder_id, folder_path, name}]` (deduplicated, owner-scoped)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_agent_tool_files.py` (follow the existing FakeRepo pattern from `TestListFilesTool`):

```python
class TestListFilesFolders:
    async def test_list_files_returns_folders(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        fake_file = MagicMock()
        fake_file.id = "00000000-0000-0000-0000-000000000001"
        fake_file.original_filename = "a.md"
        fake_file.size_bytes = 5
        fake_file.updated_at = None
        fake_file.folder_id = None

        fake_folder = MagicMock()
        fake_folder.id = "00000000-0000-0000-0000-000000000099"
        fake_folder.name = "00_Agent规范与模板"
        fake_folder.path = "/00_Agent规范与模板"

        class FakeRepo:
            async def list_files(self, **kwargs):
                return MagicMock(items=[fake_file], total=1)
            async def get_folder_tree(self, owner_id):
                return [fake_folder]

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: fake_session)
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", lambda session: FakeRepo())

        result = await executor._list_files({}, "user-1", False)
        assert result["folders"][0]["folder_id"] == "00000000-0000-0000-0000-000000000099"
        assert result["folders"][0]["folder_path"] == "/00_Agent规范与模板"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesFolders -v
```

Expected: FAIL (`KeyError: 'folders'`).

- [ ] **Step 3: Implement**

In `backend/app/services/agent/tool_executor.py`, `_list_files` (around line 349), add folders collection before the return:

```python
        folders: list[dict[str, str]] = []
        async with async_session_factory() as session:
            repo = FileRepository(session)
            folder_rows = await repo.get_folder_tree(owner_user_id) if owner_user_id else []
            seen: set[str] = set()
            for folder_obj in folder_rows:
                key = str(folder_obj.id)
                if key in seen:
                    continue
                seen.add(key)
                folders.append({
                    "folder_id": key,
                    "folder_path": folder_obj.path or "/",
                    "name": folder_obj.name,
                })

        return {
            "files": [...existing...],
            "folders": folders,
            "total": len(files),
        }
```

Keep the existing `files` structure unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesFolders -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: list_files returns owner folders for write targeting"
```

---

### Task 3: `_write_file` hardening

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `WriteFileInput` (Task 1)
- Produces: exact folder resolution (create-if-missing), `extracted_text`/`preview_status` set, overwrite policy, return `{file_id, filename, folder_path, action}`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_tool_files.py`:

```python
class TestWriteFileHardening:
    async def test_write_creates_file_with_extracted_text_and_file_id(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        captured = {}

        class FakeSession:
            def __init__(self):
                self.added = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                self.added.append(obj)
            async def flush(self):
                return None
            async def commit(self):
                captured["added"] = list(self.added)
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._write_file(
            {"path": "新文件夹/测试方案.md", "content": "# 测试\n内容", "overwrite": True},
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert result["action"] == "created"
        assert result["filename"] == "测试方案.md"
        assert "file_id" in result
        file_obj = [o for o in captured["added"] if getattr(o, "original_filename", None) == "测试方案.md"][0]
        assert file_obj.extracted_text == "# 测试\n内容"
        assert file_obj.preview_status == "ready"

    async def test_write_overwrites_existing_file(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        existing = MagicMock()
        existing.id = "00000000-0000-0000-0000-0000000000bb"
        existing.original_filename = "已存在.md"
        existing.folder_id = None
        existing.storage_key = ""

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._write_file(
            {"path": "已存在.md", "content": "新内容", "overwrite": True},
            "00000000-0000-0000-0000-0000000000aa",
        )
        assert result["action"] == "updated"
        assert result["file_id"] == "00000000-0000-0000-0000-0000000000bb"
```

Note: `_write_file` writes to `./var/files/{owner}/{uuid}` on disk — the second test's `existing.storage_key=""` makes it skip the disk write path only if you guard on storage_key; if your implementation always writes disk, patch `Path.write_bytes`/`write_text` via monkeypatch or set `tmp_path`. Adapt the mocks to match your implementation structure (read the current method first). The assertions on `action`/`file_id`/`extracted_text` must hold.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestWriteFileHardening -v
```

Expected: FAIL (no `action`/`file_id` in return; no `extracted_text`).

- [ ] **Step 3: Rewrite `_write_file`**

Replace the entire `_write_file` method body (lines 363-445) with:

```python
    async def _write_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        path = payload["path"]
        content = payload["content"]
        overwrite = bool(payload.get("overwrite", True))

        if not path.lower().endswith(".md"):
            raise ValueError("only_md_files_supported")

        from pathlib import Path as FilePath
        from datetime import datetime, UTC
        import hashlib

        filename = path.split("/")[-1]
        folder_parts = [p for p in path.split("/")[:-1] if p]

        async with async_session_factory() as session:
            folder_uuid: uuid.UUID | None = None
            if folder_parts:
                parent_id: uuid.UUID | None = None
                current_path = ""
                for part in folder_parts:
                    current_path = f"{current_path}/{part}" if current_path else f"/{part}"
                    result = await session.execute(
                        select(FileFolder).where(
                            FileFolder.owner_user_id == owner_user_id,
                            FileFolder.name == part,
                            FileFolder.parent_folder_id == parent_id,
                            FileFolder.is_deleted == False,
                        )
                    )
                    folder = result.scalar_one_or_none()
                    if folder is None:
                        folder = FileFolder(
                            owner_user_id=owner_user_id,
                            parent_folder_id=parent_id,
                            name=part,
                            path=current_path,
                            depth=current_path.count("/"),
                            created_by=owner_user_id,
                        )
                        session.add(folder)
                        await session.flush()
                    parent_id = folder.id
                folder_uuid = parent_id

            # Existing file check (exact folder + filename)
            existing_result = await session.execute(
                select(FileObject).where(
                    FileObject.owner_user_id == owner_user_id,
                    FileObject.folder_id == folder_uuid,
                    FileObject.original_filename == filename,
                    FileObject.is_deleted == False,
                )
            )
            existing = existing_result.scalar_one_or_none()

            content_bytes = content.encode("utf-8")
            digest = hashlib.sha256(content_bytes).hexdigest()

            if existing is not None:
                if not overwrite:
                    raise ValueError(f"file_already_exists: {path}")
                storage_path = FilePath(existing.storage_key) if existing.storage_key else None
                if storage_path is None or not storage_path.parent.exists():
                    storage_path = FilePath("./var/files") / str(owner_user_id) / str(existing.id)
                    storage_path.parent.mkdir(parents=True, exist_ok=True)
                storage_path.write_bytes(content_bytes)
                existing.size_bytes = len(content_bytes)
                existing.sha256 = digest
                existing.extracted_text = content
                existing.preview_status = "ready"
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                await session.commit()
                return {
                    "file_id": str(existing.id),
                    "filename": existing.original_filename,
                    "folder_path": path.rsplit("/", 1)[0] if "/" in path else "/",
                    "action": "updated",
                }

            file_uuid = uuid.uuid4()
            storage_root = FilePath("./var/files")
            storage_dir = storage_root / str(owner_user_id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_path = storage_dir / str(file_uuid)
            storage_path.write_bytes(content_bytes)

            file_obj = FileObject(
                id=file_uuid,
                owner_user_id=owner_user_id,
                folder_id=folder_uuid,
                storage_key=str(storage_path),
                filename=filename,
                original_filename=filename,
                media_type="text/markdown",
                size_bytes=len(content_bytes),
                sha256=digest,
                extracted_text=content,
                preview_status="ready",
                created_by=owner_user_id,
            )
            session.add(file_obj)

            if folder_uuid is not None:
                folder = await session.get(FileFolder, folder_uuid)
                if folder is not None:
                    folder.child_file_count = (folder.child_file_count or 0) + 1
                    folder.total_size_bytes = (folder.total_size_bytes or 0) + len(content_bytes)
                    session.add(folder)

            await session.commit()
            return {
                "file_id": str(file_uuid),
                "filename": filename,
                "folder_path": path.rsplit("/", 1)[0] if "/" in path else "/",
                "action": "created",
            }
```

Key changes:
- Exact folder resolution per path segment (no fuzzy `find_folder_by_name`)
- `extracted_text`/`preview_status` set (frontend search/preview ready)
- Overwrite policy: same folder + same filename → update same file (preserves file_id), else error
- Return includes `file_id`, `folder_path`, `action`

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestWriteFileHardening -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: write_file exact folder resolution, overwrite policy, extracted_text"
```

---

### Task 4: `_edit_file` hardening

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `EditFileInput` (Task 1)
- Produces: `file_id`-first resolution + path chain (exact → folder/filename → fuzzy); refreshes `extracted_text`/`size`/`sha256`; returns `file_id`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_agent_tool_files.py`:

```python
class TestEditFileHardening:
    async def test_edit_by_file_id_updates_metadata(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor
        from pathlib import Path

        content_file = tmp_path / "target.md"
        content_file.write_text("第一行\n需要修改的内容\n第三行", encoding="utf-8")

        fake_file = MagicMock()
        fake_file.id = "00000000-0000-0000-0000-0000000000cc"
        fake_file.original_filename = "目标.md"
        fake_file.media_type = "text/markdown"
        fake_file.storage_key = str(content_file)
        fake_file.folder_id = None

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=fake_file))
            def add(self, obj):
                pass
            async def commit(self):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._edit_file(
            {"file_id": "00000000-0000-0000-0000-0000000000cc", "old_str": "需要修改的内容", "new_str": "已修改的内容"},
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert result["file_id"] == "00000000-0000-0000-0000-0000000000cc"
        assert result["action"] == "updated"
        new_text = content_file.read_text(encoding="utf-8")
        assert "已修改的内容" in new_text
        assert "需要修改的内容" not in new_text
        assert fake_file.extracted_text == new_text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestEditFileHardening -v
```

Expected: FAIL (current `_edit_file` requires `path`, ignores `file_id`; no `extracted_text` update).

- [ ] **Step 3: Rewrite `_edit_file`**

Replace the entire `_edit_file` method body (lines 447-482) with:

```python
    async def _edit_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        file_id = payload.get("file_id")
        path = payload.get("path")
        old_str = payload["old_str"]
        new_str = payload["new_str"]

        from pathlib import Path as FilePath
        from datetime import datetime, UTC
        import hashlib

        async with async_session_factory() as session:
            repo = FileRepository(session)
            file_obj = None

            if file_id:
                file_obj = await repo.get_file(uuid.UUID(file_id))
                if file_obj is None:
                    raise ValueError(f"file_not_found: {file_id}")
                if not (file_obj.owner_user_id == owner_user_id):
                    raise ValueError(f"file_not_found: {file_id}")
            elif path:
                folder_name: str | None = None
                filename = path
                if "/" in path:
                    parts = path.rsplit("/", 1)
                    folder_name = parts[0].strip() or None
                    filename = parts[1].strip()

                file_obj = await repo.get_by_owner_and_filename(owner_user_id, path)
                if file_obj is None and folder_name:
                    folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                    if folder is not None:
                        matches = await repo.search_by_folder_and_filename(folder.id, filename)
                        if len(matches) == 1:
                            file_obj = matches[0]
                if file_obj is None:
                    matches = await repo.search_by_owner_and_filename(owner_user_id, filename)
                    if len(matches) == 1:
                        file_obj = matches[0]
                if file_obj is None:
                    raise ValueError(f"file_not_found: {path}")
            else:
                raise ValueError("file_id_or_path_required")

            storage_path = FilePath(file_obj.storage_key) if file_obj.storage_key else None
            if not storage_path or not storage_path.is_file():
                raise ValueError(f"file_data_not_found: {file_obj.original_filename}")
            current_content = storage_path.read_text(encoding="utf-8")

            count = current_content.count(old_str)
            if count == 0:
                raise ValueError("old_str not found")
            if count > 1:
                raise ValueError(f"old_str found multiple times: {count}")

            new_content = current_content.replace(old_str, new_str, 1)
            storage_path.write_text(new_content, encoding="utf-8")
            content_bytes = new_content.encode("utf-8")
            file_obj.size_bytes = len(content_bytes)
            file_obj.sha256 = hashlib.sha256(content_bytes).hexdigest()
            file_obj.extracted_text = new_content
            file_obj.preview_status = "ready"
            file_obj.updated_at = datetime.now(UTC)
            session.add(file_obj)
            await session.commit()
            return {
                "file_id": str(file_obj.id),
                "filename": file_obj.original_filename,
                "action": "updated",
            }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestEditFileHardening -v
```

Expected: PASS.

- [ ] **Step 5: Run the full tool + loop suites**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py tests/test_agent_loop.py -v
```

Expected: All pass. If any existing test breaks (e.g., write return shape changed from `status` to `action`), update that test to the new contract — do NOT weaken the new tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: edit_file file_id/path resolution with metadata refresh"
```
