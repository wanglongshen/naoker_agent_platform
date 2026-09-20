# 二期：广告营销行业知识库（RAG）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让平台具备「行业知识检索」能力：把已采集的 226 篇官方方法论（`var/kb_industry/`，约 625 万字）解析、切分、向量化入库，DSH 通过 `knowledge_search` 工具检索并带来源引用；以 100 问黄金集 recall@5 ≥90% 验收。

**Architecture:** 新增 `backend/app/services/rag/`（parsing / chunking / embedding / store / ingest / search）与 `rag_documents`、`rag_chunks`、`rag_eval_set` 三张表；检索走 `POST /api/rag/search`（`X-Platform-Token` 双身份），DSH connector 新增第 4 个工具 `knowledge_search` + `knowledge-search/SKILL.md`；管理页 `/knowledge`（super_admin）复用现有表格/抽屉组件。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic + PostgreSQL 18 + numpy（向量检索）+ sentence-transformers（本地 embedding，可切 HTTP）+ 抖音官方素材（`var/kb_industry/`）+ DSH connector（TypeScript）+ Next.js 16 / AntD。

## Global Constraints

- **不做用户私有库**：只做平台级行业知识库；检索面对全部登录用户开放，管理页仅 `super_admin`（复用现有 super_admin 内联门，不新增权限码，12 权限体系一字不动）。
- **不新增 Docker 依赖**：本机无 Docker（实测 `docker: NOT FOUND`），且本机 PostgreSQL 18.4 无 pgvector 扩展（实测 `pg_available_extensions` 无 `vector`，pgvector 官方 Windows 安装需 MSVC + nmake）。因此向量检索采用 **bytea + 内存 numpy 精确检索**（见「决策 D1」）；生产如需 pgvector 走后续升级任务，接口不变。
- 素材只采公开发行内容、保留 `source_url`、仅内部知识库使用不公开再分发（`var/kb_industry/README.md:5-46`）；`var/kb_industry/` 已被 `.gitignore` 忽略，素材不进 git。
- 统一响应壳 `success(request, ...)`；写操作带 `Depends(require_csrf)`；管理页依赖 `require_super_admin`（`dependencies.py:113`）。
- 单测不下载模型、不连外网：embedding 用 fake provider；真实模型只在 T3 的 opt-in 冒烟与 T8 评测中跑。
- 每个任务提交前 `git diff --cached --name-only` 核对，只 add 自己的精确路径。
- 运行测试：`cd backend` 后 `X:\python\anaconda\envs\01-rbac\python.exe -m pytest <path> -q`；connector：`cd dsh-platform/packages/server-connector` 后 `pnpm test`。

### 决策记录（偏离已批准 spec 的部分，实施前需用户确认）

- **D1 向量检索实现**：spec §3 要求 pgvector + HNSW（`docs/superpowers/specs/2026-09-07-dsh-platform-rebase-design.md:165`）。
  实测本机无 Docker、PG 无 pgvector 扩展、Windows 编译 pgvector 需 MSVC；而目标语料 ≈14k chunks（226 篇 ≈625 万字，512/64 切分），
  精确检索（bytea 存 float32 + numpy 余弦 top-k）内存 ≈29MB、单次查询 ≈5-10ms，**recall 100%**（优于 HNSW 近似检索），
  完全满足「P95 ≤500ms + recall@5 ≥90%」验收。故 v1 用精确检索，`VectorStore` 协议保留 `PgVectorStore` 升级位（>20 万 chunks 时切换）。
- **D2 embedding 供给**：默认本地 `bge-small-zh-v1.5`（512 维，`sentence-transformers`，pip 安装，不动系统）；
  同时提供 OpenAI 兼容 HTTP 后端（`rag_embedding_provider=http` + base_url/key/model），模型/维度走配置，切换零代码。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/models/rag.py`（新） | `rag_documents` / `rag_chunks` / `rag_eval_set` |
| `backend/app/repositories/rag_repository.py`（新） | 文档/块/评测集 CRUD 与批量写入 |
| `backend/app/services/rag/parsing.py`（新） | Quill delta JSON → Markdown/纯文本；网页正文提取（预留 trafilatura） |
| `backend/app/services/rag/chunking.py`（新） | 标题感知切分（512/64，`section_path`） |
| `backend/app/services/rag/embedding.py`（新） | `EmbeddingProvider` 协议 + 本地/HTTP 实现 |
| `backend/app/services/rag/store.py`（新） | `VectorStore` 协议 + `NumpyVectorStore`（bytea → 内存矩阵） |
| `backend/app/services/rag/ingest.py`（新） | 入库管线：manifest → parse → chunk → embed → upsert（幂等） |
| `backend/app/services/rag/search.py`（新） | 检索服务：query → embedding → top-k → 带来源的 chunks |
| `backend/app/api/rag.py`（新） | `POST /api/rag/search` + 管理 API |
| `backend/scripts/rag_ingest.py`（新） | CLI：`--manifest-core` 批量入库、`--dry-run`、`--limit` |
| `backend/scripts/rag_eval.py`（新） | 黄金集评测：recall@5、P95、报告 |
| `dsh-platform/packages/server-connector/src/index.ts`（改） | 第 4 工具 `knowledge_search` + POST 支持 |
| `dsh-platform/skills-template/knowledge-search/SKILL.md`（新） | 检索技能说明（rank 400 自动发现） |
| `frontend/src/app/(dashboard)/knowledge/page.tsx`（新） | 知识库管理页 |
| `frontend/src/components/knowledge/*`（新） | 文档列表 / 采集与入库状态 / 预览禁用 |
| `docs/verification/rag-acceptance.md`（新） | 验收结果与口径 |

**共享文件唯一属主**：`backend/app/models/__init__.py` + `backend/alembic/env.py`（T1）、`backend/app/main.py`（T5）、`dsh-platform/packages/server-connector/src/index.ts`（T6）、`frontend/src/components/layout/app-sidebar.tsx` + `frontend/src/lib/copy.ts`（T7）。

---

### Task 1: 数据层 + 向量存储协议（含 pgvector 决策落地）

**Files:**
- Create: `backend/app/models/rag.py`、`backend/app/repositories/rag_repository.py`
- Create: `backend/alembic/versions/<new>_add_rag_tables.py`
- Modify: `backend/app/models/__init__.py`、`backend/alembic/env.py`
- Create: `backend/app/services/rag/__init__.py`、`store.py`
- Test: `backend/tests/test_rag_store.py`、`backend/tests/test_rag_repository.py`

**Interfaces:**
- Produces:
  - `RagDocument`（`rag_documents`）：`id`、`title`、`doc_type`、`source_url`、`publisher`、`license_note`、`file_key`、`sha256`(unique)、`status`(`pending|ready|disabled`)、`chunk_count`、`created_by`、`created_at`、`updated_at`
  - `RagChunk`（`rag_chunks`）：`id`、`doc_id`(FK ondelete CASCADE)、`chunk_index`、`section_path`、`content`、`embedding`(bytea, float32 LE)、`embedding_dim`、`created_at`
  - `RagEvalSet`（`rag_eval_set`）：`id`、`query`、`expected_doc_ids`(JSONB)、`approved_at`、`created_by`、`created_at`
  - `VectorStore` 协议：`def upsert(chunks: list[tuple[uuid.UUID, bytes]]) -> None`、`def search(query_vector: bytes, top_k: int) -> list[tuple[uuid.UUID, float]]`、`def invalidate() -> None`
  - `NumpyVectorStore(chunk_loader: Callable[[], Awaitable[list[tuple[uuid.UUID, bytes]]]])`：首次查询懒加载为 `np.ndarray(n, dim)`，余弦相似度（向量已 L2 归一化）→ top-k
- 字段来源证据：`source_url`/`publisher`/`license_note`/`sha256` 来自 `var/kb_industry/manifest/manifest-core.json` 的 items 字段（实测样本：`id/title/file/char_count/pages_estimate/tags/view_count/update_timestamp/source_url/source_site/source_type/sha256`）；`status` 对齐现有 `file_objects.preview_status` 的状态机风格；`embedding_dim` 用于将来换模型时校验。

- [ ] **Step 1: 模型 + 迁移**（`bytea` 用 `LargeBinary`；索引 `ix_rag_chunks_doc_chunk` unique(doc_id, chunk_index)、`ix_rag_documents_status`）

- [ ] **Step 2: 写失败测试（store 用纯内存 fake loader）**

```python
# backend/tests/test_rag_store.py
from __future__ import annotations

import uuid

import numpy as np
import pytest

from app.services.rag.store import NumpyVectorStore, to_bytes


def _vec(*values: float) -> bytes:
    arr = np.array(values, dtype=np.float32)
    arr = arr / np.linalg.norm(arr)
    return to_bytes(arr)


@pytest.mark.anyio
async def test_numpy_store_returns_cosine_topk():
    ids = [uuid.uuid4() for _ in range(3)]
    rows = [
        (ids[0], _vec(1, 0, 0)),
        (ids[1], _vec(0.9, 0.1, 0)),
        (ids[2], _vec(0, 1, 0)),
    ]

    async def loader():
        return rows

    store = NumpyVectorStore(loader)
    hits = await store.search(_vec(1, 0, 0), top_k=2)
    assert [h[0] for h in hits] == [ids[0], ids[1]]
    assert hits[0][1] > hits[1][1]


@pytest.mark.anyio
async def test_numpy_store_reloads_after_invalidate():
    ids = [uuid.uuid4(), uuid.uuid4()]
    state = {"rows": [(ids[0], _vec(1, 0))]}

    async def loader():
        return state["rows"]

    store = NumpyVectorStore(loader)
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    state["rows"] = [(ids[0], _vec(1, 0)), (ids[1], _vec(0.5, 0.5))]
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1  # 未失效
    store.invalidate()
    assert len(await store.search(_vec(1, 0), top_k=5)) == 2
```

- [ ] **Step 3: 实现 `store.py`**

```python
"""向量存储：v1 用精确余弦检索（决策 D1：本机无 pgvector，语料 ≈14k chunks 精确检索更快更准）。

PgVectorStore 升级位：当 chunks > 20 万或需要 ANN 时新增实现，协议不变。
"""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable, Protocol

import numpy as np


def to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_bytes(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


class VectorStore(Protocol):
    async def search(self, query_vector: bytes, top_k: int) -> list[tuple[uuid.UUID, float]]: ...
    def invalidate(self) -> None: ...


class NumpyVectorStore:
    def __init__(self, loader: Callable[[], Awaitable[list[tuple[uuid.UUID, bytes]]]]) -> None:
        self._loader = loader
        self._ids: list[uuid.UUID] = []
        self._matrix: np.ndarray | None = None

    async def _ensure(self) -> None:
        if self._matrix is not None:
            return
        rows = await self._loader()
        self._ids = [r[0] for r in rows]
        self._matrix = (
            np.vstack([from_bytes(r[1]) for r in rows]) if rows else np.zeros((0, 1), dtype=np.float32)
        )

    async def search(self, query_vector: bytes, top_k: int) -> list[tuple[uuid.UUID, float]]:
        await self._ensure()
        if not self._ids:
            return []
        query = from_bytes(query_vector)
        scores = self._matrix @ query
        order = np.argsort(-scores)[:top_k]
        return [(self._ids[i], float(scores[i])) for i in order]

    def invalidate(self) -> None:
        self._matrix = None
        self._ids = []
```

- [ ] **Step 4: 跑绿 + 迁移校验**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_store.py tests/test_rag_repository.py -q`
Run: `X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head; X:\python\anaconda\envs\01-rbac\python.exe -m alembic heads`

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/rag.py backend/app/models/__init__.py backend/alembic/versions/<new>_add_rag_tables.py backend/alembic/env.py backend/app/repositories/rag_repository.py backend/app/services/rag/__init__.py backend/app/services/rag/store.py backend/tests/test_rag_store.py backend/tests/test_rag_repository.py
git commit -m "feat(rag): tables, repository and vector store"
```

---

### Task 2: 素材解析（Quill delta JSON → Markdown）与标题感知切分

**Files:**
- Create: `backend/app/services/rag/parsing.py`、`backend/app/services/rag/chunking.py`
- Test: `backend/tests/test_rag_parsing.py`、`backend/tests/test_rag_chunking.py`

**Interfaces:**
- Produces:
  - `def parse_source_file(path: Path) -> ParsedDoc`（`ParsedDoc(title, markdown, source_meta)`；输入是 `var/kb_industry/markdown/*.md`：前 5 行元数据头 + 其后的 Quill delta JSON）
  - `def delta_json_to_markdown(payload: dict) -> str`（`deltas` 分组内 `ops`：`insert` 文本 + `attributes.heading`（1-6）→ `#` 前缀；换行还原；`attachments` 忽略但记录）
  - `def chunk_markdown(markdown: str, *, size: int = 512, overlap: int = 64) -> list[Chunk]`（`Chunk(section_path, content, index)`：维护标题栈，段落优先，超长段落按句子边界切）
- 证据：素材实测为 `{"version":2,"deltas":{...},"attachments":[...]}`，核心 226/226 为该格式（`var/kb_industry/markdown/`，样本 `aJpo4GTEqyeH-*.md`）；设计切分参数 512/64（spec §3）。

- [ ] **Step 1: 写失败测试（用真实素材文件做夹具，若文件缺失则 skip）**

```python
# backend/tests/test_rag_parsing.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rag.parsing import delta_json_to_markdown, parse_source_file

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "markdown"


def test_delta_json_to_markdown_restores_headings_and_text():
    payload = {
        "version": 2,
        "deltas": {
            "d1": {"ops": [{"insert": "小店随心推产品手册"}, {"insert": "\n", "attributes": {"heading": 1}}]},
            "d2": {"ops": [{"insert": "全域投放包含直播与短视频两种模式。"}, {"insert": "\n"}]},
        },
        "attachments": [],
    }
    md = delta_json_to_markdown(payload)
    assert md.startswith("# 小店随心推产品手册")
    assert "全域投放包含直播与短视频两种模式。" in md


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="kb_industry 素材不在本机")
def test_parse_real_sample_yields_markdown_and_meta():
    sample = next(iter(sorted(SAMPLE_DIR.glob("*.md"))))
    doc = parse_source_file(sample)
    assert doc.title
    assert len(doc.markdown) > 500
    assert not doc.markdown.lstrip().startswith("{\"version\"")
```

```python
# backend/tests/test_rag_chunking.py
from app.services.rag.chunking import chunk_markdown


def test_chunk_keeps_section_path_and_size():
    md = "# 投放手册\n\n## 出价策略\n\n" + "出价策略说明。" * 120 + "\n\n## 预算\n\n预算建议。"
    chunks = chunk_markdown(md, size=200, overlap=20)
    assert chunks[0].section_path.startswith("投放手册")
    assert all(len(c.content) <= 240 for c in chunks)
    assert any("出价策略" in c.section_path for c in chunks)
    assert chunks[-1].section_path.endswith("预算")
```

- [ ] **Step 2: 实现**（解析：跳过前 5 行元数据；`json.loads` 失败 → 视为纯 Markdown 原文返回；切分：按 `\n\n` 段落聚合，超 size 时按 `。！？\n` 断句，overlap 用尾部字符）

- [ ] **Step 3: 跑绿 + 提交**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_parsing.py tests/test_rag_chunking.py -q`

```bash
git add backend/app/services/rag/parsing.py backend/app/services/rag/chunking.py backend/tests/test_rag_parsing.py backend/tests/test_rag_chunking.py
git commit -m "feat(rag): quill delta parsing and title-aware chunking"
```

---

### Task 3: Embedding 服务（本地 bge-small-zh-v1.5 / HTTP 可切换）

**Files:**
- Create: `backend/app/services/rag/embedding.py`
- Modify: `backend/app/core/config.py`（新增 `rag_*` 配置段）、`backend/requirements.txt`（`sentence-transformers`、`numpy`、`zstandard` 已在；`pgvector` 不装）
- Test: `backend/tests/test_rag_embedding.py`

**Interfaces:**
- Produces:
  - `class EmbeddingProvider(Protocol): dim: int; async def embed(self, texts: list[str]) -> list[bytes]`
  - `class LocalSentenceTransformerProvider(model_name, dim)`（懒加载，`normalize_embeddings=True`，`encode(..., batch_size=32)`；`asyncio.to_thread` 包装避免阻塞事件循环）
  - `class HttpEmbeddingProvider(base_url, api_key, model, dim)`（OpenAI 兼容 `POST /embeddings`）
  - `def build_embedding_provider() -> EmbeddingProvider`（读 `settings.rag_embedding_provider`）
- 配置：`rag_embedding_provider: str = "local"`、`rag_embedding_model: str = "BAAI/bge-small-zh-v1.5"`、`rag_embedding_dim: int = 512`、`rag_embedding_base_url: str = ""`、`rag_embedding_api_key: str = ""`

- [ ] **Step 1: 写失败测试（fake provider + 可注入的 fake 编码器）**

```python
# backend/tests/test_rag_embedding.py
from __future__ import annotations

import numpy as np
import pytest

from app.services.rag.embedding import LocalSentenceTransformerProvider, build_embedding_provider


@pytest.mark.anyio
async def test_local_provider_encodes_normalized_vectors(monkeypatch):
    provider = LocalSentenceTransformerProvider("fake-model", 4)

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True, batch_size=32):
            return np.array([[3.0, 0.0, 0.0, 0.0]] * len(texts), dtype=np.float32)

    monkeypatch.setattr(provider, "_load_model", lambda: FakeModel())
    vectors = await provider.embed(["a", "b"])
    assert len(vectors) == 2
    arr = np.frombuffer(vectors[0], dtype=np.float32)
    assert pytest.approx(float(np.linalg.norm(arr)), rel=1e-3) == 1.0


def test_build_provider_switchable_by_settings(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rag_embedding_provider", "http")
    monkeypatch.setattr(get_settings(), "rag_embedding_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(get_settings(), "rag_embedding_api_key", "k")
    provider = build_embedding_provider()
    assert provider.dim == 512
```

- [ ] **Step 2: 实现 + 装依赖**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pip install sentence-transformers`
（若下载/安装失败，记录并以 HTTP provider 为默认——配置项已支持，评测时改用 HTTP 后端，报告中注明。）

- [ ] **Step 3: 真实模型冒烟（opt-in，失败不阻塞）**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -c "import asyncio; from app.services.rag.embedding import build_embedding_provider; p=build_embedding_provider(); v=asyncio.run(p.embed(['投放策略'])); print(p.dim, len(v[0]))"`
Expected: `512 2048`

- [ ] **Step 4: 跑绿 + 提交**

```bash
git add backend/app/services/rag/embedding.py backend/app/core/config.py backend/requirements.txt backend/tests/test_rag_embedding.py
git commit -m "feat(rag): local/http embedding providers"
```

---

### Task 4: 入库管线与 CLI

**Files:**
- Create: `backend/app/services/rag/ingest.py`、`backend/scripts/rag_ingest.py`
- Test: `backend/tests/test_rag_ingest.py`

**Interfaces:**
- Consumes: `parse_source_file`/`chunk_markdown`（T2）、`EmbeddingProvider`（T3）、`RagRepository`（T1）、`manifest-core.json`
- Produces:
  - `async def ingest_manifest(repo, provider, manifest_path: Path, *, source_dir: Path, limit: int | None = None, doc_type: str = "industry_methodology") -> IngestReport`（`IngestReport(inserted, skipped, failed, chunks, errors)`；幂等：按 `sha256` 跳过已入库且 `status='ready'` 的文档；`documents`/`chunks` 批量写入；每篇文档写 `license_note`/`source_url`/`publisher`）
  - CLI：`python -m scripts.rag_ingest --manifest-core [--limit N] [--dry-run]`（`--dry-run` 只打印解析/切分统计不入库）

- [ ] **Step 1: 写失败测试（fake provider + 小 manifest fixture）**

```python
# backend/tests/test_rag_ingest.py
from __future__ import annotations

import json
from pathlib import Path

import pytest


class FakeProvider:
    dim = 4

    async def embed(self, texts):
        import numpy as np

        return [np.ones(4, dtype=np.float32).tobytes() for _ in texts]


@pytest.mark.anyio
async def test_ingest_is_idempotent_by_sha256(test_db, tmp_path: Path):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import ingest_manifest

    doc_md = tmp_path / "doc1.md"
    doc_md.write_text(
        "# 标题\n\n来源：抖音电商官方学习中心\n\n"
        + json.dumps({"version": 2, "deltas": {"d": {"ops": [{"insert": "投放方法正文。"}, {"insert": "\n"}]}}, "attachments": []}),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest-core.json"
    manifest.write_text(json.dumps({"items": [{
        "title": "投放方法", "file": "doc1.md", "sha256": "abc123",
        "source_url": "https://example.com/a", "source_site": "抖音电商官方学习中心",
    }]}), encoding="utf-8")

    repo = RagRepository(test_db)
    first = await ingest_manifest(repo, FakeProvider(), manifest, source_dir=tmp_path)
    assert first.inserted == 1 and first.chunks >= 1
    second = await ingest_manifest(repo, FakeProvider(), manifest, source_dir=tmp_path)
    assert second.inserted == 0 and second.skipped == 1
```

- [ ] **Step 2: 实现 + 提交**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_ingest.py -q`

```bash
git add backend/app/services/rag/ingest.py backend/scripts/rag_ingest.py backend/tests/test_rag_ingest.py
git commit -m "feat(rag): ingestion pipeline and CLI"
```

---

### Task 5: 检索服务与 API

**Files:**
- Create: `backend/app/services/rag/search.py`、`backend/app/api/rag.py`、`backend/app/schemas/rag.py`
- Modify: `backend/app/main.py`（include_router）
- Test: `backend/tests/test_rag_api.py`

**Interfaces:**
- Produces:
  - `class RagSearchService: async def search(self, query: str, top_k: int = 5) -> list[SearchHit]`（`SearchHit(chunk_id, doc_id, title, section_path, content, source_url, publisher, score)`；过滤 `status='ready'` 的文档；query 空/过长（>500 字）→ `ValueError`）
  - `POST /api/rag/search`（body `{query, top_k}`；返回 `{items: [...], elapsed_ms}`；身份 = 平台 token 或登录用户，普通用户可用）
  - `GET /api/rag/documents`（super_admin：列表 + 状态；支持 `status`/`keyword` 过滤）
  - `POST /api/rag/documents/{id}/disable`、`POST /api/rag/documents/{id}/enable`（super_admin）
- 权限：检索用 `get_current_user`（含 `X-Platform-Token` 双身份，`dependencies.py:16-25`）；管理用 `require_super_admin`

- [ ] **Step 1: 写失败测试（fake store + fake provider）**

```python
# backend/tests/test_rag_api.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_search_returns_hits_with_source(test_db, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    repo = RagRepository(test_db)
    doc = await repo.create_document(title="投放手册", sha256="s1", source_url="https://example.com/x", publisher="抖音电商官方学习中心", status="ready")
    await repo.add_chunks(doc.id, [("投放手册 > 出价", "出价策略正文", b"\x00" * 8, 2)])

    class FakeProvider:
        dim = 2

        async def embed(self, texts):
            import numpy as np

            return [np.array([1.0, 0.0], dtype=np.float32).tobytes()]

    service = RagSearchService(repo, FakeProvider(), store=None)
    hits = await service.search("出价策略", top_k=3)
    assert hits and hits[0].title == "投放手册"
    assert hits[0].source_url == "https://example.com/x"
```

- [ ] **Step 2: 实现**（`store=None` 时用 `NumpyVectorStore` 懒加载 + `repo.iter_embeddings()`；`add_chunks` 后调用 `store.invalidate()`）

- [ ] **Step 3: 跑绿 + 提交**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_rag_api.py -q`

```bash
git add backend/app/services/rag/search.py backend/app/api/rag.py backend/app/schemas/rag.py backend/app/main.py backend/tests/test_rag_api.py
git commit -m "feat(rag): search service and API"
```

---

### Task 6: DSH 工具 `knowledge_search` + 技能模板

**Files:**
- Modify: `dsh-platform/packages/server-connector/src/index.ts`、`dsh-platform/packages/server-connector/tests/connector.test.ts`
- Create: `dsh-platform/skills-template/knowledge-search/SKILL.md`
- Test: `dsh-platform/packages/server-connector` 的 vitest（含现有 3 工具断言更新为 4）

**Interfaces:**
- Consumes: `POST /api/rag/search`（T5）
- Produces: 工具 `knowledge_search`，参数 `{query: string, top_k?: number}`，返回 `{items: [{title, section_path, content, source_url}], elapsed_ms}`；`platformFetch` 增加 `method`/`body` 支持（现有默认 GET，`index.ts:65-77`）

- [ ] **Step 1: 写失败测试**

```ts
it("registers knowledge_search and posts to /api/rag/search", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const tools = installWithFakeFetch(calls);
  expect(tools.map((t) => t.name)).toContain("knowledge_search");
  const result = await tools.find((t) => t.name === "knowledge_search")!.execute({ query: "投放策略", top_k: 3 });
  expect(calls[0].url).toContain("/api/rag/search");
  expect(calls[0].init?.method).toBe("POST");
  expect(JSON.parse(String(calls[0].init?.body))).toEqual({ query: "投放策略", top_k: 3 });
});
```

- [ ] **Step 2: 实现工具 + SKILL.md**（SKILL.md：`name: knowledge-search`、`whenToUse`：涉及行业方法论/投放规则/平台政策/案例数据时先检索再作答；引用时给出 `source_url`；检索为空时说明未命中并改用 web_search）

- [ ] **Step 3: 跑绿 + 提交**

Run: `cd dsh-platform/packages/server-connector; pnpm test`

```bash
git add dsh-platform/packages/server-connector/src/index.ts dsh-platform/packages/server-connector/tests/connector.test.ts dsh-platform/packages/server-connector/lib/index.js dsh-platform/skills-template/knowledge-search/SKILL.md
git commit -m "feat(rag): knowledge_search connector tool and skill"
```

---

### Task 7: 前端 `/knowledge` 管理页（super_admin）

**Files:**
- Create: `frontend/src/app/(dashboard)/knowledge/page.tsx`、`frontend/src/components/knowledge/*`、`frontend/src/lib/rag-api.ts`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`（`systemItems`）、`frontend/src/lib/copy.ts`
- Test: `frontend/src/components/knowledge/document-list.test.tsx`

**Interfaces:**
- Consumes: `api<T>()`（`lib/api.ts:27-80`）；`isSuperAdmin`（`lib/roles.ts:3-5`）；管理页内联 super_admin 门（照 `app/(agent)/agent/audit/page.tsx:8,68,165-168`）
- Produces: `ragApi = { listDocuments(params), disable(id), enable(id), search(query) }`；页面：文档表格（标题/来源/状态/块数/入库时间）+ 关键词过滤 + 预览抽屉（展示命中块与 `source_url`）+ 禁用/启用；菜单「知识库」（super_admin 可见）

- [ ] **Step 1: 写失败测试 → Step 2: 实现 → Step 3: 跑绿**

Run: `cd frontend; npm test -- --run src/components/knowledge`

```bash
git add frontend/src/app/(dashboard)/knowledge frontend/src/components/knowledge frontend/src/lib/rag-api.ts frontend/src/components/layout/app-sidebar.tsx frontend/src/lib/copy.ts
git commit -m "feat(rag): knowledge admin page"
```

---

### Task 8: 黄金测试集与评测脚本（recall@5 ≥90%）

**Files:**
- Create: `backend/scripts/rag_eval.py`、`docs/langgraph-eval/../rag-eval/` 报告目录（实际：`docs/rag-eval/report.md`）
- Create: `backend/tests/test_rag_eval.py`
- 数据：`rag_eval_set` 表（100 问；由 T8 用 LLM 生成 + 抽 10 条人工复核，写库）

**Interfaces:**
- Produces:
  - `def recall_at_k(hits: list[SearchHit], expected_doc_ids: list[uuid.UUID], k: int = 5) -> float`（命中任一 expected 即 1）
  - `async def evaluate(repo, service, *, k: int = 5) -> EvalReport`（`EvalReport(total, hits, recall, p95_ms, misses: list[dict])`）
  - CLI：`python -m scripts.rag_eval [--k 5] [--report docs/rag-eval/report.md]`
- 验收线：`recall@5 >= 0.90` 且检索 P95 ≤500ms（spec §3）

- [ ] **Step 1: 写失败测试（fake service 返回固定命中）**

```python
# backend/tests/test_rag_eval.py
from __future__ import annotations

import uuid

from scripts.rag_eval import recall_at_k


class Hit:
    def __init__(self, doc_id):
        self.doc_id = doc_id


def test_recall_at_k_counts_hit_within_topk():
    d1, d2 = uuid.uuid4(), uuid.uuid4()
    assert recall_at_k([Hit(d1), Hit(d2)], [d2], k=1) == 0.0
    assert recall_at_k([Hit(d1), Hit(d2)], [d2], k=2) == 1.0
```

- [ ] **Step 2: 实现 + 生成 100 问**

Run（生成黄金集，需真实 LLM，一次）:
`X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_eval --generate-questions --per-doc 4`
（对每篇 `ready` 文档用 LLM 生成 3-5 个可被该文档回答的问题 → 写 `rag_eval_set`，`expected_doc_ids=[doc.id]`，`approved_at=null`；人工抽 10 条复核后 `approved_at=now`）

- [ ] **Step 3: 跑评测**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m scripts.rag_eval --k 5`
Expected: `recall@5 >= 0.90`；否则按设计阶梯（bge-reranker-base 重排 → 混合检索 BM25+RRF → 调切分参数）逐级启用并记录

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/rag_eval.py backend/tests/test_rag_eval.py docs/rag-eval/report.md
git commit -m "feat(rag): golden eval set and recall@5 harness"
```

---

### Task 9: 端到端验收与文档

**Files:**
- Create: `docs/verification/rag-acceptance.md`
- Modify: 本计划（勾选）

- [ ] **Step 1: 端到端手测（记录证据）**
  1. 入库核心集：`python -m scripts.rag_ingest --manifest-core`（记录耗时、插入文档数/块数）
  2. DSH 侧：打开工作台问「抖音千川全域投放的出价策略有哪些？」→ 观察是否调用 `knowledge_search` 并给出 `source_url` 引用
  3. 管理页：禁用一篇文档 → 再问相关问题 → 该文档不再被引用；重新启用恢复
  4. 越权：普通用户访问 `/knowledge` → 提示仅超级管理员；`POST /api/rag/search` 无 token → 401
  5. 评测：`python -m scripts.rag_eval` → 报告写入 `docs/rag-eval/report.md`（含 recall@5、P95、misses 清单）

- [ ] **Step 2: 写验收文档 + 提交**

```bash
git add docs/verification/rag-acceptance.md docs/superpowers/plans/2026-09-15-rag-industry-kb.md
git commit -m "docs(verification): rag acceptance results"
```

---

## Self-Review

- **Spec 覆盖**：spec §3（`2026-09-07-dsh-platform-rebase-design.md:147-203`）的五段管线 → T2/T3/T4；三张表 → T1；`knowledge_search` + skill → T6；`/knowledge` 管理页 → T7；黄金集 recall@5 ≥90% → T8；检索面对全部登录用户、管理仅 super_admin → T5/T7。
- **偏离项**：D1（pgvector → 精确检索）与 D2（embedding 供给可切换）已在 Global Constraints 明示，需用户确认后开工。
- **占位符扫描**：无 TBD；T7 前端步骤给了测试骨架与实现要点（组件细节按现有 dashboard 组件风格实现），T5/T6 给了接口与断言。
- **类型一致性**：`SearchHit`（T5）与 T6 工具返回字段一致；`EmbeddingProvider.embed`（T3）在 T4/T5 调用一致；`RagRepository.add_chunks(doc_id, [(section_path, content, embedding, dim)])` 在 T1/T5 一致。

## Execution Handoff

推荐子代理驱动：**T1/T2/T3 可并发**（无共享文件）→ T4/T5 并发 → T6/T7/T8 并发 → T9 人工验收。
