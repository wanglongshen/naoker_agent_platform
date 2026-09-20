import io

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
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
async def no_permission_client(client, test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="nobody",
            display_name="No Permission",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "Password123"},
    )
    return client


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049"
        "454e44ae426082"
    )


async def _make_user(session, username: str) -> object:
    from app.models.rbac import User

    user = User(
        username=username,
        display_name=username,
        password_hash=hash_password("Password123"),
        status="active",
    )
    session.add(user)
    await session.flush()
    await session.commit()
    return user


async def test_upload_own_avatar_success(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["avatar_url"] is not None
    assert body["avatar_url"].startswith("/api/avatars/")


async def test_upload_rejects_non_image(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "AVATAR_INVALID_TYPE"


async def test_upload_rejects_spoofed_content_type(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(b"not an image"), "image/png")},
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversize(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (20 * 1024 * 1024 + 2)), "image/png")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "AVATAR_TOO_LARGE"


async def test_upload_accepts_image_larger_than_2mb(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["avatar_url"] is not None


async def test_upload_requires_auth(client) -> None:
    resp = await client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 401


async def test_clear_own_avatar(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200
    resp = await admin_client.delete("/api/avatars/me")
    assert resp.status_code == 200
    assert resp.json()["data"]["avatar_url"] is None


async def test_get_avatar_returns_image(admin_client, session) -> None:
    from sqlalchemy import select
    from app.models.rbac import User

    await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    admin = await session.scalar(select(User).where(User.username == "admin"))
    resp = await admin_client.get(f"/api/avatars/{admin.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content.startswith(b"\x89PNG")


async def test_get_avatar_without_avatar_404(admin_client, session) -> None:
    from sqlalchemy import select
    from app.models.rbac import User

    admin = await session.scalar(select(User).where(User.username == "admin"))
    resp = await admin_client.get(f"/api/avatars/{admin.id}")
    assert resp.status_code == 404


async def test_admin_can_set_avatar_for_other_user(admin_client, session) -> None:
    target = await _make_user(session, "avatar_target")
    resp = await admin_client.post(
        f"/api/avatars/{target.id}",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200, resp.text


async def test_normal_user_cannot_set_avatar_for_other(session, no_permission_client) -> None:
    target = await _make_user(session, "avatar_target2")
    resp = await no_permission_client.post(
        f"/api/avatars/{target.id}",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 403
