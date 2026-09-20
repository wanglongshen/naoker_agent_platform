# 知识库管理（库 → 文件 两级）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/knowledge` 从扁平文档列表升级为「库列表 → 库详情（数据集 / 搜索测试 / 配置）」两级知识库管理，支持多库、上传文件异步入库、从已采集素材导入、库维度检索过滤。

**Architecture:** 新增 `rag_libraries`、`rag_jobs` 两张表并给 `rag_documents` 加 `library_id`（迁移回填现有 192 篇到默认库「行业知识库」）；后端在既有 `RagRepository` + `/api/rag` 上扩展库/文档/任务/上传接口，入库逻辑从 `ingest.py` 抽成公共函数 `ingest_one`，新增 `rag_ingest_worker` 异步执行；前端新增 `/knowledge/[libraryId]` 动态路由与组件，复用 AntD + `DataSurface` + `rag-api` 客户端。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic + PostgreSQL；Next.js App Router + Ant Design + vitest；本地 `bge-small-zh-v1.5` embedding（既有）。

**Spec:** `docs/superpowers/specs/2026-09-17-knowledge-base-management-design.md` · 设计稿 `.superpowers/brainstorm/kb-manage-01/design.html`

## Global Constraints

- 知识库管理全部接口用 `require_super_admin`，**不新增权限码**；`POST /api/rag/search` 仍用 `get_current_user`（全部登录用户可用）。
- 所有写接口（POST / PATCH / DELETE）必须带 `Depends(require_csrf)`。
- 迁移 head 当前为 `80488b353bdd`（`add_task_chain_tables`），新迁移 `down_revision` 指向它。
- 上传限制：扩展名白名单 `pdf/docx/xlsx/pptx/txt/md/csv/html`；单文件 ≤20MB；同库 sha256 去重；落盘 `backend/var/rag/uploads/<library_id>/<uuid>.<ext>`（`var/` 已被 gitignore，提交时绝不 add）。
- 文档状态取值：`pending` / `processing` / `ready` / `failed` / `disabled`；库 `retrieval_enabled=false` 或文档非 `ready` 时**不参与检索**。
- 前端沿用现有色板与组件（`DataSurface` / `PageHeader` / `view-states` / AntD），不引入新 UI 库。
- 后端测试在 `backend/` 下跑：`X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/<file> -q`；前端在 `frontend/` 下跑：`npx vitest run <file>`。
- 每个任务提交前用 `git diff --cached --name-only` 核对暂存区，只 add 本任务文件。

## File Structure

**后端（新增）**

| 文件 | 职责 |
| --- | --- |
| `backend/alembic/versions/f3a1c7d9e2b4_add_rag_libraries.py` | 建 `rag_libraries` / `rag_jobs`、加 `rag_documents.library_id`/`error_message`、回填默认库 |
| `backend/app/services/rag/ingest.py`（改） | 抽出 `ingest_one()`，`ingest_manifest()` 改为调用它（支持 `library_id`） |
| `backend/app/workers/rag_ingest_worker.py` | 领取 `rag_jobs` → 解析/切分/向量化 → 更新进度与状态 |
| `backend/tests/test_rag_libraries_api.py` | 库 CRUD + 统计 |
| `backend/tests/test_rag_documents_api.py` | 文档分页/搜索/删除/切块预览/启用禁用 |
| `backend/tests/test_rag_upload_api.py` | 上传校验 + 入队 |
| `backend/tests/test_rag_jobs_api.py` | 任务进度与活跃任务 |
| `backend/tests/test_rag_ingest_worker.py` | worker 成功/失败/重试路径 |
| `backend/tests/test_rag_import_api.py` | 从已采集素材导入 |
| `backend/tests/test_rag_search_library_filter.py` | 库维度检索过滤 |

**后端（改）**

| 文件 | 改动 |
| --- | --- |
| `backend/app/models/rag.py` | 加 `RagLibrary`、`RagJob`，`RagDocument` 加 `library_id`/`error_message` |
| `backend/app/repositories/rag_repository.py` | 库/文档/任务仓储方法 + `list_documents(library_id=...)` |
| `backend/app/schemas/rag.py` | 库/任务 schema + 文档 schema 加字段 |
| `backend/app/api/rag.py` | 库 CRUD、文档列表/删除/切块、上传、导入、任务、检索过滤 |
| `backend/app/services/rag/search.py` | `search(..., library_id=..., include_disabled_libraries=...)` + 库加载与过滤 |

**前端（新增）**

| 文件 | 职责 |
| --- | --- |
| `frontend/src/app/(dashboard)/knowledge/[libraryId]/page.tsx` | 库详情页（tab=datasets/search/config） |
| `frontend/src/components/knowledge/library-grid.tsx` | 库卡片网格 + 新建入口 |
| `frontend/src/components/knowledge/library-card.tsx` | 单个库卡片 + `···` 菜单 |
| `frontend/src/components/knowledge/new-library-modal.tsx` | 新建/编辑库表单 |
| `frontend/src/components/knowledge/dataset-table.tsx` | 文档表格（分页/搜索/开关/批量/操作） |
| `frontend/src/components/knowledge/upload-modal.tsx` | 上传 + 进度轮询 |
| `frontend/src/components/knowledge/search-test-panel.tsx` | 库内搜索测试 |
| `frontend/src/components/knowledge/config-panel.tsx` | 配置页 |
| `frontend/src/components/knowledge/chunk-preview-drawer.tsx` | 切块预览抽屉 |
| `frontend/src/components/knowledge/library-detail-nav.tsx` | 库详情左侧子导航 |

**前端（改/删）**

| 文件 | 改动 |
| --- | --- |
| `frontend/src/app/(dashboard)/knowledge/page.tsx` | 改为渲染 `LibraryGrid` |
| `frontend/src/lib/rag-api.ts` | 加库/文档/任务/上传/检索库过滤 |
| `frontend/src/lib/copy.ts` | `navigation.knowledge` → `"知识库管理"` |
| `frontend/src/components/knowledge/document-list.tsx` + `.test.tsx` | 删除（被 `dataset-table` 取代） |
| `frontend/src/components/knowledge/document-preview-drawer.tsx` | 删除（被 `chunk-preview-drawer` 取代） |

---

### Task 1: 数据模型与迁移（rag_libraries / library_id / rag_jobs）

**Files:**
- Modify: `backend/app/models/rag.py`
- Create: `backend/alembic/versions/f3a1c7d9e2b4_add_rag_libraries.py`
- Test: `backend/tests/test_rag_models.py`

**Interfaces:**
- Produces: `RagLibrary(id, name, description, kind, visibility, retrieval_enabled, created_by, created_at, updated_at)`；`RagJob(id, library_id, doc_id, kind, status, total, processed, error_message, payload, created_by, created_at, started_at, finished_at)`；`RagDocument.library_id: uuid.UUID`（NOT NULL）、`RagDocument.error_message: str | None`；常量 `DEFAULT_LIBRARY_ID = uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000001")`（迁移与回填共用，测试断言用）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_models.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.rag import RagDocument, RagJob, RagLibrary


@pytest.mark.anyio
async def test_library_and_document_relation(test_db):
    async with test_db() as session:
        lib = RagLibrary(name="测试库", description="desc", kind="custom")
        session.add(lib)
        await session.commit()

        doc = RagDocument(
            title="文档A",
            sha256="m1",
            status="ready",
            library_id=lib.id,
        )
        session.add(doc)
        await session.commit()

        row = (await session.execute(select(RagDocument).where(RagDocument.id == doc.id))).scalar_one()
        assert row.library_id == lib.id
        assert row.error_message is None


@pytest.mark.anyio
async def test_job_defaults(test_db):
    async with test_db() as session:
        lib = RagLibrary(name="任务库")
        session.add(lib)
        await session.commit()

        job = RagJob(library_id=lib.id, kind="upload", status="queued", total=1)
        session.add(job)
        await session.commit()

        row = (await session.execute(select(RagJob).where(RagJob.id == job.id))).scalar_one()
        assert row.processed == 0
        assert row.started_at is None
        assert row.doc_id is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'RagLibrary'`

- [ ] **Step 3: 改模型**

在 `backend/app/models/rag.py` 顶部 import 区补 `Boolean`，并在 `RagDocument` 前插入两个模型、给 `RagDocument` 加两列：

```python
class RagLibrary(Base):
    __tablename__ = "rag_libraries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="custom")
    visibility: Mapped[str] = mapped_column(String(16), default="admins_only")
    retrieval_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("ix_rag_documents_status", "status"),
        Index("ix_rag_documents_library_id", "library_id"),
    )

    # …既有字段保持不变，新增两列：
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_libraries.id", ondelete="CASCADE"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`RagChunk` / `RagEvalSet` 之后追加：

```python
class RagJob(Base):
    __tablename__ = "rag_jobs"
    __table_args__ = (Index("ix_rag_jobs_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_libraries.id", ondelete="CASCADE"), nullable=False
    )
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="upload")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=1)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_models.py -q`
Expected: `2 passed`

- [ ] **Step 5: 写迁移**

`backend/alembic/versions/f3a1c7d9e2b4_add_rag_libraries.py`：

```python
"""add rag libraries and jobs

Revision ID: f3a1c7d9e2b4
Revises: 80488b353bdd
Create Date: 2026-09-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a1c7d9e2b4'
down_revision: Union[str, Sequence[str], None] = '80488b353bdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_LIBRARY_ID = '6f1d2c3a-1111-4a2b-9c3d-000000000001'


def upgrade() -> None:
    op.create_table('rag_libraries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('visibility', sa.String(length=16), nullable=False),
        sa.Column('retrieval_enabled', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column('rag_documents', sa.Column('library_id', sa.Uuid(), nullable=True))
    op.add_column('rag_documents', sa.Column('error_message', sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "INSERT INTO rag_libraries (id, name, description, kind, visibility, retrieval_enabled) "
            "VALUES (:id, :name, :description, 'industry', 'admins_only', true)"
        ).bindparams(
            id=DEFAULT_LIBRARY_ID,
            name='行业知识库',
            description='抖音电商官方方法论、投放手册与运营白皮书',
        )
    )
    op.execute(
        sa.text("UPDATE rag_documents SET library_id = :id WHERE library_id IS NULL").bindparams(
            id=DEFAULT_LIBRARY_ID
        )
    )

    op.alter_column('rag_documents', 'library_id', nullable=False)
    op.create_index('ix_rag_documents_library_id', 'rag_documents', ['library_id'])
    op.create_foreign_key(
        'fk_rag_documents_library_id', 'rag_documents', 'rag_libraries',
        ['library_id'], ['id'], ondelete='CASCADE',
    )

    op.create_table('rag_jobs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('library_id', sa.Uuid(), nullable=False),
        sa.Column('doc_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('processed', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['library_id'], ['rag_libraries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doc_id'], ['rag_documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_rag_jobs_status', 'rag_jobs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_rag_jobs_status', table_name='rag_jobs')
    op.drop_table('rag_jobs')
    op.drop_constraint('fk_rag_documents_library_id', 'rag_documents', type_='foreignkey')
    op.drop_index('ix_rag_documents_library_id', table_name='rag_documents')
    op.drop_column('rag_documents', 'error_message')
    op.drop_column('rag_documents', 'library_id')
    op.drop_table('rag_libraries')
```

- [ ] **Step 6: 在开发库跑迁移并验证回填**

Run（`backend/` 下）：
```
X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head
X:\python\anaconda\envs\01-rbac\python.exe -c "import asyncio, sqlalchemy as sa; from app.db.session import async_session_factory
async def main():
    async with async_session_factory() as s:
        print('nulls', (await s.execute(sa.text('select count(*) from rag_documents where library_id is null'))).scalar_one())
        print('libs', (await s.execute(sa.text('select name, retrieval_enabled from rag_libraries'))).all())
asyncio.run(main())"
```
Expected: `nulls 0` 与 `libs [('行业知识库', True)]`

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/rag.py backend/alembic/versions/f3a1c7d9e2b4_add_rag_libraries.py backend/tests/test_rag_models.py
git commit -m "feat(rag): add libraries/jobs tables and backfill documents"
```

---

### Task 2: RagRepository 扩展（库 / 文档过滤 / 任务）

**Files:**
- Modify: `backend/app/repositories/rag_repository.py`
- Test: `backend/tests/test_rag_repository.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的模型
- Produces（后续任务按此签名调用）：
  - `create_library(**fields) -> RagLibrary`、`get_library(id) -> RagLibrary | None`、`get_library_by_name(name) -> RagLibrary | None`、`list_libraries() -> list[RagLibrary]`、`update_library(id, **fields) -> RagLibrary | None`、`delete_library(id) -> bool`、`get_libraries_by_ids(ids) -> list[RagLibrary]`
  - `library_stats() -> dict[uuid.UUID, dict[str, Any]]`（键：`doc_count`/`chunk_count`/`ready_count`/`failed_count`/`last_updated_at`）
  - `list_documents(*, library_id=None, status=None, keyword=None, page=1, page_size=20) -> Page`
  - `delete_document(doc_id) -> bool`、`list_chunks_page(doc_id, *, page=1, page_size=20) -> tuple[list[RagChunk], int]`、`clear_chunks(doc_id) -> int`（删切块并把 `chunk_count` 归零，供重新入库/重试使用）
  - `create_job(**fields) -> RagJob`、`get_job(job_id) -> RagJob | None`、`claim_next_job() -> RagJob | None`、`update_job(job_id, **fields) -> RagJob | None`、`list_active_jobs(library_id=None) -> list[RagJob]`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_repository.py（追加）
@pytest.mark.anyio
async def test_library_crud_and_stats(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="统计库", description="d")
        assert await repo.get_library_by_name("统计库") is not None

        doc = await repo.create_document(
            title="A", sha256="rs1", status="ready", library_id=lib.id
        )
        await repo.add_chunks(doc.id, [("sec", "内容", b"\x00\x00\x80?", 4)])
        await repo.create_document(
            title="B", sha256="rs2", status="failed", library_id=lib.id
        )

        stats = await repo.library_stats()
        assert stats[lib.id]["doc_count"] == 2
        assert stats[lib.id]["ready_count"] == 1
        assert stats[lib.id]["failed_count"] == 1
        assert stats[lib.id]["chunk_count"] == 1

        assert await repo.clear_chunks(doc.id) == 1
        assert (await repo.get_document(doc.id)).chunk_count == 0

        page = await repo.list_documents(library_id=lib.id, page=1, page_size=10)
        assert page.total == 2

        assert await repo.delete_library(lib.id) is True
        assert await repo.get_library(lib.id) is None


@pytest.mark.anyio
async def test_job_claim_and_progress(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="任务库2")
        job = await repo.create_job(library_id=lib.id, kind="upload", status="queued", total=2)

        claimed = await repo.claim_next_job()
        assert claimed is not None and claimed.id == job.id
        assert claimed.status == "running" and claimed.started_at is not None

        await repo.update_job(job.id, processed=2, status="succeeded")
        updated = await repo.get_job(job.id)
        assert updated.processed == 2 and updated.status == "succeeded"
        assert await repo.list_active_jobs(library_id=lib.id) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_repository.py -q`
Expected: FAIL — `AttributeError: 'RagRepository' object has no attribute 'create_library'`

- [ ] **Step 3: 实现仓储方法**

在 `backend/app/repositories/rag_repository.py` 顶部 import 增加 `datetime, UTC`、`delete`、`update`、`RagJob, RagLibrary`；`list_documents` 签名加 `library_id` 过滤：

```python
    async def list_documents(
        self,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        library_id: uuid.UUID | None = None,
    ) -> Page:
        base = select(RagDocument)
        if library_id is not None:
            base = base.where(RagDocument.library_id == library_id)
        if status:
            base = base.where(RagDocument.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(
                or_(RagDocument.title.ilike(pattern), RagDocument.publisher.ilike(pattern))
            )
        # …其余保持不变
```

追加方法（完整）：

```python
    async def create_library(self, **fields: Any) -> RagLibrary:
        lib = RagLibrary(**fields)
        self.session.add(lib)
        await self.session.commit()
        return lib

    async def get_library(self, library_id: uuid.UUID) -> RagLibrary | None:
        return await self.session.get(RagLibrary, library_id)

    async def get_library_by_name(self, name: str) -> RagLibrary | None:
        result = await self.session.execute(
            select(RagLibrary).where(RagLibrary.name == name)
        )
        return result.scalar_one_or_none()

    async def list_libraries(self) -> list[RagLibrary]:
        result = await self.session.execute(select(RagLibrary).order_by(RagLibrary.created_at))
        return list(result.scalars().all())

    async def update_library(self, library_id: uuid.UUID, **fields: Any) -> RagLibrary | None:
        lib = await self.session.get(RagLibrary, library_id)
        if lib is None:
            return None
        for key, value in fields.items():
            setattr(lib, key, value)
        await self.session.commit()
        return lib

    async def delete_library(self, library_id: uuid.UUID) -> bool:
        lib = await self.session.get(RagLibrary, library_id)
        if lib is None:
            return False
        await self.session.delete(lib)
        await self.session.commit()
        return True

    async def get_libraries_by_ids(self, library_ids: list[uuid.UUID]) -> list[RagLibrary]:
        if not library_ids:
            return []
        result = await self.session.execute(
            select(RagLibrary).where(RagLibrary.id.in_(library_ids))
        )
        return list(result.scalars().all())

    async def library_stats(self) -> dict[uuid.UUID, dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(
                    RagDocument.library_id,
                    func.count(RagDocument.id),
                    func.coalesce(func.sum(RagDocument.chunk_count), 0),
                    func.count(RagDocument.id).filter(RagDocument.status == "ready"),
                    func.count(RagDocument.id).filter(RagDocument.status == "failed"),
                    func.max(RagDocument.updated_at),
                ).group_by(RagDocument.library_id)
            )
        ).all()
        return {
            row[0]: {
                "doc_count": int(row[1]),
                "chunk_count": int(row[2]),
                "ready_count": int(row[3]),
                "failed_count": int(row[4]),
                "last_updated_at": row[5],
            }
            for row in rows
        }

    async def delete_document(self, doc_id: uuid.UUID) -> bool:
        doc = await self.session.get(RagDocument, doc_id)
        if doc is None:
            return False
        await self.session.delete(doc)
        await self.session.commit()
        return True

    async def clear_chunks(self, doc_id: uuid.UUID) -> int:
        result = await self.session.execute(
            delete(RagChunk).where(RagChunk.doc_id == doc_id)
        )
        doc = await self.session.get(RagDocument, doc_id)
        if doc is not None:
            doc.chunk_count = 0
        await self.session.commit()
        return int(result.rowcount or 0)

    async def list_chunks_page(
        self, doc_id: uuid.UUID, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[RagChunk], int]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(RagChunk).where(RagChunk.doc_id == doc_id)
            )
        ).scalar_one()
        result = await self.session.execute(
            select(RagChunk)
            .where(RagChunk.doc_id == doc_id)
            .order_by(RagChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total)

    async def create_job(self, **fields: Any) -> RagJob:
        job = RagJob(**fields)
        self.session.add(job)
        await self.session.commit()
        return job

    async def get_job(self, job_id: uuid.UUID) -> RagJob | None:
        return await self.session.get(RagJob, job_id)

    async def claim_next_job(self) -> RagJob | None:
        result = await self.session.execute(
            select(RagJob)
            .where(RagJob.status == "queued")
            .order_by(RagJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job is None:
            await self.session.rollback()
            return None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await self.session.commit()
        return job

    async def update_job(self, job_id: uuid.UUID, **fields: Any) -> RagJob | None:
        job = await self.session.get(RagJob, job_id)
        if job is None:
            return None
        for key, value in fields.items():
            setattr(job, key, value)
        await self.session.commit()
        return job

    async def list_active_jobs(self, library_id: uuid.UUID | None = None) -> list[RagJob]:
        query = select(RagJob).where(RagJob.status.in_(["queued", "running"]))
        if library_id is not None:
            query = query.where(RagJob.library_id == library_id)
        result = await self.session.execute(query.order_by(RagJob.created_at))
        return list(result.scalars().all())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_repository.py tests/test_rag_api.py -q`
Expected: 全绿（既有 rag api 测试不回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/repositories/rag_repository.py backend/tests/test_rag_repository.py
git commit -m "feat(rag): repository support for libraries, jobs and library-scoped documents"
```

---

### Task 3: 库 API（CRUD + 统计）

**Files:**
- Modify: `backend/app/schemas/rag.py`、`backend/app/api/rag.py`、`backend/tests/conftest.py`（新增带 Origin 的 admin 客户端与 CSRF fixture）
- Test: `backend/tests/test_rag_libraries_api.py`

**Interfaces:**
- Consumes: Task 2 仓储方法
- Produces: REST 端点 `GET/POST /api/rag/libraries`、`GET/PATCH/DELETE /api/rag/libraries/{library_id}`；schema `RagLibraryItem`、`RagLibraryCreate`、`RagLibraryUpdate`、`RagLibraryListResponse`；测试 fixture `admin_client`（带 `Origin`）、`admin_csrf`（`{"X-CSRF-Token": ...}`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_libraries_api.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_library_crud(admin_client, admin_csrf):
    resp = await admin_client.post(
        "/api/rag/libraries", json={"name": "规则库", "description": "d"}, headers=admin_csrf
    )
    assert resp.status_code == 200
    lib = resp.json()["data"]
    assert lib["name"] == "规则库"
    assert lib["retrieval_enabled"] is True

    dup = await admin_client.post("/api/rag/libraries", json={"name": "规则库"}, headers=admin_csrf)
    assert dup.status_code == 409

    listed = (await admin_client.get("/api/rag/libraries")).json()["data"]["items"]
    assert any(item["id"] == lib["id"] for item in listed)
    assert [item for item in listed if item["id"] == lib["id"]][0]["stats"]["doc_count"] == 0

    patched = await admin_client.patch(
        f"/api/rag/libraries/{lib['id']}",
        json={"description": "新介绍", "retrieval_enabled": False},
        headers=admin_csrf,
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["retrieval_enabled"] is False

    deleted = await admin_client.delete(f"/api/rag/libraries/{lib['id']}", headers=admin_csrf)
    assert deleted.status_code == 200


@pytest.mark.anyio
async def test_delete_non_empty_library_conflicts(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    created = (
        await admin_client.post("/api/rag/libraries", json={"name": "非空库"}, headers=admin_csrf)
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        await repo.create_document(
            title="x", sha256="api1", status="ready", library_id=uuid.UUID(created["id"])
        )

    resp = await admin_client.delete(f"/api/rag/libraries/{created['id']}", headers=admin_csrf)
    assert resp.status_code == 409

    forced = await admin_client.delete(
        f"/api/rag/libraries/{created['id']}?force=true", headers=admin_csrf
    )
    assert forced.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_libraries_api.py -q`
Expected: FAIL — `fixture 'admin_csrf' not found`

- [ ] **Step 3: 加 conftest fixture（带 Origin 的 admin 客户端 + CSRF 头）**

`backend/tests/conftest.py` 顶部加 `TEST_ORIGIN = "http://localhost:3000"`，并把既有 `admin_client` 改为带 Origin（只增不改语义，既有测试仍通过）：

```python
@pytest.fixture
async def admin_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Origin": TEST_ORIGIN}
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={
                "username": settings.initial_admin_username,
                "password": settings.initial_admin_password,
            },
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def admin_csrf(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    return {"X-CSRF-Token": resp.json()["data"]["token"]}
```

- [ ] **Step 4: 加 schema**

`backend/app/schemas/rag.py` 追加：

```python
class RagLibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    kind: str = Field(default="custom", pattern="^(industry|rules|custom)$")


class RagLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: str | None = Field(default=None, pattern="^(admins_only|all_members)$")
    retrieval_enabled: bool | None = None


class RagLibraryStats(BaseModel):
    doc_count: int
    chunk_count: int
    ready_count: int
    failed_count: int
    last_updated_at: datetime | None = None


class RagLibraryItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    visibility: str
    retrieval_enabled: bool
    created_at: datetime
    updated_at: datetime
    stats: RagLibraryStats

    model_config = {"from_attributes": True}


class RagLibraryListResponse(BaseModel):
    items: list[RagLibraryItem]
```

同时 `RagDocumentItem` 增加 `library_id: uuid.UUID` 与 `error_message: str | None`。

- [ ] **Step 5: 加路由**

`backend/app/api/rag.py` 追加（放在 `search` 之前）：

```python
def _library_item(lib: RagLibrary, stats: dict[str, Any]) -> RagLibraryItem:
    return RagLibraryItem(
        id=lib.id,
        name=lib.name,
        description=lib.description,
        kind=lib.kind,
        visibility=lib.visibility,
        retrieval_enabled=lib.retrieval_enabled,
        created_at=lib.created_at,
        updated_at=lib.updated_at,
        stats=RagLibraryStats(**stats),
    )


@router.get("/libraries")
async def list_libraries(
    request: Request,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    libs = await repo.list_libraries()
    stats = await repo.library_stats()
    empty = {"doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None}
    payload = RagLibraryListResponse(
        items=[_library_item(lib, stats.get(lib.id, empty)) for lib in libs]
    )
    return success(request, payload.model_dump(mode="json"))


@router.post("/libraries")
async def create_library(
    request: Request,
    data: RagLibraryCreate,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library_by_name(data.name) is not None:
        raise ApiError(status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在")
    lib = await repo.create_library(
        name=data.name,
        description=data.description,
        kind=data.kind,
        created_by=current_user.id,
    )
    stats = {"doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None}
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.get("/libraries/{library_id}")
async def get_library(
    request: Request,
    library_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    lib = await repo.get_library(library_id)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    stats = (await repo.library_stats()).get(lib.id) or {
        "doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None
    }
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.patch("/libraries/{library_id}")
async def update_library(
    request: Request,
    library_id: uuid.UUID,
    data: RagLibraryUpdate,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if data.name:
        existing = await repo.get_library_by_name(data.name)
        if existing is not None and existing.id != library_id:
            raise ApiError(status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在")
    fields = data.model_dump(exclude_unset=True)
    lib = await repo.update_library(library_id, **fields)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    stats = (await repo.library_stats()).get(lib.id) or {
        "doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None
    }
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.delete("/libraries/{library_id}")
async def delete_library(
    request: Request,
    library_id: uuid.UUID,
    force: bool = Query(default=False),
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    lib = await repo.get_library(library_id)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    stats = (await repo.library_stats()).get(lib.id) or {"doc_count": 0}
    if stats["doc_count"] > 0 and not force:
        raise ApiError(
            status_code=409,
            code="LIBRARY_NOT_EMPTY",
            message="知识库非空：请先清空文档或使用强制删除",
        )
    await repo.delete_library(library_id)
    return success(request, {"deleted": True})
```

同时 import 区补 `RagLibrary` 与新增 schema；`or_` 已在 Task 2 用到，需在 repository 内 import。

- [ ] **Step 6: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_libraries_api.py -q`
Expected: `2 passed`

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/rag.py backend/app/schemas/rag.py backend/tests/test_rag_libraries_api.py
git commit -m "feat(rag): knowledge library CRUD API"
```

---

### Task 4: 文档列表/删除/切块 API + 库维度检索过滤

**Files:**
- Modify: `backend/app/api/rag.py`、`backend/app/services/rag/search.py`、`backend/app/repositories/rag_repository.py`（`_SessionRepo` 同步加库查询）
- Test: `backend/tests/test_rag_documents_api.py`、`backend/tests/test_rag_search_library_filter.py`

**Interfaces:**
- Produces:
  - `GET /api/rag/libraries/{library_id}/documents?q=&status=&page=&page_size=` → `RagDocumentListResponse`
  - `DELETE /api/rag/documents/{doc_id}`、`GET /api/rag/documents/{doc_id}/chunks?page=&page_size=`
  - `RagSearchService.search(query, top_k=5, *, library_id=None, include_disabled_libraries=False) -> list[SearchHit]`；`SearchHit` 增加 `library_id: uuid.UUID | None`、`library_name: str | None`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_documents_api.py
from __future__ import annotations

import uuid

import numpy as np
import pytest


def _vec() -> bytes:
    return np.array([1.0, 0.0], dtype=np.float32).tobytes()


@pytest.mark.anyio
async def test_documents_scoped_to_library(admin_client, test_db):
    from app.repositories.rag_repository import RagRepository

    lib_a = (await admin_client.post("/api/rag/libraries", json={"name": "库A"})).json()["data"]
    lib_b = (await admin_client.post("/api/rag/libraries", json={"name": "库B"})).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        await repo.create_document(title="A文档", sha256="da1", status="ready", library_id=uuid.UUID(lib_a["id"]))
        await repo.create_document(title="B文档", sha256="db1", status="ready", library_id=uuid.UUID(lib_b["id"]))

    page = (await admin_client.get(f"/api/rag/libraries/{lib_a['id']}/documents")).json()["data"]
    assert page["total"] == 1
    assert page["items"][0]["title"] == "A文档"

    filtered = (
        await admin_client.get(f"/api/rag/libraries/{lib_a['id']}/documents?q=B")
    ).json()["data"]
    assert filtered["total"] == 0


@pytest.mark.anyio
async def test_document_delete_and_chunks(admin_client, test_db):
    from app.repositories.rag_repository import RagRepository

    lib = (await admin_client.post("/api/rag/libraries", json={"name": "切块库"})).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.create_document(title="带块文档", sha256="dc1", status="ready", library_id=uuid.UUID(lib["id"]))
        await repo.add_chunks(doc.id, [("s1", "内容1", _vec(), 2), ("s2", "内容2", _vec(), 2)])
        doc_id = str(doc.id)

    chunks = (await admin_client.get(f"/api/rag/documents/{doc_id}/chunks")).json()["data"]
    assert chunks["total"] == 2
    assert chunks["items"][0]["section_path"] == "s1"
    assert "embedding" not in chunks["items"][0]

    deleted = await admin_client.delete(f"/api/rag/documents/{doc_id}")
    assert deleted.status_code == 200
    assert (await admin_client.get(f"/api/rag/documents/{doc_id}/chunks")).status_code == 404
```

```python
# backend/tests/test_rag_search_library_filter.py
from __future__ import annotations

import uuid

import numpy as np
import pytest

from app.models.rag import RagLibrary


class FakeProvider:
    dim = 2

    async def embed(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32).tobytes() for _ in texts]


@pytest.mark.anyio
async def test_search_filters_by_library_and_disabled_library(test_db):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib_on = await repo.create_library(name="启用库")
        lib_off = await repo.create_library(name="停用库", retrieval_enabled=False)

        doc_on = await repo.create_document(title="启用库文档", sha256="sf1", status="ready", library_id=lib_on.id)
        await repo.add_chunks(doc_on.id, [("s", "内容", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)])
        doc_off = await repo.create_document(title="停用库文档", sha256="sf2", status="ready", library_id=lib_off.id)
        await repo.add_chunks(doc_off.id, [("s", "内容", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)])

        service = RagSearchService(repo, FakeProvider(), store=None)

        hits = await service.search("内容", top_k=5)
        titles = {hit.title for hit in hits}
        assert titles == {"启用库文档"}
        assert hits[0].library_name == "启用库"

        only_off = await service.search("内容", top_k=5, library_id=lib_off.id, include_disabled_libraries=True)
        assert [hit.title for hit in only_off] == ["停用库文档"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_documents_api.py tests/test_rag_search_library_filter.py -q`
Expected: FAIL（路由 404 / `search()` 不接受 `library_id`）

- [ ] **Step 3: 改 search 服务**

`backend/app/services/rag/search.py`：
1. `SearchHit` dataclass 追加 `library_id: uuid.UUID | None = None`、`library_name: str | None = None`。
2. 增加 `_load_libraries`（与 `_load_documents` 同构，优先用仓储自定义方法 `get_libraries_by_ids`）。
3. `search` 签名与过滤：

```python
    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        library_id: uuid.UUID | None = None,
        include_disabled_libraries: bool = False,
    ) -> list[SearchHit]:
        # …前缀校验与 embed 不变
        fetch_k = max(top_k * 3, top_k)  # 过滤后仍能凑满 top_k
        candidates = await self.store.search(vectors[0], fetch_k)
        # …
        chunks = await self._load_chunks([chunk_id for chunk_id, _ in candidates])
        documents = await self._load_documents(list({c.doc_id for c in chunks.values()}))
        libraries = await self._load_libraries(
            list({d.library_id for d in documents.values() if d.library_id})
        )

        hits: list[SearchHit] = []
        for chunk_id, score in candidates:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            doc = documents.get(chunk.doc_id)
            if doc is None or doc.status != "ready":
                continue
            if library_id is not None and doc.library_id != library_id:
                continue
            lib = libraries.get(doc.library_id)
            if not include_disabled_libraries and lib is not None and not lib.retrieval_enabled:
                continue
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    doc_id=doc.id,
                    title=doc.title,
                    section_path=chunk.section_path or doc.title,
                    content=chunk.content,
                    source_url=doc.source_url,
                    publisher=doc.publisher,
                    score=score,
                    library_id=doc.library_id,
                    library_name=lib.name if lib is not None else None,
                )
            )
            if len(hits) >= top_k:
                break
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits
```

- [ ] **Step 4: 改 API**

`backend/app/api/rag.py`：
1. `RagSearchRequest` 加 `library_id: uuid.UUID | None = None`；`RagSearchHit` schema 加 `library_id` / `library_name`；`search()` 调用改为 `service.search(data.query, data.top_k, library_id=data.library_id, include_disabled_libraries=current_user is not None and data.include_disabled is True)`——`include_disabled` 仅超管可用（`getattr(current_user, "is_super_admin", False)`），普通用户固定 False。
2. `_SessionRepo` 加：

```python
    async def get_libraries_by_ids(self, library_ids: list[uuid.UUID]) -> list[RagLibrary]:
        if not library_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagLibrary).where(RagLibrary.id.in_(library_ids))
            )
            return list(result.scalars().all())
```

3. 新路由：

```python
@router.get("/libraries/{library_id}/documents")
async def list_library_documents(
    request: Request,
    library_id: uuid.UUID,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    result = await repo.list_documents(
        library_id=library_id, status=status, keyword=q, page=page, page_size=page_size
    )
    payload = RagDocumentListResponse(
        items=[RagDocumentItem.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )
    return success(request, payload.model_dump(mode="json"))


@router.delete("/documents/{doc_id}")
async def delete_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if not await repo.delete_document(doc_id):
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    get_search_service().store.invalidate()
    return success(request, {"deleted": True})


@router.get("/documents/{doc_id}/chunks")
async def list_document_chunks(
    request: Request,
    doc_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_document(doc_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    chunks, total = await repo.list_chunks_page(doc_id, page=page, page_size=page_size)
    return success(
        request,
        {
            "items": [
                {
                    "id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "section_path": chunk.section_path,
                    "content": chunk.content,
                }
                for chunk in chunks
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_documents_api.py tests/test_rag_search_library_filter.py tests/test_rag_api.py -q`
Expected: 全绿（既有检索测试不回归）

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/rag.py backend/app/schemas/rag.py backend/app/services/rag/search.py backend/tests/test_rag_documents_api.py backend/tests/test_rag_search_library_filter.py
git commit -m "feat(rag): library-scoped documents API and retrieval filtering"
```

---

### Task 5: 上传入库 API + `ingest_one` 公共函数

**Files:**
- Modify: `backend/app/services/rag/ingest.py`、`backend/app/api/rag.py`、`backend/app/schemas/rag.py`
- Test: `backend/tests/test_rag_upload_api.py`、`backend/tests/test_rag_ingest.py`（追加）

**Interfaces:**
- Produces:
  - `async def ingest_one(repo, provider, *, library_id, title, sha256, path: Path | None = None, markdown: str | None = None, source_url=None, publisher=None, license_note=LICENSE_NOTE, doc_type="industry_methodology", created_by=None, store=None) -> tuple[RagDocument, int]`（返回文档与块数；解析为空抛 `EmptyDocumentError`）
  - `class EmptyDocumentError(RuntimeError)`
  - `POST /api/rag/libraries/{library_id}/documents`（multipart `file`）→ `{doc_id, job_id}`
  - `rag_upload_root() -> Path`（`backend/var/rag/uploads`）
  - `UPLOAD_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".html", ".htm"}`、`MAX_UPLOAD_BYTES = 20 * 1024 * 1024`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_upload_api.py
from __future__ import annotations

import io
import uuid

import pytest


@pytest.mark.anyio
async def test_upload_creates_document_and_job(admin_client, test_db):
    lib = (await admin_client.post("/api/rag/libraries", json={"name": "上传库"})).json()["data"]
    files = {"file": ("手册.md", io.BytesIO("# 标题\n\n正文内容".encode("utf-8")), "text/markdown")}
    resp = await admin_client.post(f"/api/rag/libraries/{lib['id']}/documents", files=files)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["doc_id"] and body["job_id"]

    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(uuid.UUID(body["doc_id"]))
        assert doc.status == "pending"
        assert doc.library_id == uuid.UUID(lib["id"])
        job = await repo.get_job(uuid.UUID(body["job_id"]))
        assert job.status == "queued" and job.kind == "upload"


@pytest.mark.anyio
async def test_upload_rejects_bad_extension_and_duplicate(admin_client):
    lib = (await admin_client.post("/api/rag/libraries", json={"name": "校验库"})).json()["data"]
    bad = {"file": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    resp = await admin_client.post(f"/api/rag/libraries/{lib['id']}/documents", files=bad)
    assert resp.status_code == 400

    good = {"file": ("a.md", io.BytesIO("# t\n\nbody".encode("utf-8")), "text/markdown")}
    assert (await admin_client.post(f"/api/rag/libraries/{lib['id']}/documents", files=good)).status_code == 200
    dup = {"file": ("a.md", io.BytesIO("# t\n\nbody".encode("utf-8")), "text/markdown")}
    assert (await admin_client.post(f"/api/rag/libraries/{lib['id']}/documents", files=dup)).status_code == 409
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_upload_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 抽出 `ingest_one`**

`backend/app/services/rag/ingest.py`：

```python
class EmptyDocumentError(RuntimeError):
    """解析后没有正文（纯图片 PDF 等）。"""


async def ingest_one(
    repo: RagRepository,
    provider: EmbeddingProvider,
    *,
    library_id: uuid.UUID,
    title: str,
    sha256: str,
    path: Path | None = None,
    markdown: str | None = None,
    source_url: str | None = None,
    publisher: str | None = None,
    license_note: str = LICENSE_NOTE,
    doc_type: str = "industry_methodology",
    created_by: uuid.UUID | None = None,
    store: VectorStore | None = None,
    doc: RagDocument | None = None,
) -> tuple[RagDocument, int]:
    """入库单篇文档。

    `doc` 非空时复用该文档（清空旧切块后重写，用于上传占位文档与重新切分），
    为空时新建文档。
    """
    if markdown is None:
        if path is None:
            raise ValueError("path 与 markdown 至少提供一个")
        parsed = parse_source_file(path)
        markdown = parsed.markdown
        source_url = source_url or parsed.source_meta.get("source_url")
        publisher = publisher or parsed.source_meta.get("source")
        title = title or parsed.title
    text = (markdown or "").strip()
    if not text:
        raise EmptyDocumentError("未提取到正文")
    chunks = chunk_markdown(text)
    if not chunks:
        raise EmptyDocumentError("未提取到正文")
    embeddings = await provider.embed([chunk.content for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise RuntimeError(f"embedding 数量不匹配：{len(embeddings)} != {len(chunks)}")

    if doc is None:
        doc = await repo.create_document(
            title=title,
            doc_type=doc_type,
            source_url=source_url,
            publisher=publisher,
            license_note=license_note,
            file_key=path.name if path is not None else None,
            sha256=sha256,
            status="ready",
            library_id=library_id,
            created_by=created_by,
        )
    else:
        await repo.clear_chunks(doc.id)
        doc.title = title
        doc.doc_type = doc_type
        doc.source_url = source_url
        doc.publisher = publisher
        doc.license_note = license_note
        doc.sha256 = sha256
        doc.status = "ready"
        doc.error_message = None
        await repo.session.commit()

    await repo.add_chunks(
        doc.id,
        [
            (chunk.section_path, chunk.content, embedding, provider.dim)
            for chunk, embedding in zip(chunks, embeddings)
        ],
    )
    if store is not None:
        store.invalidate()
    return doc, len(chunks)
```

`ingest_manifest` 内部循环改为调用 `ingest_one(...)`（保留原统计与异常处理），并给 `ingest_manifest` 增加 `library_id: uuid.UUID` 必填参数。

- [ ] **Step 4: 加上传 API**

`backend/app/api/rag.py`：

```python
UPLOAD_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".html", ".htm"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def rag_upload_root() -> Path:
    from app.core.config import get_settings

    return Path(get_settings().backend_root_path) / "var" / "rag" / "uploads"


@router.post("/libraries/{library_id}/documents")
async def upload_document(
    request: Request,
    library_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")

    filename = _validate_filename(file.filename or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ApiError(status_code=400, code="UNSUPPORTED_FILE_TYPE", message=f"不支持的文件类型：{suffix}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(status_code=400, code="FILE_TOO_LARGE", message="文件超过 20MB 限制")
    detected = _detect_mime_type(content[:4096])
    if detected is None and suffix in {".pdf", ".docx", ".xlsx", ".pptx"}:
        raise ApiError(status_code=400, code="UNSUPPORTED_FILE_TYPE", message="文件内容与扩展名不匹配")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = await repo.get_document_by_sha256(sha256)
    if existing is not None and existing.library_id == library_id:
        raise ApiError(status_code=409, code="DOCUMENT_EXISTS", message="该文件已在本知识库中")

    target_dir = rag_upload_root() / str(library_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)

    doc = await repo.create_document(
        title=Path(filename).stem,
        doc_type="upload",
        file_key=str(target),
        sha256=sha256,
        status="pending",
        library_id=library_id,
        created_by=current_user.id,
    )
    job = await repo.create_job(
        library_id=library_id,
        doc_id=doc.id,
        kind="upload",
        status="queued",
        total=1,
        payload={"path": str(target), "title": Path(filename).stem},
        created_by=current_user.id,
    )
    return success(request, {"doc_id": str(doc.id), "job_id": str(job.id)})
```

（import 区补 `File, UploadFile`、`hashlib`、`Path`、`_validate_filename` / `_detect_mime_type` from `app.services.file_service`）

同一 Step 追加「重新切分」端点（复用同一 worker 与 `ingest_one(doc=...)` 复用语义）：

```python
@router.post("/documents/{doc_id}/reingest")
async def reingest_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    doc = await repo.get_document(doc_id)
    if doc is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    if not doc.file_key:
        raise ApiError(status_code=400, code="NO_SOURCE_FILE", message="该文档没有可重新解析的源文件")
    await repo.set_document_status(doc.id, "pending")
    job = await repo.create_job(
        library_id=doc.library_id,
        doc_id=doc.id,
        kind="upload",
        status="queued",
        total=1,
        payload={"path": doc.file_key, "title": doc.title, "sha256": doc.sha256},
        created_by=current_user.id,
    )
    return success(request, {"doc_id": str(doc.id), "job_id": str(job.id)})
```

并补测试（放在 `tests/test_rag_upload_api.py`）：

```python
@pytest.mark.anyio
async def test_reingest_enqueues_job_and_resets_status(admin_client, admin_csrf, test_db):
    import uuid as _uuid

    from app.repositories.rag_repository import RagRepository

    lib = (await admin_client.post("/api/rag/libraries", json={"name": "重切库"}, headers=admin_csrf)).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.create_document(
            title="可重切", sha256="re1", status="ready",
            library_id=_uuid.UUID(lib["id"]), file_key="backend/var/rag/uploads/x.md",
        )
        doc_id = str(doc.id)

    resp = await admin_client.post(f"/api/rag/documents/{doc_id}/reingest", headers=admin_csrf)
    assert resp.status_code == 200
    async with test_db() as session:
        repo = RagRepository(session)
        assert (await repo.get_document(_uuid.UUID(doc_id))).status == "pending"
        assert (await repo.get_job(_uuid.UUID(resp.json()["data"]["job_id"]))).kind == "upload"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_upload_api.py tests/test_rag_ingest.py -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/rag/ingest.py backend/app/api/rag.py backend/app/schemas/rag.py backend/tests/test_rag_upload_api.py
git commit -m "feat(rag): upload documents into a library with async job enqueue"
```

---

### Task 6: rag_ingest_worker（异步入库）

**Files:**
- Create: `backend/app/workers/rag_ingest_worker.py`
- Test: `backend/tests/test_rag_ingest_worker.py`

**Interfaces:**
- Consumes: `ingest_one`、`RagRepository.claim_next_job/update_job/clear_chunks`
- Produces: `async def run_cycle() -> bool`、`async def main() -> None`、`async def process_job(job_id: uuid.UUID) -> None`（测试直接调 `process_job`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_ingest_worker.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_process_job_marks_document_ready(test_db, tmp_path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            import numpy as np

            return [np.zeros(4, dtype=np.float32).tobytes() for _ in texts]

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="worker库")
        md = tmp_path / "doc.md"
        md.write_text("# 标题\n\n正文一\n\n## 小节\n\n正文二", encoding="utf-8")
        doc = await repo.create_document(
            title="worker文档", sha256="w1", status="pending", library_id=lib.id
        )
        job = await repo.create_job(
            library_id=lib.id, doc_id=doc.id, kind="upload", status="queued", total=1,
            payload={"path": str(md), "title": "worker文档"},
        )
        doc_id, job_id = doc.id, job.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(doc_id)
        job = await repo.get_job(job_id)
        assert doc.status == "ready" and doc.chunk_count >= 1
        assert job.status == "succeeded" and job.processed == 1


@pytest.mark.anyio
async def test_process_job_marks_failed_on_empty_document(test_db, tmp_path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            return []

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="失败库")
        md = tmp_path / "empty.md"
        md.write_text("   ", encoding="utf-8")
        doc = await repo.create_document(
            title="空文档", sha256="w2", status="pending", library_id=lib.id
        )
        job = await repo.create_job(
            library_id=lib.id, doc_id=doc.id, kind="upload", status="queued", total=1,
            payload={"path": str(md), "title": "空文档"},
        )
        doc_id, job_id = doc.id, job.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(doc_id)
        job = await repo.get_job(job_id)
        assert doc.status == "failed" and "未提取到正文" in (doc.error_message or "")
        assert job.status == "failed" and job.processed == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_ingest_worker.py -q`
Expected: FAIL — `ModuleNotFoundError: app.workers.rag_ingest_worker`

- [ ] **Step 3: 实现 worker**

```python
"""RAG 入库 worker：领取 rag_jobs 并执行解析/切分/向量化。"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import uuid
from pathlib import Path

from app.db.session import async_session_factory
from app.repositories.rag_repository import RagRepository
from app.services.rag.embedding import build_embedding_provider
from app.services.rag.ingest import EmptyDocumentError, ingest_one

logger = logging.getLogger("rag_ingest_worker")

POLL_INTERVAL_SECONDS = 3


async def process_job(job_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        repo = RagRepository(db)
        job = await repo.get_job(job_id)
        if job is None or job.status == "superseded":
            return
        provider = build_embedding_provider()
        payload = job.payload or {}
        processed = job.processed or 0
        try:
            doc = await repo.get_document(job.doc_id) if job.doc_id is not None else None
            if doc is not None:
                await repo.set_document_status(doc.id, "processing")
            path = Path(str(payload.get("path"))) if payload.get("path") else None
            await ingest_one(
                repo,
                provider,
                library_id=job.library_id,
                title=str(payload.get("title") or "未命名文档"),
                sha256=str(payload.get("sha256") or uuid.uuid4().hex),
                path=path,
                source_url=payload.get("source_url"),
                publisher=payload.get("publisher"),
                doc_type=str(payload.get("doc_type") or "upload"),
                created_by=job.created_by,
                doc=doc,
            )
            await repo.update_job(job.id, status="succeeded", processed=processed + 1)
        except EmptyDocumentError as exc:
            await _fail(repo, job, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("rag_ingest_job_failed job=%s", job_id)
            await _fail(repo, job, str(exc))


async def _fail(repo: RagRepository, job, message: str) -> None:
    if job.doc_id is not None:
        doc = await repo.get_document(job.doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.error_message = message
            await repo.session.commit()
    await repo.update_job(
        job.id, status="failed", processed=(job.processed or 0) + 1, error_message=message
    )


async def run_cycle() -> bool:
    async with async_session_factory() as db:
        repo = RagRepository(db)
        job = await repo.claim_next_job()
    if job is None:
        return False
    logger.info("rag_ingest_claimed job=%s library=%s", job.id, job.library_id)
    await process_job(job.id)
    return True


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    logger.info("rag_ingest_worker_started")
    while not stop_event.is_set():
        try:
            ran = await run_cycle()
        except Exception:  # noqa: BLE001
            logger.exception("rag_ingest_cycle_failed")
            ran = False
        if ran:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("rag_ingest_worker_stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
```

注意：上传流程的占位文档（`pending`）由 `ingest_one(doc=...)` 复用并置为 `ready`，因此文档 ID 在入库前后保持稳定（前端表格无需处理 ID 变化）。

- [ ] **Step 4: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_ingest_worker.py -q`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/workers/rag_ingest_worker.py backend/tests/test_rag_ingest_worker.py
git commit -m "feat(rag): async ingest worker for upload jobs"
```

---

### Task 7: 从已采集素材导入 + 任务查询 API

**Files:**
- Modify: `backend/app/api/rag.py`、`backend/app/schemas/rag.py`、`backend/app/services/rag/ingest.py`
- Test: `backend/tests/test_rag_import_api.py`、`backend/tests/test_rag_jobs_api.py`

**Interfaces:**
- Produces: `POST /api/rag/libraries/{library_id}/import` `{scope, category?, limit?}` → `{job_id, queued}`；`GET /api/rag/jobs/{job_id}`、`GET /api/rag/jobs?library_id=&active=true`
- 素材根目录：`get_settings().kb_industry_root_path`（`backend/var/kb_industry`，含 `markdown/` 与 `manifest/manifest.json`、`manifest/manifest-core.json`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_import_api.py
from __future__ import annotations

import json

import pytest


@pytest.mark.anyio
async def test_import_from_collected_material(admin_client, admin_csrf, tmp_path, monkeypatch):
    from app.api import rag as rag_api

    source_dir = tmp_path / "markdown"
    source_dir.mkdir()
    (source_dir / "a.md").write_text("# A\n\n正文A", encoding="utf-8")
    (source_dir / "b.md").write_text("# B\n\n正文B", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"title": "A文档", "file": "a.md", "sha256": "imp-a", "source_site": "测试源", "category": "methodology"},
                {"title": "B规则", "file": "b.md", "sha256": "imp-b", "source_site": "测试源", "category": "rules"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rag_api, "kb_industry_root", lambda: tmp_path)
    monkeypatch.setattr(rag_api, "kb_manifest_path", lambda scope: manifest)

    lib = (
        await admin_client.post("/api/rag/libraries", json={"name": "导入库"}, headers=admin_csrf)
    ).json()["data"]
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/import",
        json={"scope": "all", "category": "rules"},
        headers=admin_csrf,
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["queued"] == 1

    detail = (await admin_client.get(f"/api/rag/jobs/{body['job_id']}")).json()["data"]
    assert detail["kind"] == "import"
    assert detail["total"] == 1
    assert detail["status"] == "queued"
```

```python
# backend/tests/test_rag_jobs_api.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_jobs_list_and_detail(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    lib = (
        await admin_client.post("/api/rag/libraries", json={"name": "任务查询库"}, headers=admin_csrf)
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        job = await repo.create_job(
            library_id=uuid.UUID(lib["id"]), kind="upload", status="running", total=3, processed=1
        )
        job_id = str(job.id)

    detail = (await admin_client.get(f"/api/rag/jobs/{job_id}")).json()["data"]
    assert detail["status"] == "running" and detail["processed"] == 1

    active = (
        await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}&active=true")
    ).json()["data"]["items"]
    assert [item["id"] for item in active] == [job_id]

    all_jobs = (await admin_client.get(f"/api/rag/jobs?library_id={lib['id']}")).json()["data"]["items"]
    assert [item["id"] for item in all_jobs] == [job_id]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_import_api.py tests/test_rag_jobs_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 加导入与任务路由**

`backend/app/api/rag.py`：

```python
def kb_industry_root() -> Path:
    return Path(get_settings().backend_root_path) / "var" / "kb_industry"


def kb_manifest_path(scope: str) -> Path:
    name = "manifest-core.json" if scope == "core" else "manifest.json"
    return kb_industry_root() / "manifest" / name


class RagImportRequest(BaseModel):
    scope: str = Field(default="core", pattern="^(core|all)$")
    category: str | None = Field(default=None, pattern="^(methodology|rules|other)$")
    limit: int | None = Field(default=None, ge=1, le=2000)


@router.post("/libraries/{library_id}/import")
async def import_collected(
    request: Request,
    library_id: uuid.UUID,
    data: RagImportRequest,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    manifest = kb_manifest_path(data.scope)
    if not manifest.exists():
        raise ApiError(status_code=400, code="MANIFEST_NOT_FOUND", message=f"素材清单不存在：{manifest.name}")

    items = load_manifest_items(manifest)
    if data.category:
        items = [item for item in items if str(item.get("category") or "methodology") == data.category]
    if data.limit is not None:
        items = items[: data.limit]
    if not items:
        raise ApiError(status_code=400, code="NO_MATERIAL", message="没有符合条件的素材")

    job = await repo.create_job(
        library_id=library_id,
        kind="import",
        status="queued",
        total=len(items),
        payload={"scope": data.scope, "category": data.category, "items": items},
        created_by=current_user.id,
    )
    return success(request, {"job_id": str(job.id), "queued": len(items)})


@router.get("/jobs/{job_id}")
async def get_job(
    request: Request,
    job_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    job = await repo.get_job(job_id)
    if job is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="任务不存在")
    return success(request, _job_payload(job))


@router.get("/jobs")
async def list_jobs(
    request: Request,
    library_id: uuid.UUID | None = Query(default=None),
    active: bool = Query(default=False),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    jobs = (
        await repo.list_active_jobs(library_id)
        if active
        else await repo.list_jobs(library_id)
    )
    return success(request, {"items": [_job_payload(job) for job in jobs]})


def _job_payload(job: RagJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "library_id": str(job.library_id),
        "doc_id": str(job.doc_id) if job.doc_id else None,
        "kind": job.kind,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
```

`RagRepository` 追加：

```python
    async def list_jobs(self, library_id: uuid.UUID | None = None) -> list[RagJob]:
        query = select(RagJob)
        if library_id is not None:
            query = query.where(RagJob.library_id == library_id)
        result = await self.session.execute(query.order_by(RagJob.created_at.desc()).limit(50))
        return list(result.scalars().all())
```

导入任务的执行：`rag_ingest_worker` 的 `process_job` 需支持 `kind="import"`——payload 里带 `items` 时逐个 `ingest_one`（`path=kb_industry_root()/"markdown"/item["file"]`，`sha256=item["sha256"]`，去重跳过计入 processed），每完成一个更新 `processed`。把这段逻辑加进 Task 6 的 `process_job`（实现时同步补一个 `test_process_import_job` 用例，断言 total/processed 与文档数）。

- [ ] **Step 4: 跑测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_import_api.py tests/test_rag_jobs_api.py tests/test_rag_ingest_worker.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/rag.py backend/app/schemas/rag.py backend/app/services/rag/ingest.py backend/app/repositories/rag_repository.py backend/tests/test_rag_import_api.py backend/tests/test_rag_jobs_api.py
git commit -m "feat(rag): import collected material and job progress APIs"
```

---

### Task 8: 前端库列表（`/knowledge` 改造）

**Files:**
- Modify: `frontend/src/lib/rag-api.ts`、`frontend/src/lib/copy.ts`、`frontend/src/app/(dashboard)/knowledge/page.tsx`
- Create: `frontend/src/components/knowledge/library-grid.tsx`、`library-card.tsx`、`new-library-modal.tsx`
- Test: `frontend/src/components/knowledge/library-grid.test.tsx`

**Interfaces:**
- Produces（`ragApi` 新增）：
  - `listLibraries(): Promise<RagLibrary[]>`、`createLibrary(body)`、`updateLibrary(id, body)`、`deleteLibrary(id, force?)`
  - 类型 `RagLibrary { id; name; description; kind; visibility; retrieval_enabled; created_at; updated_at; stats: { doc_count; chunk_count; ready_count; failed_count; last_updated_at } }`
- 组件 props：`<LibraryGrid />`（自取数据）、`<LibraryCard library onOpen onChanged />`、`<NewLibraryModal open library? onClose onSaved />`

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/knowledge/library-grid.test.tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockListLibraries, mockCreateLibrary } = vi.hoisted(() => ({
  mockListLibraries: vi.fn(),
  mockCreateLibrary: vi.fn(),
}));

vi.mock("@/lib/rag-api", () => ({
  ragApi: { listLibraries: mockListLibraries, createLibrary: mockCreateLibrary },
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mockPush }) }));

import LibraryGrid from "./library-grid";

const LIB = {
  id: "lib-1",
  name: "行业知识库",
  description: "抖音电商官方方法论",
  kind: "industry",
  visibility: "admins_only",
  retrieval_enabled: true,
  created_at: "2026-09-15T07:00:00Z",
  updated_at: "2026-09-15T07:52:00Z",
  stats: { doc_count: 192, chunk_count: 1501, ready_count: 192, failed_count: 0, last_updated_at: "2026-09-15T07:52:00Z" },
};

function renderGrid() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <LibraryGrid />
    </ConfigProvider>
  );
}

describe("LibraryGrid", () => {
  beforeEach(() => {
    mockListLibraries.mockReset();
    mockCreateLibrary.mockReset();
    mockPush.mockReset();
  });

  it("renders library cards with real stats and opens detail on click", async () => {
    mockListLibraries.mockResolvedValue([LIB]);
    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());
    expect(screen.getByText(/192/)).toBeTruthy();
    expect(screen.getByText(/1,501/)).toBeTruthy();
    await userEvent.click(screen.getByText("行业知识库"));
    expect(mockPush).toHaveBeenCalledWith("/knowledge/lib-1");
  });

  it("creates a library from the new modal", async () => {
    mockListLibraries.mockResolvedValue([]);
    mockCreateLibrary.mockResolvedValue({ ...LIB, id: "lib-2", name: "新库", stats: { ...LIB.stats, doc_count: 0, chunk_count: 0 } });
    renderGrid();
    await waitFor(() => expect(mockListLibraries).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /新建知识库/ }));
    await userEvent.type(screen.getByLabelText("名称"), "新库");
    await userEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(mockCreateLibrary).toHaveBeenCalledWith({ name: "新库", description: undefined }));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run（`frontend/` 下）：`npx vitest run src/components/knowledge/library-grid.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 扩展 `rag-api.ts`**

```ts
export interface RagLibraryStats {
  doc_count: number;
  chunk_count: number;
  ready_count: number;
  failed_count: number;
  last_updated_at: string | null;
}

export interface RagLibrary {
  id: string;
  name: string;
  description: string | null;
  kind: string;
  visibility: string;
  retrieval_enabled: boolean;
  created_at: string;
  updated_at: string;
  stats: RagLibraryStats;
}

export interface RagJob {
  id: string;
  library_id: string;
  doc_id: string | null;
  kind: string;
  status: string;
  total: number;
  processed: number;
  error_message: string | null;
}

// ragApi 内新增：
  listLibraries: () => api<{ items: RagLibrary[] }>("/api/rag/libraries").then((r) => r.items),
  createLibrary: (body: { name: string; description?: string; kind?: string }) =>
    api<RagLibrary>("/api/rag/libraries", { method: "POST", csrf: true, body: JSON.stringify(body) }),
  updateLibrary: (id: string, body: Partial<{ name: string; description: string; visibility: string; retrieval_enabled: boolean }>) =>
    api<RagLibrary>(`/api/rag/libraries/${id}`, { method: "PATCH", csrf: true, body: JSON.stringify(body) }),
  deleteLibrary: (id: string, force = false) =>
    api<{ deleted: boolean }>(`/api/rag/libraries/${id}${force ? "?force=true" : ""}`, { method: "DELETE", csrf: true }),
  listLibraryDocuments: (libraryId: string, params: RagDocumentListParams = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.keyword) q.set("q", params.keyword);
    q.set("page", String(params.page ?? 1));
    q.set("page_size", String(params.pageSize ?? 20));
    return api<RagDocumentPage>(`/api/rag/libraries/${libraryId}/documents?${q.toString()}`);
  },
  deleteDocument: (id: string) =>
    api<{ deleted: boolean }>(`/api/rag/documents/${id}`, { method: "DELETE", csrf: true }),
  listChunks: (docId: string, page = 1, pageSize = 20) =>
    api<{ items: { id: string; chunk_index: number; section_path: string | null; content: string }[]; total: number }>(
      `/api/rag/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`
    ),
  uploadDocument: (libraryId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<{ doc_id: string; job_id: string }>(`/api/rag/libraries/${libraryId}/documents`, {
      method: "POST",
      csrf: true,
      body: form,
    });
  },
  importCollected: (libraryId: string, body: { scope: "core" | "all"; category?: string; limit?: number }) =>
    api<{ job_id: string; queued: number }>(`/api/rag/libraries/${libraryId}/import`, {
      method: "POST",
      csrf: true,
      body: JSON.stringify(body),
    }),
  listJobs: (libraryId: string, active = false) =>
    api<{ items: RagJob[] }>(`/api/rag/jobs?library_id=${libraryId}&active=${active}`).then((r) => r.items),
```

`search` 增加可选库过滤：`search: (query: string, topK = 5, libraryId?: string) => api<RagSearchResult>("/api/rag/search", { method: "POST", body: JSON.stringify({ query, top_k: topK, library_id: libraryId }) })`。

- [ ] **Step 4: 写组件**

`library-card.tsx`：卡片渲染（名称、介绍、`192 篇 · 1,501 块`、权限/类型标签、检索状态、`···` 菜单含 重命名/停用检索/删除），`onOpen` 由外层 `router.push(\`/knowledge/${library.id}\`)` 提供。

`library-grid.tsx`：`useEffect` 拉 `ragApi.listLibraries()`；顶部统计条（库数/文档总数/块总数/最近入库）；网格渲染 `LibraryCard` + 虚线「新建知识库」卡片；空态与错误态用 `view-states`；新建/编辑用 `NewLibraryModal`。

`new-library-modal.tsx`：AntD `Modal` + `Form`，字段 `名称`（必填，`aria-label` 与 label 均为「名称」）、`介绍`；提交调用 `ragApi.createLibrary` 或 `ragApi.updateLibrary`；409 时在表单内联报错。

- [ ] **Step 5: 改造页面与文案**

`knowledge/page.tsx`：保留超管门与 `PageHeader`，把 `<DocumentList />` 换成 `<LibraryGrid />`，描述改为「按库组织文档、控制启用状态、验证检索效果 · 仅超级管理员可访问」。
`copy.ts`：`knowledge: "知识库管理"`。

- [ ] **Step 6: 跑测试确认通过**

Run: `npx vitest run src/components/knowledge/library-grid.test.tsx`
Expected: `2 passed`

- [ ] **Step 7: 提交**

```bash
git add frontend/src/lib/rag-api.ts frontend/src/lib/copy.ts "frontend/src/app/(dashboard)/knowledge/page.tsx" frontend/src/components/knowledge/library-grid.tsx frontend/src/components/knowledge/library-card.tsx frontend/src/components/knowledge/new-library-modal.tsx frontend/src/components/knowledge/library-grid.test.tsx
git commit -m "feat(knowledge): library grid with create/rename/delete"
```

---

### Task 9: 前端库详情（数据集 / 搜索测试 / 配置）

**Files:**
- Create: `frontend/src/app/(dashboard)/knowledge/[libraryId]/page.tsx`、`frontend/src/components/knowledge/library-detail-nav.tsx`、`dataset-table.tsx`、`upload-modal.tsx`、`search-test-panel.tsx`、`config-panel.tsx`、`chunk-preview-drawer.tsx`
- Delete: `frontend/src/components/knowledge/document-list.tsx`、`document-list.test.tsx`、`document-preview-drawer.tsx`
- Test: `frontend/src/components/knowledge/dataset-table.test.tsx`、`upload-modal.test.tsx`、`search-test-panel.test.tsx`

**Interfaces:**
- Consumes: Task 8 的 `ragApi` 方法；`useSearchParams` 读 `tab`
- Produces: `<DatasetTable libraryId />`、`<UploadModal libraryId open onClose onQueued />`、`<SearchTestPanel libraryId />`、`<ConfigPanel library onSaved />`、`<ChunkPreviewDrawer doc open onClose />`、`<LibraryDetailNav libraryId libraryName activeTab />`

- [ ] **Step 1: 写失败测试（三个文件，核心断言）**

```tsx
// dataset-table.test.tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockList, mockDisable, mockEnable, mockDelete } = vi.hoisted(() => ({
  mockList: vi.fn(), mockDisable: vi.fn(), mockEnable: vi.fn(), mockDelete: vi.fn(),
}));
vi.mock("@/lib/rag-api", () => ({
  ragApi: { listLibraryDocuments: mockList, disable: mockDisable, enable: mockEnable, deleteDocument: mockDelete },
}));

import DatasetTable from "./dataset-table";

const DOC = {
  id: "d1", title: "千川手册", doc_type: "industry_methodology", source_url: null,
  publisher: "抖音电商官方学习中心", status: "ready", chunk_count: 52,
  created_at: "2026-09-15T07:49:00Z", updated_at: "2026-09-15T07:52:00Z",
};

describe("DatasetTable", () => {
  beforeEach(() => {
    mockList.mockReset(); mockDisable.mockReset(); mockEnable.mockReset(); mockDelete.mockReset();
  });

  it("renders documents and toggles enabled state", async () => {
    mockList.mockResolvedValue({ items: [DOC], page: 1, page_size: 20, total: 1 });
    mockDisable.mockResolvedValue({ ...DOC, status: "disabled" });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("千川手册")).toBeTruthy());
    expect(screen.getByText("52")).toBeTruthy();
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(mockDisable).toHaveBeenCalledWith("d1"));
  });

  it("shows failure reason for failed documents", async () => {
    mockList.mockResolvedValue({
      items: [{ ...DOC, id: "d2", status: "failed", error_message: "未提取到正文", chunk_count: 0 }],
      page: 1, page_size: 20, total: 1,
    });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("失败")).toBeTruthy());
    expect(screen.getByTitle("未提取到正文")).toBeTruthy();
  });
});
```

```tsx
// upload-modal.test.tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockUpload, mockJobs } = vi.hoisted(() => ({ mockUpload: vi.fn(), mockJobs: vi.fn() }));
vi.mock("@/lib/rag-api", () => ({
  ragApi: { uploadDocument: mockUpload, listJobs: mockJobs },
}));

import UploadModal from "./upload-modal";

describe("UploadModal", () => {
  beforeEach(() => {
    mockUpload.mockReset();
    mockJobs.mockReset();
  });

  it("uploads a file and shows queued progress", async () => {
    mockUpload.mockResolvedValue({ doc_id: "d9", job_id: "j9" });
    mockJobs.mockResolvedValue([
      { id: "j9", library_id: "lib-1", doc_id: "d9", kind: "upload", status: "running", total: 1, processed: 0, error_message: null },
    ]);
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <UploadModal libraryId="lib-1" open onClose={() => {}} onQueued={() => {}} />
      </ConfigProvider>
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["# t"], "a.md", { type: "text/markdown" }));
    await userEvent.click(screen.getByRole("button", { name: "开始上传" }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/处理中/)).toBeTruthy());
  });
});
```

```tsx
// search-test-panel.test.tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockSearch } = vi.hoisted(() => ({ mockSearch: vi.fn() }));
vi.mock("@/lib/rag-api", () => ({ ragApi: { search: mockSearch } }));

import SearchTestPanel from "./search-test-panel";

describe("SearchTestPanel", () => {
  beforeEach(() => mockSearch.mockReset());

  it("runs a library-scoped search and renders hits", async () => {
    mockSearch.mockResolvedValue({
      items: [
        {
          chunk_id: "c1",
          doc_id: "d1",
          title: "千川手册",
          section_path: "出价",
          content: "控成本投放",
          source_url: "https://x",
          publisher: "抖音",
          score: 0.83,
        },
      ],
      elapsed_ms: 12,
    });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <SearchTestPanel libraryId="lib-1" />
      </ConfigProvider>
    );
    await userEvent.type(screen.getByPlaceholderText("输入问题，验证本库召回效果"), "出价策略");
    await userEvent.click(screen.getByRole("button", { name: "检索" }));
    await waitFor(() => expect(screen.getByText("千川手册")).toBeTruthy());
    expect(mockSearch).toHaveBeenCalledWith("出价策略", 5, "lib-1");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/knowledge/dataset-table.test.tsx src/components/knowledge/upload-modal.test.tsx src/components/knowledge/search-test-panel.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现组件**

- `dataset-table.tsx`：AntD `Table`（列：名称+来源副标题、训练模式固定「直接分段」、数据总量（块数）、创建/更新时间、状态（`ready` 绿「已就绪」/`pending` 金「排队中」/`processing` 蓝「处理中」/`failed` 红「失败」+ `Tooltip title={error_message}`/`disabled` 灰「已禁用」）、`Switch`（`checked={status !== "disabled"}`，`aria-label` 用标题）、操作 `···`（预览切块 / 查看来源 / 重新切分 / 删除））；工具栏含搜索框、状态筛选、批量启用/禁用/删除、「新建 / 导入」按钮（打开 `UploadModal`）；存在 `pending/processing` 或活跃任务时 `setInterval` 3s 刷新（`document.visibilityState === "visible"` 才轮询），卸载清理。
- `upload-modal.tsx`：AntD `Upload.Dragger`（`beforeUpload` 返回 false 只收集文件，校验扩展名与 20MB），「开始上传」逐个 `ragApi.uploadDocument`，随后轮询 `ragApi.listJobs(libraryId, true)` 显示「处理中 x/y」，全部结束后 `onQueued()` 触发列表刷新并关闭。
- `search-test-panel.tsx`：输入框（placeholder「输入问题，验证本库召回效果」）、Top-K `Select`（3/5/10）、「检索」按钮 → `ragApi.search(q, topK, libraryId)`；命中卡片显示相似度条、`section_path`、正文（关键词高亮可选）、来源链接、`elapsed_ms`。
- `config-panel.tsx`：展示库信息（名称/介绍/可见范围可改 → `ragApi.updateLibrary`）、向量与切分只读项（bge-small-zh-v1.5 · 512 维 / 512 字符 64 重叠 / 精确余弦 Top-K 20）、采集来源白名单只读、危险区（清空文档 / 删除库：调用 `deleteDocument` 批量或 `deleteLibrary(id, force)`，删除库后 `router.push("/knowledge")`）。
- `chunk-preview-drawer.tsx`：`ragApi.listChunks(docId, page)` 分页展示 `section_path` + `content`。
- `library-detail-nav.tsx`：左侧子导航（库名 + 类型标签、`数据集`/`搜索测试`/`配置` 三项切换 `?tab=`、底部「← 全部知识库」`router.push("/knowledge")`）。
- `[libraryId]/page.tsx`：`useParams()` 取 `libraryId`，`useSearchParams()` 取 `tab`（默认 `datasets`），超管门 + `PageHeader`（库名），布局 `detail`（左导航 + 右侧面板）。

- [ ] **Step 4: 删除旧组件并跑测试**

```bash
git rm frontend/src/components/knowledge/document-list.tsx frontend/src/components/knowledge/document-list.test.tsx frontend/src/components/knowledge/document-preview-drawer.tsx
```
Run: `npx vitest run src/components/knowledge`
Expected: 全绿（新 3 个测试文件 + 既有 preview 测试若有则同步删除）

- [ ] **Step 5: 提交**

```bash
git add "frontend/src/app/(dashboard)/knowledge/[libraryId]/page.tsx" frontend/src/components/knowledge
git commit -m "feat(knowledge): library detail with datasets, search test and config"
```

---

### Task 10: 运行脚本 / 文档 / 回归验收

**Files:**
- Modify: `scripts/run-all.ps1`、`scripts/status-all.ps1`、`scripts/stop-all.ps1`、`README.md`
- Create: `docs/verification/knowledge-management-checklist.md`

- [ ] **Step 1: 把 `rag_ingest_worker` 纳入一键脚本**

`run-all.ps1` 的 `$workers` 数组追加一项：

```powershell
@{ name = "rag-ingest-worker"; module = "app.workers.rag_ingest_worker" },
```

`status-all.ps1` 的状态表加一行 `rag-ingest-worker`；`stop-all.ps1` 依赖 pid 文件无需改动（确认会遍历 `.runtime/pids/*.pid`）。

- [ ] **Step 2: 回归：评测集不下降**

Run（`backend/` 下）：
```
$env:WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS="true"
X:\python\anaconda\envs\01-rbac\python.exe scripts\rag_eval.py
```
Expected: `recall@5 >= 0.90`（与迁移前一致；报告中 `docs/rag-eval/report.md` 更新）

- [ ] **Step 3: 后端全量回归**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest -q`
Expected: 通过数不低于本轮改动前基线（已知非本轮失败：4 个缺依赖的 `test_file_reader` + 1 个他人未跟踪测试），且 **无新增失败**

- [ ] **Step 4: 写验收清单**

`docs/verification/knowledge-management-checklist.md`：逐条列出人工验收步骤（新建库 → 上传 PDF → 进度到 ready → 块数正确 → 搜索测试命中 → Agent `knowledge_search` 引用新库；规则库导入 254 篇；192 篇仍在默认库；普通用户被拒且 Agent 检索可用；删除非空库提示；停用库不参与检索），每条含「预期」与「实测」两栏。

- [ ] **Step 5: 提交**

```bash
git add scripts/run-all.ps1 scripts/status-all.ps1 scripts/stop-all.ps1 README.md docs/verification/knowledge-management-checklist.md docs/rag-eval/report.md
git commit -m "chore(knowledge): wire ingest worker into scripts and add acceptance checklist"
```

---

## Self-Review

**Spec coverage**

| Spec 章节 | 对应任务 |
| --- | --- |
| 3.1 `rag_libraries` / 3.2 `rag_documents.library_id` / 3.3 迁移回填 / 3.4 `rag_jobs` | Task 1 |
| 4 库 API（列表/新建/详情/改/删 + 统计） | Task 3 |
| 4 文件 API（分页搜索/删除/切块/启用禁用） | Task 4（启用禁用沿用既有端点） |
| 4 上传 + 任务入队 | Task 5 |
| 4 从已采集素材导入（`scope`/`category`/`limit`） | Task 7 |
| 4 任务进度 API | Task 7 |
| 4 检索 `library_id` 过滤 + 停用库跳过 | Task 4 |
| 5 入库管线（`ingest_one` 公共函数 + worker + 失败原因 + 重试） | Task 5 / Task 6（重试 = 再次 `POST .../reingest` 复用上传接口，见下） |
| 6 前端两级页面与组件 | Task 8 / Task 9 |
| 7 边界与错误（409/白名单/去重/解析为空/停用库） | Task 3 / Task 5 / Task 4 |
| 8 测试与验收 | 各任务测试 + Task 10 |
| v1 不做（UI 触发采集、库级 embedding 参数、用户私有库） | 未排任务（符合 spec） |

**已并入任务的两处补丁（不再留到实现期临时决定）**

1. `POST /api/rag/documents/{doc_id}/reingest` 与「重试」能力：并入 Task 5（含测试），复用 `ingest_one(doc=...)` 的复用语义与 `clear_chunks`。
2. 导入任务的 `process_job` 分支（`kind="import"` 遍历 `payload["items"]`，逐篇 `ingest_one` 并推进 `processed`）：并入 Task 7 Step 3，并要求补 `test_process_import_job`。

**Type consistency 检查**：`library_stats()` 键名在 Task 2/3 一致；`ingest_one` 参数（含 `doc`）在 Task 5/6/7 一致；`ragApi` 方法名在 Task 8/9 一致（`listLibraries` / `listLibraryDocuments` / `uploadDocument` / `listJobs` / `search(q, topK, libraryId)`）；`SearchHit.library_id/library_name` 在 Task 4 定义并在 Task 9 展示；测试 fixture `admin_client`（带 Origin）/`admin_csrf` 在 Task 3 定义、后续任务统一使用。

**Placeholder 扫描**：无 TBD/TODO；所有代码步骤含可执行代码；测试步骤含真实断言与预期输出。
