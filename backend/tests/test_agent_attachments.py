import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentAttachment, AgentRun, AgentRunAttachment, AgentSession
from app.models.base import Base
from app.models.file import FileFolder, FileObject
from app.models.rbac import User
from app.services.agent.attachments import ATTACHMENT_FOLDER_NAME

settings = get_settings()
TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as s:
        await seed_rbac(s)
        await s.commit()

    async def override_get_db():
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    yield async_session_factory

    app.dependency_overrides.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def admin_client(api_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={
                "username": settings.initial_admin_username,
                "password": settings.initial_admin_password,
            },
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
async def owned_session(admin_client, csrf_headers):
    resp = await admin_client.post(
        "/api/agent/sessions",
        json={"title": "attachment session"},
        headers=csrf_headers,
    )
    assert resp.status_code == 201
    return resp.json()["data"]


@pytest.fixture
async def other_user(api_db):
    async with api_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"other_{uuid.uuid4().hex[:8]}",
            display_name="Other",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def other_client(api_db, other_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        await ac.post(
            "/api/auth/login",
            json={"username": other_user.username, "password": "Password123"},
        )
        yield ac


def _make_text_content(text: str) -> bytes:
    return text.encode("utf-8")


class TestUpload:
    async def test_upload_text_file_succeeds(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("report.txt", _make_text_content("hello world"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert "storage_key" not in data
        assert data["filename"] == "report.txt"
        assert data["extraction_status"] in ("ready", "pending_scan")

    async def test_upload_uses_opaque_storage_key_and_never_exposes_source_filename(
        self, admin_client, csrf_headers, owned_session
    ):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("../../secrets.txt", _make_text_content("public report"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        attachment = resp.json()["data"]
        assert "storage_key" not in attachment
        assert ".." not in attachment["filename"]
        assert attachment["filename"] == "secrets.txt"

    async def test_path_traversal_rejected(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("../../../etc/passwd", _make_text_content("hack"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        assert ".." not in resp.json()["data"]["filename"]

    async def test_mime_spoofing_rejected(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        pe_header = b"MZ\x90\x00" + b"\x00" * 100
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("evil.exe", pe_header, "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_archive_rejected(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        zip_header = b"PK\x03\x04" + b"\x00" * 100
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("data.zip", zip_header, "application/zip")},
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_size_limit_enforced(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        big_content = b"X" * (settings.agent_attachment_max_bytes + 100)
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("big.txt", big_content, "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_count_limit_enforced(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        max_count = settings.agent_attachment_max_count
        for i in range(max_count):
            resp = await admin_client.post(
                f"/api/agent/sessions/{sid}/attachments",
                files={"file": (f"file_{i}.txt", _make_text_content("data"), "text/plain")},
                headers=csrf_headers,
            )
            assert resp.status_code == 201

        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("overflow.txt", _make_text_content("data"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_requires_csrf(self, admin_client, owned_session):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("test.txt", _make_text_content("data"), "text/plain")},
        )
        assert resp.status_code == 403

    async def test_foreign_session_is_404(self, other_client, owned_session):
        sid = owned_session["id"]
        resp = await other_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("test.txt", _make_text_content("data"), "text/plain")},
        )
        assert resp.status_code == 404


class TestList:
    async def test_list_attachments_empty(self, admin_client, owned_session):
        sid = owned_session["id"]
        resp = await admin_client.get(f"/api/agent/sessions/{sid}/attachments")
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    async def test_list_attachments_with_items(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("a.txt", _make_text_content("a"), "text/plain")},
            headers=csrf_headers,
        )
        await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("b.txt", _make_text_content("b"), "text/plain")},
            headers=csrf_headers,
        )
        resp = await admin_client.get(f"/api/agent/sessions/{sid}/attachments")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 2

    async def test_foreign_session_list_is_404(self, other_client, owned_session):
        sid = owned_session["id"]
        resp = await other_client.get(f"/api/agent/sessions/{sid}/attachments")
        assert resp.status_code == 404


class TestDownload:
    async def test_download_owned_attachment(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("hello.txt", _make_text_content("hello world content"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        dl_resp = await admin_client.get(f"/api/agent/attachments/{aid}/download")
        assert dl_resp.status_code == 200
        assert b"hello world content" in dl_resp.content

    async def test_foreign_attachment_download_is_404(self, other_client, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("secret.txt", _make_text_content("secret"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        resp = await other_client.get(f"/api/agent/attachments/{aid}/download")
        assert resp.status_code == 404

    async def test_nonexistent_attachment_download_is_404(self, admin_client):
        fake_id = str(uuid.uuid4())
        resp = await admin_client.get(f"/api/agent/attachments/{fake_id}/download")
        assert resp.status_code == 404


class TestDownloadDisposition:
    async def test_download_attachment_header_when_requested(self, admin_client, csrf_headers):
        upload_resp = await admin_client.post(
            "/api/files/upload",
            files={"file": ("hello.txt", _make_text_content("hello world"), "text/plain")},
            headers=csrf_headers,
        )
        assert upload_resp.status_code == 201
        file_id = upload_resp.json()["data"]["uploaded"][0]["id"]

        dl_resp = await admin_client.get(f"/api/files/{file_id}/download?download=1")
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-disposition"].startswith("attachment")

    async def test_download_inline_by_default(self, admin_client, csrf_headers):
        upload_resp = await admin_client.post(
            "/api/files/upload",
            files={"file": ("hello.txt", _make_text_content("hello world"), "text/plain")},
            headers=csrf_headers,
        )
        assert upload_resp.status_code == 201
        file_id = upload_resp.json()["data"]["uploaded"][0]["id"]

        dl_resp = await admin_client.get(f"/api/files/{file_id}/download")
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-disposition"].startswith("inline")


class TestDelete:
    async def test_delete_unreferenced_attachment(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("delme.txt", _make_text_content("delete me"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        del_resp = await admin_client.delete(
            f"/api/agent/attachments/{aid}",
            headers=csrf_headers,
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["data"]["deleted"] is True

    async def test_active_run_attachment_deletion_rejected(
        self, admin_client, csrf_headers, owned_session, api_db
    ):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("inuse.txt", _make_text_content("in use"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid)))
            att.extraction_status = "ready"
            s.add(att)

            run = AgentRun(
                session_id=uuid.UUID(sid),
                owner_user_id=att.owner_user_id,
                goal="test run",
                status="queued",
            )
            s.add(run)
            await s.flush()

            ra = AgentRunAttachment(run_id=run.id, attachment_id=att.id)
            s.add(ra)
            await s.commit()

        del_resp = await admin_client.delete(
            f"/api/agent/attachments/{aid}",
            headers=csrf_headers,
        )
        assert del_resp.status_code == 409

    async def test_delete_requires_csrf(self, admin_client, csrf_headers, owned_session):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("nocerf.txt", _make_text_content("data"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        resp = await admin_client.delete(f"/api/agent/attachments/{aid}")
        assert resp.status_code == 403


class TestAttachmentInRun:
    async def test_create_run_with_valid_attachment(self, admin_client, csrf_headers, owned_session, api_db):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("data.txt", _make_text_content("important data"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid)))
            att.extraction_status = "ready"
            s.add(att)
            await s.commit()

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/runs",
            json={"goal": "summarize", "mode": "quick", "attachment_ids": [aid]},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 201

    async def test_create_run_with_unready_attachment_rejected(self, admin_client, csrf_headers, owned_session, api_db):
        sid = owned_session["id"]
        upload_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("pending.txt", _make_text_content("pending"), "text/plain")},
            headers=csrf_headers,
        )
        aid = upload_resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid)))
            att.extraction_status = "pending_scan"
            s.add(att)
            await s.commit()

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/runs",
            json={"goal": "summarize", "mode": "quick", "attachment_ids": [aid]},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 422

    async def test_create_run_with_foreign_attachment_rejected(
        self, admin_client, other_user, api_db, csrf_headers, owned_session
    ):
        sid = owned_session["id"]

        async with api_db() as s:
            attachment = AgentAttachment(
                id=uuid.uuid4(),
                owner_user_id=other_user.id,
                session_id=uuid.UUID(sid),
                storage_key="fake",
                filename="foreign.txt",
                original_filename="foreign.txt",
                media_type="text/plain",
                size_bytes=10,
                sha256="abc",
                extraction_status="ready",
                expires_at=datetime.now(UTC) + timedelta(days=90),
            )
            s.add(attachment)
            await s.commit()
            aid = str(attachment.id)

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/runs",
            json={"goal": "summarize", "mode": "quick", "attachment_ids": [aid]},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 422


class TestAttachmentFolderDoubleWrite:
    async def test_upload_attachment_creates_attachment_folder_file(
        self, admin_client, csrf_headers, owned_session, api_db
    ):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("report.txt", _make_text_content("hello world"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        aid = resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(
                select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid))
            )
            folder = await s.scalar(
                select(FileFolder).where(
                    FileFolder.owner_user_id == att.owner_user_id,
                    FileFolder.name == ATTACHMENT_FOLDER_NAME,
                    FileFolder.parent_folder_id.is_(None),
                    FileFolder.is_deleted == False,
                )
            )
            assert folder is not None
            file_obj = await s.scalar(
                select(FileObject).where(
                    FileObject.folder_id == folder.id,
                    FileObject.storage_key == att.storage_key,
                    FileObject.is_deleted == False,
                )
            )
            assert file_obj is not None
            assert file_obj.original_filename == "report.txt"

    async def test_attachment_folder_double_written_file_downloads(
        self, admin_client, csrf_headers, owned_session, api_db
    ):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("dl.txt", _make_text_content("download me"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        aid = resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(
                select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid))
            )
            file_obj = await s.scalar(
                select(FileObject).where(
                    FileObject.owner_user_id == att.owner_user_id,
                    FileObject.storage_key == att.storage_key,
                    FileObject.is_deleted == False,
                )
            )
            assert file_obj is not None
            assert file_obj.storage_key.startswith("attachments/")
            file_id = str(file_obj.id)

        dl_resp = await admin_client.get(f"/api/files/{file_id}/download")
        assert dl_resp.status_code == 200
        assert b"download me" in dl_resp.content

    async def test_attachment_folder_double_written_file_previews(
        self, admin_client, csrf_headers, owned_session, api_db
    ):
        sid = owned_session["id"]
        resp = await admin_client.post(
            f"/api/agent/sessions/{sid}/attachments",
            files={"file": ("pv.txt", _make_text_content("preview me"), "text/plain")},
            headers=csrf_headers,
        )
        assert resp.status_code == 201
        aid = resp.json()["data"]["id"]

        async with api_db() as s:
            att = await s.scalar(
                select(AgentAttachment).where(AgentAttachment.id == uuid.UUID(aid))
            )
            file_obj = await s.scalar(
                select(FileObject).where(
                    FileObject.owner_user_id == att.owner_user_id,
                    FileObject.storage_key == att.storage_key,
                    FileObject.is_deleted == False,
                )
            )
            assert file_obj is not None
            assert file_obj.storage_key.startswith("attachments/")
            file_id = str(file_obj.id)

        pv_resp = await admin_client.get(f"/api/files/{file_id}/preview")
        assert pv_resp.status_code == 200
        data = pv_resp.json()["data"]
        assert data["type"] == "text"
        assert "preview me" in data["content"]

    async def test_attachment_folder_created_once(
        self, admin_client, csrf_headers, owned_session, api_db
    ):
        sid = owned_session["id"]
        for i in range(2):
            resp = await admin_client.post(
                f"/api/agent/sessions/{sid}/attachments",
                files={"file": (f"note_{i}.txt", _make_text_content("data"), "text/plain")},
                headers=csrf_headers,
            )
            assert resp.status_code == 201

        async with api_db() as s:
            att = await s.scalar(
                select(AgentAttachment).where(
                    AgentAttachment.session_id == uuid.UUID(sid)
                )
            )
            count = (
                await s.execute(
                    select(func.count()).select_from(FileFolder).where(
                        FileFolder.owner_user_id == att.owner_user_id,
                        FileFolder.name == ATTACHMENT_FOLDER_NAME,
                        FileFolder.parent_folder_id.is_(None),
                        FileFolder.is_deleted == False,
                    )
                )
            ).scalar_one()
            assert count == 1
