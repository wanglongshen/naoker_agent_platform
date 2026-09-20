from __future__ import annotations

import uuid

import numpy as np
import pytest


def _vec() -> bytes:
    return np.array([1.0, 0.0], dtype=np.float32).tobytes()


@pytest.mark.anyio
async def test_documents_scoped_to_library(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    lib_a = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "库A"}, headers=admin_csrf
        )
    ).json()["data"]
    lib_b = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "库B"}, headers=admin_csrf
        )
    ).json()["data"]
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
async def test_document_delete_and_chunks(admin_client, admin_csrf, test_db):
    from app.repositories.rag_repository import RagRepository

    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "切块库"}, headers=admin_csrf
        )
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.create_document(title="带块文档", sha256="dc1", status="ready", library_id=uuid.UUID(lib["id"]))
        await repo.add_chunks(doc.id, [("s1", "内容1", _vec(), 2), ("s2", "内容2", _vec(), 2)])
        doc_id = str(doc.id)

    chunks = (await admin_client.get(f"/api/rag/documents/{doc_id}/chunks")).json()["data"]
    assert chunks["total"] == 2
    assert chunks["items"][0]["section_path"] == "s1"
    assert "embedding" not in chunks["items"][0]

    deleted = await admin_client.delete(f"/api/rag/documents/{doc_id}", headers=admin_csrf)
    assert deleted.status_code == 200
    assert (await admin_client.get(f"/api/rag/documents/{doc_id}/chunks")).status_code == 404


@pytest.mark.anyio
async def test_delete_document_removes_uploaded_file_only_inside_root(
    admin_client, admin_csrf, test_db, tmp_path, monkeypatch
):
    from app.api import rag as rag_api
    from app.repositories.rag_repository import RagRepository

    monkeypatch.setattr(rag_api, "rag_upload_root", lambda: tmp_path)
    inside = tmp_path / "lib-a" / "a.md"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("x", encoding="utf-8")
    outside = tmp_path.parent / "outside-keep.md"
    outside.write_text("y", encoding="utf-8")

    lib = (
        await admin_client.post("/api/rag/libraries", json={"name": "清理库"}, headers=admin_csrf)
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        inside_doc = await repo.create_document(
            title="待删", sha256="cl-1", status="ready",
            library_id=uuid.UUID(lib["id"]), file_key=str(inside),
        )
        outside_doc = await repo.create_document(
            title="外部文件", sha256="cl-2", status="ready",
            library_id=uuid.UUID(lib["id"]), file_key=str(outside),
        )
        inside_id, outside_id = str(inside_doc.id), str(outside_doc.id)

    assert (
        await admin_client.delete(f"/api/rag/documents/{inside_id}", headers=admin_csrf)
    ).status_code == 200
    assert not inside.exists()

    assert (
        await admin_client.delete(f"/api/rag/documents/{outside_id}", headers=admin_csrf)
    ).status_code == 200
    assert outside.exists()
