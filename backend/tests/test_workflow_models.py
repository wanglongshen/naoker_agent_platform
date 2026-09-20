import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.workflow import WorkflowDocSummary


class TestWorkflowDocSummary:
    async def test_create_and_read_back(self, test_db):
        async with test_db() as s:
            row = WorkflowDocSummary(
                doc_path="00_Agent规范与模板/蓝图.md",
                file_updated_at="2026-08-03T00:00:00+00:00",
                file_sha256="abc",
                summary="强制规则摘要",
                status="ready",
                failure_count=0,
                distilled_at=datetime.now(UTC),
            )
            s.add(row)
            await s.commit()

        async with test_db() as s:
            fetched = await s.scalar(
                select(WorkflowDocSummary).where(
                    WorkflowDocSummary.doc_path == "00_Agent规范与模板/蓝图.md"
                )
            )
            assert fetched is not None
            assert fetched.summary == "强制规则摘要"
            assert fetched.status == "ready"

    async def test_upsert_overwrites_same_path(self, test_db):
        async with test_db() as s:
            s.add(WorkflowDocSummary(doc_path="p", file_updated_at="a", file_sha256="s1", summary="v1"))
            await s.commit()

        async with test_db() as s:
            existing = await s.scalar(select(WorkflowDocSummary).where(WorkflowDocSummary.doc_path == "p"))
            existing.file_updated_at = "b"
            existing.file_sha256 = "s2"
            existing.summary = "v2"
            existing.distilled_at = datetime.now(UTC)
            await s.commit()

        async with test_db() as s:
            rows = (await s.scalars(select(WorkflowDocSummary).where(WorkflowDocSummary.doc_path == "p"))).all()
            assert len(rows) == 1
            assert rows[0].summary == "v2"
            assert rows[0].file_sha256 == "s2"
