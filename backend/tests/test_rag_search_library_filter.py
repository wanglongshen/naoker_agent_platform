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


@pytest.mark.anyio
async def test_search_scoped_to_library_ranks_within_library(test_db):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib_big = await repo.create_library(name="大库")
        lib_small = await repo.create_library(name="小库")
        lib_empty = await repo.create_library(name="空库")

        doc_big = await repo.create_document(
            title="大库文档", sha256="scope-big", status="ready", library_id=lib_big.id
        )
        await repo.add_chunks(
            doc_big.id,
            [
                ("s", f"大库内容{i}", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)
                for i in range(3)
            ],
        )
        doc_small = await repo.create_document(
            title="小库文档", sha256="scope-small", status="ready", library_id=lib_small.id
        )
        await repo.add_chunks(
            doc_small.id,
            [("s", "小库内容", np.array([0.9, 0.1], dtype=np.float32).tobytes(), 2)],
        )

        service = RagSearchService(repo, FakeProvider(), store=None)

        global_hits = await service.search("内容", top_k=1)
        assert [hit.title for hit in global_hits] == ["大库文档"]

        scoped = await service.search("内容", top_k=1, library_id=lib_small.id)
        assert [hit.title for hit in scoped] == ["小库文档"]

        assert await service.search("内容", top_k=1, library_id=lib_empty.id) == []


@pytest.mark.anyio
async def test_global_search_prefilters_disabled_library_chunks(test_db):
    """停用库块数远超 fetch_k 时，全局检索仍须返回启用库结果（A5a）。

    修复前：候选窗口 fetch_k = top_k*3 被相似度更高的停用库块占满，
    事后过滤导致 0 命中。
    """
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib_on = await repo.create_library(name="启用库-预过滤")
        lib_off = await repo.create_library(name="停用库-预过滤", retrieval_enabled=False)

        doc_on = await repo.create_document(
            title="启用库-预过滤文档", sha256="pf-on", status="ready", library_id=lib_on.id
        )
        await repo.add_chunks(
            doc_on.id,
            [("s", "启用内容", np.array([0.7, 0.7], dtype=np.float32).tobytes(), 2)],
        )
        doc_off = await repo.create_document(
            title="停用库-预过滤文档", sha256="pf-off", status="ready", library_id=lib_off.id
        )
        await repo.add_chunks(
            doc_off.id,
            [
                ("s", f"停用内容{i}", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)
                for i in range(60)
            ],
        )

        service = RagSearchService(repo, FakeProvider(), store=None)

        hits = await service.search("内容", top_k=5)

        assert [hit.title for hit in hits] == ["启用库-预过滤文档"]
