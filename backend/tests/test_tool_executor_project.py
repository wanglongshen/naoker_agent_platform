import uuid
from pathlib import Path as FilePath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.rbac import User


@pytest.fixture
async def owner_user(test_db):
    async with test_db() as db:
        user = User(
            username="owner_user",
            display_name="Owner User",
            password_hash="test-password-hash",
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    return SimpleNamespace(id=user_id)


async def _make_folder(test_db, owner_user, name):
    from app.models.file import FileFolder

    async with test_db() as db:
        folder = FileFolder(
            owner_user_id=owner_user.id, name=name, path=f"/{name}", depth=0
        )
        db.add(folder)
        await db.flush()
        await db.commit()
        return folder


async def _make_file(test_db, owner_user, folder, filename, content, tmp_path):
    from app.models.file import FileObject

    storage = tmp_path / f"{filename}-{uuid.uuid4()}.md"
    storage.write_text(content, encoding="utf-8")
    async with test_db() as db:
        file_obj = FileObject(
            owner_user_id=owner_user.id,
            folder_id=folder.id,
            storage_key=str(storage),
            filename=filename,
            original_filename=filename,
            media_type="text/markdown",
            size_bytes=len(content.encode("utf-8")),
            sha256="a" * 64,
        )
        db.add(file_obj)
        await db.flush()
        await db.commit()
        return file_obj


class TestProjectScopedFileTools:
    @pytest.mark.anyio
    async def test_read_file_scoped_to_project(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_a, "方案.md", "A 项目内容", tmp_path)
        await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        assert "A 项目内容" in result.get("content", "")

    @pytest.mark.anyio
    async def test_read_file_other_project_file_not_found(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        # 项目 A 内无此文件 → 找不到（不返回 B 的内容）
        assert "error" in result
        assert "未找到" in str(result)

    @pytest.mark.anyio
    async def test_write_file_defaults_to_project_root(
        self, test_db, owner_user, monkeypatch
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "write_file", "input": {"path": "新建方案.md", "content": "正文"}},
            owner_user_id=owner_user.id,
            goal="生成方案",
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        # 验证文件落在项目 A 根
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            files = await repo.search_by_folder_and_filename(folder_a.id, "新建方案")
        assert len(files) == 1
        assert files[0].folder_id == folder_a.id

    @pytest.mark.anyio
    async def test_write_file_to_folder_outside_project_rejected(
        self, test_db, owner_user, monkeypatch
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )
        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        await _make_folder(test_db, owner_user, "项目B")
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "write_file", "input": {"path": "项目B/xx.md", "content": "正文"}},
            owner_user_id=owner_user.id,
            goal="生成方案",
            project_folder_id=folder_a.id,
        )
        assert "error" in result

    @pytest.mark.anyio
    async def test_unbound_project_keeps_global_behavior(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_b, "方案.md", "B 内容", tmp_path)
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=None,
        )
        assert "error" not in result, result
        assert "B 内容" in result.get("content", "")

    @pytest.mark.anyio
    async def test_edit_file_scoped_to_project_rejects_outside(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        with pytest.raises(ValueError, match="未找到"):
            await executor.execute(
                {
                    "type": "edit_file",
                    "input": {"path": "方案.md", "old_str": "B", "new_str": "C"},
                },
                owner_user_id=owner_user.id,
                project_folder_id=folder_a.id,
            )

    @pytest.mark.anyio
    async def test_read_file_path_with_slash_outside_project_no_crash(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"path": "项目B/方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        # 项目 B 不在当前会话项目内 → 返回未找到观察，而不是抛异常
        assert "error" in result
        assert "未找到" in str(result)

    @pytest.mark.anyio
    async def test_read_file_by_id_outside_project_not_found(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        file_b = await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"file_id": str(file_b.id)}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        assert "error" in result
        assert "未找到" in str(result)

    @pytest.mark.anyio
    async def test_read_file_by_id_inside_project_success(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        file_a = await _make_file(test_db, owner_user, folder_a, "方案.md", "A 项目内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"file_id": str(file_a.id)}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        assert "A 项目内容" in result.get("content", "")

    @pytest.mark.anyio
    async def test_edit_file_by_id_outside_project_rejected(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        file_b = await _make_file(test_db, owner_user, folder_b, "方案.md", "B 项目内容", tmp_path)

        executor = ToolExecutor()
        with pytest.raises(ValueError, match="未找到"):
            await executor.execute(
                {
                    "type": "edit_file",
                    "input": {"file_id": str(file_b.id), "old_str": "B", "new_str": "C"},
                },
                owner_user_id=owner_user.id,
                project_folder_id=folder_a.id,
            )

    @pytest.mark.anyio
    async def test_list_files_scoped_to_project(
        self, test_db, owner_user, monkeypatch, tmp_path
    ):
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "app.services.agent.tool_executor.async_session_factory", test_db
        )

        folder_a = await _make_folder(test_db, owner_user, "项目A")
        folder_b = await _make_folder(test_db, owner_user, "项目B")
        await _make_file(test_db, owner_user, folder_a, "方案A.md", "A 内容", tmp_path)
        await _make_file(test_db, owner_user, folder_b, "方案B.md", "B 内容", tmp_path)

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "list_files", "input": {"keyword": "方案"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        filenames = [f["filename"] for f in result["files"]]
        assert "方案A.md" in filenames
        assert "方案B.md" not in filenames
