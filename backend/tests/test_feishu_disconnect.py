import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.feishu_token import FeishuToken
from app.services.feishu.crypto import derive_token_key, encrypt_token


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _insert_token(test_engine, owner: uuid.UUID) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    key = derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)
    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        s.add(
            FeishuToken(
                owner_user_id=owner,
                access_token=encrypt_token("fake_access_token", key),
                refresh_token=encrypt_token("fake_refresh_token", key),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
                open_id="ou_fake123",
            )
        )
        await s.commit()


async def _first_user(test_engine) -> uuid.UUID:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        return owner.id


@pytest.mark.asyncio
async def test_disconnect_removes_token_and_updates_status(admin_client, test_engine, monkeypatch) -> None:
    from app.services.feishu import client as feishu_client

    owner_id = await _first_user(test_engine)
    await _insert_token(test_engine, owner_id)

    monkeypatch.setattr(feishu_client.FeishuClient, "revoke_token", lambda self, token: None)

    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False

    status = await admin_client.get("/api/feishu/status")
    assert status.json()["data"]["connected"] is False


@pytest.mark.asyncio
async def test_disconnect_without_token_is_idempotent(admin_client, test_engine) -> None:
    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False


@pytest.mark.asyncio
async def test_disconnect_removes_local_token_when_revoke_fails(admin_client, test_engine, monkeypatch) -> None:
    from app.services.feishu import client as feishu_client

    owner_id = await _first_user(test_engine)
    await _insert_token(test_engine, owner_id)

    def _boom(self, token):
        raise RuntimeError("feishu down")

    monkeypatch.setattr(feishu_client.FeishuClient, "revoke_token", _boom)

    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    status = await admin_client.get("/api/feishu/status")
    assert status.json()["data"]["connected"] is False
