import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentAttachment, AgentSession, AgentRun
from app.models.base import Base
from app.models.rbac import Role, User, UserRole

settings = get_settings()


@pytest.fixture
async def auth_db(test_engine):
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
async def admin_client(auth_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": settings.initial_admin_username, "password": settings.initial_admin_password},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def ordinary_user(auth_db):
    async with auth_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"ordinary_{uuid.uuid4().hex[:8]}",
            display_name="Ordinary User",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def ordinary_client(auth_db, ordinary_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


# --- Tests for non-owner access ---

async def test_non_owner_and_missing_agent_runs_are_indistinguishable(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        session = AgentSession(owner_user_id=ordinary_user.id, title="Other Session")
        s.add(session)
        await s.flush()
        run = AgentRun(
            session_id=session.id,
            owner_user_id=ordinary_user.id,
            goal="Test goal",
            mode="quick",
            status="queued",
        )
        s.add(run)
        await s.commit()
        run_id = run.id

    response = await admin_client.get(f"/api/agent/runs/{run_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_non_owner_and_missing_agent_sessions_are_indistinguishable(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        session = AgentSession(owner_user_id=ordinary_user.id, title="Other Session")
        s.add(session)
        await s.commit()
        session_id = session.id

    response = await admin_client.get(f"/api/agent/sessions/{session_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_non_owner_and_missing_agent_attachments_are_indistinguishable(
    auth_db, admin_client, ordinary_user
) -> None:
    from datetime import UTC, datetime, timedelta

    async with auth_db() as s:
        session = AgentSession(owner_user_id=ordinary_user.id, title="Other Session")
        s.add(session)
        await s.flush()
        attachment = AgentAttachment(
            owner_user_id=ordinary_user.id,
            session_id=session.id,
            storage_key="test/key",
            filename="test.txt",
            original_filename="test.txt",
            media_type="text/plain",
            size_bytes=10,
            sha256="abc",
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
        s.add(attachment)
        await s.commit()
        attachment_id = attachment.id

    response = await admin_client.get(f"/api/agent/attachments/{attachment_id}/download")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


# --- Tests for super_admin access ---

async def test_only_active_super_admin_can_open_audit(ordinary_client) -> None:
    response = await ordinary_client.get("/api/agent/audit/sessions")
    assert response.status_code == 403


async def test_admin_can_access_audit(admin_client) -> None:
    response = await admin_client.get("/api/agent/audit/sessions")
    assert response.status_code == 200


# --- Tests for super_admin file access ---

async def test_super_admin_cannot_delete_other_users_file(
    auth_db, admin_client, ordinary_user
) -> None:
    from app.models.file import FileObject

    async with auth_db() as s:
        file_obj = FileObject(
            owner_user_id=ordinary_user.id,
            storage_key="test/key",
            filename="other.txt",
            original_filename="other.txt",
            media_type="text/plain",
            size_bytes=10,
            sha256="abc",
        )
        s.add(file_obj)
        await s.commit()
        file_id = file_obj.id

    csrf_resp = await admin_client.get("/api/auth/csrf")
    assert csrf_resp.status_code == 200
    token = csrf_resp.json()["data"]["token"]

    response = await admin_client.delete(
        f"/api/files/{file_id}",
        headers={"X-CSRF-Token": token, "Origin": "http://localhost:3000"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


# --- Tests for CSRF ---

async def test_csrf_token_endpoint_returns_token(ordinary_client) -> None:
    response = await ordinary_client.get("/api/auth/csrf")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "token" in data


async def test_csrf_endpoint_requires_auth(auth_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/auth/csrf")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


# --- Tests for role-disable revocation ---

async def test_role_disable_revocation_works_immediately(
    auth_db, admin_client, ordinary_user
) -> None:
    from app.models.rbac import UserRole

    async with auth_db() as s:
        super_admin_role = await s.scalar(select(Role).where(Role.code == "super_admin"))
        s.add(UserRole(user_id=ordinary_user.id, role_id=super_admin_role.id))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as promoted:
        login_resp = await promoted.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert login_resp.status_code == 200
        audit_before = await promoted.get("/api/agent/audit/sessions")
        assert audit_before.status_code == 200

    async with auth_db() as s:
        role = await s.scalar(select(Role).where(Role.code == "super_admin"))
        role.status = "disabled"
        await s.commit()

    transport2 = ASGITransport(app=app)
    async with AsyncClient(transport=transport2, base_url="http://test") as re_auth:
        login_resp2 = await re_auth.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert login_resp2.status_code == 200
        audit_after = await re_auth.get("/api/agent/audit/sessions")
        assert audit_after.status_code == 403
