# Agent File Discovery & Reading Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the AI discover ("我的文件" File-module) files via a new `list_files` tool and read them by `file_id`/path/attachment_id, fixing the broken attachment path.

**Architecture:** Add `ListFilesInput` + `list_files` action type in `planner.py`; add `file_id` to `ReadFileInput`. In `tool_executor.py`, implement `_list_files` and extend `_read_file` with file_id resolution (first priority) + a fixed attachment_id branch (query `AgentAttachment` directly; read `extracted_text` or from `storage_key` via `PrivateObjectStorage`).

**Tech Stack:** Python, SQLAlchemy, Pydantic

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-agent-file-tools-design.md`
- Owner isolation: normal users see only their own files; `is_super_admin` bypasses owner scoping (existing pattern)
- `_format_file_result` reused unchanged for content output
- Existing tests must pass (39 loop + tool tests)
- Frontend unchanged

---

### Task 1: Planner — list_files input + file_id field + prompt

**Files:**
- Modify: `backend/app/services/agent/planner.py`

**Interfaces:**
- Produces: `ListFilesInput` model; `ReadFileInput.file_id`; `PlanAction` Literal includes `"list_files"`; `input_models` dict includes `list_files`; action_policy text documents both tools

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_tool_files.py` (read the file first to match its imports/structure):

```python
class TestListFilesInput:
    def test_list_files_input_valid(self):
        from app.services.agent.planner import ListFilesInput
        parsed = ListFilesInput(keyword="简历", folder="文档", limit=5)
        assert parsed.keyword == "简历"
        assert parsed.limit == 5

    def test_list_files_input_limit_bounds(self):
        from app.services.agent.planner import ListFilesInput
        from pydantic import ValidationError
        try:
            ListFilesInput(limit=50)
            raise AssertionError("limit must be capped at 20")
        except ValidationError:
            pass

    def test_read_file_input_accepts_file_id(self):
        from app.services.agent.planner import ReadFileInput
        parsed = ReadFileInput(file_id="00000000-0000-0000-0000-000000000001")
        assert parsed.file_id == "00000000-0000-0000-0000-000000000001"

    def test_plan_action_accepts_list_files(self):
        from app.services.agent.planner import PlanAction
        parsed = PlanAction(type="list_files", input={"keyword": "简历"})
        assert parsed.type == "list_files"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesInput -v
```

Expected: FAIL (ImportError — models don't exist).

- [ ] **Step 3: Implement planner changes**

In `backend/app/services/agent/planner.py`:

Add after `ReadFileInput` (line ~51):

```python
class ListFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    folder: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)
```

Change `ReadFileInput` to add `file_id`:

```python
class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str | None = Field(default=None, min_length=36, max_length=36)
    path: str | None = Field(default=None, min_length=1, max_length=500)
    attachment_id: str | None = Field(default=None, min_length=1, max_length=64)
```

Change `PlanAction.type` Literal (line ~63):

```python
    type: Literal["web_search", "http_request", "extract_web_content", "calculator", "read_file", "write_file", "edit_file", "list_files", "finish"]
```

Add to the `input_models` dict in `_validate_plan` (line ~246):

```python
            "list_files": ListFilesInput,
```

Update `action_policy` in `_build_messages` (line ~117):

```python
            action_policy = (
                "允许的 action.type 有 web_search、http_request、extract_web_content、calculator、"
                "list_files（列出或搜索\"我的文件\"中的文件，输入 keyword/folder/limit，返回文件元数据与 file_id）、"
                "read_file（读取文件内容；推荐传入 file_id；path 可为文件名或\"文件夹/文件名\"；支持模糊匹配；"
                "若返回多个候选请用 file_id 指定）、"
                "write_file（创建或覆盖 .md 文件，需 path 和 content）、"
                "edit_file（修改文件，需 path、old_str、new_str，old_str 必须在文件中唯一出现）、"
                "以及 finish。"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesInput -v
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/planner.py backend/tests/test_agent_tool_files.py
git commit -m "feat: add list_files action and file_id field to planner"
```

---

### Task 2: ToolExecutor — `_list_files` implementation

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `FileRepository.list_files`, `find_folder_by_name`, `search_by_folder_and_filename`
- Produces: `_list_files(payload, owner_user_id, is_super_admin) -> dict` — `{"files": [...], "total": n}` metadata only, no content

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_tool_files.py` (match the file's existing mocking pattern for FileRepository — read the file first):

```python
class TestListFilesTool:
    async def test_list_files_by_keyword(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        fake_file = MagicMock()
        fake_file.id = "00000000-0000-0000-0000-000000000001"
        fake_file.original_filename = "杨振东-全栈开发.md"
        fake_file.size_bytes = 1024
        fake_file.updated_at = None

        class FakeRepo:
            async def list_files(self, **kwargs):
                return MagicMock(items=[fake_file], total=1)

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: fake_session)
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", lambda session: FakeRepo())

        result = await executor._list_files({"keyword": "杨振东"}, "user-1", False)
        assert result["total"] == 1
        assert result["files"][0]["filename"] == "杨振东-全栈开发.md"
        assert "content" not in result["files"][0]

    async def test_list_files_by_folder(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        fake_file = MagicMock()
        fake_file.id = "00000000-0000-0000-0000-000000000002"
        fake_file.original_filename = "a.md"
        fake_file.size_bytes = 5
        fake_file.updated_at = None

        fake_folder = MagicMock()
        fake_folder.id = "00000000-0000-0000-0000-000000000099"

        class FakeRepo:
            async def find_folder_by_name(self, owner_id, name):
                return fake_folder
            async def search_by_folder_and_filename(self, folder_id, keyword):
                return [fake_file]

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: fake_session)
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", lambda session: FakeRepo())

        result = await executor._list_files({"folder": "文档"}, "user-1", False)
        assert result["total"] == 1
        assert result["files"][0]["filename"] == "a.md"
```

Note: adapt the `async_session_factory` patch target to match how `tool_executor.py` imports it (check the file's import lines first — it may be imported as `from app.db.session import async_session_factory`, in which case patch `"app.db.session.async_session_factory"` or the module attribute per existing tests).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesTool -v
```

Expected: FAIL (`AttributeError` — no `_list_files`).

- [ ] **Step 3: Implement `_list_files`**

In `backend/app/services/agent/tool_executor.py`, add the dispatch branch in `execute` (after the `read_file` branch, line ~194):

```python
        if action_type == "list_files":
            return await self._list_files(payload, owner_user_id, is_super_admin)
```

Add the method after `_read_file`:

```python
    async def _list_files(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None, is_super_admin: bool
    ) -> dict[str, Any]:
        keyword = payload.get("keyword")
        folder = payload.get("folder")
        limit = min(int(payload.get("limit", 10)), 20)

        async with async_session_factory() as session:
            repo = FileRepository(session)
            files = []
            if folder:
                folder_obj = await repo.find_folder_by_name(owner_user_id, folder)
                if folder_obj is not None:
                    files = await repo.search_by_folder_and_filename(folder_obj.id, keyword or "")
            elif keyword:
                if is_super_admin:
                    files = await repo.search_by_filename(keyword)
                else:
                    if owner_user_id is None:
                        raise ValueError("owner_user_id_required")
                    files = await repo.search_by_owner_and_filename(owner_user_id, keyword)
            else:
                page = await repo.list_files(owner_id=owner_user_id, page_size=limit)
                files = page.items

        files = files[:limit]
        return {
            "files": [
                {
                    "file_id": str(f.id),
                    "filename": f.original_filename,
                    "folder_path": "/",
                    "size_bytes": f.size_bytes,
                    "updated_at": f.updated_at.isoformat() if f.updated_at else None,
                }
                for f in files
            ],
            "total": len(files),
        }
```

Note: if the FileObject model has a `folder` relationship or `folder_path`-like field, prefer it over the hardcoded `"/"` — check `backend/app/models/file.py` first.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestListFilesTool -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: implement list_files tool in tool executor"
```

---

### Task 3: ToolExecutor — `_read_file` file_id support + attachment fix

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `FileRepository.get_file`, `AgentAttachment` model, `PrivateObjectStorage` from `app.services.agent.storage`
- Produces: `_read_file` resolves `file_id` FIRST (before `path`); attachment branch no longer crashes

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_tool_files.py`:

```python
class TestReadFileFixes:
    async def test_read_file_by_file_id(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor

        fake_file = MagicMock()
        fake_file.id = "00000000-0000-0000-0000-000000000001"
        fake_file.original_filename = "杨振东-全栈开发.md"
        fake_file.media_type = "text/markdown"
        fake_file.storage_key = "./var/files/u1/x.md"
        fake_file.extracted_text = None

        class FakeRepo:
            async def get_file(self, file_id):
                return fake_file

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: fake_session)
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", lambda session: FakeRepo())

        # _format_file_result reads from disk; patch it to return a fixed payload
        async def fake_format(file_obj):
            return {"filename": "杨振东-全栈开发.md", "media_type": "text/markdown", "content": "# 简历内容", "truncated": False}
        monkeypatch.setattr(executor, "_format_file_result", fake_format)

        result = await executor._read_file({"file_id": "00000000-0000-0000-0000-000000000001"}, "user-1", False)
        assert result["content"] == "# 简历内容"

    async def test_read_file_attachment_path_no_crash(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.tool_executor import ToolExecutor
        from sqlalchemy import select

        fake_attachment = MagicMock()
        fake_attachment.id = "00000000-0000-0000-0000-000000000010"
        fake_attachment.original_filename = "note.md"
        fake_attachment.media_type = "text/markdown"
        fake_attachment.extracted_text = "附件内容"
        fake_attachment.storage_key = "key-1"

        class FakeResult:
            def scalar_one_or_none(self):
                return fake_attachment

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return FakeResult()

        fake_session_factory = lambda: FakeSession()

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", fake_session_factory)

        result = await executor._read_file({"attachment_id": "00000000-0000-0000-0000-000000000010"}, "user-1", False)
        assert result["content"] == "附件内容"
        assert result["filename"] == "note.md"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestReadFileFixes -v
```

Expected: file_id test fails (file_id ignored — falls to path branch → `path_or_attachment_required`); attachment test fails (AttributeError on `get_owned_attachment`).

- [ ] **Step 3: Implement the fixes in `_read_file`**

In `backend/app/services/agent/tool_executor.py`, replace the method body of `_read_file` (lines 203-280) with:

```python
    async def _read_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None, is_super_admin: bool
    ) -> dict[str, Any]:
        file_id = payload.get("file_id")
        path = payload.get("path")
        attachment_id = payload.get("attachment_id")

        if file_id:
            async with async_session_factory() as session:
                repo = FileRepository(session)
                file_obj = await repo.get_file(uuid.UUID(file_id))
                if file_obj is None:
                    raise ValueError(f"file_not_found: {file_id}")
                if not is_super_admin:
                    if owner_user_id is None or file_obj.owner_user_id != uuid.UUID(str(owner_user_id)):
                        raise ValueError(f"file_not_found: {file_id}")
                return self._format_file_result(file_obj)

        if path:
            # keep existing exact → folder → fuzzy resolution unchanged
            async with async_session_factory() as session:
                repo = FileRepository(session)

                folder_name: str | None = None
                filename = path
                if "/" in path:
                    parts = path.rsplit("/", 1)
                    folder_name = parts[0].strip() or None
                    filename = parts[1].strip()

                if is_super_admin:
                    file_obj = await repo.get_by_filename(path)
                else:
                    if owner_user_id is None:
                        raise ValueError("owner_user_id_required")
                    file_obj = await repo.get_by_owner_and_filename(owner_user_id, path)

                if file_obj is None and folder_name:
                    folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                    if folder is not None:
                        matches = await repo.search_by_folder_and_filename(folder.id, filename)
                        if len(matches) == 1:
                            file_obj = matches[0]
                        elif len(matches) > 1:
                            names = ", ".join(f.original_filename for f in matches[:5])
                            raise ValueError(f"multiple_files_match_in_folder: {folder_name}: {names}")

                if file_obj is None:
                    if is_super_admin:
                        matches = await repo.search_by_filename(filename)
                    else:
                        matches = await repo.search_by_owner_and_filename(owner_user_id, filename)
                    if len(matches) == 1:
                        file_obj = matches[0]
                    elif len(matches) > 1:
                        names = ", ".join(f.original_filename for f in matches[:5])
                        raise ValueError(f"multiple_files_match: {names}")

                if file_obj is None:
                    hint = f" (folder: {folder_name})" if folder_name else ""
                    raise ValueError(f"file_not_found: {path}{hint}")
                return self._format_file_result(file_obj)

        if attachment_id:
            if owner_user_id is None:
                raise ValueError("owner_user_id_required")
            async with async_session_factory() as session:
                result = await session.execute(
                    select(AgentAttachment).where(
                        AgentAttachment.id == uuid.UUID(attachment_id),
                        AgentAttachment.owner_user_id == uuid.UUID(owner_user_id),
                    )
                )
                attachment = result.scalar_one_or_none()
                if attachment is None:
                    raise ValueError(f"attachment_not_found: {attachment_id}")
                text = attachment.extracted_text or ""
                if not text and attachment.storage_key:
                    from app.services.agent.storage import PrivateObjectStorage
                    storage = PrivateObjectStorage()
                    chunks: list[bytes] = []
                    async for chunk in storage.open(attachment.storage_key):
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    extracted = extract_file_text(attachment.media_type or "application/octet-stream", raw)
                    text = extracted["text"]
                if not text:
                    text = "(binary file, no text extracted)"
                return {
                    "filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "content": text[:50000],
                }

        raise ValueError("file_id_or_path_or_attachment_required")
```

Add the required imports at the top of `tool_executor.py` (check existing imports; add what's missing):

```python
from sqlalchemy import select
from app.models.agent import AgentAttachment
```

Note: the `file_id` owner check line is intentionally defensive; if `uuid.UUID(owner_user_id)` fails because `owner_user_id` is already a UUID, wrap the comparison to handle both (use `uuid.UUID(str(owner_user_id))`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py::TestReadFileFixes -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Run the full tool + loop test suites**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_tool_files.py tests/test_agent_loop.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "fix: read_file supports file_id and attachment path no longer crashes"
```

---

### Task 4: Integration — AI discovers then reads a file end-to-end

**Files:**
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: planner with `list_files`/`read_file` (Task 1), tool executor (Tasks 2-3)
- Produces: proof that a run using list_files → read_file completes and reaches `succeeded`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_agent_loop.py` (follow the `TestFastPathIntegration` fixture patterns):

```python
class TestFileToolsIntegration:
    async def test_run_lists_then_reads_file_and_succeeds(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"ft_user_{uid}",
                display_name="FT User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="ft")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "读取我的文件里的杨振东简历并总结", "expert", True, []
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("ft-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        plan_chunks = [
            '{"thought_summary":"先列出文件再读取","action":{"type":"list_files","input":{"keyword":"杨振东"}}}\n',
            "【说明】我先查看你的文件中是否有杨振东的资料。",
        ]

        class FakeStream:
            async def stream_text(self, messages):
                for c in plan_chunks:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())

        # Tool executor: list_files returns one file; read_file returns content
        from unittest.mock import AsyncMock, MagicMock
        fake_list = MagicMock()
        async def fake_execute(action, **kwargs):
            if action["type"] == "list_files":
                return {"files": [{"file_id": "00000000-0000-0000-0000-000000000001", "filename": "杨振东-全栈开发.md"}], "total": 1}
            if action["type"] == "read_file":
                return {"filename": "杨振东-全栈开发.md", "content": "杨振东：全栈开发工程师"}
            return {"final_answer": "完成"}
        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "ft-worker")

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"
```

Note: this test exercises the merged plan+thought path (expert mode bypasses the fast-path gate). The LLM stream declares `list_files` first; a REAL multi-action run would have multiple steps — this test only asserts the first step doesn't crash and the run reaches terminal. If the loop needs the tool observation to feed the next planner step, the test's FakeStream must yield a plan that matches the loop's multi-step expectations — read `_do_process_attempt` carefully and adjust (e.g., yield a `finish` action on the SECOND planner call by checking a call counter in the fake).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFileToolsIntegration -v
```

Expected: FAIL — planner rejects `list_files` type (Literal error) because Task 1 wasn't applied yet in this test file run... if Tasks 1-3 are already committed, this test should FAIL for a different reason (e.g., tool not recognized). Verify the failure is real before implementing.

- [ ] **Step 3: Verify the failure is genuinely caused by missing wiring**

If the test fails because `list_files` is already supported (Tasks 1-3 done), confirm the failure mode is the multi-step flow (planner called twice) and fix the FakeStream to handle it. Do NOT weaken the assertion that the run reaches `succeeded`.

- [ ] **Step 4: Run the full loop suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_agent_loop.py
git commit -m "test: integration — AI discovers and reads a file end-to-end"
```
