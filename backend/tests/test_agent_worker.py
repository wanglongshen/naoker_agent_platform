import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.agent import AgentRun, AgentRunAttempt, AgentRunEvent, AgentSession
from app.models.rbac import User
from app.repositories.agent_repository import AgentRepository
from app.services.agent.llm import ProviderConfigurationError


@pytest.fixture
async def queued_attempt(session, seeded_user) -> AgentRunAttempt:
    agent_session = AgentSession(owner_user_id=seeded_user.id, title="queued attempt test")
    session.add(agent_session)
    await session.flush()
    repo = AgentRepository(session)
    run, attempt, _ = await repo.create_run_with_attempt(
        agent_session, "queued attempt goal", True, [], "quick"
    )
    await session.flush()
    return attempt


@pytest.fixture
async def queued_session(session, seeded_user) -> AgentSession:
    agent_session = AgentSession(owner_user_id=seeded_user.id, title="worker test session")
    session.add(agent_session)
    await session.flush()
    return agent_session


@pytest.fixture
async def queued_run_and_attempt(session, queued_session) -> tuple[AgentRun, AgentRunAttempt]:
    repo = AgentRepository(session)
    run, attempt, event = await repo.create_run_with_attempt(
        queued_session, "worker test goal", True, [], "quick"
    )
    await session.flush()
    return run, attempt


class TestConcurrentClaim:
    async def test_only_one_worker_claims_a_queued_attempt(self, test_db):
        from argon2 import PasswordHasher
        from app.models.rbac import User

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"concurrent_user_{uuid.uuid4().hex[:8]}",
                display_name="Concurrent Test User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()

            agent_session = AgentSession(owner_user_id=user.id, title="concurrent test")
            s.add(agent_session)
            await s.flush()

            repo = AgentRepository(s)
            await repo.create_run_with_attempt(
                agent_session, "concurrent claim test", True, [], "quick"
            )
            await s.commit()

        async def try_claim(worker_id: str) -> AgentRunAttempt | None:
            async with test_db() as s:
                repo = AgentRepository(s)
                claimed = await repo.claim_next_attempt(worker_id)
                if claimed is not None:
                    await s.commit()
                    return claimed
                await s.rollback()
                return None

        first_claim, second_claim = await asyncio.gather(
            try_claim("worker-a"),
            try_claim("worker-b"),
        )

        claimed_count = sum(1 for c in (first_claim, second_claim) if c is not None)
        assert claimed_count == 1

    async def test_claim_next_attempt_returns_none_when_no_queued_runs(self, session):
        repo = AgentRepository(session)
        result = await repo.claim_next_attempt("worker-test")
        assert result is None


class TestLeaseRecovery:
    async def test_expired_lease_creates_recovery_attempt(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "recovery test", True, [], "quick"
        )
        await session.flush()

        attempt.status = "running"
        attempt.worker_id = "dead-worker"
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(attempt)
        run.status = "running"
        session.add(run)
        await session.flush()

        recovered = await repo.recover_expired_attempts(now=datetime.now(UTC))
        assert recovered == 1

        await session.refresh(attempt)
        assert attempt.status == "failed"
        assert attempt.failure_code == "lease_expired"

        await session.refresh(run)
        assert run.status == "retry_wait"

    async def test_expired_lease_past_max_retries_marks_run_failed(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "no more retries test", True, [], "quick"
        )
        await session.flush()

        attempt.status = "running"
        attempt.worker_id = "dead-worker"
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        attempt.attempt_number = 3
        session.add(attempt)
        run.status = "running"
        session.add(run)
        await session.flush()

        recovered = await repo.recover_expired_attempts(now=datetime.now(UTC))
        assert recovered == 1

        await session.refresh(attempt)
        assert attempt.status == "failed"
        assert attempt.failure_code == "lease_expired_no_retry"

        await session.refresh(run)
        assert run.status == "failed"

    async def test_recovery_creates_new_attempt_when_rerun_accrues(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "recovery retry test", True, [], "quick"
        )
        await session.flush()

        attempt.status = "running"
        attempt.worker_id = "dead-worker"
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(attempt)
        run.status = "running"
        session.add(run)
        await session.flush()

        recovered = await repo.recover_expired_attempts(now=datetime.now(UTC))
        assert recovered == 1

        await session.refresh(run)
        assert run.status == "retry_wait"

        all_attempts = await repo.list_attempts(run.id)
        assert len(all_attempts) == 2

        retry = all_attempts[-1]
        assert retry.attempt_number == 2
        assert retry.retry_of_attempt_id == attempt.id
        assert retry.status == "queued"
        assert retry.not_before is not None


class TestCancelRace:
    async def test_cancel_preserves_legal_terminal_state(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "cancel race test", True, [], "quick"
        )
        await session.flush()

        await repo.mark_run_running(run)
        await session.flush()

        cancel_result = await repo.request_cancel(run)
        assert cancel_result is True
        assert run.status == "cancel_requested"

        cancelled_result = await repo.mark_run_cancelled(run)
        assert cancelled_result is True
        assert run.status == "cancelled"

    async def test_cannot_cancel_already_succeeded_run(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "prevent cancel test", True, [], "quick"
        )
        await session.flush()

        await repo.mark_run_running(run)
        await session.flush()
        await repo.mark_run_succeeded(run)
        await session.flush()

        result = await repo.request_cancel(run)
        assert result is False
        await session.refresh(run)
        assert run.status == "succeeded"

    async def test_is_cancel_requested_detected_during_processing(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "detect cancel test", True, [], "quick"
        )
        await session.flush()

        assert await repo.is_cancel_requested(run.id) is False

        await repo.mark_run_running(run)
        await session.flush()
        await repo.request_cancel(run)
        await session.flush()

        assert await repo.is_cancel_requested(run.id) is True

    async def test_claim_next_attempt_updates_run_status(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "claim updates run", True, [], "quick"
        )
        await session.flush()

        claimed = await repo.claim_next_attempt("worker-1")
        await session.flush()

        assert claimed is not None
        assert claimed.id == attempt.id
        assert claimed.status == "running"
        assert claimed.worker_id == "worker-1"
        assert claimed.lease_expires_at is not None

        await session.refresh(run)
        assert run.status == "running"

    async def test_renew_lease_updates_expiry(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "renew lease test", True, [], "quick"
        )
        await session.flush()

        claimed = await repo.claim_next_attempt("worker-1")
        await session.flush()
        assert claimed is not None

        original_lease = claimed.lease_expires_at
        result = await repo.renew_lease(claimed, "worker-1")
        await session.flush()

        assert result is True
        assert claimed.lease_expires_at is not None
        assert claimed.lease_expires_at >= original_lease

    async def test_renew_lease_rejects_wrong_worker(self, session, queued_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            queued_session, "wrong worker test", True, [], "quick"
        )
        await session.flush()

        claimed = await repo.claim_next_attempt("worker-1")
        await session.flush()
        assert claimed is not None

        result = await repo.renew_lease(claimed, "worker-2")
        assert result is False


class TestRecoveryRetry:
    async def test_recovery_creates_delayed_replacement_attempt(self, session, seeded_user):
        repo = AgentRepository(session)
        agent_session = AgentSession(owner_user_id=seeded_user.id, title="recovery retry")
        session.add(agent_session)
        await session.flush()
        run, attempt, _ = await repo.create_run_with_attempt(
            agent_session, "recovery retry goal", True, [], "quick"
        )
        await session.flush()

        await repo.transition_attempt_status(attempt, {"queued"}, "running")
        await session.flush()
        await session.execute(
            update(AgentRunAttempt).where(AgentRunAttempt.id == attempt.id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.flush()
        run.status = "running"
        session.add(run)
        await session.flush()

        recovered = await repo.recover_expired_attempts(now=datetime.now(UTC))
        await session.flush()
        assert recovered >= 1
        attempts = await repo.list_attempts(run.id)
        assert len(attempts) >= 2
        new_attempt = [a for a in attempts if a.status == "queued"]
        assert len(new_attempt) >= 1
        if new_attempt[0].not_before is not None:
            assert new_attempt[0].not_before > datetime.now(UTC)


class TestWorkerExceptionHandling:
    async def test_worker_exception_marks_claimed_run_failed_and_persists_event(
        self, monkeypatch, test_db
    ):
        from app.db.seed import seed_rbac
        from app.services.agent.worker import AgentWorker
        from app.services.agent.loop import agent_loop_service

        async with test_db() as s:
            await seed_rbac(s)
            await s.commit()

        async with test_db() as s:
            user_id = (
                await s.execute(select(User.id).where(User.username == "admin"))
            ).scalar_one()
            agent_session = AgentSession(
                owner_user_id=user_id,
                title="exception test",
            )
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "exception test", True, [], "quick"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async def explode(*_args, **_kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(agent_loop_service, "process_attempt", explode)

        worker = AgentWorker(worker_id="worker-test", concurrency=1)
        settings = get_settings()
        database_url = settings.test_database_url or settings.database_url
        worker._engine = create_async_engine(database_url, echo=False)
        worker._session_factory = async_sessionmaker(
            worker._engine, class_=AsyncSession, expire_on_commit=False
        )

        claimed = await worker._claim_and_execute()
        await asyncio.sleep(0.5)

        async with test_db() as s:
            run = await s.get(AgentRun, run_id)
            attempts = await AgentRepository(s).list_attempts(run_id)
            events = await AgentRepository(s).list_events(run_id)

        assert run.status in ("failed", "retry_wait")
        assert any(a.failure_code is not None for a in attempts)
        assert any(e.event_type == "run_failed" for e in events)

    async def test_failure_finalization_logs_safe_exception_details(self, monkeypatch, caplog):
        from app.services.agent.worker import AgentWorker

        worker = AgentWorker(worker_id="worker-test", concurrency=1)

        class BrokenSessionFactory:
            def __call__(self):
                raise RuntimeError("secret response must not be logged")

        worker._session_factory = BrokenSessionFactory()

        with caplog.at_level("ERROR", logger="agent_worker"):
            await worker._mark_unhandled_attempt_failure(uuid.uuid4())

        record = next(record for record in caplog.records if record.msg.startswith("agent_failure_finalization_failed"))
        assert record.exception_type == "RuntimeError"
        assert record.failure_stage == "failure_finalization"
        assert "secret response" not in caplog.text

    async def test_unhandled_provider_configuration_error_keeps_safe_failure_code(self, monkeypatch):
        from app.services.agent.worker import AgentWorker
        from app.services.agent.loop import agent_loop_service

        worker = AgentWorker(worker_id="worker-test", concurrency=1)
        failure_codes: list[str] = []

        async def explode(*_args, **_kwargs):
            raise ProviderConfigurationError("provider configuration is invalid")

        async def capture_failure(_attempt_id, failure_code):
            failure_codes.append(failure_code)

        monkeypatch.setattr(agent_loop_service, "process_attempt", explode)
        monkeypatch.setattr(worker, "_mark_unhandled_attempt_failure", capture_failure)

        await worker._process_attempt_with_renewal(uuid.uuid4())

        assert failure_codes == ["deepseek_config_error"]

    async def test_unhandled_failure_notifies_postgres_before_local_wakeup(self, monkeypatch):
        from app.services.agent import worker as worker_module
        from app.services.agent.worker import AgentWorker

        run_id = uuid.uuid4()
        session = SimpleNamespace(commit=AsyncMock())
        repo = SimpleNamespace(
            fail_attempt_and_run=AsyncMock(return_value=(run_id, 42)),
        )
        published: list[object] = []

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return None

        worker = AgentWorker(worker_id="worker-test", concurrency=1)
        worker._session_factory = lambda: SessionContext()
        monkeypatch.setattr(worker_module, "AgentRepository", lambda _session: repo)

        async def publish(event):
            published.append(event)

        monkeypatch.setattr(worker_module.event_bus, "publish", publish)

        await worker._mark_unhandled_attempt_failure(uuid.uuid4(), "deepseek_config_error")

        session.commit.assert_awaited_once()
        assert published and published[0].run_id == run_id
        assert published[0].seq == 42


class TestWorkerConcurrency:
    async def test_worker_holds_concurrency_permit_until_attempt_finishes(self, monkeypatch, test_db):
        from app.services.agent.worker import AgentWorker
        from app.services.agent.loop import agent_loop_service
        from app.models.agent import AgentSession
        from app.repositories.agent_repository import AgentRepository

        async with test_db() as s:
            user_id = (
                await s.execute(select(User.id).where(User.username == "admin"))
            ).scalar_one()
            agent_session = AgentSession(
                owner_user_id=user_id, title="concurrency test"
            )
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            await repo.create_run_with_attempt(
                agent_session, "task 1", True, [], "quick"
            )
            await repo.create_run_with_attempt(
                agent_session, "task 2", True, [], "quick"
            )
            await repo.create_run_with_attempt(
                agent_session, "task 3", True, [], "quick"
            )
            await s.commit()

        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def delayed_first(attempt_id, worker_id):
            first_started.set()
            await release_first.wait()

        monkeypatch.setattr(agent_loop_service, "process_attempt", delayed_first)

        worker = AgentWorker(worker_id="worker-concurrency", concurrency=1)
        settings = get_settings()
        db_url = settings.test_database_url or settings.database_url
        worker._engine = create_async_engine(db_url, echo=False, pool_size=5)
        worker._session_factory = async_sessionmaker(
            worker._engine, class_=AsyncSession, expire_on_commit=False
        )

        async with test_db() as s:
            repo = AgentRepository(s)
            await repo.claim_next_attempt("worker-concurrency")
            await s.commit()

        result1 = await worker._claim_and_execute()
        await first_started.wait()
        result2 = await worker._claim_and_execute()

        release_first.set()
        await asyncio.sleep(0.3)

        assert result1 is True
        assert result2 is False, (
            "Second claim should be blocked while first attempt is running"
        )
        await worker._engine.dispose()


class TestConcurrentRecover:
    async def test_only_one_recovery_schedules_retry(self, test_db):
        import uuid as _uuid
        from datetime import UTC, datetime, timedelta
        from sqlalchemy import select as sa_select

        from argon2 import PasswordHasher

        from app.models.agent import AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"recover_user_{_uuid.uuid4().hex[:8]}",
                display_name="Recover Test User",
                password_hash=ph.hash("Test1234"),
                status="active",
            )
            s.add(user)
            await s.flush()

            agent_session = AgentSession(owner_user_id=user.id, title="recover test")
            s.add(agent_session)
            await s.flush()

            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "concurrent recover test", True, [], "quick"
            )
            attempt.status = "running"
            attempt.worker_id = "dead-worker"
            attempt.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
            attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
            s.add(attempt)
            await s.commit()
            run_id = run.id

        async def do_recover() -> int:
            async with test_db() as s:
                repo = AgentRepository(s)
                try:
                    count = await repo.recover_expired_attempts()
                    await s.commit()
                    return count
                except Exception:
                    await s.rollback()
                    raise

        results = await asyncio.gather(do_recover(), do_recover())
        assert sum(results) == 1

        async with test_db() as s:
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
