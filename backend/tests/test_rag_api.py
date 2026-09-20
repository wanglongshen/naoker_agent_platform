from __future__ import annotations

import uuid

import numpy as np
import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.models.rbac import User

settings = get_settings()
TEST_ORIGIN = "http://localhost:3000"


class FakeProvider:
    dim = 2

    async def embed(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32).tobytes() for _ in texts]


def _chunk(dim: int = 2) -> bytes:
    return np.array([1.0] + [0.0] * (dim - 1), dtype=np.float32).tobytes()


@pytest.mark.anyio
async def test_search_returns_hits_with_source(test_db):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="搜索库")
        doc = await repo.create_document(
            title="投放手册",
            sha256="s1",
            source_url="https://example.com/x",
            publisher="抖音电商官方学习中心",
            status="ready",
            library_id=lib.id,
        )
        await repo.add_chunks(
            doc.id, [("投放手册 > 出价", "出价策略正文", _chunk(), 2)]
        )

        service = RagSearchService(repo, FakeProvider(), store=None)
        hits = await service.search("出价策略", top_k=3)
        assert hits and hits[0].title == "投放手册"
        assert hits[0].source_url == "https://example.com/x"
        assert hits[0].publisher == "抖音电商官方学习中心"
        assert hits[0].section_path == "投放手册 > 出价"
        assert hits[0].content == "出价策略正文"
        assert hits[0].doc_id == doc.id


@pytest.mark.anyio
async def test_search_falls_back_to_title_and_skips_not_ready(test_db):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="回退库")
        ready = await repo.create_document(
            title="无标题章节文档", sha256="s2", status="ready", library_id=lib.id
        )
        await repo.add_chunks(ready.id, [("", "正文", _chunk(), 2)])
        disabled = await repo.create_document(
            title="已禁用文档", sha256="s3", status="disabled", library_id=lib.id
        )
        await repo.add_chunks(disabled.id, [("已禁用", "不该出现", _chunk(), 2)])

        service = RagSearchService(repo, FakeProvider(), store=None)
        hits = await service.search("任意问题", top_k=5)
        assert [hit.doc_id for hit in hits] == [ready.id]
        assert hits[0].section_path == "无标题章节文档"


@pytest.mark.anyio
async def test_search_rejects_invalid_query(test_db):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        service = RagSearchService(RagRepository(session), FakeProvider(), store=None)
        for query in ("", "   ", "x" * 501):
            with pytest.raises(ValueError):
                await service.search(query)


@pytest.mark.anyio
async def test_store_refreshes_after_new_chunks(test_db, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag import search as search_module
    from app.services.rag.search import RagSearchService

    monkeypatch.setattr(search_module, "_CACHE_CHECK_INTERVAL_SECONDS", 0.0)

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="增量库")
        doc = await repo.create_document(
            title="增量文档", sha256="s4", status="ready", library_id=lib.id
        )
        await repo.add_chunks(doc.id, [("一", "第一块", _chunk(), 2)])

        service = RagSearchService(repo, FakeProvider(), store=None)
        first = await service.search("问题", top_k=5)
        assert len(first) == 1

        added = await repo.create_document(
            title="增量文档二", sha256="s4b", status="ready", library_id=lib.id
        )
        await repo.add_chunks(added.id, [("二", "第二块", _chunk(), 2)])
        second = await service.search("问题", top_k=5)
        assert len(second) == 2
        assert {hit.doc_id for hit in second} == {doc.id, added.id}


@pytest.mark.anyio
async def test_search_api_returns_items(test_db):
    from app.api import rag as rag_api
    from app.core import dependencies
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="API 库")
        doc = await repo.create_document(
            title="API 手册",
            sha256="s5",
            source_url="https://example.com/api",
            status="ready",
            library_id=lib.id,
        )
        await repo.add_chunks(doc.id, [("章节", "API 正文", _chunk(), 2)])
        service = RagSearchService(repo, FakeProvider(), store=None)

        async def fake_current_user():
            return User(id=uuid.uuid4(), username="tester", display_name="Tester")

        app.dependency_overrides[dependencies.get_current_user] = fake_current_user
        app.dependency_overrides[rag_api.get_search_service] = lambda: service
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"Origin": TEST_ORIGIN},
            ) as ac:
                response = await ac.post(
                    "/api/rag/search", json={"query": "API 正文", "top_k": 3}
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"][0]["title"] == "API 手册"
    assert data["items"][0]["source_url"] == "https://example.com/api"
    assert "elapsed_ms" in data


@pytest.mark.anyio
async def test_search_api_rejects_empty_query(test_db):
    from app.api import rag as rag_api
    from app.core import dependencies
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        service = RagSearchService(RagRepository(session), FakeProvider(), store=None)

        async def fake_current_user():
            return User(id=uuid.uuid4(), username="tester", display_name="Tester")

        app.dependency_overrides[dependencies.get_current_user] = fake_current_user
        app.dependency_overrides[rag_api.get_search_service] = lambda: service
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"Origin": TEST_ORIGIN},
            ) as ac:
                response = await ac.post("/api/rag/search", json={"query": "   "})
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_QUERY"


@pytest.mark.anyio
async def test_documents_api_requires_super_admin(test_db):
    ph = PasswordHasher()
    async with test_db() as session:
        user = User(
            username=f"plain_{uuid.uuid4().hex[:8]}",
            display_name="Plain User",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        session.add(user)
        await session.commit()
        username = user.username

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Origin": TEST_ORIGIN}
    ) as ac:
        login = await ac.post(
            "/api/auth/login", json={"username": username, "password": "Password123"}
        )
        assert login.status_code == 200
        response = await ac.get("/api/rag/documents")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.anyio
async def test_documents_api_lists_for_admin(test_db, admin_client):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="列表库")
        await repo.create_document(
            title="列表文档", sha256="s6", status="ready", library_id=lib.id
        )

    response = await admin_client.get("/api/rag/documents?status=ready")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "列表文档"


@pytest.mark.anyio
async def test_search_include_disabled_only_for_super_admin(test_db, admin_client):
    from app.api import rag as rag_api
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="停用检索库", retrieval_enabled=False)
        doc = await repo.create_document(
            title="停用库文档", sha256="s7", status="ready", library_id=lib.id
        )
        await repo.add_chunks(doc.id, [("章节", "停用库正文", _chunk(), 2)])
        service = RagSearchService(repo, FakeProvider(), store=None)
        library_id = str(lib.id)

        app.dependency_overrides[rag_api.get_search_service] = lambda: service
        try:
            with_flag = await admin_client.post(
                "/api/rag/search",
                json={
                    "query": "停用库正文",
                    "top_k": 5,
                    "library_id": library_id,
                    "include_disabled": True,
                },
            )
            without_flag = await admin_client.post(
                "/api/rag/search",
                json={"query": "停用库正文", "top_k": 5, "library_id": library_id},
            )
        finally:
            app.dependency_overrides.pop(rag_api.get_search_service, None)

    assert with_flag.status_code == 200
    assert [item["title"] for item in with_flag.json()["data"]["items"]] == ["停用库文档"]
    assert without_flag.status_code == 200
    assert without_flag.json()["data"]["items"] == []


@pytest.mark.anyio
async def test_search_api_accepts_library_name(test_db, admin_client):
    """按库名检索：library="平台规则" 只返回该库命中。"""
    from app.api import rag as rag_api
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.search import RagSearchService

    async with test_db() as session:
        repo = RagRepository(session)
        rules = await repo.create_library(name="平台规则")
        other = await repo.create_library(name="千川投放")
        doc_rules = await repo.create_document(
            title="商家申诉举证标准", sha256="libname1", status="ready", library_id=rules.id
        )
        await repo.add_chunks(
            doc_rules.id,
            [("s", "举证材料要求", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)],
        )
        doc_other = await repo.create_document(
            title="千川投放手册", sha256="libname2", status="ready", library_id=other.id
        )
        await repo.add_chunks(
            doc_other.id,
            [("s", "出价策略", np.array([1.0, 0.0], dtype=np.float32).tobytes(), 2)],
        )
        service = RagSearchService(repo, FakeProvider(), store=None)

        app.dependency_overrides[rag_api.get_search_service] = lambda: service
        try:
            response = await admin_client.post(
                "/api/rag/search", json={"query": "举证", "top_k": 5, "library": "平台规则"}
            )
        finally:
            app.dependency_overrides.pop(rag_api.get_search_service, None)

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
