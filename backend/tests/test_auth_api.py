import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.rbac import User

settings = get_settings()


@pytest.fixture
async def client(test_engine):
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def disabled_user(client, test_engine):
    from argon2 import PasswordHasher

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    ph = PasswordHasher()
    user = User(
        username="disabled1",
        display_name="Disabled User",
        password_hash=ph.hash("Password123"),
        status="disabled",
    )

    async with async_session_factory() as s:
        s.add(user)
        await s.commit()

    return user


@pytest.fixture
async def admin_client(client):
    response = await client.post(
        "/api/auth/login",
        json={"username": settings.initial_admin_username, "password": settings.initial_admin_password},
    )
    assert response.status_code == 200
    return client


async def test_login_sets_httponly_cookie_and_me_returns_permissions(client) -> None:
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe-Strong1"})
    assert response.status_code == 200
    assert "access_token" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    data = me.json()["data"]
    assert "user:assign_role" in data["permissions"]
    assert len(data["assignable_roles"]) == 4
    assert any(role["code"] == "super_admin" for role in data["assignable_roles"])


async def test_me_returns_role_summaries_and_menu_permissions(admin_client) -> None:
    response = await admin_client.get("/api/auth/me")
    body = response.json()["data"]
    assert body["roles"][0].keys() >= {"id", "code", "name"}
    assert body["menu_permissions"] == body["permissions"]


async def test_disabled_user_cannot_login(client, disabled_user) -> None:
    response = await client.post("/api/auth/login", json={"username": disabled_user.username, "password": "Password123"})
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_super_admin_me_lists_super_admin_role_as_assignable(client) -> None:
    await client.post(
        "/api/auth/login",
        json={
            "username": settings.initial_admin_username,
            "password": settings.initial_admin_password,
        },
    )
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    codes = [r["code"] for r in response.json()["data"]["assignable_roles"]]
    assert "super_admin" in codes


async def test_user_manager_me_excludes_super_admin_from_assignable(client, test_engine) -> None:
    from argon2 import PasswordHasher
    from sqlalchemy import select

    from app.models.rbac import Role, User, UserRole

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        mgr = User(
            username="mgr_me",
            display_name="Manager Me",
            password_hash=ph.hash("Password123"),
        )
        s.add(mgr)
        await s.flush()
        manager_role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        s.add(UserRole(user_id=mgr.id, role_id=manager_role.id))
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "mgr_me", "password": "Password123"},
    )

    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert "user:assign_role" in response.json()["data"]["permissions"]
    codes = [r["code"] for r in response.json()["data"]["assignable_roles"]]
    assert "super_admin" not in codes


async def test_me_includes_avatar_url(admin_client) -> None:
    resp = await admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "avatar_url" in body
