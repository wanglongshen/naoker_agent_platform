import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.agent.tool_executor import ToolExecutor
from app.models.file import FileObject, FileFolder
from app.models.agent import AgentAttachment


def _make_file_mock(tmp_path, filename, content):
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    m = MagicMock(spec=FileObject)
    m.storage_key = str(f)
    m.media_type = "text/markdown"
    m.original_filename = filename
    m.owner_user_id = uuid.uuid4()
    m.id = uuid.uuid4()
    return m


class TestReadFile:
    @pytest.mark.anyio
    async def test_read_file_by_path_returns_content(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        my_id = uuid.uuid4()
        fake_file = _make_file_mock(tmp_path, "test.md", "# Hello\n\nWorld")
        fake_file.owner_user_id = my_id

        async def mock_get_by_owner(owner_id, path):
            return fake_file if path == "notes/test.md" else None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner), "search_by_owner_and_filename": staticmethod(AsyncMock(return_value=[])), "find_folder_by_name": staticmethod(AsyncMock(return_value=None)), "search_by_folder_and_filename": staticmethod(AsyncMock(return_value=[])),}),
        )

        result = await executor._read_file({"path": "notes/test.md"}, owner_user_id=my_id, is_super_admin=False)
        assert result["filename"] == "test.md"
        assert "# Hello" in result["content"]

    @pytest.mark.anyio
    async def test_read_file_by_attachment_returns_content(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()
        fake_attachment = MagicMock(spec=AgentAttachment)
        fake_attachment.original_filename = "doc.md"
        fake_attachment.media_type = "text/markdown"
        fake_attachment.extracted_text = "Attachment content"
        fake_attachment.owner_user_id = my_id
        fake_attachment.id = uuid.uuid4()

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

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        result = await executor._read_file({"attachment_id": str(fake_attachment.id)}, owner_user_id=my_id, is_super_admin=False)
        assert result["filename"] == "doc.md"
        assert result["content"] == "Attachment content"

    @pytest.mark.anyio
    async def test_read_file_missing_both_path_and_attachment(self):
        executor = ToolExecutor()
        result = await executor._read_file({}, owner_user_id=uuid.uuid4(), is_super_admin=False)
        assert isinstance(result, dict)
        assert result.get("error") == "file_id_or_path_or_attachment_required"


class TestWriteFile:
    @pytest.mark.anyio
    async def test_write_rejects_non_md_extension(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="only_md"):
            await executor._write_file({"path": "script.py", "content": "print('hello')"}, owner_user_id=uuid.uuid4())


class TestEditFile:
    @pytest.mark.anyio
    async def test_edit_replaces_old_with_new(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()
        fake_file = _make_file_mock(tmp_path, "test.md", "# Hello\n\nWorld")
        fake_file.owner_user_id = owner_id

        async def mock_get_by_owner(owner_id, path):
            return fake_file

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner)}),
        )

        result = await executor._edit_file({"path": "test.md", "old_str": "World", "new_str": "Universe"}, owner_user_id=owner_id)
        assert result["filename"] == "test.md"
        assert result["action"] == "updated"

    @pytest.mark.anyio
    async def test_edit_fails_on_multiple_matches(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()
        fake_file = _make_file_mock(tmp_path, "test.md", "# Hello\n\nWorld\n\nWorld")
        fake_file.owner_user_id = owner_id

        async def mock_get_by_owner(owner_id, path):
            return fake_file

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner)}),
        )

        with pytest.raises(ValueError, match="multiple"):
            await executor._edit_file({"path": "test.md", "old_str": "World", "new_str": "Universe"}, owner_user_id=owner_id)

    @pytest.mark.anyio
    async def test_edit_fails_when_old_not_found(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        owner_id = uuid.uuid4()
        fake_file = _make_file_mock(tmp_path, "test.md", "# Hello")
        fake_file.owner_user_id = owner_id

        async def mock_get_by_owner(owner_id, path):
            return fake_file

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner)}),
        )

        with pytest.raises(ValueError, match="not found"):
            await executor._edit_file({"path": "test.md", "old_str": "Missing", "new_str": "X"}, owner_user_id=owner_id)


class TestFileRBAC:
    @pytest.mark.anyio
    async def test_super_admin_can_read_others_file(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        fake_file = _make_file_mock(tmp_path, "other.md", "Other user data")

        async def mock_get_by_filename(path):
            return fake_file if path == "other.md" else None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_filename": staticmethod(mock_get_by_filename), "search_by_filename": staticmethod(AsyncMock(return_value=[])), "find_folder_by_name": staticmethod(AsyncMock(return_value=None)), "search_by_folder_and_filename": staticmethod(AsyncMock(return_value=[])),}),
        )

        result = await executor._read_file({"path": "other.md"}, owner_user_id=uuid.uuid4(), is_super_admin=True)
        assert result["filename"] == "other.md"
        assert result["content"] == "Other user data"

    @pytest.mark.anyio
    async def test_regular_user_cannot_read_others_file(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()

        async def mock_get_by_owner(owner_id, path):
            return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner), "search_by_owner_and_filename": staticmethod(AsyncMock(return_value=[])), "find_folder_by_name": staticmethod(AsyncMock(return_value=None)), "search_by_folder_and_filename": staticmethod(AsyncMock(return_value=[])),}),
        )

        result = await executor._read_file({"path": "secret.md"}, owner_user_id=my_id, is_super_admin=False)
        assert isinstance(result, dict)
        assert "file_not_found" in str(result.get("error"))

    @pytest.mark.anyio
    async def test_super_admin_cannot_write_without_owner(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor._write_file({"path": "output.md", "content": "# Test"}, owner_user_id=None)


class TestFileSecurity:
    @pytest.mark.anyio
    async def test_rejects_path_traversal(self, monkeypatch):
        executor = ToolExecutor()
        my_id = uuid.uuid4()

        async def mock_get_by_owner(owner_id, path):
            return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner), "search_by_owner_and_filename": staticmethod(AsyncMock(return_value=[])), "find_folder_by_name": staticmethod(AsyncMock(return_value=None)), "search_by_folder_and_filename": staticmethod(AsyncMock(return_value=[])),}),
        )

        result = await executor._read_file({"path": "../../etc/passwd"}, owner_user_id=my_id, is_super_admin=False)
        assert isinstance(result, dict)
        assert "file_not_found" in str(result.get("error"))

    @pytest.mark.anyio
    async def test_write_rejects_non_md_extension(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="only_md"):
            await executor._write_file({"path": "script.py", "content": "print('hello')"}, owner_user_id=uuid.uuid4())


class TestFileToolsIntegration:
    @pytest.mark.anyio
    async def test_execute_dispatches_read_file(self, monkeypatch, tmp_path):
        executor = ToolExecutor()
        my_id = uuid.uuid4()
        fake_file = _make_file_mock(tmp_path, "test.md", "Integration test")
        fake_file.owner_user_id = my_id

        async def mock_get_by_owner(owner_id, path):
            return fake_file

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: AsyncMock())
        monkeypatch.setattr(
            "app.services.agent.tool_executor.FileRepository",
            type("FakeRepo", (), {"__init__": lambda self, session: None, "get_by_owner_and_filename": staticmethod(mock_get_by_owner), "search_by_owner_and_filename": staticmethod(AsyncMock(return_value=[])), "find_folder_by_name": staticmethod(AsyncMock(return_value=None)), "search_by_folder_and_filename": staticmethod(AsyncMock(return_value=[])),}),
        )

        result = await executor.execute({"type": "read_file", "input": {"path": "test.md"}}, owner_user_id=my_id)
        assert result["filename"] == "test.md"

    @pytest.mark.anyio
    async def test_execute_read_file_rejects_when_owner_missing(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor.execute({"type": "read_file", "input": {"path": "test.md"}}, owner_user_id=None)


class TestToolExecutorWireUp:
    def test_execute_signature_accepts_owner_and_admin_kwargs(self):
        executor = ToolExecutor()
        import inspect
        sig = inspect.signature(executor.execute)
        params = list(sig.parameters.keys())
        assert "owner_user_id" in params
        assert "is_super_admin" in params


class TestListFilesInput:
    def test_list_files_input_valid(self):
        from app.services.agent.planner import ListFilesInput
        parsed = ListFilesInput(keyword="简历", folder="文档", limit=5)
        assert parsed.keyword == "简历"
        assert parsed.limit == 5

    def test_list_files_input_limit_bounds(self):
        from app.services.agent.planner import ListFilesInput
        from pydantic import ValidationError

        # 盘点/版本扫描场景需要大 limit（工具实现上限 1000）
        assert ListFilesInput(limit=50).limit == 50
        assert ListFilesInput(limit=1000).limit == 1000
        try:
            ListFilesInput(limit=1001)
            raise AssertionError("limit must be capped at 1000")
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
            async def get_folder_tree(self, owner_id):
                return []

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
            async def get_folder_tree(self, owner_id):
                return []

        fake_session = MagicMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: fake_session)
        monkeypatch.setattr("app.services.agent.tool_executor.FileRepository", lambda session: FakeRepo())

        result = await executor._list_files({"folder": "文档"}, "user-1", False)
        assert result["total"] == 1
        assert result["files"][0]["filename"] == "a.md"


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
        def fake_format(file_obj):
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


class TestWriteFileHardening:
    async def test_write_creates_file_with_extracted_text_and_file_id(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

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
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

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
        fake_file.owner_user_id = "00000000-0000-0000-0000-0000000000aa"

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
            session_history=None, web_enabled=True, final_step=False,
        )
        system_content = messages[0]["content"]
        assert "write_file" in system_content
        assert "覆盖" in system_content or "overwrite" in system_content


class TestFetchWebContent:
    @pytest.mark.anyio
    async def test_execute_dispatches_fetch_web_content(self, monkeypatch):
        executor = ToolExecutor()

        async def fake_post(url, json, **kwargs):
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"title": "抖音视频", "text": "内容", "url": "https://www.douyin.com/video/1", "status_code": 200, "error": None}
            return FakeResp()

        class FakeAsyncClient:
            def __init__(self, timeout=None):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, json, **kwargs):
                return await fake_post(url, json, **kwargs)

        monkeypatch.setattr("app.services.agent.tool_executor.httpx.AsyncClient", FakeAsyncClient)

        result = await executor.execute(
            {"type": "fetch_web_content", "input": {"url": "https://www.douyin.com/video/1"}},
        )
        assert result["title"] == "抖音视频"
        assert result["source"] == "playwright"

    @pytest.mark.anyio
    async def test_fetch_web_content_rejects_bad_url(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="unsafe_network_target"):
            await executor.execute(
                {"type": "fetch_web_content", "input": {"url": "file:///etc/passwd"}},
            )


class TestWriteFileStructureValidation:
    async def test_write_rejects_incomplete_plan_without_saving(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        saved = {"called": False}

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                saved["called"] = True
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._write_file(
            {
                "path": "brief/残缺方案.md",
                "content": "# 创意建议（初稿）\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n## 三、内容玩法\n\n",
                "overwrite": True,
            },
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert saved["called"] is False  # 未保存
        assert result["error"] == "plan_structure_incomplete"
        assert "前策调研" in result["missing_modules"]
        assert "投流策略" in result["missing_modules"]

    async def test_write_rejects_title_only_skeleton(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        saved = {"called": False}

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                saved["called"] = True
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        content = (
            "# 方案\n\n"
            "## 一、Brief Recap\n\n## 二、前策调研\n\n## 三、本品表现\n\n"
            "## 四、用户分析\n\n## 五、创意与传播规划\n\n## 六、投流策略\n\n"
            "## 七、Roadmap\n\n## 八、附录\n\n"
        )
        result = await executor._write_file(
            {"path": "brief/完整方案.md", "content": content, "overwrite": True},
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert result.get("error") == "plan_content_shallow"
        assert saved["called"] is False

    async def test_write_rejection_includes_skeleton(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        saved = {"called": False}

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                saved["called"] = True
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._write_file(
            {
                "path": "brief/残缺方案.md",
                "content": "# 创意建议（初稿）\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n## 三、内容玩法\n\n",
                "overwrite": True,
            },
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert result["error"] == "plan_structure_incomplete"
        assert "skeleton" in result
        assert "## 一、Brief Recap" in result["skeleton"]
        assert "## 八、附录" in result["skeleton"]
        assert "前策调研" in result["missing_modules"]

    async def test_write_file_uses_routed_doc_structure(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structure(goal):
            return ["目标回顾", "市场与友商调研", "社媒平台生态概览",
                    "品牌资产与账号机会梳理", "矩阵账号策略总纲", "品牌官号内容策划",
                    "创始人 IP 号内容策划", "投流与增长规划", "3 个月 Roadmap 与交付保障"]

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/矩阵号代运营方案.md",
                       "content": "# 矩阵号代运营方案\n\n## 一、目标回顾\n\n## 二、投流策略\n\n"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="请生成矩阵号代运营方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "市场与友商调研" in result["missing_modules"]
        assert "## 二、市场与友商调研" in result["skeleton"]

    async def test_write_file_default_structure_when_no_goal(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structure(goal):
            return ["目标回顾", "市场调研", "用户画像"]

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/普通方案.md",
                       "content": "# 方案\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写个文案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "目标回顾" in result["missing_modules"]

    async def test_resolve_structure_survives_load_exception(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        te_mod._structure_cache.clear()

        class BoomSession:
            async def __aenter__(self):
                raise RuntimeError("simulated db session failure")
            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: BoomSession())
        modules = await te_mod._resolve_active_structure("写个文案")
        assert modules == DEFAULT_MODULES

    async def test_resolve_structure_uses_cache_when_load_fails(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import resolve_structure_doc
        from app.core.config import get_settings

        doc_path = resolve_structure_doc("写个文案") or get_settings().workflow_core_doc_path
        te_mod._structure_cache.clear()
        te_mod._structure_cache[doc_path] = ("fingerprint", ["warm模块A", "warm模块B"])

        class BoomSession:
            async def __aenter__(self):
                raise RuntimeError("simulated db session failure")
            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: BoomSession())
        modules = await te_mod._resolve_active_structure("写个文案")
        assert modules == ["warm模块A", "warm模块B"]

    async def test_resolve_structure_survives_storage_os_error(self, monkeypatch):
        from unittest.mock import AsyncMock
        from app.services.agent import tool_executor as te_mod
        from app.services.agent import workflow_policy as wp_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        te_mod._structure_cache.clear()

        async def boom(session, owner_id, doc_path):
            raise OSError("simulated storage read failure")

        fake_policy = type("FakePolicy", (), {})()
        fake_policy._resolve_super_admin_id = AsyncMock(
            return_value=uuid.UUID("00000000-0000-0000-0000-0000000000aa"))
        fake_policy._load_doc = boom
        monkeypatch.setattr(wp_mod, "workflow_policy", fake_policy)

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())
        modules = await te_mod._resolve_active_structure("写个文案")
        assert modules == DEFAULT_MODULES

    async def test_blueprint_parse_uses_full_document(self, monkeypatch, tmp_path):
        from types import SimpleNamespace
        from app.services.agent import tool_executor as te_mod
        from app.services.agent import workflow_policy as wp_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        long_blueprint = (
            "## 3. 正式方案默认结构\n\n"
            "1. Brief Recap：复述背景、推广主体、核心任务、目标心智/效果。\n"
            "2. 前策调研与思考：行业/平台现状、竞品拆解、demo 链接、前端小结。\n"
            "3. 本品表现与机会下探：本品资产、平台表现、用户原生表达、卖点转译。\n"
            "4. 用户分析与达人类型：人群画像、内容偏好、达人类型、内容任务。\n"
            "5. 创意与传播规划：传播 TAG、核心创意内容、达人类型、Message House、Content Demo。\n"
            "6. 投流策略：阶段、预算比例、投放形式、关键词、人群包、效果口径。\n"
            "7. Roadmap：阶段、时间、核心目标、节点、物料、投放、KPI。\n"
            "8. 附录：链接筛选、团队、假设。\n"
        )
        # 蓝图的结构段落在 12000 字符截断点之后
        padded = "x" * 12050 + "\n" + long_blueprint
        blueprint_file = tmp_path / "blueprint_padded.md"
        blueprint_file.write_text(padded, encoding="utf-8")

        te_mod._structure_cache.clear()
        owner_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
        # 真实 WorkflowPolicy 实例 + 仅打桩 _resolve_super_admin_id/_resolve_file：
        # 当前实现会走真实 _load_doc（含 12000 截断）→ 解析失败 → DEFAULT_MODULES（RED）；
        # 修复后走 _resolve_file + 全量读文件 → 命中蓝图结构（GREEN）。
        real_policy = wp_mod.WorkflowPolicy()
        real_policy._resolve_super_admin_id = AsyncMock(return_value=owner_id)
        real_policy._resolve_file = AsyncMock(
            return_value=SimpleNamespace(storage_key=str(blueprint_file), updated_at=None)
        )
        monkeypatch.setattr(wp_mod, "workflow_policy", real_policy)

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())
        modules = await te_mod._resolve_active_structure("写个文案")
        assert modules != DEFAULT_MODULES
        assert modules[1] == "前策调研与思考"

    async def test_rejection_hint_guides_incremental_write(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺模块方案.md",
                       "content": "## 一、Brief Recap\n\n只有一章"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "edit_file" in result["hint"]
        assert "骨架" in result["hint"]

    async def test_rejects_when_one_module_missing(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺一模块.md",
                       "content": "# 方案\n\n## 一、Brief Recap\n\n## 二、前策调研与思考\n\n## 三、本品表现与机会下探\n\n## 四、用户分析与达人类型\n\n## 五、创意与传播规划\n\n## 六、投流策略\n\n## 七、Roadmap\n"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "附录" in result["missing_modules"]

    async def test_rejects_placeholder_words(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        content = "\n".join(
            [f"## {name}\n\n内容" for name in DEFAULT_MODULES]
        ) + "\n\n数据待补充"
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/占位.md", "content": content}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_has_placeholders"
        assert "待补充" in result["placeholder_words"]

    async def test_write_file_rejects_missing_subitems(self, monkeypatch):
        from unittest.mock import MagicMock
        from pathlib import Path as FilePath
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())

        async def fake_structure(goal):
            return DEFAULT_MODULES

        async def fake_guides(goal):
            return {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_resolve_active_guides", fake_guides)
        executor = te_mod.ToolExecutor()
        content = (
            "# 方案\n\n"
            "## 一、Brief Recap\n\n## 二、前策调研\n\n## 三、本品表现\n\n"
            "## 四、用户分析\n\n## 五、创意与传播规划\n\n## 六、投流策略\n"
            "- 阶段：预热期\n- 预算比例：40/40/20\n\n"
            "## 七、Roadmap\n\n## 八、附录\n\n"
        )
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺子项方案.md", "content": content}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_subitems_incomplete"
        assert "投流策略" in result["missing_subitems"]
        assert "投放形式" in result["missing_subitems"]["投流策略"]
        assert "关键词" in result["missing_subitems"]["投流策略"]
        assert "skeleton" in result

    async def test_clean_content_passes_both_checks(self, monkeypatch):
        from unittest.mock import MagicMock
        from pathlib import Path as FilePath
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        saved = {"called": False}

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                saved["called"] = True
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())

        executor = te_mod.ToolExecutor()
        content = "\n".join(
            [f"## {name}\n\n" + "完整内容描述。" * 50 for name in DEFAULT_MODULES]
        )
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/完整.md", "content": content}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result.get("error") is None
        assert saved["called"] is True
        assert result["action"] in ("created", "updated")

    async def test_rejection_skeleton_includes_blueprint_descriptions(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES, extract_blueprint_guides

        blueprint = (
            "## 3. 正式方案默认结构\n\n"
            "1. Brief Recap：复述背景、推广主体、核心任务。\n"
            "2. 附录：达人筛选、团队、案例。\n"
        )

        async def fake_structure(goal):
            return DEFAULT_MODULES

        async def fake_load(doc_path):
            return blueprint

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_load_doc_text", fake_load)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺模块.md",
                       "content": "## 一、Brief Recap\n\n只有一章"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "> 复述背景、推广主体、核心任务。" in result["skeleton"]


class TestFeishuActions:
    @pytest.mark.anyio
    async def test_create_doc_dispatches(self, monkeypatch):
        executor = ToolExecutor()
        uid = uuid.uuid4()

        fake_service = type("FakeService", (), {
            "create_document": AsyncMock(return_value={"document_id": "doc1", "url": "https://feishu.cn/docx/doc1", "title": "报告"}),
            "read_document": AsyncMock(return_value={"data": {"content": "x"}}),
            "edit_document": AsyncMock(return_value={}),
            "set_permission": AsyncMock(return_value={}),
        })()
        monkeypatch.setattr("app.services.agent.tool_executor.FeishuService", lambda: fake_service)

        result = await executor.execute(
            {"type": "feishu_create_doc", "input": {"title": "报告", "content": "# 标题"}},
            owner_user_id=uid,
        )
        assert result["document_id"] == "doc1"
        assert result["source"] == "feishu"

    @pytest.mark.anyio
    async def test_read_requires_owner(self, monkeypatch):
        executor = ToolExecutor()
        monkeypatch.setattr("app.services.agent.tool_executor.FeishuService", lambda: type("F", (), {})())
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor.execute(
                {"type": "feishu_read_doc", "input": {"doc_token": "d1"}},
                owner_user_id=None,
            )


class TestFetchWebContentCookie:
    def test_parse_cookie_string_basic(self):
        from app.services.agent.tool_executor import _parse_cookie_string
        cookies = _parse_cookie_string("sessionid=abc; uid=123", "www.douyin.com")
        assert len(cookies) == 2
        assert cookies[0]["name"] == "sessionid"
        assert cookies[0]["value"] == "abc"
        assert cookies[0]["domain"] == "www.douyin.com"

    def test_parse_cookie_string_skips_invalid(self):
        from app.services.agent.tool_executor import _parse_cookie_string
        cookies = _parse_cookie_string("; invalid; a=b", "x.com")
        assert len(cookies) == 1
        assert cookies[0]["name"] == "a"


class TestFetchWebContentLoginExpired:
    def test_marks_douyin_verification_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "验证中间页 请稍候", "title": "验证中间页", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["login_expired"] is True

    def test_normal_content_not_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "热门视频" * 100, "title": "抖音", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["login_expired"] is False

    def test_generic_platform_not_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "generic", "text": "captcha 验证", "title": "x", "url": "https://example.com", "status_code": 200}
        result = _build_fetch_result(data, "https://example.com")
        assert result["login_expired"] is False

    def test_result_keeps_all_fields(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "x" * 600, "title": "T", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["status_code"] == 200
        assert result["title"] == "T"
        assert result["source"] == "playwright"
        assert result["login_expired"] is False


class TestWriteFileCreatedAtRefresh:
    async def test_overwrite_refreshes_created_at(self, test_engine, monkeypatch, tmp_path):
        import uuid
        from datetime import UTC, datetime, timedelta
        from pathlib import Path

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.rbac import User
        from app.models.file import FileObject
        from app.models.base import Base
        from app.services.agent import tool_executor
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.chdir(tmp_path)
        factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(tool_executor, "async_session_factory", factory)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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


class TestStructureRetryGate:
    """同一 (owner, path) 连续 3 次结构校验失败后放行，避免循环拦截到超时。"""

    @pytest.mark.anyio
    async def test_third_consecutive_failure_passes_through(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.tool_executor import (
            _structure_retry_counts,
        )
        from unittest.mock import MagicMock
        from pathlib import Path as FilePath

        _structure_retry_counts.clear()

        async def fake_structure(goal):
            return ["目标回顾", "市场调研"]

        async def fake_guides(goal):
            return {
                "目标回顾": "复述背景、推广主体",
                "市场调研": "竞品拆解、行业现状",
            }

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_resolve_active_guides", fake_guides)
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        class FakeResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            def __init__(self):
                self.added = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def execute(self, *a, **k):
                return FakeResult()

            async def flush(self):
                pass

            async def commit(self):
                pass

            async def get(self, *a, **k):
                return None

            def add(self, obj):
                self.added.append(obj)

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())

        from app.services.agent.tool_executor import ToolExecutor

        executor = ToolExecutor()
        owner = "00000000-0000-0000-0000-0000000000aa"
        bad = {
            "type": "write_file",
            "input": {
                "path": "brief/x_V1.md",
                "content": "# 方案\n\n## 一、目标回顾\n\n\n## 二、市场调研\n\n",
            },
        }
        results = []
        for _ in range(4):
            r = await executor.execute(bad, owner_user_id=owner, goal="写个方案")
            results.append(r)

        assert results[0]["error"] == "plan_subitems_incomplete"
        assert results[1]["error"] == "plan_subitems_incomplete"
        # 第 3 次起放行：不再返回校验错误
        assert "error" not in results[2]
        assert "file_id" in results[2]
        assert "error" not in results[3]

    def test_success_clears_retry_count(self):
        from app.services.agent.tool_executor import (
            _structure_retry_counts,
            _structure_retry_gate,
        )

        _structure_retry_counts.clear()
        _structure_retry_gate("owner1", "a.md", passed=False)
        _structure_retry_gate("owner1", "a.md", passed=False)
        _structure_retry_gate("owner1", "a.md", passed=True)
        assert _structure_retry_gate("owner1", "a.md", passed=False) is False

    def test_different_paths_counted_independently(self):
        from app.services.agent.tool_executor import (
            _structure_retry_counts,
            _structure_retry_gate,
        )

        _structure_retry_counts.clear()
        assert _structure_retry_gate("o", "p1.md", passed=False) is False
        assert _structure_retry_gate("o", "p1.md", passed=False) is False
        assert _structure_retry_gate("o", "p2.md", passed=False) is False
        assert _structure_retry_gate("o", "p1.md", passed=False) is True


class TestWriteFileContentDepth:
    @pytest.mark.anyio
    async def test_title_only_skeleton_rejected(self, monkeypatch):
        from unittest.mock import MagicMock
        from pathlib import Path as FilePath

        from app.services.agent import tool_executor as te_mod
        from app.services.agent.tool_executor import ToolExecutor

        async def fake_structure(goal):
            return ["目标回顾", "市场调研"]

        async def fake_guides(goal):
            return {"目标回顾": "复述背景", "市场调研": "竞品拆解"}

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_resolve_active_guides", fake_guides)
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        class FakeResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            def __init__(self):
                self.added = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def execute(self, *a, **k):
                return FakeResult()

            async def flush(self):
                pass

            async def commit(self):
                pass

            async def get(self, *a, **k):
                return None

            def add(self, obj):
                self.added.append(obj)

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor.execute(
            {
                "type": "write_file",
                "input": {
                    "path": "brief/x_V1.md",
                    "content": "# 方案\n\n## 一、目标回顾\n\n\n## 二、市场调研\n\n",
                },
            },
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写个方案",
        )
        assert result.get("error") == "plan_content_shallow"
        assert "目标回顾" in result.get("shallow_modules", [])

    @pytest.mark.anyio
    async def test_section_with_body_passes_all_checks(self, monkeypatch):
        from unittest.mock import MagicMock
        from pathlib import Path as FilePath

        from app.services.agent import tool_executor as te_mod
        from app.services.agent.tool_executor import ToolExecutor, _structure_retry_counts

        _structure_retry_counts.clear()

        async def fake_structure(goal):
            return ["目标回顾", "市场调研"]

        async def fake_guides(goal):
            return {"目标回顾": "复述背景、推广主体", "市场调研": "竞品拆解、行业现状"}

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_resolve_active_guides", fake_guides)
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        class FakeResult:
            def scalar_one_or_none(self):
                return None

        class FakeSession:
            def __init__(self):
                self.added = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def execute(self, *a, **k):
                return FakeResult()

            async def flush(self):
                pass

            async def commit(self):
                pass

            async def get(self, *a, **k):
                return None

            def add(self, obj):
                self.added.append(obj)

        monkeypatch.setattr(te_mod, "async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor.execute(
            {
                "type": "write_file",
                "input": {
                    "path": "brief/x_V1.md",
                    "content": (
                        "# 方案\n\n## 一、目标回顾\n\n"
                        + "复述背景与推广主体，确认核心任务。" * 30
                        + "\n\n## 二、市场调研\n\n"
                        + "竞品拆解与行业现状。" * 30
                    ),
                },
            },
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写个方案",
        )
        assert result.get("error") is None
        assert result.get("file_id")


class TestFetchPlatformSearch:
    async def _executor(self):
        from app.services.agent.tool_executor import ToolExecutor

        return ToolExecutor()

    async def test_returns_samples_with_note(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "samples": [
                        {"title": "成毅GAP大片", "author": "博主", "url": "https://www.douyin.com/video/1", "likes": 100}
                    ],
                    "sample_count": 1,
                    "login_required": False,
                    "platform": "douyin",
                    "error": None,
                }

        async def fake_post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "douyin", "keyword": "GAP成毅", "max_results": 30},
            owner_user_id=None,
        )
        assert result["platform"] == "douyin"
        assert result["sample_count"] == 1
        assert result["samples"][0]["title"] == "成毅GAP大片"
        assert "累计" in result["note"]
        assert "/search" in captured["url"]

    async def test_login_required_passthrough(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"samples": [], "sample_count": 0, "login_required": True, "platform": "xiaohongshu", "error": None}

        async def fake_post(self, url, json=None):
            return FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "xiaohongshu", "keyword": "成毅", "max_results": 30},
            owner_user_id=None,
        )
        assert result["login_required"] is True

    async def test_renderer_unavailable_is_retryable(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import (
            ToolExecutor,
            RetryableToolError,
        )

        async def fake_post(self, url, json=None):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        try:
            await ToolExecutor()._fetch_platform_search(
                {"platform": "douyin", "keyword": "x", "max_results": 10},
                owner_user_id=None,
            )
            raise AssertionError("must raise RetryableToolError")
        except RetryableToolError as exc:
            assert "web_renderer_unavailable" in str(exc)

    async def test_http_status_error_is_retryable_with_conventional_key(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import (
            ToolExecutor,
            RetryableToolError,
        )

        class FakeResponse:
            status_code = 502

            def raise_for_status(self):
                raise httpx.HTTPStatusError(
                    "502", request=httpx.Request("POST", "http://x"), response=self
                )

        async def fake_post(self, url, json=None):
            return FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        try:
            await ToolExecutor()._fetch_platform_search(
                {"platform": "douyin", "keyword": "x", "max_results": 10},
                owner_user_id=None,
            )
            raise AssertionError("must raise RetryableToolError")
        except RetryableToolError as exc:
            assert "web_renderer_status" in str(exc)

    async def test_same_platform_calls_are_throttled(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        ToolExecutor._last_platform_search_at = {}
        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "samples": [],
                    "sample_count": 0,
                    "login_required": False,
                    "platform": "douyin",
                    "error": None,
                }

        async def fake_post(self, url, json=None):
            return FakeResponse()

        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await ToolExecutor()._fetch_platform_search(
            {"platform": "douyin", "keyword": "x", "max_results": 10},
            owner_user_id=None,
        )
        await ToolExecutor()._fetch_platform_search(
            {"platform": "douyin", "keyword": "y", "max_results": 10},
            owner_user_id=None,
        )
        assert any(s > 0 for s in sleeps), f"expected throttle sleep, got {sleeps}"
        # 不同平台互不影响
        ToolExecutor._last_platform_search_at = {}
        await ToolExecutor()._fetch_platform_search(
            {"platform": "xiaohongshu", "keyword": "x", "max_results": 10},
            owner_user_id=None,
        )
        assert any(s > 0 for s in sleeps)


class TestPlatformNotePersist:
    async def test_fetch_platform_search_persists_and_returns_stored_count(
        self, monkeypatch
    ):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        ToolExecutor._last_platform_search_at = {}

        search_response = {
            "samples": [
                {
                    "title": "笔记一",
                    "author": "A",
                    "url": "https://www.xiaohongshu.com/explore/n1",
                    "likes": 1,
                },
                {
                    "title": "",
                    "author": "",
                    "url": "",
                    "likes": None,
                },  # 清洗应丢弃
            ],
            "sample_count": 2,
            "login_required": False,
            "platform": "xiaohongshu",
            "error": None,
        }
        detail_calls = []

        class FakeSearchResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return search_response

        async def fake_post(self, url, json=None, timeout=None):
            nonlocal_platform = json.get("platform") if json else None
            if url.endswith("/search"):
                return FakeSearchResponse()
            # /detail
            detail_calls.append(json)
            return _FakeJson(
                {
                    "platform": json["platform"],
                    "url": json["url"],
                    "title": "笔记一",
                    "content": "正文全文",
                    "published_at": "2026-08-01T00:00:00+00:00",
                    "like_count": 10,
                    "collect_count": 5,
                    "comment_count": 2,
                    "topic_tags": ["护肤"],
                    "author": "A",
                    "image_urls": ["https://img.example.com/d.jpg"],
                    "login_required": False,
                    "error": None,
                }
            )

        class _FakeJson:
            def __init__(self, data):
                self._d = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._d

        # 屏蔽真实入库：monkeypatch repository
        import app.repositories.platform_note_repository as pnr

        upserted = []

        async def fake_upsert(session, owner_user_id, platform, keyword, sample):
            upserted.append(sample)
            return True

        async def fake_count(session, owner_user_id, platform):
            return 1

        monkeypatch.setattr(pnr, "upsert", fake_upsert)
        monkeypatch.setattr(pnr, "count_platform", fake_count)
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        # 屏蔽真实 cookie 查询（web_cookie_store 在模块顶层绑定了 session 工厂）
        import app.services.agent.web_cookie_store as wcs

        async def fake_cookie(owner_user_id, domain):
            return None

        monkeypatch.setattr(wcs, "get_user_cookie_string", fake_cookie)

        # 工具内的入库是独立 session（async_session_factory）——patch 它
        import app.db.session as dbs

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def commit(self):
                return None

            def execute(self, *a, **k):
                raise AssertionError("execute should not be reached (repo patched)")

        monkeypatch.setattr(dbs, "async_session_factory", lambda: FakeSession())

        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "xiaohongshu", "keyword": "成毅", "max_results": 10},
            owner_user_id=__import__("uuid").UUID("4c40bada-b2e6-45ea-b1b2-a2e43e663072"),
        )
        assert result["sample_count"] == 2
        assert result["stored_count"] == 1
        assert result["platform_total"] == 1
        assert len(upserted) == 1
        assert upserted[0]["title"] == "笔记一"
        assert upserted[0]["content"] == "正文全文"
        assert upserted[0]["image_urls"] == ["https://img.example.com/d.jpg"]
        assert len(detail_calls) == 1
        assert "150" in result["note"] and "40" in result["note"]

