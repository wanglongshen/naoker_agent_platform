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
    monkeypatch.setattr(worker, "async_session_factory", test_db)

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
        assert job.finished_at is not None


@pytest.mark.anyio
async def test_process_job_marks_failed_on_empty_document(test_db, tmp_path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            return []

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())
    monkeypatch.setattr(worker, "async_session_factory", test_db)

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
        assert job.finished_at is not None


@pytest.mark.anyio
async def test_process_job_marks_failed_when_provider_build_fails(
    test_db, tmp_path, monkeypatch
):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "build_embedding_provider", boom)
    monkeypatch.setattr(worker, "async_session_factory", test_db)

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="provider失败库")
        md = tmp_path / "doc.md"
        md.write_text("# 标题\n\n正文", encoding="utf-8")
        doc = await repo.create_document(
            title="provider失败文档", sha256="w3", status="pending", library_id=lib.id
        )
        job = await repo.create_job(
            library_id=lib.id, doc_id=doc.id, kind="upload", status="queued", total=1,
            payload={"path": str(md), "title": "provider失败文档"},
        )
        doc_id, job_id = doc.id, job.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(doc_id)
        job = await repo.get_job(job_id)
        assert job.status == "failed"
        assert job.error_message and "boom" in job.error_message
        assert job.finished_at is not None
        assert doc.status == "failed"


@pytest.mark.anyio
async def test_process_import_job(test_db, tmp_path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            import numpy as np

            return [np.zeros(4, dtype=np.float32).tobytes() for _ in texts]

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())
    monkeypatch.setattr(worker, "async_session_factory", test_db)

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="导入库")
        existing = await repo.create_document(
            title="已存在文档", sha256="dup-sha", status="ready", library_id=lib.id
        )
        (tmp_path / "new.md").write_text(
            "# 新文档\n\n正文一\n\n## 小节\n\n正文二", encoding="utf-8"
        )
        (tmp_path / "dup.md").write_text("# 重复\n\n正文", encoding="utf-8")
        job = await repo.create_job(
            library_id=lib.id,
            kind="import",
            status="queued",
            total=2,
            payload={
                "scope": "core",
                "category": None,
                "markdown_root": str(tmp_path),
                "items": [
                    {
                        "file": "new.md",
                        "title": "新文档",
                        "sha256": "new-sha",
                        "source_site": "抖音电商官方学习中心",
                        "category": "methodology",
                    },
                    {
                        "file": "dup.md",
                        "title": "重复文档",
                        "sha256": "dup-sha",
                        "source_site": "抖音电商官方学习中心",
                        "category": "rules",
                    },
                ],
            },
        )
        lib_id, job_id, existing_id = lib.id, job.id, existing.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        job = await repo.get_job(job_id)
        assert job.status == "succeeded" and job.processed == 2 and job.total == 2
        page = await repo.list_documents(library_id=lib_id, page_size=100)
        assert page.total == 2
        new_doc = await repo.get_document_by_sha256("new-sha")
        assert new_doc is not None and new_doc.id != existing_id
        assert new_doc.status == "ready" and new_doc.chunk_count >= 1
        assert new_doc.doc_type == "methodology"
        assert new_doc.publisher == "抖音电商官方学习中心"
        duplicate = await repo.get_document_by_sha256("dup-sha")
        assert duplicate is not None and duplicate.id == existing_id


def _import_job_items(*names: str, hashed: bool = True) -> list[dict]:
    return [
        {
            "file": name,
            "title": name,
            "sha256": f"sha-{name}" if hashed else "",
            "source_site": "测试源",
        }
        for name in names
    ]


class _OkProvider:
    dim = 4

    async def embed(self, texts):
        import numpy as np

        return [np.zeros(4, dtype=np.float32).tobytes() for _ in texts]


async def _run_import_job(test_db, tmp_path, monkeypatch, lib_name: str, items: list[dict]):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: _OkProvider())
    monkeypatch.setattr(worker, "async_session_factory", test_db)

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name=lib_name)
        job = await repo.create_job(
            library_id=lib.id,
            kind="import",
            status="queued",
            total=len(items),
            payload={"markdown_root": str(tmp_path), "items": items},
        )
        job_id = job.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        return await repo.get_job(job_id)


@pytest.mark.anyio
async def test_import_all_success_marks_job_succeeded(test_db, tmp_path, monkeypatch):
    for name in ("ok-1.md", "ok-2.md", "ok-3.md"):
        (tmp_path / name).write_text("# 标题\n\n正文内容", encoding="utf-8")
    job = await _run_import_job(
        test_db, tmp_path, monkeypatch, "全成功库", _import_job_items("ok-1.md", "ok-2.md", "ok-3.md")
    )
    assert job.status == "succeeded"
    assert job.processed == 3 and job.total == 3
    assert job.error_message is None
    assert job.finished_at is not None


@pytest.mark.anyio
async def test_import_partial_failure_marks_job_partial(test_db, tmp_path, monkeypatch):
    for name in ("ok-1.md", "ok-2.md"):
        (tmp_path / name).write_text("# 标题\n\n正文内容", encoding="utf-8")
    items = _import_job_items("ok-1.md", "ok-2.md") + [
        {"file": "missing.md", "title": "缺失文档", "sha256": "", "source_site": "测试源"}
    ]
    job = await _run_import_job(test_db, tmp_path, monkeypatch, "部分成功库", items)
    assert job.status == "partial"
    assert job.processed == 3 and job.total == 3
    assert job.error_message is not None and "missing.md" in job.error_message
    assert job.finished_at is not None


@pytest.mark.anyio
async def test_import_all_failures_marks_job_failed(test_db, tmp_path, monkeypatch):
    items = _import_job_items(
        "missing-1.md", "missing-2.md", "missing-3.md", hashed=False
    )
    job = await _run_import_job(test_db, tmp_path, monkeypatch, "全失败库", items)
    assert job.status == "failed"
    assert job.processed == 3 and job.total == 3
    assert job.error_message is not None and "missing-3.md" in job.error_message
    assert job.finished_at is not None


@pytest.mark.anyio
async def test_import_reingests_failed_document_in_same_library(test_db, tmp_path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.workers import rag_ingest_worker as worker

    class FakeProvider:
        dim = 4

        async def embed(self, texts):
            import numpy as np

            return [np.zeros(4, dtype=np.float32).tobytes() for _ in texts]

    monkeypatch.setattr(worker, "build_embedding_provider", lambda: FakeProvider())
    monkeypatch.setattr(worker, "async_session_factory", test_db)

    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    md = markdown_dir / "a.md"
    md.write_text("# 标题\n\n正文内容", encoding="utf-8")

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="import-heal")
        stuck = await repo.create_document(
            title="卡住的文档", sha256="heal-1", status="failed", library_id=lib.id
        )
        job = await repo.create_job(
            library_id=lib.id,
            kind="import",
            status="queued",
            total=1,
            payload={
                "markdown_root": str(markdown_dir),
                "items": [
                    {
                        "file": "a.md",
                        "title": "卡住的文档",
                        "sha256": "heal-1",
                        "source_site": "测试源",
                    }
                ],
            },
        )
        job_id, doc_id = job.id, stuck.id

    await worker.process_job(job_id)

    async with test_db() as session:
        repo = RagRepository(session)
        doc = await repo.get_document(doc_id)
        finished = await repo.get_job(job_id)
        assert doc.status == "ready" and doc.chunk_count > 0
        assert finished.status == "succeeded" and finished.processed == 1
