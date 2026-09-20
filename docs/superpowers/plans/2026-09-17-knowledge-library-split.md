# 知识库多库拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把单一「行业知识库」拆成 8 个专业库（规则路由），全量 601 篇素材按库入库，删除老库。

**Architecture:** 新增纯函数归类器 `library_routing.py` 作为唯一事实源（库定义 + 标签/标题规则）；一次 alembic 迁移完成「建 8 库 → 迁移已有文档 → 断言 → 删老库」；采集素材通过一个「路由导入任务」交给现有 `rag_ingest_worker` 逐篇按库入库；检索新增按库名过滤，DSH `knowledge_search` 工具与技能模板同步。

**Tech Stack:** FastAPI + SQLAlchemy(async) + alembic + PostgreSQL；pytest(asyncio_mode=auto)；Next.js + AntD + vitest；DSH connector（TypeScript + vitest）。

**Spec:** `docs/superpowers/specs/2026-09-17-knowledge-library-split-design.md`

## Global Constraints

- 8 个库的固定 UUID：`6f1d2c3a-1111-4a2b-9c3d-000000000101` … `…0108`（顺序见 Task 1 的 `LIBRARY_SEEDS`）。
- 老库 UUID（删除目标）：`6f1d2c3a-1111-4a2b-9c3d-000000000001`。
- 迁移必须可逆（`downgrade` 重建老库并把文档指回）。
- 路由只改 `rag_documents.library_id`：**不重算 embedding、不重新切块**。
- 幂等键是 `sha256`：重复导入不得产生重复文档。
- 不新增 RBAC 权限码（沿用 `require_super_admin`）。
- 后端命令一律在 `backend/` 下用 `X:\python\anaconda\envs\01-rbac\python.exe` 执行。
- 前端测试：`frontend/` 下 `npx vitest run <file>`；connector 测试：`dsh-platform/packages/server-connector/` 下 `pnpm test`。

---

### Task 1: 归类器 `library_routing.py`

**Files:**
- Create: `backend/app/services/rag/library_routing.py`
- Test: `backend/tests/test_rag_library_routing.py`

**Interfaces:**
- Consumes: `app.services.rag.ingest.classify_manifest_item(item) -> "methodology" | "rules" | "other"`
- Produces:
  - `LIBRARY_SEEDS: tuple[LibrarySeed, ...]`（8 项；`LibrarySeed(slug, id, name, description, kind)`）
  - `SLUG_TO_SEED: dict[str, LibrarySeed]`
  - `FALLBACK_SLUG = "general"`
  - `route_library(item: dict) -> RouteResult`（`RouteResult(slug, library_id, library_name, matched_rule)`）
  - 素材字段口径：`item["title"]: str`、`item["tags"]: list[str] | str`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_library_routing.py
import json
from pathlib import Path

from app.services.rag.library_routing import (
    FALLBACK_SLUG,
    LIBRARY_SEEDS,
    route_library,
)

MANIFEST = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "manifest" / "manifest.json"

EXPECTED_DISTRIBUTION = {
    "qianchuan": 80,
    "live": 21,
    "short-video": 25,
    "mall": 37,
    "influencer": 65,
    "industry-case": 57,
    "platform-rules": 254,
    "general": 62,
}


def test_eight_libraries_with_unique_ids_and_names():
    assert len(LIBRARY_SEEDS) == 8
    assert len({seed.id for seed in LIBRARY_SEEDS}) == 8
    assert len({seed.name for seed in LIBRARY_SEEDS}) == 8


def test_rules_category_goes_to_platform_rules():
    item = {"title": "商家申诉举证标准", "tags": ["规则解读"]}
    assert route_library(item).slug == "platform-rules"


def test_industry_case_tag_wins_over_business_tags():
    item = {
        "title": "差异化选品提升竞争力，短视频+直播助推618生意突围",
        "tags": ["案例-直播运营", "案例-短视频运营", "案例-商城运营", "案例-生鲜"],
    }
    assert route_library(item).slug == "industry-case"


def test_business_tag_priority_qianchuan_before_live():
    item = {"title": "直播间运营白皮书", "tags": ["商品推广(千川)", "直播间运营"]}
    assert route_library(item).slug == "qianchuan"


def test_title_fallback_when_no_tag_matches():
    item = {"title": "巨量千川直播全域投放使用宝典", "tags": []}
    result = route_library(item)
    assert result.slug == "qianchuan"
    assert result.matched_rule.startswith("title:")


def test_doudian_title_keyword_routes_to_mall():
    item = {"title": "服务商抖店服务市场入驻与合作指南", "tags": ["头部作者"]}
    result = route_library(item)
    assert result.slug == "mall"
    assert result.matched_rule.startswith("title:")


def test_unknown_item_falls_back_to_general():
    item = {"title": "2022新版创作者口碑分解读-合集", "tags": []}
    result = route_library(item)
    assert result.slug == FALLBACK_SLUG
    assert result.matched_rule == "fallback"


def test_all_601_manifest_items_routed_with_expected_distribution():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"]
    assert len(items) == 601
    distribution: dict[str, int] = {}
    for item in items:
        slug = route_library(item).slug
        distribution[slug] = distribution.get(slug, 0) + 1
    assert distribution == EXPECTED_DISTRIBUTION
```

- [ ] **Step 2: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rag.library_routing'`

- [ ] **Step 3: 实现归类器**

```python
# backend/app/services/rag/library_routing.py
"""知识库归类器：素材 → 8 个专业库的确定性路由（唯一事实源）。

规则优先级（spec 2026-09-17-knowledge-library-split-design.md §5）：
1. 规则类素材（classify_manifest_item == "rules"）→ 平台规则
2. 官方标签命中「案例-行业」→ 行业案例
3. 官方标签依次：千川投放 → 直播运营 → 短视频与内容 → 商城与商品卡 → 达人与大促
4. 标签未命中 → 标题关键词按同样顺序
5. 都不命中 → 课程与通用
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.rag.ingest import classify_manifest_item


@dataclass(frozen=True)
class LibrarySeed:
    slug: str
    id: uuid.UUID
    name: str
    description: str
    kind: str


LIBRARY_SEEDS: tuple[LibrarySeed, ...] = (
    LibrarySeed(
        "qianchuan",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000101"),
        "千川投放",
        "巨量千川投放、出价、流量获取与搜索运营方法论",
        "industry",
    ),
    LibrarySeed(
        "live",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000102"),
        "直播运营",
        "直播间运营方法与直播经营案例",
        "industry",
    ),
    LibrarySeed(
        "short-video",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000103"),
        "短视频与内容",
        "短视频/图文内容运营、素材制作与人设打造",
        "industry",
    ),
    LibrarySeed(
        "mall",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000104"),
        "商城与商品卡",
        "商城、店铺、商品卡与商品优化",
        "industry",
    ),
    LibrarySeed(
        "influencer",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000105"),
        "达人与大促",
        "达人合作、联盟、大促活动与消费者运营",
        "industry",
    ),
    LibrarySeed(
        "industry-case",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000106"),
        "行业案例",
        "分行业商家经营案例（生鲜/个护家清/食品饮料/珠宝文玩/智能家居/美妆/品牌商家）",
        "industry",
    ),
    LibrarySeed(
        "platform-rules",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000107"),
        "平台规则",
        "平台规则、协议、标准、细则与公示通知",
        "rules",
    ),
    LibrarySeed(
        "general",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000108"),
        "课程与通用",
        "经营课程、操作指南与通用经营知识",
        "industry",
    ),
)

SLUG_TO_SEED: dict[str, LibrarySeed] = {seed.slug: seed for seed in LIBRARY_SEEDS}
FALLBACK_SLUG = "general"

TAG_RULES: tuple[tuple[str, str], ...] = (
    (
        "industry-case",
        r"案例-(生鲜|个护家清|食品饮料|珠宝文玩|智能家居|美妆|品牌商家|营销案例)|优秀案例",
    ),
    ("qianchuan", r"商品推广\(千川\)|流量获取|搜索运营|热点搜索优化|千川"),
    ("live", r"案例-直播运营|直播间运营"),
    ("short-video", r"案例-短视频运营|短视频运营|AIGC素材|人设打造|图文"),
    ("mall", r"店铺运营|商品优化|商城运营|案例-商城运营|货品运营|抖店运营"),
    ("influencer", r"案例-大促活动|案例-达人合作|达人合作|达人|消费者运营"),
)

TITLE_RULES: tuple[tuple[str, str], ...] = (
    ("qianchuan", r"千川|投放|出价|竞价|全域|流量|搜索|推广"),
    ("live", r"直播"),
    ("short-video", r"短视频|图文|内容|素材|种草|拍摄|剪辑|人设"),
    ("mall", r"商城|商品卡|店铺|商品|橱窗|货架|抖店"),
    ("influencer", r"达人|联盟|团长|大促|活动|会员|消费者"),
)


@dataclass(frozen=True)
class RouteResult:
    slug: str
    library_id: uuid.UUID
    library_name: str
    matched_rule: str


def _tags_text(item: dict[str, Any]) -> str:
    tags = item.get("tags") or []
    if isinstance(tags, str):
        return tags
    return " ".join(str(tag) for tag in tags)


def _result(slug: str, matched_rule: str) -> RouteResult:
    seed = SLUG_TO_SEED[slug]
    return RouteResult(
        slug=seed.slug,
        library_id=seed.id,
        library_name=seed.name,
        matched_rule=matched_rule,
    )


def route_library(item: dict[str, Any]) -> RouteResult:
    """把一条素材路由到 8 个库之一，并返回命中的规则（可审计）。"""
    title = str(item.get("title") or "")
    tags_text = _tags_text(item)
    if classify_manifest_item(item) == "rules":
        return _result("platform-rules", "category:rules")
    for slug, pattern in TAG_RULES:
        if re.search(pattern, tags_text):
            return _result(slug, f"tag:{pattern.split('|')[0]}")
    for slug, pattern in TITLE_RULES:
        if re.search(pattern, title):
            return _result(slug, f"title:{pattern.split('|')[0]}")
    return _result(FALLBACK_SLUG, "fallback")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_routing.py -v`
Expected: 7 passed（含 601 篇分布精确匹配）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/rag/library_routing.py backend/tests/test_rag_library_routing.py
git commit -m "feat(rag): 知识库归类器（8 库规则路由 + 601 篇分布测试）"
```

---

### Task 2: 拆分迁移（建 8 库 / 迁移文档 / 断言 / 删老库）

**Files:**
- Create: `backend/alembic/versions/a4b8c2d6e9f1_split_rag_libraries.py`
- Test: `backend/tests/test_rag_library_split_migration.py`

**Interfaces:**
- Consumes: `LIBRARY_SEEDS`、`route_library`（Task 1）
- Produces: 数据库状态 —— 8 个库存在、老库不存在、全部文档归属 8 库之一

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_library_split_migration.py
import uuid

import pytest
from sqlalchemy import func, select, text

from app.db.session import async_session_factory
from app.models.rag import RagDocument, RagLibrary
from app.services.rag.library_routing import LIBRARY_SEEDS

OLD_LIBRARY_ID = uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000001")


@pytest.mark.asyncio
async def test_eight_libraries_exist_after_migration():
    async with async_session_factory() as session:
        names = (await session.execute(select(RagLibrary.name))).scalars().all()
    for seed in LIBRARY_SEEDS:
        assert seed.name in names


@pytest.mark.asyncio
async def test_old_default_library_is_deleted():
    async with async_session_factory() as session:
        library = await session.get(RagLibrary, OLD_LIBRARY_ID)
    assert library is None


@pytest.mark.asyncio
async def test_no_orphan_documents():
    async with async_session_factory() as session:
        orphan = (
            await session.execute(
                select(func.count())
                .select_from(RagDocument)
                .where(RagDocument.library_id == OLD_LIBRARY_ID)
            )
        ).scalar_one()
    assert orphan == 0


@pytest.mark.asyncio
async def test_every_document_belongs_to_one_of_eight_libraries():
    ids = [seed.id for seed in LIBRARY_SEEDS]
    async with async_session_factory() as session:
        outside = (
            await session.execute(
                select(func.count())
                .select_from(RagDocument)
                .where(RagDocument.library_id.notin_(ids))
            )
        ).scalar_one()
    assert outside == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_split_migration.py -v`
Expected: FAIL（8 库尚不存在、老库仍存在）

- [ ] **Step 3: 写迁移**

```python
# backend/alembic/versions/a4b8c2d6e9f1_split_rag_libraries.py
"""split rag libraries into eight routed libraries

Revision ID: a4b8c2d6e9f1
Revises: f3a1c7d9e2b4
Create Date: 2026-09-17
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "a4b8c2d6e9f1"
down_revision = "f3a1c7d9e2b4"
branch_labels = None
depends_on = None

OLD_LIBRARY_ID = uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000001")
OLD_LIBRARY_NAME = "行业知识库"
OLD_LIBRARY_DESCRIPTION = "抖音电商官方方法论、投放手册与运营白皮书"
REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest.json"

INSERT_LIBRARY = sa.text(
    "INSERT INTO rag_libraries (id, name, description, kind, visibility, retrieval_enabled)"
    " VALUES (:id, :name, :description, :kind, 'admins_only', true)"
    " ON CONFLICT (id) DO NOTHING"
)


def _manifest_index() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    payload = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    return {
        str(item.get("title") or ""): item
        for item in items or []
        if isinstance(item, dict)
    }


def upgrade() -> None:
    from app.services.rag.library_routing import LIBRARY_SEEDS, route_library

    bind = op.get_bind()
    for seed in LIBRARY_SEEDS:
        bind.execute(
            INSERT_LIBRARY,
            {
                "id": seed.id,
                "name": seed.name,
                "description": seed.description,
                "kind": seed.kind,
            },
        )

    manifest = _manifest_index()
    rows = bind.execute(sa.text("SELECT id, title, library_id FROM rag_documents")).all()
    for doc_id, title, library_id in rows:
        if library_id != OLD_LIBRARY_ID:
            continue
        item = manifest.get(str(title)) or {"title": title, "tags": []}
        route = route_library(item)
        bind.execute(
            sa.text("UPDATE rag_documents SET library_id = :library_id WHERE id = :doc_id"),
            {"library_id": route.library_id, "doc_id": doc_id},
        )

    remaining = bind.execute(
        sa.text("SELECT count(*) FROM rag_documents WHERE library_id = :library_id"),
        {"library_id": OLD_LIBRARY_ID},
    ).scalar_one()
    if remaining:
        raise RuntimeError(f"老库仍有 {remaining} 篇文档引用，中止删除")

    bind.execute(
        sa.text("DELETE FROM rag_libraries WHERE id = :library_id"),
        {"library_id": OLD_LIBRARY_ID},
    )


def downgrade() -> None:
    from app.services.rag.library_routing import LIBRARY_SEEDS

    bind = op.get_bind()
    bind.execute(
        INSERT_LIBRARY,
        {
            "id": OLD_LIBRARY_ID,
            "name": OLD_LIBRARY_NAME,
            "description": OLD_LIBRARY_DESCRIPTION,
            "kind": "industry",
        },
    )
    ids = [seed.id for seed in LIBRARY_SEEDS]
    bind.execute(
        sa.text(
            "UPDATE rag_documents SET library_id = :old_id"
            " WHERE library_id = ANY(:new_ids)"
        ),
        {"old_id": OLD_LIBRARY_ID, "new_ids": ids},
    )
```

- [ ] **Step 4: 执行迁移并验证**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head`
Expected: 输出 `Running upgrade f3a1c7d9e2b4 -> a4b8c2d6e9f1, split rag libraries into eight routed libraries`

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_split_migration.py -v`
Expected: 4 passed

- [ ] **Step 5: 校验迁移可逆（改回再改回）**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m alembic downgrade -1`
Expected: 无报错；老库「行业知识库」重新出现且文档全部指回

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head`
Expected: 再次无报错（8 库重新生效）

- [ ] **Step 6: 提交**

```bash
git add backend/alembic/versions/a4b8c2d6e9f1_split_rag_libraries.py backend/tests/test_rag_library_split_migration.py
git commit -m "feat(rag): 知识库拆分迁移（建 8 库 + 文档路由 + 删老库，可逆）"
```

---

### Task 3: 路由导入（worker 支持 + CLI）

**Files:**
- Modify: `backend/app/workers/rag_ingest_worker.py:69-127`（`_process_import_job`）
- Create: `backend/scripts/rag_split_import.py`
- Test: `backend/tests/test_rag_split_import.py`

**Interfaces:**
- Consumes: `route_library`（Task 1）、`RagRepository.create_job(**fields)`、`rag_jobs.payload`
- Produces: 任务载荷约定 —— `payload = {"scope": str, "category": str | None, "routed": True, "markdown_root": str, "items": list[dict]}`；`job.library_id` 为兜底库（`general`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_split_import.py
import uuid
from types import SimpleNamespace

import pytest

from app.services.rag.library_routing import SLUG_TO_SEED
from app.workers.rag_ingest_worker import _process_import_job


class FakeRepo:
    def __init__(self):
        self.ingested: list[tuple[str, uuid.UUID]] = []
        self.updates: list[dict] = []

    async def get_document_by_sha256(self, sha256):
        return None

    async def update_job(self, job_id, **fields):
        self.updates.append(fields)
        return None


@pytest.mark.asyncio
async def test_routed_job_sends_each_item_to_its_library(monkeypatch):
    captured: list[tuple[str, uuid.UUID]] = []

    async def fake_ingest_one(repo, provider, **kwargs):
        captured.append((kwargs["title"], kwargs["library_id"]))
        return SimpleNamespace(id=uuid.uuid4()), 3

    monkeypatch.setattr(
        "app.workers.rag_ingest_worker.ingest_one", fake_ingest_one
    )

    repo = FakeRepo()
    job = SimpleNamespace(
        id=uuid.uuid4(),
        library_id=SLUG_TO_SEED["general"].id,
        created_by=None,
    )
    items = [
        {"title": "巨量千川直播全域投放使用宝典", "tags": ["商品推广(千川)"], "file": "a.md", "sha256": "a" * 64},
        {"title": "商家申诉举证标准", "tags": ["规则解读"], "file": "b.md", "sha256": "b" * 64},
        {"title": "服务商抖店服务市场入驻与合作指南", "tags": [], "file": "c.md", "sha256": "c" * 64},
    ]
    payload = {"routed": True, "markdown_root": "C:/tmp", "items": items}

    await _process_import_job(repo, provider=None, job=job, payload=payload, processed=0)

    assert captured == [
        ("巨量千川直播全域投放使用宝典", SLUG_TO_SEED["qianchuan"].id),
        ("商家申诉举证标准", SLUG_TO_SEED["platform-rules"].id),
        ("服务商抖店服务市场入驻与合作指南", SLUG_TO_SEED["general"].id),
    ]


@pytest.mark.asyncio
async def test_non_routed_job_still_uses_job_library(monkeypatch):
    captured: list[uuid.UUID] = []

    async def fake_ingest_one(repo, provider, **kwargs):
        captured.append(kwargs["library_id"])
        return SimpleNamespace(id=uuid.uuid4()), 1

    monkeypatch.setattr(
        "app.workers.rag_ingest_worker.ingest_one", fake_ingest_one
    )

    target = SLUG_TO_SEED["live"].id
    repo = FakeRepo()
    job = SimpleNamespace(id=uuid.uuid4(), library_id=target, created_by=None)
    items = [{"title": "直播间运营白皮书", "tags": [], "file": "d.md", "sha256": "d" * 64}]

    await _process_import_job(
        repo, provider=None, job=job, payload={"markdown_root": "C:/tmp", "items": items}, processed=0
    )

    assert captured == [target]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_split_import.py -v`
Expected: FAIL — 第二个断言失败（当前实现只按 `job.library_id` 入库）

- [ ] **Step 3: 修改 worker 支持按条路由**

在 `backend/app/workers/rag_ingest_worker.py` 顶部 import 区加入：

```python
from app.services.rag.library_routing import route_library
```

把 `_process_import_job` 中 `for item in items:` 循环体替换为：

```python
    routed = bool(payload.get("routed"))
    for item in items:
        file_name = str(item.get("file") or "")
        try:
            target_library_id = (
                route_library(item).library_id if routed else job.library_id
            )
            path = markdown_root / file_name
            sha256 = str(item.get("sha256") or "").strip()
            if not sha256:
                sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            existing = await repo.get_document_by_sha256(sha256)
            if existing is not None and existing.status == "ready":
                # 已入库且就绪：同库或他库都跳过（内容已在库里）
                processed += 1
                await repo.update_job(job.id, processed=processed, error_message=last_error)
                continue
            if existing is not None and existing.library_id == target_library_id:
                # 同库但未就绪（failed/processing/pending）：复用该文档重新入库，避免被 sha256 卡死
                await ingest_one(
                    repo,
                    provider,
                    library_id=target_library_id,
                    title=str(item.get("title") or file_name or "未命名文档"),
                    sha256=sha256,
                    path=path,
                    publisher=item.get("source_site"),
                    doc_type=str(item.get("category") or "industry_methodology"),
                    created_by=job.created_by,
                    doc=existing,
                )
            elif existing is None:
                await ingest_one(
                    repo,
                    provider,
                    library_id=target_library_id,
                    title=str(item.get("title") or file_name or "未命名文档"),
                    sha256=sha256,
                    path=path,
                    publisher=item.get("source_site"),
                    doc_type=str(item.get("category") or "industry_methodology"),
                    created_by=job.created_by,
                )
            # existing 属于其它库：跳过（sha256 全局唯一）
        except Exception as exc:  # noqa: BLE001
            failures += 1
```

（`failures`/`last_error`/循环尾部的原有错误处理保持不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_split_import.py tests/test_rag_ingest_worker.py -v`
Expected: 全部 passed（新测试 + 原 worker 测试无回归）

- [ ] **Step 5: 写导入 CLI**

```python
# backend/scripts/rag_split_import.py
"""把采集素材按归类器分派到 8 个专业库。

用法（在 backend 目录下运行）：
    python -m scripts.rag_split_import --scope all --dry-run
    python -m scripts.rag_split_import --scope all
    python -m scripts.rag_split_import --scope core --category methodology

说明：真正的入库由 rag_ingest_worker 消费本命令创建的路由导入任务完成，
进度可在「知识库管理 → 库详情 → 数据集」查看；重复执行按 sha256 幂等。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_ROOT = REPO_ROOT / "var" / "kb_industry"
MANIFESTS = {
    "all": KB_ROOT / "manifest" / "manifest.json",
    "core": KB_ROOT / "manifest" / "manifest-core.json",
}
MARKDOWN_ROOT = KB_ROOT / "markdown"


def _load_items(scope: str, category: str | None, limit: int | None) -> list[dict]:
    from app.services.rag.ingest import filter_manifest_items, load_manifest_items

    manifest = MANIFESTS[scope]
    if not manifest.exists():
        raise SystemExit(f"[错误] 素材清单不存在：{manifest}")
    items = filter_manifest_items(load_manifest_items(manifest), category)
    if limit is not None:
        items = items[: max(limit, 0)]
    return items


def _print_distribution(items: list[dict]) -> None:
    from app.services.rag.library_routing import route_library

    counter: Counter[str] = Counter()
    for item in items:
        route = route_library(item)
        counter[f"{route.library_name}（{route.slug}）"] += 1
    print(f"[路由] 素材 {len(items)} 篇：")
    for name, count in counter.most_common():
        print(f"  {name}: {count} 篇")


async def _create_job(items: list[dict], scope: str, category: str | None) -> str:
    from app.db.session import async_session_factory
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.library_routing import SLUG_TO_SEED

    async with async_session_factory() as session:
        repo = RagRepository(session)
        library = await repo.get_library(SLUG_TO_SEED["general"].id)
        if library is None:
            raise SystemExit("[错误] 「课程与通用」库不存在，请先执行 alembic upgrade head")
        job = await repo.create_job(
            library_id=library.id,
            kind="import",
            status="queued",
            total=len(items),
            payload={
                "scope": scope,
                "category": category,
                "routed": True,
                "markdown_root": str(MARKDOWN_ROOT),
                "items": items,
            },
            created_by=None,
        )
        return str(job.id)


def main() -> int:
    parser = argparse.ArgumentParser(description="按归类器分派采集素材到 8 个专业库")
    parser.add_argument("--scope", choices=sorted(MANIFESTS), default="all")
    parser.add_argument("--category", default=None, choices=[None, "methodology", "rules", "other"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只打印路由分布，不创建任务")
    args = parser.parse_args()

    items = _load_items(args.scope, args.category, args.limit)
    if not items:
        print("[错误] 没有符合条件的素材")
        return 1
    _print_distribution(items)
    if args.dry_run:
        print("[干跑] 未创建任务")
        return 0

    job_id = asyncio.run(_create_job(items, args.scope, args.category))
    print(f"[任务] 已创建路由导入任务 job_id={job_id}（共 {len(items)} 篇，由 rag_ingest_worker 消费）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 干跑验证路由分布**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_split_import --scope all --dry-run`
Expected: 打印 8 行分布，篇数与 spec §4 一致（80/21/25/37/65/57/254/62）

- [ ] **Step 7: 提交**

```bash
git add backend/app/workers/rag_ingest_worker.py backend/scripts/rag_split_import.py backend/tests/test_rag_split_import.py
git commit -m "feat(rag): 路由导入（worker 按条分库 + rag_split_import CLI）"
```

---

### Task 4: 常量清理 + 按库名检索 + DSH 工具与技能

**Files:**
- Modify: `backend/app/models/rag.py:23`（删除 `DEFAULT_LIBRARY_ID`）
- Modify: `backend/app/schemas/rag.py`（`RagSearchRequest` 增加 `library`）
- Modify: `backend/app/api/rag.py:322-349`（`search` 支持按库名）
- Modify: `dsh-platform/packages/server-connector/src/index.ts`（`knowledge_search` 增加 `library`）
- Modify: `dsh-platform/skills-template/knowledge-search/SKILL.md`
- Test: `backend/tests/test_rag_api.py`（追加用例）、`dsh-platform/packages/server-connector/tests/connector.test.ts`（追加用例）

**Interfaces:**
- Consumes: `RagRepository.get_library_by_name(name) -> RagLibrary | None`；`RagSearchService.search(query, top_k, library_id=..., include_disabled_libraries=...)`；命中项已含 `library_name` 字段（`_hit_payload`）
- Produces: `POST /api/rag/search` 请求体新增可选 `library: str`（库名）；connector `knowledge_search` 入参新增可选 `library: string`

- [ ] **Step 1: 写失败测试（后端，追加到 `backend/tests/test_rag_api.py`）**

```python
@pytest.mark.anyio
async def test_search_api_accepts_library_name(test_db, admin_client):
    """按库名检索：library="平台规则" 只返回该库命中。"""
    import numpy as np

    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        rules = await repo.create_library(name="平台规则")
        other = await repo.create_library(name="千川投放")
        doc_rules = await repo.create_document(
            title="商家申诉举证标准", sha256="libname1", status="ready", library_id=rules.id
        )
        await repo.add_chunks(
            doc_rules.id, [("s", "举证材料要求", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)]
        )
        doc_other = await repo.create_document(
            title="千川投放手册", sha256="libname2", status="ready", library_id=other.id
        )
        await repo.add_chunks(
            doc_other.id, [("s", "出价策略", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)]
        )

    response = await admin_client.post(
        "/api/rag/search", json={"query": "举证", "top_k": 5, "library": "平台规则"}
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items, "按库名检索应有命中"
    assert all(item["library_name"] == "平台规则" for item in items)


@pytest.mark.anyio
async def test_search_api_unknown_library_name_returns_404(test_db, admin_client):
    response = await admin_client.post(
        "/api/rag/search", json={"query": "举证", "library": "不存在的库"}
    )
    assert response.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_search_library_filter.py -v`
Expected: FAIL（`library` 字段被忽略或 422）

- [ ] **Step 3: 实现按库名检索**

`backend/app/schemas/rag.py` 的 `RagSearchRequest` 增加字段：

```python
    library: str | None = Field(default=None, max_length=120, description="按知识库名称过滤")
```

`backend/app/api/rag.py` 的 `search` 中，在调用 `service.search` 前解析库名：

```python
    repo = RagRepository(db)
    library_id = data.library_id
    if library_id is None and data.library:
        library = await repo.get_library_by_name(data.library)
        if library is None:
            raise ApiError(
                status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在"
            )
        library_id = library.id
```

并把 `service.search(...)` 的 `library_id=data.library_id` 改为 `library_id=library_id`。

`backend/app/models/rag.py`：删除第 23 行 `DEFAULT_LIBRARY_ID = uuid.UUID(...)`（先确认全仓已无引用）。

Run: `Select-String -Path backend\app\**\*.py,backend\scripts\*.py -Pattern 'DEFAULT_LIBRARY_ID'`
Expected: 无输出（迁移文件内的同名常量已自带字面量，不受影响）

- [ ] **Step 4: 运行后端测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_search_library_filter.py tests/test_rag_api.py -v`
Expected: 全部 passed

- [ ] **Step 5: 写失败测试（connector，追加到 `dsh-platform/packages/server-connector/tests/connector.test.ts` 的 `describe('knowledge_search')`）**

```ts
  it('forwards the library filter to /api/rag/search', async () => {
    const fetchFn = stubFetch({ data: { items: [] } })
    const { ctx, register } = makeCtx()
    apply(ctx as never, CONFIG as never)
    const tools = toolsFrom(register)

    await tools.knowledge_search.execute({
      query: '平台规则对发货时效的要求',
      top_k: 5,
      library: '平台规则',
    })

    const { init } = lastCall(fetchFn)
    expect(JSON.parse(String(init.body))).toMatchObject({
      query: '平台规则对发货时效的要求',
      top_k: 5,
      library: '平台规则',
    })
  })
```

- [ ] **Step 6: 实现 connector 侧**

`dsh-platform/packages/server-connector/src/index.ts`：

```ts
interface KnowledgeSearchInput {
  query: string;
  top_k?: number;
  library?: string;
}
```

```ts
        library: {
          type: 'string',
          description:
            '可选：限定知识库名称。可选值：千川投放、直播运营、短视频与内容、商城与商品卡、达人与大促、行业案例、平台规则、课程与通用。不传则跨全部库检索。',
        },
```

在 `execute` 构造请求体处加入 `library: args.library`（仅在非空时发送）。

- [ ] **Step 7: 运行 connector 测试 + 构建**

Run（workdir=`dsh-platform/packages/server-connector`）: `pnpm test`
Expected: 全部 passed（新增 1 条 + 原有）

Run: `pnpm build`
Expected: 无错误，`lib/index.js` 重新产出（提交构建产物）

- [ ] **Step 8: 更新技能模板**

`dsh-platform/skills-template/knowledge-search/SKILL.md` 的 Tool reference 段替换为：

```markdown
- `knowledge_search(query, top_k=5, library?)` — semantic search over the platform industry knowledge base. `query` is a natural-language question or keyword; `top_k` caps the number of returned chunks (1..20, default 5); `library` optionally restricts the search to one library.
- Libraries: `千川投放`（投放/出价/流量/搜索）、`直播运营`、`短视频与内容`、`商城与商品卡`、`达人与大促`、`行业案例`（分行业案例）、`平台规则`（规则/协议/标准/细则）、`课程与通用`（课程/通用）。
- 选库建议：问合规/准入/处罚 → `平台规则`；问投放与出价 → `千川投放`；问直播玩法 → `直播运营`；问内容/短视频 → `短视频与内容`；问商城/商品卡 → `商城与商品卡`；问达人/大促 → `达人与大促`；问某行业案例 → `行业案例`；不确定时不要传 `library`（跨库检索）。
```

- [ ] **Step 9: 提交**

```bash
git add backend/app/models/rag.py backend/app/schemas/rag.py backend/app/api/rag.py backend/tests/test_rag_api.py dsh-platform/packages/server-connector/src/index.ts dsh-platform/packages/server-connector/tests/connector.test.ts dsh-platform/packages/server-connector/lib dsh-platform/skills-template/knowledge-search/SKILL.md
git commit -m "feat(rag): 按库名检索 + knowledge_search 支持选库 + 技能模板 8 库说明"
```

---

### Task 5: 前端库卡片按篇数降序

**Files:**
- Modify: `frontend/src/components/knowledge/library-grid.tsx:24-33`
- Test: `frontend/src/components/knowledge/library-grid.test.tsx`（追加用例）

**Interfaces:**
- Consumes: `ragApi.listLibraries(): Promise<RagLibrary[]>`（`RagLibrary.stats.doc_count: number`）
- Produces: 列表按 `doc_count` 降序渲染

- [ ] **Step 1: 写失败测试**

在 `frontend/src/components/knowledge/library-grid.test.tsx` 追加（沿用文件内已有的 `LIB` 常量与 `renderGrid()` 辅助函数）：

```tsx
  it("库卡片按文档数降序排列", async () => {
    mockListLibraries.mockResolvedValue([
      { ...LIB, id: "lib-small", name: "小库", stats: { ...LIB.stats, doc_count: 3 } },
      { ...LIB, id: "lib-big", name: "大库", stats: { ...LIB.stats, doc_count: 80 } },
    ]);
    const { container } = renderGrid();
    await waitFor(() => expect(screen.getByText("大库")).toBeTruthy());
    const text = container.textContent ?? "";
    expect(text.indexOf("大库")).toBeLessThan(text.indexOf("小库"));
  });
```

- [ ] **Step 2: 运行测试确认失败**

Run（workdir=`frontend`）: `npx vitest run src/components/knowledge/library-grid.test.tsx`
Expected: FAIL（顺序为 "小库" 在前）

- [ ] **Step 3: 实现排序**

`frontend/src/components/knowledge/library-grid.tsx` 的 `load`：

```tsx
  const load = useCallback(async () => {
    try {
      const data = await ragApi.listLibraries();
      setLibraries(
        [...data].sort((a, b) => b.stats.doc_count - a.stats.doc_count),
      );
      setError("");
    } catch {
      setError("加载知识库列表失败");
    } finally {
      setInitialLoading(false);
    }
  }, []);
```

- [ ] **Step 4: 运行测试确认通过**

Run（workdir=`frontend`）: `npx vitest run src/components/knowledge/library-grid.test.tsx`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/knowledge/library-grid.tsx frontend/src/components/knowledge/library-grid.test.tsx
git commit -m "feat(knowledge): 库卡片按文档数降序排列"
```

---

### Task 6: 分配报告生成

**Files:**
- Create: `backend/scripts/rag_library_report.py`
- Test: `backend/tests/test_rag_library_report.py`
- Output: `docs/rag-eval/library-assignment.md`（生成物，随任务提交）

**Interfaces:**
- Consumes: `load_manifest_items(path)`、`route_library(item)`（Task 1）
- Produces: `build_report(items) -> list[ReportRow]`（`ReportRow(title, library_name, matched_rule)`）；`render_markdown(rows) -> str`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_rag_library_report.py
import json
from pathlib import Path

from scripts.rag_library_report import build_report, render_markdown

MANIFEST = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "manifest" / "manifest.json"


def test_report_covers_all_items_with_library_and_rule():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"]
    rows = build_report(items)
    assert len(rows) == 601
    assert all(row.library_name for row in rows)
    assert all(row.matched_rule for row in rows)


def test_markdown_has_one_line_per_document():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"][:5]
    text = render_markdown(build_report(items))
    assert text.startswith("# 知识库分配报告")
    assert text.count("| ") >= 5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.rag_library_report'`

- [ ] **Step 3: 实现报告脚本**

```python
# backend/scripts/rag_library_report.py
"""生成知识库分配报告：每篇素材 → 归属库 → 命中规则。

用法（在 backend 目录下运行）：
    python -m scripts.rag_library_report
输出：docs/rag-eval/library-assignment.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest.json"
OUTPUT = REPO_ROOT / "docs" / "rag-eval" / "library-assignment.md"


@dataclass(frozen=True)
class ReportRow:
    title: str
    library_name: str
    matched_rule: str


def build_report(items: list[dict]) -> list[ReportRow]:
    from app.services.rag.library_routing import LIBRARY_SEEDS, route_library

    order = {seed.name: index for index, seed in enumerate(LIBRARY_SEEDS)}
    rows = []
    for item in items:
        route = route_library(item)
        rows.append(
            ReportRow(
                title=str(item.get("title") or ""),
                library_name=route.library_name,
                matched_rule=route.matched_rule,
            )
        )
    rows.sort(key=lambda row: (order.get(row.library_name, 99), row.title))
    return rows


def render_markdown(rows: list[ReportRow]) -> str:
    lines = [
        "# 知识库分配报告",
        "",
        "由 `backend/scripts/rag_library_report.py` 生成，规则见 "
        "`docs/superpowers/specs/2026-09-17-knowledge-library-split-design.md` §5。",
        "",
        f"共 {len(rows)} 篇。",
        "",
        "| 篇名 | 归属库 | 命中规则 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        title = row.title.replace("|", "\\|")
        lines.append(f"| {title} | {row.library_name} | `{row.matched_rule}` |")
    lines.append("")
    return "\n".join(lines)


async def _print_stats() -> None:
    from sqlalchemy import text

    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT l.name, count(d.id), coalesce(sum(d.chunk_count), 0)"
                    " FROM rag_libraries l"
                    " LEFT JOIN rag_documents d ON d.library_id = l.id AND d.status = 'ready'"
                    " GROUP BY l.name ORDER BY count(d.id) DESC"
                )
            )
        ).all()
        statuses = (
            await session.execute(
                text("SELECT status, count(*) FROM rag_documents GROUP BY status")
            )
        ).all()
    print("[统计] 各库就绪文档/块数：")
    for name, docs, chunks in rows:
        print(f"  {name}: {docs} 篇 / {chunks} 块")
    print("[统计] 文档状态分布：")
    for status, count in statuses:
        print(f"  {status}: {count}")


def main() -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="生成知识库分配报告 / 打印分库统计")
    parser.add_argument("--stats", action="store_true", help="只打印数据库中各库统计，不写报告")
    args = parser.parse_args()
    if args.stats:
        asyncio.run(_print_stats())
        return 0

    from app.services.rag.ingest import load_manifest_items

    rows = build_report(load_manifest_items(MANIFEST))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_markdown(rows), encoding="utf-8")
    print(f"[报告] {len(rows)} 篇 → {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试并生成报告**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_library_report.py -v`
Expected: 2 passed

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_library_report`
Expected: `[报告] 601 篇 → ...\docs\rag-eval\library-assignment.md`

- [ ] **Step 5: 提交**

```bash
git add backend/scripts/rag_library_report.py backend/tests/test_rag_library_report.py docs/rag-eval/library-assignment.md
git commit -m "feat(rag): 知识库分配报告生成（601 篇逐篇可审计）"
```

---

### Task 7: 端到端验收（真实数据）

**Files:**
- Create: `docs/verification/knowledge-library-split-checklist.md`

**Interfaces:**
- Consumes: 前 6 个任务的全部产出
- Produces: 验收证据（命令输出 + SQL 结果），落盘为清单文档

- [ ] **Step 1: 确认服务在线并执行导入**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\status-all.ps1`
Expected: backend 8010 / frontend 3001 / rag-ingest-worker alive

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_split_import --scope all`（workdir=`backend`）
Expected: 打印 `[任务] 已创建路由导入任务 job_id=...（共 601 篇...）`

- [ ] **Step 2: 等待 worker 处理完成并核对分库结果**

Run（workdir=`backend`，每隔 1~2 分钟重复执行，直到「文档状态分布」中 `pending`/`processing` 为 0）：

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_library_report --stats`
Expected: 8 行分库统计，就绪篇数与 spec §4 一致（千川投放 80 / 直播运营 21 / 短视频与内容 25 / 商城与商品卡 37 / 达人与大促 65 / 行业案例 57 / 平台规则 254 / 课程与通用 62），状态分布中 `failed: 0`

- [ ] **Step 3: 检索抽查（按库名）**

```powershell
$body = '{"query":"千川全域投放出价策略","top_k":3,"library":"千川投放"}'
Invoke-WebRequest -Uri "http://127.0.0.1:8010/api/rag/search" -Method Post -ContentType "application/json" -Body $body -UseBasicParsing
```

Expected: 200，命中标题来自千川投放库

```powershell
$body = '{"query":"商家准入细则","top_k":3,"library":"平台规则"}'
Invoke-WebRequest -Uri "http://127.0.0.1:8010/api/rag/search" -Method Post -ContentType "application/json" -Body $body -UseBasicParsing
```

Expected: 200，命中标题来自平台规则库

- [ ] **Step 4: DSH 侧验收（需重启实例加载新 connector 与技能）**

按记忆 #963：先杀掉旧实例进程，再调用重启接口（否则「收养」逻辑不会加载新代码）：

```powershell
$pid = (Get-NetTCPConnection -LocalPort 3163 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($pid) { Stop-Process -Id $pid -Force }
```

然后浏览器打开 `http://localhost:3001/agent`（admin / ChangeMe-Strong1），问：
「平台规则里对商家发货时效的要求是什么？」
Expected: 回复带 `source_url` 来源，且检索命中的是「平台规则」库内容

- [ ] **Step 5: 浏览器验收（清单 6 条）**

对照 spec §9 验收线逐条核对：① 8 张库卡片数字；② 老库已消失；③ 按库检索命中；④ 601 篇 0 失败；⑤ DSH 规则问答；⑥ 报告抽 10 篇。

- [ ] **Step 6: 回归测试**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/ -k "rag" -q`（workdir=`backend`）
Expected: 全部 passed

Run（workdir=`frontend`）: `npx vitest run src/components/knowledge`
Expected: 全部 passed

- [ ] **Step 7: 落盘验收清单并提交**

```bash
git add docs/verification/knowledge-library-split-checklist.md
git commit -m "docs(rag): 知识库多库拆分验收清单与实测结果"
```

---

## 附：任务依赖与并行建议

- Task 1 是其余任务的前置（先做，不可并行）。
- Task 2 依赖 Task 1；Task 5、Task 6 只依赖 Task 1 → **可与 Task 2/3 并行**。
- Task 3、Task 4 依赖 Task 1（互不共享文件，可并行）。
- Task 7 依赖全部，最后串行执行。
