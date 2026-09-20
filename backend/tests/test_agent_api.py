import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentRun, AgentRunAttempt, AgentRunEvent, AgentSession
from app.models.base import Base
from app.models.rbac import Role, User, UserRole

settings = get_settings()


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


TEST_ORIGIN = "http://localhost:3000"


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
async def ordinary_user(api_db):
    async with api_db() as s:
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
async def ordinary_client(api_db, ordinary_user):
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
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
async def ordinary_csrf_headers(ordinary_client):
    resp = await ordinary_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


class TestCreateSession:
    async def test_create_session_returns_enveloped_201(self, admin_client, csrf_headers):
        response = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "test session"},
            headers=csrf_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert "data" in body
        assert "request_id" in body
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["data"]["title"] == "test session"
        assert body["data"]["id"] is not None

    async def test_create_session_without_csrf_fails(self, admin_client):
        response = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "no csrf"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "CSRF_VALIDATION_FAILED"

    async def test_create_session_without_title(self, admin_client, csrf_headers):
        response = await admin_client.post(
            "/api/agent/sessions",
            json={},
            headers=csrf_headers,
        )
        assert response.status_code == 201
        assert response.json()["data"]["title"] is None


class TestListSessions:
    async def test_list_sessions_empty(self, admin_client):
        response = await admin_client.get("/api/agent/sessions")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert body["data"]["items"] == []
        assert body["data"]["page"] == 1
        assert body["data"]["total"] == 0

    async def test_list_sessions_paginates(self, admin_client, csrf_headers):
        for i in range(3):
            resp = await admin_client.post(
                "/api/agent/sessions",
                json={"title": f"session {i}"},
                headers=csrf_headers,
            )
            assert resp.status_code == 201

        response = await admin_client.get("/api/agent/sessions?page=1&page_size=2")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]["items"]) == 2
        assert body["data"]["total"] == 3
        assert body["data"]["page_size"] == 2

    async def test_list_sessions_isolates_between_users(
        self, api_db, admin_client, ordinary_user, ordinary_client, csrf_headers, ordinary_csrf_headers
    ):
        await admin_client.post(
            "/api/agent/sessions",
            json={"title": "admin session"},
            headers=csrf_headers,
        )
        await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "ordinary session"},
            headers=ordinary_csrf_headers,
        )

        admin_resp = await admin_client.get("/api/agent/sessions")
        admin_items = admin_resp.json()["data"]["items"]
        assert len(admin_items) == 1
        assert admin_items[0]["title"] == "admin session"

        ordinary_resp = await ordinary_client.get("/api/agent/sessions")
        ordinary_items = ordinary_resp.json()["data"]["items"]
        assert len(ordinary_items) == 1
        assert ordinary_items[0]["title"] == "ordinary session"


class TestGetSession:
    async def test_get_session_returns_enveloped_data(self, admin_client, csrf_headers):
        create_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "detail session"},
            headers=csrf_headers,
        )
        session_id = create_resp.json()["data"]["id"]

        response = await admin_client.get(f"/api/agent/sessions/{session_id}")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert body["data"]["id"] == session_id
        assert body["data"]["title"] == "detail session"

    async def test_get_session_404_for_other_user(
        self, admin_client, ordinary_user, api_db, csrf_headers
    ):
        create_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "owned session"},
            headers=csrf_headers,
        )
        session_id = create_resp.json()["data"]["id"]

        from httpx import ASGITransport, AsyncClient
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
            username = user.username

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"Origin": TEST_ORIGIN},
        ) as other:
            await other.post(
                "/api/auth/login",
                json={"username": username, "password": "Password123"},
            )
            response = await other.get(f"/api/agent/sessions/{session_id}")
            assert response.status_code == 404

    async def test_get_nonexistent_session_returns_404(self, admin_client):
        fake_id = str(uuid.uuid4())
        response = await admin_client.get(f"/api/agent/sessions/{fake_id}")
        assert response.status_code == 404

    async def test_list_runs_for_owned_session_returns_creation_order(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions", json={"title": "conversation"}, headers=csrf_headers
        )
        session_id = session_resp.json()["data"]["id"]
        for goal in ("first question", "second question"):
            response = await admin_client.post(
                f"/api/agent/sessions/{session_id}/runs",
                json={"goal": goal, "mode": "quick"},
                headers=csrf_headers,
            )
            assert response.status_code == 201

        response = await admin_client.get(f"/api/agent/sessions/{session_id}/runs")

        assert response.status_code == 200
        assert [item["goal"] for item in response.json()["data"]] == [
            "first question",
            "second question",
        ]

    async def test_attempt_steps_return_404_when_attempt_is_not_for_the_owned_run(self, admin_client, csrf_headers):
        create = await admin_client.post("/api/agent/sessions", json={"title": "assoc"}, headers=csrf_headers)
        sid1 = create.json()["data"]["id"]
        create2 = await admin_client.post("/api/agent/sessions", json={"title": "assoc2"}, headers=csrf_headers)
        sid2 = create2.json()["data"]["id"]
        r1 = await admin_client.post(f"/api/agent/sessions/{sid1}/runs", json={"goal": "a", "mode": "quick"}, headers=csrf_headers)
        r2 = await admin_client.post(f"/api/agent/sessions/{sid2}/runs", json={"goal": "b", "mode": "quick"}, headers=csrf_headers)
        attempts2 = await admin_client.get(f"/api/agent/runs/{r2.json()['data']['id']}/attempts")
        attempt_id = attempts2.json()["data"]["items"][0]["id"]
        response = await admin_client.get(f"/api/agent/runs/{r1.json()['data']['id']}/attempts/{attempt_id}/steps")
        assert response.status_code == 404


class TestCreateRun:
    async def test_create_session_and_run_returns_enveloped_owned_resources(
        self, admin_client, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "report"},
            headers=csrf_headers,
        )
        assert session_resp.status_code == 201
        session_id = session_resp.json()["data"]["id"]

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={
                "goal": "summarize data",
                "network_enabled": True,
                "attachment_ids": [],
            },
            headers=csrf_headers,
        )
        assert run_resp.status_code == 201
        body = run_resp.json()
        assert body["data"]["status"] == "queued"
        assert body["data"]["goal"] == "summarize data"
        assert body["data"]["mode"] == "expert"
        assert body["data"]["session_id"] == session_id
        assert "request_id" in body
        assert body["request_id"] == run_resp.headers["X-Request-ID"]

    async def test_create_run_without_csrf_fails(self, admin_client, csrf_headers):
        create_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "test"},
            headers=csrf_headers,
        )
        session_id = create_resp.json()["data"]["id"]

        response = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test goal"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "CSRF_VALIDATION_FAILED"

    async def test_create_run_with_expert_mode(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "expert session"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={
                "goal": "deep analysis",
                "mode": "expert",
                "network_enabled": False,
                "attachment_ids": [],
            },
            headers=csrf_headers,
        )
        assert run_resp.status_code == 201
        assert run_resp.json()["data"]["mode"] == "expert"
        assert run_resp.json()["data"]["network_enabled"] is False

    async def test_create_run_with_empty_goal(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]

        response = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "   ", "mode": "quick"},
            headers=csrf_headers,
        )
        assert response.status_code == 422

    async def test_create_run_on_nonexistent_session(self, admin_client, csrf_headers):
        fake_id = str(uuid.uuid4())
        response = await admin_client.post(
            f"/api/agent/sessions/{fake_id}/runs",
            json={"goal": "test"},
            headers=csrf_headers,
        )
        assert response.status_code == 404

    async def test_create_run_on_foreign_session(
        self, api_db, admin_client, ordinary_user, csrf_headers
    ):
        async with api_db() as s:
            session = AgentSession(owner_user_id=ordinary_user.id, title="foreign")
            s.add(session)
            await s.commit()
            session_id = session.id

        response = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test"},
            headers=csrf_headers,
        )
        assert response.status_code == 404


class TestGetRun:
    async def test_get_run_returns_attempt_summary(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "run detail"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]

        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test goal", "mode": "quick", "network_enabled": True},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["id"] == run_id
        assert body["data"]["status"] == "queued"
        assert "attempts" in body["data"]
        assert len(body["data"]["attempts"]) == 1
        assert body["data"]["attempts"][0]["status"] == "queued"

    async def test_get_run_404_for_other_user(
        self, api_db, admin_client, ordinary_user, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "owned"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "secret", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        from httpx import ASGITransport, AsyncClient
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
            username = user.username

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"Origin": TEST_ORIGIN},
        ) as other:
            await other.post(
                "/api/auth/login",
                json={"username": username, "password": "Password123"},
            )
            response = await other.get(f"/api/agent/runs/{run_id}")
            assert response.status_code == 404

    async def test_get_nonexistent_run_returns_404(self, admin_client):
        fake_id = str(uuid.uuid4())
        response = await admin_client.get(f"/api/agent/runs/{fake_id}")
        assert response.status_code == 404

    async def test_list_current_run_steps_returns_empty_list_before_execution(
        self, admin_client, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions", json={"title": "step list"}, headers=csrf_headers
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "queued run", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.get(f"/api/agent/runs/{run_id}/steps")

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestListAttempts:
    async def test_list_attempts_returns_paginated(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "attempt list"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.get(f"/api/agent/runs/{run_id}/attempts")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["attempt_number"] == 1
        assert body["data"]["total"] == 1

    async def test_list_attempts_404_for_other_user(
        self, api_db, admin_client, ordinary_user, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "owned"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "secret", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

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
            username = user.username

        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"Origin": TEST_ORIGIN},
        ) as other:
            await other.post(
                "/api/auth/login",
                json={"username": username, "password": "Password123"},
            )
            response = await other.get(f"/api/agent/runs/{run_id}/attempts")
            assert response.status_code == 404


class TestListSteps:
    async def test_list_steps_empty(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "steps test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        attempts_resp = await admin_client.get(f"/api/agent/runs/{run_id}/attempts")
        attempt_id = attempts_resp.json()["data"]["items"][0]["id"]

        response = await admin_client.get(
            f"/api/agent/runs/{run_id}/attempts/{attempt_id}/steps"
        )
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0


class TestListEvents:
    async def test_list_events_with_after_seq_cursor(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "events test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.get(f"/api/agent/runs/{run_id}/events")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "items" in body["data"]
        assert len(body["data"]["items"]) >= 1
        assert body["data"]["items"][0]["event_type"] == "run_queued"
        assert "next_seq" in body["data"]

    async def test_list_events_after_seq_empty(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "events test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        first_resp = await admin_client.get(f"/api/agent/runs/{run_id}/events")
        next_seq = first_resp.json()["data"]["next_seq"]

        second_resp = await admin_client.get(
            f"/api/agent/runs/{run_id}/events?after_seq={next_seq}"
        )
        assert second_resp.status_code == 200
        body = second_resp.json()
        assert len(body["data"]["items"]) == 0
        assert body["data"]["next_seq"] is None

    async def test_list_events_404_for_other_user(
        self, api_db, admin_client, ordinary_user, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "owned events"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "secret", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

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
            username = user.username

        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"Origin": TEST_ORIGIN},
        ) as other:
            await other.post(
                "/api/auth/login",
                json={"username": username, "password": "Password123"},
            )
            response = await other.get(f"/api/agent/runs/{run_id}/events")
            assert response.status_code == 404


class TestCancelRun:
    async def test_cancel_queued_run(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "cancel test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        cancel_resp = await admin_client.post(
            f"/api/agent/runs/{run_id}/cancel",
            headers=csrf_headers,
        )
        assert cancel_resp.status_code == 200
        body = cancel_resp.json()
        assert body["data"]["status"] == "cancelled"
        assert "request_id" in body

    async def test_cancel_without_csrf_fails(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.post(f"/api/agent/runs/{run_id}/cancel")
        assert response.status_code == 403

    async def test_cannot_cancel_terminal_run(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "terminal cancel"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        async with api_db() as s:
            run = await s.get(AgentRun, uuid.UUID(run_id))
            run.status = "succeeded"
            await s.commit()

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/cancel",
            headers=csrf_headers,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_TRANSITION"


class TestRetryRun:
    async def test_retry_terminal_run(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "retry test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        async with api_db() as s:
            run = await s.get(AgentRun, uuid.UUID(run_id))
            run.status = "succeeded"
            await s.commit()

        retry_resp = await admin_client.post(
            f"/api/agent/runs/{run_id}/retry",
            headers=csrf_headers,
        )
        assert retry_resp.status_code == 201
        body = retry_resp.json()
        assert body["data"]["status"] == "queued"
        assert "request_id" in body

    async def test_retry_without_csrf_fails(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        async with api_db() as s:
            run = await s.get(AgentRun, uuid.UUID(run_id))
            run.status = "succeeded"
            await s.commit()

        response = await admin_client.post(f"/api/agent/runs/{run_id}/retry")
        assert response.status_code == 403

    async def test_cannot_retry_nonterminal_run(self, admin_client, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "nonterminal retry"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/retry",
            headers=csrf_headers,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_TRANSITION"

    async def test_retry_creates_new_attempt(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "retry attempts"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        async with api_db() as s:
            run = await s.get(AgentRun, uuid.UUID(run_id))
            run.status = "succeeded"
            await s.commit()

        await admin_client.post(
            f"/api/agent/runs/{run_id}/retry",
            headers=csrf_headers,
        )

        attempts_resp = await admin_client.get(f"/api/agent/runs/{run_id}/attempts")
        assert attempts_resp.json()["data"]["total"] == 2


class TestTerminalEvidence:
    async def test_run_response_labels_answer_completed_as_terminal_evidence(
        self, admin_client, api_db, csrf_headers
    ):
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "terminal evidence"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "answer completed test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "answer_completed",
                {"text": "This is the final answer", "stream_id": "stream-1"},
            )
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "running"
        assert data["terminal_evidence"] == "answer_completed_event"

    async def test_run_response_labels_persisted_terminal_status(
        self, admin_client, api_db, csrf_headers
    ):
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "persisted terminal"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "succeeded run", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "run_succeeded",
                {"final_answer": "done"},
            )
            await repo.mark_run_succeeded(run)
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "succeeded"
        assert data["terminal_evidence"] == "persisted_terminal"

    async def test_run_response_returns_none_when_no_events(
        self, admin_client, api_db, csrf_headers
    ):
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "no events"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "queued run", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["terminal_evidence"] == "none"

    async def test_run_response_returns_run_succeeded_event_evidence(
        self, admin_client, api_db, csrf_headers
    ):
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "run succeeded event"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "run succeeded but still running", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "run_succeeded",
                {"final_answer": "done"},
            )
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "running"
        assert data["terminal_evidence"] == "run_succeeded_event"

    async def test_session_runs_list_includes_terminal_evidence(
        self, admin_client, api_db, csrf_headers
    ):
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "list evidence"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "list test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "answer_completed",
                {"text": "list answer", "stream_id": "s1"},
            )
            await s.commit()

        response = await admin_client.get(f"/api/agent/sessions/{session_id}/runs")
        assert response.status_code == 200
        runs = response.json()["data"]
        assert len(runs) == 1
        assert runs[0]["status"] == "running"
        assert runs[0]["terminal_evidence"] == "answer_completed_event"


class TestRunResult:
    async def test_get_run_has_result_when_succeeded(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post("/api/agent/sessions", json={"title": "result test"}, headers=csrf_headers)
        sid = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(f"/api/agent/sessions/{sid}/runs", json={"goal": "result", "mode": "quick"}, headers=csrf_headers)
        rid = run_resp.json()["data"]["id"]

        from app.repositories.agent_repository import AgentRepository
        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, uuid.UUID(rid))
            run.status = "running"
            await repo.append_event(run, None, "run_succeeded", {"final_answer": "test answer"})
            await repo.mark_run_succeeded(run)
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{rid}")
        assert response.json()["data"].get("result") is not None

    async def test_session_runs_includes_result_field(self, admin_client, api_db, csrf_headers):
        session_resp = await admin_client.post("/api/agent/sessions", json={"title": "result s2"}, headers=csrf_headers)
        sid = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(f"/api/agent/sessions/{sid}/runs", json={"goal": "hi", "mode": "quick"}, headers=csrf_headers)
        rid = run_resp.json()["data"]["id"]

        from app.repositories.agent_repository import AgentRepository
        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, uuid.UUID(rid))
            run.status = "running"
            await repo.append_event(run, None, "run_succeeded", {"final_answer": "hi answer"})
            await repo.mark_run_succeeded(run)
            await s.commit()

        runs = await admin_client.get(f"/api/agent/sessions/{sid}/runs")
        assert "result" in runs.json()["data"][0]


class TestGetRunSteps:
    async def test_steps_endpoint_returns_structured_observation(self, admin_client, csrf_headers):
        session_resp = await admin_client.post("/api/agent/sessions", json={"title": "obs test"}, headers=csrf_headers)
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick", "network_enabled": True},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]
        response = await admin_client.get(f"/api/agent/runs/{run_id}/steps")
        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_steps_with_json_observation_serializes_correctly(self, admin_client, api_db, csrf_headers):
        from app.repositories.agent_repository import AgentRepository

        session_resp = await admin_client.post("/api/agent/sessions", json={"title": "json obs"}, headers=csrf_headers)
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = uuid.UUID(run_resp.json()["data"]["id"])

        async with api_db() as s:
            repo = AgentRepository(s)
            atts = await repo.list_attempts(run_id)
            step = await repo.add_step(atts[0].id, 0, "test", "finish", {}, {"final_answer": "你好"}, "success")
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}/steps")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["observation"] == {"final_answer": "你好"}


class TestAuditTranscript:
    @pytest.fixture
    async def foreign_session(self, api_db, ordinary_user):
        from datetime import UTC, datetime
        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            session = AgentSession(owner_user_id=ordinary_user.id, title="Foreign Session")
            s.add(session)
            await s.flush()

            run, attempt, event = await repo.create_run_with_attempt(
                session, "test goal", True, [], "quick"
            )

            run.status = "running"
            await repo.append_event(run, attempt, "run_succeeded", {"final_answer": "secret answer"})
            run.result = {
                "final_answer": "secret answer",
                "answer_format": "markdown",
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "source_event_sequence": None,
            }
            await repo.mark_run_succeeded(run)

            await repo.add_step(
                attempt.id, 1, "test thought", "finish", {},
                {"final_answer": "secret answer"}, "success"
            )

            await s.commit()
            return session

    async def test_super_admin_reads_other_users_transcript(self, admin_client, foreign_session):
        response = await admin_client.get(
            f"/api/agent/audit/sessions/{foreign_session.id}/transcript"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["owner"]["display_name"]
        assert data["turns"][0]["run"]["session_id"] == str(foreign_session.id)
        assert data["turns"][0]["run"]["result"]["final_answer"] == "secret answer"

    async def test_ordinary_user_cannot_read_audit_transcript(
        self, ordinary_client, foreign_session
    ):
        response = await ordinary_client.get(
            f"/api/agent/audit/sessions/{foreign_session.id}/transcript"
        )
        assert response.status_code == 403

    async def test_audit_transcript_redacts_sensitive_events(self, admin_client, api_db, ordinary_user):
        from datetime import UTC, datetime
        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            session = AgentSession(owner_user_id=ordinary_user.id, title="Sensitive Session")
            s.add(session)
            await s.flush()

            run, attempt, event = await repo.create_run_with_attempt(
                session, "sensitive goal", True, [], "quick"
            )
            run.status = "running"
            await repo.append_event(run, attempt, "tool_call", {
                "tool": "search",
                "authorization": "Bearer secret-token",
                "api_key": "sk-12345",
                "token": "secret-jwt",
                "safe_field": "visible",
            })
            run.result = {"final_answer": "safe result"}
            await repo.mark_run_succeeded(run)
            await s.commit()
            session_id = session.id

        response = await admin_client.get(
            f"/api/agent/audit/sessions/{session_id}/transcript"
        )
        assert response.status_code == 200
        data = response.json()["data"]

        events = data["turns"][0]["events"]
        tool_call_event = next((e for e in events if e["event_type"] == "tool_call"), None)
        assert tool_call_event is not None
        assert tool_call_event["payload"]["authorization"] == "[REDACTED]"
        assert tool_call_event["payload"]["api_key"] == "[REDACTED]"
        assert tool_call_event["payload"]["token"] == "[REDACTED]"
        assert tool_call_event["payload"]["safe_field"] == "visible"

    async def test_audit_transcript_returns_404_for_nonexistent_session(self, admin_client):
        fake_id = str(uuid.uuid4())
        response = await admin_client.get(
            f"/api/agent/audit/sessions/{fake_id}/transcript"
        )
        assert response.status_code == 404

    async def test_audit_transcript_returns_owner_roles(self, admin_client, foreign_session):
        response = await admin_client.get(
            f"/api/agent/audit/sessions/{foreign_session.id}/transcript"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        owner = data["owner"]
        assert "roles" in owner
        assert isinstance(owner["roles"], list)


class TestPhase1ResultColumnMissing:
    """Phase 2 green tests — AgentRun now has a ``result`` column."""

    async def test_be_d01_transaction_atomicity_result_missing(
        self, admin_client, api_db, csrf_headers
    ):
        """BE-D-01: Verify that status, result, and terminal event are
        atomically persisted to the ``result`` column.  GREEN now that
        the ORM column exists and can be set.
        """
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "be-d01"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "atomicity test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from datetime import UTC, datetime

        from app.repositories.agent_repository import AgentRepository

        now = datetime.now(UTC)
        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "run_succeeded",
                {"final_answer": "atomic answer"},
            )
            run.result = {
                "final_answer": "atomic answer",
                "answer_format": "markdown",
                "completed_at": now.isoformat().replace("+00:00", "Z"),
                "source_event_sequence": None,
            }
            await repo.mark_run_succeeded(run)
            await s.commit()

        async with api_db() as s:
            fresh = await s.get(AgentRun, run_id)

        assert fresh.status == "succeeded"
        persisted_result = getattr(fresh, "result", None)
        assert persisted_result is not None, (
            "BE-D-01 FAIL: AgentRun.result is None — "
            "result should be atomically persisted alongside status and event"
        )
        assert isinstance(persisted_result, dict)
        assert persisted_result["final_answer"] == "atomic answer"

    async def test_be_a01_stable_answer_from_persisted_result(
        self, admin_client, api_db, csrf_headers
    ):
        """BE-A-01: GET run returns ``result.final_answer`` from the
        persisted column (not reconstructed from events).  GREEN now
        that ``AgentRun.result`` is an ORM-mapped column.
        """
        import uuid as _uuid

        from datetime import UTC, datetime

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "be-a01"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "persist test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        now = datetime.now(UTC)
        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "run_succeeded",
                {"final_answer": "persisted answer"},
            )
            run.result = {
                "final_answer": "persisted answer",
                "answer_format": "markdown",
                "completed_at": now.isoformat().replace("+00:00", "Z"),
                "source_event_sequence": None,
            }
            await repo.mark_run_succeeded(run)
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["data"].get("result") is not None, (
            "BE-A-01 FAIL (response): response missing result key entirely"
        )
        assert body["data"]["result"].get("final_answer") == "persisted answer"

        async with api_db() as s:
            fresh = await s.get(AgentRun, run_id)
            persisted_result = getattr(fresh, "result", None)
            assert persisted_result is not None, (
                "BE-A-01 FAIL (column): AgentRun.result is None — "
                "response should be from persisted column, not events"
            )
            assert isinstance(persisted_result, dict)
            assert persisted_result["final_answer"] == "persisted answer"

    async def test_be_a02_fallback_does_not_silently_swallow_errors(
        self, caplog,
    ):
        """BE-A-02: ``_populate_run_result`` logs errors with structured
        logging instead of silently swallowing via ``except Exception: pass``.
        """
        import logging
        from unittest.mock import AsyncMock

        from app.api.agent import _populate_run_result

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        run_response = {"id": "00000000-0000-0000-0000-000000000001"}

        with caplog.at_level(logging.WARNING, logger="app.api.agent"):
            result = await _populate_run_result(fake_db, run_response)

        assert result == run_response, (
            "BE-A-02 FAIL: _populate_run_result should return the "
            "unmodified run_response on error"
        )
        assert len(caplog.records) >= 1, (
            "BE-A-02 FAIL: no warning logged — error was silently swallowed"
        )
        assert "Failed to populate result from events" in caplog.text, (
            "BE-A-02 FAIL: expected warning log for failed result population"
        )

    async def test_be_a02_fallback_works_with_events_when_no_result_column(
        self, admin_client, api_db, csrf_headers
    ):
        """BE-A-02b: Confirm that the fallback path (reading from events)
        currently works even without a result column — but this should
        eventually be replaced by direct column reads.
        """
        import uuid as _uuid

        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "be-a02b"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "fallback test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = _uuid.UUID(run_resp.json()["data"]["id"])

        from app.repositories.agent_repository import AgentRepository

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await s.get(AgentRun, run_id)
            run.status = "running"
            await repo.append_event(
                run, None, "run_succeeded",
                {"final_answer": "fallback answer"},
            )
            await repo.mark_run_succeeded(run)
            await s.commit()

        response = await admin_client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["data"].get("result") is not None, (
            "BE-A-02b FAIL: even event-based fallback returned no result"
        )
        assert body["data"]["result"]["final_answer"] == "fallback answer"


class TestAnswerPendingQuestions:
    """Task 4: POST /runs/{run_id}/answer resumes an awaiting_question run."""

    async def _make_awaiting_run(self, admin_client, api_db, csrf_headers) -> uuid.UUID:
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "answer test"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = uuid.UUID(run_resp.json()["data"]["id"])

        async with api_db() as s:
            run = await s.get(AgentRun, run_id)
            run.status = "awaiting_question"
            run.pending_questions = [
                {"question": "本次方案的预算级别是多少？", "affects": "达人矩阵"},
            ]
            await s.commit()
        return run_id

    async def test_answer_pending_questions_resumes_run(
        self, admin_client, api_db, csrf_headers
    ):
        from sqlalchemy import select

        from app.repositories.agent_repository import AgentRepository

        run_id = await self._make_awaiting_run(admin_client, api_db, csrf_headers)

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/answer",
            json={"answers": {"预算级别": "50万"}},
            headers=csrf_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "queued"
        assert "request_id" in body

        async with api_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "queued"
            assert run.pending_questions is None
            assert run.result is not None
            assert run.result["answers"] == {"预算级别": "50万"}
            assert run.result["resumed_after_question"] is True

            attempts = list(
                (
                    await s.execute(
                        select(AgentRunAttempt)
                        .where(AgentRunAttempt.run_id == run_id)
                        .order_by(AgentRunAttempt.attempt_number)
                    )
                ).scalars().all()
            )
            assert len(attempts) == 2, f"expected 2 attempts, got {len(attempts)}"
            assert attempts[-1].attempt_number == 2
            assert attempts[-1].status == "queued"
            assert run.current_attempt_id == attempts[-1].id

            events = await repo.list_events(run_id)
            event_types = [e.event_type for e in events]
            assert "run_resumed" in event_types, (
                f"run_resumed missing from {event_types}"
            )

    async def test_answer_not_awaiting_returns_404(
        self, admin_client, api_db, csrf_headers
    ):
        session_resp = await admin_client.post(
            "/api/agent/sessions",
            json={"title": "answer 404"},
            headers=csrf_headers,
        )
        session_id = session_resp.json()["data"]["id"]
        run_resp = await admin_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "test", "mode": "quick"},
            headers=csrf_headers,
        )
        run_id = run_resp.json()["data"]["id"]

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/answer",
            json={"answers": {"预算级别": "50万"}},
            headers=csrf_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "RUN_NOT_AWAITING_QUESTION"

    async def test_answer_missing_pending_questions_returns_404(
        self, admin_client, api_db, csrf_headers
    ):
        run_id = await self._make_awaiting_run(admin_client, api_db, csrf_headers)

        async with api_db() as s:
            run = await s.get(AgentRun, run_id)
            run.pending_questions = None
            await s.commit()

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/answer",
            json={"answers": {"预算级别": "50万"}},
            headers=csrf_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "RUN_NOT_AWAITING_QUESTION"

    async def test_answer_invalid_body_returns_422(
        self, admin_client, api_db, csrf_headers
    ):
        run_id = await self._make_awaiting_run(admin_client, api_db, csrf_headers)

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/answer",
            json={"answers": "not-a-dict"},
            headers=csrf_headers,
        )
        assert response.status_code == 422

    async def test_answer_without_csrf_fails(
        self, admin_client, api_db, csrf_headers
    ):
        run_id = await self._make_awaiting_run(admin_client, api_db, csrf_headers)

        response = await admin_client.post(
            f"/api/agent/runs/{run_id}/answer",
            json={"answers": {"预算级别": "50万"}},
        )
        assert response.status_code == 403


class TestPlatformNotesApi:
    @staticmethod
    async def _owner_id(api_db):
        from sqlalchemy import select

        from app.models.rbac import User

        async with api_db() as s:
            return (
                await s.execute(
                    select(User.id).where(
                        User.username == settings.initial_admin_username
                    )
                )
            ).scalar_one()

    async def test_list_platform_notes_owner_isolated(
        self, admin_client, ordinary_client, api_db
    ):
        from app.repositories.platform_note_repository import upsert

        owner = await self._owner_id(api_db)
        async with api_db() as s:
            assert await upsert(
                s,
                owner,
                "xiaohongshu",
                "成毅",
                {
                    "title": "笔记A",
                    "url": "https://www.xiaohongshu.com/explore/na1",
                    "content": "正文内容很长" * 50,
                },
            )
            await s.commit()

        resp = await ordinary_client.get("/api/agent/platform-notes")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_platform_notes_filters_and_truncates(
        self, admin_client, api_db
    ):
        from app.repositories.platform_note_repository import upsert

        owner = await self._owner_id(api_db)
        async with api_db() as s:
            await upsert(
                s,
                owner,
                "xiaohongshu",
                "成毅",
                {"title": "笔记B", "url": "https://www.xiaohongshu.com/explore/nb1"},
            )
            await upsert(
                s,
                owner,
                "douyin",
                "成毅",
                {"title": "视频C", "url": "https://www.douyin.com/video/9"},
            )
            await s.commit()

        resp = await admin_client.get("/api/agent/platform-notes?platform=xiaohongshu")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] == 1
        assert body["items"][0]["title"] == "笔记B"

        resp2 = await admin_client.get("/api/agent/platform-notes?keyword=不存在词")
        assert resp2.json()["data"]["total"] == 0

        async with api_db() as s:
            await upsert(
                s,
                owner,
                "xiaohongshu",
                "长文",
                {
                    "title": "长文笔记",
                    "url": "https://www.xiaohongshu.com/explore/nc1",
                    "content": "长" * 800,
                },
            )
            await s.commit()
        resp3 = await admin_client.get("/api/agent/platform-notes?platform=xiaohongshu")
        items3 = resp3.json()["data"]["items"]
        long_item = next((i for i in items3 if i["title"] == "长文笔记"), None)
        assert long_item is not None
        assert len(long_item["content"]) == 500

    async def test_list_platform_notes_requires_auth(self, api_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            response = await ac.get("/api/agent/platform-notes")
            assert response.status_code == 401
