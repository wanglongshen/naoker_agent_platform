import uuid
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.dsh import DshInstance, DshSession
from app.models.rbac import User

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def api_db(test_engine):
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
async def user_a(api_db):
    async with api_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"dsh_a_{uuid.uuid4().hex[:8]}",
            display_name="DSH User A",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def user_b(api_db):
    async with api_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"dsh_b_{uuid.uuid4().hex[:8]}",
            display_name="DSH User B",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


async def _login(user, password="Password123"):
    transport = ASGITransport(app=app)
    ac = AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    )
    response = await ac.post(
        "/api/auth/login",
        json={"username": user.username, "password": password},
    )
    assert response.status_code == 200
    return ac


@pytest.fixture
async def client_a(api_db, user_a):
    ac = await _login(user_a)
    yield ac
    await ac.aclose()


@pytest.fixture
async def client_b(api_db, user_b):
    ac = await _login(user_b)
    yield ac
    await ac.aclose()


def _seed_session(user_id, sess_id, title, turns, when=None):
    now = when or datetime.now(UTC)
    return DshSession(
        user_id=user_id,
        dsh_session_id=sess_id,
        title=title,
        turn_count=turns,
        last_activity_at=now,
        synced_at=now,
    )


class StubManager:
    """免真实 spawn 的 get_manager 替代品，记录调用并返回内存态。"""

    def __init__(self):
        self.stop_calls: list[uuid.UUID] = []
        self.ensure_calls: list[uuid.UUID] = []

    async def get(self, user_id, db):
        return (
            await db.execute(
                select(DshInstance).where(DshInstance.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def check_alive(self, user_id, db):
        return await self.get(user_id, db)

    async def stop(self, user_id, db):
        self.stop_calls.append(user_id)
        return None

    async def ensure_running(self, user_id, db):
        self.ensure_calls.append(user_id)
        return DshInstance(
            id=uuid.uuid4(),
            user_id=user_id,
            port=3210,
            state="running",
            pid=4242,
            last_active_at=datetime.now(UTC),
            error_hint=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


@pytest.fixture
def stub_manager(api_db):
    from app.services.dsh import get_manager as real_get_manager

    stub = StubManager()
    app.dependency_overrides[real_get_manager] = lambda: stub
    yield stub
    app.dependency_overrides.pop(real_get_manager, None)


async def test_sessions_requires_login(api_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/dsh/sessions")
    assert response.status_code == 401


async def test_sessions_list_only_own(api_db, client_a, client_b, user_a, user_b):
    async with api_db() as s:
        s.add_all([
            _seed_session(user_a.id, "s-a-1", "A1", 2),
            _seed_session(user_a.id, "s-a-2", "A2", 5),
            _seed_session(user_b.id, "s-b-1", "B1", 1),
        ])
        await s.commit()

    response = await client_a.get("/api/dsh/sessions")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    ids = {item["dsh_session_id"] for item in data["items"]}
    assert ids == {"s-a-1", "s-a-2"}
    row = next(i for i in data["items"] if i["dsh_session_id"] == "s-a-1")
    assert row["title"] == "A1"
    assert row["turn_count"] == 2
    assert row["last_activity_at"] is not None
    assert row["synced_at"] is not None


async def test_sessions_pagination(api_db, client_a, user_a):
    async with api_db() as s:
        s.add_all([
            _seed_session(user_a.id, "s-a-1", "A1", 1),
            _seed_session(user_a.id, "s-a-2", "A2", 2),
        ])
        await s.commit()

    response = await client_a.get("/api/dsh/sessions", params={"page": 1, "page_size": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 1
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 1

    response = await client_a.get("/api/dsh/sessions", params={"page_size": 101})
    assert response.status_code == 422


async def test_audit_admin_sees_all_across_users(api_db, admin_client, user_a, user_b):
    async with api_db() as s:
        s.add_all([
            _seed_session(user_a.id, "s-a-1", "A1", 2),
            _seed_session(user_b.id, "s-b-1", "B1", 3),
        ])
        await s.commit()

    response = await admin_client.get("/api/dsh/sessions/audit")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert {i["dsh_session_id"] for i in data["items"]} == {"s-a-1", "s-b-1"}

    response = await admin_client.get(
        "/api/dsh/sessions/audit", params={"user_id": str(user_b.id)}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["dsh_session_id"] == "s-b-1"
    assert data["items"][0]["user_id"] == str(user_b.id)


async def test_audit_items_include_owner_username_and_display_name(
    api_db, admin_client, user_a, user_b
):
    async with api_db() as s:
        s.add_all([
            _seed_session(user_a.id, "s-a-1", "A1", 2),
            _seed_session(user_b.id, "s-b-1", "B1", 3),
        ])
        await s.commit()

    response = await admin_client.get("/api/dsh/sessions/audit")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 2

    expected = {
        str(user_a.id): (user_a.username, user_a.display_name),
        str(user_b.id): (user_b.username, user_b.display_name),
    }
    for item in items:
        username, display_name = expected[item["user_id"]]
        assert item.get("username") == username
        assert item.get("display_name") == display_name


async def test_audit_ordinary_forbidden_even_with_user_id(
    api_db, client_a, user_a, user_b
):
    async with api_db() as s:
        s.add_all([
            _seed_session(user_a.id, "s-a-1", "A1", 2),
            _seed_session(user_b.id, "s-b-1", "B1", 3),
        ])
        await s.commit()

    response = await client_a.get("/api/dsh/sessions/audit")
    assert response.status_code == 403
    response = await client_a.get(
        "/api/dsh/sessions/audit", params={"user_id": str(user_b.id)}
    )
    assert response.status_code == 403


async def test_instances_me_running(api_db, client_a, user_a, stub_manager):
    async with api_db() as s:
        s.add(DshInstance(
            user_id=user_a.id, port=3121, state="running", pid=7777,
        ))
        await s.commit()

    response = await client_a.get("/api/dsh/instances/me")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "running"
    assert data["port"] == 3121
    assert data["pid"] == 7777


async def test_instances_me_stopped_when_missing(api_db, client_a, stub_manager):
    response = await client_a.get("/api/dsh/instances/me")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "stopped"
    assert data["port"] is None


async def test_instances_restart_calls_manager(
    api_db, client_a, user_a, stub_manager
):
    csrf = await client_a.get("/api/auth/csrf")
    assert csrf.status_code == 200
    headers = {"X-CSRF-Token": csrf.json()["data"]["token"]}
    response = await client_a.post(
        "/api/dsh/instances/me/restart", headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "running"
    assert data["port"] == 3210
    assert stub_manager.stop_calls == [user_a.id]
    assert stub_manager.ensure_calls == [user_a.id]
