from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import RagChunk, RagDocument, RagEvalSet, RagJob, RagLibrary


class LibraryNameConflict(Exception):
    """知识库名称唯一约束冲突（并发插入）。"""


@dataclass
class Page:
    items: list[Any]
    page: int
    page_size: int
    total: int


class RagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(self, **fields: Any) -> RagDocument:
        doc = RagDocument(**fields)
        self.session.add(doc)
        await self.session.commit()
        return doc

    async def get_document(self, doc_id: uuid.UUID) -> RagDocument | None:
        return await self.session.get(RagDocument, doc_id)

    async def get_document_by_sha256(self, sha256: str) -> RagDocument | None:
        result = await self.session.execute(
            select(RagDocument).where(RagDocument.sha256 == sha256)
        )
        return result.scalar_one_or_none()

    async def get_documents_by_ids(
        self, doc_ids: list[uuid.UUID]
    ) -> list[RagDocument]:
        if not doc_ids:
            return []
        result = await self.session.execute(
            select(RagDocument).where(RagDocument.id.in_(doc_ids))
        )
        return list(result.scalars().all())

    async def list_documents(
        self,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        library_id: uuid.UUID | None = None,
    ) -> Page:
        base = select(RagDocument)
        if library_id is not None:
            base = base.where(RagDocument.library_id == library_id)
        if status:
            base = base.where(RagDocument.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(
                or_(RagDocument.title.ilike(pattern), RagDocument.publisher.ilike(pattern))
            )

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            base.order_by(RagDocument.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def set_document_status(
        self, doc_id: uuid.UUID, status: str
    ) -> RagDocument | None:
        doc = await self.session.get(RagDocument, doc_id)
        if doc is None:
            return None
        doc.status = status
        await self.session.commit()
        return doc

    async def add_chunks(
        self, doc_id: uuid.UUID, chunks: list[tuple[str, str, bytes, int]]
    ) -> int:
        for index, (section_path, content, embedding, embedding_dim) in enumerate(
            chunks
        ):
            self.session.add(
                RagChunk(
                    doc_id=doc_id,
                    chunk_index=index,
                    section_path=section_path,
                    content=content,
                    embedding=embedding,
                    embedding_dim=embedding_dim,
                )
            )
        doc = await self.session.get(RagDocument, doc_id)
        if doc is not None:
            doc.chunk_count = (doc.chunk_count or 0) + len(chunks)
        await self.session.commit()
        return len(chunks)

    async def iter_embeddings(self) -> list[tuple[uuid.UUID, bytes]]:
        result = await self.session.execute(
            select(RagChunk.id, RagChunk.embedding).order_by(RagChunk.id)
        )
        return [(row.id, row.embedding) for row in result.all()]

    async def list_chunks(self, doc_id: uuid.UUID) -> list[RagChunk]:
        result = await self.session.execute(
            select(RagChunk)
            .where(RagChunk.doc_id == doc_id)
            .order_by(RagChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def get_chunks_by_ids(
        self, chunk_ids: list[uuid.UUID]
    ) -> list[RagChunk]:
        if not chunk_ids:
            return []
        result = await self.session.execute(
            select(RagChunk).where(RagChunk.id.in_(chunk_ids))
        )
        return list(result.scalars().all())

    async def list_chunk_ids_for_library(self, library_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(RagChunk.id)
            .join(RagDocument, RagDocument.id == RagChunk.doc_id)
            .where(RagDocument.library_id == library_id)
        )
        return list(result.scalars().all())

    async def create_eval_question(
        self,
        query: str,
        expected_doc_ids: list[uuid.UUID],
        created_by: uuid.UUID | None = None,
    ) -> RagEvalSet:
        item = RagEvalSet(
            query=query,
            expected_doc_ids=[str(doc_id) for doc_id in expected_doc_ids],
            created_by=created_by,
        )
        self.session.add(item)
        await self.session.commit()
        return item

    async def list_eval_questions(self) -> list[RagEvalSet]:
        result = await self.session.execute(
            select(RagEvalSet).order_by(RagEvalSet.created_at)
        )
        return list(result.scalars().all())

    async def create_library(self, **fields: Any) -> RagLibrary:
        lib = RagLibrary(**fields)
        self.session.add(lib)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise LibraryNameConflict(str(exc)) from exc
        return lib

    async def get_library(self, library_id: uuid.UUID) -> RagLibrary | None:
        return await self.session.get(RagLibrary, library_id)

    async def get_library_by_name(self, name: str) -> RagLibrary | None:
        result = await self.session.execute(
            select(RagLibrary).where(RagLibrary.name == name)
        )
        return result.scalar_one_or_none()

    async def list_libraries(self) -> list[RagLibrary]:
        result = await self.session.execute(select(RagLibrary).order_by(RagLibrary.created_at))
        return list(result.scalars().all())

    async def update_library(self, library_id: uuid.UUID, **fields: Any) -> RagLibrary | None:
        lib = await self.session.get(RagLibrary, library_id)
        if lib is None:
            return None
        for key, value in fields.items():
            setattr(lib, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise LibraryNameConflict(str(exc)) from exc
        return lib

    async def delete_library(self, library_id: uuid.UUID) -> bool:
        lib = await self.session.get(RagLibrary, library_id)
        if lib is None:
            return False
        await self.session.delete(lib)
        await self.session.commit()
        return True

    async def get_libraries_by_ids(self, library_ids: list[uuid.UUID]) -> list[RagLibrary]:
        if not library_ids:
            return []
        result = await self.session.execute(
            select(RagLibrary).where(RagLibrary.id.in_(library_ids))
        )
        return list(result.scalars().all())

    async def library_stats(self) -> dict[uuid.UUID, dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(
                    RagDocument.library_id,
                    func.count(RagDocument.id),
                    func.coalesce(func.sum(RagDocument.chunk_count), 0),
                    func.count(RagDocument.id).filter(RagDocument.status == "ready"),
                    func.count(RagDocument.id).filter(RagDocument.status == "failed"),
                    func.max(RagDocument.updated_at),
                ).group_by(RagDocument.library_id)
            )
        ).all()
        return {
            row[0]: {
                "doc_count": int(row[1]),
                "chunk_count": int(row[2]),
                "ready_count": int(row[3]),
                "failed_count": int(row[4]),
                "last_updated_at": row[5],
            }
            for row in rows
        }

    async def delete_document(self, doc_id: uuid.UUID) -> bool:
        doc = await self.session.get(RagDocument, doc_id)
        if doc is None:
            return False
        await self.session.delete(doc)
        await self.session.commit()
        return True

    async def clear_chunks(self, doc_id: uuid.UUID) -> int:
        result = await self.session.execute(
            delete(RagChunk).where(RagChunk.doc_id == doc_id)
        )
        doc = await self.session.get(RagDocument, doc_id)
        if doc is not None:
            doc.chunk_count = 0
        await self.session.commit()
        return int(result.rowcount or 0)

    async def list_chunks_page(
        self, doc_id: uuid.UUID, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[RagChunk], int]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(RagChunk).where(RagChunk.doc_id == doc_id)
            )
        ).scalar_one()
        result = await self.session.execute(
            select(RagChunk)
            .where(RagChunk.doc_id == doc_id)
            .order_by(RagChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total)

    async def create_job(self, **fields: Any) -> RagJob:
        job = RagJob(**fields)
        self.session.add(job)
        await self.session.commit()
        return job

    async def get_job(self, job_id: uuid.UUID) -> RagJob | None:
        return await self.session.get(RagJob, job_id)

    async def claim_next_job(self) -> RagJob | None:
        result = await self.session.execute(
            select(RagJob)
            .where(RagJob.status == "queued")
            .order_by(RagJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job is None:
            await self.session.rollback()
            return None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await self.session.commit()
        return job

    async def update_job(self, job_id: uuid.UUID, **fields: Any) -> RagJob | None:
        job = await self.session.get(RagJob, job_id)
        if job is None:
            return None
        for key, value in fields.items():
            setattr(job, key, value)
        await self.session.commit()
        return job

    async def list_active_jobs(self, library_id: uuid.UUID | None = None) -> list[RagJob]:
        query = select(RagJob).where(RagJob.status.in_(["queued", "running"]))
        if library_id is not None:
            query = query.where(RagJob.library_id == library_id)
        result = await self.session.execute(query.order_by(RagJob.created_at))
        return list(result.scalars().all())

    async def requeue_stale_jobs(self, *, older_than_minutes: int = 30) -> int:
        """把 worker 中断遗留的 running 任务重新排队（无租约机制下的兜底）。"""
        cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        result = await self.session.execute(
            update(RagJob)
            .where(
                RagJob.status == "running",
                RagJob.started_at.is_not(None),
                RagJob.started_at < cutoff,
            )
            .values(status="queued", started_at=None, error_message="worker 中断，已重新排队")
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def list_jobs(self, library_id: uuid.UUID | None = None) -> list[RagJob]:
        query = select(RagJob)
        if library_id is not None:
            query = query.where(RagJob.library_id == library_id)
        result = await self.session.execute(query.order_by(RagJob.created_at.desc()).limit(50))
        return list(result.scalars().all())
