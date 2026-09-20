import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.agent import AgentRunAttempt, AgentRunEvent, AgentSession
from app.repositories.agent_repository import AgentRepository


@pytest.fixture
async def run_with_completed_answer_no_run_succeeded(session, seeded_user):
    agent_session = AgentSession(owner_user_id=seeded_user.id, title="reconcile test")
    session.add(agent_session)
    await session.flush()

    repo = AgentRepository(session)
    run, attempt, _ = await repo.create_run_with_attempt(
        agent_session, "reconcile test goal", True, [], "quick"
    )
    await session.flush()

    attempt.status = "running"
    attempt.worker_id = "dead-worker"
    attempt.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
    attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    attempt.started_at = datetime.now(UTC) - timedelta(minutes=10)
    session.add(attempt)
    await session.flush()

    run.status = "running"
    run.current_attempt_id = attempt.id
    session.add(run)
    await session.flush()

    answer_event = await repo.append_event(
        run, attempt, "answer_completed",
        {"text": "This is the final answer", "stream_id": str(uuid.uuid4())},
    )
    await session.flush()

    return run, attempt, answer_event


class TestReconcileCompletedAgentRuns:
    async def test_reconciles_expired_running_attempt_with_completed_answer(
        self, session, run_with_completed_answer_no_run_succeeded
    ):
        run, attempt, answer_event = run_with_completed_answer_no_run_succeeded
        repo = AgentRepository(session)

        result = await repo.reconcile_completed_answer_run(run.id)
        assert result is True

        await session.refresh(run)
        await session.refresh(attempt)

        assert run.status == "succeeded"
        assert attempt.status == "succeeded"
        assert run.result is not None
        assert run.result["final_answer"] == "This is the final answer"
        assert run.result["answer_format"] == "markdown"
        assert run.result["completed_at"] is not None
        assert run.result["source_event_sequence"] == answer_event.seq

        events_result = await session.execute(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run.id, AgentRunEvent.event_type == "run_succeeded")
        )
        run_succeeded_events = events_result.scalars().all()
        assert len(run_succeeded_events) == 1
        assert run_succeeded_events[0].payload.get("final_answer") == "This is the final answer"

    async def test_reconciliation_is_idempotent(
        self, session, run_with_completed_answer_no_run_succeeded
    ):
        run, attempt, _ = run_with_completed_answer_no_run_succeeded
        repo = AgentRepository(session)

        result1 = await repo.reconcile_completed_answer_run(run.id)
        assert result1 is True

        result2 = await repo.reconcile_completed_answer_run(run.id)
        assert result2 is False

        events_result = await session.execute(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run.id, AgentRunEvent.event_type == "run_succeeded")
        )
        run_succeeded_events = events_result.scalars().all()
        assert len(run_succeeded_events) == 1

    async def test_reconcile_skips_answer_from_previous_attempt(
        self, session, seeded_user
    ):
        agent_session = AgentSession(
            owner_user_id=seeded_user.id, title="skip reconcile"
        )
        session.add(agent_session)
        await session.flush()

        repo = AgentRepository(session)
        run, attempt1, _ = await repo.create_run_with_attempt(
            agent_session, "skip reconcile goal", True, [], "quick"
        )
        await session.flush()

        attempt1.status = "running"
        attempt1.worker_id = "dead-worker"
        attempt1.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
        attempt1.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
        session.add(attempt1)
        await session.flush()

        await repo.append_event(
            run, attempt1, "answer_completed",
            {"text": "answer from attempt 1", "stream_id": str(uuid.uuid4())},
        )
        await session.flush()

        attempt1.status = "failed"
        attempt2 = AgentRunAttempt(
            run_id=run.id,
            attempt_number=2,
            status="queued",
            retry_of_attempt_id=attempt1.id,
            not_before=datetime.now(UTC) + timedelta(seconds=5),
        )
        session.add(attempt2)
        run.status = "retry_wait"
        await session.flush()
        run.current_attempt_id = attempt2.id
        await session.flush()

        result = await repo.reconcile_completed_answer_run(run.id)

        assert result is False
        await session.refresh(run)
        await session.refresh(attempt2)
        assert run.status == "retry_wait"
        assert attempt2.status == "queued"
