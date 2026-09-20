import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentRun, AgentRunEvent, AgentSession
from app.models.base import Base
from app.models.rbac import Role, User, UserRole

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def audit_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as s:
        await seed_rbac(s)
        await s.commit()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    yield session_factory

    app.dependency_overrides.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def admin_client(audit_db):
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
async def ordinary_user(audit_db):
    async with audit_db() as s:
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
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
async def ordinary_client(audit_db, ordinary_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def run_with_sensitive_event(audit_db, ordinary_user):
    async with audit_db() as s:
        session_obj = AgentSession(
            owner_user_id=ordinary_user.id, title="Sensitive Session"
        )
        s.add(session_obj)
        await s.flush()

        run = AgentRun(
            session_id=session_obj.id,
            owner_user_id=ordinary_user.id,
            goal="Sensitive goal",
            mode="quick",
            status="queued",
        )
        s.add(run)
        await s.flush()

        event = AgentRunEvent(
            run_id=run.id,
            event_type="run_queued",
            payload={
                "goal": "Sensitive goal",
                "attachment_content": "secret file content here",
                "attachment_text": "extracted text",
                "token": "bearer-secret-token-123",
                "authorization": "Basic secret",
                "password": "hunter2",
                "secret": "another-secret",
                "raw_prompt": "system: do x\nuser: do y",
                "raw_response": "model output",
                "safe_field": "visible data",
            },
        )
        s.add(event)
        await s.flush()

        event2 = AgentRunEvent(
            run_id=run.id,
            event_type="run_started",
            payload={"status": "ok", "data": "visible"},
        )
        s.add(event2)
        await s.flush()

        await s.commit()
        return run


class TestAgentAudit:
    async def test_only_admin_can_access_audit_sessions(self, ordinary_client):
        response = await ordinary_client.get("/api/agent/audit/sessions")
        assert response.status_code == 403

    async def test_admin_can_access_audit_sessions(self, admin_client):
        response = await admin_client.get("/api/agent/audit/sessions")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "items" in data
        assert "page" in data
        assert "total" in data

    async def test_events_are_paginated_and_redacted(
        self, admin_client, run_with_sensitive_event
    ):
        response = await admin_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}/events",
            params={"page_size": 1, "cursor": 0},
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert len(payload["items"]) == 1
        event_payload = payload["items"][0]["payload"]
        assert event_payload.get("attachment_content") == "[REDACTED]"
        assert event_payload.get("attachment_text") == "[REDACTED]"
        assert event_payload.get("token") == "[REDACTED]"
        assert event_payload.get("authorization") == "[REDACTED]"
        assert event_payload.get("password") == "[REDACTED]"
        assert event_payload.get("secret") == "[REDACTED]"
        assert event_payload.get("safe_field") == "visible data"

    async def test_non_admin_gets_403_for_audit_events(
        self, ordinary_client, run_with_sensitive_event
    ):
        response = await ordinary_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}/events"
        )
        assert response.status_code == 403

    async def test_non_admin_gets_403_for_audit_run(
        self, ordinary_client, run_with_sensitive_event
    ):
        response = await ordinary_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}"
        )
        assert response.status_code == 403

    async def test_non_admin_gets_403_for_audit_steps(
        self, ordinary_client, run_with_sensitive_event
    ):
        response = await ordinary_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}/attempts/{uuid.uuid4()}/steps"
        )
        assert response.status_code == 403

    async def test_audit_sessions_by_user_id_filter(
        self, admin_client, audit_db, ordinary_user
    ):
        async with audit_db() as s:
            session_obj = AgentSession(
                owner_user_id=ordinary_user.id, title="Filtered"
            )
            s.add(session_obj)
            await s.commit()

        response = await admin_client.get(
            "/api/agent/audit/sessions",
            params={"user_id": str(ordinary_user.id)},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] >= 1
        found = any(
            item.get("title") == "Filtered" for item in data["items"]
        )
        assert found

    async def test_audit_events_with_cursor(
        self, admin_client, run_with_sensitive_event
    ):
        response = await admin_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}/events",
            params={"page_size": 2},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["items"]) == 2
        assert data["next_seq"] is not None

    async def test_audit_unauthorized_no_cookie(self, audit_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            response = await ac.get("/api/agent/audit/sessions")
            assert response.status_code == 401

    async def test_audit_run_detail_admin(self, admin_client, run_with_sensitive_event):
        response = await admin_client.get(
            f"/api/agent/audit/runs/{run_with_sensitive_event.id}"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["goal"] == "Sensitive goal"

    async def test_audit_session_runs_returns_list(self, admin_client, csrf_headers):
        sid = (await admin_client.post("/api/agent/sessions", json={"title": "audit"}, headers=csrf_headers)).json()["data"]["id"]
        run = await admin_client.post(f"/api/agent/sessions/{sid}/runs", json={"goal": "x", "mode": "quick"}, headers=csrf_headers)
        rid = run.json()["data"]["id"]
        runs = await admin_client.get(f"/api/agent/audit/sessions/{sid}/runs")
        assert runs.status_code == 200
        assert runs.json()["data"][0]["id"] == rid

    async def test_audit_events_use_cursor_pagination(self, admin_client, csrf_headers):
        sid = (await admin_client.post("/api/agent/sessions", json={"title": "evt"}, headers=csrf_headers)).json()["data"]["id"]
        run = await admin_client.post(f"/api/agent/sessions/{sid}/runs", json={"goal": "x", "mode": "quick"}, headers=csrf_headers)
        rid = run.json()["data"]["id"]
        evts = await admin_client.get(f"/api/agent/audit/runs/{rid}/events?page_size=1")
        assert evts.status_code == 200
        body = evts.json()["data"]
        assert "items" in body and "next_seq" in body
