from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_create_and_fetch_document(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="文档库")
        doc = await repo.create_document(
            title="小店随心推产品手册",
            doc_type="industry_methodology",
            source_url="https://example.com/a",
            publisher="抖音电商官方学习中心",
            license_note="仅内部知识库使用",
            file_key="markdown/doc1.md",
            sha256="sha-doc-1",
            library_id=lib.id,
        )
        assert doc.id is not None
        assert doc.status == "pending"
        assert doc.chunk_count == 0

        fetched = await repo.get_document(doc.id)
        assert fetched is not None
        assert fetched.title == "小店随心推产品手册"
        assert fetched.publisher == "抖音电商官方学习中心"

        by_sha = await repo.get_document_by_sha256("sha-doc-1")
        assert by_sha is not None
        assert by_sha.id == doc.id
        assert await repo.get_document_by_sha256("missing") is None
        assert await repo.get_document(uuid.uuid4()) is None

        by_ids = await repo.get_documents_by_ids([doc.id])
        assert [d.id for d in by_ids] == [doc.id]


@pytest.mark.anyio
async def test_list_documents_filters_status_and_keyword(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="过滤库")
        await repo.create_document(
            title="千川投放手册", sha256="s-a", status="ready", library_id=lib.id
        )
        await repo.create_document(
            title="巨量引擎入门", sha256="s-b", status="disabled", library_id=lib.id
        )
        await repo.create_document(
            title="千川答疑", sha256="s-c", status="ready", library_id=lib.id
        )

        page = await repo.list_documents(status="ready")
        assert page.total == 2
        assert {d.title for d in page.items} == {"千川投放手册", "千川答疑"}

        by_keyword = await repo.list_documents(keyword="入门")
        assert by_keyword.total == 1
        assert by_keyword.items[0].title == "巨量引擎入门"

        paged = await repo.list_documents(page=2, page_size=2)
        assert paged.total == 3
        assert len(paged.items) == 1


@pytest.mark.anyio
async def test_set_document_status(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="状态库")
        doc = await repo.create_document(
            title="文档", sha256="s-status", library_id=lib.id
        )
        updated = await repo.set_document_status(doc.id, "disabled")
        assert updated is not None
        assert updated.status == "disabled"
        assert (await repo.get_document(doc.id)).status == "disabled"
        assert await repo.set_document_status(uuid.uuid4(), "ready") is None


@pytest.mark.anyio
async def test_add_chunks_lists_and_iterates_embeddings(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="切块库")
        doc = await repo.create_document(
            title="文档", sha256="s-chunks", status="ready", library_id=lib.id
        )
        emb1 = b"\x01\x02\x03\x04"
        emb2 = b"\x05\x06\x07\x08"
        inserted = await repo.add_chunks(
            doc.id,
            [
                ("投放手册 > 出价", "出价策略正文", emb1, 2),
                ("投放手册 > 预算", "预算建议正文", emb2, 2),
            ],
        )
        assert inserted == 2
        assert (await repo.get_document(doc.id)).chunk_count == 2

        chunks = await repo.list_chunks(doc.id)
        assert [c.chunk_index for c in chunks] == [0, 1]
        assert chunks[0].section_path == "投放手册 > 出价"
        assert chunks[1].content == "预算建议正文"

        embeddings = dict(await repo.iter_embeddings())
        assert embeddings == {chunks[0].id: emb1, chunks[1].id: emb2}

        by_ids = await repo.get_chunks_by_ids([chunks[1].id])
        assert [c.id for c in by_ids] == [chunks[1].id]
        assert await repo.get_chunks_by_ids([]) == []


@pytest.mark.anyio
async def test_eval_questions_roundtrip(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="评测库")
        doc = await repo.create_document(
            title="文档", sha256="s-eval", status="ready", library_id=lib.id
        )
        question = await repo.create_eval_question(
            "抖音千川全域投放的出价策略有哪些？", [doc.id]
        )
        assert question.approved_at is None
        assert question.expected_doc_ids == [str(doc.id)]

        items = await repo.list_eval_questions()
        assert [i.id for i in items] == [question.id]


@pytest.mark.anyio
async def test_library_crud_and_stats(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="统计库", description="d")
        assert await repo.get_library_by_name("统计库") is not None

        doc = await repo.create_document(
            title="A", sha256="rs1", status="ready", library_id=lib.id
        )
        await repo.add_chunks(doc.id, [("sec", "内容", b"\x00\x00\x80?", 4)])
        await repo.create_document(
            title="B", sha256="rs2", status="failed", library_id=lib.id
        )

        stats = await repo.library_stats()
        assert stats[lib.id]["doc_count"] == 2
        assert stats[lib.id]["ready_count"] == 1
        assert stats[lib.id]["failed_count"] == 1
        assert stats[lib.id]["chunk_count"] == 1

        assert await repo.clear_chunks(doc.id) == 1
        assert (await repo.get_document(doc.id)).chunk_count == 0

        page = await repo.list_documents(library_id=lib.id, page=1, page_size=10)
        assert page.total == 2

        assert await repo.delete_library(lib.id) is True
        assert await repo.get_library(lib.id) is None


@pytest.mark.anyio
async def test_job_claim_and_progress(test_db):
    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="任务库2")
        job = await repo.create_job(library_id=lib.id, kind="upload", status="queued", total=2)

        claimed = await repo.claim_next_job()
        assert claimed is not None and claimed.id == job.id
        assert claimed.status == "running" and claimed.started_at is not None

        await repo.update_job(job.id, processed=2, status="succeeded")
        updated = await repo.get_job(job.id)
        assert updated.processed == 2 and updated.status == "succeeded"
        assert await repo.list_active_jobs(library_id=lib.id) == []


@pytest.mark.anyio
async def test_requeue_stale_jobs_only_touches_old_running_jobs(test_db):
    from datetime import UTC, datetime, timedelta

    from app.repositories.rag_repository import RagRepository

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="requeue库")
        stale = await repo.create_job(library_id=lib.id, kind="upload", status="running", total=1)
        fresh = await repo.create_job(library_id=lib.id, kind="upload", status="running", total=1)
        stale.started_at = datetime.now(UTC) - timedelta(minutes=90)
        fresh.started_at = datetime.now(UTC)
        await session.commit()

        assert await repo.requeue_stale_jobs(older_than_minutes=30) == 1
        assert (await repo.get_job(stale.id)).status == "queued"
        assert (await repo.get_job(stale.id)).started_at is None
        assert (await repo.get_job(fresh.id)).status == "running"
