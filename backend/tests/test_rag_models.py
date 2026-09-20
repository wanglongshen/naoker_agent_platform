from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.rag import RagDocument, RagJob, RagLibrary


@pytest.mark.anyio
async def test_library_and_document_relation(test_db):
    async with test_db() as session:
        lib = RagLibrary(name="测试库", description="desc", kind="custom")
        session.add(lib)
        await session.commit()

        doc = RagDocument(
            title="文档A",
            sha256="m1",
            status="ready",
            library_id=lib.id,
        )
        session.add(doc)
        await session.commit()

        row = (await session.execute(select(RagDocument).where(RagDocument.id == doc.id))).scalar_one()
        assert row.library_id == lib.id
        assert row.error_message is None


@pytest.mark.anyio
async def test_job_defaults(test_db):
    async with test_db() as session:
        lib = RagLibrary(name="任务库")
        session.add(lib)
        await session.commit()

        job = RagJob(library_id=lib.id, kind="upload", status="queued", total=1)
        session.add(job)
        await session.commit()

        row = (await session.execute(select(RagJob).where(RagJob.id == job.id))).scalar_one()
        assert row.processed == 0
        assert row.started_at is None
        assert row.doc_id is None
