from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, TypeVar

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import (
    AgentAttachment,
    AgentRun,
    AgentRunAttachment,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
    AgentStep,
    agent_run_events_seq,
)
from app.models.file import FileObject

T = TypeVar("T")


@dataclass
class Page:
    items: list[Any]
    page: int
    page_size: int
    total: int


settings = get_settings()


class AgentRepository:
    def __init__(
        self,
        session: AsyncSession,
        storage: "PrivateObjectStorage | None" = None,
    ) -> None:
        if storage is None:
            from app.services.agent.storage import PrivateObjectStorage

            storage = PrivateObjectStorage()
        self.session = session
        self._storage = storage

    async def create_session(self, owner_user_id: uuid.UUID, title: str | None) -> AgentSession:
        session = AgentSession(owner_user_id=owner_user_id, title=title)
        self.session.add(session)
        await self.session.flush()
        return session

    async def get_owned_session(self, session_id: uuid.UUID, owner_user_id: uuid.UUID) -> AgentSession | None:
        result = await self.session.execute(
            select(AgentSession).where(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_session(self, session_id: uuid.UUID) -> AgentSession | None:
        return await self.session.get(AgentSession, session_id)

    async def list_owned_sessions(self, owner_user_id: uuid.UUID, page: int, page_size: int) -> Page:
        count_q = select(func.count()).select_from(AgentSession).where(
            AgentSession.owner_user_id == owner_user_id
        )
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            select(AgentSession)
            .where(AgentSession.owner_user_id == owner_user_id)
            .order_by(
                AgentSession.is_pinned.desc(),
                AgentSession.updated_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def delete_session(self, session_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
        attachment_keys = (
            await self.session.execute(
                select(AgentAttachment.storage_key).where(
                    AgentAttachment.session_id == session_id
                )
            )
        ).scalars().all()

        if attachment_keys:
            await self.session.execute(
                delete(AgentAttachment).where(AgentAttachment.session_id == session_id)
            )
            await self.session.execute(
                update(FileObject)
                .where(FileObject.storage_key.in_(attachment_keys))
                .values(is_deleted=True)
            )
            for key in attachment_keys:
                try:
                    await self._storage.delete(key)
                except Exception:
                    pass

        run_ids = (
            await self.session.execute(
                select(AgentRun.id).where(AgentRun.session_id == session_id)
            )
        ).scalars().all()

        for run_id in run_ids:
            await self.session.execute(
                delete(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
            )
            await self.session.execute(
                delete(AgentStep).where(AgentStep.attempt_id.in_(
                    select(AgentRunAttempt.id).where(AgentRunAttempt.run_id == run_id)
                ))
            )
            await self.session.execute(
                delete(AgentRunAttempt).where(AgentRunAttempt.run_id == run_id)
            )
            await self.session.execute(
                delete(AgentRunAttachment).where(AgentRunAttachment.run_id == run_id)
            )

        await self.session.execute(
            delete(AgentRun).where(AgentRun.session_id == session_id)
        )
        await self.session.execute(
            delete(AgentSession).where(
                AgentSession.id == session_id,
                AgentSession.owner_user_id == owner_user_id,
            )
        )

    async def list_runs_for_session(self, session_id: uuid.UUID) -> list[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_recent_session_history(self, session_id: uuid.UUID, limit: int = 6) -> list[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.asc())
        )
        runs = list(result.scalars().all())
        return runs[-limit:]

    async def get_run(self, run_id: uuid.UUID) -> AgentRun | None:
        return await self.session.get(AgentRun, run_id)

    async def get_owned_run(self, run_id: uuid.UUID, owner_user_id: uuid.UUID) -> AgentRun | None:
        result = await self.session.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.owner_user_id == owner_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_owned_runs(
        self, owner_user_id: uuid.UUID, page: int, page_size: int
    ) -> Page:
        count_q = (
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.owner_user_id == owner_user_id)
        )
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.owner_user_id == owner_user_id)
            .order_by(AgentRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def create_run_with_attempt(
        self,
        session: AgentSession,
        goal: str,
        network_enabled: bool,
        attachment_ids: list[uuid.UUID],
        mode: str = "expert",
    ) -> tuple[AgentRun, AgentRunAttempt, AgentRunEvent]:
        run = AgentRun(
            session_id=session.id,
            owner_user_id=session.owner_user_id,
            goal=goal,
            mode=mode,
            network_enabled=network_enabled,
            status="queued",
        )
        self.session.add(run)
        await self.session.flush()

        attempt = AgentRunAttempt(
            run_id=run.id,
            attempt_number=1,
            status="queued",
        )
        self.session.add(attempt)
        await self.session.flush()

        run.current_attempt_id = attempt.id
        self.session.add(run)

        event = AgentRunEvent(
            run_id=run.id,
            attempt_id=attempt.id,
            event_type="run_queued",
            payload={"goal": goal, "mode": mode, "network_enabled": network_enabled},
        )
        self.session.add(event)
        await self.session.flush()

        for attachment_id in attachment_ids:
            ra = AgentRunAttachment(run_id=run.id, attachment_id=attachment_id)
            self.session.add(ra)

        session.last_run_id = run.id
        session.updated_at = datetime.now(UTC)
        self.session.add(session)
        await self.session.flush()

        return run, attempt, event

    async def create_retry_attempt(self, run: AgentRun) -> AgentRunAttempt:
        max_num_result = await self.session.execute(
            select(func.coalesce(func.max(AgentRunAttempt.attempt_number), 0))
            .where(AgentRunAttempt.run_id == run.id)
        )
        max_num = max_num_result.scalar_one()
        new_number = max_num + 1

        attempt = AgentRunAttempt(
            run_id=run.id,
            attempt_number=new_number,
            status="queued",
            retry_of_attempt_id=run.current_attempt_id,
        )
        self.session.add(attempt)
        await self.session.flush()

        run.current_attempt_id = attempt.id
        run.status = "queued"
        self.session.add(run)
        await self.session.flush()

        return attempt

    async def mark_run_awaiting_question(
        self, run: AgentRun, questions: list[dict[str, str]]
    ) -> None:
        run.pending_questions = questions
        run.status = "awaiting_question"
        run.updated_at = datetime.now(UTC)
        self.session.add(run)
        await self.session.flush()

    async def resume_run_from_answer(
        self, run: AgentRun, answers: dict[str, str]
    ) -> None:
        run.pending_questions = None
        run.result = {
            **(run.result or {}),
            "answers": answers,
            "resumed_after_question": True,
        }
        run.status = "queued"
        run.updated_at = datetime.now(UTC)
        self.session.add(run)
        await self.session.flush()

    async def create_resume_attempt(self, run: AgentRun) -> AgentRunAttempt:
        max_num_result = await self.session.execute(
            select(func.coalesce(func.max(AgentRunAttempt.attempt_number), 0))
            .where(AgentRunAttempt.run_id == run.id)
        )
        max_num = max_num_result.scalar_one()
        new_number = max_num + 1

        attempt = AgentRunAttempt(
            run_id=run.id,
            attempt_number=new_number,
            status="queued",
        )
        self.session.add(attempt)
        await self.session.flush()

        run.current_attempt_id = attempt.id
        run.status = "queued"
        self.session.add(run)
        await self.session.flush()

        return attempt

    async def schedule_retry_attempt(
        self, run: AgentRun, failed_attempt: AgentRunAttempt, error: str
    ) -> AgentRunAttempt:
        retry_number = failed_attempt.attempt_number
        delay_seconds = min(
            settings.retry_backoff_base_seconds * (2 ** max(retry_number - 1, 0)),
            settings.retry_backoff_max_seconds,
        )
        not_before = datetime.now(UTC) + timedelta(seconds=delay_seconds)

        attempt = AgentRunAttempt(
            run_id=run.id,
            attempt_number=retry_number + 1,
            status="queued",
            retry_of_attempt_id=failed_attempt.id,
            not_before=not_before,
        )
        self.session.add(attempt)
        await self.session.flush()

        run.current_attempt_id = attempt.id
        run.status = "retry_wait"
        self.session.add(run)
        await self.session.flush()

        return attempt

    async def append_event(
        self,
        run: AgentRun,
        attempt: AgentRunAttempt | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> AgentRunEvent:
        result = await self.session.execute(
            insert(AgentRunEvent)
            .values(
                run_id=run.id,
                attempt_id=attempt.id if attempt else None,
                event_type=event_type,
                payload=payload,
                seq=agent_run_events_seq.next_value(),
            )
            .returning(AgentRunEvent)
        )
        event = result.scalar_one()
        await self.session.flush()
        return event

    async def list_events_after_seq(
        self, run_id: uuid.UUID, after_seq: int | None, limit: int
    ) -> list[AgentRunEvent]:
        stmt = select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
        if after_seq is not None:
            stmt = stmt.where(AgentRunEvent.seq > after_seq)
        stmt = stmt.order_by(AgentRunEvent.seq.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_events(self, run_id: uuid.UUID) -> list[AgentRunEvent]:
        result = await self.session.execute(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id)
            .order_by(AgentRunEvent.seq.asc())
        )
        return list(result.scalars().all())

    async def list_attempts(self, run_id: uuid.UUID) -> list[AgentRunAttempt]:
        result = await self.session.execute(
            select(AgentRunAttempt)
            .where(AgentRunAttempt.run_id == run_id)
            .order_by(AgentRunAttempt.attempt_number.asc())
        )
        return list(result.scalars().all())

    async def list_steps(self, attempt_id: uuid.UUID) -> list[AgentStep]:
        result = await self.session.execute(
            select(AgentStep)
            .where(AgentStep.attempt_id == attempt_id)
            .order_by(AgentStep.step_number.asc())
        )
        return list(result.scalars().all())

    async def get_steps_for_run_attempt(
        self, run_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> list[AgentStep] | None:
        attempt = await self.session.scalar(
            select(AgentRunAttempt).where(
                AgentRunAttempt.id == attempt_id,
                AgentRunAttempt.run_id == run_id,
            )
        )
        if attempt is None:
            return None
        return await self.list_steps(attempt.id)

    async def add_step(
        self,
        attempt_id: uuid.UUID,
        step_number: int,
        thought_summary: str,
        action_type: str,
        action_payload: dict | None,
        observation: dict[str, Any] | None,
        status: str,
    ) -> AgentStep:
        step = AgentStep(
            attempt_id=attempt_id,
            step_number=step_number,
            thought_summary=thought_summary,
            action_type=action_type,
            action_payload=action_payload,
            observation=observation,
            status=status,
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def _transition_run_status(
        self,
        run: AgentRun,
        from_statuses: set[str],
        to_status: str,
    ) -> bool:
        result = await self.session.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id, AgentRun.status.in_(from_statuses))
            .values(status=to_status, updated_at=datetime.now(UTC))
        )
        if result.rowcount == 0:
            return False
        await self.session.refresh(run)
        return True

    async def mark_run_running(self, run: AgentRun) -> bool:
        return await self._transition_run_status(run, {"queued", "retry_wait"}, "running")

    async def mark_run_succeeded(self, run: AgentRun) -> bool:
        return await self._transition_run_status(run, {"running"}, "succeeded")

    async def mark_run_failed(self, run: AgentRun) -> bool:
        return await self._transition_run_status(run, {"running"}, "failed")

    async def mark_run_retry_wait(self, run: AgentRun) -> bool:
        return await self._transition_run_status(run, {"running"}, "retry_wait")

    async def request_cancel(self, run: AgentRun) -> bool:
        return await self._transition_run_status(
            run, {"queued", "running", "retry_wait"}, "cancel_requested"
        )

    async def cancel_queued_run(self, run: AgentRun) -> bool:
        return await self._transition_run_status(
            run, {"queued", "retry_wait"}, "cancelled"
        )

    async def mark_run_cancelled(self, run: AgentRun) -> bool:
        return await self._transition_run_status(run, {"cancel_requested"}, "cancelled")

    async def is_cancel_requested(self, run_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(AgentRun.status).where(AgentRun.id == run_id)
        )
        status = result.scalar_one_or_none()
        return status == "cancel_requested"

    async def transition_attempt_status(
        self,
        attempt: AgentRunAttempt,
        from_statuses: set[str],
        to_status: str,
        **extra_fields: Any,
    ) -> bool:
        values: dict[str, Any] = {"status": to_status, "updated_at": datetime.now(UTC), **extra_fields}
        result = await self.session.execute(
            update(AgentRunAttempt)
            .where(AgentRunAttempt.id == attempt.id, AgentRunAttempt.status.in_(from_statuses))
            .values(**values)
        )
        if result.rowcount == 0:
            return False
        await self.session.refresh(attempt)
        return True

    async def claim_next_attempt(self, worker_id: str) -> AgentRunAttempt | None:
        lease_seconds = settings.worker_lease_seconds
        now = datetime.now(UTC)
        lease_expires = now + timedelta(seconds=lease_seconds)

        subq = (
            select(AgentRunAttempt.id)
            .where(
                AgentRunAttempt.status == "queued",
                AgentRunAttempt.run_id.in_(
                    select(AgentRun.id).where(
                        AgentRun.status.in_(["queued", "retry_wait"])
                    )
                ),
            )
            .where(
                (AgentRunAttempt.not_before == None) | (AgentRunAttempt.not_before <= now)
            )
            .order_by(AgentRunAttempt.created_at.asc())
            .limit(1)
            .scalar_subquery()
        )

        result = await self.session.execute(
            update(AgentRunAttempt)
            .where(AgentRunAttempt.id == subq)
            .values(
                status="running",
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_expires,
                started_at=now,
                updated_at=now,
            )
            .returning(AgentRunAttempt)
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            return None

        await self.session.execute(
            update(AgentRun)
            .where(AgentRun.id == attempt.run_id, AgentRun.status.in_(["queued", "retry_wait"]))
            .values(status="running", updated_at=now)
        )
        await self.session.refresh(attempt)
        return attempt

    async def renew_lease(self, attempt: AgentRunAttempt, worker_id: str) -> bool:
        lease_seconds = settings.worker_lease_seconds
        now = datetime.now(UTC)
        lease_expires = now + timedelta(seconds=lease_seconds)

        result = await self.session.execute(
            update(AgentRunAttempt)
            .where(
                AgentRunAttempt.id == attempt.id,
                AgentRunAttempt.worker_id == worker_id,
                AgentRunAttempt.status == "running",
            )
            .values(lease_expires_at=lease_expires, updated_at=now)
        )
        if result.rowcount == 0:
            return False
        await self.session.refresh(attempt)
        return True

    async def fail_attempt_and_run(
        self, attempt_id: uuid.UUID, worker_id: str, failure_code: str
    ) -> tuple[uuid.UUID, int] | None:
        now = datetime.now(UTC)
        attempt_result = await self.session.execute(
            update(AgentRunAttempt).where(
                AgentRunAttempt.id == attempt_id,
                AgentRunAttempt.worker_id == worker_id,
                AgentRunAttempt.status == "running",
            ).values(
                status="failed",
                failure_code=failure_code,
                finished_at=now,
                updated_at=now,
            ).returning(AgentRunAttempt.run_id)
        )
        run_id = attempt_result.scalar_one_or_none()
        if run_id is None:
            return None

        run_result = await self.session.execute(
            update(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.status.not_in(["succeeded", "failed", "cancelled"]),
            ).values(status="failed", updated_at=now).returning(AgentRun.id)
        )
        if run_result.scalar_one_or_none() is None:
            return None

        event_result = await self.session.execute(
            insert(AgentRunEvent).values(
                run_id=run_id,
                attempt_id=attempt_id,
                event_type="run_failed",
                payload={"error": failure_code},
            ).returning(AgentRunEvent.seq)
        )
        return run_id, event_result.scalar_one()

    async def recover_expired_attempts(self, now: datetime | None = None) -> int:
        if now is None:
            now = datetime.now(UTC)
        recovered = 0

        expired_attempts = await self.session.execute(
            select(AgentRunAttempt)
            .where(
                AgentRunAttempt.status == "running",
                AgentRunAttempt.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
        for attempt in expired_attempts.scalars().all():
            if attempt.attempt_number >= settings.max_retry_attempts:
                await self.session.execute(
                    update(AgentRunAttempt)
                    .where(AgentRunAttempt.id == attempt.id)
                    .values(
                        status="failed",
                        failure_code="lease_expired_no_retry",
                        finished_at=now,
                        updated_at=now,
                    )
                )
                await self.session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == attempt.run_id)
                    .values(status="failed", updated_at=now)
                )
            else:
                await self.session.execute(
                    update(AgentRunAttempt)
                    .where(AgentRunAttempt.id == attempt.id)
                    .values(
                        status="failed",
                        failure_code="lease_expired",
                        finished_at=now,
                        updated_at=now,
                    )
                )

                retry_delay_seconds = min(
                    settings.retry_backoff_base_seconds * (2 ** max(attempt.attempt_number - 1, 0)),
                    settings.retry_backoff_max_seconds,
                )
                retry_not_before = now + timedelta(seconds=retry_delay_seconds)

                new_attempt = AgentRunAttempt(
                    run_id=attempt.run_id,
                    attempt_number=attempt.attempt_number + 1,
                    status="queued",
                    retry_of_attempt_id=attempt.id,
                    not_before=retry_not_before,
                )
                self.session.add(new_attempt)
                await self.session.flush()

                await self.session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == attempt.run_id)
                    .values(status="retry_wait", current_attempt_id=new_attempt.id, updated_at=now)
                )
            recovered += 1

        return recovered

    async def find_reconcilable_completed_answer_run_ids(self) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        answer_sub = (
            select(AgentRunEvent.run_id)
            .where(
                AgentRunEvent.event_type == "answer_completed",
                AgentRunEvent.run_id == AgentRun.id,
                AgentRunEvent.payload["text"].as_string() != "",
                AgentRunEvent.payload["text"].as_string() != None,
            )
            .correlate(AgentRun)
        )
        run_succeeded_sub = (
            select(AgentRunEvent.id)
            .where(
                AgentRunEvent.run_id == AgentRun.id,
                AgentRunEvent.event_type == "run_succeeded",
            )
            .correlate(AgentRun)
            .limit(1)
        )

        stmt = (
            select(AgentRun.id)
            .join(AgentRunAttempt, AgentRunAttempt.id == AgentRun.current_attempt_id)
            .where(
                AgentRun.status.in_(["running", "queued", "retry_wait"]),
                AgentRun.current_attempt_id.isnot(None),
                AgentRun.id.in_(answer_sub),
                ~run_succeeded_sub.exists(),
                (
                    (AgentRunAttempt.lease_expires_at != None) & (AgentRunAttempt.lease_expires_at < now)
                )
                | (AgentRunAttempt.worker_id.is_(None)),
            )
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def reconcile_completed_answer_run(self, run_id: uuid.UUID) -> bool:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            return False

        if run.status not in ("running", "queued", "retry_wait"):
            return False

        if run.current_attempt_id is None:
            return False

        attempt = await self.session.get(AgentRunAttempt, run.current_attempt_id)
        if attempt is None:
            return False

        now = datetime.now(UTC)
        lease_expired = (
            attempt.lease_expires_at is not None and attempt.lease_expires_at < now
        )
        no_worker = attempt.worker_id is None
        if not (lease_expired or no_worker):
            return False

        answer_event_result = await self.session.execute(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.event_type == "answer_completed",
            )
            .order_by(AgentRunEvent.seq.desc())
            .limit(1)
        )
        answer_event = answer_event_result.scalar_one_or_none()
        if answer_event is None:
            return False

        if answer_event.attempt_id != attempt.id:
            return False

        answer_text = (
            answer_event.payload.get("text", "") if answer_event.payload else ""
        )
        if not answer_text or not answer_text.strip():
            return False

        run_succeeded_result = await self.session.execute(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.event_type == "run_succeeded",
            )
            .limit(1)
        )
        if run_succeeded_result.scalar_one_or_none() is not None:
            return False

        attempt.status = "succeeded"
        attempt.finished_at = now
        attempt.updated_at = now
        self.session.add(attempt)

        run.status = "succeeded"
        run.result = {
            "final_answer": answer_text,
            "answer_format": "markdown",
            "completed_at": now.isoformat(),
            "source_event_sequence": answer_event.seq,
        }
        run.updated_at = now
        self.session.add(run)

        run_succeeded_event = await self.append_event(
            run, attempt, "run_succeeded", {"final_answer": answer_text}
        )

        return True
