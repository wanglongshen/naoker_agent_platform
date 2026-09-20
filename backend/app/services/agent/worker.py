from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.agent import AgentRunAttempt
from app.repositories.agent_repository import AgentRepository
from app.services.agent.event_bus import EventItem, event_bus
from app.services.agent.loop import agent_loop_service, classify_agent_failure
from app.services.agent.retention import RetentionService
from app.services.agent.storage import PrivateObjectStorage
from app.services.observability import (
    WORKER_ACTIVE,
    WORKER_CLAIMED,
    WORKER_ERRORS,
    WORKER_HEARTBEATS,
    WORKER_POLL_LATENCY,
)

logger = logging.getLogger("agent_worker")
settings = get_settings()


class AgentWorker:
    def __init__(self, worker_id: str, concurrency: int) -> None:
        self.worker_id = worker_id
        self.concurrency = concurrency
        self._stop_event = asyncio.Event()
        self._new_run_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task] = set()
        self._engine = None
        self._session_factory = None
        self._heartbeat_task: asyncio.Task | None = None

    async def _listen_new_runs(self) -> None:
        dsn = settings.database_url.replace("+asyncpg", "")
        while not self._stop_event.is_set():
            try:
                conn = await asyncpg.connect(dsn=dsn)
                await conn.add_listener("new_run", lambda *_: self._new_run_event.set())
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
            except Exception:
                logger.warning("worker_new_run_listen_disconnected", exc_info=True)
            finally:
                try:
                    await conn.close()
                except Exception:
                    pass

    async def _heartbeat_loop(self) -> None:
        import time as _time

        while not self._stop_event.is_set():
            WORKER_HEARTBEATS.inc()
            loop_start = _time.monotonic()
            pending = 0
            db_latency_ms = 0.0
            try:
                async with self._session_factory() as session:
                    from sqlalchemy import func, select
                    from app.models.agent import AgentRunAttempt
                    start = _time.monotonic()
                    pending = (
                        await session.execute(
                            select(func.count()).select_from(AgentRunAttempt).where(
                                AgentRunAttempt.status == "queued"
                            )
                        )
                    ).scalar_one()
                    db_latency_ms = round((_time.monotonic() - start) * 1000, 2)
            except Exception:
                pass
            loop_elapsed = (_time.monotonic() - loop_start) * 1000
            logger.info(
                "worker_heartbeat",
                extra={
                    "worker_id": self.worker_id,
                    "pending_attempts": pending,
                    "db_latency_ms": db_latency_ms,
                    "heartbeat_loop_ms": round(loop_elapsed, 2),
                    "uptime_s": int(_time.monotonic()),
                },
            )
            await asyncio.sleep(30)

    async def run(self) -> None:
        database_url = settings.database_url
        self._engine = create_async_engine(database_url, echo=False, pool_size=10, max_overflow=20)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

        loop = asyncio.get_running_loop()

        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: self._stop_event.set())
        else:
            signal.signal(signal.SIGTERM, lambda _sig, _frame: self._stop_event.set())
            signal.signal(signal.SIGINT, lambda _sig, _frame: self._stop_event.set())

        listen_task = asyncio.create_task(self._listen_new_runs())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while not self._stop_event.is_set():
                import time as _time
                _poll_start = _time.monotonic()
                recovered = await self._recover_expired()
                if recovered > 0:
                    pass

                await self._cleanup_attachment_folders()

                claimed = await self._claim_and_execute()
                if not claimed:
                    self._new_run_event.clear()
                    try:
                        await asyncio.wait_for(
                            self._new_run_event.wait(),
                            timeout=settings.worker_poll_interval_seconds,
                        )
                    except asyncio.TimeoutError:
                        pass
                _poll_ms = (_time.monotonic() - _poll_start) * 1000
                WORKER_POLL_LATENCY.observe(_poll_ms)
        finally:
            listen_task.cancel()
            with suppress(asyncio.CancelledError):
                await listen_task
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            await self._shutdown()

    async def _recover_expired(self) -> int:
        try:
            async with self._session_factory() as session:
                repo = AgentRepository(session)
                recovered = await repo.recover_expired_attempts()
                await session.commit()
            async with self._session_factory() as session:
                repo = AgentRepository(session)
                reconciled = 0
                run_ids = await repo.find_reconcilable_completed_answer_run_ids()
                for run_id in run_ids:
                    did = await repo.reconcile_completed_answer_run(run_id)
                    if did:
                        reconciled += 1
                if reconciled > 0:
                    await session.commit()
                return recovered + reconciled
        except Exception:
            return 0

    async def _cleanup_attachment_folders(self) -> None:
        try:
            async with self._session_factory() as session:
                svc = RetentionService(session, PrivateObjectStorage())
                await svc.cleanup_attachment_folders()
                await session.commit()
        except Exception:
            logger.warning("attachment_folder_cleanup_failed", exc_info=True)

    async def _claim_and_execute(self) -> bool:
        if self._semaphore.locked():
            return False
        try:
            async with self._session_factory() as session:
                repo = AgentRepository(session)
                attempt = await repo.claim_next_attempt(self.worker_id)
                await session.commit()
            if attempt is None:
                return False
            WORKER_CLAIMED.inc()
            WORKER_ACTIVE.inc()
            task = asyncio.create_task(self._execute_claimed_attempt(attempt.id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return True
        except Exception:
            return False

    async def _execute_claimed_attempt(self, attempt_id) -> None:
        async with self._semaphore:
            await self._process_attempt_with_renewal(attempt_id)

    async def _process_attempt_with_renewal(self, attempt_id) -> None:
        renewal_task = asyncio.create_task(
            self._renew_lease_until_finished(attempt_id)
        )
        try:
            await agent_loop_service.process_attempt(attempt_id, self.worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure_code = classify_agent_failure(exc)
            WORKER_ERRORS.inc()
            logger.exception(
                "agent_attempt_unhandled attempt_id=%s worker_id=%s failure_code=%s exception_type=%s stage=%s",
                attempt_id,
                self.worker_id,
                failure_code,
                type(exc).__name__,
                "attempt_execution",
                extra={
                    "attempt_id": str(attempt_id),
                    "worker_id": self.worker_id,
                    "failure_code": failure_code,
                    "exception_type": type(exc).__name__,
                    "failure_stage": "attempt_execution",
                },
            )
            await self._mark_unhandled_attempt_failure(attempt_id, failure_code)
        finally:
            renewal_task.cancel()
            with suppress(asyncio.CancelledError):
                await renewal_task
            WORKER_ACTIVE.dec()

    async def _renew_lease_until_finished(self, attempt_id) -> None:
        lease_seconds = settings.worker_lease_seconds
        sleep_interval = max(1, lease_seconds // 3)
        while True:
            await asyncio.sleep(sleep_interval)
            try:
                async with self._session_factory() as session:
                    repo = AgentRepository(session)
                    attempt = await session.get(
                        AgentRunAttempt, attempt_id
                    )
                    if attempt is None or attempt.status != "running":
                        return
                    renewed = await repo.renew_lease(attempt, self.worker_id)
                    await session.commit()
                    if not renewed:
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "agent_lease_renewal_failed",
                    extra={"attempt_id": str(attempt_id), "worker_id": self.worker_id},
                )
                await self._mark_unhandled_attempt_failure(attempt_id)
                return

    async def _mark_unhandled_attempt_failure(
        self, attempt_id, failure_code: str = "worker_unhandled_error"
    ) -> None:
        try:
            async with self._session_factory() as session:
                repo = AgentRepository(session)
                event_ref = await repo.fail_attempt_and_run(
                    attempt_id, self.worker_id, failure_code
                )
                if event_ref is not None:
                    run_id, seq = event_ref
                await session.commit()
            if event_ref is not None:
                await event_bus.publish(
                    EventItem(
                        run_id=run_id, seq=seq,
                        event_type="run_failed",
                        payload={"error": failure_code},
                        created_at=datetime.now(UTC),
                    )
                )
        except Exception as exc:
            logger.error(
                "agent_failure_finalization_failed attempt_id=%s worker_id=%s failure_code=%s exception_type=%s stage=%s",
                attempt_id,
                self.worker_id,
                "worker_failure_finalization_error",
                type(exc).__name__,
                "failure_finalization",
                extra={
                    "attempt_id": str(attempt_id),
                    "worker_id": self.worker_id,
                    "failure_code": "worker_failure_finalization_error",
                    "exception_type": type(exc).__name__,
                    "failure_stage": "failure_finalization",
                },
            )

    async def _process_attempt(self, attempt_id) -> None:
        try:
            await agent_loop_service.process_attempt(attempt_id, self.worker_id)
        except Exception:
            pass

    async def stop(self) -> None:
        self._stop_event.set()

    async def _shutdown(self) -> None:
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=settings.worker_shutdown_grace_seconds,
                )
            except asyncio.TimeoutError:
                pass

        await agent_loop_service.close()

        if self._engine:
            await self._engine.dispose()
