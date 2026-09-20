import uuid

import pytest
from sqlalchemy.exc import IntegrityError

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
from app.models.base import Base
from app.models.rbac import User


def test_agent_models_are_registered_in_base_metadata():
    assert {
        "agent_sessions",
        "agent_runs",
        "agent_run_attempts",
        "agent_run_events",
        "agent_steps",
        "agent_attachments",
        "agent_run_attachments",
        "agent_retention_jobs",
    } <= set(Base.metadata.tables)


async def test_agent_session_fk_enforcement(session):
    session_obj = AgentSession(
        owner_user_id=uuid.uuid4(),
        title="orphan session",
    )
    session.add(session_obj)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_agent_run_owner_must_match_its_session(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    other_user_id = uuid.uuid4()
    session.add(
        AgentRun(
            session_id=owned.id,
            owner_user_id=other_user_id,
            goal="mismatched owner",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_agent_run_fk_constraint_on_session_owner_pair(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    run = AgentRun(
        session_id=owned.id,
        owner_user_id=seeded_user.id,
        goal="valid run",
    )
    session.add(run)
    await session.flush()
    assert run.id is not None


async def test_attempt_number_unique_per_run(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    run = AgentRun(
        session_id=owned.id,
        owner_user_id=seeded_user.id,
        goal="test run",
    )
    session.add(run)
    await session.flush()

    attempt1 = AgentRunAttempt(
        run_id=run.id,
        attempt_number=1,
    )
    session.add(attempt1)
    await session.flush()

    attempt2 = AgentRunAttempt(
        run_id=run.id,
        attempt_number=1,
    )
    session.add(attempt2)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_step_number_unique_per_attempt(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    run = AgentRun(
        session_id=owned.id,
        owner_user_id=seeded_user.id,
        goal="test run",
    )
    session.add(run)
    await session.flush()

    attempt = AgentRunAttempt(
        run_id=run.id,
        attempt_number=1,
    )
    session.add(attempt)
    await session.flush()

    step1 = AgentStep(
        attempt_id=attempt.id,
        step_number=1,
    )
    session.add(step1)
    await session.flush()

    step2 = AgentStep(
        attempt_id=attempt.id,
        step_number=1,
    )
    session.add(step2)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_agent_run_status_check_constraint(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    run = AgentRun(
        session_id=owned.id,
        owner_user_id=seeded_user.id,
        goal="test run",
        status="invalid_status",
    )
    session.add(run)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_agent_session_create_and_read(session, seeded_user):
    session_obj = AgentSession(owner_user_id=seeded_user.id, title="my session")
    session.add(session_obj)
    await session.flush()

    assert session_obj.id is not None
    assert session_obj.owner_user_id == seeded_user.id
    assert session_obj.title == "my session"
    assert session_obj.created_at is not None
    assert session_obj.updated_at is not None


async def test_agent_run_event_sequence(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(owned)
    await session.flush()

    run = AgentRun(
        session_id=owned.id,
        owner_user_id=seeded_user.id,
        goal="test run",
    )
    session.add(run)
    await session.flush()

    event1 = AgentRunEvent(
        run_id=run.id,
        event_type="run_created",
        payload={"message": "hello"},
    )
    session.add(event1)
    await session.flush()
    await session.refresh(event1)

    event2 = AgentRunEvent(
        run_id=run.id,
        event_type="run_queued",
        payload={"message": "queued"},
    )
    session.add(event2)
    await session.flush()
    await session.refresh(event2)

    assert event1.seq is not None
    assert event2.seq is not None
    assert event2.seq == event1.seq + 1


async def test_agent_attachment_fk_session(session, seeded_user):
    from datetime import UTC, datetime, timedelta

    session_obj = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(session_obj)
    await session.flush()

    attachment = AgentAttachment(
        owner_user_id=seeded_user.id,
        session_id=session_obj.id,
        storage_key="attachments/deadbeef",
        filename="report.pdf",
        original_filename="report.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    session.add(attachment)
    await session.flush()
    assert attachment.id is not None


async def test_agent_attachment_fk_invalid_session(session, seeded_user):
    from datetime import UTC, datetime, timedelta

    attachment = AgentAttachment(
        owner_user_id=seeded_user.id,
        session_id=uuid.uuid4(),
        storage_key="attachments/deadbeef",
        filename="report.pdf",
        original_filename="report.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    session.add(attachment)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_retention_job_persistence(session):
    job = AgentRetentionJob(
        job_type="attachment_cleanup",
        stats={"deleted": 10, "skipped": 2},
    )
    session.add(job)
    await session.flush()

    assert job.id is not None
    assert job.job_type == "attachment_cleanup"
    assert job.stats == {"deleted": 10, "skipped": 2}
    assert job.started_at is not None
