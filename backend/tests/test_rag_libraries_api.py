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
async def test_patch_library_ignores_null_fields(admin_client, admin_csrf):
    created = (
        await admin_client.post("/api/rag/libraries", json={"name": "空值库"}, headers=admin_csrf)
    ).json()["data"]

    resp = await admin_client.patch(
        f"/api/rag/libraries/{created['id']}",
        json={"name": None, "description": "x"},
        headers=admin_csrf,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "空值库"
    assert data["description"] == "x"


@pytest.mark.anyio
async def test_patch_nonexistent_library_returns_404_not_409(admin_client, admin_csrf):
    await admin_client.post("/api/rag/libraries", json={"name": "已存在库"}, headers=admin_csrf)

    resp = await admin_client.patch(
        f"/api/rag/libraries/{uuid.uuid4()}",
        json={"name": "已存在库"},
        headers=admin_csrf,
    )
    assert resp.status_code == 404


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


@pytest.mark.anyio
async def test_patch_library_can_clear_description(admin_client, admin_csrf):
    lib = (
        await admin_client.post(
            "/api/rag/libraries",
            json={"name": "清空介绍库", "description": "原始介绍"},
            headers=admin_csrf,
        )
    ).json()["data"]

    resp = await admin_client.patch(
        f"/api/rag/libraries/{lib['id']}", json={"description": None}, headers=admin_csrf
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] is None


@pytest.mark.anyio
async def test_library_create_conflict_raises_domain_error(test_db):
    from app.repositories.rag_repository import LibraryNameConflict, RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        await repo.create_library(name="并发冲突库")
        with pytest.raises(LibraryNameConflict):
            await repo.create_library(name="并发冲突库")


@pytest.mark.anyio
async def test_library_create_conflict_returns_409_even_without_precheck(
    admin_client, admin_csrf, monkeypatch
):
    from app.repositories.rag_repository import RagRepository

    created = await admin_client.post(
        "/api/rag/libraries", json={"name": "绕过预检库"}, headers=admin_csrf
    )
    assert created.status_code == 200

    async def _always_miss(self, name):
        return None

    monkeypatch.setattr(RagRepository, "get_library_by_name", _always_miss)

    dup = await admin_client.post(
        "/api/rag/libraries", json={"name": "绕过预检库"}, headers=admin_csrf
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "LIBRARY_NAME_EXISTS"


@pytest.mark.anyio
async def test_library_rename_conflict_returns_409_even_without_precheck(
    admin_client, admin_csrf, monkeypatch
):
    from app.repositories.rag_repository import RagRepository

    first = (
        await admin_client.post("/api/rag/libraries", json={"name": "重名库A"}, headers=admin_csrf)
    ).json()["data"]
    second = (
        await admin_client.post("/api/rag/libraries", json={"name": "重名库B"}, headers=admin_csrf)
    ).json()["data"]
    assert first["id"] != second["id"]

    async def _always_miss(self, name):
        return None

    monkeypatch.setattr(RagRepository, "get_library_by_name", _always_miss)

    resp = await admin_client.patch(
        f"/api/rag/libraries/{second['id']}", json={"name": "重名库A"}, headers=admin_csrf
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "LIBRARY_NAME_EXISTS"
