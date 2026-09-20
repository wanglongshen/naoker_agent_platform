import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base


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


async def test_health_returns_generated_request_id(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


async def test_error_returns_forwarded_request_id(client) -> None:
    response = await client.get("/api/users", headers={"X-Request-ID": "manual-request"})
    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "manual-request"
    assert response.json()["request_id"] == "manual-request"
