# Agent File Tools — Read, Write, Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `read_file`, `write_file`, `edit_file` tools to the Agent's `ToolExecutor`, enabling the LLM to read user files and attachments, generate new Markdown files, and modify existing files — all gated by RBAC ownership.

**Architecture:** Three new action types registered in `ToolExecutor.execute()` with corresponding Pydantic input schemas in `planner.py`. Read fetches from `FileObject` or `AgentAttachment` models. Write creates a new `FileObject` in the user's own file space. Edit does a string find-and-replace on an existing `FileObject` owned by the user. Planner prompt updated to inform LLM of available file tools.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2

## Global Constraints

- `read_file`: regular users can read their own `FileObject` + `AgentAttachment`; super admins can read ALL `FileObject` records + their own attachments. Uses `owner_user_id` gate.
- `write_file`: always creates in caller's OWN file space (`owner_user_id = current user`). Only `.md` extension. Creates parent folders on the fly.
- `edit_file`: only OWN files. Does `old_str → new_str` replacement. Fails if `old_str` not found or appears multiple times.
- All file tools use `async_session_factory` for DB access (match existing pattern).
- Storage backend: `PrivateObjectStorage` via `FileService` (existing).
- Input schemas: Pydantic `BaseModel` with `extra="forbid"` (match existing `WebSearchInput` etc).

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/app/services/agent/planner.py` | Add `ReadFileInput`, `WriteFileInput`, `EditFileInput` schemas; register in `input_models` dict; update system prompt |
| `backend/app/services/agent/tool_executor.py` | Add `_read_file()`, `_write_file()`, `_edit_file()` methods; wire into `execute()` |
| `backend/tests/test_agent_tool_files.py` | **New.** Unit tests for all three tools |

---

### Task 1: Add Pydantic Schemas + Planner Prompt

**Files:**
- Modify: `backend/app/services/agent/planner.py:36-38` (after FinishInput)
- Modify: `backend/app/services/agent/planner.py:88-95` (action_policy lines)
- Modify: `backend/app/services/agent/planner.py:146-150` (example JSON lines)

**Interfaces:**
- Produces: `ReadFileInput`, `WriteFileInput`, `EditFileInput` Pydantic models; updated `input_models` dict

- [ ] **Step 1: Add input schemas after FinishInput (line 38)**

In `backend/app/services/agent/planner.py`, after the `FinishInput` class, add:

```python
class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, min_length=1, max_length=500)
    attachment_id: str | None = Field(default=None, min_length=1, max_length=64)


class WriteFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)


class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=500)
    old_str: str = Field(min_length=1, max_length=10000)
    new_str: str = Field(min_length=0, max_length=10000)
```

- [ ] **Step 2: Register schemas in input_models dict (lines 209-215)**

Find the `input_models` dict and add entries:

```python
input_models = {
    "web_search": WebSearchInput,
    "http_request": HttpRequestInput,
    "extract_web_content": ExtractWebContentInput,
    "calculator": CalculatorInput,
    "finish": FinishInput,
    "read_file": ReadFileInput,
    "write_file": WriteFileInput,
    "edit_file": EditFileInput,
}
```

- [ ] **Step 3: Update action_policy in system prompt (lines 88-91)**

Change the action_policy line from:

```python
action_policy = (
    "允许的 action.type 有 web_search、http_request、extract_web_content、calculator 和 finish。"
)
```

To:

```python
action_policy = (
    "允许的 action.type 有 web_search、http_request、extract_web_content、calculator、"
    "read_file（读取文件，path 为文件路径或 attachment_id 为附件ID）、"
    "write_file（创建或覆盖 .md 文件，需 path 和 content）、"
    "edit_file（修改文件，需 path、old_str、new_str，old_str 必须在文件中唯一出现）、"
    "以及 finish。"
)
```

- [ ] **Step 4: Add example JSON outputs (after line 150)**

After the existing finish example `'{"thought_summary":"...","action":{"type":"finish","input":{}}}'`, add:

```python
            '{"thought_summary":"简短中文原因","action":{"type":"read_file","input":{"path":"notes/todo.md"}}}\n'
            '{"thought_summary":"简短中文原因","action":{"type":"read_file","input":{"attachment_id":"<附件ID>"}}}\n'
            '{"thought_summary":"简短中文原因","action":{"type":"write_file","input":{"path":"notes/report.md","content":"# 报告\\n\\n内容..."}}}\n'
            '{"thought_summary":"简短中文原因","action":{"type":"edit_file","input":{"path":"notes/report.md","old_str":"旧内容","new_str":"新内容"}}}\n'
```

- [ ] **Step 5: Run planner tests**

```powershell
python -X utf8 -m pytest tests/test_agent_loop.py -v --no-header -k "plan_created|planner"
```

Expected: existing planner tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/planner.py
git commit -m "feat: add read_file, write_file, edit_file input schemas and planner prompt"
```

---

### Task 2: Implement File Tools in ToolExecutor

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py:172-186` (execute method)
- Create: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `ReadFileInput`, `WriteFileInput`, `EditFileInput` from Task 1
- Produces: `ToolExecutor._read_file()`, `ToolExecutor._write_file()`, `ToolExecutor._edit_file()`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_agent_tool_files.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.agent.tool_executor import ToolExecutor
from app.models.file import FileFolder, FileObject
from app.models.agent import AgentAttachment


class TestReadFile:
    @pytest.mark.anyio
    async def test_read_file_by_path_returns_content(self, monkeypatch):
        executor = ToolExecutor()
        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"# Hello\n\nWorld"
        fake_file.media_type = "text/markdown"
        fake_file.original_filename = "test.md"
        fake_file.owner_user_id = uuid.uuid4()
        fake_file.id = uuid.uuid4()

        async def mock_get_by_path(session, owner_id, path):
            return fake_file

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_path)}),
        )

        result = await executor._read_file(
            {"path": "notes/test.md"},
            owner_user_id=uuid.uuid4(),
            is_super_admin=False,
        )
        assert result["filename"] == "test.md"
        assert "# Hello" in result["content"]

    @pytest.mark.anyio
    async def test_read_file_by_attachment_returns_content(self, monkeypatch):
        executor = ToolExecutor()

        fake_attachment = MagicMock(spec=AgentAttachment)
        fake_attachment.original_filename = "doc.md"
        fake_attachment.media_type = "text/markdown"
        fake_attachment.extracted_text = "Attachment content"
        fake_attachment.owner_user_id = uuid.uuid4()
        fake_attachment.id = uuid.uuid4()

        async def mock_get_attachment(session, attachment_id):
            return fake_attachment

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )
        monkeypatch.setattr(
            "app.services.agent.tool_executor.AgentRepository",
            type("FakeRepo", (), {"get_owned_attachment": staticmethod(mock_get_attachment)}),
        )

        result = await executor._read_file(
            {"attachment_id": str(uuid.uuid4())},
            owner_user_id=uuid.uuid4(),
            is_super_admin=False,
        )
        assert result["filename"] == "doc.md"
        assert result["content"] == "Attachment content"

    @pytest.mark.anyio
    async def test_read_file_missing_both_path_and_attachment(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="path_or_attachment_required"):
            await executor._read_file({}, owner_user_id=uuid.uuid4(), is_super_admin=False)


class TestWriteFile:
    @pytest.mark.anyio
    async def test_write_creates_file(self, monkeypatch):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.id = uuid.uuid4()
        fake_file.original_filename = "output.md"
        fake_file.content = b"# Written"
        fake_file.media_type = "text/markdown"
        fake_file.owner_user_id = owner_id

        mock_service = AsyncMock()
        mock_service.create_file.return_value = fake_file
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileService",
            lambda storage, session: mock_service,
        )

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        result = await executor._write_file(
            {"path": "output/report.md", "content": "# Written"},
            owner_user_id=owner_id,
        )
        assert result["path"] == "output/report.md"
        assert "created" in result["status"]


class TestEditFile:
    @pytest.mark.anyio
    async def test_edit_replaces_old_with_new(self, monkeypatch):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"# Hello\n\nWorld"
        fake_file.media_type = "text/markdown"
        fake_file.original_filename = "test.md"
        fake_file.owner_user_id = owner_id
        fake_file.id = uuid.uuid4()

        updated_file = MagicMock(spec=FileObject)
        updated_file.content = b"# Hello\n\nUniverse"
        updated_file.original_filename = "test.md"

        async def mock_get_by_path(session, oid, path):
            return fake_file

        mock_service = AsyncMock()
        mock_service.update_content.return_value = updated_file
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_path)}),
        )
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileService",
            lambda storage, session: mock_service,
        )

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        result = await executor._edit_file(
            {"path": "test.md", "old_str": "World", "new_str": "Universe"},
            owner_user_id=owner_id,
        )
        assert result["filename"] == "test.md"
        assert "replaced" in result["status"]

    @pytest.mark.anyio
    async def test_edit_fails_on_multiple_matches(self, monkeypatch):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"# Hello\n\nWorld\n\nWorld"
        fake_file.media_type = "text/markdown"
        fake_file.owner_user_id = owner_id
        fake_file.id = uuid.uuid4()

        async def mock_get_by_path(session, oid, path):
            return fake_file

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_path)}),
        )

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        with pytest.raises(ValueError, match="multiple"):
            await executor._edit_file(
                {"path": "test.md", "old_str": "World", "new_str": "Universe"},
                owner_user_id=owner_id,
            )

    @pytest.mark.anyio
    async def test_edit_fails_when_old_not_found(self, monkeypatch):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"# Hello"
        fake_file.media_type = "text/markdown"
        fake_file.owner_user_id = owner_id
        fake_file.id = uuid.uuid4()

        async def mock_get_by_path(session, oid, path):
            return fake_file

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_path)}),
        )

        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        with pytest.raises(ValueError, match="not found"):
            await executor._edit_file(
                {"path": "test.md", "old_str": "Missing", "new_str": "X"},
                owner_user_id=owner_id,
            )
```

class TestFileRBAC:
    @pytest.mark.anyio
    async def test_super_admin_can_read_others_file(self, monkeypatch):
        executor = ToolExecutor()
        other_owner = uuid.uuid4()
        admin_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"Other user data"
        fake_file.media_type = "text/markdown"
        fake_file.original_filename = "other.md"
        fake_file.owner_user_id = other_owner
        fake_file.id = uuid.uuid4()

        async def mock_get_by_path(session, path):
            return fake_file

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_path": staticmethod(mock_get_by_path)}),
        )
        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        result = await executor._read_file(
            {"path": "other.md"},
            owner_user_id=admin_id,
            is_super_admin=True,
        )
        assert result["filename"] == "other.md"
        assert result["content"] == "Other user data"

    @pytest.mark.anyio
    async def test_super_admin_cannot_write_others_file_space(self):
        executor = ToolExecutor()
        other_owner = uuid.uuid4()

        # Write always uses owner_user_id — super admin writes to OWN space
        # even when trying to write to another user's path.
        # The test verifies that write_file uses owner_user_id, not super_admin flag.
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor._write_file(
                {"path": "output.md", "content": "# Test"},
                owner_user_id=None,
            )

    @pytest.mark.anyio
    async def test_regular_user_cannot_read_others_file(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()

        async def mock_get_by_owner(session, owner_id, path):
            return None  # File belongs to someone else

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_owner)}),
        )
        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        with pytest.raises(ValueError, match="file_not_found"):
            await executor._read_file(
                {"path": "secret.md"},
                owner_user_id=my_id,
                is_super_admin=False,
            )


class TestFileSecurity:
    @pytest.mark.anyio
    async def test_rejects_path_traversal_dotdot(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()

        async def mock_get_by_owner(session, owner_id, path):
            if ".." in path or path.startswith("/") or ":\\" in path:
                return None
            return MagicMock()

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_owner)}),
        )
        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        with pytest.raises(ValueError, match="file_not_found"):
            await executor._read_file(
                {"path": "../../etc/passwd"},
                owner_user_id=my_id,
                is_super_admin=False,
            )

    @pytest.mark.anyio
    async def test_write_rejects_non_md_extension(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="only_md"):
            await executor._write_file(
                {"path": "script.py", "content": "print('hello')"},
                owner_user_id=uuid.uuid4(),
            )


class TestFileToolsIntegration:
    @pytest.mark.anyio
    async def test_execute_dispatches_read_file(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()

        fake_file = MagicMock(spec=FileObject)
        fake_file.content = b"Integration test"
        fake_file.media_type = "text/markdown"
        fake_file.original_filename = "test.md"
        fake_file.owner_user_id = my_id
        fake_file.id = uuid.uuid4()

        async def mock_get_by_owner(session, owner_id, path):
            return fake_file

        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"get_by_owner_and_path": staticmethod(mock_get_by_owner)}),
        )
        mock_factory = AsyncMock()
        mock_factory.return_value.__aenter__.return_value = AsyncMock()
        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory",
            lambda: mock_factory,
        )

        result = await executor.execute(
            {"type": "read_file", "input": {"path": "test.md"}},
            owner_user_id=my_id,
        )
        assert result["filename"] == "test.md"

    @pytest.mark.anyio
    async def test_execute_read_file_rejects_when_owner_missing(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor.execute(
                {"type": "read_file", "input": {"path": "test.md"}},
                owner_user_id=None,
            )
```

- [ ] **Step 2: Run tests to verify they FAIL**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py -v --no-header
```

Expected: all tests FAIL — `ToolExecutor` has no `_read_file`/`_write_file`/`_edit_file`.

- [ ] **Step 3: Implement file tools in ToolExecutor**

In `backend/app/services/agent/tool_executor.py`, modify the `execute()` method (lines 172-186) to add three new branches before the `raise ValueError`:

```python
class ToolExecutor:
    async def execute(self, action: dict[str, Any], web_enabled: bool = True,
                      owner_user_id: uuid.UUID | None = None,
                      is_super_admin: bool = False) -> dict[str, Any]:
        action_type = action.get("type")
        payload = action.get("input", {})
        if action_type in NETWORK_ACTIONS and not web_enabled:
            raise ValueError(f"networking_disabled: {action_type}")
        if action_type == "web_search":
            return await self._web_search(payload)
        if action_type in {"http_request", "extract_web_content"}:
            return await self._http_request(payload)
        if action_type == "calculator":
            return self._calculator(payload)
        if action_type == "read_file":
            return await self._read_file(payload, owner_user_id, is_super_admin)
        if action_type == "write_file":
            return await self._write_file(payload, owner_user_id)
        if action_type == "edit_file":
            return await self._edit_file(payload, owner_user_id)
        if action_type == "finish":
            return {"final_answer": payload.get("answer", "done")}
        raise ValueError(f"Unsupported action type: {action_type}")
```

Add these imports at the top of `tool_executor.py`:

```python
import uuid
from sqlalchemy import select as sa_select
from app.db.session import async_session_factory
from app.repositories.file_repository import FileRepository
from app.repositories.agent_repository import AgentRepository
from app.models.file import FileObject, FileFolder
from app.services.file_service import FileService
from app.services.agent.storage import PrivateObjectStorage
```

Add these three methods to `ToolExecutor` class (before `_web_search`):

```python
    async def _read_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None, is_super_admin: bool
    ) -> dict[str, Any]:
        path = payload.get("path")
        attachment_id = payload.get("attachment_id")

        if path:
            async with async_session_factory() as session:
                repo = FileRepository(session)
                if is_super_admin:
                    file_obj = await repo.get_by_path(path)
                else:
                    if owner_user_id is None:
                        raise ValueError("owner_user_id_required")
                    file_obj = await repo.get_by_owner_and_path(owner_user_id, path)
                if file_obj is None:
                    raise ValueError(f"file_not_found: {path}")
                return self._format_file_result(file_obj)

        if attachment_id:
            if owner_user_id is None:
                raise ValueError("owner_user_id_required")
            async with async_session_factory() as session:
                agent_repo = AgentRepository(session)
                attachment = await agent_repo.get_owned_attachment(
                    uuid.UUID(attachment_id), owner_user_id
                )
                if attachment is None:
                    raise ValueError(f"attachment_not_found: {attachment_id}")
                text = attachment.extracted_text or "(binary file, no text extracted)"
                return {
                    "filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "content": text[:10000],
                }

        raise ValueError("path_or_attachment_required")

    async def _write_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        path = payload["path"]
        content = payload["content"]

        if not path.lower().endswith(".md"):
            raise ValueError("only_md_files_supported")

        storage = PrivateObjectStorage(root="./var/files")
        async with async_session_factory() as session:
            service = FileService(storage, session)
            file_obj = await service.create_file(
                owner_user_id=owner_user_id,
                original_filename=path.split("/")[-1],
                media_type="text/markdown",
                content=content.encode("utf-8"),
                parent_path="/".join(path.split("/")[:-1]) if "/" in path else None,
            )
            await session.commit()
            return {
                "path": path,
                "filename": file_obj.original_filename,
                "status": "created",
            }

    async def _edit_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        path = payload["path"]
        old_str = payload["old_str"]
        new_str = payload["new_str"]

        async with async_session_factory() as session:
            repo = FileRepository(session)
            file_obj = await repo.get_by_owner_and_path(owner_user_id, path)
            if file_obj is None:
                raise ValueError(f"file_not_found: {path}")

            current_content = file_obj.content.decode("utf-8") if file_obj.content else ""

            count = current_content.count(old_str)
            if count == 0:
                raise ValueError(f"old_str_not_found")
            if count > 1:
                raise ValueError(f"old_str_found_multiple_times: {count}")

            new_content = current_content.replace(old_str, new_str, 1)
            storage = PrivateObjectStorage(root="./var/files")
            service = FileService(storage, session)
            updated = await service.update_content(file_obj, new_content.encode("utf-8"))
            await session.commit()
            return {
                "filename": updated.original_filename,
                "status": "replaced",
                "old_str_matched": True,
            }

    @staticmethod
    def _format_file_result(file_obj) -> dict[str, Any]:
        content = file_obj.content.decode("utf-8") if file_obj.content else ""
        return {
            "filename": file_obj.original_filename,
            "media_type": file_obj.media_type,
            "content": content[:10000],
        }
```

- [ ] **Step 4: Run tests to verify they PASS**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py -v --no-header
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Run full agent loop regression**

```powershell
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tool_files.py -v --no-header
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: add read_file, write_file, edit_file tools to Agent ToolExecutor"
```

---

### Task 3: Wire owner_user_id into Agent Loop

**Files:**
- Modify: `backend/app/services/agent/loop.py` — pass `owner_user_id` and `is_super_admin` to `ToolExecutor.execute()`
- Modify: `backend/app/services/agent/worker.py` — read `owner_user_id` from run and pass to loop

**Interfaces:**
- Consumes: `ToolExecutor.execute()` with new kwargs from Task 2
- Produces: `owner_user_id` passed through from `AgentLoopService.process_attempt()`

- [ ] **Step 1: Add owner_user_id parameter to process_attempt**

In `backend/app/services/agent/loop.py`, find `process_attempt` (line ~806). Add `owner_user_id` parameter:

```python
async def process_attempt(self, attempt_id: UUID, worker_id: str,
                          owner_user_id: UUID | None = None,
                          is_super_admin: bool = False) -> None:
```

Pass `owner_user_id` and `is_super_admin` to `_process_attempt_internal`, and from there to the tool executor call at line ~569:

```python
observation = await asyncio.wait_for(
    self.tool_executor.execute(action, web_enabled=web_enabled,
                               owner_user_id=owner_user_id,
                               is_super_admin=is_super_admin),
    timeout=settings.step_timeout_seconds,
)
```

- [ ] **Step 2: Pass owner_user_id through worker**

In `backend/app/services/agent/worker.py`, find where `agent_loop_service.process_attempt` is called (line ~131). Change to read `owner_user_id` from the run:

```python
async with self._session_factory() as session:
    run = await session.get(AgentRun, attempt.run_id) if hasattr(attempt, 'run_id') else None
    owner_user_id = run.owner_user_id if run else None
agent_loop_service.process_attempt(attempt.id, self.worker_id, owner_user_id=owner_user_id)
```

- [ ] **Step 3: Run wire-up test**

Add to `test_agent_tool_files.py`:

```python
class TestToolExecutorWireUp:
    def test_execute_signature_accepts_owner_and_admin_kwargs(self):
        """verify execute() accepts owner_user_id and is_super_admin kwargs."""
        executor = ToolExecutor()
        import inspect
        sig = inspect.signature(executor.execute)
        params = list(sig.parameters.keys())
        assert "owner_user_id" in params
        assert "is_super_admin" in params
```

- [ ] **Step 4: Run all tests including wire-up**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py tests/test_agent_loop.py -v --no-header
```
