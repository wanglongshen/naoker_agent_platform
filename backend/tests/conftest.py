import asyncio
import sys
from urllib.parse import urlparse, urlunparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.rbac import Permission, Role, RolePermission, User, UserRole  # noqa: F401
from app.models.agent import (  # noqa: F401
    AgentAttachment,
    AgentRetentionJob,
    AgentRun,
    AgentRunAttachment,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
    AgentStep,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"

test_database_url = settings.test_database_url or settings.database_url

parsed = urlparse(test_database_url)
db_name = parsed.path.lstrip("/")
parsed_postgres = parsed._replace(path="/postgres")
postgres_url = urlunparse(parsed_postgres)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_engine():
    postgres_engine = create_async_engine(
        postgres_url, echo=False, isolation_level="AUTOCOMMIT"
    )
    try:
        async with postgres_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": db_name}
            )
            if result.fetchone() is None:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await postgres_engine.dispose()

    engine = create_async_engine(test_database_url, echo=False)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as s:
        async with s.begin():
            yield s
            await s.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def test_db(test_engine):
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
async def seeded_user(session):
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    user = User(
        username="test_agent_user",
        display_name="Test Agent User",
        password_hash=ph.hash("Test1234"),
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def admin_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Origin": TEST_ORIGIN}
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": settings.initial_admin_username, "password": settings.initial_admin_password},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def admin_csrf(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    return {"X-CSRF-Token": resp.json()["data"]["token"]}
