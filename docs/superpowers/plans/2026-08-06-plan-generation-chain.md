# 方案生成链路（文件夹即项目 + 飞书同步 + 生成记录） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 方案生成后自动记录审计链路（生成记录，挂文件夹）并在用户开启开关时自动同步为飞书文档（用户 OAuth token），飞书同步开关在"连接飞书"区域。

**Architecture:** 项目 = 文件库文件夹（无新项目表）。用户级开关 `users.sync_feishu_enabled`（连接飞书区域 Switch）。新表 `generation_logs`（append-only，folder_id 可空——产物在根目录时 NULL）。run 完成后前端调 `POST /api/generations {session_id, run_id}` → 后端校验归属/完成 → 提取输入（`run.goal`）→ 从 run 事件识别 write_file 成功产物（step_completed 事件 observation.file_id）→ INSERT 记录 → 开关开则 `FeishuService.create_document(user_id, title, markdown)`（已实现：创建+写入+url，用户空间根目录）→ 失败不阻塞（status=succeeded + error 记录）。文件页"生成记录"入口查看。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, React + AntD

**Spec:** `docs/superpowers/specs/2026-08-06-plan-generation-chain-design.md` (v2, ead4f97)

## Global Constraints

- 新表/新列（手写迁移，写前 `alembic heads` 核实 revision 链）：`users.sync_feishu_enabled`（bool default false）、`generation_logs`（字段见 T1）
- append-only：generation_logs 无删除/更新端点；status 仅 pending→succeeded/failed 一次
- 飞书同步用 `FeishuService.create_document(owner_user_id, title, markdown)`（app/services/feishu/service.py:124——已实现，禁止改动）+ `get_access_token`；凭据不落日志
- 识别方案文件：run 事件里最后一个 `step_completed` 且 payload.action_type=="write_file" 且 observation 含 file_id 且无 error
- 输入文本：`run.goal`（用户需求原文）
- run 必须 status=="succeeded" 才记录（否则 400 run_not_completed）
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`；前端 `npx tsc --noEmit` + `npx vitest run`（workdir `C:\01_agent_loop_pro\frontend`）
- **git 纪律**：仓库有并行会话改动——只 `git add` 本任务精确路径，禁 `git add -A`；提交前 `git status --short`
- 迁移测试：若 `alembic upgrade head` 遇共享库他人已应用（表已存在）→ `alembic stamp <revision>` 并注明
- 后端测试可能被并行会话中间态阻塞（conftest ImportError）——等待其提交或报告 BLOCKED

---

### Task 1: 模型 + 迁移（users 列 + generation_logs 表）

**Files:**
- Create: `backend/app/models/generation_log.py`
- Create: `backend/alembic/versions/d1e2f3a4b5c6_add_generation_logs_and_sync_flag.py`
- Modify: `backend/app/models/user.py`（如有——核实 users 模型文件位置，`app/models/rbac.py` 含 User；在 User 类加列 `sync_feishu_enabled`）

**Interfaces:**
- Consumes: `app/models/base.py` 的 `Base`；`User`（rbac.py）
- Produces:
  - `GenerationLog` ORM（字段：id/folder_id(NULL FK file_folders)/user_id/session_id/run_id/input_text/final_md_file_id(NULL FK file_objects)/final_answer/feishu_doc_url/status/error/created_at/updated_at）
  - `User.sync_feishu_enabled: Mapped[bool] = mapped_column(Boolean, default=False)`
  - 迁移：ALTER users 加列 + 建 generation_logs 表（含 FK: folder_id→file_folders.id, user_id→users.id, session_id→agent_sessions.id, run_id→agent_runs.id, final_md_file_id→file_objects.id；索引 folder_id）

- [ ] **Step 1: 核实 alembic head 与 User 模型位置**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic heads`（workdir `C:\01_agent_loop_pro\backend`）
Expected: 单行 head revision id——把它作为本任务迁移文件的 `down_revision`。
确认 `User` 类在 `backend/app/models/rbac.py`（`Select-String "class User" backend/app/models/rbac.py`）；`FileFolder`/`FileObject` 表名 `file_folders`/`file_objects`（models/file.py）。

- [ ] **Step 2: 写模型文件**

`backend/app/models/generation_log.py`（仿 feishu_token.py 风格）：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationLog(Base):
    __tablename__ = "generation_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("file_folders.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_md_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("file_objects.id"), nullable=True
    )
    final_answer: Mapped[str] = mapped_column(Text, default="")
    feishu_doc_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
```

- [ ] **Step 3: User 加列**

`backend/app/models/rbac.py` 的 `User` 类加（在现有 Mapped 字段中，`sync_feishu_enabled: Mapped[bool] = mapped_column(Boolean, default=False)`，import Boolean 若未引入——核实文件头部 imports）。

- [ ] **Step 4: 写迁移文件**

`backend/alembic/versions/d1e2f3a4b5c6_add_generation_logs_and_sync_flag.py`（revision=`d1e2f3a4b5c6`，down_revision=Step 1 的 head）：

```python
"""add generation_logs and users.sync_feishu_enabled

Revision ID: d1e2f3a4b5c6
Revises: <STEP1_HEAD>
Create Date: 2026-08-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = '<STEP1_HEAD>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('sync_feishu_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_table('generation_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('folder_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('input_text', sa.Text(), nullable=False),
    sa.Column('final_md_file_id', sa.Uuid(), nullable=True),
    sa.Column('final_answer', sa.Text(), nullable=False),
    sa.Column('feishu_doc_url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['folder_id'], ['file_folders.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['agent_sessions.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ),
    sa.ForeignKeyConstraint(['final_md_file_id'], ['file_objects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generation_logs_folder_id'), 'generation_logs', ['folder_id'], unique=False)
    op.create_index(op.f('ix_generation_logs_user_id'), 'generation_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_generation_logs_run_id'), 'generation_logs', ['run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_generation_logs_run_id'), table_name='generation_logs')
    op.drop_index(op.f('ix_generation_logs_user_id'), table_name='generation_logs')
    op.drop_index(op.f('ix_generation_logs_folder_id'), table_name='generation_logs')
    op.drop_table('generation_logs')
    op.drop_column('users', 'sync_feishu_enabled')
```

- [ ] **Step 5: 应用迁移 + 验证导入**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head`（workdir `C:\01_agent_loop_pro\backend`）
Expected: `Running upgrade ... -> d1e2f3a4b5c6`（表已存在时用 `alembic stamp d1e2f3a4b5c6` 并注明）

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.models.generation_log import GenerationLog; from app.models.rbac import User; print(User.sync_feishu_enabled.type); print('OK')"`
Expected: `Boolean` 与 `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/generation_log.py backend/app/models/rbac.py backend/alembic/versions/d1e2f3a4b5c6_add_generation_logs_and_sync_flag.py
git commit -m "feat: generation_logs table and users.sync_feishu_enabled column"
```
Workdir `C:\01_agent_loop_pro`（先 `git status --short`）。

---

### Task 2: 生成记录 API + 飞书同步

**Files:**
- Create: `backend/app/api/generations.py`
- Modify: `backend/app/api/auth.py`（/me 响应加 sync_feishu_enabled + PUT /api/me/sync-feishu）
- Modify: `backend/app/schemas/auth.py`（CurrentUserResponse 加字段）
- Modify: `backend/app/main.py`（挂载 router——核实现有 router 注册方式）
- Test: `backend/tests/test_generations_api.py`

**Interfaces:**
- Consumes: `GenerationLog`/`User.sync_feishu_enabled`（T1）；`FeishuService.create_document/get_access_token`；`AgentRun`/`AgentRunEvent`/`AgentSession`（models/agent.py）；`FileObject`（models/file.py）；`get_current_user`/`require_super_admin`（core/dependencies.py）；`require_csrf`（core/csrf.py）；`success`（schemas/common.py）；`get_db`（db/session.py）
- Produces（前端 T3 依赖）：
  - `POST /api/generations` body `{session_id, run_id}` → 200 `{log: {...}}`；400 run_not_completed / run_not_owned；409 already_recorded（同 run 已记录）
  - `GET /api/generations?folder_id=&page=1&page_size=20` → `{logs: [...], total}`（folder_id 可选；不传=当前用户全部；传=该文件夹+根目录(NULL)不包含——**语义**：传 folder_id 精确匹配该文件夹；不传=全部）
  - `PUT /api/me/sync-feishu` body `{enabled: bool}`（csrf）→ `{sync_feishu_enabled: bool}`
  - `GET /api/auth/me` 响应增加 `sync_feishu_enabled: bool`
- GenerationLog 响应字段：id/folder_id/user_id/session_id/run_id/input_text/final_md_file_id/final_answer/feishu_doc_url/status/error/created_at（含 folder_name——列表展示用：LEFT JOIN file_folders.name；folder 已删时 ""）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_generations_api.py`（完整代码；fixtures：conftest 有 `test_db`（async session factory——用 `async with test_db() as db`）；`ordinary_client`/`ordinary_user` 若 conftest 无此 fixture 则照 test_feishu_config_api.py 模式在测试文件内定义；POST 需 `csrf_headers` fixture（GET /api/auth/csrf 拿 token + Origin header——照 test_feishu_config_api.py）；`admin_client` 同模式定义）：

```python
import uuid

import pytest

from app.models.agent import AgentRun, AgentSession
from app.models.rbac import User


async def _make_session(db, user_id, title="测试会话") -> AgentSession:
    session = AgentSession(owner_user_id=user_id, title=title)
    db.add(session)
    await db.flush()
    return session


async def _make_run(
    db,
    user_id,
    session: AgentSession,
    status="succeeded",
    goal="写一个杭州3日游方案",
) -> AgentRun:
    run = AgentRun(
        session_id=session.id,
        owner_user_id=user_id,
        goal=goal,
        status=status,
        max_steps=5,
        result={"final_answer": "这是最终方案", "answer_format": "markdown"},
    )
    db.add(run)
    await db.flush()
    return run


class TestGenerationsApi:
    @pytest.mark.anyio
    async def test_create_records_with_input_and_final_answer(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["input_text"] == "写一个杭州3日游方案"
        assert log["final_answer"] == "这是最终方案"
        assert log["final_md_file_id"] is None
        assert log["folder_id"] is None
        assert log["status"] == "succeeded"
        assert log["feishu_doc_url"] == ""

    @pytest.mark.anyio
    async def test_create_rejects_incomplete_run(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session, status="running")
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "RUN_NOT_COMPLETED"

    @pytest.mark.anyio
    async def test_create_rejects_other_users_run(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, admin_user.id)
            run = await _make_run(db, admin_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_create_duplicate_rejected(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        body = {"session_id": str(session.id), "run_id": str(run.id)}
        assert (await ordinary_client.post("/api/generations", json=body, headers=csrf_headers)).status_code == 200
        resp2 = await ordinary_client.post("/api/generations", json=body, headers=csrf_headers)
        assert resp2.status_code == 409

    @pytest.mark.anyio
    async def test_list_by_folder(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A")
            db.add(folder)
            await db.flush()
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            from app.models.generation_log import GenerationLog

            log = GenerationLog(
                folder_id=folder.id,
                user_id=ordinary_user.id,
                session_id=session.id,
                run_id=run.id,
                input_text=run.goal,
                status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(
            f"/api/generations?folder_id={folder.id}"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["logs"][0]["folder_name"] == "项目A"

    @pytest.mark.anyio
    async def test_list_requires_owner_folder(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=admin_user.id, name="别人项目")
            db.add(folder)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations?folder_id={folder.id}")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_sync_feishu_on_enabled(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.services.feishu.service import FeishuService

        fake_create = AsyncMock(return_value={"url": "https://feishu.cn/docx/fakedoc"})
        monkeypatch.setattr(FeishuService, "create_document", fake_create)
        async with test_db() as db:
            ordinary_user.sync_feishu_enabled = True
            await db.commit()
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        log = resp.json()["data"]["log"]
        assert log["feishu_doc_url"] == "https://feishu.cn/docx/fakedoc"
        assert log["status"] == "succeeded"
        fake_create.assert_awaited_once()

    @pytest.mark.anyio
    async def test_sync_skipped_when_disabled(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.services.feishu.service import FeishuService

        fake_create = AsyncMock()
        monkeypatch.setattr(FeishuService, "create_document", fake_create)
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["feishu_doc_url"] == ""
        fake_create.assert_not_awaited()

    @pytest.mark.anyio
    async def test_sync_failure_keeps_succeeded(
        self, test_db, ordinary_client, ordinary_user, csrf_headers, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.services.feishu.service import FeishuService

        async def boom(*args, **kwargs):
            raise RuntimeError("feishu api down")

        monkeypatch.setattr(FeishuService, "create_document", boom)
        async with test_db() as db:
            ordinary_user.sync_feishu_enabled = True
            await db.commit()
        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["status"] == "succeeded"
        assert "feishu api down" in log["error"]

    @pytest.mark.anyio
    async def test_plan_file_identified_from_events(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.agent import AgentRunEvent
        from app.models.file import FileFolder, FileObject

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A")
            db.add(folder)
            await db.flush()
            obj = FileObject(
                owner_user_id=ordinary_user.id,
                folder_id=folder.id,
                storage_key="var/files/placeholder",
                original_filename="方案.md",
            )
            db.add(obj)
            await db.flush()
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            ev = AgentRunEvent(
                run_id=run.id,
                event_type="step_completed",
                payload={
                    "action_type": "write_file",
                    "observation": {"file_id": str(obj.id), "filename": "方案.md"},
                },
            )
            db.add(ev)
            await db.commit()
        resp = await ordinary_client.post(
            "/api/generations",
            json={"session_id": str(session.id), "run_id": str(run.id)},
            headers=csrf_headers,
        )
        log = resp.json()["data"]["log"]
        assert log["final_md_file_id"] == str(obj.id)
        assert log["folder_id"] == str(folder.id)
        assert log["folder_name"] == "项目A"

    @pytest.mark.anyio
    async def test_me_sync_toggle(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        resp = await ordinary_client.put(
            "/api/me/sync-feishu", json={"enabled": True}, headers=csrf_headers
        )
        assert resp.status_code == 200, resp.text
        me = await ordinary_client.get("/api/auth/me")
        assert me.json()["data"]["sync_feishu_enabled"] is True
```

（`AgentRunEvent.seq` 是 DB 序列默认——INSERT 时不传 seq 由 DB 默认生成（`agent_run_events_seq` server default）；若模型要求显式 seq 则传任意递增值（如 1）。`FileObject` 其他必填列（如 `created_by`/`size_bytes`）如有 NOT NULL 无默认则补默认值——照 models/file.py 核对。fixtures 名与 conftest 实际不符时照 test_feishu_config_api.py 的本地定义模式调整并注明。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_generations_api.py -q --no-header`
Expected: FAIL（404/ModuleNotFoundError）

- [ ] **Step 3: 实现 generations.py**

`backend/app/api/generations.py`：

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentRun, AgentRunEvent, AgentSession
from app.models.file import FileFolder, FileObject
from app.models.generation_log import GenerationLog
from app.models.rbac import User
from app.schemas.common import success
from app.services.feishu.service import FeishuService

router = APIRouter(tags=["Generations"])


class GenerationCreateRequest(BaseModel):
    session_id: uuid.UUID
    run_id: uuid.UUID


def _log_view(log: GenerationLog, folder_name: str = "") -> dict:
    return {
        "id": str(log.id),
        "folder_id": str(log.folder_id) if log.folder_id else None,
        "folder_name": folder_name,
        "user_id": str(log.user_id),
        "session_id": str(log.session_id),
        "run_id": str(log.run_id),
        "input_text": log.input_text,
        "final_md_file_id": str(log.final_md_file_id) if log.final_md_file_id else None,
        "final_answer": log.final_answer,
        "feishu_doc_url": log.feishu_doc_url,
        "status": log.status,
        "error": log.error,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


async def _find_plan_file(db: AsyncSession, run_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    """Return (file_id, folder_id) of the last successful write_file in the run."""
    result = await db.execute(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.event_type == "step_completed",
        )
        .order_by(AgentRunEvent.seq.desc())
    )
    for event in result.scalars().all():
        payload = event.payload or {}
        if payload.get("action_type") != "write_file":
            continue
        obs = payload.get("observation") or {}
        if obs.get("file_id") and "error" not in obs:
            try:
                file_id = uuid.UUID(str(obs["file_id"]))
            except (ValueError, TypeError):
                continue
            obj = await db.get(FileObject, file_id)
            if obj is not None and not obj.is_deleted:
                return file_id, obj.folder_id
    return None, None


async def _sync_feishu(
    db: AsyncSession, user: User, log: GenerationLog, project_name: str
) -> str:
    """Create a feishu doc from the plan markdown. Returns (url, error)."""
    from datetime import UTC, datetime

    markdown = log.final_answer
    if log.final_md_file_id is not None:
        obj = await db.get(FileObject, log.final_md_file_id)
        if obj is not None and obj.storage_key:
            from pathlib import Path

            path = Path(obj.storage_key)
            try:
                markdown = path.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                pass
    title = f"{project_name or '方案'} - 方案 - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    try:
        result = await FeishuService().create_document(user.id, title, markdown)
        return result["url"], ""
    except ValueError as exc:
        msg = str(exc)
        if "feishu_not_connected" in msg:
            return "", "未连接飞书"
        return "", msg[:300]
    except Exception as exc:
        return "", str(exc)[:300]


@router.post("/generations")
async def create_generation(
    request: Request,
    data: GenerationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AgentRun, data.run_id)
    if run is None or str(run.owner_user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="RUN_NOT_OWNED", message="无权访问该运行")
    if run.status != "succeeded":
        raise ApiError(status_code=400, code="RUN_NOT_COMPLETED", message="运行尚未成功完成")
    session = await db.get(AgentSession, data.session_id)
    if session is None or str(session.owner_user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="SESSION_NOT_OWNED", message="无权访问该会话")
    existing = await db.scalar(
        select(GenerationLog).where(GenerationLog.run_id == data.run_id)
    )
    if existing is not None:
        raise ApiError(status_code=409, code="ALREADY_RECORDED", message="该运行已记录")

    file_id, folder_id = await _find_plan_file(db, data.run_id)
    folder_name = ""
    if folder_id is not None:
        folder = await db.get(FileFolder, folder_id)
        folder_name = folder.name if folder else ""

    log = GenerationLog(
        folder_id=folder_id,
        user_id=current_user.id,
        session_id=data.session_id,
        run_id=data.run_id,
        input_text=run.goal,
        final_md_file_id=file_id,
        final_answer=(run.result or {}).get("final_answer", "") or "",
        status="pending",
    )
    db.add(log)
    await db.flush()

    url, error = "", ""
    if current_user.sync_feishu_enabled:
        url, error = await _sync_feishu(db, current_user, log, folder_name)

    log.status = "succeeded"
    log.feishu_doc_url = url
    log.error = error
    await db.commit()
    return success(request, {"log": _log_view(log, folder_name)})


@router.get("/generations")
async def list_generations(
    request: Request,
    folder_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if folder_id is not None:
        folder = await db.get(FileFolder, folder_id)
        if folder is None or str(folder.owner_user_id) != str(current_user.id):
            raise ApiError(status_code=403, code="FOLDER_NOT_OWNED", message="无权访问该文件夹")
    stmt = select(GenerationLog).where(GenerationLog.user_id == current_user.id)
    if folder_id is not None:
        stmt = stmt.where(GenerationLog.folder_id == folder_id)
    total = (
        await db.execute(
            select(GenerationLog.id).where(
                GenerationLog.user_id == current_user.id,
                *([GenerationLog.folder_id == folder_id] if folder_id is not None else []),
            )
        )
    ).all()
    result = await db.execute(
        stmt.order_by(GenerationLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = list(result.scalars().all())
    folder_ids = {l.folder_id for l in logs if l.folder_id}
    names: dict[uuid.UUID, str] = {}
    if folder_ids:
        folders = await db.execute(select(FileFolder).where(FileFolder.id.in_(folder_ids)))
        names = {f.id: f.name for f in folders.scalars().all()}
    return success(
        request,
        {
            "logs": [_log_view(l, names.get(l.folder_id, "")) for l in logs],
            "total": len(total),
        },
    )
```

- [ ] **Step 4: auth 端点扩展**

`backend/app/schemas/auth.py` 的 `CurrentUserResponse` 加：`sync_feishu_enabled: bool = False`。

`backend/app/api/auth.py` 的 `/api/auth/me` 返回处补 `"sync_feishu_enabled": current_user.sync_feishu_enabled`（核实该端点返回构造方式——读文件；若用 `_user_to_response` 之类的统一转换则在该处加）。

新增端点（auth.py）：

```python
from pydantic import BaseModel


class SyncFeishuRequest(BaseModel):
    enabled: bool


@router.put("/me/sync-feishu")
async def update_sync_feishu(
    request: Request,
    data: SyncFeishuRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    current_user.sync_feishu_enabled = data.enabled
    await db.commit()
    return success(request, {"sync_feishu_enabled": data.enabled})
```

（`require_csrf`/`get_db`/`AsyncSession` 若未 import 补上——读 auth.py 现状。）

- [ ] **Step 5: 注册 router（main.py）**

`backend/app/main.py` 仿其他 router 注册（`include_router` + 前缀 `/api`）：

```python
from app.api.generations import router as generations_router
...
app.include_router(generations_router, prefix="/api")
```

- [ ] **Step 6: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_generations_api.py -q --no-header`
Expected: 全部通过（~10 个）
再跑相关回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_api.py tests/test_auth.py -q --no-header`（auth/me 改动回归——文件名为 test_auth.py 或类似，用 glob 核实 `tests/test_*auth*`）

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/generations.py backend/app/api/auth.py backend/app/schemas/auth.py backend/app/main.py backend/tests/test_generations_api.py
git commit -m "feat: generation audit logs API with feishu doc sync and user toggle"
```

---

### Task 3: 前端（开关 + 生成记录 + run 完成回调）

**Files:**
- Modify: `frontend/src/lib/api.ts`（3 个 API 函数 + 类型）
- Modify: `frontend/src/types/auth.ts`（CurrentUser 加 sync_feishu_enabled）
- Modify: `frontend/src/components/feishu/feishu-connect.tsx`（开关）
- Modify: `frontend/src/components/files/file-manager.tsx` 或对应文件页组件（生成记录入口/列表——先读文件页结构，选择挂载点：工具栏按钮 + Modal/抽屉）
- Modify: 会话页组件（run 完成回调）——读 `frontend/src/components/agent/` 下会话/stream 组件，找 run_succeeded 处理点（use-run-event-stream.ts 或 session-conversation-stream.tsx）
- Test: `frontend/src/components/feishu/feishu-connect.test.tsx`（开关测试）、文件页生成记录测试（如文件页已有测试文件则扩展）

**Interfaces:**
- Consumes: T2 契约（POST/GET /api/generations、PUT /api/me/sync-feishu、/api/auth/me 加字段）
- Produces: 无（最终交付）

- [ ] **Step 1: api.ts + types**

`frontend/src/types/auth.ts` 的 CurrentUser 加：`sync_feishu_enabled?: boolean`。

`frontend/src/lib/api.ts` 追加：

```ts
export interface GenerationLog {
  id: string;
  folder_id: string | null;
  folder_name: string;
  user_id: string;
  session_id: string;
  run_id: string;
  input_text: string;
  final_md_file_id: string | null;
  final_answer: string;
  feishu_doc_url: string;
  status: string;
  error: string;
  created_at: string;
}

export async function createGeneration(sessionId: string, runId: string) {
  return api<{ log: GenerationLog }>("/api/generations", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, run_id: runId }),
    csrf: true,
  });
}

export async function listGenerations(params: { folderId?: string | null; page?: number; pageSize?: number }) {
  const q = new URLSearchParams();
  if (params.folderId) q.set("folder_id", params.folderId);
  if (params.page) q.set("page", String(params.page));
  if (params.pageSize) q.set("page_size", String(params.pageSize));
  return api<{ logs: GenerationLog[]; total: number }>(`/api/generations?${q.toString()}`);
}

export async function updateSyncFeishu(enabled: boolean) {
  return api<{ sync_feishu_enabled: boolean }>("/api/me/sync-feishu", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
    csrf: true,
  });
}
```

- [ ] **Step 2: feishu-connect.tsx 加开关**

读现有组件（连接/断开/超管配置区）。在连接区下方（所有用户可见）加：

```tsx
const [syncEnabled, setSyncEnabled] = useState(false);

// 组件挂载时从 /api/auth/me 取（现有 fetchCurrentUser 返回 CurrentUser——含 sync_feishu_enabled）
// fetchCurrentUser().then((u) => { if (u) setSyncEnabled(!!u.sync_feishu_enabled); ... })

<div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
  <Switch
    checked={syncEnabled}
    onChange={async (v) => {
      try {
        await updateSyncFeishu(v);
        setSyncEnabled(v);
      } catch {
        message.error("设置失败，请重试");
      }
    }}
  />
  <span>方案生成后同步到飞书</span>
</div>
```

（`Switch` 从 antd import；`updateSyncFeishu` 从 api.ts import；位置：现有连接区附近——读文件决定，保证员工可见。）

- [ ] **Step 3: 文件页生成记录**

读 `frontend/src/components/files/` 与文件页（`(agent)/files` 路由）——确定列表组件（file-manager.tsx 或类似）与当前选中文件夹状态（selectedFolder）。添加：
1. 工具栏"生成记录"按钮（选中文件夹时传 folder_id；未选中=全部）
2. 点击打开 Modal/抽屉：记录列表（created_at 格式化、状态徽标 succeeded 绿/failed 红/pending 灰、输入摘要 60 字截断）分页（antd Pagination，每页 10）；每条 [详情]
3. 详情：Modal 内展示 input_text 全文（ScrollArea）、final_answer 预览（截断 2000 字）、飞书链接（feishu_doc_url 非空时 `<a target="_blank">打开飞书文档</a>`）、error（非空红色）、时间
4. 状态徽标：succeeded→绿色"成功"（若 feishu_doc_url 非空显示"已同步飞书"）、failed→红色"失败"、pending→灰色

- [ ] **Step 4: run 完成回调**

读会话页流式组件（`use-run-event-stream` hook 或 `session-conversation-stream.tsx`——找 run_succeeded / answer_completed 事件处理处）。在 run 成功完成处理处加（fire-and-forget，失败静默）：

```tsx
// run 完成（run_succeeded）时
if (runId && sessionId) {
  createGeneration(sessionId, runId).catch(() => {});
}
```

（从现有事件数据取 sessionId/runId——组件里已有；只对 status==="succeeded" 的 run 触发。）

- [ ] **Step 5: 前端验证**

Run: `npx tsc --noEmit`（workdir `C:\01_agent_loop_pro\frontend`）——本任务文件零新增错误（仓库有 pre-existing 并行错误）
Run: `npx vitest run src/components/feishu/ src/components/files/ src/components/agent/`——现有测试通过；feishu-connect.test.tsx 若因新开关变化需更新 mock（auth/me mock 加 sync_feishu_enabled）则同步更新并注明

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/types/auth.ts frontend/src/components/feishu/feishu-connect.tsx frontend/src/components/files/<实际文件> frontend/src/components/agent/<实际文件> frontend/src/components/feishu/feishu-connect.test.tsx
git commit -m "feat: feishu sync toggle, generation records in file page, auto-record on run complete"
```

---

### Task 4: E2E 验证与收尾

- [ ] **Step 1: 应用迁移 + 重启 API**

```powershell
& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head   # workdir C:\01_agent_loop_pro\backend
```
uvicorn 8000 `--reload` 自动加载；`GET http://127.0.0.1:8000/docs` 确认存活。

- [ ] **Step 2: 后端全量回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_genchain"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全过或仅已知失败（pypdf 4 个）；并行会话中间态阻塞时等待后重跑。

- [ ] **Step 3: 用户实测**

1. 对话页顶栏"连接飞书"区域出现"方案生成后同步到飞书"开关 → 打开
2. Agent 会话里让 AI 写一个方案 md（write_file 到某文件夹）→ run 成功
3. 文件页 → 该文件夹 → [生成记录] → 出现一条记录（输入/状态"成功 已同步飞书"/飞书链接）
4. 点飞书链接 → 打开飞书文档（内容与 md 一致、标题"文件夹名 - 方案 - 时间"）
5. 未连接飞书时（开关开）：记录状态"成功"+ error"未连接飞书"
6. 开关关：不调飞书，记录无链接

- [ ] **Step 4: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: generation chain E2E calibration"
```
（仅当有修复。）
