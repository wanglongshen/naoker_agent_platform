# 会话项目隔离（Agent 工作区）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 会话绑定"项目"（文件库顶层文件夹）后，Agent 文件工具只在项目树内读写，跨项目文件物理不可达；run 启动时快照项目。

**Architecture:** `agent_sessions.project_folder_id`（可空可改，会话内切换）+ `agent_runs.project_folder_id`（create_run 快照）→ loop 把快照传给 `tool_executor.execute(..., project_folder_id=...)` → 文件工具检索范围收窄为项目子树（FileRepository 新增 BFS 子树 id + IN 查询）。前端会话页顶部项目选择器切换。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, React + AntD

**Spec:** `docs/superpowers/specs/2026-08-07-session-project-isolation-design.md` (4bfff20)

## Global Constraints

- 已核实事实：`FileFolder` 字段 `id/owner_user_id/parent_folder_id/name/path/depth/child_file_count`；`FileObject` 有 `folder_id/original_filename/is_deleted/owner_user_id`；`tool_executor.execute(action, web_enabled=True, owner_user_id=None, is_super_admin=False, goal=None)`（tool_executor.py:358），loop.py:1257 调用；前端取文件夹 `api<FolderNode[]>("/api/files/folders")`（file-management.tsx:75），`FolderNode` 类型在 `@/types/file`
- 会话切换校验：文件夹属于当前用户 + `parent_folder_id IS NULL`（顶层）
- 隔离 = 检索范围收窄（查询条件层面），不返回项目外文件内容；未绑定（None）= 现状全局行为
- 迁移：手写（写前 `alembic heads` 核实当前 head），不建 FK 约束（文件夹可软删）
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`
- **git 纪律**：只 `git add` 本任务精确路径，禁 `git add -A`；提交前 `git status --short`；仓库有并行会话改动
- 前端测试约定：禁页面级 byRole（jsdom 病理），用 querySelectorAll("button") + textContent 匹配
- 已有测试文件可参考：backend/tests/ 下 test_file_*（repo 测试写法）、test_agent_api.py（会话 API）、test_tool_executor*.py（工具测试）

---

### Task 1: 模型字段 + 迁移 + FileRepository 子树检索

**Files:**
- Modify: `backend/app/models/agent.py`（AgentSession + AgentRun 各加一列）
- Create: `backend/alembic/versions/<hex>_add_session_run_project_folder.py`
- Modify: `backend/app/repositories/file_repository.py`
- Test: `backend/tests/test_file_repository_project.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `AgentSession.project_folder_id: uuid.UUID | None`
  - `AgentRun.project_folder_id: uuid.UUID | None`
  - `FileRepository.get_folder_subtree_ids(folder_id: uuid.UUID) -> list[uuid.UUID]`（含自身，BFS 沿 parent_folder_id）
  - `FileRepository.search_by_folder_ids(folder_ids: list[uuid.UUID], keyword: str) -> list[FileObject]`
  - `FileRepository.get_by_folder_ids(folder_ids: list[uuid.UUID], filename: str) -> FileObject | None`

- [ ] **Step 1: 核实 alembic head 与模型导入处**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic heads`（workdir backend）
Expected: 单行 head——迁移 down_revision。
读 `backend/app/models/agent.py` 的 AgentSession（~line 30-60）与 AgentRun 类定义——确认插入字段的位置与现有类型风格（Mapped[uuid.UUID | None] = mapped_column(nullable=True)）。

- [ ] **Step 2: 模型加字段**

`backend/app/models/agent.py`：

AgentSession 加（`is_pinned` 之后）：
```python
    project_folder_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
```

AgentRun 加（找到 AgentRun 类，末尾任意字段后）：
```python
    project_folder_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
```

（不建 FK——文件夹可软删；类型与文件库 folder id 一致。）

- [ ] **Step 3: 写迁移**

`backend/alembic/versions/<hex>_add_session_run_project_folder.py`（revision=<hex>，down_revision=Step 1 的 head）：

```python
"""add project_folder_id to sessions and runs

Revision ID: <hex>
Revises: <STEP1_HEAD>
Create Date: 2026-08-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '<hex>'
down_revision: Union[str, Sequence[str], None] = '<STEP1_HEAD>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_sessions', sa.Column('project_folder_id', sa.Uuid(), nullable=True))
    op.add_column('agent_runs', sa.Column('project_folder_id', sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_runs', 'project_folder_id')
    op.drop_column('agent_sessions', 'project_folder_id')
```

- [ ] **Step 4: 应用迁移**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head`（workdir backend；表已有冲突 → stamp 并注明）

- [ ] **Step 5: 写失败测试**

`backend/tests/test_file_repository_project.py`（fixtures 照现有 test_file_repository 测试——核实其 fixture 名（test_db/owner_user 等）并从现有文件复制）：

```python
import uuid

import pytest


class TestFolderSubtree:
    @pytest.mark.anyio
    async def test_subtree_includes_self_and_all_descendants(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root = FileFolder(owner_user_id=owner_user.id, name="项目A", depth=0)
            db.add(root)
            await db.flush()
            child = FileFolder(
                owner_user_id=owner_user.id, name="子1", depth=1,
                parent_folder_id=root.id,
            )
            db.add(child)
            await db.flush()
            grand = FileFolder(
                owner_user_id=owner_user.id, name="孙1", depth=2,
                parent_folder_id=child.id,
            )
            db.add(grand)
            await db.flush()

            ids = await repo.get_folder_subtree_ids(root.id)
            assert set(ids) == {root.id, child.id, grand.id}

    @pytest.mark.anyio
    async def test_subtree_excludes_deleted_and_other_branches(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root_a = FileFolder(owner_user_id=owner_user.id, name="A", depth=0)
            root_b = FileFolder(owner_user_id=owner_user.id, name="B", depth=0)
            db.add_all([root_a, root_b])
            await db.flush()
            deleted_child = FileFolder(
                owner_user_id=owner_user.id, name="删", depth=1,
                parent_folder_id=root_a.id, is_deleted=True,
            )
            db.add(deleted_child)
            await db.flush()

            ids = await repo.get_folder_subtree_ids(root_a.id)
            assert set(ids) == {root_a.id}
            ids_b = await repo.get_folder_subtree_ids(root_b.id)
            assert set(ids_b) == {root_b.id}


class TestFolderScopedFileSearch:
    @pytest.mark.anyio
    async def test_search_by_folder_ids_scopes_to_given_folders(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder, FileObject
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root_a = FileFolder(owner_user_id=owner_user.id, name="A", depth=0)
            root_b = FileFolder(owner_user_id=owner_user.id, name="B", depth=0)
            db.add_all([root_a, root_b])
            await db.flush()
            fa = FileObject(
                owner_user_id=owner_user.id, folder_id=root_a.id,
                original_filename="方案.md", filename="x1", storage_key="k1",
            )
            fb = FileObject(
                owner_user_id=owner_user.id, folder_id=root_b.id,
                original_filename="方案.md", filename="x2", storage_key="k2",
            )
            db.add_all([fa, fb])
            await db.flush()

            hits = await repo.search_by_folder_ids([root_a.id], "方案")
            assert [f.id for f in hits] == [fa.id]

            exact = await repo.get_by_folder_ids([root_a.id], "方案.md")
            assert exact is not None and exact.id == fa.id
            outside = await repo.get_by_folder_ids([root_a.id], "别的.md")
            assert outside is None

    @pytest.mark.anyio
    async def test_search_excludes_files_without_folder(self, test_db, owner_user):
        from app.models.file import FileObject
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            db.add(FileObject(
                owner_user_id=owner_user.id, folder_id=None,
                original_filename="无项目.md", filename="x3", storage_key="k3",
            ))
            await db.flush()
            hits = await repo.search_by_folder_ids([uuid.uuid4()], "无项目")
            assert hits == []
```

（FileObject 必填字段核实——读 app/models/file.py 的 FileObject 定义，测试构造补齐 required 字段如 size/media_type 等；is_deleted 默认 False 则不需传。）

- [ ] **Step 6: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_repository_project.py -q --no-header`
Expected: FAIL（AttributeError: get_folder_subtree_ids 不存在）

- [ ] **Step 7: 实现 repo 方法**

`backend/app/repositories/file_repository.py`（在 search_by_folder_and_filename 附近加）：

```python
    async def get_folder_subtree_ids(self, folder_id: uuid.UUID) -> list[uuid.UUID]:
        ids: list[uuid.UUID] = [folder_id]
        frontier = [folder_id]
        while frontier:
            result = await self.session.execute(
                select(FileFolder.id).where(
                    FileFolder.parent_folder_id.in_(frontier),
                    FileFolder.is_deleted == False,
                )
            )
            frontier = list(result.scalars().all())
            ids.extend(frontier)
        return ids
```

```python
    async def search_by_folder_ids(
        self, folder_ids: list[uuid.UUID], keyword: str
    ) -> list[FileObject]:
        if not folder_ids:
            return []
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.folder_id.in_(folder_ids),
                FileObject.original_filename.ilike(f"%{keyword}%"),
                FileObject.is_deleted == False,
            )
        )
        return list(result.scalars().all())

    async def get_by_folder_ids(
        self, folder_ids: list[uuid.UUID], filename: str
    ) -> FileObject | None:
        if not folder_ids:
            return None
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.folder_id.in_(folder_ids),
                FileObject.original_filename == filename,
                FileObject.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()
```

（`select`/`FileFolder`/`FileObject` 已在文件顶部 import——核实。）

- [ ] **Step 8: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_repository_project.py -q --no-header`
Expected: 5 通过
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_file_repository.py -q --no-header`（若存在；无则跳过）

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/agent.py backend/alembic/versions/<hex>_add_session_run_project_folder.py backend/app/repositories/file_repository.py backend/tests/test_file_repository_project.py
git commit -m "feat: session/run project_folder_id and folder-scoped repo search"
```

---

### Task 2: tool_executor 项目范围隔离

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Modify: `backend/app/services/agent/loop.py:1257`（execute 调用传 project_folder_id）
- Test: `backend/tests/test_tool_executor_project.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `get_folder_subtree_ids` / `search_by_folder_ids` / `get_by_folder_ids`
- Produces:
  - `ToolExecutor.execute(action, web_enabled=True, owner_user_id=None, is_super_admin=False, goal=None, project_folder_id=None)`
  - 文件工具（read_file/list_files/write_file/edit_file）在 project_folder_id 非 None 时范围=项目子树；project 外显式路径 → 拒绝观察（见下）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_tool_executor_project.py`（fixtures 照现有 test_tool_executor 测试——核实 fixture（test_db/owner_user/make_file 等）并从现有测试文件复制构造方式；工具返回值结构照 `_read_file` 现有测试断言——读 tests/test_tool_executor*.py）：

```python
import uuid

import pytest


class TestProjectScopedFileTools:
    @pytest.mark.anyio
    async def test_read_file_scoped_to_project(
        self, test_db, owner_user, make_file, make_folder
    ):
        from app.services.agent.tool_executor import ToolExecutor

        # make_folder(name, parent=None) / make_file(folder, filename) —— 按现有测试 fixture 实际签名调整
        folder_a = await make_folder("项目A")
        folder_b = await make_folder("项目B")
        fa = await make_file(folder_a, "方案.md", content="A 项目内容")
        await make_file(folder_b, "方案.md", content="B 项目内容")

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"file_path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        assert "A 项目内容" in result.get("content", "")

    @pytest.mark.anyio
    async def test_read_file_other_project_file_not_found(
        self, test_db, owner_user, make_file, make_folder
    ):
        from app.services.agent.tool_executor import ToolExecutor

        folder_a = await make_folder("项目A")
        folder_b = await make_folder("项目B")
        await make_file(folder_b, "方案.md", content="B 项目内容")

        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"file_path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=folder_a.id,
        )
        # 项目 A 内无此文件 → 找不到（不返回 B 的内容）
        assert "error" in result or "未找到" in str(result)

    @pytest.mark.anyio
    async def test_write_file_defaults_to_project_root(
        self, test_db, owner_user, make_folder, repo
    ):
        from app.services.agent.tool_executor import ToolExecutor

        folder_a = await make_folder("项目A")
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "write_file", "input": {"file_path": "新建方案.md", "content": "正文"}},
            owner_user_id=owner_user.id,
            goal="生成方案",
            project_folder_id=folder_a.id,
        )
        assert "error" not in result, result
        # 验证文件落在项目 A 根
        files = await repo.search_by_folder_and_filename(folder_a.id, "新建方案")
        assert len(files) == 1

    @pytest.mark.anyio
    async def test_write_file_to_folder_outside_project_rejected(
        self, test_db, owner_user, make_folder
    ):
        from app.services.agent.tool_executor import ToolExecutor

        folder_a = await make_folder("项目A")
        folder_b = await make_folder("项目B")
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "write_file", "input": {"file_path": "项目B/xx.md", "content": "正文"}},
            owner_user_id=owner_user.id,
            goal="生成方案",
            project_folder_id=folder_a.id,
        )
        assert "error" in result

    @pytest.mark.anyio
    async def test_unbound_project_keeps_global_behavior(
        self, test_db, owner_user, make_file, make_folder
    ):
        from app.services.agent.tool_executor import ToolExecutor

        folder_b = await make_folder("项目B")
        await make_file(folder_b, "方案.md", content="B 内容")
        executor = ToolExecutor()
        result = await executor.execute(
            {"type": "read_file", "input": {"file_path": "方案.md"}},
            owner_user_id=owner_user.id,
            project_folder_id=None,
        )
        assert "error" not in result, result
```

（fixture 名/构造方式以现有测试为准——读 `backend/tests/` 下 tool_executor 相关测试文件，把 make_folder/make_file/repo fixture 换成实际存在的；若没有现成 fixture，按现有测试的 test_db + 直接 ORM 构造。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_tool_executor_project.py -q --no-header`
Expected: FAIL（TypeError: execute() got an unexpected keyword argument 'project_folder_id'）

- [ ] **Step 3: 实现 execute 参数与文件工具隔离**

`backend/app/services/agent/tool_executor.py`：

1. `execute` 签名加 `project_folder_id: uuid.UUID | None = None`；调用处（read_file/list_files/write_file/edit_file）把该参数透传进各 `_*_file` 方法：

```python
        if action_type == "read_file":
            return await self._read_file(payload, owner_user_id, is_super_admin, project_folder_id=project_folder_id)
        if action_type == "list_files":
            return await self._list_files(payload, owner_user_id, is_super_admin, project_folder_id=project_folder_id)
        if action_type == "write_file":
            return await self._write_file(payload, owner_user_id, goal, project_folder_id=project_folder_id)
        if action_type == "edit_file":
            return await self._edit_file(payload, owner_user_id, project_folder_id=project_folder_id)
```

2. 各方法签名加 `project_folder_id: uuid.UUID | None = None`。

3. 新增辅助方法（放 execute 之前）：

```python
    async def _project_context(self, owner_user_id: uuid.UUID, project_folder_id: uuid.UUID | None) -> tuple[list[uuid.UUID] | None, str | None]:
        """返回 (subtree_ids | None, project_name | None)。未绑定返回 (None, None)。"""
        if project_folder_id is None:
            return None, None
        from app.db.session import async_session_factory
        from app.models.file import FileFolder
        from sqlalchemy import select
        from app.repositories.file_repository import FileRepository

        async with async_session_factory() as db:
            repo = FileRepository(db)
            root = await db.get(FileFolder, project_folder_id)
            if root is None or root.is_deleted or root.owner_user_id != owner_user_id:
                return [], None
            subtree = await repo.get_folder_subtree_ids(project_folder_id)
            return subtree, root.name
```

（注意：tool_executor 各文件方法内部如何拿 session/repo——**核实**现有 `_read_file` 是否自建 session（读其开头 10 行）——若各方法已自建 session+repo，则在方法内用同样模式调用子树查询；若方法接收 repo 参数，则改签名。**按现有代码模式实现**，`_project_context` 只做示意。）

4. **read_file** 范围收窄（在现有文件名解析逻辑处——读 `_read_file` 现有实现后插入）：

```python
        subtree_ids, project_name = await self._project_context(owner_user_id, project_folder_id)
        if subtree_ids is not None:
            # 项目内检索：路径含 / → 先限定子树内找文件夹（新增 repo 方法或现有 find_folder_by_name 加子树过滤）
            # 无 / → get_by_folder_ids(subtree_ids, filename) 精确 → 无则 search_by_folder_ids 模糊
            # 找不到 → 返回观察错误：f"未找到文件，当前会话项目「{project_name}」内没有匹配文件"
```

（在 FileRepository 加 `find_folder_in_subtree(subtree_ids, name)` 方法——T1 未含，**本任务内补加**到 file_repository.py 并加 1 个测试：folder.id IN subtree_ids AND name ILIKE；或复用现有 find_folder_by_name 后校验结果是否在 subtree 内——**推荐后者**：`folder = await repo.find_folder_by_name(owner_user_id, name); if folder and folder.id in subtree_ids:`）

5. **list_files**：现有检索逻辑（keyword 全局 search_by_owner_and_filename / 文件夹 search_by_folder_and_filename）在 project_folder_id 非 None 时：全局检索改 `search_by_folder_ids(subtree_ids, keyword)`；文件夹分支校验 folder.id in subtree_ids，不在则空结果。

6. **write_file**：目标文件夹解析（现有 `find_folder_by_name` 或默认 None=根）——project 绑定且未指定文件夹 → `folder_id=project_folder_id`（项目根）；指定文件夹 → 校验在 subtree_ids 内，不在 → 返回观察错误 `{"error": "目标文件夹不属于当前项目"}`（观察错误格式照现有 error 返回模式）。

7. **edit_file**：定位逻辑同 read_file 收窄。

- [ ] **Step 4: loop.py 传参**

`backend/app/services/agent/loop.py:1257`：

```python
            observation = await asyncio.wait_for(
                self.tool_executor.execute(action, web_enabled=web_enabled,
                                           owner_user_id=owner_user_id,
                                           is_super_admin=is_super_admin,
                                           goal=ctx.run.goal,
                                           project_folder_id=ctx.run.project_folder_id),
                timeout=settings.step_timeout_seconds,
            )
```

- [ ] **Step 5: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_tool_executor_project.py -q --no-header`
Expected: 5 通过
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_tool_executor.py tests/test_agent_loop.py -q --no-header`（既有工具/循环测试不受影响——未绑定路径不变）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/app/services/agent/loop.py backend/tests/test_tool_executor_project.py
git commit -m "feat: scope agent file tools to session project subtree"
```

---

### Task 3: 会话 API（创建可选项目 + 切换端点 + run 快照）

**Files:**
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/schemas/agent.py`（或 schema 所在处——核实 AgentSessionCreate/AgentSessionResponse 定义文件）
- Test: `backend/tests/test_agent_session_project.py`（新建）

**Interfaces:**
- Consumes: Task 1 的模型字段
- Produces:
  - `POST /api/agent/sessions` body 加可选 `project_folder_id: uuid | None`
  - `PUT /api/agent/sessions/{session_id}/project` `{project_folder_id: uuid | None}` → `{project_folder_id, project_name}`
  - session 列表/详情响应加 `project_folder_id` 字段
  - create_run/retry 填 run.project_folder_id = session.project_folder_id

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_session_project.py`（fixtures 照 test_agent_api.py 现有——ordinary_client/ordinary_user/csrf_headers/admin 等；文件夹构造用 file_repository 或直接 ORM）：

```python
import uuid

import pytest


class TestSessionProject:
    @pytest.mark.anyio
    async def test_create_session_with_project(self, test_db, ordinary_client, ordinary_user, csrf_headers):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            db.add(folder)
            await db.commit()
            folder_id = folder.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(folder_id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["project_folder_id"] == str(folder_id)

    @pytest.mark.anyio
    async def test_create_session_rejects_non_top_level_folder(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            root = FileFolder(owner_user_id=ordinary_user.id, name="根", depth=0)
            db.add(root)
            await db.flush()
            child = FileFolder(owner_user_id=ordinary_user.id, name="子", depth=1, parent_folder_id=root.id)
            db.add(child)
            await db.commit()
            child_id = child.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(child_id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_create_session_rejects_others_folder(
        self, test_db, ordinary_client, ordinary_user, admin_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=admin_user.id, name="别人的", depth=0)
            db.add(folder)
            await db.commit()
            folder_id = folder.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(folder_id)},
            headers=csrf_headers,
        )
        assert resp.status_code in (400, 403)

    @pytest.mark.anyio
    async def test_switch_project_and_unbind(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            a = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            b = FileFolder(owner_user_id=ordinary_user.id, name="项目B", depth=0)
            db.add_all([a, b])
            await db.commit()
            a_id, b_id = a.id, b.id

        resp = await ordinary_client.post(
            "/api/agent/sessions", json={"title": "测试"}, headers=csrf_headers
        )
        session_id = resp.json()["data"]["id"]

        switch = await ordinary_client.put(
            f"/api/agent/sessions/{session_id}/project",
            json={"project_folder_id": str(a_id)},
            headers=csrf_headers,
        )
        assert switch.status_code == 200, switch.text
        assert switch.json()["data"]["project_folder_id"] == str(a_id)
        assert switch.json()["data"]["project_name"] == "项目A"

        unbind = await ordinary_client.put(
            f"/api/agent/sessions/{session_id}/project",
            json={"project_folder_id": None},
            headers=csrf_headers,
        )
        assert unbind.status_code == 200
        assert unbind.json()["data"]["project_folder_id"] is None

    @pytest.mark.anyio
    async def test_run_creation_snapshots_project(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            a = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            db.add(a)
            await db.commit()
            a_id = a.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(a_id)},
            headers=csrf_headers,
        )
        session_id = resp.json()["data"]["id"]

        run_resp = await ordinary_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "写方案", "network_enabled": True},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 201, run_resp.text
        from app.models.agent import AgentRun
        async with test_db() as db:
            run = await db.get(AgentRun, uuid.UUID(run_resp.json()["data"]["id"]))
            assert str(run.project_folder_id) == str(a_id)
```

（run 创建响应结构与 test_agent_api 现有 run 测试一致——核实 `data.id` 路径；session 创建响应结构同样核实。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_session_project.py -q --no-header`
Expected: FAIL（schema 无 project_folder_id）

- [ ] **Step 3: 实现 schema + 端点**

schema（AgentSessionCreate/AgentSessionResponse 所在文件——核实 app/schemas/agent.py 或 api/agent.py 内联）：

```python
class AgentSessionCreate(BaseModel):
    title: str | None = None
    project_folder_id: uuid.UUID | None = None
```

AgentSessionResponse 加字段：`project_folder_id: uuid.UUID | None = None`（若有 project_name 则加 `project_name: str = ""`）。

`backend/app/api/agent.py`：

1. 创建会话处（~:105）：校验+存字段：

```python
    project_folder_id = None
    if data.project_folder_id is not None:
        folder = await db.get(FileFolder, data.project_folder_id)
        if (
            folder is None or folder.is_deleted
            or folder.owner_user_id != current_user.id
            or folder.parent_folder_id is not None
        ):
            raise ApiError(status_code=400, code="INVALID_PROJECT", message="项目无效：必须是自己的顶层文件夹")
        project_folder_id = data.project_folder_id
```

（FileFolder import 核实；db.get 需要 async session——确认 create_session 已有 db 依赖。）

2. 新增端点：

```python
class SessionProjectUpdate(BaseModel):
    project_folder_id: uuid.UUID | None = None


@router.put("/sessions/{session_id}/project")
async def update_session_project(
    session_id: uuid.UUID,
    data: SessionProjectUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    session_obj = await repo.get_owned_session(current_user.id, session_id)  # 按现有 get_owned 模式
    if session_obj is None:
        raise ApiError(status_code=404, code="SESSION_NOT_FOUND", message="会话不存在")
    project_folder_id = None
    project_name = ""
    if data.project_folder_id is not None:
        folder = await db.get(FileFolder, data.project_folder_id)
        if (
            folder is None or folder.is_deleted
            or folder.owner_user_id != current_user.id
            or folder.parent_folder_id is not None
        ):
            raise ApiError(status_code=400, code="INVALID_PROJECT", message="项目无效：必须是自己的顶层文件夹")
        project_folder_id = data.project_folder_id
        project_name = folder.name
    session_obj.project_folder_id = project_folder_id
    await db.commit()
    return success(request, {"project_folder_id": project_folder_id, "project_name": project_name})
```

（get_owned_session/require_csrf/success 的 import 与现有端点一致——照 create_session/rename_session 的模式。）

3. run 快照：create_run（:228）与 retry（:475）的 AgentRun(...) 构造处加：

```python
            project_folder_id=session_obj.project_folder_id,
```

（session 查询变量名按实际；retry 里从原 run 的 session 取——**核实** retry 怎么拿 session：若 retry 用 run.session_id 查 session 则同样取；若直接复用 run 则用 `run.project_folder_id or session.project_folder_id`——**以 run 归属的 session 当前值快照**。）

- [ ] **Step 4: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_session_project.py -q --no-header`
Expected: 5 通过
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_api.py tests/test_generations_api.py -q --no-header`（session 响应加字段不破坏既有断言——若既有测试断言响应精确相等则需同步）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent.py backend/app/schemas/<实际文件> backend/tests/test_agent_session_project.py
git commit -m "feat: session project binding API with run snapshot"
```

---

### Task 4: 前端（会话页项目选择器 + 新建会话下拉）

**Files:**
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/lib/agent-api.ts`（或 api.ts——核实 agent 会话 API 所在文件：createSession/renameSession 等）
- Modify: `frontend/src/components/agent/session-sidebar-list.tsx`（新建会话入口——核实新建入口实际位置：可能有 create-session 弹窗组件或 sidebar 内按钮）
- Test: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx` 扩展 + sidebar 测试

**Interfaces:**
- Consumes: Task 3 契约（创建带 project_folder_id、PUT project、响应含 project_folder_id）
- Produces: 无

- [ ] **Step 1: agent-api 加函数**

（agent-api.ts 现有 createSession 等——核实签名与 api 封装模式）：

```ts
export function updateSessionProject(sessionId: string, projectFolderId: string | null) {
  return api<{ project_folder_id: string | null; project_name: string }>(
    `/api/agent/sessions/${sessionId}/project`,
    { method: "PUT", body: JSON.stringify({ project_folder_id: projectFolderId }), csrf: true }
  );
}
```

createSession 调用处（侧边栏）加可选参数 `project_folder_id?: string | null`——核实现有函数签名并扩展。

- [ ] **Step 2: 会话页顶部项目选择器**

`[sessionId]/page.tsx`：
1. state：`const [projectOptions, setProjectOptions] = useState<{ value: string; label: string }[]>([]);` `const [projectFolderId, setProjectFolderId] = useState<string | null>(null);` `const [projectName, setProjectName] = useState("");`
2. session 加载后同步 `projectFolderId = session.project_folder_id ?? null`
3. 加载顶层文件夹（session 就绪后一次）：

```tsx
api<FolderNode[]>("/api/files/folders")
  .then((nodes) => {
    setProjectOptions(
      (nodes ?? []).map((n) => ({ value: n.id, label: n.name }))
    );
  })
  .catch(() => {});
```

（`FolderNode` 结构核实：`@/types/file` 的 FolderNode 字段 id/name——顶层文件夹 = 数组本身（该接口返回该用户文件夹树，根级即顶层）——**核实**接口语义：`/api/files/folders` 返回用户顶层文件夹列表还是整树；整树则取 `parent_folder_id == null` 的节点。）
4. 标题区渲染（session 加载完成 && !loading 时）：

```tsx
<Select
  allowClear
  placeholder="未绑定项目"
  style={{ width: 180 }}
  value={projectFolderId ?? undefined}
  options={projectOptions}
  onChange={(v) => void handleProjectChange(v ?? null)}
  popupMatchSelectWidth={false}
/>
```

5. 切换处理：

```tsx
async function handleProjectChange(v: string | null) {
  try {
    const res = await updateSessionProject(sessionId, v);
    setProjectFolderId(res.project_folder_id);
    setProjectName(res.project_name);
    if (res.project_folder_id) {
      message.success(`已切换到项目「${res.project_name}」，文件操作仅限该项目`);
    } else {
      message.info("已解除项目绑定，文件操作为全局范围");
    }
  } catch (err) {
    message.error(err instanceof Error ? err.message : "切换项目失败");
  }
}
```

- [ ] **Step 3: 新建会话入口加项目下拉**

核实新建会话 UI（session-sidebar-list.tsx 的创建按钮或独立组件）：弹窗加 Select（复用同一文件夹列表），提交时带 `project_folder_id`；不选 = null。若新建入口是直接创建（无弹窗），则保持现状（默认不绑定，进入会话页后再选）——**按实际 UI 结构决定**，若加弹窗成本高则跳过本步并在测试中注明（会话内切换已满足需求）。

- [ ] **Step 4: 测试**

`[sessionId]/page.test.tsx` 扩展（mock updateSessionProject 与文件夹接口）：
- 渲染项目选择器（未绑定显示 placeholder）
- 切换成功 → message + 状态更新
- 切换失败 → error message

sidebar 测试：若 Step 3 实现弹窗，加创建带项目用例；否则跳过。

- [ ] **Step 5: 前端验证**

Run: `npx tsc --noEmit`（workdir frontend）——本任务文件零新增错误
Run: `npx vitest run "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"`——通过

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/agent-api.ts frontend/src/app/"(agent)"/agent/sessions/"[sessionId]"/page.tsx frontend/src/components/agent/session-sidebar-list.tsx frontend/src/app/"(agent)"/agent/sessions/"[sessionId]"/page.test.tsx
git commit -m "feat: session project selector and switch UI"
```

---

### Task 5: prompt 注入项目提示 + E2E 回归

**Files:**
- Modify: `backend/app/services/agent/loop.py`（messages 组装处——`_build_planner_messages` 内 merged_system 构建处 ~:1564）
- Modify: `backend/app/services/agent/tool_executor.py`（工具描述注入——若存在 get_instruction/工具说明模板）

**Interfaces:**
- Consumes: Task 2 的隔离、Task 3 的 run 快照
- Produces: 无

- [ ] **Step 1: 项目名注入 system prompt**

loop.py `_build_planner_messages`（~:1545-1570）在 `merged_system` 组装处加（需从 DB 取项目名——**实现方式**：`_do_process_attempt` 或 ctx 创建时把 `ctx.run.project_folder_id` 对应的文件夹名查出来存 ctx（`ctx.project_name`——核实 _AttemptContext 是否可加字段，或经 `_wf` 机制）；**推荐**：在 `_do_process_attempt` 内 attempt 上下文创建后、步骤循环前查一次）：

```python
        project_hint = ""
        project_folder_id = getattr(ctx.run, "project_folder_id", None)
        if project_folder_id is not None:
            project_hint = f"\n\n当前会话绑定项目「{ctx.project_name}」：文件操作（读/写/改/列）仅限该项目内，不得访问其他项目的文件。"
        merged_system = merged_system + project_hint
```

（ctx.project_name 的获取：`_do_process_attempt` 内 `async with async_session_factory() as db: folder = await db.get(FileFolder, ctx.run.project_folder_id); ctx.project_name = folder.name if folder else ""`——_AttemptContext 是 dataclass，加字段 `project_name: str = ""`（T2 已动过 loop——注意本任务在 T2 之后执行）。）

- [ ] **Step 2: 验证编译与单测**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import ast; ast.parse(open(r'C:\01_agent_loop_pro\backend\app\services\agent\loop.py', encoding='utf-8').read()); print('OK')"`
Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_loop.py -q --no-header`——回归通过

- [ ] **Step 3: 全量回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_project"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全过或仅已知失败（pypdf 4 个 + 并行会话既有）

- [ ] **Step 4: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: project isolation E2E calibration"
```
（仅当有修复；否则跳过）

- [ ] **Step 5: 用户实测清单**

1. 文件页建两个顶层文件夹「项目A」「项目B」，各放一个同名"方案.md"（内容不同）
2. 新建会话 → 顶部选择「项目A」→ 发消息"读方案.md" → Agent 读到 A 的内容
3. 顶部切到「项目B」→ 再问 → Agent 读 B 的内容（切换即授权）
4. 发消息"写一个方案.md" → 文件落在当前项目根
5. 新建会话不绑定 → 全局行为不变（读得到同名文件）
