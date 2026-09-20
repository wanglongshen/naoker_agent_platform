"""检索服务：query → embedding → top-k 向量命中 → 回查 chunk/文档 → 带来源的 SearchHit。

默认 store 用 `NumpyVectorStore` 懒加载 `repo.iter_embeddings()`；为保证 CLI 入库后
API 进程能看到新数据，每次检索前按 30 秒节流做「签名校验」：`rag_chunks` 的
`count(*) + max(created_at)` 变化时调用 `store.invalidate()`。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.models.rag import RagChunk, RagDocument, RagLibrary
from app.services.rag.store import NumpyVectorStore, VectorStore

MAX_QUERY_CHARS = 500
_CACHE_CHECK_INTERVAL_SECONDS = 30.0


@dataclass
class SearchHit:
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    title: str
    section_path: str
    content: str
    source_url: str | None
    publisher: str | None
    score: float
    library_id: uuid.UUID | None = None
    library_name: str | None = None


class RagSearchService:
    def __init__(
        self,
        repo: Any,
        provider: Any,
        store: VectorStore | None = None,
    ) -> None:
        self.repo = repo
        self.provider = provider
        self.store = (
            store
            if store is not None
            else NumpyVectorStore(loader=self.repo.iter_embeddings)
        )
        self._signature: tuple[int, Any] | None = None
        self._cache_checked_at: float = 0.0
        self._enabled_ids: set[uuid.UUID] | None = None
        self._enabled_ids_at: float = 0.0

    async def _maybe_refresh_cache(self) -> None:
        now = time.monotonic()
        if now - self._cache_checked_at < _CACHE_CHECK_INTERVAL_SECONDS:
            return
        signature = await self._chunk_signature()
        self._cache_checked_at = now
        if self._signature is None:
            self._signature = signature
        elif signature != self._signature:
            self._signature = signature
            self.store.invalidate()

    async def _chunk_signature(self) -> tuple[int, Any]:
        """`rag_chunks` 的 count(*) + max(created_at)，用于判断缓存是否过期。

        仓储可提供 `chunk_signature()`（如 API 侧的 session 工厂实现）；否则回退
        到仓储自带的 session 直接查询。
        """
        custom = getattr(self.repo, "chunk_signature", None)
        if custom is not None:
            return await custom()
        session = self.repo.session
        result = await session.execute(
            select(func.count(RagChunk.id), func.max(RagChunk.created_at))
        )
        count, latest = result.one()
        return (int(count or 0), latest)

    async def _load_chunks(
        self, chunk_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, RagChunk]:
        if not chunk_ids:
            return {}
        custom = getattr(self.repo, "get_chunks_by_ids", None)
        if custom is not None:
            rows = await custom(chunk_ids)
            return {chunk.id: chunk for chunk in rows}
        result = await self.repo.session.execute(
            select(RagChunk).where(RagChunk.id.in_(chunk_ids))
        )
        return {chunk.id: chunk for chunk in result.scalars().all()}

    async def _load_documents(
        self, doc_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, RagDocument]:
        if not doc_ids:
            return {}
        custom = getattr(self.repo, "get_documents_by_ids", None)
        if custom is not None:
            rows = await custom(doc_ids)
            return {doc.id: doc for doc in rows}
        result = await self.repo.session.execute(
            select(RagDocument).where(RagDocument.id.in_(doc_ids))
        )
        return {doc.id: doc for doc in result.scalars().all()}

    async def _load_allowed_chunk_ids(
        self, library_id: uuid.UUID
    ) -> list[uuid.UUID]:
        custom = getattr(self.repo, "list_chunk_ids_for_library", None)
        if custom is not None:
            return await custom(library_id)
        result = await self.repo.session.execute(
            select(RagChunk.id)
            .join(RagDocument, RagDocument.id == RagChunk.doc_id)
            .where(RagDocument.library_id == library_id)
        )
        return list(result.scalars().all())

    async def _load_libraries(
        self, library_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, RagLibrary]:
        if not library_ids:
            return {}
        custom = getattr(self.repo, "get_libraries_by_ids", None)
        if custom is not None:
            rows = await custom(library_ids)
            return {lib.id: lib for lib in rows}
        result = await self.repo.session.execute(
            select(RagLibrary).where(RagLibrary.id.in_(library_ids))
        )
        return {lib.id: lib for lib in result.scalars().all()}

    async def _enabled_chunk_ids(self) -> set[uuid.UUID]:
        """启用库中 ready 文档的 chunk id 集合（全局检索预过滤，A5a）。

        与 chunk 版本探针同样以 30 秒为界刷新，避免库启用/停用切换后长期陈旧。
        """
        now = time.monotonic()
        if (
            self._enabled_ids is not None
            and now - self._enabled_ids_at < _CACHE_CHECK_INTERVAL_SECONDS
        ):
            return self._enabled_ids
        custom = getattr(self.repo, "list_enabled_chunk_ids", None)
        if custom is not None:
            self._enabled_ids = set(await custom())
        else:
            result = await self.repo.session.execute(
                select(RagChunk.id)
                .join(RagDocument, RagDocument.id == RagChunk.doc_id)
                .join(RagLibrary, RagLibrary.id == RagDocument.library_id)
                .where(
                    RagLibrary.retrieval_enabled.is_(True),
                    RagDocument.status == "ready",
                )
            )
            self._enabled_ids = set(result.scalars().all())
        self._enabled_ids_at = now
        return self._enabled_ids

    async def warmup(self) -> None:
        """预热 embedding 模型与向量矩阵（首个检索请求的两笔懒加载）。

        由 API 进程启动时以后台任务调用，不阻塞启动；失败向上抛，
        由调用方决定是否降级为告警（见 `app.main._warmup_rag`）。
        """
        await self.provider.embed(["warmup"])
        ensure = getattr(self.store, "_ensure", None)
        if ensure is not None:
            await ensure()

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        library_id: uuid.UUID | None = None,
        include_disabled_libraries: bool = False,
    ) -> list[SearchHit]:
        normalized = (query or "").strip()
        if not normalized or len(normalized) > MAX_QUERY_CHARS:
            raise ValueError("invalid_query")
        if top_k < 1:
            raise ValueError("invalid_query")

        allowed_ids: set[uuid.UUID] | None = None
        if library_id is not None:
            allowed_ids = set(await self._load_allowed_chunk_ids(library_id))
            if not allowed_ids:
                return []
        elif not include_disabled_libraries:
            allowed_ids = await self._enabled_chunk_ids()
            if not allowed_ids:
                return []

        await self._maybe_refresh_cache()
        vectors = await self.provider.embed([normalized])
        if not vectors:
            return []
        fetch_k = max(top_k * 3, top_k)
        candidates = await self.store.search(
            vectors[0], fetch_k, allowed_ids=allowed_ids
        )
        if not candidates:
            return []

        chunks = await self._load_chunks([chunk_id for chunk_id, _ in candidates])
        documents = await self._load_documents(
            list({chunk.doc_id for chunk in chunks.values()})
        )
        libraries = await self._load_libraries(
            list({doc.library_id for doc in documents.values() if doc.library_id})
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
            if (
                not include_disabled_libraries
                and lib is not None
                and not lib.retrieval_enabled
            ):
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
