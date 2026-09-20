import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.agent import (
    AgentAttachment,
    AgentRun,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
)
from app.models.file import FileFolder, FileObject
from app.repositories.agent_repository import AgentRepository
from app.services.agent.storage import PrivateObjectStorage


@pytest.fixture
async def repo(session):
    return AgentRepository(session)


@pytest.fixture
async def owned_session(session, seeded_user):
    agent_session = AgentSession(owner_user_id=seeded_user.id, title="test session")
    session.add(agent_session)
    await session.flush()
    return agent_session


@pytest.fixture
async def terminal_run(session, owned_session):
    run = AgentRun(
        session_id=owned_session.id,
        owner_user_id=owned_session.owner_user_id,
        goal="test goal",
        mode="quick",
        network_enabled=True,
        status="succeeded",
    )
    session.add(run)
    await session.flush()

    attempt = AgentRunAttempt(
        run_id=run.id,
        attempt_number=1,
        status="succeeded",
    )
    session.add(attempt)
    await session.flush()

    run.current_attempt_id = attempt.id
    session.add(run)
    await session.flush()

    event = AgentRunEvent(
        run_id=run.id,
        attempt_id=attempt.id,
        event_type="run_queued",
        payload={"goal": "test goal"},
    )
    session.add(event)
    await session.flush()

    return run


class TestCreateRunWithAttempt:
    async def test_create_run_creates_first_attempt_and_queued_event_in_one_transaction(
        self, session, owned_session
    ):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "analyze quarterly report", True, [], "quick"
        )
        await session.flush()

        assert attempt.run_id == run.id
        assert attempt.attempt_number == 1
        assert event.event_type == "run_queued"
        assert event.attempt_id == attempt.id
        assert event.run_id == run.id
        assert run.current_attempt_id == attempt.id
        assert run.status == "queued"
        assert "goal" in event.payload

    async def test_repository_never_calls_commit_internally(
        self, session, owned_session
    ):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "ephemeral run", True, [], "quick"
        )
        await session.flush()

        assert run.id is not None
        assert attempt.id is not None
        assert event.id is not None
        assert run.status == "queued"

    async def test_create_run_updates_session_last_run_id(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "update session", True, [], "quick"
        )
        await session.flush()
        assert owned_session.last_run_id == run.id

    async def test_create_run_with_expert_mode(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "deep dive", False, []
        )
        await session.flush()
        assert run.mode == "expert"
        assert run.network_enabled is False


class TestRetry:
    async def test_retry_creates_an_immutable_new_attempt(self, session, terminal_run):
        repo = AgentRepository(session)
        original_attempt_id = terminal_run.current_attempt_id
        original_attempts = await repo.list_attempts(terminal_run.id)
        assert len(original_attempts) == 1

        original_events = await repo.list_events(terminal_run.id)
        assert len(original_events) == 1

        retry = await repo.create_retry_attempt(terminal_run)
        await session.flush()

        assert retry.attempt_number == 2
        assert retry.retry_of_attempt_id == original_attempt_id
        assert retry.status == "queued"
        assert retry.run_id == terminal_run.id

        all_attempts = await repo.list_attempts(terminal_run.id)
        assert len(all_attempts) == 2

        attempt_ids = {a.id for a in all_attempts}
        assert original_attempt_id in attempt_ids
        assert retry.id in attempt_ids

        all_events = await repo.list_events(terminal_run.id)
        assert len(all_events) == 1
        assert all_events[0].id == original_events[0].id

        assert terminal_run.current_attempt_id == retry.id
        assert terminal_run.status == "queued"

    async def test_retry_does_not_delete_original_events(self, session, terminal_run):
        original_events = await AgentRepository(session).list_events(terminal_run.id)
        assert len(original_events) >= 1

        repo = AgentRepository(session)
        await repo.create_retry_attempt(terminal_run)
        await session.flush()

        events_after = await repo.list_events(terminal_run.id)
        assert len(events_after) >= len(original_events)
        original_event_ids = {e.id for e in original_events}
        after_event_ids = {e.id for e in events_after}
        assert original_event_ids.issubset(after_event_ids)

    async def test_multiple_retries_increment_attempt_number(self, session, terminal_run):
        repo = AgentRepository(session)

        retry1 = await repo.create_retry_attempt(terminal_run)
        await session.flush()
        assert retry1.attempt_number == 2

        terminal_run.status = "succeeded"
        terminal_run.current_attempt_id = retry1.id
        retry1.status = "succeeded"
        session.add(terminal_run)
        session.add(retry1)
        await session.flush()

        retry2 = await repo.create_retry_attempt(terminal_run)
        await session.flush()
        assert retry2.attempt_number == 3
        assert retry2.retry_of_attempt_id == retry1.id


class TestEventOrdering:
    async def test_events_ordered_by_seq(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, first_event = await repo.create_run_with_attempt(
            owned_session, "ordering test", True, [], "quick"
        )
        await session.flush()

        event2 = await repo.append_event(
            run, attempt, "run_started", {"message": "starting"}
        )
        await session.flush()

        event3 = await repo.append_event(
            run, attempt, "thought", {"content": "thinking..."}
        )
        await session.flush()

        events = await repo.list_events(run.id)
        assert len(events) == 3
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)
        assert seqs[0] < seqs[1] < seqs[2]

    async def test_list_events_after_seq_respects_cursor(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "cursor test", True, [], "quick"
        )
        await session.flush()

        for i in range(5):
            await repo.append_event(run, attempt, f"step_{i}", {"index": i})
        await session.flush()

        all_events = await repo.list_events(run.id)
        assert len(all_events) == 6

        after_seq = all_events[2].seq
        later = await repo.list_events_after_seq(run.id, after_seq, 10)
        assert len(later) == 3
        assert all(e.seq > after_seq for e in later)
        assert later[0].seq == all_events[3].seq

    async def test_list_events_after_seq_with_limit(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "limit test", True, [], "quick"
        )
        await session.flush()

        for i in range(5):
            await repo.append_event(run, attempt, f"step_{i}", {"index": i})
        await session.flush()

        all_events = await repo.list_events(run.id)
        after_seq = all_events[1].seq
        limited = await repo.list_events_after_seq(run.id, after_seq, 2)
        assert len(limited) == 2

    async def test_list_events_after_none_seq(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "none cursor", True, [], "quick"
        )
        await session.flush()

        events = await repo.list_events_after_seq(run.id, None, 10)
        assert len(events) == 1


class TestStateTransitions:
    async def test_mark_run_running_from_queued(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "state test", True, [], "quick"
        )
        await session.flush()

        result = await repo.mark_run_running(run)
        assert result is True
        assert run.status == "running"

    async def test_mark_run_running_rejects_wrong_source(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "state test", True, [], "quick"
        )
        await session.flush()

        run.status = "succeeded"
        session.add(run)
        await session.flush()

        result = await repo.mark_run_running(run)
        assert result is False
        await session.refresh(run)
        assert run.status == "succeeded"

    async def test_request_cancel_from_running(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "cancel test", True, [], "quick"
        )
        await session.flush()

        await repo.mark_run_running(run)
        await session.flush()

        result = await repo.request_cancel(run)
        assert result is True
        assert run.status == "cancel_requested"

    async def test_cancel_queued_run_marks_cancelled(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "cancel queued", True, [], "quick"
        )
        await session.flush()
        assert run.status == "queued"

        result = await repo.cancel_queued_run(run)

        assert result is True
        assert run.status == "cancelled"

    async def test_cancel_queued_run_rejects_running(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "cancel running", True, [], "quick"
        )
        await session.flush()
        assert await repo.mark_run_running(run) is True

        result = await repo.cancel_queued_run(run)

        assert result is False
        assert run.status == "running"

    async def test_mark_run_cancelled_from_cancel_requested(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "cancel final", True, [], "quick"
        )
        await session.flush()

        await repo.mark_run_running(run)
        await session.flush()
        await repo.request_cancel(run)
        await session.flush()

        result = await repo.mark_run_cancelled(run)
        assert result is True
        assert run.status == "cancelled"

    async def test_cannot_cancel_terminal_run(self, session, terminal_run):
        repo = AgentRepository(session)
        result = await repo.request_cancel(terminal_run)
        assert result is False
        assert terminal_run.status == "succeeded"

    async def test_is_cancel_requested(self, session, owned_session):
        repo = AgentRepository(session)
        run, _, _ = await repo.create_run_with_attempt(
            owned_session, "check cancel", True, [], "quick"
        )
        await session.flush()

        assert await repo.is_cancel_requested(run.id) is False

        await repo.mark_run_running(run)
        await session.flush()
        await repo.request_cancel(run)
        await session.flush()

        assert await repo.is_cancel_requested(run.id) is True


class TestAttemptTransitions:
    async def test_transition_attempt_from_queued_to_running(self, session, owned_session):
        repo = AgentRepository(session)
        _, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "attempt test", True, [], "quick"
        )
        await session.flush()

        result = await repo.transition_attempt_status(
            attempt, {"queued"}, "running", started_at=datetime.now(UTC)
        )
        assert result is True
        assert attempt.status == "running"

    async def test_transition_attempt_rejects_illegal_source(self, session, owned_session):
        repo = AgentRepository(session)
        _, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "illegal transition", True, [], "quick"
        )
        await session.flush()

        result = await repo.transition_attempt_status(
            attempt, {"running"}, "succeeded"
        )
        assert result is False
        assert attempt.status == "queued"


class TestListSessions:
    async def test_create_and_list_owned_sessions(self, session, seeded_user):
        repo = AgentRepository(session)

        await repo.create_session(seeded_user.id, "session one")
        await session.flush()
        await repo.create_session(seeded_user.id, "session two")
        await session.flush()

        page = await repo.list_owned_sessions(seeded_user.id, page=1, page_size=10)
        assert page.total == 2
        assert len(page.items) == 2
        assert page.items[0].owner_user_id == seeded_user.id

    async def test_get_owned_session_returns_none_for_other_user(
        self, session, seeded_user, owned_session
    ):
        repo = AgentRepository(session)
        other_id = uuid.uuid4()
        result = await repo.get_owned_session(owned_session.id, other_id)
        assert result is None

    async def test_get_owned_session_returns_session_for_owner(
        self, session, owned_session
    ):
        repo = AgentRepository(session)
        result = await repo.get_owned_session(owned_session.id, owned_session.owner_user_id)
        assert result is not None
        assert result.id == owned_session.id


class TestSessionHistory:
    async def test_list_runs_for_session_ordered_by_created_at(self, session, owned_session):
        repo = AgentRepository(session)
        run1, _, _ = await repo.create_run_with_attempt(
            owned_session, "first run", True, [], "quick"
        )
        await session.flush()
        run2, _, _ = await repo.create_run_with_attempt(
            owned_session, "second run", True, [], "quick"
        )
        await session.flush()

        runs = await repo.list_runs_for_session(owned_session.id)
        assert len(runs) == 2
        assert runs[0].id == run1.id
        assert runs[1].id == run2.id
        assert runs[0].created_at <= runs[1].created_at

    async def test_list_recent_session_history_respects_limit(self, session, owned_session):
        repo = AgentRepository(session)
        for i in range(8):
            await repo.create_run_with_attempt(
                owned_session, f"run {i}", True, [], "quick"
            )
            await session.flush()

        recent = await repo.list_recent_session_history(owned_session.id, limit=3)
        assert len(recent) == 3


class TestClaimAttempt:
    async def test_claim_next_attempt_triggers_update(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "claim test", True, [], "quick"
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

    async def test_claim_next_attempt_returns_none_when_none_queued(self, session):
        repo = AgentRepository(session)
        claimed = await repo.claim_next_attempt("worker-1")
        assert claimed is None

    async def test_renew_lease_updates_expiry(self, session, owned_session):
        repo = AgentRepository(session)
        _, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "lease test", True, [], "quick"
        )
        await session.flush()

        claimed = await repo.claim_next_attempt("worker-1")
        await session.flush()

        original_lease = claimed.lease_expires_at
        result = await repo.renew_lease(claimed, "worker-1")
        await session.flush()

        assert result is True
        assert claimed.lease_expires_at is not None
        assert claimed.lease_expires_at >= original_lease

    async def test_recover_expired_attempts_marks_failed(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            owned_session, "recovery test", True, [], "quick"
        )
        await session.flush()

        attempt.status = "running"
        attempt.worker_id = "dead-worker"
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(attempt)
        await session.flush()

        recovered = await repo.recover_expired_attempts()
        assert recovered == 1
        await session.refresh(attempt)
        assert attempt.status == "failed"
        assert attempt.failure_code == "lease_expired"
        await session.refresh(run)
        assert run.status == "retry_wait"


class TestStepObservation:
    async def test_step_observation_round_trips_as_json(self, session, seeded_user):
        agent_session = AgentSession(owner_user_id=seeded_user.id, title="observation test")
        session.add(agent_session)
        await session.flush()
        repo = AgentRepository(session)
        run, attempt, _ = await repo.create_run_with_attempt(
            agent_session, "observation test", True, [], "quick"
        )
        await session.flush()
        step = await repo.add_step(attempt.id, 1, "think", "calculator", {}, {"value": 42}, "succeeded")
        assert step.observation == {"value": 42}


class TestDeleteSession:
    async def _put_bytes(self, storage, key, content):
        async def _stream():
            yield content

        await storage.put(key, _stream())

    async def _make_attachment_folder_record(
        self, session, owner_user_id, storage_key
    ):
        folder = FileFolder(owner_user_id=owner_user_id, name="附件")
        session.add(folder)
        await session.flush()
        file_obj = FileObject(
            owner_user_id=owner_user_id,
            folder_id=folder.id,
            storage_key=storage_key,
            filename="note.txt",
            original_filename="note.txt",
            media_type="text/plain",
            size_bytes=18,
            sha256="",
        )
        session.add(file_obj)
        await session.flush()
        return folder, file_obj

    @pytest.mark.anyio
    async def test_delete_session_cascades_attachments(
        self, session, seeded_user, tmp_path
    ):
        agent_session = AgentSession(
            owner_user_id=seeded_user.id, title="cascade test"
        )
        session.add(agent_session)
        await session.flush()

        storage = PrivateObjectStorage(root=str(tmp_path))
        attachment_id = uuid.uuid4()
        storage_key = f"attachments/{attachment_id.hex}"
        await self._put_bytes(storage, storage_key, b"attachment payload")

        attachment = AgentAttachment(
            id=attachment_id,
            owner_user_id=seeded_user.id,
            session_id=agent_session.id,
            storage_key=storage_key,
            filename="note.txt",
            original_filename="note.txt",
            media_type="text/plain",
            size_bytes=18,
            sha256="",
            extraction_status="ready",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(attachment)
        await session.flush()

        _, file_obj = await self._make_attachment_folder_record(
            session, seeded_user.id, storage_key
        )

        repo = AgentRepository(session, storage=storage)
        await repo.delete_session(agent_session.id, agent_session.owner_user_id)
        await session.flush()

        att_count = await session.scalar(
            select(func.count()).select_from(AgentAttachment).where(
                AgentAttachment.id == attachment_id
            )
        )
        assert att_count == 0

        assert not (tmp_path / "attachments" / attachment_id.hex).exists()

        deleted = await session.scalar(
            select(FileObject.is_deleted).where(FileObject.id == file_obj.id)
        )
        assert deleted is True

    @pytest.mark.anyio
    async def test_delete_session_keeps_other_folders(
        self, session, seeded_user, tmp_path
    ):
        agent_session = AgentSession(
            owner_user_id=seeded_user.id, title="folder test"
        )
        session.add(agent_session)
        await session.flush()

        storage = PrivateObjectStorage(root=str(tmp_path))

        attachment_id = uuid.uuid4()
        att_key = f"attachments/{attachment_id.hex}"
        await self._put_bytes(storage, att_key, b"attachment payload")

        other_id = uuid.uuid4()
        other_key = f"files/{other_id.hex}"
        await self._put_bytes(storage, other_key, b"library payload")

        attachment = AgentAttachment(
            id=attachment_id,
            owner_user_id=seeded_user.id,
            session_id=agent_session.id,
            storage_key=att_key,
            filename="note.txt",
            original_filename="note.txt",
            media_type="text/plain",
            size_bytes=18,
            sha256="",
            extraction_status="ready",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(attachment)
        await session.flush()

        att_folder, att_file_obj = await self._make_attachment_folder_record(
            session, seeded_user.id, att_key
        )

        docs_folder = FileFolder(owner_user_id=seeded_user.id, name="文档")
        session.add(docs_folder)
        await session.flush()
        other_file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=docs_folder.id,
            storage_key=other_key,
            filename="report.txt",
            original_filename="report.txt",
            media_type="text/plain",
            size_bytes=15,
            sha256="",
        )
        session.add(other_file_obj)
        await session.flush()

        repo = AgentRepository(session, storage=storage)
        await repo.delete_session(agent_session.id, agent_session.owner_user_id)
        await session.flush()

        assert await session.scalar(
            select(FileObject.is_deleted).where(FileObject.id == att_file_obj.id)
        ) is True
        assert await session.scalar(
            select(FileObject.is_deleted).where(FileObject.id == other_file_obj.id)
        ) is False

        assert not (tmp_path / "attachments" / attachment_id.hex).exists()
        assert (tmp_path / "files" / other_id.hex).exists()
