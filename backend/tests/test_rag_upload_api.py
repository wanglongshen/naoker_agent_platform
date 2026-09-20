from __future__ import annotations

import importlib.util
import io
import uuid

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec("docx") is not None,
    reason="python-docx 已安装，无法复现缺解析依赖场景",
)
@pytest.mark.anyio
async def test_upload_missing_parser_returns_400(admin_client, admin_csrf):
    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "缺解析依赖库"}, headers=admin_csrf
        )
    ).json()["data"]
    files = {
        "file": (
            "报告.docx",
            io.BytesIO(b"PK\x03\x04fake-docx-bytes"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/documents", files=files, headers=admin_csrf
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "PARSER_UNAVAILABLE"
    assert body["message"] == "该格式需要安装解析依赖：docx"


@pytest.mark.skipif(
    importlib.util.find_spec("pypdf") is None,
    reason="pypdf 未安装，无法验证 PDF 上传链路",
)
@pytest.mark.anyio
async def test_upload_pdf_end_to_end_ready(admin_client, admin_csrf, test_db, monkeypatch):
    import numpy as np

    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            return [np.ones(4, dtype=np.float32).tobytes() for _ in texts]

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())
    monkeypatch.setattr(worker, "async_session_factory", test_db)

    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "PDF端到端库"}, headers=admin_csrf
        )
    ).json()["data"]
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/documents",
        files={
            "file": (
                "手册.pdf",
                io.BytesIO(_make_pdf_bytes("Hello RAG PDF pipeline")),
                "application/pdf",
            )
        },
        headers=admin_csrf,
    )
    assert resp.status_code == 200
    body = resp.json()["data"]

    await worker.process_job(uuid.UUID(body["job_id"]))

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(uuid.UUID(body["doc_id"]))
        job = await repo.get_job(uuid.UUID(body["job_id"]))
        assert doc.status == "ready" and doc.chunk_count >= 1
        assert job.status == "succeeded"
        chunks, total = await repo.list_chunks_page(doc.id, page=1, page_size=10)
        assert total >= 1
        assert "Hello RAG PDF pipeline" in "".join(chunk.content for chunk in chunks)


def _make_pdf_bytes(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font_ref = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.anyio
async def test_upload_creates_document_and_job(admin_client, admin_csrf, test_db):
    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "上传库"}, headers=admin_csrf
        )
    ).json()["data"]
    files = {
        "file": (
            "手册.md",
            io.BytesIO("# 标题\n\n正文内容".encode("utf-8")),
            "text/markdown",
        )
    }
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/documents", files=files, headers=admin_csrf
    )
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
async def test_upload_rejects_bad_extension_and_duplicate(admin_client, admin_csrf):
    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "校验库"}, headers=admin_csrf
        )
    ).json()["data"]
    bad = {"file": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/documents", files=bad, headers=admin_csrf
    )
    assert resp.status_code == 400

    good = {"file": ("a.md", io.BytesIO("# t\n\nbody".encode("utf-8")), "text/markdown")}
    assert (
        await admin_client.post(
            f"/api/rag/libraries/{lib['id']}/documents", files=good, headers=admin_csrf
        )
    ).status_code == 200
    dup = {"file": ("a.md", io.BytesIO("# t\n\nbody".encode("utf-8")), "text/markdown")}
    assert (
        await admin_client.post(
            f"/api/rag/libraries/{lib['id']}/documents", files=dup, headers=admin_csrf
        )
    ).status_code == 409


@pytest.mark.anyio
async def test_upload_cross_library_duplicate_returns_409(admin_client, admin_csrf):
    lib_a = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "跨库A"}, headers=admin_csrf
        )
    ).json()["data"]
    lib_b = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "跨库B"}, headers=admin_csrf
        )
    ).json()["data"]
    content = "# 重复文件\n\n跨库同内容".encode("utf-8")
    first = await admin_client.post(
        f"/api/rag/libraries/{lib_a['id']}/documents",
        files={"file": ("dup.md", io.BytesIO(content), "text/markdown")},
        headers=admin_csrf,
    )
    assert first.status_code == 200
    dup = await admin_client.post(
        f"/api/rag/libraries/{lib_b['id']}/documents",
        files={"file": ("dup.md", io.BytesIO(content), "text/markdown")},
        headers=admin_csrf,
    )
    assert dup.status_code == 409
    body = dup.json()
    assert body["code"] == "DOCUMENT_EXISTS"
    assert "跨库A" in body["message"]


@pytest.mark.anyio
async def test_upload_rejects_invalid_filename(admin_client, admin_csrf):
    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "文件名校验库"}, headers=admin_csrf
        )
    ).json()["data"]
    resp = await admin_client.post(
        f"/api/rag/libraries/{lib['id']}/documents",
        files={"file": ("..", io.BytesIO(b"# t\n\nbody"), "text/markdown")},
        headers=admin_csrf,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_FILENAME"
    assert resp.json()["message"] == "文件名不合法"


@pytest.mark.anyio
async def test_reingest_enqueues_job_and_resets_status(admin_client, admin_csrf, test_db):
    import uuid as _uuid

    from app.repositories.rag_repository import RagRepository

    lib = (
        await admin_client.post(
            "/api/rag/libraries", json={"name": "重切库"}, headers=admin_csrf
        )
    ).json()["data"]
    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.create_document(
            title="可重切",
            sha256="re1",
            status="ready",
            library_id=_uuid.UUID(lib["id"]),
            file_key="backend/var/rag/uploads/x.md",
        )
        doc_id = str(doc.id)

    resp = await admin_client.post(
        f"/api/rag/documents/{doc_id}/reingest", headers=admin_csrf
    )
    assert resp.status_code == 200
    async with test_db() as session:
        repo = RagRepository(session)
        assert (await repo.get_document(_uuid.UUID(doc_id))).status == "pending"
        assert (
            await repo.get_job(_uuid.UUID(resp.json()["data"]["job_id"]))
        ).kind == "upload"
