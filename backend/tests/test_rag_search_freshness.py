"""跨进程新鲜度：ingest worker 提交新 chunk 后，常驻检索服务应立即检索到（无需重启）。"""

from __future__ import annotations

import numpy as np
import pytest


class FakeProvider:
    dim = 2

    async def embed(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32).tobytes() for _ in texts]


def _chunk() -> bytes:
    return np.array([1.0, 0.0], dtype=np.float32).tobytes()


@pytest.mark.anyio
async def test_search_service_sees_worker_ingested_chunks_without_restart(
    test_db, monkeypatch
):
    from app.api import rag as rag_api
    from app.db import session as db_session
    from app.repositories.rag_repository import RagRepository

    monkeypatch.setattr(db_session, "async_session_factory", test_db)
    monkeypatch.setattr(rag_api, "build_embedding_provider", lambda: FakeProvider())

    service = rag_api._build_search_service()

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="新鲜度库")
        library_id = lib.id

    assert await service.search("出价策略", top_k=5, library_id=library_id) == []

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.create_document(
            title="worker 入库文档",
            sha256="fresh1",
            status="ready",
            library_id=library_id,
        )
        await repo.add_chunks(doc.id, [("出价", "出价策略正文", _chunk(), 2)])

    hits = await service.search("出价策略", top_k=5, library_id=library_id)
    assert [hit.title for hit in hits] == ["worker 入库文档"]
