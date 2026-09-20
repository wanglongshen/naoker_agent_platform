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


async def test_missing_user_returns_chinese_message(admin_client) -> None:
    response = await admin_client.delete("/api/users/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"
    assert response.json()["message"] == "用户不存在"


async def test_openapi_metadata_and_tags_are_chinese(client) -> None:
    response = await client.get("/openapi.json")
    schema = response.json()
    assert schema["info"]["title"] == "权限管理系统 API"
    assert {tag["name"] for tag in schema["tags"]} >= {"认证管理", "用户管理", "角色管理", "权限管理"}
