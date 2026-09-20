import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import (
    AgentAttachment,
    AgentRetentionJob,
    AgentRun,
    AgentRunAttachment,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
    AgentStep,
)
from app.models.file import FileFolder, FileObject
from app.services.agent.storage import PrivateObjectStorage

settings = get_settings()


@dataclass
class RetentionResult:
    deleted_attachments: int = 0
    deleted_run_attachments: int = 0
    deleted_events: int = 0
    deleted_steps: int = 0
    deleted_attempts: int = 0
    deleted_runs: int = 0
    deleted_sessions: int = 0
    errors: list[str] = field(default_factory=list)


class RetentionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: PrivateObjectStorage,
        batch_size: int = 50,
    ) -> None:
        self._session = session
        self._storage = storage
        self._batch_size = batch_size

    async def run_once(self, now: datetime, batch_size: int | None = None) -> RetentionResult:
        if batch_size is not None:
            self._batch_size = batch_size

        result = RetentionResult()
        job = AgentRetentionJob(
            id=uuid.uuid4(),
            job_type="daily_retention",
            started_at=now,
        )
        self._session.add(job)
        await self._session.flush()

        try:
            result.deleted_attachments = await self.cleanup_attachment_folders()

            run_cutoff = now - timedelta(days=settings.agent_run_retention_days)
            await self._delete_run_attachments(run_cutoff, result)
            await self._delete_events(run_cutoff, result)
            await self._delete_steps(run_cutoff, result)
            await self._delete_attempts(run_cutoff, result)
            await self._delete_runs(run_cutoff, result)
            await self._delete_orphaned_sessions(result)

            job.completed_at = datetime.now(UTC)
            job.stats = {
                "deleted_attachments": result.deleted_attachments,
                "deleted_run_attachments": result.deleted_run_attachments,
                "deleted_events": result.deleted_events,
                "deleted_steps": result.deleted_steps,
                "deleted_attempts": result.deleted_attempts,
                "deleted_runs": result.deleted_runs,
                "deleted_sessions": result.deleted_sessions,
            }
            if result.errors:
                job.error_summary = "; ".join(result.errors[:10])
            self._session.add(job)
            await self._session.flush()
        except Exception as exc:
            result.errors.append(str(exc))
            job.error_summary = str(exc)
            self._session.add(job)
            await self._session.flush()

        return result

    async def _delete_run_attachments(self, cutoff: datetime, result: RetentionResult) -> None:
        while True:
            subq = (
                select(AgentRunAttachment.run_id, AgentRunAttachment.attachment_id)
                .join(AgentRun, AgentRun.id == AgentRunAttachment.run_id)
                .where(AgentRun.created_at < cutoff)
                .limit(self._batch_size)
                .subquery()
            )
            batch_result = await self._session.execute(
                select(subq.c.run_id, subq.c.attachment_id)
            )
            rows = batch_result.all()
            if not rows:
                break

            run_ids = {row.run_id for row in rows}
            delete_result = await self._session.execute(
                delete(AgentRunAttachment).where(
                    AgentRunAttachment.run_id.in_(run_ids)
                )
            )
            result.deleted_run_attachments += delete_result.rowcount
            await self._session.flush()

    async def _delete_events(self, cutoff: datetime, result: RetentionResult) -> None:
        while True:
            subq = (
                select(AgentRunEvent.id)
                .join(AgentRun, AgentRun.id == AgentRunEvent.run_id)
                .where(AgentRun.created_at < cutoff)
                .limit(self._batch_size)
                .subquery()
            )
            delete_result = await self._session.execute(
                delete(AgentRunEvent).where(
                    AgentRunEvent.id.in_(select(subq.c.id))
                )
            )
            count = delete_result.rowcount
            if count == 0:
                break
            result.deleted_events += count
            await self._session.flush()

    async def _delete_steps(self, cutoff: datetime, result: RetentionResult) -> None:
        while True:
            subq = (
                select(AgentStep.id)
                .join(AgentRunAttempt, AgentRunAttempt.id == AgentStep.attempt_id)
                .join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
                .where(AgentRun.created_at < cutoff)
                .limit(self._batch_size)
                .subquery()
            )
            delete_result = await self._session.execute(
                delete(AgentStep).where(
                    AgentStep.id.in_(select(subq.c.id))
                )
            )
            count = delete_result.rowcount
            if count == 0:
                break
            result.deleted_steps += count
            await self._session.flush()

    async def _delete_attempts(self, cutoff: datetime, result: RetentionResult) -> None:
        while True:
            subq = (
                select(AgentRunAttempt.id)
                .join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
                .where(AgentRun.created_at < cutoff)
                .limit(self._batch_size)
                .subquery()
            )
            delete_result = await self._session.execute(
                delete(AgentRunAttempt).where(
                    AgentRunAttempt.id.in_(select(subq.c.id))
                )
            )
            count = delete_result.rowcount
            if count == 0:
                break
            result.deleted_attempts += count
            await self._session.flush()

    async def _delete_runs(self, cutoff: datetime, result: RetentionResult) -> None:
        while True:
            subq = (
                select(AgentRun.id)
                .where(AgentRun.created_at < cutoff)
                .limit(self._batch_size)
                .subquery()
            )
            delete_result = await self._session.execute(
                delete(AgentRun).where(
                    AgentRun.id.in_(select(subq.c.id))
                )
            )
            count = delete_result.rowcount
            if count == 0:
                break
            result.deleted_runs += count
            await self._session.flush()

    async def cleanup_attachment_folders(self) -> int:
        """删除用户"附件"文件夹中无对应 AgentAttachment 的孤儿文件（记录软删 + storage 删除）。"""
        folder_ids = (
            await self._session.execute(
                select(FileFolder.id).where(
                    FileFolder.name == "附件",
                    FileFolder.parent_folder_id.is_(None),
                    FileFolder.is_deleted == False,
                )
            )
        ).scalars().all()
        if not folder_ids:
            return 0

        attached_keys = select(AgentAttachment.storage_key)
        orphans = (
            await self._session.execute(
                select(FileObject).where(
                    FileObject.folder_id.in_(folder_ids),
                    FileObject.is_deleted == False,
                    FileObject.storage_key.not_in(attached_keys),
                )
            )
        ).scalars().all()

        deleted = 0
        for file_obj in orphans:
            try:
                await self._storage.delete(file_obj.storage_key)
            except Exception:
                pass
            file_obj.is_deleted = True
            deleted += 1
        await self._session.flush()
        return deleted

    async def _delete_orphaned_sessions(self, result: RetentionResult) -> None:
        while True:
            orphaned_result = await self._session.execute(
                select(AgentSession.id)
                .outerjoin(AgentRun, AgentRun.session_id == AgentSession.id)
                .group_by(AgentSession.id)
                .having(func.count(AgentRun.id) == 0)
                .limit(self._batch_size)
            )
            session_ids = [row[0] for row in orphaned_result.all()]
            if not session_ids:
                break

            delete_result = await self._session.execute(
                delete(AgentSession).where(
                    AgentSession.id.in_(session_ids)
                )
            )
            result.deleted_sessions += delete_result.rowcount
            await self._session.flush()
