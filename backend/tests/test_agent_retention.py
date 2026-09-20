import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
from app.models.base import Base
from app.models.rbac import User
from app.services.agent.retention import RetentionService
from app.services.agent.storage import PrivateObjectStorage, build_attachment_key

settings = get_settings()


@pytest.fixture
async def storage_tmp(test_engine):
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PrivateObjectStorage(tmpdir)
        yield storage


@pytest.fixture
async def session_with_data(session, storage_tmp):
    owner_id = uuid.uuid4()

    user = User(
        id=owner_id,
        username="retention_test",
        display_name="Retention Test",
        password_hash="hash",
        status="active",
    )
    session.add(user)

    agent_session = AgentSession(
        id=uuid.uuid4(),
        owner_user_id=owner_id,
        title="test session",
    )
    session.add(agent_session)

    old_run = AgentRun(
        id=uuid.uuid4(),
        session_id=agent_session.id,
        owner_user_id=owner_id,
        goal="old run",
        status="succeeded",
        created_at=datetime.now(UTC) - timedelta(days=settings.agent_run_retention_days + 1),
    )
    session.add(old_run)
    await session.flush()

    aid = uuid.uuid4()
    storage_key = build_attachment_key(aid)
    await storage_tmp.put(storage_key, _async_bytes_iter(b"attachment data"))

    old_attachment = AgentAttachment(
        id=aid,
        owner_user_id=owner_id,
        session_id=agent_session.id,
        storage_key=storage_key,
        filename="old.txt",
        original_filename="old.txt",
        media_type="text/plain",
        size_bytes=15,
        sha256="abc",
        extraction_status="ready",
        expires_at=datetime.now(UTC) - timedelta(days=settings.agent_attachment_retention_days + 1),
    )
    session.add(old_attachment)

    ra_attach = AgentRunAttachment(run_id=old_run.id, attachment_id=aid)
    session.add(ra_attach)

    attempt = AgentRunAttempt(
        id=uuid.uuid4(),
        run_id=old_run.id,
        attempt_number=1,
        status="succeeded",
    )
    session.add(attempt)
    await session.flush()

    step = AgentStep(
        id=uuid.uuid4(),
        attempt_id=attempt.id,
        step_number=1,
        status="completed",
    )
    session.add(step)

    event = AgentRunEvent(
        id=uuid.uuid4(),
        run_id=old_run.id,
        attempt_id=attempt.id,
        event_type="run_succeeded",
        payload={"done": True},
    )
    session.add(event)

    recent_run = AgentRun(
        id=uuid.uuid4(),
        session_id=agent_session.id,
        owner_user_id=owner_id,
        goal="recent run",
        status="queued",
    )
    session.add(recent_run)

    recent_attachment = AgentAttachment(
        id=uuid.uuid4(),
        owner_user_id=owner_id,
        session_id=agent_session.id,
        storage_key=build_attachment_key(uuid.uuid4()),
        filename="recent.txt",
        original_filename="recent.txt",
        media_type="text/plain",
        size_bytes=5,
        sha256="def",
        extraction_status="ready",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(recent_attachment)

    await session.flush()
    return session


async def _async_bytes_iter(data: bytes):
    yield data


class TestRetention:
    async def test_retention_keeps_attachment_when_session_exists(
        self, session_with_data, storage_tmp
    ):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)
        assert result.deleted_attachments == 0

        from sqlalchemy import select
        atts = await session_with_data.execute(
            select(AgentAttachment).where(AgentAttachment.filename == "old.txt")
        )
        assert atts.scalars().first() is not None

    async def test_retention_deletes_old_events(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)
        assert result.deleted_events >= 1

    async def test_retention_deletes_old_steps(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)
        assert result.deleted_steps >= 1

    async def test_retention_deletes_old_attempts(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)
        assert result.deleted_attempts >= 1

    async def test_retention_deletes_old_runs(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)
        assert result.deleted_runs >= 1

    async def test_retention_preserves_recent_data(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        result = await svc.run_once(now)

        from sqlalchemy import select
        recent = await session_with_data.execute(
            select(AgentRun).where(AgentRun.goal == "recent run")
        )
        recent_runs = recent.scalars().all()
        assert len(recent_runs) == 1

        recent_att = await session_with_data.execute(
            select(AgentAttachment).where(AgentAttachment.filename == "recent.txt")
        )
        assert recent_att.scalars().first() is not None

    async def test_retention_job_records_written(self, session_with_data, storage_tmp):
        now = datetime.now(UTC)
        svc = RetentionService(
            session=session_with_data,
            storage=storage_tmp,
            batch_size=10,
        )
        await svc.run_once(now)

        from sqlalchemy import select
        jobs = await session_with_data.execute(
            select(AgentRetentionJob).order_by(AgentRetentionJob.started_at.desc()).limit(1)
        )
        job = jobs.scalars().first()
        assert job is not None
        assert job.job_type == "daily_retention"
        assert job.completed_at is not None
        assert isinstance(job.stats, dict)
        assert "deleted_attachments" in job.stats


class TestAttachmentFolderCleanup:
    async def test_cleanup_removes_orphan_attachment_folder_files(
        self, session, storage_tmp, seeded_user
    ):
        from app.models.agent import AgentAttachment, AgentSession
        from app.models.file import FileFolder, FileObject

        folder = FileFolder(
            owner_user_id=seeded_user.id,
            name="附件",
            path="/附件",
            depth=0,
        )
        session.add(folder)
        await session.flush()

        agent_session = AgentSession(
            id=uuid.uuid4(),
            owner_user_id=seeded_user.id,
            title="orphan cleanup session",
        )
        session.add(agent_session)
        await session.flush()

        key_a = build_attachment_key(uuid.uuid4())
        await storage_tmp.put(key_a, _async_bytes_iter(b"orphan data"))

        orphan_file = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=folder.id,
            storage_key=key_a,
            filename="orphan.txt",
            original_filename="orphan.txt",
            media_type="text/plain",
            size_bytes=11,
            sha256="a" * 64,
            created_by=seeded_user.id,
        )
        session.add(orphan_file)

        key_b = build_attachment_key(uuid.uuid4())
        await storage_tmp.put(key_b, _async_bytes_iter(b"attached data"))

        attached = AgentAttachment(
            id=uuid.uuid4(),
            owner_user_id=seeded_user.id,
            session_id=agent_session.id,
            storage_key=key_b,
            filename="attached.txt",
            original_filename="attached.txt",
            media_type="text/plain",
            size_bytes=13,
            sha256="b" * 64,
            extraction_status="ready",
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
        session.add(attached)

        kept_file = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=folder.id,
            storage_key=key_b,
            filename="attached.txt",
            original_filename="attached.txt",
            media_type="text/plain",
            size_bytes=13,
            sha256="b" * 64,
            created_by=seeded_user.id,
        )
        session.add(kept_file)
        await session.flush()

        svc = RetentionService(session=session, storage=storage_tmp, batch_size=10)
        deleted = await svc.cleanup_attachment_folders()
        assert deleted == 1

        orphan_ref = await session.get(FileObject, orphan_file.id)
        assert orphan_ref.is_deleted is True
        kept_ref = await session.get(FileObject, kept_file.id)
        assert kept_ref.is_deleted is False

        with pytest.raises(FileNotFoundError):
            async for _ in storage_tmp.open(key_a):
                pass

        chunks = []
        async for chunk in storage_tmp.open(key_b):
            chunks.append(chunk)
        assert b"".join(chunks) == b"attached data"

    async def test_cleanup_ignores_other_folders(
        self, session, storage_tmp, seeded_user
    ):
        from app.models.file import FileFolder, FileObject

        folder = FileFolder(
            owner_user_id=seeded_user.id,
            name="Docs",
            path="/Docs",
            depth=0,
        )
        session.add(folder)
        await session.flush()

        key = build_attachment_key(uuid.uuid4())
        await storage_tmp.put(key, _async_bytes_iter(b"keep me"))

        file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=folder.id,
            storage_key=key,
            filename="old.txt",
            original_filename="old.txt",
            media_type="text/plain",
            size_bytes=7,
            sha256="c" * 64,
            created_at=datetime.now(UTC) - timedelta(days=2),
            created_by=seeded_user.id,
        )
        session.add(file_obj)
        await session.flush()

        svc = RetentionService(session=session, storage=storage_tmp, batch_size=10)
        deleted = await svc.cleanup_attachment_folders()
        assert deleted == 0

        from sqlalchemy import select
        rows = (
            await session.execute(
                select(FileObject).where(FileObject.folder_id == folder.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].is_deleted is False

        chunks = []
        async for chunk in storage_tmp.open(key):
            chunks.append(chunk)
        assert b"".join(chunks) == b"keep me"

    async def test_attachment_folder_cleanup_ignores_subfolder_named_attachments(
        self, session, storage_tmp, seeded_user
    ):
        from app.models.file import FileFolder, FileObject

        parent = FileFolder(
            owner_user_id=seeded_user.id,
            name="Docs",
            path="/Docs",
            depth=0,
        )
        session.add(parent)
        await session.flush()

        subfolder = FileFolder(
            owner_user_id=seeded_user.id,
            parent_folder_id=parent.id,
            name="附件",
            path="/Docs/附件",
            depth=1,
        )
        session.add(subfolder)
        await session.flush()

        key = build_attachment_key(uuid.uuid4())
        await storage_tmp.put(key, _async_bytes_iter(b"keep me"))

        file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=subfolder.id,
            storage_key=key,
            filename="old.txt",
            original_filename="old.txt",
            media_type="text/plain",
            size_bytes=7,
            sha256="d" * 64,
            created_at=datetime.now(UTC) - timedelta(days=2),
            created_by=seeded_user.id,
        )
        session.add(file_obj)
        await session.flush()

        svc = RetentionService(session=session, storage=storage_tmp, batch_size=10)
        deleted = await svc.cleanup_attachment_folders()
        assert deleted == 0

        from sqlalchemy import select
        rows = (
            await session.execute(
                select(FileObject).where(FileObject.folder_id == subfolder.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].is_deleted is False


class TestStorage:
    async def test_put_and_open(self, storage_tmp):
        key = "test/data.bin"
        content = b"hello storage"
        size = await storage_tmp.put(key, _async_bytes_iter(content))
        assert size == len(content)

        chunks = []
        async for chunk in storage_tmp.open(key):
            chunks.append(chunk)
        assert b"".join(chunks) == content

    async def test_path_traversal_rejected(self, storage_tmp):
        key = "../../../etc/passwd"
        with pytest.raises(ValueError):
            await storage_tmp.put(key, _async_bytes_iter(b"bad"))

    async def test_compute_sha256(self, storage_tmp):
        key = "test/hash.bin"
        content = b"sha256 test"
        await storage_tmp.put(key, _async_bytes_iter(content))
        import hashlib
        expected = hashlib.sha256(content).hexdigest()
        actual = await storage_tmp.compute_sha256(key)
        assert actual == expected

    async def test_delete(self, storage_tmp):
        key = "test/del.bin"
        await storage_tmp.put(key, _async_bytes_iter(b"delete me"))
        await storage_tmp.delete(key)
        with pytest.raises(FileNotFoundError):
            async for _ in storage_tmp.open(key):
                pass

    async def test_build_attachment_key(self):
        aid = uuid.uuid4()
        key = build_attachment_key(aid)
        assert key.startswith("attachments/")
        assert aid.hex in key
